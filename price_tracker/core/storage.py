"""JSONL storage backend and run report writer."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import List

from .models import CategoryResult, PriceObservation


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

        report = {
            "run_id": run_id,
            "market": market,
            "city": city,
            "run_started_at": run_start.isoformat(),
            "run_finished_at": run_end.isoformat(),
            "run_duration_s": round((run_end - run_start).total_seconds(), 1),
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

        entry = {
            "run_id": run_id,
            "market": market,
            "city": city,
            "timestamp": run_end.isoformat(),
            "duration_s": round((run_end - run_start).total_seconds(), 1),
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
