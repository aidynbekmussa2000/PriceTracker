#!/usr/bin/env python3
"""
Arbuz.kz global category orchestrator.

Discovers all categories from the catalog index page, then runs the
single-category crawler on each one sequentially, tracking success/failure
in a structured run report.

Usage
-----
python orchestrator_arbuz.py              # full run (headless, save debug, skip done)
python orchestrator_arbuz.py --list-only  # discover and print categories, then exit
python orchestrator_arbuz.py --category-id 225178   # run one specific category
python orchestrator_arbuz.py --force-rerun           # re-crawl all, including done
python orchestrator_arbuz.py --headed --no-debug     # visible browser, no debug files
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

from parser_arbuz import (
    DEBUG_DIR,
    crawl_category,
    dbg,
    dismiss_overlays,
    extract_category_id,
    save_json,
)

# ─────────────────────────────────────────
# Constants
# ─────────────────────────────────────────

CATALOG_URL = "https://arbuz.kz/ru/almaty/catalog"
DATA_DIR    = Path("data")
REPORT_PATH = Path("run_report.json")

CAT_SEL = 'a[href*="/catalog/cat/"]'


# ─────────────────────────────────────────
# Orchestrator-level logging
# ─────────────────────────────────────────

def orch(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [ORCH] {msg}", flush=True)


# ─────────────────────────────────────────
# Category discovery
# ─────────────────────────────────────────

def discover_categories(headless: bool = False) -> List[Dict[str, str]]:
    """
    Launch a browser, load the catalog index, and extract all category URLs.

    Returns a list of dicts sorted by numeric category ID:
        [{"id": "225178", "slug": "ovoshi", "url": "https://..."}]
    """
    orch(f"Discovering categories from {CATALOG_URL}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            locale="ru-RU",
            viewport={"width": 1280, "height": 900},
        )
        page = context.new_page()

        page.goto(CATALOG_URL, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(1_000)  # let SPA render
        dismiss_overlays(page)

        # Wait for at least one category link to appear
        try:
            page.wait_for_selector(CAT_SEL, state="attached", timeout=30_000)
        except Exception as exc:
            browser.close()
            raise RuntimeError(
                f"No category links found on catalog page within 30s: {exc}"
            ) from exc

        # Extract all category hrefs from the DOM
        hrefs: List[str] = page.eval_on_selector_all(
            CAT_SEL,
            "els => [...new Set(els.map(e => e.getAttribute('href')).filter(h => h && h.includes('/catalog/cat/')))]",
        )

        # Save debug snapshot of the catalog page
        DEBUG_DIR.mkdir(exist_ok=True)
        html_path = DEBUG_DIR / "discovery_catalog.html"
        html_path.write_text(page.content(), encoding="utf-8")
        ss_path = DEBUG_DIR / "discovery_catalog.png"
        page.screenshot(path=str(ss_path), full_page=False, timeout=10_000)
        orch(f"Catalog snapshot → {html_path}  |  {ss_path}")

        browser.close()

    # Build structured category records
    base = "https://arbuz.kz"
    categories: List[Dict[str, str]] = []
    seen_ids: set[str] = set()

    for href in hrefs:
        url = href if href.startswith("http") else base + href
        cat_id = extract_category_id(url)
        if not cat_id or cat_id in seen_ids:
            continue
        seen_ids.add(cat_id)

        # Slug = the part after "{id}-" in the path segment
        m = re.search(r"/catalog/cat/\d+-(.+?)(?:[#?]|$)", urlparse(url).path)
        slug = m.group(1) if m else cat_id

        categories.append({"id": cat_id, "slug": slug, "url": url.split("#")[0]})

    # Sort deterministically by numeric ID
    categories.sort(key=lambda c: int(c["id"]))

    if not categories:
        raise RuntimeError("No categories discovered — check network or site structure")

    orch(f"Discovered {len(categories)} categories")
    return categories


# ─────────────────────────────────────────
# Output path helpers
# ─────────────────────────────────────────

def output_path(category: Dict[str, str]) -> Path:
    return DATA_DIR / f"category_{category['id']}.json"


def already_done(category: Dict[str, str]) -> bool:
    p = output_path(category)
    if not p.exists():
        return False
    return p.stat().st_size > 5  # empty "[]" is 2 bytes; real data is kilobytes


# ─────────────────────────────────────────
# Per-category processing
# ─────────────────────────────────────────

def process_category(
    category: Dict[str, str],
    headless: bool,
    save_debug: bool,
) -> Dict[str, Any]:
    """
    Crawl one category. Never raises — all exceptions are captured in the record.

    Status values:
        "success"  — items found and written to disk
        "empty"    — crawler returned 0 items (no exception)
        "failed"   — exception raised during crawl or file write
    """
    record: Dict[str, Any] = {
        "category_id":   category["id"],
        "category_slug": category["slug"],
        "category_url":  category["url"],
        "status":        None,
        "item_count":    0,
        "output_file":   None,
        "error":         None,
        "started_at":    datetime.now(timezone.utc).isoformat(),
        "finished_at":   None,
        "duration_s":    None,
    }
    t0 = time.monotonic()

    try:
        items = crawl_category(
            category["url"],
            headless=headless,
            save_debug=save_debug,
        )
        if not items:
            record["status"] = "empty"
        else:
            out = output_path(category)
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            save_json(items, str(out))
            record["status"]      = "success"
            record["item_count"]  = len(items)
            record["output_file"] = str(out.resolve())
    except Exception:
        record["status"] = "failed"
        record["error"]  = traceback.format_exc()

    record["finished_at"] = datetime.now(timezone.utc).isoformat()
    record["duration_s"]  = round(time.monotonic() - t0, 1)
    return record


# ─────────────────────────────────────────
# Run report
# ─────────────────────────────────────────

def write_report(results: List[Dict[str, Any]], run_start: datetime) -> None:
    summary: Dict[str, int] = {"success": 0, "empty": 0, "failed": 0, "skipped": 0}
    total_items = 0
    for r in results:
        status = r.get("status") or "failed"
        summary[status] = summary.get(status, 0) + 1
        if status == "success":
            total_items += r.get("item_count", 0)

    run_end = datetime.now(timezone.utc)
    report = {
        "run_started_at":              run_start.isoformat(),
        "run_finished_at":             run_end.isoformat(),
        "run_duration_s":              round((run_end - run_start).total_seconds(), 1),
        "total_categories_discovered": len(results),
        "summary":                     summary,
        "total_items_collected":       total_items,
        "categories":                  results,
    }
    REPORT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    orch(f"Run report saved → {REPORT_PATH.resolve()}")


# ─────────────────────────────────────────
# Main orchestration loop
# ─────────────────────────────────────────

def run_orchestrator(
    headless: bool = False,
    save_debug: bool = True,
    force_rerun: bool = False,
    only_id: Optional[str] = None,
) -> None:
    run_start = datetime.now(timezone.utc)

    # Phase 1: discover
    categories = discover_categories(headless=headless)

    # Filter to a single category if requested
    if only_id:
        categories = [c for c in categories if c["id"] == only_id]
        if not categories:
            orch(f"ERROR: category_id={only_id} not found in discovered categories")
            sys.exit(1)

    total = len(categories)
    results: List[Dict[str, Any]] = []

    # Phase 2: process each category
    for i, cat in enumerate(categories, 1):
        prefix = f"[{i}/{total}] category_id={cat['id']} ({cat['slug']})"

        if not force_rerun and already_done(cat):
            orch(f"SKIP   {prefix} — already done")
            results.append({
                "category_id":   cat["id"],
                "category_slug": cat["slug"],
                "category_url":  cat["url"],
                "status":        "skipped",
                "item_count":    None,
                "output_file":   str(output_path(cat).resolve()),
                "error":         None,
                "started_at":    None,
                "finished_at":   None,
                "duration_s":    None,
            })
            continue

        orch(f"START  {prefix}")
        record = process_category(cat, headless=headless, save_debug=save_debug)

        status = record["status"]
        if status == "success":
            orch(
                f"OK     {prefix} — {record['item_count']} items  ({record['duration_s']}s)"
            )
        elif status == "empty":
            orch(f"EMPTY  {prefix} — 0 items returned  ({record['duration_s']}s)")
        else:
            # Trim traceback to first line for the progress log; full text in report
            first_line = (record["error"] or "").strip().splitlines()[-1]
            orch(f"FAIL   {prefix} — {first_line}  ({record['duration_s']}s)")

        results.append(record)

    # Phase 3: report
    write_report(results, run_start)

    # Final summary table
    summary: Dict[str, int] = {"success": 0, "empty": 0, "failed": 0, "skipped": 0}
    for r in results:
        s = r.get("status") or "failed"
        summary[s] = summary.get(s, 0) + 1

    total_items = sum(r.get("item_count") or 0 for r in results if r["status"] == "success")
    failed = [r for r in results if r["status"] == "failed"]

    orch("─" * 60)
    orch(f"Categories processed : {total}")
    orch(f"  success            : {summary['success']}")
    orch(f"  empty              : {summary['empty']}")
    orch(f"  failed             : {summary['failed']}")
    orch(f"  skipped            : {summary['skipped']}")
    orch(f"Total items collected: {total_items}")

    if failed:
        orch("Failed categories:")
        for r in failed:
            orch(f"  category_id={r['category_id']} ({r['category_slug']})")
            # Print last error line for quick diagnosis
            last = (r["error"] or "").strip().splitlines()[-1]
            orch(f"    {last}")
    orch("─" * 60)


# ─────────────────────────────────────────
# CLI
# ─────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Orchestrate full arbuz.kz catalog crawl",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python orchestrator_arbuz.py --list-only          # just discover categories
  python orchestrator_arbuz.py --category-id 225178 # crawl one category
  python orchestrator_arbuz.py --force-rerun        # re-crawl all
  python orchestrator_arbuz.py --headed --no-debug  # visible browser, no debug files
        """,
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Run browser in headed (visible) mode. Default: headless.",
    )
    parser.add_argument(
        "--no-debug",
        action="store_true",
        help="Disable saving debug HTML/screenshots. Default: save debug.",
    )
    parser.add_argument(
        "--force-rerun",
        action="store_true",
        help="Re-crawl all categories, including already-done ones.",
    )
    parser.add_argument(
        "--category-id",
        metavar="ID",
        default=None,
        help="Run only the specified category ID (skips discovery loop for others).",
    )
    parser.add_argument(
        "--list-only",
        action="store_true",
        help="Discover and print all categories, then exit without crawling.",
    )

    args = parser.parse_args()

    if args.list_only:
        categories = discover_categories(headless=not args.headed)
        print(f"\n{'ID':<10} {'Slug':<40} URL")
        print("-" * 100)
        for cat in categories:
            print(f"{cat['id']:<10} {cat['slug']:<40} {cat['url']}")
        print(f"\nTotal: {len(categories)} categories")
        return

    run_orchestrator(
        headless=not args.headed,
        save_debug=not args.no_debug,
        force_rerun=args.force_rerun,
        only_id=args.category_id,
    )


if __name__ == "__main__":
    main()
