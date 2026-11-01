"""Quick history by ingredient (chips-1.0).

Most people don't know which product label made them itch, but they do remember "vitamin C made me
itch" or "azelaic acid broke me out". A chip is that memory: one ingredient (or group) and what
happened. The data is app/chips.json, versioned; every chip maps to canonical INCI keys and, where
one exists, to a family in app/families.json.

The rules, in the order they apply to one product:

1. "suited me" is shown as "worked for you". It never excludes anything.
2. itched / stung / burned -> skip any product that lists it, exact or same group, and say which.
   With "clinician-confirmed" ticked it also becomes the existing CONFIRMED_ALLERGY record type
   (app/decision.py), so the cart check blocks it like any other confirmed record.
3. broke out / closed comedones -> skip only products where it is a KEY active (first five label
   lines, water not counted, or printed with a percentage), and say plainly that it may have been
   the rest of that product's formula, not this ingredient.
4. For a purge-capable ingredient (families.json purge_capable) the user is asked once: "Was it in
   your usual spots, and did it settle within about 6 weeks?" A yes turns into an OFFER to record it
   as possible purging. It is never decided silently: until the user picks "possible purging", the
   chip stays a breakout and rule 3 applies.
5. Product-level history (records, outcomes) ranks above chips: the basket shows the product-level
   reason first whenever both apply. That ordering lives in app/basket.py (SKIP_ORDER).

Nothing here says "caused" or "allergy" about the user's own report: an ingredient "itched, stung or
burned on you before", in their words.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from . import families as FAM
from .decision import HistoryRecord, RecordType
from .inci import SYNONYMS, canonical, clean

DATA_PATH = Path(__file__).parent / "chips.json"


@lru_cache(maxsize=4)
def data(path: str | None = None) -> dict:
    return json.loads(Path(path or DATA_PATH).read_text(encoding="utf-8"))


RULE_VERSION = data()["version"]
REACTIONS: dict[str, str] = data()["reactions"]
FAILED = ("itched", "broke_out", "comedones")
PURGE_QUESTION: str = data()["purge_question"]
PURGE_OFFER: str = data()["purge_offer"]
TOP_LINES: int = data()["key_active_rule"]["top_lines"]

# What each reaction reads as inside a sentence.
REACTED = {"itched": "itched, stung or burned on you", "broke_out": "broke you out",
           "comedones": "gave you closed comedones"}


def _spec(raw: dict) -> dict:
    exact = list(raw.get("exact", []))
    members = list(dict.fromkeys(exact + list(raw.get("members", []))
                                 + (FAM.members_of(raw["family"]) if raw.get("family") else [])))
    purge = any(FAM.is_purge_capable(m) for m in members)
    return {"id": raw["id"], "label": raw["label"], "word": raw["word"], "family": raw.get("family"),
            "exact": exact, "members": members, "purge_capable": purge,
            "aliases": list(raw.get("aliases", []))}


def catalogue() -> list[dict]:
    """Every chip the basket's question 2 offers, in display order."""
    return [_spec(c) for c in data()["chips"]]


def spec_of(chip_id: str) -> dict | None:
    if chip_id.startswith("free:"):
        return match_text(chip_id[5:])
    return next((c for c in catalogue() if c["id"] == chip_id), None)


def match_text(text: str) -> dict | None:
    """Free text -> a chip. Tried in order: a chip's own name or alias, an ingredient a chip covers,
    a family in families.json (by key, label or member), then any INCI name the synonym table knows.
    None when nothing matches: the screen then says so instead of guessing."""
    t = clean(text or "")
    if not t or len(t) > 60:
        return None
    key = canonical(t)
    for c in catalogue():
        names = {clean(c["label"]), clean(c["word"]), c["id"].replace("_", " ")} | {clean(a) for a in c["aliases"]}
        if t in names or key in c["exact"]:
            return c
    for c in catalogue():
        if key in c["members"]:
            return c
    for fam, spec in FAM.families().items():
        if t in (fam, clean(spec["label"])) or key in spec["members"]:
            return {"id": f"free:{fam}", "label": spec["label"].capitalize(), "word": spec["label"],
                    "family": fam, "exact": list(spec["members"]), "members": list(spec["members"]),
                    "purge_capable": any(FAM.is_purge_capable(m) for m in spec["members"]), "aliases": []}
    known = set(SYNONYMS) | {s for v in SYNONYMS.values() for s in v}
    if t in known or key in SYNONYMS:
        return {"id": f"free:{key}", "label": key.capitalize(), "word": key, "family": None,
                "exact": [key], "members": [key], "purge_capable": FAM.is_purge_capable(key), "aliases": []}
    return None


