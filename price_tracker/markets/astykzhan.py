"""
Astykzhan.kz market adapter.

Scrapes product prices from astykzhan.kz. The site is a server-rendered
Bitrix CMS site, so all data is fetched via plain HTTPS requests without
a browser.

Site notes:
    - Bitrix CMS; city routing via BITRIX_SM_city cookie (KO = Kostanai).
    - The session cookie is required to avoid an infinite 302 redirect loop.
    - Category URLs: /catalog/{parent}/{child}/ (hierarchical slugs).
    - Only leaf categories are crawled (those not a URL-prefix of any other).
    - Product cards: div.catalog-product
        - name:  .catalog-product__title
        - price: div[data-price] (clean integer, no formatting needed)
        - url:   a.learn_more_bnt[href]
    - Pagination: ?PAGEN_1=N&SIZEN_1=30 (Bitrix standard).
    - Max page detected from highest PAGEN_1=N value in pagination links.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from ..core.models import CategoryInfo, PriceObservation
from .base import BaseMarket

logger = logging.getLogger("price_tracker.astykzhan")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_URL = "https://astykzhan.kz"
CATALOG_URL = f"{BASE_URL}/catalog/"
PAGE_SIZE = 30

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "ru-RU,ru;q=0.9",
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
    })
    # Bitrix city session cookie required to avoid infinite 302 redirect.
    # KO = Kostanai (site's primary city); BITRIX_SM_lang fixes language.
    s.cookies.set("BITRIX_SM_city", "KO", domain="astykzhan.kz")
    s.cookies.set("BITRIX_SM_lang", "RU", domain="astykzhan.kz")
    return s


def _detect_max_pages(soup: BeautifulSoup) -> int:
    """Return highest PAGEN_1 value found in pagination links, default 1."""
    max_page = 1
    for a in soup.select("a[href*='PAGEN_1=']"):
        m = re.search(r"PAGEN_1=(\d+)", a.get("href", ""))
        if m:
            max_page = max(max_page, int(m.group(1)))
    return max_page


def _cat_slug(path: str) -> str:
    """Convert /catalog/a/b/c/ → a/b/c."""
    parts = [p for p in path.split("/") if p and p != "catalog"]
    return "/".join(parts)


def _cat_id(slug: str) -> str:
    """Use the last path segment as the category ID."""
    return slug.split("/")[-1] if "/" in slug else slug


# ---------------------------------------------------------------------------
# AstykzhanMarket adapter
# ---------------------------------------------------------------------------


class AstykzhanMarket(BaseMarket):
    """
    Astykzhan.kz price scraper — uses plain HTTP requests.

    The Playwright browser passed by the runner is accepted but not used;
    all data is retrieved via requests over HTTPS.
    """

    @property
    def market_name(self) -> str:
        return "astykzhan"

    @property
    def supported_cities(self) -> List[str]:
        # Site serves Kostanai region; 'almaty' used as conventional key.
        return ["almaty"]

    # -- Category discovery -------------------------------------------------

    def discover_categories(self, city: str) -> List[CategoryInfo]:
        """Fetch the catalog page and return all leaf category URLs."""
        logger.info("Discovering categories from %s", CATALOG_URL)

        sess = _make_session()
        resp = sess.get(CATALOG_URL, timeout=30)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

        # Collect all unique /catalog/... hrefs
        all_paths: list[str] = []
        seen: set = set()
        for a in soup.select("a[href*='/catalog/']"):
            href = a.get("href", "")
            # Normalise to path only
            if href.startswith("http"):
                from urllib.parse import urlparse
                href = urlparse(href).path
            href = href.rstrip("/") + "/"
            if not href.startswith("/catalog/"):
                continue
            # Skip the root catalog page and known non-product sections
            slug = _cat_slug(href)
            if not slug or slug in ("sales", "akcii"):
                continue
            if href not in seen:
                seen.add(href)
                all_paths.append(href)

        # Keep only leaf paths (not a URL-prefix of any other path)
        path_set = set(all_paths)
        leaves: List[CategoryInfo] = []
        seen_ids: set = set()
        for path in all_paths:
            is_leaf = not any(
                other != path and other.startswith(path)
                for other in path_set
            )
            if not is_leaf:
                continue
            slug = _cat_slug(path)
            cat_id = _cat_id(slug)
            # Deduplicate by full slug (handles identical last segments)
            if slug in seen_ids:
                continue
            seen_ids.add(slug)
            leaves.append(
                CategoryInfo(
                    id=slug,
                    slug=slug,
                    url=urljoin(BASE_URL, path),
                )
            )

        leaves.sort(key=lambda c: c.id)

        if not leaves:
            raise RuntimeError(
                "No categories discovered — check network or site structure"
            )

        logger.info("Discovered %d leaf categories", len(leaves))
        return leaves

    # -- Single-category crawl ----------------------------------------------

    def crawl_category(
        self,
        category: CategoryInfo,
        city: str,
        run_id: str,
    ) -> List[PriceObservation]:
        """Crawl all pages of a single category via URL-based pagination."""
        all_items: Dict[str, PriceObservation] = {}
        logger.info("Crawling category %s", category.id)

        sess = _make_session()

        # First page — also used to detect total pages
        resp = sess.get(category.url, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        max_pages = _detect_max_pages(soup)
        logger.debug("Max pages: %d", max_pages)

        items = self._parse_page(soup, category, city, run_id)
        for item in items:
            all_items[item.product_url] = item
        logger.debug("Page 1: %d items, cumulative %d", len(items), len(all_items))

        for page_num in range(2, max_pages + 1):
            page_url = (
                f"{category.url}?PAGEN_1={page_num}&SIZEN_1={PAGE_SIZE}"
            )
            logger.debug("Page %d/%d: %s", page_num, max_pages, page_url)
            resp = sess.get(page_url, timeout=30)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            items = self._parse_page(soup, category, city, run_id)
            for item in items:
                all_items[item.product_url] = item
            logger.debug(
                "Page %d: %d items, cumulative %d",
                page_num, len(items), len(all_items),
            )

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
        cards = soup.select("div.catalog-product")
        items: List[PriceObservation] = []
        seen: set = set()

        for card in cards:
            # Product URL from the "Узнать подробнее" link
            link_el = card.select_one("a.learn_more_bnt[href]")
            if not link_el:
                continue
            href = link_el.get("href", "")
            product_url = href if href.startswith("http") else urljoin(BASE_URL, href)
            if product_url in seen:
                continue

            # Product name
            name_el = card.select_one(".catalog-product__title")
            if not name_el:
                continue
            name = name_el.get_text(strip=True)
            if not name:
                continue

            # Price from data-price attribute (clean integer, no parsing needed)
            price_el = card.select_one("[data-price]")
            if not price_el:
                continue
            try:
                price = int(price_el.get("data-price", ""))
            except (ValueError, TypeError):
                continue

            seen.add(product_url)
            items.append(
                PriceObservation(
                    run_id=run_id,
                    market="astykzhan.kz",
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
    register_market("astykzhan", AstykzhanMarket)


_register()
