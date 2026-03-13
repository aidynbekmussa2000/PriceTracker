"""
Shared inflation-basket filter for construction / DIY market adapters.

Used by leroy_merlin.py, megastroy.py and any future construction-store
adapters.  Import normalize_category_name and is_relevant_category.

Keyword matching is substring-based against the *normalized* category
display name (Russian text from the navigation).  URL slugs are used as
a fallback when no display text is available.
"""
from __future__ import annotations

import re
import unicodedata

# ---------------------------------------------------------------------------
# Inflation-basket keyword mapping
# ---------------------------------------------------------------------------
# Keys are internal CPI labels.
# Values are Russian substring keywords matched against the normalized label.
# Add / remove keywords here to tune coverage without touching parser logic.

CONSTRUCTION_CATEGORY_MAPPING: dict[str, list[str]] = {
    "wallpaper": [
        "обои",
        "wallpaper",
    ],
    "cement": [
        "цемент",
    ],
    "dry_mixes": [
        "сухие строительные смеси",
        "строительные смеси",
        "сухие смеси",
        "штукатур",
        "шпаклев",
        "наливной пол",
        "кладочные смеси",
    ],
    "paint": [
        "краска",
        "водоэмульсион",
        "интерьерная краска",
        "фасадная краска",
    ],
    "wall_tile": [
        "кафель",
        "плитка",
        "настенная плитка",
        "керамическая плитка",
    ],
    "laminate": [
        "ламинат",
    ],
    "wallpaper_glue": [
        "обойный клей",
        "клей для обоев",
    ],
    "faucets": [
        "смеситель",
        "смесители",
    ],
    "lighting": [
        "люстра",
        "настольная лампа",
        "лампа",
        "светильник",
        "энергосберегающая лампа",
    ],
    "power_tools": [
        "дрель",
        "шуруповерт",
        "электродрель",
    ],
    "hand_tools": [
        "молоток",
    ],
}

# ---------------------------------------------------------------------------
# Negative / exclusion list
# ---------------------------------------------------------------------------
# If any of these substrings appear in the normalized label, the category is
# skipped even when a positive keyword also matches.

IRRELEVANT_KEYWORDS: list[str] = [
    "сад",
    "огород",
    "растения",
    "декор",
    "посуда",
    "мебель",
    "хранение",
    "текстиль",
    "шторы",
    "бытовая техника",
    "кухня",
    "товары для животных",
    "игрушки",
    "авто",
    "спорт",
    "канцтовары",
    "новогодние товары",
    "сезонные товары",
]

_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)


def normalize_category_name(name: str) -> str:
    """
    Normalize a category label for robust keyword matching.

    Steps:
    - NFKC Unicode normalisation
    - 'ё' → 'е'  (common Russian spelling variant)
    - lowercase
    - strip punctuation
    - collapse whitespace
    """
    text = unicodedata.normalize("NFKC", name)
    text = text.replace("ё", "е").replace("Ё", "е")
    text = text.lower()
    text = _PUNCT_RE.sub(" ", text)
    return " ".join(text.split())


def is_relevant_category(
    name: str,
    url: str | None = None,
) -> tuple[bool, str | None]:
    """
    Return ``(is_relevant, cpi_group_key | None)``.

    Matches the normalized *name* (and optionally the URL slug as fallback)
    against ``CONSTRUCTION_CATEGORY_MAPPING``.  Categories that contain any
    ``IRRELEVANT_KEYWORDS`` substring are excluded.

    Args:
        name: Display text or slug of the category.
        url:  Full category URL; its last path segment is used as a slug
              fallback when *name* is empty or too short.

    Returns:
        A 2-tuple: (True, cpi_key) if relevant, (False, None) otherwise.
    """
    label = normalize_category_name(name)

    # Build URL-slug fallback label
    slug_label = ""
    if url:
        slug = url.rstrip("/").split("/")[-1]
        slug_label = normalize_category_name(slug.replace("-", " "))

    combined = label + " " + slug_label

    # Negative check — bail early if clearly irrelevant
    for bad_kw in IRRELEVANT_KEYWORDS:
        if bad_kw in combined:
            return False, None

    # Positive keyword check
    for cpi_key, keywords in CONSTRUCTION_CATEGORY_MAPPING.items():
        for kw in keywords:
            if kw in label or (slug_label and kw in slug_label):
                return True, cpi_key

    return False, None
