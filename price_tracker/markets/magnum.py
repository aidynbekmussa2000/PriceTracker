"""
Magnum.kz market adapter.

Magnum operates a public Strapi v4 API at https://magnum.kz:1337/api.
No authentication or browser rendering is required — all data is fetched
via plain HTTPS JSON requests.

API overview:
    GET /api/categories?locale=ru&pagination[pageSize]=100
        -> list of all product categories (id, slug, label)

    GET /api/products?pagination[page]=N&pagination[pageSize]=500
                     &filters[category][slug][$eq]={slug}&locale=ru
        -> paginated product list with Strapi meta.pagination
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests

from ..core.models import CategoryInfo, PriceObservation
from .base import BaseMarket

logger = logging.getLogger("price_tracker.magnum")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

API_BASE = "https://magnum.kz:1337/api"
SITE_BASE = "https://magnum.kz"
LOCALE = "ru"
PAGE_SIZE = 500

PACK_RE = re.compile(
    r"\b(\d{1,4}(?:[.,]\d+)?)\s*(кг|г|л|мл|kg|g|l|ml)\b", re.IGNORECASE
)
PACK_UNIT_MAP = {
    "кг": "kg", "г": "g", "л": "l", "мл": "ml",
    "kg": "kg", "g": "g", "l": "l", "ml": "ml",
}


# ---------------------------------------------------------------------------
# Static helpers
# ---------------------------------------------------------------------------

def _parse_pack_from_name(name: str) -> Tuple[Optional[float], Optional[str]]:
    """Extract pack quantity and unit from product name (e.g. '400 г')."""
    norm = re.sub(r"\s+", " ", name.replace("\xa0", " ")).strip()
    m = PACK_RE.search(norm)
    if not m:
        return None, None
    qty = float(m.group(1).replace(",", "."))
    unit_raw = m.group(2).lower()
    return qty, PACK_UNIT_MAP.get(unit_raw, unit_raw)


def _make_session() -> requests.Session:
    """Create a requests session with sensible defaults."""
    s = requests.Session()
    s.headers.update({
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (compatible; price-tracker/1.0)",
    })
    return s


# ---------------------------------------------------------------------------
# MagnumMarket adapter
# ---------------------------------------------------------------------------

class MagnumMarket(BaseMarket):
    """
    Magnum.kz price scraper — uses the public Strapi API.

    The Playwright browser passed by the runner is accepted but not used;
    all data is retrieved via requests over HTTPS.
    """

    @property
    def market_name(self) -> str:
        return "magnum"

    @property
    def supported_cities(self) -> List[str]:
        return ["almaty", "astana", "shymkent", "karaganda"]

    # -- Category discovery -------------------------------------------------

    def discover_categories(self, city: str) -> List[CategoryInfo]:
        """Fetch all product categories from the Strapi categories endpoint."""
        url = f"{API_BASE}/categories"
        params = {
            "locale": LOCALE,
            "pagination[pageSize]": 100,
            "sort[0]": "order:asc",
        }
        logger.info("Discovering categories from %s", url)

        sess = _make_session()
        resp = sess.get(url, params=params, timeout=30)
        resp.raise_for_status()
        body = resp.json()

        categories: List[CategoryInfo] = []
        for item in body.get("data", []):
            attrs = item.get("attributes", {})
            slug = attrs.get("slug", "")
            if not slug:
                continue
            name = attrs.get("label") or attrs.get("name") or slug
            cat_id = str(item.get("id", slug))
            cat_url = f"{SITE_BASE}/catalog?category={slug}&city={city}"
            categories.append(
                CategoryInfo(id=cat_id, slug=slug, url=cat_url, name=name)
            )

        if not categories:
            raise RuntimeError("No categories returned from Magnum API")

        logger.info("Discovered %d categories", len(categories))
        return categories

    # -- Single-category crawl ----------------------------------------------

    def crawl_category(
        self,
        category: CategoryInfo,
        city: str,
        run_id: str,
    ) -> List[PriceObservation]:
        """Fetch all pages of products for one category from the Strapi API."""
        all_items: Dict[str, PriceObservation] = {}
        sess = _make_session()

        logger.info("Crawling category %s (%s)", category.slug, category.id)

        page = 1
        while True:
            params = {
                "pagination[page]": page,
                "pagination[pageSize]": PAGE_SIZE,
                "filters[category][slug][$eq]": category.slug,
                "locale": LOCALE,
                "populate[image]": "*",
                "populate[category]": "*",
            }
            resp = sess.get(f"{API_BASE}/products", params=params, timeout=60)
            resp.raise_for_status()
            body = resp.json()

            products = body.get("data", [])
            meta_pag = body.get("meta", {}).get("pagination", {})
            page_count = max(int(meta_pag.get("pageCount", 1)), 1)

            captured = datetime.now(timezone.utc).isoformat()

            for raw in products:
                obs = self._parse_product(raw, category, city, run_id, captured)
                if obs:
                    all_items[obs.product_url] = obs

            logger.debug(
                "Page %d/%d: got %d products, cumulative %d",
                page, page_count, len(products), len(all_items),
            )

            if page >= page_count:
                break
            page += 1

        logger.info(
            "Category %s done: %d unique products", category.slug, len(all_items)
        )
        return list(all_items.values())

    # -- Product parsing ----------------------------------------------------

    def _parse_product(
        self,
        product: Dict[str, Any],
        category: CategoryInfo,
        city: str,
        run_id: str,
        captured: str,
    ) -> Optional[PriceObservation]:
        """Convert a Strapi product record into a PriceObservation."""
        product_id = product.get("id")
        if not product_id:
            return None

        attrs = product.get("attributes", {})
        name = attrs.get("name", "").strip()
        if not name:
            return None

        # final_price is the discounted/current price; fall back to start_price
        price_raw = attrs.get("final_price")
        if price_raw is None:
            price_raw = attrs.get("start_price")
        if price_raw is None:
            return None
        try:
            price = int(round(float(price_raw)))
        except (ValueError, TypeError):
            return None

        product_url = f"{SITE_BASE}/products/{product_id}?city={city}"
        pack_qty, pack_unit = _parse_pack_from_name(name)

        return PriceObservation(
            run_id=run_id,
            market="magnum.kz",
            city=city,
            category_id=category.id,
            category_url=category.url,
            product_url=product_url,
            name=name,
            price_current=price,
            currency="KZT",
            unit_code=None,
            unit_qty=None,
            pack_qty=pack_qty,
            pack_unit=pack_unit,
            captured_at=captured,
        )


# ---------------------------------------------------------------------------
# Registration — makes this market available to the runner
# ---------------------------------------------------------------------------

def _register() -> None:
    from ..core.runner import register_market
    register_market("magnum", MagnumMarket)


_register()
