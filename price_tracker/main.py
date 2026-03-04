#!/usr/bin/env python3
"""
Multi-market price tracker CLI.

Usage:
    python -m price_tracker.main                              # run all from config.yaml
    python -m price_tracker.main --market arbuz --city almaty  # single market + city
    python -m price_tracker.main --category-id 225178          # single category
    python -m price_tracker.main --no-headless --debug         # visible browser + debug files
    python -m price_tracker.main --list-categories             # just list categories and exit
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import yaml

from .core.runner import Runner, get_market_class
from .core.utils import setup_logging

# Import markets package to trigger registration of all adapters
from . import markets  # noqa: F401

logger = logging.getLogger("price_tracker")


def load_config(path: str = "config.yaml") -> dict:
    """Load config from YAML file, return empty dict if not found."""
    p = Path(path)
    if p.exists():
        with p.open() as f:
            return yaml.safe_load(f) or {}
    return {}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Multi-market price tracker",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  python -m price_tracker.main
  python -m price_tracker.main --market arbuz --city almaty
  python -m price_tracker.main --category-id 225178
  python -m price_tracker.main --list-categories --market arbuz --city almaty
        """,
    )
    parser.add_argument("--market", help="Run only this market (overrides config)")
    parser.add_argument("--city", help="Run only this city (overrides config)")
    parser.add_argument("--category-id", help="Crawl only this category ID")
    parser.add_argument(
        "--headless", action="store_true", default=None,
        help="Run browser headless (default)",
    )
    parser.add_argument(
        "--no-headless", dest="headless", action="store_false",
        help="Run browser in visible mode",
    )
    parser.add_argument(
        "--debug", action="store_true", default=None,
        help="Save debug screenshots and HTML",
    )
    parser.add_argument(
        "--no-debug", dest="debug", action="store_false",
        help="Disable debug output (default)",
    )
    parser.add_argument(
        "--list-categories", action="store_true",
        help="Discover and print categories, then exit",
    )
    parser.add_argument("--config", default="config.yaml", help="Config file path")

    args = parser.parse_args()

    config = load_config(args.config)

    # CLI overrides
    if args.headless is not None:
        config["headless"] = args.headless
    if args.debug is not None:
        config["debug"] = args.debug
    if args.market:
        config["markets"] = [args.market]
    if args.city:
        config["cities"] = [args.city]

    config.setdefault("headless", True)
    config.setdefault("debug", False)
    config.setdefault("markets", ["arbuz"])
    config.setdefault("cities", ["almaty"])

    setup_logging(debug=config.get("debug", False))

    # List-categories mode
    if args.list_categories:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=config["headless"])
            for market_name in config["markets"]:
                market_cls = get_market_class(market_name)
                market = market_cls(browser=browser, headless=config["headless"])
                for city in config["cities"]:
                    cats = market.discover_categories(city)
                    print(f"\n{market_name}/{city}: {len(cats)} categories")
                    print(f"{'ID':<10} {'Slug':<40} URL")
                    print("-" * 100)
                    for c in cats:
                        print(f"{c.id:<10} {c.slug:<40} {c.url}")
            browser.close()
        return

    # Normal run
    runner = Runner(config)
    runner.run(only_category_id=args.category_id)


if __name__ == "__main__":
    main()
