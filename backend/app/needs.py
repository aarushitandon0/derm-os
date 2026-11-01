"""Needs engine (needs-1.0): your face, zone by zone, in plain words.

docs/strategy.md section 5. Zone skin types (YouCam skin_type: whole / t_zone / u_zone) and the
measured concern scores become a short list of needs ("oil control on T-zone", "hydration on
cheeks"), and each need names the ingredients and textures a product should be aimed at. The
finish goal (dewy / natural / matte) reorders textures and finishes later, in app/basket.py.

Three rules that decide how this is written:

* The curated part is data (app/needs.json, versioned). This file only applies it.
* Every zone type and every need says where it came from: "face" when YouCam measured it, and
  "answers" when it came from the quiz because nothing was measured. The shopping flow never
  stops at "can't tell": a missing measurement is filled from the answers and labelled so.
* Raw scores are read here and never shown. The user sees words, not numbers.

The skin_type response shape is only partly documented (subcategories whole, t_zone, u_zone; the
values Normal / Oily / Dry / Combination, optionally "& Redness"). The live SD response (checked
2026-11-01) sends one output item per region: {"type": "skin_type", "region": "t_zone",
"skin_type": "Oily"}. `parse_zones()` reads that shape and stays tolerant of how values are
wrapped; it is tested on the live shape and on synthetic dicts of the documented one.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

DATA_PATH = Path(__file__).parent / "needs.json"

FROM_FACE = "From your face (YouCam)"
FROM_ANSWERS = "from your answers"
ZONES = ("t_zone", "u_zone")


@lru_cache(maxsize=4)
def data(path: str | None = None) -> dict:
    return json.loads(Path(path or DATA_PATH).read_text(encoding="utf-8"))


def version() -> str:
    return data()["version"]


RULE_VERSION = version()


def zone_name(zone: str) -> str:
    if zone == "whole":
        return "whole face"
    return data()["zones"][zone]["name"]


def zone_in_sentence(zone: str) -> str:
    """'T-zone' stays capitalised mid-sentence; 'Cheeks' doesn't."""
    name = zone_name(zone)
    return name if name.startswith("T-") else name.lower()


# ---------------------------------------------------------------- reading skin_type
_TYPES = ("combination", "normal", "oily", "dry")


def _read_type(v) -> tuple[str | None, bool]:
    """'Oily & Redness' -> ('oily', True); {'skin_type': 'Dry'} -> ('dry', False)."""
    if isinstance(v, dict):
        for k in ("skin_type", "type", "label", "value", "result", "class", "category", "name"):
            if k in v:
                t, r = _read_type(v[k])
                if t or r:
                    return t, r
        return None, False
    if isinstance(v, list):
        for item in v:
            t, r = _read_type(item)
            if t or r:
                return t, r
        return None, False
    if not isinstance(v, str):
        return None, False
    s = v.strip().lower()
    redness = "redness" in s or "red" == s
    base = next((t for t in _TYPES if t in s), None)
    if base is None and ("combo" in s):
        base = "combination"
    return base, redness


def _region_items(node) -> dict | None:
    """The live SD shape (checked 2026-11-01): one output item PER REGION,
    {"type": "skin_type", "region": "whole" | "t_zone" | "u_zone", "skin_type": "Oily"}.
    Gathered into {region: item}, or None when the response isn't shaped like that."""
    if isinstance(node, dict):
        for k in ("data", "results", "output", "response"):
            if k in node:
                hit = _region_items(node[k])
                if hit:
                    return hit
        return None
    if isinstance(node, list):
        out = {item["region"]: item for item in node
               if isinstance(item, dict) and str(item.get("type", "")).lower() in ("skin_type", "hd_skin_type")
               and item.get("region") in ("whole", "t_zone", "u_zone")}
        return out or None
    return None


