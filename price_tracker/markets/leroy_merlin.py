"""
Leroy Merlin Kazakhstan market adapter.

leroymerlin.kz is served by the lemanapro.kz platform (React SSR).
All requests redirect through servicepipe.ru bot protection, which is
bypassed by removing navigator.webdriver via an init script.

Category discovery: /catalogue/ page — all /catalogue/{slug}/ links.
Product listing: [data-qa="product"] cards with URL-based ?page=N pagination.
Price: [data-testid="price-integer"] — clean integer, strip spaces.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from playwright.sync_api import BrowserContext

from ..core.models import CategoryInfo, PriceObservation
from .base import BaseMarket

logger = logging.getLogger("price_tracker.leroy_merlin")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE = "https://lemanapro.kz"
CATALOGUE_URL = "https://lemanapro.kz/catalogue/"

# User-agent that passes servicepipe.ru JS challenge in headless mode
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# Removes navigator.webdriver flag, bypassing the bot-detection challenge
ANTI_BOT_SCRIPT = "delete Object.getPrototypeOf(navigator).webdriver"

PRODUCT_CARD_SEL = '[data-qa="product"]'
PRODUCT_LINK_SEL = 'a[href*="/product/"]'
NAME_SEL = ".product-card-name-link"
PRICE_INT_SEL = '[data-testid="price-integer"]'


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_slug(path: str) -> str:
    """Return the category slug from a /catalogue/{slug}/ path."""
    return path.strip("/").split("/")[-1]


def _max_page_from_html(soup: BeautifulSoup) -> int:
    """Extract highest page number from ?page=N pagination links.

    Page 0 is the disabled 'previous' button on page 1 — skip it.
    Returns 1 if no pagination found.
    """
    nums = []
    for a in soup.select('a[href*="?page="]'):
        href = a.get("href", "")
        m = re.search(r"[?&]page=(\d+)", href)
        if m:
            n = int(m.group(1))
            if n > 0:  # skip page=0 (disabled prev)
                nums.append(n)
    return max(nums) if nums else 1


def _to_int_price(text: str) -> Optional[int]:
    """Strip whitespace/NBSP, return integer price or None."""
    cleaned = re.sub(r"[\s\xa0\u202f]+", "", text)
    try:
        return int(cleaned)
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# LeroyMerlinMarket adapter
# ---------------------------------------------------------------------------

class LeroyMerlinMarket(BaseMarket):
    """Leroy Merlin Kazakhstan (lemanapro.kz) price scraper."""

    @property
    def market_name(self) -> str:
        return "leroy_merlin"

    @property
    def supported_cities(self) -> List[str]:
        # No city-based URL routing; single catalogue for Kazakhstan
        return ["almaty"]

    def _new_context(self) -> BrowserContext:
        """Override to inject anti-bot UA and init script."""
        ctx = self.browser.new_context(
            locale="ru-RU",
            viewport={"width": 1280, "height": 900},
            user_agent=UA,
            ignore_https_errors=True,
        )
        ctx.add_init_script(ANTI_BOT_SCRIPT)
        return ctx

    # -- Category discovery -------------------------------------------------

    def discover_categories(self, city: str) -> List[CategoryInfo]:
        """Load the catalogue index and extract all /catalogue/{slug}/ links."""
        logger.info("Discovering categories from %s", CATALOGUE_URL)

        context = self._new_context()
        page = context.new_page()

        try:
            page.goto(CATALOGUE_URL, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(4_000)

            self.dbg.save_screenshot(page, "discovery_catalog.png")
            self.dbg.save_html(page.content(), "discovery_catalog.html")

            hrefs: List[str] = page.eval_on_selector_all(
                'a[href*="/catalogue/"]',
                """els => [...new Set(
                    els.map(e => e.getAttribute('href'))
                       .filter(h => h && h !== '/catalogue/' && !h.startsWith('http'))
                )]""",
            )
        finally:
            context.close()

        categories: List[CategoryInfo] = []
        seen: set = set()

        for href in hrefs:
            # Only depth-1 catalogue paths: /catalogue/{slug}/
            parts = href.strip("/").split("/")
            if len(parts) != 2 or parts[0] != "catalogue":
                continue

            slug = parts[1]
            if not slug or slug in seen:
                continue
            seen.add(slug)

            url = BASE + href.rstrip("/") + "/"
            categories.append(CategoryInfo(id=slug, slug=slug, url=url))

        categories.sort(key=lambda c: c.slug)

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
        """Crawl all pages of a single category using URL-based pagination."""
        all_items: dict = {}  # keyed by product_url for dedup
        base_url = category.url.rstrip("/") + "/"

        logger.info("Crawling %s (category %s)", category.slug, category.id)

        context = self._new_context()
        page = context.new_page()

        try:
            # Page 1: no ?page= param
            page.goto(base_url, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(3_000)

            self.dbg.save_screenshot(page, "stage1_page1.png")

            html = page.content()
            soup = BeautifulSoup(html, "html.parser")

            # If no product cards: parent/empty category — return early
            if not soup.select(PRODUCT_CARD_SEL):
                logger.info("No product cards on %s — skipping", category.slug)
                return []

            max_pages = _max_page_from_html(soup)
            logger.debug("Max pages: %d", max_pages)

            items = self._parse_page(soup, category, city, run_id)
            for item in items:
                all_items[item.product_url] = item
            logger.debug("Page 1: %d items, cumulative %d", len(items), len(all_items))

            # Pages 2..N
            for page_num in range(2, max_pages + 1):
                page_url = f"{base_url}?page={page_num}"
                logger.debug("Page %d/%d: %s", page_num, max_pages, page_url)

                page.goto(page_url, wait_until="domcontentloaded", timeout=60_000)
                page.wait_for_timeout(2_000)

                items = self._parse_page(
                    BeautifulSoup(page.content(), "html.parser"),
                    category, city, run_id,
                )
                for item in items:
                    all_items[item.product_url] = item

                logger.debug(
                    "Page %d: %d items, cumulative %d",
                    page_num, len(items), len(all_items),
                )

                self.dbg.save_screenshot(page, f"stage2_page{page_num}.png")
        finally:
            context.close()

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
        items: List[PriceObservation] = []
        seen: set = set()

        for card in soup.select(PRODUCT_CARD_SEL):
            # Product URL
            link_el = card.select_one(PRODUCT_LINK_SEL)
            if not link_el:
                continue
            href = link_el.get("href", "")
            if not href:
                continue
            product_url = urljoin(BASE, href.split("?")[0].split("#")[0])
            if product_url in seen:
                continue

            # Product name
            name_el = card.select_one(NAME_SEL)
            if name_el:
                name = name_el.get_text(strip=True)
            else:
                # Fallback: aria-label on the product image link
                img_link = card.select_one('[data-qa="product-image"]')
                name = img_link.get("aria-label", "").strip() if img_link else ""
            if not name:
                continue

            # Price
            price_el = card.select_one(PRICE_INT_SEL)
            if not price_el:
                continue
            price = _to_int_price(price_el.get_text(strip=True))
            if price is None:
                continue

            seen.add(product_url)
            items.append(
                PriceObservation(
                    run_id=run_id,
                    market="leroymerlin.kz",
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
    register_market("leroy_merlin", LeroyMerlinMarket)


_register()
