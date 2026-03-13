"""
Lamoda.kz market adapter.

lamoda.kz is a Vue/Nuxt SPA with bot-detection (403 on plain requests).
Playwright is required for JS rendering. Bot detection is bypassed by
removing the navigator.webdriver property (same technique as leroy_merlin).

Category discovery: loads the main page and extracts /c/{id}/{slug}/ links
from the rendered navigation.

Product listing: SSR HTML already contains product cards in preloader state.
Card container class is "x-product-card__card" (BEM element of base block).
Brand, product name, and current price are present in SSR HTML.

Pagination: URL-based ?page=N.  Max page detected from embedded JSON
"pagination":{"pages":N} in SSR HTML (Lamoda does not render anchor-based pagination).
"""
from __future__ import annotations

import logging
import re
import unicodedata
from datetime import datetime, timezone
from typing import List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from playwright.sync_api import BrowserContext

from ..core.models import CategoryInfo, PriceObservation
from .base import BaseMarket

logger = logging.getLogger("price_tracker.lamoda")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE = "https://www.lamoda.kz"

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# Removes the webdriver flag that triggers bot-detection JS challenges
ANTI_BOT_SCRIPT = "delete Object.getPrototypeOf(navigator).webdriver"

# CSS selectors — confirmed from SSR HTML
# Card container: class "x-product-card__card" (NOT "x-product-card" which doesn't exist)
PRODUCT_CARD_SEL = ".x-product-card__card"
# Product URL is on the image anchor: <a href="/p/{sku}/{slug}/">
PRODUCT_LINK_SEL = 'a[href*="/p/"]'
BRAND_SEL = ".x-product-card-description__brand-name"
NAME_SEL = ".x-product-card-description__product-name"
# Sale/discounted price (includes ₸ symbol); always prefer this
PRICE_NEW_SEL = ".x-product-card-description__price-new"
# Non-sale products may use a plain price class (no -new/-old modifier)
PRICE_PLAIN_SEL = ".x-product-card-description__price:not(.x-product-card-description__price-old)"

PRICE_RE = re.compile(r"([\d\s\xa0\u202f]+)\s*[₸тТ]")
CAT_RE = re.compile(r"/c/(\d+)/([^/?#]+)")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_int_price(text: str) -> Optional[int]:
    """Strip whitespace/NBSP/narrow-space and return int price, or None."""
    cleaned = re.sub(r"[\s\xa0\u202f\u00a0]+", "", text)
    try:
        return int(cleaned)
    except (ValueError, TypeError):
        return None


def _parse_price(text: str) -> Optional[int]:
    """Extract integer price from a string like '7 780 ₸'."""
    m = PRICE_RE.search(text)
    if not m:
        return None
    return _to_int_price(m.group(1))


PAGINATION_RE = re.compile(r'"pagination"\s*:\s*\{[^}]*"pages"\s*:\s*(\d+)')

# ---------------------------------------------------------------------------
# Inflation-basket category whitelist
# ---------------------------------------------------------------------------
# Keys are internal CPI labels; values are Russian keyword substrings matched
# against the category's visible navigation label (case-insensitive, NFKC-normalised).
# Add / remove keywords here to tune coverage without touching scraping logic.

INFLATION_CATEGORY_MAPPING: dict = {
    "outerwear_men":   ["пуховик", "куртка", "ветровка", "пальто", "муж"],
    "classic_men":     ["костюм", "брюки классические", "сорочка", "муж"],
    "casual_men":      ["джинсы", "свитер", "джемпер", "толстовка", "футболка", "майка", "муж"],
    "underwear_men":   ["трусы", "носки", "муж"],
    "outerwear_women": ["пуховик", "куртка", "ветровка", "пальто", "жен"],
    "classic_women":   ["костюм", "блузка", "юбка", "платье", "жен"],
    "casual_women":    ["свитер", "джемпер", "футболка", "джинсы", "брюки", "жен"],
    "underwear_women": ["нижнее белье", "колготки", "жен"],
    "boys":       ["мальчик", "для мальчиков", "футболка", "спортивный костюм", "толстовка", "носки", "трусы"],
    "girls":      ["девочка", "для девочек", "платье", "футболка", "колготки", "толстовка", "носки", "трусы"],
    "babies":     ["младен", "до 2 лет", "комбинезон", "базовая одежда"],
    "school":     ["школьн", "форма", "кардиган", "жилет", "брюки школьные", "юбка школьная", "блузка школьная"],
    "accessories": ["шапка", "кепка", "берет", "шарф", "палантины", "галстук", "ремень", "перчатки", "варежки"],
}


def normalize_category_name(name: str) -> str:
    """Lowercase + Unicode-normalize a category label for keyword matching."""
    return unicodedata.normalize("NFKC", name).lower().strip()


def is_relevant_category(name: str) -> bool:
    """Return True if *name* contains at least one inflation-basket keyword."""
    normalized = normalize_category_name(name)
    for keywords in INFLATION_CATEGORY_MAPPING.values():
        if any(kw in normalized for kw in keywords):
            return True
    return False


def _max_page_from_html(html: str) -> int:
    """Extract total page count from embedded JSON pagination data.

    Lamoda SSR embeds: "pagination":{"page":1,"pages":N,...}
    Falls back to 1 if not found.
    """
    m = PAGINATION_RE.search(html)
    if m:
        return int(m.group(1))
    return 1


# ---------------------------------------------------------------------------
# LamodaMarket adapter
# ---------------------------------------------------------------------------

