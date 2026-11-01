"""Ingredient families and the purge-capable list, loaded from a versioned data file.

Why a data file and not code: these are curated claims (CAMP-style cross-reactor groups and the
turnover ingredients that can purge). They are reviewed and versioned as data, so a change to the
list is visible in a diff and carried in every engine result as FAMILIES_VERSION.

The one rule that matters downstream: an exact ingredient match always ranks above a family match
(app/patterns.py), so this module only reports membership. It never ranks.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from .inci import canonical

DATA_PATH = Path(__file__).parent / "families.json"


@lru_cache(maxsize=4)
def _load(path: str | None = None) -> dict:
    return json.loads(Path(path or DATA_PATH).read_text(encoding="utf-8"))


def version() -> str:
    return _load()["version"]


FAMILIES_VERSION = version()


def families() -> dict[str, dict]:
    """family key -> {"label", "members" (canonical keys), "general_note"}."""
    return _load()["families"]


def purge_capable() -> dict[str, dict]:
    """canonical ingredient key -> {"strength": "can" | "mild", "note"}."""
    return _load()["purge_capable"]


def family_of(ingredient: str) -> list[str]:
    """Every family the ingredient belongs to, by canonical key. Usually one, sometimes none."""
    key = canonical(ingredient)
    return sorted(f for f, spec in families().items() if key in spec["members"])


def members_of(family: str) -> list[str]:
    spec = families().get(canonical(family)) or families().get(family)
    return list(spec["members"]) if spec else []


def label_of(family: str) -> str:
    spec = families().get(family)
    return spec["label"] if spec else family


def general_note(family: str) -> str | None:
    """General knowledge about a family, kept apart from personal evidence (STRATEGY rule 4)."""
    spec = families().get(family)
    return (spec or {}).get("general_note")


def is_purge_capable(ingredient: str) -> bool:
    return canonical(ingredient) in purge_capable()


def purge_info(ingredient: str) -> dict | None:
    return purge_capable().get(canonical(ingredient))


def purge_capable_in(inci: list[str]) -> list[dict]:
    """Which of a label's lines are purge-capable, with the label line kept for display.
    Empty means purging is not on the table for this product at all (STRATEGY rule 7)."""
    out = []
    for raw in inci:
        info = purge_info(raw)
        if info:
            out.append({"label_line": raw.strip(), "ingredient": canonical(raw),
                        "strength": info["strength"], "note": info["note"]})
    return out
