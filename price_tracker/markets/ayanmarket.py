"""
AyanMarket.kz market adapter.

Scrapes product prices from ayanmarket.kz using the site's public REST API
(https://ayanmarketapi.kz/api). No browser/Playwright needed — all requests
are JSON over HTTPS with only a referer header and a UUID anonymous-id.

API flow per run:
  1. POST /api/site/geo/find/address  {"pointCoords":[]}
     → returns list of department objects; extract their `id` values.
     These are the store/department IDs used in product filters.
  2. Categories come from scraping the server-rendered HTML at https://ayanmarket.kz/
     a[href*="/shop/collection/"] links; each href ends in /slug-{categoryId}.
  3. Products: PUT /api/web/provider/product/get/filter/site
     body: {"categoryIds":[N],"departmentIds":[...],"page":0,"size":72,...}
     response: {"products":{"content":[...],"totalPages":N,...}}
     Paginate by incrementing `page` until page >= totalPages.

Note: ayanmarket.kz serves Karaganda, Temirtau, and Astana.
The API is location-based (uses default coordinates → Karaganda departments).
City routing is not supported; `supported_cities = ['almaty']` is conventional.
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import List, Optional

import requests
from bs4 import BeautifulSoup

from ..core.models import CategoryInfo, PriceObservation
from .base import BaseMarket

logger = logging.getLogger("price_tracker.ayanmarket")

API_BASE = "https://ayanmarketapi.kz/api"
SITE_BASE = "https://ayanmarket.kz"

PAGE_SIZE = 72
CAT_HREF_RE = re.compile(r"/shop/collection/([\w-]+)-(\d+)$")


def _build_headers() -> dict:
    return {
        "referer": f"{SITE_BASE}/",
        "accept-language": "ru-RU",
        "user-agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "accept": "application/json, text/plain, */*",
        "x-anonymous-id": str(uuid.uuid4()),
        "content-type": "application/json;charset=UTF-8",
    }


class AyanMarketMarket(BaseMarket):
    """AyanMarket.kz price scraper — pure REST API adapter."""

    def __init__(self, browser, headless: bool = True, debug: bool = False):
        super().__init__(browser, headless, debug)
        self._session = requests.Session()
        self._session.headers.update(_build_headers())
        self._dept_ids: Optional[List[int]] = None

    @property
    def market_name(self) -> str:
        return "ayanmarket"

    @property
    def supported_cities(self) -> List[str]:
        # Site doesn't have city-based URL routing; uses geo-located departments.
        # 'almaty' is conventional to align with default runner config.
        return ["almaty"]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_dept_ids(self) -> List[int]:
        """Fetch department IDs once per adapter instance (cached)."""
        if self._dept_ids is not None:
            return self._dept_ids

        resp = self._session.post(
            f"{API_BASE}/site/geo/find/address",
            json={"pointCoords": []},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        departments = data.get("data", []) if isinstance(data, dict) else data
        self._dept_ids = [d["id"] for d in departments if isinstance(d, dict)]
        logger.debug("Fetched %d department IDs", len(self._dept_ids))
        return self._dept_ids

    # ------------------------------------------------------------------
    # Category discovery
    # ------------------------------------------------------------------

    def discover_categories(self, city: str) -> List[CategoryInfo]:
        """Scrape category links from the server-rendered homepage HTML."""
        logger.info("Discovering categories from %s", SITE_BASE)

        resp = self._session.get(SITE_BASE, timeout=30)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")
        links = soup.select('a[href*="/shop/collection/"]')

        categories: List[CategoryInfo] = []
        seen_ids: set = set()

        for a in links:
            href = a.get("href", "")
            m = CAT_HREF_RE.search(href)
            if not m:
                continue

            slug = m.group(1)
            cat_id = m.group(2)
            if cat_id in seen_ids:
                continue
            seen_ids.add(cat_id)

            name = a.get_text(strip=True) or slug
            url = f"{SITE_BASE}{href}"
            categories.append(CategoryInfo(id=cat_id, slug=slug, url=url, name=name))

        if not categories:
            raise RuntimeError("No categories discovered — check site structure")

        logger.info("Discovered %d categories", len(categories))
        return categories

    # ------------------------------------------------------------------
    # Single-category crawl
    # ------------------------------------------------------------------

    def crawl_category(
        self,
        category: CategoryInfo,
        city: str,
        run_id: str,
    ) -> List[PriceObservation]:
        """Fetch all pages of products for one category via API pagination."""
        dept_ids = self._get_dept_ids()
        cat_id_int = int(category.id)
        all_items: dict[str, PriceObservation] = {}
        page = 0

        logger.debug("Crawling category %s (%s)", category.id, category.slug)

        while True:
            body = {
                "categoryIds": [cat_id_int],
                "departmentIds": dept_ids,
                "page": page,
                "size": PAGE_SIZE,
                "sortType": "POPULAR",
                "sortOrder": "DESC",
                "discount": False,
                "loyaltyDiscount": False,
            }

            resp = self._session.put(
                f"{API_BASE}/web/provider/product/get/filter/site",
                json=body,
                timeout=30,
            )
            resp.raise_for_status()

            data = resp.json()
            products_data = data.get("products") or {}
            content = products_data.get("content") or []
            total_pages = products_data.get("totalPages") or 1

            captured = datetime.now(timezone.utc).isoformat()

            for product in content:
                product_id = product.get("providerProductId")
                if not product_id:
                    continue

                name = (product.get("name") or "").strip()
                if not name:
                    continue

                # Use the minimum available price across all providers
                prices = [
                    p["price"]
                    for p in product.get("pricesList") or []
                    if p.get("price") and p.get("available", True)
                ]
                if not prices:
                    continue

                price_current = int(min(prices))
                product_url = f"{SITE_BASE}/product/{product_id}"
                key = str(product_id)

                if key not in all_items:
                    all_items[key] = PriceObservation(
                        run_id=run_id,
                        market="ayanmarket.kz",
                        city=city,
                        category_id=category.id,
                        category_url=category.url,
                        product_url=product_url,
                        name=name,
                        price_current=price_current,
                        currency="KZT",
                        unit_code=None,
                        unit_qty=None,
                        pack_qty=None,
                        pack_unit=None,
                        captured_at=captured,
                    )

            logger.debug(
                "Category %s page %d/%d: %d products, cumulative %d",
                category.id, page + 1, total_pages, len(content), len(all_items),
            )

            page += 1
            if page >= total_pages:
                break

        return list(all_items.values())


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def _register() -> None:
    from ..core.runner import register_market
    register_market("ayanmarket", AyanMarketMarket)


_register()
