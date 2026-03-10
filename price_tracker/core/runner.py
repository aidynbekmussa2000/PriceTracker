"""Market-agnostic orchestration runner with retry logic."""
from __future__ import annotations

import logging
import time
import traceback
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Dict, List, Optional, Type

from playwright.sync_api import sync_playwright

from .models import CategoryResult
from .storage import Storage

if TYPE_CHECKING:
    from ..markets.base import BaseMarket

logger = logging.getLogger("price_tracker.runner")

# ---------------------------------------------------------------------------
# Market registry
# ---------------------------------------------------------------------------

MARKET_REGISTRY: Dict[str, type] = {}


def register_market(name: str, cls: Type[BaseMarket]) -> None:
    """Register a market class by name."""
    MARKET_REGISTRY[name] = cls


def get_market_class(name: str) -> Type[BaseMarket]:
    """Look up a registered market class. Raises ValueError if not found."""
    if name not in MARKET_REGISTRY:
        raise ValueError(
            f"Unknown market: {name!r}. Available: {list(MARKET_REGISTRY.keys())}"
        )
    return MARKET_REGISTRY[name]


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

class Runner:
    """Orchestrates crawling across markets and cities."""

    def __init__(self, config: dict):
        self.config = config
        self.storage = Storage(config.get("data_dir", "data"))
        self.max_retries = config.get("max_retries", 2)

    def run(
        self,
        markets: Optional[List[str]] = None,
        cities: Optional[List[str]] = None,
        only_category_id: Optional[str] = None,
    ) -> None:
        """Main entry: launch browser, run each market x city combination."""
        markets = markets or self.config.get("markets", [])
        cities = cities or self.config.get("cities", [])
        headless = self.config.get("headless", True)
        debug = self.config.get("debug", False)
        run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%SZ")

        logger.info("Starting run %s  markets=%s cities=%s", run_id, markets, cities)

        market_errors: list = []
        market_successes: list = []

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            try:
                for market_name in markets:
                    try:
                        market_cls = get_market_class(market_name)
                        market = market_cls(
                            browser=browser, headless=headless, debug=debug
                        )
                    except Exception as exc:
                        logger.error(
                            "Failed to initialize market %s: %s",
                            market_name, exc,
                        )
                        market_errors.append((market_name, None, str(exc)))
                        continue

                    for city in cities:
                        if city not in market.supported_cities:
                            logger.warning(
                                "Skipping %s — not supported by %s",
                                city, market_name,
                            )
                            continue
                        try:
                            self._run_market_city(
                                market, city, run_id, only_category_id
                            )
                            market_successes.append((market_name, city))
                        except Exception as exc:
                            logger.error(
                                "Market %s/%s failed: %s",
                                market_name, city, exc,
                            )
                            market_errors.append((market_name, city, str(exc)))
                            continue
            finally:
                browser.close()

        self._log_run_summary(market_successes, market_errors)
        logger.info("Run %s complete", run_id)

    def _run_market_city(
        self,
        market: BaseMarket,
        city: str,
        run_id: str,
        only_category_id: Optional[str],
    ) -> List[CategoryResult]:
        """Discover categories and crawl them for one market + city."""
        run_start = datetime.now(timezone.utc)

        categories = market.discover_categories(city)
        if only_category_id:
            categories = [c for c in categories if c.id == only_category_id]
            if not categories:
                logger.error(
                    "Category %s not found in %s/%s", only_category_id,
                    market.market_name, city,
                )
                return []

        total = len(categories)
        results: List[CategoryResult] = []

        for i, cat in enumerate(categories, 1):
            logger.info(
                "[%d/%d] %s/%s category=%s (%s)",
                i, total, market.market_name, city, cat.id, cat.slug,
            )
            result = self._process_with_retry(market, cat, city, run_id)
            results.append(result)

            if result.status == "success":
                logger.info(
                    "  OK — %d items (%.1fs)", result.item_count, result.duration_s
                )
            elif result.status == "empty":
                logger.warning("  EMPTY — 0 items (%.1fs)", result.duration_s)
            else:
                last_line = (result.error or "").strip().splitlines()[-1:]
                logger.error("  FAILED — %s", last_line[0] if last_line else "unknown")

        run_end = datetime.now(timezone.utc)
        report_path = self.storage.write_report(
            results, market.market_name, city, run_id, run_start, run_end
        )
        logger.info("Report saved → %s", report_path)

        log_path = self.storage.append_scrape_log(
            results, market.market_name, city, run_id, run_start, run_end
        )
        logger.info("Scrape log updated → %s", log_path)

        self._log_summary(results)
        return results

    def _process_with_retry(
        self,
        market: BaseMarket,
        category: "CategoryResult | Any",
        city: str,
        run_id: str,
    ) -> CategoryResult:
        """Crawl a single category with retry on failure."""
        last_error: Optional[str] = None
        started_at = datetime.now(timezone.utc).isoformat()
        t0 = time.monotonic()

        for attempt in range(1, self.max_retries + 1):
            try:
                observations = market.crawl_category(category, city, run_id)
                duration = round(time.monotonic() - t0, 1)

                if observations:
                    self.storage.append_observations(
                        observations, market.market_name, city, run_id
                    )
                    return CategoryResult(
                        category=category,
                        status="success",
                        item_count=len(observations),
                        error=None,
                        started_at=started_at,
                        finished_at=datetime.now(timezone.utc).isoformat(),
                        duration_s=duration,
                    )
                else:
                    return CategoryResult(
                        category=category,
                        status="empty",
                        item_count=0,
                        error=None,
                        started_at=started_at,
                        finished_at=datetime.now(timezone.utc).isoformat(),
                        duration_s=duration,
                    )

            except Exception:
                last_error = traceback.format_exc()
                logger.warning(
                    "Attempt %d/%d failed for category %s",
                    attempt, self.max_retries, category.id,
                )
                if attempt < self.max_retries:
                    logger.info("Retrying...")

        return CategoryResult(
            category=category,
            status="failed",
            item_count=0,
            error=last_error,
            started_at=started_at,
            finished_at=datetime.now(timezone.utc).isoformat(),
            duration_s=round(time.monotonic() - t0, 1),
        )

    @staticmethod
    def _log_summary(results: List[CategoryResult]) -> None:
        """Print a final summary of the crawl results."""
        summary: Dict[str, int] = {"success": 0, "empty": 0, "failed": 0}
        total_items = 0
        for r in results:
            summary[r.status] = summary.get(r.status, 0) + 1
            if r.status == "success":
                total_items += r.item_count

        logger.info("─" * 50)
        logger.info("Categories: %d total", len(results))
        logger.info("  success: %d", summary["success"])
        logger.info("  empty:   %d", summary["empty"])
        logger.info("  failed:  %d", summary["failed"])
        logger.info("Total items collected: %d", total_items)

        failed = [r for r in results if r.status == "failed"]
        if failed:
            logger.info("Failed categories:")
            for r in failed:
                last = (r.error or "").strip().splitlines()[-1:]
                logger.info("  %s (%s): %s", r.category.id, r.category.slug,
                            last[0] if last else "unknown")
        logger.info("─" * 50)

    @staticmethod
    def _log_run_summary(
        successes: list,
        errors: list,
    ) -> None:
        """Print a final cross-market summary."""
        if not successes and not errors:
            return
        logger.info("═" * 50)
        logger.info("RUN SUMMARY")
        logger.info("═" * 50)
        if successes:
            logger.info("Completed: %d market/city combinations", len(successes))
            for market_name, city in successes:
                logger.info("  OK  %s/%s", market_name, city)
        if errors:
            logger.info("Failed: %d market/city combinations", len(errors))
            for market_name, city, err in errors:
                label = f"{market_name}/{city}" if city else market_name
                logger.info("  FAIL  %s — %s", label, err)
        logger.info("═" * 50)
