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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._seen_hrefs: set = set()

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
        """Crawl all pages of a category via AJAX "load more" button."""
        all_items: Dict[str, PriceObservation] = {}
        self._seen_hrefs = set()  # Reset for each category

        logger.info("Crawling %s", category.slug)

        context = self._new_context()
        page = context.new_page()

        try:
            page.goto(category.url, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(3_000)

            html = page.content()
            self.dbg.save_html(html, f"stage1_category_{category.slug}.html")

            self.dbg.save_screenshot(page, "stage1_page1.png")

            # Parse initial page
            items = self._parse_page(page, category, city, run_id)
            for item in items:
                all_items[item.product_url] = item
            logger.debug("Page 1: %d items, cumulative %d", len(items), len(all_items))

            # Click "load more" button repeatedly until it disappears
            page_num = 2
            while True:
                # Check if "load more" button still exists
                button_exists = page.evaluate(
                    """() => {
                        return !!document.querySelector(
                            '.product__item-more .product__item-inner[data-next-page]'
                        );
                    }"""
                )

                if not button_exists:
                    logger.debug("No more 'load more' button found; pagination complete")
                    break

                logger.debug("Page %d: calling loadMoreProducts function", page_num)

                try:
                    # Call the loadMoreProducts function via JavaScript
                    # This mimics clicking the button without actually clicking it
                    page.evaluate(
                        """() => {
                            const btn = document.querySelector(
                                '.product__item-more .product__item-inner[data-next-page]'
                            );
                            if (btn && typeof loadMoreProducts === 'function') {
                                loadMoreProducts(btn);
                            }
                        }"""
                    )

                    # Wait for AJAX response and DOM updates
                    page.wait_for_timeout(3_000)
                except Exception as e:
                    logger.debug("Failed to call loadMoreProducts: %s", e)
                    break

                # Parse newly loaded products
                items = self._parse_page(page, category, city, run_id)

                if not items:
                    logger.debug("Page %d returned no new items; stopping", page_num)
                    break

                for item in items:
                    all_items[item.product_url] = item

                self.dbg.save_screenshot(page, f"stage2_page{page_num}.png")
                logger.debug(
                    "Page %d: %d items, cumulative %d",
                    page_num, len(items), len(all_items),
                )
                page_num += 1
        finally:
            context.close()

        logger.info(
            "Category %s done: %d unique items", category.slug, len(all_items)
        )
        return list(all_items.values())

    # -- Pagination detection -----------------------------------------------

    @staticmethod
    def _detect_max_pages() -> int:
        """
        Sulpak uses dynamic "load more" pagination with no upfront page count.
        Return a high limit (100) and crawl_category will stop when pages return no items.
        """
        logger.debug("Sulpak uses dynamic pagination; will crawl until empty page")
        return 100  # High limit; loop stops when _parse_page returns no items

    # -- Page parsing -------------------------------------------------------

    def _parse_page(
        self,
        page: Page,
        category: CategoryInfo,
        city: str,
        run_id: str,
    ) -> List[PriceObservation]:
        """
        Parse new products from current page.

        Since Sulpak dynamically loads products, we return only NEW products
        (those not seen in previous pages) by tracking all hrefs. This way,
        each _parse_page call returns ~22 new items from each "load more".
        """
        captured = datetime.now(timezone.utc).isoformat()

        # Get current batch data (most recent 22 items from insider_object)
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

        # Get ALL product hrefs in DOM (accumulated from all pages so far)
        all_product_hrefs: List[str] = page.evaluate(
            """() => {
                const seen = new Set();
                const result = [];
                document.querySelectorAll('a[href^="/g/"]').forEach(el => {
                    const raw = el.getAttribute('href') || '';
                    const h = raw.split('#')[0];
                    if (h && !seen.has(h)) {
                        seen.add(h);
                        result.push(h);
                    }
                });
                return result;
            }"""
        )

        if not js_items or not all_product_hrefs:
            logger.debug(
                "No data on page (insider_items=%d hrefs=%d)",
                len(js_items), len(all_product_hrefs),
            )
            return []

        observations: List[PriceObservation] = []

        # Match the last batch of hrefs with insider_object items
        # The last 22 hrefs should correspond to the 22 items in insider_object
        start_idx = max(0, len(all_product_hrefs) - len(js_items))
        for i in range(start_idx, len(all_product_hrefs)):
            href = all_product_hrefs[i]

            # Skip if we've seen this href before
            if href in self._seen_hrefs:
                continue
            self._seen_hrefs.add(href)

            batch_idx = i - start_idx
            if batch_idx >= len(js_items):
                continue

            product_url = BASE_URL + href
            name = (js_items[batch_idx].get("name") or "").strip()
            price_raw = js_items[batch_idx].get("price")

            if not name:
                continue

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
