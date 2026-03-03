#!/usr/bin/env python3
"""
Arbuz.kz category scraper with staged debugging.

Debug stages
------------
STAGE 1  Browser launch + base page load
STAGE 2  Pagination detection (DOM snapshot saved)
STAGE 3  Per-page crawl  (screenshot + HTML dump saved per page)
STAGE 4  Parse + deduplicate summary
STAGE 5  Write JSON output
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote, urljoin, urlparse

from bs4 import BeautifulSoup, Tag
from playwright.sync_api import Page, sync_playwright


# ─────────────────────────────────────────
# Debug helpers
# ─────────────────────────────────────────

DEBUG_DIR = Path("debug_arbuz")


def dbg(stage: int, msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [STAGE {stage}] {msg}", flush=True)


def save_debug_html(html: str, name: str) -> Path:
    DEBUG_DIR.mkdir(exist_ok=True)
    p = DEBUG_DIR / name
    p.write_text(html, encoding="utf-8")
    return p


def save_screenshot(page: Page, name: str) -> Path:
    DEBUG_DIR.mkdir(exist_ok=True)
    p = DEBUG_DIR / name
    page.screenshot(path=str(p), full_page=False, timeout=10_000)
    return p


# ─────────────────────────────────────────
# Regex + normalization helpers
# ─────────────────────────────────────────

PRICE_RE = re.compile(r"(\d[\d\s\xa0]*)\s*₸")

PER_RE   = re.compile(r"за\s*([\d.,]+)\s*(кг|г|л|мл|шт)\b", re.IGNORECASE)
SLASH_RE = re.compile(r"/\s*(кг|г|л|мл|шт)\b",               re.IGNORECASE)
UNIT_MAP = {"кг": "kg", "г": "g", "л": "l", "мл": "ml", "шт": "pcs"}

PACK_RE = re.compile(r"\b(\d{1,4}(?:[.,]\d+)?)\s*(кг|г|л|мл|kg|g|l|ml)\b", re.IGNORECASE)
PACK_UNIT_MAP = {
    "кг": "kg", "г": "g", "л": "l", "мл": "ml",
    "kg": "kg", "g": "g", "l": "l", "ml": "ml",
}


def to_int_price(s: str) -> int:
    cleaned = re.sub(r"\s+", "", s.replace("\xa0", " "))
    return int(cleaned)


def parse_price_unit(text: str) -> Tuple[Optional[str], Optional[float], Optional[str]]:
    m = PER_RE.search(text)
    if m:
        qty       = float(m.group(1).replace(",", "."))
        unit_code = UNIT_MAP.get(m.group(2).lower(), m.group(2).lower())
        return unit_code, qty, f"за {m.group(1)} {m.group(2)}"
    m = SLASH_RE.search(text)
    if m:
        unit_code = UNIT_MAP.get(m.group(1).lower(), m.group(1).lower())
        return unit_code, 1.0, f"/{m.group(1)}"
    return None, None, None


def parse_pack_from_name(name: str) -> Tuple[Optional[float], Optional[str]]:
    norm = re.sub(r"\s+", " ", name.replace("\xa0", " ")).strip()
    m    = PACK_RE.search(norm)
    if not m:
        return None, None
    qty      = float(m.group(1).replace(",", "."))
    unit_raw = m.group(2).lower()
    return qty, PACK_UNIT_MAP.get(unit_raw, unit_raw)


def extract_city(url: str) -> str:
    parts = urlparse(url).path.strip("/").split("/")
    if len(parts) >= 2 and parts[0] in ("ru", "kz", "en"):
        return parts[1]
    return "unknown"


def extract_category_id(url: str) -> Optional[str]:
    m = re.search(r"/catalog/cat/(\d+)-", urlparse(url).path)
    return m.group(1) if m else None


# ─────────────────────────────────────────
# Hash-pagination URL builder
# ─────────────────────────────────────────

def make_page_url(base_url: str, page_num: int) -> str:
    """
    Build the full URL for a given page number using arbuz.kz's hash pagination.

    e.g. https://arbuz.kz/ru/almaty/catalog/cat/225178-ovoshi
         #/?[{"slug":"page","value":2,"component":"pagination"}]
    """
    clean   = base_url.split("#")[0]
    payload = [{"slug": "page", "value": page_num, "component": "pagination"}]
    encoded = quote(json.dumps(payload, separators=(",", ":"), ensure_ascii=False), safe="")
    return f"{clean}#/?{encoded}"


# ─────────────────────────────────────────
# Navigation helpers
# ─────────────────────────────────────────

PRODUCT_SEL    = 'a[href*="/catalog/item/"][title]'
PAGINATION_SEL = "ul.arbuz-pagination"
OVERLAY_SEL    = "div.super-app-modal-overlay"


def dismiss_overlays(page: Page) -> None:
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
        // Also remove any leftover backdrop
        document.querySelectorAll('.modal-backdrop').forEach(el => { el.remove(); count++; });
        return count;
    }""")
    if removed:
        dbg(1, f"Dismissed {removed} overlay(s) blocking the page")