class LamodaMarket(BaseMarket):
    """Lamoda.kz fashion marketplace price scraper."""

    @property
    def market_name(self) -> str:
        return "lamoda"

    @property
    def supported_cities(self) -> List[str]:
        # Lamoda has no city-based URL routing for Kazakhstan
        return ["almaty"]

    def _new_context(self) -> BrowserContext:
        """Override to inject anti-bot UA and webdriver removal script."""
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
        """Load the main page and extract all /c/{id}/{slug}/ nav links."""
        logger.info("Discovering categories from %s", BASE)

        context = self._new_context()
        page = context.new_page()

        try:
            page.goto(BASE + "/", wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(4_000)

            self.dbg.save_screenshot(page, "discovery_catalog.png")
            self.dbg.save_html(page.content(), "discovery_catalog.html")

            # Extract href + visible text for all /c/{digits}/{slug}/ nav links.
            # Deduplication is done in JS to avoid returning the same href twice.
            hrefs: List[dict] = page.eval_on_selector_all(
                'a[href*="/c/"]',
                """(els) => {
                    const seen = new Set();
                    const results = [];
                    for (const el of els) {
                        const href = el.getAttribute('href');
                        if (!href || !/\\/c\\/\\d+\\/[^/?#]+/.test(href) || href.includes('?')) continue;
                        if (seen.has(href)) continue;
                        seen.add(href);
                        results.push({href, text: (el.innerText || el.textContent || '').trim()});
                    }
                    return results;
                }""",
            )
        finally:
            context.close()

        categories: List[CategoryInfo] = []
        seen_ids: set = set()
        matched = skipped = 0

        for entry in hrefs:
            href = entry.get("href", "")
            display_text = entry.get("text", "")

            # Normalize: strip domain if present
            path = href
            if path.startswith("http"):
                from urllib.parse import urlparse as _up
                path = _up(path).path

            m = CAT_RE.search(path)
            if not m:
                continue
            cat_id = m.group(1)
            slug = m.group(2).rstrip("/")
            if not slug or cat_id in seen_ids:
                continue

            # Use display text for keyword matching; fall back to slug
            label_for_match = display_text or slug.replace("-", " ")

            if not is_relevant_category(label_for_match):
                logger.debug("SKIP category '%s' (slug=%s)", label_for_match, slug)
                skipped += 1
                continue

            logger.info("KEEP category '%s' (slug=%s)", label_for_match, slug)
            matched += 1
            seen_ids.add(cat_id)
            url = BASE + "/c/" + cat_id + "/" + slug + "/"
            categories.append(CategoryInfo(id=cat_id, slug=slug, url=url, name=display_text or slug))

        categories.sort(key=lambda c: c.slug)

        logger.info(
            "Category filter complete: %d kept, %d skipped (total discovered: %d)",
            matched, skipped, matched + skipped,
        )

        if not categories:
            raise RuntimeError(
                "No categories discovered — check navigation or site structure"
            )

        return categories

    # -- Single-category crawl ----------------------------------------------

    def crawl_category(
        self,
        category: CategoryInfo,
        city: str,
        run_id: str,
    ) -> List[PriceObservation]:
        """Crawl all pages of a category with URL-based pagination."""
        all_items: dict = {}  # keyed by product_url for dedup
        base_url = category.url.rstrip("/") + "/"

        logger.info("Crawling %s (category %s)", category.slug, category.id)

        context = self._new_context()
        page = context.new_page()

        try:
            # Page 1
            page.goto(base_url, wait_until="domcontentloaded", timeout=60_000)
            try:
                page.wait_for_selector(
                    PRODUCT_CARD_SEL, state="attached", timeout=20_000
                )
            except Exception:
                logger.info(
                    "No product cards on %s — empty/parent category", category.slug
                )
                return []
            page.wait_for_timeout(1_500)

            self.dbg.save_screenshot(page, "stage1_page1.png")
            html = page.content()
            soup = BeautifulSoup(html, "html.parser")

            if not soup.select(PRODUCT_CARD_SEL):
                logger.info("No product cards after render — skipping %s", category.slug)
                return []

            max_pages = _max_page_from_html(html)
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
                try:
                    page.wait_for_selector(
                        PRODUCT_CARD_SEL, state="attached", timeout=20_000
                    )
                except Exception:
                    logger.warning("No products on page %d — stopping", page_num)
                    break
                page.wait_for_timeout(1_500)

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
        """Parse one rendered page of product cards into PriceObservation objects."""
        captured = datetime.now(timezone.utc).isoformat()
        items: List[PriceObservation] = []
        seen: set = set()

        for card in soup.select(PRODUCT_CARD_SEL):
            # Product URL — image anchor has href="/p/{sku}/{slug}/"
            link_el = card.select_one(PRODUCT_LINK_SEL)
            if not link_el:
                continue
            href = link_el.get("href", "")
            if not href:
                continue
            product_url = urljoin(BASE, href.split("?")[0].split("#")[0])
            if product_url in seen:
                continue

            # Name: combine brand + product description
            brand_el = card.select_one(BRAND_SEL)
            name_el = card.select_one(NAME_SEL)
            brand = brand_el.get_text(strip=True) if brand_el else ""
            name_text = name_el.get_text(strip=True) if name_el else ""
            full_name = f"{brand} {name_text}".strip() if brand else name_text
            if not full_name:
                continue

            # Price: sale price (with ₸) preferred; fall back to any plain price
            price_el = card.select_one(PRICE_NEW_SEL)
            if not price_el:
                price_el = card.select_one(PRICE_PLAIN_SEL)
            if not price_el:
                continue
            price = _parse_price(price_el.get_text(" ", strip=True))
            if price is None:
                continue

            seen.add(product_url)
            items.append(
                PriceObservation(
                    run_id=run_id,
                    market="lamoda.kz",
                    city=city,
                    category_id=category.id,
                    category_url=category.url,
                    product_url=product_url,
                    name=full_name,
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
    register_market("lamoda", LamodaMarket)


_register()
