"""Abstract base class for market scrapers."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

from playwright.sync_api import Browser, BrowserContext

from ..core.models import CategoryInfo, PriceObservation
from ..core.utils import DebugHelper


class BaseMarket(ABC):
    """
    Base class every market adapter must subclass.

    The browser instance is created once by the runner and shared across
    all markets/categories. Each crawl_category call should create its own
    BrowserContext (via _new_context) and close it when done.

    To add a new market:
        1. Create markets/your_market.py
        2. Subclass BaseMarket, implement all abstract methods
        3. Call register_market() at module level (see arbuz.py for example)
        4. Import the module in markets/__init__.py
        5. Add the market name to config.yaml
    """

    def __init__(
        self,
        browser: Browser,
        headless: bool = True,
        debug: bool = False,
    ):
        self.browser = browser
        self.headless = headless
        self.dbg = DebugHelper(self.market_name, enabled=debug)

    @property
    @abstractmethod
    def market_name(self) -> str:
        """Short identifier used in file paths and config, e.g. 'arbuz'."""
        ...

    @property
    @abstractmethod
    def supported_cities(self) -> List[str]:
        """City slugs this market supports, e.g. ['almaty']."""
        ...

    @abstractmethod
    def discover_categories(self, city: str) -> List[CategoryInfo]:
        """Discover all crawlable categories for the given city."""
        ...

    @abstractmethod
    def crawl_category(
        self,
        category: CategoryInfo,
        city: str,
        run_id: str,
    ) -> List[PriceObservation]:
        """Crawl a single category page (with pagination). Return observations."""
        ...

    def _new_context(self) -> BrowserContext:
        """Create a browser context with standard viewport and locale."""
        return self.browser.new_context(
            locale="ru-RU",
            viewport={"width": 1280, "height": 900},
        )
