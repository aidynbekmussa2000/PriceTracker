"""
Sulpak.kz market adapter.

Sulpak is a major Kazakhstani electronics and home-appliance retailer.
The site is server-rendered. Product listing pages live at:

    https://sulpak.kz/f/{slug}/{city}          (page 1)
    https://sulpak.kz/f/{slug}/{city}?page=N   (page N)

Product data is embedded in the page as:
    window.insider_object.listing.items  →  [{name, unit_sale_price}, ...]

Product URLs are extracted from  a[href^="/g/"]  elements in DOM order,
which matches the insider_object ordering (both reflect listing order).

Category discovery:
    Load the homepage and extract all /f/{slug} links from the navigation.
    Exactly these slugs will be used as leaf category identifiers.
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

logger = logging.getLogger("price_tracker.sulpak")

BASE_URL = "https://sulpak.kz"

# Matches "Страница 3 из 37" — capture the total page count
MAX_PAGES_RE = re.compile(r"[Сс]траниц[аы]\s+\d+\s+из\s+(\d+)")


# ---------------------------------------------------------------------------
# Static helpers
# ---------------------------------------------------------------------------

def _clean_slug(href: str) -> Optional[str]:
    """
    Extract the bare category slug from a /f/ href.

    /f/smartfoniy/               -> "smartfoniy"
    /f/noutbuki                  -> "noutbuki"
    /f/smart_kolonki.../almaty/. -> "smart_kolonki..."
    Returns None for non-/f/ hrefs or empty slugs.
    """
    if not href.startswith("/f/"):
        return None
    slug = href[3:].split("/")[0].strip("/")
    return slug if slug else None


# ---------------------------------------------------------------------------
# SulpakMarket adapter
# ---------------------------------------------------------------------------

class SulpakMarket(BaseMarket):
    """Sulpak.kz electronics/appliance price scraper."""

    @property
    def market_name(self) -> str:
        return "sulpak"

    @property
    def supported_cities(self) -> List[str]:
        return ["almaty"]

    # -- Category discovery -------------------------------------------------

    def discover_categories(self, city: str) -> List[CategoryInfo]:
        """
        Load the Sulpak homepage and extract all /f/ category slugs.

        The homepage navigation contains links like /f/smartfoniy, /f/noutbuki,
        /f/kondicioneriy, etc. These are the leaf-level product listing pages.
        """
        logger.info("Discovering categories from %s", BASE_URL)

        context = self._new_context()
        page = context.new_page()

        try:
            page.goto(BASE_URL, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(2_000)
            html = page.content()
            self.dbg.save_html(html, "discovery_catalog.html")
            self.dbg.save_screenshot(page, "discovery_catalog.png")
        finally:
            context.close()

        soup = BeautifulSoup(html, "html.parser")
        seen_slugs: set = set()
        categories: List[CategoryInfo] = []

        for a in soup.select('a[href^="/f/"]'):
            href = a.get("href", "")
            slug = _clean_slug(href)
            if not slug or slug in seen_slugs:
                continue
            seen_slugs.add(slug)

            name = a.get_text(strip=True) or slug
            url = f"{BASE_URL}/f/{slug}/{city}"
            categories.append(CategoryInfo(id=slug, slug=slug, url=url, name=name))

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

            items = self._parse_page(page, category, city, run_id)
            for item in items:
                all_items[item.product_url] = item
            logger.debug("Page 1: %d items, cumulative %d", len(items), len(all_items))

            for page_num in range(2, max_pages + 1):
                page_url = f"{category.url}?page={page_num}"
                logger.debug("Page %d/%d: %s", page_num, max_pages, page_url)

                page.goto(page_url, wait_until="domcontentloaded", timeout=60_000)
                page.wait_for_timeout(1_500)

                items = self._parse_page(page, category, city, run_id)
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
        """
        Extract total pages from the 'Страница X из Y' counter.
        Falls back to scanning ?page=N links if the counter is absent.
        """
        try:
            body_text = page.inner_text("body")
            m = MAX_PAGES_RE.search(body_text)
            if m:
                return int(m.group(1))
        except Exception:
            pass

        # Fallback: collect max from pagination href attributes
        html = page.content()
        soup = BeautifulSoup(html, "html.parser")
        max_page = 1
        for a in soup.select('a[href*="page="]'):
            pm = re.search(r"[?&]page=(\d+)", a.get("href", ""))
            if pm:
                max_page = max(max_page, int(pm.group(1)))
        return max_page

    # -- Page parsing -------------------------------------------------------

    def _parse_page(
        self,
        page: Page,
        category: CategoryInfo,
        city: str,
        run_id: str,
    ) -> List[PriceObservation]:
        """
        Parse one listing page.

        Uses window.insider_object.listing.items (embedded server-side JS) for
        structured product names and prices. Product URLs are collected from
        a[href^="/g/"] elements in DOM order, which matches the JS object order.
        The two lists are zipped by position.
        """
        captured = datetime.now(timezone.utc).isoformat()

        # Pull structured data from the embedded insider_object
        js_items: List[dict] = page.evaluate(
            """() => {
                try {
                    return (window.insider_object.listing.items || []).map(i => ({
                        name: i.name || '',
                        price: i.unit_sale_price
                    }));
                } catch (e) {
                    return [];
                }
            }"""
        )

        # Collect unique product hrefs in DOM order (strip #fragments to deduplicate)
        product_hrefs: List[str] = page.evaluate(
            """() => {
                const seen = new Set();
                const result = [];
                document.querySelectorAll('a[href^="/g/"]').forEach(el => {
                    const raw = el.getAttribute('href') || '';
                    const h = raw.split('#')[0];  // strip fragment (#buyCheaperTab etc.)
                    if (h && !seen.has(h)) {
                        seen.add(h);
                        result.push(h);
                    }
                });
                return result;
            }"""
        )

        if not js_items or not product_hrefs:
            logger.debug(
                "No data on page (insider_items=%d hrefs=%d)",
                len(js_items), len(product_hrefs),
            )
            return []

        n = min(len(js_items), len(product_hrefs))
        if len(js_items) != len(product_hrefs):
            logger.warning(
                "Count mismatch: insider_items=%d hrefs=%d — using first %d",
                len(js_items), len(product_hrefs), n,
            )

        observations: List[PriceObservation] = []
        seen_urls: set = set()

        for i in range(n):
            href = product_hrefs[i]
            product_url = BASE_URL + href
            if product_url in seen_urls:
                continue
            seen_urls.add(product_url)

            name = (js_items[i].get("name") or "").strip()
            if not name:
                continue

            price_raw = js_items[i].get("price")
            if price_raw is None:
                continue
            try:
                price = int(float(price_raw))
            except (TypeError, ValueError):
                continue
            if price < 10:
                continue

            observations.append(
                PriceObservation(
                    run_id=run_id,
                    market="sulpak.kz",
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

        return observations


# ---------------------------------------------------------------------------
# Registration — makes this market available to the runner
# ---------------------------------------------------------------------------

def _register() -> None:
    from ..core.runner import register_market
    register_market("sulpak", SulpakMarket)


_register()
