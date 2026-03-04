"""
Flip.kz market adapter.

Scrapes product prices from flip.kz. The site is server-rendered HTML,
so all data is fetched via plain HTTPS requests without a browser.

Category discovery:
    GET /catalog  -> parse div.category-list a[href*="subsection="]

Product listing:
    GET /catalog?subsection={id}           (page 1)
    GET /catalog?subsection={id}&page={N}  (subsequent pages)

Product card structure:
    a.product[href*="/catalog?prod="]  -> card anchor
      div.title                        -> product name
      div.price > span:first           -> current price (e.g. "1 926 ₸")
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from ..core.models import CategoryInfo, PriceObservation
from .base import BaseMarket

logger = logging.getLogger("price_tracker.flip")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_URL = "https://flip.kz"

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

# Price: "1 926 ₸" — may use regular space, NBSP (\xa0), or narrow NBSP (\u202f)
PRICE_RE = re.compile(r"([\d\s\xa0\u202f]+)\s*₸")

# ---------------------------------------------------------------------------
# Static helpers
# ---------------------------------------------------------------------------


def _to_int_price(s: str) -> int:
    """Strip all whitespace variants from price string and return int."""
    return int(re.sub(r"[\s\xa0\u202f]+", "", s))


def _make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "ru-RU,ru;q=0.9",
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
    })
    return s


def _extract_subsection_id(url: str) -> Optional[str]:
    ids = parse_qs(urlparse(url).query).get("subsection", [])
    return ids[0] if ids else None


def _detect_max_pages(soup: BeautifulSoup) -> int:
    max_page = 1
    for a in soup.select("a[href*='page=']"):
        m = re.search(r"page=(\d+)", a.get("href", ""))
        if m:
            max_page = max(max_page, int(m.group(1)))
    return max_page


# ---------------------------------------------------------------------------
# FlipMarket adapter
# ---------------------------------------------------------------------------


class FlipMarket(BaseMarket):
    """
    Flip.kz price scraper — uses plain HTTP requests.

    The Playwright browser passed by the runner is accepted but not used;
    all data is retrieved via requests over HTTPS.
    """

    @property
    def market_name(self) -> str:
        return "flip"

    @property
    def supported_cities(self) -> List[str]:
        # Flip.kz has no city-based routing; single national catalog
        return ["almaty"]

    # -- Category discovery -------------------------------------------------

    def discover_categories(self, city: str) -> List[CategoryInfo]:
        """Fetch the catalog page and extract all category links."""
        catalog_url = f"{BASE_URL}/catalog"
        logger.info("Discovering categories from %s", catalog_url)

        sess = _make_session()
        resp = sess.get(catalog_url, timeout=30)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")
        cat_div = soup.select_one("div.category-list")
        if not cat_div:
            raise RuntimeError("div.category-list not found on catalog page")

        links = cat_div.select("a[href*='subsection=']")
        categories: List[CategoryInfo] = []
        seen_ids: set = set()

        for a in links:
            href = a.get("href", "")
            url = href if href.startswith("http") else urljoin(BASE_URL, href)
            cat_id = _extract_subsection_id(url)
            if not cat_id or cat_id in seen_ids:
                continue
            seen_ids.add(cat_id)
            name = a.get_text(strip=True)
            # Always build a clean URL without extra filter params
            categories.append(
                CategoryInfo(
                    id=cat_id,
                    slug=cat_id,
                    url=f"{BASE_URL}/catalog?subsection={cat_id}",
                    name=name or None,
                )
            )

        categories.sort(key=lambda c: int(c.id))

        if not categories:
            raise RuntimeError("No categories discovered — check network or site structure")

        logger.info("Discovered %d categories", len(categories))
        return categories

    # -- Single-category crawl ----------------------------------------------

    def crawl_category(
        self,
        category: CategoryInfo,
        city: str,
        run_id: str,
    ) -> List[PriceObservation]:
        """Crawl all pages of a single category via URL-based pagination."""
        all_items: Dict[str, PriceObservation] = {}
        logger.info("Crawling category %s", category.id)

        sess = _make_session()

        # First page — also used to detect total pages
        first_url = f"{BASE_URL}/catalog?subsection={category.id}"
        resp = sess.get(first_url, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        max_pages = _detect_max_pages(soup)
        logger.debug("Max pages: %d", max_pages)

        items = self._parse_page(soup, category, city, run_id)
        for item in items:
            all_items[item.product_url] = item
        logger.debug("Page 1: %d items, cumulative %d", len(items), len(all_items))

        for page_num in range(2, max_pages + 1):
            next_url = f"{BASE_URL}/catalog?subsection={category.id}&page={page_num}"
            logger.debug("Page %d/%d: %s", page_num, max_pages, next_url)
            resp = sess.get(next_url, timeout=30)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            items = self._parse_page(soup, category, city, run_id)
            for item in items:
                all_items[item.product_url] = item
            logger.debug(
                "Page %d: %d items, cumulative %d",
                page_num, len(items), len(all_items),
            )

        logger.info(
            "Category %s done: %d unique items across %d pages",
            category.id, len(all_items), max_pages,
        )
        return list(all_items.values())

    # -- HTML parsing -------------------------------------------------------

    def _parse_page(
        self,
        soup: BeautifulSoup,
        category: CategoryInfo,
        city: str,
        run_id: str,
    ) -> List[PriceObservation]:
        """Parse one page of product listings into PriceObservation objects."""
        captured = datetime.now(timezone.utc).isoformat()

        # Each product card is an <a class="product" href="/catalog?prod=ID">
        cards = soup.select("a.product[href*='/catalog?prod=']")
        items: List[PriceObservation] = []
        seen: set = set()

        for card in cards:
            href = card.get("href", "")
            product_url = href if href.startswith("http") else urljoin(BASE_URL, href)

            if product_url in seen:
                continue

            # Name from div.title inside the card
            name_el = card.select_one("div.title")
            if not name_el:
                continue
            name = name_el.get_text(strip=True)
            if not name:
                continue

            # Price: first span in div.price (not the .old span)
            price: Optional[int] = None
            price_div = card.select_one("div.price")
            if price_div:
                for span in price_div.select("span"):
                    if "old" in (span.get("class") or []):
                        continue
                    text = span.get_text(strip=True)
                    m = PRICE_RE.search(text)
                    if m:
                        try:
                            price = _to_int_price(m.group(1))
                            break
                        except ValueError:
                            continue

            if price is None:
                continue

            seen.add(product_url)
            items.append(
                PriceObservation(
                    run_id=run_id,
                    market="flip.kz",
                    city=city,
                    category_id=category.id,
                    category_url=category.url,
                    product_url=product_url,
                    name=name,
                    price_current=price,
                    currency="KZT",
                    unit_code=None,
                    unit_qty=None,
                    pack_qty=None,
                    pack_unit=None,
                    captured_at=captured,
                )
            )

        return items


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def _register() -> None:
    from ..core.runner import register_market
    register_market("flip", FlipMarket)


_register()