@dataclass
class Chip:
    chip: str                                 # chip id, or "free:<text>"
    reaction: str                             # one of REACTIONS
    product_name: str = ""                    # optional: the user may remember it
    confirmed_allergy: bool = False           # clinician-confirmed: becomes the existing record type
    # The purge question (rule 4). None means "not asked yet".
    usual_spots_settled: str | None = None    # "yes" | "no" | "not_sure"
    purge_choice: str | None = None           # "purging" | "breakout"; None means not chosen
    spec: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.reaction not in REACTIONS:
            raise ValueError(f"Unknown reaction {self.reaction!r}")
        spec = spec_of(self.chip)
        if spec is None:
            raise ValueError(f"Unknown ingredient chip {self.chip!r}")
        self.spec = spec
        if self.reaction != "itched":
            self.confirmed_allergy = False
        if self.reaction not in ("broke_out", "comedones") or not spec["purge_capable"]:
            self.usual_spots_settled = None
            self.purge_choice = None
        if self.usual_spots_settled not in (None, "yes", "no", "not_sure"):
            raise ValueError("usual_spots_settled must be yes, no or not_sure")
        if self.purge_choice not in (None, "purging", "breakout"):
            raise ValueError("purge_choice must be purging or breakout")
        if self.usual_spots_settled != "yes":
            self.purge_choice = None          # the offer only exists after a yes
        self.product_name = (self.product_name or "").strip()[:80]

    @property
    def word(self) -> str:
        return self.spec["word"]

    @property
    def purging(self) -> bool:
        return self.purge_choice == "purging"

    def purge_question(self) -> str | None:
        if self.reaction in ("broke_out", "comedones") and self.spec["purge_capable"]:
            return PURGE_QUESTION
        return None

    def purge_offer(self) -> str | None:
        """Only after the user answered yes, and only until they choose."""
        if self.purge_question() and self.usual_spots_settled == "yes":
            return PURGE_OFFER
        return None

    def line(self) -> str:
        """How the chip reads back on screen, in the user's terms."""
        w = self.word[0].upper() + self.word[1:]
        if self.reaction == "suited":
            return f"{w} worked for you."
        if self.reaction == "not_sure":
            return f"{w}: not sure."
        if self.purging:
            return f"{w}: you recorded it as possible purging."
        extra = " Clinician-confirmed." if self.confirmed_allergy else ""
        return f"{w} {REACTED[self.reaction]}.{extra}"

    def to_dict(self) -> dict:
        return {"chip": self.chip, "reaction": self.reaction, "reaction_label": REACTIONS[self.reaction],
                "product_name": self.product_name, "confirmed_allergy": self.confirmed_allergy,
                "usual_spots_settled": self.usual_spots_settled, "purge_choice": self.purge_choice,
                "label": self.spec["label"], "word": self.word, "line": self.line(),
                "purge_question": self.purge_question(), "purge_offer": self.purge_offer(),
                "purge_capable": self.spec["purge_capable"], "rule_version": RULE_VERSION}

    @staticmethod
    def from_dict(row: dict) -> "Chip":
        keep = {"chip", "reaction", "product_name", "confirmed_allergy", "usual_spots_settled", "purge_choice"}
        return Chip(**{k: v for k, v in row.items() if k in keep})


