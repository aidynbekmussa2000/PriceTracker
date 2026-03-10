"""
Megastroy.kz market adapter.

Scrapes product prices from megastroy.kz. The site is server-rendered
Bitrix CMS, so all data is fetched via plain HTTPS requests without a browser.

Site notes:
    - Bitrix CMS; no city routing in URLs (single catalog for Astana region).
    - Category discovery: all /catalog/... links from the catalog homepage;
      only leaf categories (not a URL-prefix of any other) are crawled.
    - Product cards: div.catalog_item_wrapp
        - name + URL: div.item-title > a
        - price:      span.price_value (space-separated thousands, e.g. "1 690")
    - Pagination: ?PAGEN_1=N (Bitrix standard).
    - Max page detected from highest PAGEN_1 value in anchor hrefs.
    - Prices are in "тенге" (KZT). No city routing.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from ..core.models import CategoryInfo, PriceObservation
from .base import BaseMarket

logger = logging.getLogger("price_tracker.megastroy")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_URL = "https://megastroy.kz"
CATALOG_URL = f"{BASE_URL}/catalog/"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


def _detect_max_pages(soup: BeautifulSoup) -> int:
    """Return highest PAGEN_1 value found in pagination links, default 1."""
    max_page = 1
    for a in soup.find_all("a", href=re.compile(r"PAGEN_1=")):
        m = re.search(r"PAGEN_1=(\d+)", a.get("href", ""))
        if m:
            max_page = max(max_page, int(m.group(1)))
    return max_page


def _parse_price(price_el) -> Optional[int]:
    """Parse price_value span text (e.g. '1 690') to int."""
    if price_el is None:
        return None
    raw = price_el.get_text(strip=True)
    cleaned = re.sub(r"[\s\xa0\u202f]+", "", raw)
    try:
        return int(cleaned)
    except ValueError:
        return None


def _cat_slug(path: str) -> str:
    """Convert /catalog/a/b/ → a/b."""
    parts = [p for p in path.split("/") if p and p != "catalog"]
    return "/".join(parts)


# ---------------------------------------------------------------------------
# MegastroyMarket adapter
# ---------------------------------------------------------------------------


class MegastroyMarket(BaseMarket):
    """
    Megastroy.kz price scraper — uses plain HTTP requests.

    The Playwright browser passed by the runner is accepted but not used;
    all data is retrieved via requests over HTTPS.
    """

    @property
    def market_name(self) -> str:
        return "megastroy"

    @property
    def supported_cities(self) -> List[str]:
        # Site serves Astana region; 'almaty' used as conventional key.
        return ["almaty"]

    # -- Category discovery -------------------------------------------------

    def discover_categories(self, city: str) -> List[CategoryInfo]:
        """Fetch the catalog page and return all leaf category URLs."""
        logger.info("Discovering categories from %s", CATALOG_URL)

        sess = _make_session()
        resp = sess.get(CATALOG_URL, timeout=30)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

        # Collect all unique /catalog/... hrefs
        all_paths: list[str] = []
        seen: set = set()
        for a in soup.find_all("a", href=re.compile(r"^/catalog/")):
            href = a.get("href", "").rstrip("/") + "/"
            # Skip root catalog page and filter/sort URLs
            if href == "/catalog/" or "/filter/" in href or "?" in href:
                continue
            if href not in seen:
                seen.add(href)
                all_paths.append(href)

        # Keep only leaf paths (not a URL-prefix of any other path)
        path_set = set(all_paths)
        leaves: List[CategoryInfo] = []
        seen_slugs: set = set()
        for path in all_paths:
            is_leaf = not any(
                other != path and other.startswith(path)
                for other in path_set
            )
            if not is_leaf:
                continue
            slug = _cat_slug(path)
            if not slug or slug in seen_slugs:
                continue
            seen_slugs.add(slug)
            leaves.append(
                CategoryInfo(
                    id=slug,
                    slug=slug,
                    url=urljoin(BASE_URL, path),
                )
            )

        leaves.sort(key=lambda c: c.id)

        if not leaves:
            raise RuntimeError(
                "No categories discovered — check network or site structure"
            )

        logger.info("Discovered %d leaf categories", len(leaves))
        return leaves

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
        resp = sess.get(category.url, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        max_pages = _detect_max_pages(soup)
        logger.debug("Max pages: %d", max_pages)

        items = self._parse_page(soup, category, city, run_id)
        for item in items:
            all_items[item.product_url] = item
        logger.debug("Page 1: %d items, cumulative %d", len(items), len(all_items))

        for page_num in range(2, max_pages + 1):
            page_url = f"{category.url}?PAGEN_1={page_num}"
            logger.debug("Page %d/%d: %s", page_num, max_pages, page_url)
            resp = sess.get(page_url, timeout=30)
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
        cards = soup.select("div.catalog_item_wrapp")
        items: List[PriceObservation] = []
        seen: set = set()

        for card in cards:
            # Product name and URL from item-title anchor (has text, not image)
            name_a = card.select_one("div.item-title a")
            if not name_a:
                continue
            href = name_a.get("href", "")
            if not href:
                continue
            product_url = href if href.startswith("http") else urljoin(BASE_URL, href)
            if product_url in seen:
                continue

            name = name_a.get_text(strip=True)
            if not name:
                continue

            # Price from span.price_value (e.g. "1 690")
            price_el = card.select_one("span.price_value")
            price = _parse_price(price_el)
            if price is None:
                continue

            seen.add(product_url)
            items.append(
                PriceObservation(
                    run_id=run_id,
                    market="megastroy.kz",
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
    register_market("megastroy", MegastroyMarket)


_register()