def _find_skin_type(node):
    """The skin_type block inside data/results/output (JSON) or a score_info dict (ZIP)."""
    regions = _region_items(node)
    if regions:
        return regions
    if isinstance(node, dict):
        if str(node.get("type", "")).lower() in ("skin_type", "hd_skin_type"):
            return node
        for k in ("skin_type", "hd_skin_type"):
            if isinstance(node.get(k), dict):
                return node[k]
        for k in ("data", "results", "output", "response"):
            if k in node:
                hit = _find_skin_type(node[k])
                if hit is not None:
                    return hit
    if isinstance(node, list):
        for item in node:
            hit = _find_skin_type(item)
            if hit is not None:
                return hit
    return None


@dataclass
class ZoneRead:
    zone: str                   # "t_zone" | "u_zone"
    type: str                   # oily | dry | normal
    redness: bool
    source: str                 # "face" | "answers"

    @property
    def label(self) -> str:
        return FROM_FACE if self.source == "face" else FROM_ANSWERS

    def line(self) -> str:
        extra = ", with some redness" if self.redness else ""
        return f"{zone_name(self.zone)}: {self.type}{extra}"

    def to_dict(self) -> dict:
        return {"zone": self.zone, "name": zone_name(self.zone), "type": self.type,
                "redness": self.redness, "source": self.source, "label": self.label,
                "line": self.line()}


def _split_whole(t: str) -> tuple[str, str]:
    """A whole-face reading with no zone split. Combination means oily centre, normal cheeks."""
    if t == "combination":
        return "oily", "normal"
    return t, t


def parse_zones(payload) -> dict[str, ZoneRead]:
    """Zone types from a skin_type response, or {} when none can be read (the caller falls back
    to the answers). Accepts {"t_zone": "Oily"}, {"t_zone": {"skin_type": "Oily"}}, the JSON
    output list, and a score_info dict."""
    block = _find_skin_type(payload)
    if block is None and isinstance(payload, dict) and any(z in payload for z in ("t_zone", "u_zone", "whole")):
        block = payload
    if not isinstance(block, dict):
        return {}
    reads: dict[str, tuple[str | None, bool]] = {
        z: _read_type(block[z]) for z in ("whole", "t_zone", "u_zone") if z in block}
    whole_t, whole_r = reads.get("whole", (None, False))
    out: dict[str, ZoneRead] = {}
    for i, z in enumerate(ZONES):
        t, r = reads.get(z, (None, False))
        if t == "combination":          # a zone itself can't be both; read it from the whole split
            t = _split_whole("combination")[i]
        if t is None and whole_t:
            t = _split_whole(whole_t)[i]
        if t is None:
            continue
        out[z] = ZoneRead(z, t, bool(r or whole_r), "face")
    return out


def zones_from_answers(answers: dict | None) -> dict[str, ZoneRead]:
    """The quiz's read, used when nothing was measured. Labelled 'from your answers'."""
    answers = answers or {}
    t = data()["answers_types"].get(answers.get("midday") or "", "normal")
    tz, uz = _split_whole(t)
    return {"t_zone": ZoneRead("t_zone", tz, False, "answers"),
            "u_zone": ZoneRead("u_zone", uz, False, "answers")}


def read_zones(payload, answers: dict | None) -> dict[str, ZoneRead]:
    """Measured zones where there are some, the answers for whatever is missing."""
    measured = parse_zones(payload) if payload is not None else {}
    fallback = zones_from_answers(answers)
    return {z: measured.get(z) or fallback[z] for z in ZONES}


def same_type(zones: dict[str, ZoneRead]) -> bool:
    return zones["t_zone"].type == zones["u_zone"].type


