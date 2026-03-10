"""
FinnFlare.kz market adapter.

Scrapes clothing/accessory prices from finn-flare.kz. The site is server-rendered
(Bitrix CMS), so no browser/Playwright is needed — adapter uses requests +
BeautifulSoup. Pagination is URL-based (?PAGEN_1=N).
"""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone
from typing import List
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from ..core.models import CategoryInfo, PriceObservation
from .base import BaseMarket

logger = logging.getLogger("price_tracker.finnflare")

BASE_URL = "https://www.finn-flare.kz"
CATALOG_URL = f"{BASE_URL}/catalog/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9",
}

CARD_SEL = ".product-element"
NAME_SEL = ".itemslider-name span"
LINK_SEL = "a.catalog-item-pointer__wrap[href]"
PRICE_SEL = ".itemslider-price .price.bold"
PRICE_RE = re.compile(r"[\d\s\u00a0\u202f]+")


def _parse_price(text: str) -> int:
    """Strip thousands separators and the ₸ symbol, return int."""
    cleaned = re.sub(r"[\s\u00a0\u202f₸]", "", text)
    return int(cleaned)


def _fetch(url: str, session: requests.Session) -> BeautifulSoup:
    r = session.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")


def _max_page(soup: BeautifulSoup) -> int:
    """Detect max pagination page from PAGEN_1 query params in links."""
    max_p = 1
    for a in soup.select("a[href*='PAGEN_1']"):
        m = re.search(r"PAGEN_1=(\d+)", a.get("href", ""))
        if m:
            max_p = max(max_p, int(m.group(1)))
    return max_p


class FinnFlareMarket(BaseMarket):
    """FinnFlare.kz clothing price scraper."""

    @property
    def market_name(self) -> str:
        return "finnflare"

    @property
    def supported_cities(self) -> List[str]:
        # No city routing; single national catalog
        return ["almaty"]

    # -- Category discovery --------------------------------------------------

    def discover_categories(self, city: str) -> List[CategoryInfo]:
        """Fetch /catalog/ and collect all /catalog/<slug>/ links."""
        logger.info("Discovering categories from %s", CATALOG_URL)
        session = requests.Session()
        soup = _fetch(CATALOG_URL, session)

        seen: set = set()
        categories: List[CategoryInfo] = []

        for a in soup.select("a[href*='/catalog/']"):
            href = a.get("href", "")
            parts = href.strip("/").split("/")
            # Only want /catalog/<slug>/ — exactly two path segments
            if len(parts) != 2 or parts[0] != "catalog" or not parts[1]:
                continue
            slug = parts[1]
            if slug in seen:
                continue
            seen.add(slug)
            name = a.get_text(strip=True) or slug
            url = urljoin(BASE_URL, href)
            categories.append(CategoryInfo(id=slug, slug=slug, url=url, name=name))

        categories.sort(key=lambda c: c.slug)

        if not categories:
            raise RuntimeError("No categories discovered — check site structure")

        logger.info("Discovered %d categories", len(categories))
        return categories

    # -- Single-category crawl -----------------------------------------------

    def crawl_category(
        self,
        category: CategoryInfo,
        city: str,
        run_id: str,
    ) -> List[PriceObservation]:
        """Crawl all pages of a category and return price observations."""
        base_url = category.url.rstrip("/") + "/"
        session = requests.Session()
        all_items: dict = {}  # keyed by product_url for dedup

        logger.info("Crawling %s", category.slug)

        # First page
        soup = _fetch(base_url, session)
        max_pages = _max_page(soup)
        logger.debug("Max pages: %d", max_pages)

        items = self._parse_page(soup, category, city, run_id)
        for obs in items:
            all_items[obs.product_url] = obs
        logger.debug("Page 1: %d items, cumulative %d", len(items), len(all_items))

        # Remaining pages
        for page_num in range(2, max_pages + 1):
            page_url = f"{base_url}?PAGEN_1={page_num}"
            logger.debug("Page %d/%d: %s", page_num, max_pages, page_url)
            time.sleep(0.3)  # polite crawl delay
            soup = _fetch(page_url, session)
            items = self._parse_page(soup, category, city, run_id)
            for obs in items:
                all_items[obs.product_url] = obs
            logger.debug(
                "Page %d: %d items, cumulative %d", page_num, len(items), len(all_items)
            )

        logger.info(
            "Category %s done: %d unique items across %d pages",
            category.slug, len(all_items), max_pages,
        )
        return list(all_items.values())

    # -- HTML parsing --------------------------------------------------------

    def _parse_page(
        self,
        soup: BeautifulSoup,
        category: CategoryInfo,
        city: str,
        run_id: str,
    ) -> List[PriceObservation]:
        captured = datetime.now(timezone.utc).isoformat()
        cards = soup.select(CARD_SEL)
        items: List[PriceObservation] = []
        seen: set = set()

        for card in cards:
            # Name
            name_el = card.select_one(NAME_SEL)
            if not name_el:
                continue
            name = name_el.get_text(strip=True)
            if not name:
                continue

            # Product URL — first color-variant link
            link_el = card.select_one(LINK_SEL)
            if not link_el:
                link_el = card.select_one("a[href*='/catalog/']")
            if not link_el:
                continue
            href = link_el.get("href", "")
            product_url = urljoin(BASE_URL, href)
            if product_url in seen:
                continue

            # Price (current/sale price; .price.bold present for both sale and regular)
            price_el = card.select_one(PRICE_SEL)
            if not price_el:
                continue
            price_text = price_el.get_text(strip=True)
            try:
                price = _parse_price(price_text)
            except (ValueError, AttributeError):
                continue

            seen.add(product_url)
            items.append(
                PriceObservation(
                    run_id=run_id,
                    market="finnflare.kz",
                    city=city,
                    category_id=category.id,
                    category_url=category.url,
                    product_url=product_url,
                    name=name,
                    price_current=price,
                    currency="KZT",
                    unit_code="pcs",
                    unit_qty=1.0,
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
    register_market("finnflare", FinnFlareMarket)


_register()
