"""What your scan found (findings-1.0): each measured concern as one plain line.

The bands and words are data (app/findings.json, versioned). This reads raw values that are
already in the scan result; it never calls YouCam. A concern that wasn't measured is left out:
there is no "unknown" line. Raw values never leave this file; only words do.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from . import needs as N

DATA_PATH = Path(__file__).parent / "findings.json"


@lru_cache(maxsize=4)
def data(path: str | None = None) -> dict:
    return json.loads(Path(path or DATA_PATH).read_text(encoding="utf-8"))


RULE_VERSION = data()["version"]


def band(value: float) -> str:
    """'high' | 'mid' | 'low'. Higher raw value = healthier-looking for every concern."""
    b = data()["bands"]
    if value >= b["high"]:
        return "high"
    if value >= b["low"]:
        return "mid"
    return "low"


def _num(v) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def lines(measured: dict | None, needs: list[N.Need] | None = None) -> list[dict]:
    """One line per measured concern, in a fixed order. `needs` (the basket's) links each line to
    the need it drives: the need built from this concern, or the need of the same kind already in
    the basket. The acne line carries the existing see-a-dermatologist line."""
    d = data()
    nd = N.data()
    out: list[dict] = []
    for c in d["order"]:
        v = _num((measured or {}).get(c))
        if v is None:
            continue
        spec = d["concerns"][c]
        b = band(v)
        row = {"concern": c, "band": b, "line": spec[b], "need": None, "see_doctor": None}
        cn = nd["concern_needs"].get(c, {})
        hit = next((n for n in (needs or []) if c in n.from_), None) or \
            next((n for n in (needs or []) if cn.get("key") and n.key == cn["key"]), None)
        if hit is not None:
            row["need"] = {"key": hit.key, "line": hit.line(), "targets": list(hit.targets[:2])}
        if c == "acne":
            row["see_doctor"] = cn.get("see_doctor")
        out.append(row)
    return out


def block(measured: dict | None, needs: list[N.Need] | None = None) -> dict | None:
    """The 'What your scan found' block, or None when nothing was measured (the face map then
    shows only what came from the answers)."""
    ls = lines(measured, needs)
    if not ls:
        return None
    return {"lines": ls, "label": data()["measured_by"], "rule_version": RULE_VERSION}


def from_saved(zone_types: dict | None, measured: dict | None) -> dict | None:
    """The block for a saved scan (Profile -> past scans): its needs rebuilt from the saved zone
    types and values with the same needs engine, so the links match what that basket was aimed at."""
    zt = {z: t for z, t in (zone_types or {}).items() if z in N.ZONES and t in N.data()["zone_needs"]}
    if len(zt) == len(N.ZONES):
        zones = {z: N.ZoneRead(z, zt[z], False, "face") for z in N.ZONES}
        needs = N.build_needs(zones, {k: v for k, v in (measured or {}).items() if _num(v) is not None})
    else:
        needs = None
    return block(measured, needs)
