"""Canonical data models for price tracking."""
from __future__ import annotations

import dataclasses
from typing import Optional


@dataclasses.dataclass
class PriceObservation:
    """A single price observation for one product."""

    run_id: str
    market: str
    city: str
    category_id: Optional[str]
    category_url: str
    product_url: str
    name: str
    price_current: int
    currency: str  # e.g. "KZT"
    unit_code: Optional[str]
    unit_qty: Optional[float]
    pack_qty: Optional[float]
    pack_unit: Optional[str]
    captured_at: str  # UTC ISO-8601

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


@dataclasses.dataclass
class CategoryInfo:
    """Discovered category metadata."""

    id: str
    slug: str
    url: str
    name: Optional[str] = None


@dataclasses.dataclass
class CategoryResult:
    """Outcome of crawling one category."""

    category: CategoryInfo
    status: str  # "success" | "empty" | "failed"
    item_count: int
    error: Optional[str]
    started_at: Optional[str]
    finished_at: Optional[str]
    duration_s: Optional[float]

    def to_dict(self) -> dict:
        d = dataclasses.asdict(self)
        return d