def parse_all(rows: list[dict] | None) -> list[Chip]:
    """Stored rows -> chips. A row that no longer parses (data changed) is dropped, not guessed."""
    out = []
    for r in rows or []:
        try:
            out.append(r if isinstance(r, Chip) else Chip.from_dict(r))
        except (ValueError, TypeError):
            continue
    return out


# ---------------------------------------------------------------- one product
def _non_water(inci: list[str]) -> list[tuple[int, str, str]]:
    """(position among non-water lines, raw label line, canonical key)."""
    out, n = [], 0
    for raw in inci:
        if not clean(raw):
            continue
        key = canonical(raw)
        if key != "water":
            n += 1
        out.append((n if key != "water" else 0, raw.strip(), key))
    return out


def is_key_active(raw: str, position: int) -> bool:
    return (0 < position <= TOP_LINES) or bool(re.search(r"\d\s*%", raw))


def matches(inci: list[str], spec: dict) -> list[dict]:
    out = []
    for pos, raw, key in _non_water(inci):
        if key in spec["members"]:
            out.append({"label_line": raw, "ingredient": key, "position": pos,
                        "match_type": "exact" if key in spec["exact"] else "family",
                        "key_active": is_key_active(raw, pos)})
    return out


def evaluate(inci: list[str], chips: list[Chip]) -> dict:
    """What the chips say about one label: skip reasons, 'worked for you' lines and notes."""
    skip: list[dict] = []
    worked: list[str] = []
    notes: list[str] = []
    for c in chips:
        hits = matches(inci, c.spec)
        if not hits:
            continue
        w = c.word
        W = w[0].upper() + w[1:]
        if c.reaction == "suited":
            worked.append(f"Lists {hits[0]['label_line']}: {w} worked for you.")
        elif c.reaction == "itched":
            h = next((h for h in hits if h["match_type"] == "exact"), hits[0])
            group = "" if h["match_type"] == "exact" else f", from the same group as {w}"
            skip.append({"chip": c.chip, "ingredient": h["ingredient"], "match_type": h["match_type"],
                         "line": f"Lists {h['label_line']}{group}. {W} {REACTED['itched']} before."})
        elif c.reaction in ("broke_out", "comedones"):
            key = [h for h in hits if h["key_active"]]
            if c.purging:
                notes.append(f"Lists {hits[0]['label_line']}. You recorded {w} as possible purging, so it "
                             f"isn't skipped: patch-test it first.")
            elif key:
                h = key[0]
                skip.append({"chip": c.chip, "ingredient": h["ingredient"], "match_type": h["match_type"],
                             "line": f"{h['label_line']} is a key active here, and {w} {REACTED[c.reaction]} "
                                     f"before. That may have been the rest of that product's formula, "
                                     f"not {w} itself."})
    return {"skip": skip, "worked": worked, "notes": notes}


# ---------------------------------------------------------------- what the other engines read
def records_from(chips: list[Chip]) -> list[HistoryRecord]:
    """Clinician-confirmed chips become the existing hard-block record type, one per ingredient."""
    out = []
    for c in chips:
        if c.reaction == "itched" and c.confirmed_allergy:
            for m in c.spec["members"]:
                out.append(HistoryRecord(RecordType.CONFIRMED_ALLERGY, ingredient=m,
                                         note=f"From your ingredient history: {c.spec['label']}"))
    return out


def itched_members(chips: list[Chip]) -> set[str]:
    """Ingredients the needs engine should stop aiming at (they itched)."""
    return {m for c in chips if c.reaction == "itched" for m in c.spec["members"]}


def avoid_items(chips: list[Chip]) -> list[dict]:
    """For "what to look for": what to avoid and the user's own reason."""
    out = []
    for c in chips:
        if c.reaction == "itched":
            out.append({"what": c.word, "why": f"{REACTED['itched']} before", "chip": c.chip})
        elif c.reaction in ("broke_out", "comedones") and not c.purging:
            out.append({"what": f"{c.word} as a key active", "why": f"{REACTED[c.reaction]} before",
                        "chip": c.chip})
    return out


def worked_words(chips: list[Chip]) -> list[str]:
    return [c.word for c in chips if c.reaction == "suited"]