def wait_for_products(page: Page, timeout_ms: int = 30_000) -> int:
    """Wait for product anchors to appear; return their count."""
    page.wait_for_selector(PRODUCT_SEL, state="attached", timeout=timeout_ms)
    return page.locator(PRODUCT_SEL).count()


def get_first_product_href(page: Page) -> Optional[str]:
    """Return the href of the first product anchor on the page, or None."""
    loc = page.locator(PRODUCT_SEL).first
    try:
        return loc.get_attribute("href", timeout=2_000)
    except Exception:
        return None


def click_page_number(page: Page, page_num: int, timeout_ms: int = 15_000) -> None:
    """
    Click a numbered pagination button inside ul.arbuz-pagination.

    The pagination widget is Vue-rendered: <ul class="arbuz-pagination">
    containing <li> > <a> elements with numeric innerText and no href.
    Clicking them is the only reliable way to trigger a page change —
    both page.goto() and window.location.hash manipulation cause the SPA
    to reload from scratch and lose pagination state.

    After clicking, we wait until the first product href changes (proving
    the product grid actually re-rendered with new content).
    """
    # Dismiss any overlays that may have appeared since initial load
    dismiss_overlays(page)

    before_href = get_first_product_href(page)

    # Find the <a> inside the pagination <ul> whose text matches the page number
    btn = page.locator(
        f"{PAGINATION_SEL} li a",
    ).filter(has_text=re.compile(rf"^{page_num}$"))

    if btn.count() == 0:
        raise RuntimeError(
            f"Pagination button '{page_num}' not found in {PAGINATION_SEL}"
        )

    # Scroll the pagination widget into view and click
    btn.first.scroll_into_view_if_needed()
    btn.first.click()

    # Wait for the product grid to update (first product href changes)
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

    # Extra settle time for the full grid to finish rendering
    page.wait_for_timeout(800)


# ─────────────────────────────────────────
# Pagination detection
# ─────────────────────────────────────────

def detect_max_pages(page: Page, max_guard: int = 50) -> Tuple[int, List[int]]:
    """
    Scrape numeric text from <a>, <button>, <span> elements.
    Returns (max_page, sorted list of all candidates found).
    Saving candidates lets the caller log them for debugging.
    """
    raw: List[int] = page.eval_on_selector_all(
        "a,button,span",
        r"""els => els
            .map(e => (e.innerText || "").trim())
            .filter(t => /^\d+$/.test(t))
            .map(t => parseInt(t, 10))""",
    )
    candidates = sorted(set(n for n in raw if 1 <= n <= max_guard))
    return (max(candidates) if candidates else 1), candidates


# ─────────────────────────────────────────
# HTML parser (BeautifulSoup)
# ─────────────────────────────────────────

def find_full_card(start: Tag, max_up: int = 14) -> Optional[Tag]:
    node: Any = start
    for _ in range(max_up):
        if not isinstance(node, Tag):
            return None
        if node.select_one(".price--wrapper") and node.select_one('a[href*="/catalog/item/"]'):
            return node
        node = node.parent
    return None


