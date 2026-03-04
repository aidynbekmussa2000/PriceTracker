"""Shared utilities: logging and debug helpers."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from playwright.sync_api import Page

logger = logging.getLogger("price_tracker")


def setup_logging(debug: bool = False) -> None:
    """Configure root logging for the price_tracker package."""
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        format="[%(asctime)s] [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
        level=level,
    )


class DebugHelper:
    """Save debug HTML snapshots and screenshots per market."""

    def __init__(self, market_name: str, enabled: bool = True):
        self.enabled = enabled
        self.dir = Path(f"debug_{market_name}")

    def save_html(self, html: str, name: str) -> Optional[Path]:
        if not self.enabled:
            return None
        self.dir.mkdir(exist_ok=True)
        p = self.dir / name
        p.write_text(html, encoding="utf-8")
        return p

    def save_screenshot(self, page: Page, name: str) -> Optional[Path]:
        if not self.enabled:
            return None
        self.dir.mkdir(exist_ok=True)
        p = self.dir / name
        page.screenshot(path=str(p), full_page=False, timeout=10_000)
        return p
