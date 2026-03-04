"""
Europharma.kz market adapter.

Europharma is a pharmacy chain in Kazakhstan. The site is server-rendered
(PHP/Yii framework) with PJAX progressive enhancement, so full product HTML
is available in the initial page response. Pagination is URL-based (?page=N).

URL pattern:
    Homepage:       https://europharma.kz/
    Category pages: https://europharma.kz/catalog/{slug}
    Category p2+:   https://europharma.kz/catalog/{slug}?page=N
    Product pages:  https://europharma.kz/{product-slug}

Category discovery:
    Main navigation has two levels:
      - Main categories: a.menu__link[href*="/catalog/"]
      - Subcategories:   a.submenu__link[href*="/catalog/"]
    Only subcategory (leaf) links are used to avoid duplicate products.
    If no subcategories are found, main categories are used as fallback.

Product parsing:
    Cards: div.card-product.sl-item
    Name:  a.card-product__link (text content)
    Link:  a.card-product__link[href] (relative path from root)
    Price: div.card-product[data-price] attribute (integer, KZT)
           fallback: span.card-product__price_discount (text "345 ₸")
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional
from urllib.parse import urljoin, urlparse, urlencode, parse_qs, urlunparse

from bs4 import BeautifulSoup
from playwright.sync_api import Page

from ..core.models import CategoryInfo, PriceObservation
from .base import BaseMarket

logger = logging.getLogger("price_tracker.europharma")

BASE_URL = "https://europharma.kz"

# Price fallback: "345 ₸" or "3 950 ₸" — spaces as thousand separators
PRICE_RE = re.compile(r"([\d][\d\s\xa0]*)\s*₸")


# ---------------------------------------------------------------------------
# Static helpers
# ---------------------------------------------------------------------------

def _to_int_price(s: str) -> int:
    """Remove thousand separators (spaces, NBSP) and convert to int."""
    cleaned = re.sub(r"[\s\xa0]+", "", s)
    return int(cleaned)


def _page_url(base: str, page_num: int) -> str:
    """Return URL for page N: base for page 1, base?page=N for N>=2."""
    if page_num <= 1:
        return base
    parsed = urlparse(base)
    qs = f"page={page_num}"
    # Preserve any existing query params (unlikely but safe)
    if parsed.query:
        qs = parsed.query + "&" + qs
    return urlunparse(parsed._replace(query=qs))


def _detect_max_pages(soup: BeautifulSoup) -> int:
    """
    Detect max page number from ul.pagination.

    Links use href="/catalog/slug?page=N" — extract highest N.
    Returns 1 if no pagination is present.
    """
    pag = soup.select_one("ul.pagination")
    if not pag:
        return 1

    max_page = 1
    for a in pag.select("a.pagination__link[href]"):
        href = a.get("href", "")
        m = re.search(r"[?&]page=(\d+)", href)
        if m:
            max_page = max(max_page, int(m.group(1)))

    return max_page


# ---------------------------------------------------------------------------
# EuropharmaMarket adapter
# ---------------------------------------------------------------------------

class EuropharmaMarket(BaseMarket):
    """Europharma.kz pharmacy price scraper (server-rendered, URL pagination)."""

    @property
    def market_name(self) -> str:
        return "europharma"

    @property
    def supported_cities(self) -> List[str]:
        # Europharma doesn't use city slugs in URLs; operates across Kazakhstan.
        return ["almaty"]

    # -- Category discovery -------------------------------------------------

    def discover_categories(self, city: str) -> List[CategoryInfo]:
        """
        Load the homepage and extract subcategory links from main nav.

        Subcategory links (a.submenu__link) are preferred over main
        category links (a.menu__link) to avoid collecting duplicate
        products from parent categories that include all subcategory items.
        """
        logger.info("Discovering categories from %s", BASE_URL)

        context = self._new_context()
        page = context.new_page()

        try:
            page.goto(BASE_URL, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(1_500)
            html = page.content()

            self.dbg.save_html(html, "discovery_homepage.html")
            self.dbg.save_screenshot(page, "discovery_homepage.png")
        finally:
            context.close()

        soup = BeautifulSoup(html, "html.parser")

        # Prefer subcategory (leaf) links
        sub_links = soup.select("a.submenu__link[href]")
        catalog_links = [
            a for a in sub_links
            if "/catalog/" in (a.get("href") or "")
        ]

        # Fallback: main nav categories
        if not catalog_links:
            logger.warning("No submenu links found; falling back to menu__link")
            catalog_links = [
                a for a in soup.select("a.menu__link[href]")
                if "/catalog/" in (a.get("href") or "")
            ]

        categories: List[CategoryInfo] = []
        seen_slugs: set = set()

        for a in catalog_links:
            href = a.get("href", "")
            text = a.get_text(strip=True)

            url = href if href.startswith("http") else urljoin(BASE_URL, href)
            # Strip query params and fragments for canonical URL
            url = url.split("?")[0].split("#")[0]

            # Extract slug: last non-empty path segment
            path = urlparse(url).path.strip("/")
            parts = path.split("/")
            # Expect /catalog/slug — skip bare /catalog/
            if not parts or parts[-1] in ("", "catalog"):
                continue

            slug = parts[-1]
            if slug in seen_slugs:
                continue
            seen_slugs.add(slug)

            categories.append(
                CategoryInfo(
                    id=slug,
                    slug=slug,
                    url=url,
                    name=text or None,
                )
            )

        if not categories:
            raise RuntimeError(
                "No categories discovered from europharma.kz nav — check site structure"
            )

        categories.sort(key=lambda c: c.slug)
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
        base_url = category.url
        all_items: Dict[str, PriceObservation] = {}

        logger.info("Crawling %s (category %s)", category.slug, category.id)

        context = self._new_context()
        page = context.new_page()

        try:
            # Load first page to detect max pages
            page.goto(base_url, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(1_500)

            html = page.content()
            self.dbg.save_html(html, "stage1_page1.html")
            self.dbg.save_screenshot(page, "stage1_page1.png")

            soup = BeautifulSoup(html, "html.parser")
            max_pages = _detect_max_pages(soup)
            logger.debug("Max pages: %d", max_pages)

            # Parse first page
            items = self._parse_page(soup, category, city, run_id)
            for item in items:
                all_items[item.product_url] = item
            logger.debug("Page 1: %d items, cumulative %d", len(items), len(all_items))

            # Paginate through remaining pages
            for page_num in range(2, max_pages + 1):
                url = _page_url(base_url, page_num)
                logger.debug("Page %d/%d: %s", page_num, max_pages, url)

                page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                page.wait_for_timeout(1_000)

                html = page.content()
                self.dbg.save_screenshot(page, f"stage2_page{page_num}.png")

                soup = BeautifulSoup(html, "html.parser")
                items = self._parse_page(soup, category, city, run_id)
                for item in items:
                    all_items[item.product_url] = item

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
        cards = soup.select("div.card-product.sl-item")
        items: List[PriceObservation] = []
        seen: set = set()

        for card in cards:
            # Product link and name
            link_el = card.select_one("a.card-product__link[href]")
            if not link_el:
                continue
            href = link_el.get("href", "").split("?")[0].split("#")[0]
            if not href:
                continue

            product_url = urljoin(BASE_URL, href)
            if product_url in seen:
                continue

            name = link_el.get_text(strip=True)
            if not name:
                continue

            # Price: prefer data-price attribute (clean integer)
            price: Optional[int] = None
            data_price = card.get("data-price", "").strip()
            if data_price:
                try:
                    price = int(data_price)
                except ValueError:
                    pass

            # Fallback: text in span.card-product__price_discount
            if price is None:
                price_el = card.select_one("span.card-product__price_discount")
                if price_el:
                    price_text = price_el.get_text(strip=True)
                    m = PRICE_RE.search(price_text)
                    if m:
                        try:
                            price = _to_int_price(m.group(1))
                        except ValueError:
                            pass

            if price is None or price <= 0:
                continue

            seen.add(product_url)
            items.append(
                PriceObservation(
                    run_id=run_id,
                    market="europharma.kz",
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
# Registration — makes this market available to the runner
# ---------------------------------------------------------------------------

def _register() -> None:
    from ..core.runner import register_market
    register_market("europharma", EuropharmaMarket)


_register()
