"""
Biosfera.kz market adapter.

Scrapes pharmacy prices from biosfera.kz. The site is a Next.js React app
backed by a public REST API at back.biosfera.kz. No browser/Playwright needed —
adapter uses `requests` to call the JSON API directly.

Category discovery: parses sitemap-categories.xml for leaf category slugs.
Products: GET back.biosfera.kz/products/bycategory?category={slug}&page={n}&limit=50
Pagination: computed from totalCount / limit (ceiling division).
City-specific pricing: minPricesByCity['Алматы'] when available, fallback to 'price'.
Product URL: https://biosfera.kz/ru/product/{GUID}
"""
from __future__ import annotations

import logging
import math
import re
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

import requests

from ..core.models import CategoryInfo, PriceObservation
from .base import BaseMarket

logger = logging.getLogger("price_tracker.biosfera")

BASE_URL = "https://biosfera.kz"
API_BASE = "https://back.biosfera.kz"
SITEMAP_URL = f"{BASE_URL}/sitemap-categories.xml"
PAGE_LIMIT = 50

HEADERS = {
    "Referer": f"{BASE_URL}/",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ru-RU,ru;q=0.9",
}

# Mapping from our city slugs to Cyrillic city names used in minPricesByCity
CITY_MAP: Dict[str, str] = {
    "almaty": "Алматы",
    "astana": "Астана",
}


class BiosferaMarket(BaseMarket):
    """Biosfera.kz pharmacy price scraper."""

    @property
    def market_name(self) -> str:
        return "biosfera"

    @property
    def supported_cities(self) -> List[str]:
        return ["almaty"]

    # -- Category discovery --------------------------------------------------

    def discover_categories(self, city: str) -> List[CategoryInfo]:
        """Parse sitemap-categories.xml and return leaf category slugs."""
        logger.info("Fetching category sitemap from %s", SITEMAP_URL)
        session = requests.Session()
        r = session.get(SITEMAP_URL, headers=HEADERS, timeout=30)
        r.raise_for_status()

        # Extract all /ru/catalog/ paths
        ru_paths = re.findall(
            r"<loc>https://biosfera\.kz/ru/catalog/([^<]+)</loc>", r.text
        )

        if not ru_paths:
            raise RuntimeError("No category URLs found in sitemap — site structure may have changed")

        # Find leaf paths: those NOT a URL-prefix of any other path
        path_set = set(ru_paths)
        leaf_paths: List[str] = []
        for p in ru_paths:
            is_parent = any(
                other != p and other.startswith(p + "/")
                for other in path_set
            )
            if not is_parent:
                leaf_paths.append(p)

        # Build CategoryInfo from leaf paths; slug = last path component
        seen_slugs: set = set()
        categories: List[CategoryInfo] = []
        for path in leaf_paths:
            slug = path.split("/")[-1]
            if slug in seen_slugs:
                continue
            seen_slugs.add(slug)
            categories.append(
                CategoryInfo(
                    id=slug,
                    slug=slug,
                    url=f"{BASE_URL}/ru/catalog/{path}",
                )
            )

        categories.sort(key=lambda c: c.slug)

        if not categories:
            raise RuntimeError("No leaf categories extracted from sitemap")

        logger.info("Discovered %d leaf categories", len(categories))
        return categories

    # -- Single-category crawl -----------------------------------------------

    def crawl_category(
        self,
        category: CategoryInfo,
        city: str,
        run_id: str,
    ) -> List[PriceObservation]:
        """Fetch all pages of a category and return price observations."""
        slug = category.id
        city_ru = CITY_MAP.get(city, "")
        session = requests.Session()
        all_items: Dict[str, PriceObservation] = {}

        logger.info("Crawling biosfera category %s (city=%s)", slug, city)

        # Fetch first page to get totalCount
        data = self._fetch_page(session, slug, page=1)
        total_count = data.get("totalCount") or 0
        products = data.get("products") or []

        if total_count == 0:
            logger.debug("Category %s: no products", slug)
            return []

        total_pages = math.ceil(total_count / PAGE_LIMIT)
        logger.debug("Category %s: totalCount=%d, pages=%d", slug, total_count, total_pages)

        obs_page = self._parse_products(products, category, city, city_ru, run_id)
        for obs in obs_page:
            all_items[obs.product_url] = obs
        logger.debug("Page 1/%d: %d items, cumulative %d", total_pages, len(obs_page), len(all_items))

        # Remaining pages
        for page_num in range(2, total_pages + 1):
            time.sleep(0.2)
            data = self._fetch_page(session, slug, page=page_num)
            products = data.get("products") or []
            if not products:
                break
            obs_page = self._parse_products(products, category, city, city_ru, run_id)
            for obs in obs_page:
                all_items[obs.product_url] = obs
            logger.debug(
                "Page %d/%d: %d items, cumulative %d",
                page_num, total_pages, len(obs_page), len(all_items),
            )

        logger.info(
            "Category %s done: %d unique items across %d pages",
            slug, len(all_items), total_pages,
        )
        return list(all_items.values())

    # -- API helpers ---------------------------------------------------------

    @staticmethod
    def _fetch_page(session: requests.Session, slug: str, page: int) -> dict:
        """Fetch one page of products from the API."""
        url = (
            f"{API_BASE}/products/bycategory"
            f"?category={slug}&page={page}&limit={PAGE_LIMIT}"
        )
        r = session.get(url, headers=HEADERS, timeout=30)
        r.raise_for_status()
        return r.json()

    # -- Product parsing -----------------------------------------------------

    @staticmethod
    def _parse_products(
        products: list,
        category: CategoryInfo,
        city: str,
        city_ru: str,
        run_id: str,
    ) -> List[PriceObservation]:
        """Convert raw API product dicts to PriceObservation objects."""
        captured = datetime.now(timezone.utc).isoformat()
        items: List[PriceObservation] = []
        seen: set = set()

        for prod in products:
            guid: Optional[str] = prod.get("GUID")
            title: Optional[str] = prod.get("title")
            if not guid or not title:
                continue

            product_url = f"{BASE_URL}/ru/product/{guid}"
            if product_url in seen:
                continue

            # City-specific price > base price
            price_int: Optional[int] = None
            city_prices: dict = prod.get("minPricesByCity") or {}
            if city_ru and city_ru in city_prices:
                price_int = int(city_prices[city_ru])
            elif prod.get("price") is not None:
                price_int = int(prod["price"])

            if not price_int:
                continue

            seen.add(product_url)
            items.append(
                PriceObservation(
                    run_id=run_id,
                    market="biosfera.kz",
                    city=city,
                    category_id=category.id,
                    category_url=category.url,
                    product_url=product_url,
                    name=title.strip(),
                    price_current=price_int,
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
    register_market("biosfera", BiosferaMarket)


_register()