# ---------------------------------------------------------------- needs
@dataclass
class Need:
    key: str
    words: str
    zone: str                    # t_zone | u_zone | whole
    targets: list[str]
    textures: list[str] = field(default_factory=list)
    avoid: list[str] = field(default_factory=list)
    source: str = "face"         # face | answers
    from_: list[str] = field(default_factory=list)   # what produced it: "zone type", "pore", ...
    see_doctor: str | None = None
    data_source: str | None = None

    def line(self) -> str:
        return f"{self.words} on {zone_in_sentence(self.zone)}" if self.zone != "whole" else self.words

    def to_dict(self) -> dict:
        return {"key": self.key, "words": self.words, "zone": self.zone, "zone_name": zone_name(self.zone),
                "line": self.line(), "targets": list(self.targets), "textures": list(self.textures),
                "avoid": list(self.avoid), "source": self.source,
                "label": FROM_FACE if self.source == "face" else FROM_ANSWERS,
                "from": list(self.from_), "see_doctor": self.see_doctor, "data_source": self.data_source}


def build_needs(zones: dict[str, ZoneRead], measured: dict[str, float] | None,
                suspects: set[str] | None = None) -> list[Need]:
    """Zone needs first (one per zone, or one whole-face need when both zones match), then each
    measured concern under the threshold, lowest score first. A concern that lands on a need
    already listed for the same zone is merged into it rather than listed twice."""
    d = data()
    suspects = set(suspects or ())
    out: list[Need] = []

    def add(n: Need) -> Need:
        for have in out:
            if have.key == n.key and (have.zone == n.zone or have.zone == "whole"):
                have.targets += [t for t in n.targets if t not in have.targets]
                have.from_ += [f for f in n.from_ if f not in have.from_]
                have.avoid += [a for a in n.avoid if a not in have.avoid]
                return have
        out.append(n)
        return n

    zone_list = [("whole", zones["t_zone"])] if same_type(zones) else [(z, zones[z]) for z in ZONES]
    for zone, zr in zone_list:
        spec = d["zone_needs"][zr.type]
        add(Need(spec["key"], spec["words"], zone, list(spec["targets"]), list(spec["textures"]),
                 list(spec.get("avoid", [])), zr.source, ["zone type"], data_source=spec.get("source")))
    for zone, zr in [(z, zones[z]) for z in ZONES]:
        if zr.redness:
            spec = d["zone_needs"]["redness"]
            add(Need(spec["key"], spec["words"], zone, list(spec["targets"]), [], list(spec["avoid"]),
                     zr.source, ["zone type"], data_source=spec.get("source")))

    thr = d["concern_threshold"]
    scored = sorted(((c, v) for c, v in (measured or {}).items()
                     if isinstance(v, (int, float)) and v < thr and c in d["concern_needs"]),
                    key=lambda cv: cv[1])
    for concern, _ in scored:
        spec = d["concern_needs"][concern]
        zone = spec["zone"]
        if zone != "whole" and same_type(zones):
            zone = "whole"
        targets = [t for t in spec["targets"] if t not in suspects]
        blocked = [t for t in spec.get("not_if_suspect", []) if t in suspects]
        got = add(Need(spec["key"], spec["words"], zone, targets, [], list(spec.get("avoid", [])), "face",
                       [concern], see_doctor=spec.get("see_doctor"), data_source=spec.get("source")))
        got.avoid += [b for b in blocked if b not in got.avoid]
    return out


def needs_line(needs: list[Need], n: int = 3) -> str:
    return "Needs: " + ", ".join(x.line() for x in needs[:n]) + "." if needs else ""


def targets_for(needs: list[Need], zone: str) -> list[str]:
    """Every target ingredient aimed at this zone (its own needs plus whole-face ones)."""
    out: list[str] = []
    for n in needs:
        if n.zone in (zone, "whole") or zone == "whole":
            out += [t for t in n.targets if t not in out]
    return out


def textures_for(needs: list[Need], zone: str) -> list[str]:
    out: list[str] = []
    for n in needs:
        if n.zone in (zone, "whole") or zone == "whole":
            out += [t for t in n.textures if t not in out]
    return out


def avoid_for(needs: list[Need]) -> list[str]:
    out: list[str] = []
    for n in needs:
        out += [a for a in n.avoid if a not in out]
    return out


def finish_spec(finish: str | None) -> tuple[str, dict]:
    d = data()
    f = finish if finish in d["finishes"] else d["default_finish"]
    return f, d["finishes"][f]