def parse_page_html(
    html: str,
    category_url: str,
    page_num: int,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Parse one page of rendered HTML.

    Returns
    -------
    items   : list of product dicts
    diag    : per-step counts for debugging (raw anchors, parse failures, etc.)
    """
    soup     = BeautifulSoup(html, "html.parser")
    base_url = f"{urlparse(category_url).scheme}://{urlparse(category_url).netloc}"
    city     = extract_city(category_url)
    cat_id   = extract_category_id(category_url)
    captured = datetime.now(timezone.utc).isoformat()

    links = soup.select('a[href*="/catalog/item/"][title]')
    diag: Dict[str, Any] = {
        "page_num":      page_num,
        "raw_anchors":   len(links),
        "no_href_title": 0,
        "duplicate_url": 0,
        "no_card":       0,
        "no_price":      0,
        "parsed_ok":     0,
    }

    items: List[Dict[str, Any]] = []
    seen:  set[str]             = set()

    for a in links:
        href  = a.get("href")
        title = a.get("title")
        if not href or not title:
            diag["no_href_title"] += 1
            continue

        product_url = urljoin(base_url, href.split("#")[0])
        if product_url in seen:
            diag["duplicate_url"] += 1
            continue

        name               = title.strip()
        pack_qty, pack_unit = parse_pack_from_name(name)

        card = find_full_card(a)
        if not card:
            diag["no_card"] += 1
            continue

        pw = card.select_one(".price--wrapper")
        if not pw:
            diag["no_card"] += 1
            continue

        # Primary: direct text node inside the price wrapper
        price: Optional[int] = None
        direct = pw.find(string=True, recursive=False)
        if direct and direct.strip():
            try:
                price = to_int_price(direct.strip())
            except ValueError:
                price = None

        # Fallback: regex over the full wrapper text
        if price is None:
            m = PRICE_RE.search(pw.get_text(" ", strip=True))
            if not m:
                diag["no_price"] += 1
                continue
            try:
                price = to_int_price(m.group(1))
            except ValueError:
                diag["no_price"] += 1
                continue

        card_text                     = card.get_text(" ", strip=True)
        unit_code, unit_qty, unit_raw = parse_price_unit(card_text)

        seen.add(product_url)
        diag["parsed_ok"] += 1
        items.append({
            "market":        "arbuz.kz",
            "city":          city,
            "category_id":   cat_id,
            "category_url":  category_url.split("#")[0],
            "product_url":   product_url,
            "name":          name,
            "price_current": price,
            "unit_raw":      unit_raw,
            "unit_code":     unit_code,
            "unit_qty":      unit_qty,
            "pack_qty":      pack_qty,
            "pack_unit":     pack_unit,
            "captured_at":   captured,
            "source":        "listing_playwright_bs4",
        })

    return items, diag


# ─────────────────────────────────────────
# Main crawler
# ─────────────────────────────────────────

def crawl_category(
    category_url: str,
    headless: bool = True,
    save_debug: bool = True,
) -> List[Dict[str, Any]]:
    base      = category_url.split("#")[0]
    all_items: Dict[str, Dict[str, Any]] = {}
    all_diags: List[Dict[str, Any]]      = []

    # ── STAGE 1: Browser launch + initial load ─────────────────────────────
    dbg(1, f"Launching browser  headless={headless}")
    dbg(1, f"Base URL: {base}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            locale="ru-RU",
            viewport={"width": 1280, "height": 900},
        )
        page = context.new_page()

        page.goto(base, wait_until="domcontentloaded", timeout=60_000)
        initial_count = wait_for_products(page)
        page.wait_for_timeout(800)

        dbg(1, f"Initial page loaded. Visible product anchors: {initial_count}")

        # Dismiss any modal overlays (app-download popup) that block clicks
        dismiss_overlays(page)

        if save_debug:
            ss = save_screenshot(page, "stage1_initial.png")
            dbg(1, f"Screenshot saved → {ss}")

        # ── STAGE 2: Pagination detection ──────────────────────────────────
        dbg(2, "Detecting pagination from initial page load …")

        max_pages, candidates = detect_max_pages(page)
        dbg(2, f"Numeric candidates found in DOM: {candidates}")
        dbg(2, f"Detected max pages: {max_pages}")

        if save_debug:
            p1_html = save_debug_html(page.content(), "stage2_page1.html")
            ss      = save_screenshot(page, "stage2_page1.png")
            dbg(2, f"Page-1 HTML → {p1_html}  |  screenshot → {ss}")

            # Dump the exact DOM nodes that contained the numeric candidates
            pag_info: List[Dict] = page.eval_on_selector_all(
                "a,button,span",
                r"""els => els
                    .filter(e => /^\d+$/.test((e.innerText || "").trim()))
                    .map(e => ({
                        tag:     e.tagName,
                        text:    (e.innerText || "").trim(),
                        classes: e.className,
                        href:    e.getAttribute('href') || ""
                    }))""",
            )
            pag_file = DEBUG_DIR / "stage2_pagination_nodes.json"
            pag_file.write_text(
                json.dumps(pag_info, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            dbg(2, f"Pagination DOM nodes → {pag_file}")

        # ── STAGE 3: Per-page crawl ────────────────────────────────────────
        for page_num in range(1, max_pages + 1):
            dbg(3, f"── Page {page_num}/{max_pages} ──────────────────────────")

            if page_num == 1:
                dbg(3, "Already on page 1 (initial load), skipping click")
            else:
                dbg(3, f"Clicking pagination button {page_num} …")
                click_page_number(page, page_num)

            current_hash  = page.evaluate("window.location.hash")
            current_url   = page.evaluate("window.location.href")
            live_anchors  = page.locator(PRODUCT_SEL).count()

            dbg(3, f"  URL:          {current_url}")
            dbg(3, f"  Hash:         {current_hash}")
            dbg(3, f"  Live anchors: {live_anchors}")

            html         = page.content()
            items, diag  = parse_page_html(html, category_url, page_num)
            all_diags.append(diag)

            dbg(3, f"  Parse diag:   {diag}")
            dbg(3, f"  Items parsed: {len(items)}")

            if items:
                sample = [it["name"] for it in items[:3]]
                dbg(3, f"  Sample names: {sample}")
            else:
                dbg(3, "  WARNING: 0 items parsed on this page!")

            if save_debug:
                ss       = save_screenshot(page, f"stage3_page{page_num}.png")
                html_out = save_debug_html(html, f"stage3_page{page_num}.html")
                dbg(3, f"  Screenshot → {ss}  |  HTML → {html_out}")

            for it in items:
                all_items[it["product_url"]] = it

            dbg(3, f"  Cumulative unique items: {len(all_items)}")

        browser.close()

    # ── STAGE 4: Deduplication summary ────────────────────────────────────
    dbg(4, "Crawl complete. Per-page parse summary:")
    for d in all_diags:
        dbg(4, (
            f"  page {d['page_num']:>2} | "
            f"raw={d['raw_anchors']:>3}  "
            f"ok={d['parsed_ok']:>3}  "
            f"dup={d['duplicate_url']:>3}  "
            f"no_card={d['no_card']:>3}  "
            f"no_price={d['no_price']:>3}"
        ))
    dbg(4, f"Total unique items across all pages: {len(all_items)}")

    if save_debug:
        diag_file = DEBUG_DIR / "stage4_diagnostics.json"
        diag_file.write_text(
            json.dumps(all_diags, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        dbg(4, f"Full diagnostics saved → {diag_file}")

    return list(all_items.values())


# ─────────────────────────────────────────
# Output
# ─────────────────────────────────────────

def save_json(items: List[Dict[str, Any]], path: str) -> str:
    out = Path(path).resolve()
    out.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(out)


# ─────────────────────────────────────────
# Entrypoint
# ─────────────────────────────────────────

if __name__ == "__main__":
    category = "https://arbuz.kz/ru/almaty/catalog/cat/225178-ovoshi"

    items = crawl_category(category, headless=True, save_debug=True)

    # ── STAGE 5: Write output ──────────────────────────────────────────────
    dbg(5, "Writing JSON output …")
    out_path = save_json(items, "arbuz_ovoshi.json")
    dbg(5, f"Saved → {out_path}  ({len(items)} items total)")

    print("\nFirst 10 items:")
    for x in items[:10]:
        print(
            f"  {x['name']:<50} {x['price_current']:>6}₸"
            f"  unit={x['unit_raw']}  pack={x.get('pack_qty')} {x.get('pack_unit')}"
        )
