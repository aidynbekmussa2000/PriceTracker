"""
VPrestige.kz market adapter.

Scrapes furniture prices from vprestige.kz. The site is server-rendered
(not a SPA), so pagination is URL-based (?PAGEN_1=N) and no special
click handling is needed.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag
from playwright.sync_api import Page

from ..core.models import CategoryInfo, PriceObservation
from .base import BaseMarket

logger = logging.getLogger("price_tracker.vprestige")

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

# Price: "215 500 тг" — space-separated thousands, trailing "тг"
PRICE_RE = re.compile(r"([\d\s\xa0]+)\s*тг")

# Category ID from URL: /catalog/soft-furniture/000000062/
CAT_NUM_RE = re.compile(r"/(\d{6,})/")

# Product URL pattern: /catalog/pNNNNN/
PRODUCT_URL_RE = re.compile(r"/catalog/p(\d+)/")

# Skip these sidebar slugs (not real product categories)
SKIP_SLUGS = {
    "action", "special-price", "products-in-the-kaspi-market",
    "podarochnye-karty", "rental",
}

# ---------------------------------------------------------------------------
# CSS selectors
# ---------------------------------------------------------------------------

CARD_SEL = ".catalog-item[data-element-id]"
NAME_SEL = "h4.catalog-item__name-content"
PRICE_SEL = ".catalog-item__price .font-weight-bold"
LINK_SEL = "a.mdc-card__primary-action[href]"
PAGINATION_SEL = "ul.pagination"
SIDEBAR_SEL = "aside.sidebar a[href*='/catalog/']"


# ---------------------------------------------------------------------------
# Static helpers
# ---------------------------------------------------------------------------

def _to_int_price(s: str) -> int:
    """Clean whitespace/NBSP from price string and convert to int."""
    cleaned = re.sub(r"[\s\xa0]+", "", s)
    return int(cleaned)


def _extract_slug(url: str) -> str:
    """Extract the main category slug from a URL path."""
    path = urlparse(url).path.strip("/")
    parts = path.split("/")
    # /catalog/soft-furniture/ -> "soft-furniture"
    # /catalog/soft-furniture/000000062/ -> "soft-furniture/000000062"
    if len(parts) >= 2 and parts[0] == "catalog":
        return "/".join(parts[1:])
    return path


def _extract_cat_id(url: str) -> str:
    """Extract a category ID from URL. Uses numeric ID if present, else slug."""
    m = CAT_NUM_RE.search(urlparse(url).path)
    if m:
        return m.group(1)
    return _extract_slug(url).replace("/", "_")


# ---------------------------------------------------------------------------
# VPrestigeMarket adapter
# ---------------------------------------------------------------------------

class VPrestigeMarket(BaseMarket):
    """VPrestige.kz furniture price scraper."""

    @property
    def market_name(self) -> str:
        return "vprestige"

    @property
    def supported_cities(self) -> List[str]:
        # VPrestige doesn't have city-based routing; single catalog
        return ["aktau"]

    # -- Category discovery -------------------------------------------------

    def discover_categories(self, city: str) -> List[CategoryInfo]:
        """Scrape sidebar links from the catalog page."""
        catalog_url = "https://vprestige.kz/catalog/"
        logger.info("Discovering categories from %s", catalog_url)

        context = self._new_context()
        page = context.new_page()

        try:
            page.goto(catalog_url, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(2_000)
            html = page.content()

            self.dbg.save_html(html, "discovery_catalog.html")
            self.dbg.save_screenshot(page, "discovery_catalog.png")
        finally:
            context.close()

        soup = BeautifulSoup(html, "html.parser")
        sidebar = soup.select_one("aside.sidebar")
        if not sidebar:
            raise RuntimeError("Sidebar not found on catalog page")

        links = sidebar.select("a[href*='/catalog/']")
        categories: List[CategoryInfo] = []
        seen_slugs: set = set()

        for a in links:
            href = a.get("href", "")
            text = a.get_text(strip=True)

            # Build absolute URL
            url = href if href.startswith("http") else urljoin("https://vprestige.kz", href)
            url = url.rstrip("/") + "/"

            # Skip product links, non-category pages
            if PRODUCT_URL_RE.search(url):
                continue

            slug = _extract_slug(url)
            if not slug or slug in seen_slugs:
                continue

            # Skip special/non-product sections
            first_part = slug.split("/")[0]
            if first_part in SKIP_SLUGS:
                continue

            seen_slugs.add(slug)
            cat_id = _extract_cat_id(url)

            categories.append(
                CategoryInfo(
                    id=cat_id,
                    slug=slug,
                    url=url,
                    name=text or None,
                )
            )

        categories.sort(key=lambda c: c.slug)

        if not categories:
            raise RuntimeError("No categories discovered from sidebar")

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
        base_url = category.url.rstrip("/") + "/"
        all_items: Dict[str, PriceObservation] = {}  # keyed by product_url

        logger.info("Crawling %s (category %s)", category.slug, category.id)

        context = self._new_context()
        page = context.new_page()

        try:
            # Load first page to detect max pages
            page.goto(base_url, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(1_500)

            max_pages = self._detect_max_pages(page)
            logger.debug("Max pages: %d", max_pages)

            self.dbg.save_screenshot(page, "stage1_page1.png")

            # Parse first page
            items = self._parse_page(page.content(), category, city, run_id)
            for item in items:
                all_items[item.product_url] = item

            logger.debug("Page 1: %d items, cumulative %d", len(items), len(all_items))

            # Paginate through remaining pages via URL
            for page_num in range(2, max_pages + 1):
                page_url = f"{base_url}?PAGEN_1={page_num}"
                logger.debug("Page %d/%d: %s", page_num, max_pages, page_url)

                page.goto(page_url, wait_until="domcontentloaded", timeout=60_000)
                page.wait_for_timeout(1_000)

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
            "Category %s done: %d unique items across %d pages",
            category.id, len(all_items), max_pages,
        )
        return list(all_items.values())

    # -- Pagination detection -----------------------------------------------

    @staticmethod
    def _detect_max_pages(page: Page) -> int:
        """Read max page number from pagination links."""
        html = page.content()
        soup = BeautifulSoup(html, "html.parser")
        pag = soup.select_one(PAGINATION_SEL)
        if not pag:
            return 1

        max_page = 1
        for a in pag.select("a[href]"):
            m = re.search(r"PAGEN_1=(\d+)", a.get("href", ""))
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
        """Parse one page of product listings."""
        soup = BeautifulSoup(html, "html.parser")
        captured = datetime.now(timezone.utc).isoformat()

        cards = soup.select(CARD_SEL)
        items: List[PriceObservation] = []
        seen: set = set()

        for card in cards:
            # Product link and ID
            link_el = card.select_one(LINK_SEL)
            if not link_el:
                continue
            href = link_el.get("href", "")
            product_url = urljoin("https://vprestige.kz", href.split("#")[0])

            if product_url in seen:
                continue

            # Product name
            name_el = card.select_one(NAME_SEL)
            if not name_el:
                continue
            name = name_el.get_text(strip=True)
            if not name:
                continue

            # Price
            price_el = card.select_one(PRICE_SEL)
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

            seen.add(product_url)
            items.append(
                PriceObservation(
                    run_id=run_id,
                    market="vprestige.kz",
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
    register_market("vprestige", VPrestigeMarket)


_register()
