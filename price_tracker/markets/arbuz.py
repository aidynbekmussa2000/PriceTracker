"""
Arbuz.kz market adapter.

Scrapes product prices from arbuz.kz using Playwright (Chromium) for
rendering the Vue SPA and BeautifulSoup for parsing the rendered HTML.

Ported from the standalone parser_arbuz.py + orchestrator_arbuz.py.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote, urljoin, urlparse

from bs4 import BeautifulSoup, Tag
from playwright.sync_api import Page

from ..core.models import CategoryInfo, PriceObservation
from .base import BaseMarket

logger = logging.getLogger("price_tracker.arbuz")

# ---------------------------------------------------------------------------
# Regex patterns (ported verbatim from parser_arbuz.py)
# ---------------------------------------------------------------------------

PRICE_RE = re.compile(r"(\d[\d\s\xa0]*)\s*₸")

PER_RE = re.compile(r"за\s*([\d.,]+)\s*(кг|г|л|мл|шт)\b", re.IGNORECASE)
SLASH_RE = re.compile(r"/\s*(кг|г|л|мл|шт)\b", re.IGNORECASE)
UNIT_MAP = {"кг": "kg", "г": "g", "л": "l", "мл": "ml", "шт": "pcs"}

PACK_RE = re.compile(
    r"\b(\d{1,4}(?:[.,]\d+)?)\s*(кг|г|л|мл|kg|g|l|ml)\b", re.IGNORECASE
)
PACK_UNIT_MAP = {
    "кг": "kg", "г": "g", "л": "l", "мл": "ml",
    "kg": "kg", "g": "g", "l": "l", "ml": "ml",
}

# ---------------------------------------------------------------------------
# CSS selectors
# ---------------------------------------------------------------------------

PRODUCT_SEL = 'a[href*="/catalog/item/"][title]'
PAGINATION_SEL = "ul.arbuz-pagination"
CAT_SEL = 'a[href*="/catalog/cat/"]'


# ---------------------------------------------------------------------------
# Static parsing helpers
# ---------------------------------------------------------------------------

def _to_int_price(s: str) -> int:
    """Clean whitespace/NBSP from a price string and return int."""
    cleaned = re.sub(r"\s+", "", s.replace("\xa0", " "))
    return int(cleaned)


def _parse_price_unit(text: str) -> Tuple[Optional[str], Optional[float], Optional[str]]:
    """Extract unit code, quantity, and raw match from card text."""
    m = PER_RE.search(text)
    if m:
        qty = float(m.group(1).replace(",", "."))
        unit_code = UNIT_MAP.get(m.group(2).lower(), m.group(2).lower())
        return unit_code, qty, f"за {m.group(1)} {m.group(2)}"
    m = SLASH_RE.search(text)
    if m:
        unit_code = UNIT_MAP.get(m.group(1).lower(), m.group(1).lower())
        return unit_code, 1.0, f"/{m.group(1)}"
    return None, None, None


def _parse_pack_from_name(name: str) -> Tuple[Optional[float], Optional[str]]:
    """Extract pack quantity and unit from product name (e.g. '100 г')."""
    norm = re.sub(r"\s+", " ", name.replace("\xa0", " ")).strip()
    m = PACK_RE.search(norm)
    if not m:
        return None, None
    qty = float(m.group(1).replace(",", "."))
    unit_raw = m.group(2).lower()
    return qty, PACK_UNIT_MAP.get(unit_raw, unit_raw)


def _extract_category_id(url: str) -> Optional[str]:
    """Extract numeric category ID from /catalog/cat/{id}-{slug} URL."""
    m = re.search(r"/catalog/cat/(\d+)-", urlparse(url).path)
    return m.group(1) if m else None


def _find_full_card(start: Tag, max_up: int = 14) -> Optional[Tag]:
    """Walk up to 14 parents to find a card with .price--wrapper + product link."""
    node: Any = start
    for _ in range(max_up):
        if not isinstance(node, Tag):
            return None
        if node.select_one(".price--wrapper") and node.select_one(
            'a[href*="/catalog/item/"]'
        ):
            return node
        node = node.parent
    return None


# ---------------------------------------------------------------------------
# Playwright navigation helpers
# ---------------------------------------------------------------------------

def _dismiss_overlays(page: Page) -> None:
    """Remove all modal overlays that could block clicks on the page."""
    removed = page.evaluate("""() => {
        const sels = [
            '.super-app-modal-overlay',
            '.modal.show',
            '.modal-background.show',
            '[class*="modal-overlay"]',
        ];
        let count = 0;
        for (const sel of sels) {
            document.querySelectorAll(sel).forEach(el => { el.remove(); count++; });
        }
        document.querySelectorAll('.modal-backdrop').forEach(el => { el.remove(); count++; });
        return count;
    }""")
    if removed:
        logger.debug("Dismissed %d overlay(s)", removed)


def _wait_for_products(page: Page, timeout_ms: int = 30_000) -> int:
    """Wait for product anchors to appear; return their count."""
    page.wait_for_selector(PRODUCT_SEL, state="attached", timeout=timeout_ms)
    return page.locator(PRODUCT_SEL).count()


def _get_first_product_href(page: Page) -> Optional[str]:
    """Return the href of the first product anchor, or None."""
    loc = page.locator(PRODUCT_SEL).first
    try:
        return loc.get_attribute("href", timeout=2_000)
    except Exception:
        return None


def _click_page_number(page: Page, page_num: int, timeout_ms: int = 15_000) -> None:
    """
    Click a numbered pagination button inside ul.arbuz-pagination.

    Must click (not URL-navigate) because the Vue SPA loses pagination
    state on full page reload. Waits for first product href to change
    as proof of re-render.
    """
    _dismiss_overlays(page)
    before_href = _get_first_product_href(page)

    btn = page.locator(f"{PAGINATION_SEL} li a").filter(
        has_text=re.compile(rf"^{page_num}$")
    )
    if btn.count() == 0:
        raise RuntimeError(
            f"Pagination button '{page_num}' not found in {PAGINATION_SEL}"
        )

    btn.first.scroll_into_view_if_needed()
    btn.first.click()

    page.wait_for_function(
        """(params) => {
            const a = document.querySelector(params.sel);
            if (!a) return false;
            const now = a.getAttribute('href');
            return now && now !== params.before;
        }""",
        arg={"sel": PRODUCT_SEL, "before": before_href or ""},
        timeout=timeout_ms,
    )
    page.wait_for_timeout(800)  # settle time for full grid render


def _detect_max_pages(page: Page, max_guard: int = 50) -> Tuple[int, List[int]]:
    """Scrape numeric text from DOM to detect max pagination page number."""
    raw: List[int] = page.eval_on_selector_all(
        "a,button,span",
        r"""els => els
            .map(e => (e.innerText || "").trim())
            .filter(t => /^\d+$/.test(t))
            .map(t => parseInt(t, 10))""",
    )
    candidates = sorted(set(n for n in raw if 1 <= n <= max_guard))
    return (max(candidates) if candidates else 1), candidates


# ---------------------------------------------------------------------------
# ArbuzMarket adapter
# ---------------------------------------------------------------------------

class ArbuzMarket(BaseMarket):
    """Arbuz.kz price scraper adapter."""

    @property
    def market_name(self) -> str:
        return "arbuz"

    @property
    def supported_cities(self) -> List[str]:
        return ["almaty"]

    # -- Category discovery -------------------------------------------------

    def discover_categories(self, city: str) -> List[CategoryInfo]:
        """Load the catalog index page and extract all category links."""
        catalog_url = f"https://arbuz.kz/ru/{city}/catalog"
        logger.info("Discovering categories from %s", catalog_url)

        context = self._new_context()
        page = context.new_page()

        try:
            page.goto(catalog_url, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(1_000)
            _dismiss_overlays(page)

            page.wait_for_selector(CAT_SEL, state="attached", timeout=30_000)

            hrefs: List[str] = page.eval_on_selector_all(
                CAT_SEL,
                "els => [...new Set(els.map(e => e.getAttribute('href'))"
                ".filter(h => h && h.includes('/catalog/cat/')))]",
            )

            self.dbg.save_html(page.content(), "discovery_catalog.html")
            self.dbg.save_screenshot(page, "discovery_catalog.png")
        finally:
            context.close()

        # Build structured records
        base = "https://arbuz.kz"
        categories: List[CategoryInfo] = []
        seen_ids: set = set()

        for href in hrefs:
            url = href if href.startswith("http") else base + href
            cat_id = _extract_category_id(url)
            if not cat_id or cat_id in seen_ids:
                continue
            seen_ids.add(cat_id)

            m = re.search(r"/catalog/cat/\d+-(.+?)(?:[#?]|$)", urlparse(url).path)
            slug = m.group(1) if m else cat_id

            categories.append(
                CategoryInfo(id=cat_id, slug=slug, url=url.split("#")[0])
            )

        categories.sort(key=lambda c: int(c.id))

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
        """Crawl all pages of a single category and return parsed observations."""
        base_url = category.url.split("#")[0]
        all_items: Dict[str, PriceObservation] = {}  # keyed by product_url for dedup
        all_diags: List[Dict[str, Any]] = []

        logger.info("Crawling %s (category %s)", category.slug, category.id)

        context = self._new_context()
        page = context.new_page()

        try:
            # Stage 1: initial page load
            page.goto(base_url, wait_until="domcontentloaded", timeout=60_000)
            _wait_for_products(page)
            page.wait_for_timeout(800)
            _dismiss_overlays(page)

            self.dbg.save_screenshot(page, "stage1_initial.png")

            # Stage 2: detect pagination
            max_pages, candidates = _detect_max_pages(page)
            logger.debug(
                "Pagination candidates: %s  max_pages=%d", candidates, max_pages
            )

            self.dbg.save_html(page.content(), "stage2_page1.html")
            self.dbg.save_screenshot(page, "stage2_page1.png")

            # Stage 3: per-page crawl
            for page_num in range(1, max_pages + 1):
                logger.debug("Page %d/%d", page_num, max_pages)

                if page_num > 1:
                    _click_page_number(page, page_num)

                html = page.content()
                items, diag = self._parse_page_html(
                    html, category, city, run_id, page_num
                )
                all_diags.append(diag)

                self.dbg.save_screenshot(page, f"stage3_page{page_num}.png")
                self.dbg.save_html(html, f"stage3_page{page_num}.html")

                for item in items:
                    all_items[item.product_url] = item

                logger.debug(
                    "Page %d: parsed=%d cumulative=%d",
                    page_num, len(items), len(all_items),
                )
        finally:
            context.close()

        # Stage 4: summary
        logger.info(
            "Category %s done: %d unique items across %d pages",
            category.id, len(all_items), len(all_diags),
        )

        return list(all_items.values())

    # -- HTML parsing -------------------------------------------------------

    def _parse_page_html(
        self,
        html: str,
        category: CategoryInfo,
        city: str,
        run_id: str,
        page_num: int,
    ) -> Tuple[List[PriceObservation], Dict[str, Any]]:
        """Parse one page of rendered HTML into PriceObservation objects."""
        soup = BeautifulSoup(html, "html.parser")
        base_url = f"{urlparse(category.url).scheme}://{urlparse(category.url).netloc}"
        captured = datetime.now(timezone.utc).isoformat()

        links = soup.select(PRODUCT_SEL)
        diag: Dict[str, Any] = {
            "page_num": page_num,
            "raw_anchors": len(links),
            "no_href_title": 0,
            "duplicate_url": 0,
            "no_card": 0,
            "no_price": 0,
            "parsed_ok": 0,
        }

        items: List[PriceObservation] = []
        seen: set = set()

        for a in links:
            href = a.get("href")
            title = a.get("title")
            if not href or not title:
                diag["no_href_title"] += 1
                continue

            product_url = urljoin(base_url, href.split("#")[0])
            if product_url in seen:
                diag["duplicate_url"] += 1
                continue

            name = title.strip()
            pack_qty, pack_unit = _parse_pack_from_name(name)

            card = _find_full_card(a)
            if not card:
                diag["no_card"] += 1
                continue

            pw = card.select_one(".price--wrapper")
            if not pw:
                diag["no_card"] += 1
                continue

            # Primary: direct text node inside .price--wrapper
            price: Optional[int] = None
            direct = pw.find(string=True, recursive=False)
            if direct and direct.strip():
                try:
                    price = _to_int_price(direct.strip())
                except ValueError:
                    price = None

            # Fallback: regex over full wrapper text
            if price is None:
                m = PRICE_RE.search(pw.get_text(" ", strip=True))
                if not m:
                    diag["no_price"] += 1
                    continue
                try:
                    price = _to_int_price(m.group(1))
                except ValueError:
                    diag["no_price"] += 1
                    continue

            card_text = card.get_text(" ", strip=True)
            unit_code, unit_qty, _unit_raw = _parse_price_unit(card_text)

            seen.add(product_url)
            diag["parsed_ok"] += 1

            items.append(
                PriceObservation(
                    run_id=run_id,
                    market="arbuz.kz",
                    city=city,
                    category_id=category.id,
                    category_url=category.url.split("#")[0],
                    product_url=product_url,
                    name=name,
                    price_current=price,
                    currency="KZT",
                    unit_code=unit_code,
                    unit_qty=unit_qty,
                    pack_qty=pack_qty,
                    pack_unit=pack_unit,
                    captured_at=captured,
                )
            )

        return items, diag


# ---------------------------------------------------------------------------
# Registration — makes this market available to the runner
# ---------------------------------------------------------------------------

def _register() -> None:
    from ..core.runner import register_market
    register_market("arbuz", ArbuzMarket)


_register()
