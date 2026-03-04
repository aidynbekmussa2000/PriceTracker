"""
Technodom.kz market adapter.

Technodom is a major electronics retailer in Kazakhstan. The site is built
with Next.js (SSR), so product listings are server-rendered and accessible
without full JavaScript execution. Pagination is URL-based (?page=N).

URL pattern:
    Catalog index:  https://technodom.kz/{city}/catalog
    Category pages: https://technodom.kz/{city}/catalog/{a}/{b}/{c}?page=N
    Product pages:  https://technodom.kz/p/{slug}-{id}

Category discovery:
    The catalog page nav contains depth-3 hrefs
    (/catalog/parent/mid/leaf) listing all product sections.
    Brand-filtered variants (/f/brands/...) are excluded.

Product parsing:
    Cards use data-testid="product-card".
    Name:  <p class*="ProductCardV_title">
    Price: <p class*="ProductCardPrices_price"> (contains ₸)
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional

from bs4 import BeautifulSoup
from playwright.sync_api import Page

from ..core.models import CategoryInfo, PriceObservation
from .base import BaseMarket

logger = logging.getLogger("price_tracker.technodom")

BASE_URL = "https://technodom.kz"

# Price: "852 990 ₸" or "15,490 ₸" — spaces/commas as thousand separators
PRICE_RE = re.compile(r"([\d][\d\s\xa0,]*)\s*₸")

# Depth-3 catalog path: /catalog/a/b/c (no brand filter, no trailing slash noise)
LEAF_CAT_RE = re.compile(r"^/catalog/([^/]+/[^/]+/[^/]+)/?$")


# ---------------------------------------------------------------------------
# Static helpers
# ---------------------------------------------------------------------------

def _to_int_price(s: str) -> int:
    """Remove thousand separators (spaces, NBSP, commas) and convert to int."""
    cleaned = re.sub(r"[\s\xa0,]+", "", s)
    return int(cleaned)


# ---------------------------------------------------------------------------
# TechnodomMarket adapter
# ---------------------------------------------------------------------------

class TechnodomMarket(BaseMarket):
    """Technodom.kz electronics price scraper (Next.js SSR, URL pagination)."""

    @property
    def market_name(self) -> str:
        return "technodom"

    @property
    def supported_cities(self) -> List[str]:
        return ["almaty"]

    # -- Category discovery -------------------------------------------------

    def discover_categories(self, city: str) -> List[CategoryInfo]:
        """
        Load the catalog index and extract all leaf category paths.

        The page nav lists depth-3 hrefs (/catalog/a/b/c) for each product
        subcategory. Brand-filtered variants (/f/) are skipped.
        """
        catalog_url = f"{BASE_URL}/{city}/catalog"
        logger.info("Discovering categories from %s", catalog_url)

        context = self._new_context()
        page = context.new_page()

        try:
            page.goto(catalog_url, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(3_000)
            html = page.content()
            self.dbg.save_html(html, "discovery_catalog.html")
            self.dbg.save_screenshot(page, "discovery_catalog.png")
        finally:
            context.close()

        soup = BeautifulSoup(html, "html.parser")
        categories: List[CategoryInfo] = []
        seen_slugs: set = set()

        for a in soup.select('a[href*="/catalog/"]'):
            href = a.get("href", "")
            # Skip brand/attribute filters
            if "/f/" in href:
                continue
            m = LEAF_CAT_RE.match(href)
            if not m:
                continue
            slug = m.group(1)  # e.g. "smartfony-i-gadzhety/smartfony-i-telefony/smartfony"
            if slug in seen_slugs:
                continue
            seen_slugs.add(slug)

            name = a.get_text(strip=True) or slug.split("/")[-1]
            url = f"{BASE_URL}/{city}/catalog/{slug}"

            categories.append(
                CategoryInfo(id=slug, slug=slug, url=url, name=name)
            )

        categories.sort(key=lambda c: c.slug)

        if not categories:
            raise RuntimeError(
                "No categories discovered — check network or site structure"
            )

        logger.info("Discovered %d categories", len(categories))
        return categories

    # -- Single-category crawl ----------------------------------------------

    def crawl_category(
        self,
        category: CategoryInfo,
        city: str,
        run_id: str,
    ) -> List[PriceObservation]:
        """Crawl all pages of a category via URL-based pagination."""
        all_items: Dict[str, PriceObservation] = {}

        logger.info("Crawling %s", category.slug)

        context = self._new_context()
        page = context.new_page()

        try:
            page.goto(category.url, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(2_000)

            max_pages = self._detect_max_pages(page)
            logger.debug("Max pages: %d", max_pages)

            self.dbg.save_screenshot(page, "stage1_page1.png")

            items = self._parse_page(page.content(), category, city, run_id)
            for item in items:
                all_items[item.product_url] = item
            logger.debug("Page 1: %d items, cumulative %d", len(items), len(all_items))

            for page_num in range(2, max_pages + 1):
                page_url = f"{category.url}?page={page_num}"
                logger.debug("Page %d/%d: %s", page_num, max_pages, page_url)

                page.goto(page_url, wait_until="domcontentloaded", timeout=60_000)
                page.wait_for_timeout(1_500)

                items = self._parse_page(page.content(), category, city, run_id)
                for item in items:
                    all_items[item.product_url] = item

                self.dbg.save_screenshot(page, f"stage2_page{page_num}.png")
                logger.debug(
                    "Page %d: %d items, cumulative %d",
                    page_num, len(items), len(all_items),
                )
        finally:
            context.close()

        logger.info(
            "Category %s done: %d unique items", category.slug, len(all_items)
        )
        return list(all_items.values())

    # -- Pagination detection -----------------------------------------------

    @staticmethod
    def _detect_max_pages(page: Page) -> int:
        """Extract maximum page number from ?page=N pagination links."""
        html = page.content()
        soup = BeautifulSoup(html, "html.parser")
        max_page = 1
        for a in soup.select('a[href*="page="]'):
            m = re.search(r"[?&]page=(\d+)", a.get("href", ""))
            if m:
                max_page = max(max_page, int(m.group(1)))
        return max_page

    # -- HTML parsing -------------------------------------------------------

    def _parse_page(
        self,
        html: str,
        category: CategoryInfo,
        city: str,
        run_id: str,
    ) -> List[PriceObservation]:
        """Parse product listings from one rendered page."""
        soup = BeautifulSoup(html, "html.parser")
        captured = datetime.now(timezone.utc).isoformat()

        items: List[PriceObservation] = []
        seen: set = set()

        for card in soup.select('[data-testid="product-card"]'):
            # Product URL from parent <a>
            parent_a = card.find_parent("a")
            if not parent_a:
                continue
            href = parent_a.get("href", "")
            if not href or "/p/" not in href:
                continue
            product_url = (
                href if href.startswith("http") else BASE_URL + href.split("?")[0]
            )
            if product_url in seen:
                continue

            # Product name
            name_el = card.select_one('p[class*="ProductCardV_title"]')
            if not name_el:
                continue
            name = name_el.get_text(strip=True)
            if not name:
                continue

            # Current price (not the old/crossed-out price)
            price_el = card.select_one('p[class*="ProductCardPrices_price"]')
            if not price_el:
                continue
            price_text = price_el.get_text(strip=True)
            m = PRICE_RE.search(price_text)
            if not m:
                continue
            try:
                price = _to_int_price(m.group(1))
            except ValueError:
                continue

            if price < 10:
                continue

            seen.add(product_url)
            items.append(
                PriceObservation(
                    run_id=run_id,
                    market="technodom.kz",
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
# Registration — makes this market available to the runner
# ---------------------------------------------------------------------------

def _register() -> None:
    from ..core.runner import register_market
    register_market("technodom", TechnodomMarket)


_register()
