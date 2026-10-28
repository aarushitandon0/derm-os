"""Decision engine: exclusions, routine building, option comparison, next question.

Deterministic on purpose. Every result carries the reason that produced it,
so the explanation layer never has to invent one.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from .inci import canonical, canonical_list, clean, expand_avoid

RULE_VERSION = "decision-1.0"
CATALOG_PATH = Path(__file__).parent / "catalog.json"


class RecordType(str, Enum):
    SUSPECTED_REACTION = "suspected_reaction"   # "product X bothered my skin"  -> blocks that product only
    AVOID = "avoid"                             # "I choose to avoid ingredient Y" -> blocks the ingredient
    CONFIRMED_ALLERGY = "confirmed_allergy"     # clinician-confirmed ingredient allergy -> blocks the ingredient


@dataclass
class HistoryRecord:
    type: RecordType
    product_id: str | None = None
    ingredient: str | None = None
    note: str = ""

    def __post_init__(self):
        if self.type == RecordType.SUSPECTED_REACTION and not self.product_id:
            raise ValueError("A suspected reaction must name a product")
        if self.type in (RecordType.AVOID, RecordType.CONFIRMED_ALLERGY) and not self.ingredient:
            raise ValueError("Avoid / confirmed allergy records must name an ingredient")


@dataclass
class Product:
    id: str
    name: str
    brand: str
    role: str
    leave_on: bool
    price_inr: int
    inci: list[str]
    inci_complete: bool
    source: str = ""

    @property
    def canonical_inci(self) -> list[str]:
        return canonical_list(self.inci)


def load_catalog(path: Path = CATALOG_PATH) -> dict[str, Product]:
    rows = json.loads(Path(path).read_text())
    return {r["id"]: Product(**r) for r in rows}


class Status(str, Enum):
    PASS = "pass"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"
    # No ingredient exclusions recorded: nothing was checked, so this is neutral, never a pass.
    NOTHING_TO_CHECK = "nothing_to_check"


INCOMPLETE_TAG = "ingredient_list_incomplete"


@dataclass
class Check:
    product_id: str
    status: Status
    reasons: list[str] = field(default_factory=list)
    matches: list[dict] = field(default_factory=list)   # {"label_line": ..., "matched": ..., "record": ...}
    # Shown whatever the status. INCOMPLETE_TAG whenever the label's ingredient list is incomplete.
    tags: list[str] = field(default_factory=list)

    def to_dict(self):
        return {"product_id": self.product_id, "status": self.status.value,
                "reasons": self.reasons, "matches": self.matches, "tags": self.tags}


def check_product(p: Product, records: list[HistoryRecord]) -> Check:
    reasons, matches = [], []
    tags = [] if p.inci_complete else [INCOMPLETE_TAG]
    for r in records:
        if r.type == RecordType.SUSPECTED_REACTION and r.product_id == p.id:
            reasons.append(f"You reported a reaction to {p.name}.")
            matches.append({"label_line": None, "matched": p.id, "record": r.type.value})

    ingredient_records = [r for r in records if r.type in (RecordType.AVOID, RecordType.CONFIRMED_ALLERGY)]
    for r in ingredient_records:
        targets = expand_avoid(r.ingredient)
        for raw, canon in zip(p.inci, p.canonical_inci):
            if canon in targets:
                why = "you chose to avoid" if r.type == RecordType.AVOID else "you have a confirmed allergy to"
                reasons.append(f'Label lists "{raw.strip()}", and {why} {clean(r.ingredient)}.')
                matches.append({"label_line": raw.strip(), "matched": canon, "record": r.type.value})

    if matches:
        return Check(p.id, Status.BLOCKED, reasons, matches, tags)
    if not ingredient_records:
        # A product-level reaction elsewhere says nothing about this product's ingredients.
        return Check(p.id, Status.NOTHING_TO_CHECK,
                     ["Nothing to check against yet: you haven't recorded an ingredient to avoid. "
                      "This is not a pass."], tags=tags)
    if not p.inci_complete:
        return Check(p.id, Status.UNKNOWN,
                     ["The full ingredient list isn't available, so your exclusions can't be checked. "
                      "This is not a pass."], tags=tags)
    return Check(p.id, Status.PASS, ["No match with your recorded exclusions."], tags=tags)


@dataclass
class OptionItem:
    product_id: str
    mode: str | None = None   # "add" | "replace" | None (not yet answered)


@dataclass
class Option:
    name: str
    items: list[OptionItem]


@dataclass
class RoutineResult:
    name: str
    steps: list[str]                     # product ids in routine order
    added: list[str]
    replaced: list[dict]                 # {"out": id, "in": id}
    kept: list[str]
    stopped: list[str]                   # products you'd stop using (replaced ones)
    step_count: int                      # number of steps after the change
    new_spend_inr: int                   # price of the new product(s): you buy them whether added or replacing
    duplicate_roles: list[str]
    checks: list[Check]
    blocked: bool
    unknowns: list[str]
    new_leave_on: int
    open_questions: list[dict]

    def to_dict(self):
        d = self.__dict__.copy()
        d["checks"] = [c.to_dict() for c in self.checks]
        return d


ROLE_ORDER = ["cleanser", "toner", "serum", "treatment", "moisturiser", "sunscreen"]


def _order(ids: list[str], cat: dict[str, Product]) -> list[str]:
    return sorted(ids, key=lambda i: (ROLE_ORDER.index(cat[i].role) if cat[i].role in ROLE_ORDER else 99))


def build(current: list[str], option: Option, cat: dict[str, Product],
          records: list[HistoryRecord]) -> RoutineResult:
    steps = list(current)
    added, replaced, questions = [], [], []
    for it in option.items:
        p = cat[it.product_id]
        same_role = [s for s in steps if cat[s].role == p.role]
        mode = it.mode
        if mode is None and same_role:
            questions.append({
                "id": f"mode:{option.name}:{p.id}",
                "text": f"Is {p.name} replacing your {cat[same_role[0]].name}, or added alongside it?",
                "choices": ["replace", "add"],
                "why": "The answer changes your routine, your spend and how many new products you test at once.",
            })
            mode = "add"   # provisional; shown as unanswered in the UI
        if mode == "replace" and same_role:
            out = same_role[0]
            steps[steps.index(out)] = p.id
            replaced.append({"out": out, "in": p.id})
        else:
            steps.append(p.id)
            added.append(p.id)
    new_ids = added + [r["in"] for r in replaced]
    checks = [check_product(cat[i], records) for i in new_ids]
    roles = [cat[s].role for s in steps]
    dup = sorted({r for r in roles if roles.count(r) > 1})
    kept = [s for s in steps if s in current]
    return RoutineResult(
        name=option.name,
        steps=_order(steps, cat),
        added=added,
        replaced=replaced,
        kept=kept,
        stopped=[r["out"] for r in replaced],
        step_count=len(steps),
        new_spend_inr=sum(cat[i].price_inr for i in new_ids),
        duplicate_roles=dup,
        checks=checks,
        blocked=any(c.status == Status.BLOCKED for c in checks),
        unknowns=[c.product_id for c in checks if c.status == Status.UNKNOWN],
        new_leave_on=sum(1 for i in new_ids if cat[i].leave_on),
        open_questions=questions,
    )


def compare(current: list[str], options: list[Option], cat: dict[str, Product],
            records: list[HistoryRecord]) -> dict:
    """Always includes 'Change nothing' as the first column."""
    cols = [build(current, Option("Change nothing", []), cat, records)]
    cols += [build(current, o, cat, records) for o in options]
    q = next_question(cols)
    return {"columns": [c.to_dict() for c in cols], "next_question": q, "rule_version": RULE_VERSION}


def next_question(cols: list[RoutineResult]) -> dict | None:
    """Ask only questions whose answer changes the table. 'Replace or add' always does,
    because it changes steps, spend and the number of new leave-on products."""
    for c in cols:
        if c.open_questions:
            return c.open_questions[0]
    return None
