"""JSONL storage backend and run report writer."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List

from .models import CategoryResult, PriceObservation

ASTANA_TZ = timezone(timedelta(hours=5))


def _format_astana(dt: datetime) -> str:
    """Format datetime in Astana time (UTC+5) in a user-friendly format."""
    astana = dt.astimezone(ASTANA_TZ)
    day = astana.day
    return astana.strftime(f"{day} %B %Y, %H:%M (Astana, UTC+5)")


def _format_duration(seconds: float) -> str:
    """Format duration in 'H hr MM min' format."""
    total_minutes = int(seconds) // 60
    hours = total_minutes // 60
    minutes = total_minutes % 60
    return f"{hours} hr {minutes:02d} min"


class Storage:
    """Append-only JSONL storage with per-run report files."""

    def __init__(self, base_dir: str = "data"):
        self.base = Path(base_dir)

    def _run_dir(self, market: str, city: str) -> Path:
        """Return data/{market}/{city}/ directory path."""
        return self.base / market / city

    def append_observations(
        self,
        observations: List[PriceObservation],
        market: str,
        city: str,
        run_id: str,
    ) -> Path:
        """Append observations as JSONL to data/{market}/{city}/{run_id}.jsonl."""
        d = self._run_dir(market, city)
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{run_id}.jsonl"
        with path.open("a", encoding="utf-8") as f:
            for obs in observations:
                f.write(json.dumps(obs.to_dict(), ensure_ascii=False) + "\n")
        return path

    def write_report(
        self,
        results: List[CategoryResult],
        market: str,
        city: str,
        run_id: str,
        run_start: datetime,
        run_end: datetime,
    ) -> Path:
        """Write run summary to data/{market}/{city}/{run_id}_report.json."""
        d = self._run_dir(market, city)
        d.mkdir(parents=True, exist_ok=True)

        summary = {"success": 0, "empty": 0, "failed": 0}
        total_items = 0
        for r in results:
            summary[r.status] = summary.get(r.status, 0) + 1
            if r.status == "success":
                total_items += r.item_count

        duration_s = round((run_end - run_start).total_seconds(), 1)
        report = {
            "run_id": run_id,
            "market": market,
            "city": city,
            "run_started_at": run_start.isoformat(),
            "run_finished_at": run_end.isoformat(),
            "run_started_at_astana": _format_astana(run_start),
            "run_finished_at_astana": _format_astana(run_end),
            "run_duration_s": duration_s,
            "run_duration": _format_duration(duration_s),
            "total_categories": len(results),
            "summary": summary,
            "total_items_collected": total_items,
            "categories": [r.to_dict() for r in results],
        }

        path = d / f"{run_id}_report.json"
        path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return path

    def append_scrape_log(
        self,
        results: List[CategoryResult],
        market: str,
        city: str,
        run_id: str,
        run_start: datetime,
        run_end: datetime,
    ) -> Path:
        """Append one summary line to data/scrape_log.jsonl for cross-run tracking."""
        summary = {"success": 0, "empty": 0, "failed": 0}
        total_items = 0
        for r in results:
            summary[r.status] = summary.get(r.status, 0) + 1
            if r.status == "success":
                total_items += r.item_count

        failed_categories = []
        for r in results:
            if r.status == "failed":
                last_line = (r.error or "").strip().splitlines()[-1:]
                failed_categories.append({
                    "id": r.category.id,
                    "slug": r.category.slug,
                    "error": last_line[0] if last_line else "unknown",
                })

        duration_s = round((run_end - run_start).total_seconds(), 1)
        entry = {
            "run_id": run_id,
            "market": market,
            "city": city,
            "started_at": run_start.isoformat(),
            "finished_at": run_end.isoformat(),
            "started_at_astana": _format_astana(run_start),
            "finished_at_astana": _format_astana(run_end),
            "duration_s": duration_s,
            "duration": _format_duration(duration_s),
            "total_categories": len(results),
            "success": summary["success"],
            "empty": summary["empty"],
            "failed": summary["failed"],
            "total_products": total_items,
            "failed_categories": failed_categories,
        }

        self.base.mkdir(parents=True, exist_ok=True)
        path = self.base / "scrape_log.jsonl"
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return path
