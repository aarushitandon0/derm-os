"""Patterns engine: which ingredient keeps turning up when your skin reacts?

This is docs/STRATEGY.md section 4, rules 1-7, and nothing more. It is deterministic, it carries
its inputs with every result, and it never names a cause. The strongest word it uses is "suspect".

The seven rules, in the order they are applied:

1. Reaction types are kept apart. `analyse("irritation", ...)` and `analyse("breakout", ...)` are
   separate runs over separate failure sets. They never share a suspect list.
2. "Suited" only counts after >= 4 weeks (app/outcomes.py). A shorter "suited" clears nothing.
3. Contrast decides the tier:
      SUSPECT       in >= 2 failed products of this type, and 0 suited products
      LEAD          in 1 failed product, and 0 suited products
      CLEARED_SO_FAR in at least one suited product ("used without that problem in X")
   With exactly one failed product we say plainly that we cannot narrow it down, and we name no
   suspects and no leads at all. That is the rule, not a shortcut: with a single failed label,
   every line on it is in "1 failed product and 0 suited", so calling them leads would dress up
   a whole ingredient list as evidence. What the user gets instead is the honest sentence and the
   list of lines that appear in nothing that suited them.
4. Personal evidence and general knowledge are labelled separately: `evidence` is "personal" or
   "general", and a general note never changes a tier.
5. Ingredient families come from the versioned app/families.json. An exact ingredient match always
   ranks above a family match.
6. Missing is not safe. A failed or suited product with an incomplete INCI is counted, flagged,
   and its unknown remainder is reported, never silently treated as clean.
7. Purging is only ever OFFERED, never applied, and only when all three hold: a purge-capable
   ingredient, the user's usual spots, and it settled within ~6 weeks while still in use.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum

from . import families as FAM
from .decision import Product
from .inci import canonical, clean
from .outcomes import ProductOutcome, split

RULE_VERSION = "patterns-1.0"

KINDS = ("irritation", "breakout")

# Rule 7: purge-consistent means it settled within about this many weeks.
PURGE_SETTLE_WEEKS = 6

# Rule 8 of the MVP brief: for breakouts a wash-off product gets less weight than a leave-on one,
# and the lower weight is always shown with its own label. Irritation is not weighted: a cleanser
# that stings, stings.
WASH_OFF_WEIGHT = 0.5
LEAVE_ON_WEIGHT = 1.0
WASH_OFF_LABEL = "Washed off, so it counts for less here"


class Tier(str, Enum):
    SUSPECT = "suspect"
    LEAD = "lead"
    CLEARED = "cleared_so_far"


TIER_ORDER = {Tier.SUSPECT: 0, Tier.LEAD: 1, Tier.CLEARED: 2}

TIER_LABEL = {
    Tier.SUSPECT.value: "Suspect",
    Tier.LEAD.value: "Lead",
    Tier.CLEARED.value: "Used without this problem",
}


@dataclass
class Appearance:
    """One ingredient's appearance on one product's label."""
    product_id: str
    product_name: str
    label_line: str
    inci_position: int          # 1-based position on the label
    inci_length: int
    leave_on: bool
    weight: float
    weight_label: str | None = None

    def to_dict(self) -> dict:
        return {"product_id": self.product_id, "product_name": self.product_name,
                "label_line": self.label_line, "inci_position": self.inci_position,
                "inci_length": self.inci_length, "leave_on": self.leave_on,
                "weight": self.weight, "weight_label": self.weight_label}


@dataclass
class Suspect:
    ingredient: str                   # canonical key
    display: str                      # the label line as most recently seen
    tier: str
    match_type: str                   # "exact" | "family"
    family: str | None
    evidence: str                     # "personal" | "general"
    in_failed: list[Appearance] = field(default_factory=list)
    in_suited: list[Appearance] = field(default_factory=list)
    failed_total: int = 0
    suited_total: int = 0
    general_note: str | None = None
    failed_phrase: str = "that bothered your skin"

    @property
    def failed_weight(self) -> float:
        return round(sum(a.weight for a in self.in_failed), 2)

    def counts_line(self) -> str:
        """"in 2 of 2 products that made you itch, 0 of 3 that suited you" (STRATEGY 4, moment 1)."""
        n_f = len({a.product_id for a in self.in_failed})
        n_s = len({a.product_id for a in self.in_suited})
        return (f"in {n_f} of {self.failed_total} product"
                f"{'' if self.failed_total == 1 else 's'} {self.failed_phrase}, "
                f"{n_s} of {self.suited_total} that suited you")

    def to_dict(self) -> dict:
        return {
            "ingredient": self.ingredient, "display": self.display, "tier": self.tier,
            "tier_label": TIER_LABEL[self.tier], "match_type": self.match_type,
            "family": self.family, "family_label": FAM.label_of(self.family) if self.family else None,
            "evidence": self.evidence, "general_note": self.general_note,
            "in_failed": [a.to_dict() for a in self.in_failed],
            "in_suited": [a.to_dict() for a in self.in_suited],
            "failed_count": len({a.product_id for a in self.in_failed}),
            "failed_total": self.failed_total,
            "suited_count": len({a.product_id for a in self.in_suited}),
            "suited_total": self.suited_total,
            "failed_weight": self.failed_weight,
            "counts_line": self.counts_line(),
        }


@dataclass
class PurgeOffer:
    """Rule 7. Offered to the user as a question, never applied by the engine."""
    product_id: str
    product_name: str
    ingredient: str
    label_line: str
    strength: str                   # "can" | "mild"
    settled_week: int | None
    question: str
    note: str

    def to_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class PatternReport:
    kind: str                         # "irritation" | "breakout"
    suspects: list[Suspect]
    failed_products: list[dict]
    suited_products: list[dict]
    # Rule 3, the one-failed-product case.
    cannot_narrow: str | None = None
    only_in_failed: list[dict] = field(default_factory=list)
    # Rule 6.
    incomplete_products: list[dict] = field(default_factory=list)
    unknown_note: str | None = None
    # Rule 7, breakout runs only.
    purge_offers: list[PurgeOffer] = field(default_factory=list)
    headline: str = ""
    rule_version: str = RULE_VERSION
    families_version: str = FAM.FAMILIES_VERSION

    def top(self) -> Suspect | None:
        return self.suspects[0] if self.suspects else None

    def to_dict(self) -> dict:
        return {
            "kind": self.kind, "headline": self.headline,
            "suspects": [s.to_dict() for s in self.suspects],
            "failed_products": self.failed_products, "suited_products": self.suited_products,
            "cannot_narrow": self.cannot_narrow, "only_in_failed": self.only_in_failed,
            "incomplete_products": self.incomplete_products, "unknown_note": self.unknown_note,
            "purge_offers": [p.to_dict() for p in self.purge_offers],
            "rule_version": self.rule_version, "families_version": self.families_version,
        }


FAILED_PHRASE = {"irritation": "that made you itch, sting or burn",
                 "breakout": "that broke you out"}


def _weight(kind: str, leave_on: bool) -> tuple[float, str | None]:
    """Rule 8: wash-off products count for less in a breakout run, and say so."""
    if kind == "breakout" and not leave_on:
        return WASH_OFF_WEIGHT, WASH_OFF_LABEL
    return LEAVE_ON_WEIGHT, None


def _appearances(outs: list[ProductOutcome], catalog: dict[str, Product], kind: str
                 ) -> tuple[dict[str, list[Appearance]], dict[str, list[Appearance]], list[dict]]:
    """canonical ingredient -> where it appears, plus the family index and the incomplete labels."""
    exact: dict[str, list[Appearance]] = {}
    fam: dict[str, list[Appearance]] = {}
    incomplete: list[dict] = []
    for o in outs:
        p = catalog.get(o.product_id)
        if p is None:
            continue
        w, wlabel = _weight(kind, p.leave_on)
        if not p.inci_complete:
            incomplete.append({"product_id": p.id, "product_name": p.name,
                               "listed": len(p.inci),
                               "note": "This label's ingredient list is incomplete, so anything not "
                                       "listed stays unknown. Unknown is not a pass."})
        for i, raw in enumerate(p.inci, 1):
            if not clean(raw):
                continue
            a = Appearance(p.id, p.name, raw.strip(), i, len(p.inci), p.leave_on, w, wlabel)
            exact.setdefault(canonical(raw), []).append(a)
            for f in FAM.family_of(raw):
                fam.setdefault(f, []).append(a)
    return exact, fam, incomplete


def _product_rows(outs: list[ProductOutcome], catalog: dict[str, Product],
                  today: date | None) -> list[dict]:
    rows = []
    for o in outs:
        p = catalog.get(o.product_id)
        rows.append({**o.to_dict(today), "product_name": p.name if p else o.product_id,
                     "inci_complete": p.inci_complete if p else None,
                     "inci_length": len(p.inci) if p else None})
    return rows


def analyse(kind: str, outcomes: list[ProductOutcome], catalog: dict[str, Product],
            today: date | None = None) -> PatternReport:
    """One run for one reaction type. Rules 1-7 of docs/STRATEGY.md section 4."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}, not {kind!r}")
    groups = split(outcomes, today)                     # rule 2 lives in outcomes.split
    failed = groups[kind]                               # rule 1: only this type's failures
    suited = groups["suited"]

    f_exact, f_fam, f_incomplete = _appearances(failed, catalog, kind)
    s_exact, s_fam, s_incomplete = _appearances(suited, catalog, kind)
    n_failed, n_suited = len(failed), len(suited)
    phrase = FAILED_PHRASE[kind]

    suspects: list[Suspect] = []
    # Rule 3: a single failed product cannot produce suspects or leads. Cleared entries are still
    # worth computing, because "you've used that without this problem" is useful on its own.
    can_rank = n_failed >= 2

    def add(ingredient: str, match_type: str, family: str | None,
            fa: list[Appearance], sa: list[Appearance]) -> None:
        # Rule 3, applied to distinct products, not to label lines.
        f_ids = {a.product_id for a in fa}
        s_ids = {a.product_id for a in sa}
        if not f_ids:
            return
        if s_ids:
            tier = Tier.CLEARED
        elif not can_rank:
            return
        elif len(f_ids) >= 2:
            tier = Tier.SUSPECT
        else:
            tier = Tier.LEAD
        display = fa[-1].label_line if match_type == "exact" else FAM.label_of(family or "")
        s = Suspect(ingredient=ingredient, display=display, tier=tier.value, match_type=match_type,
                    family=family, evidence="personal",
                    in_failed=sorted(fa, key=lambda a: (a.product_id, a.inci_position)),
                    in_suited=sorted(sa, key=lambda a: (a.product_id, a.inci_position)),
                    failed_total=n_failed, suited_total=n_suited,
                    general_note=FAM.general_note(family) if family else None)
        s.failed_phrase = phrase
        suspects.append(s)

    for key, fa in f_exact.items():
        add(key, "exact", (FAM.family_of(key) or [None])[0], fa, s_exact.get(key, []))
    exact_keys = set(f_exact)
    for family, fa in f_fam.items():
        # Rule 5: a family entry is only worth reporting for what the exact lines didn't already
        # cover, and it always sorts below an exact match of the same strength.
        if all(canonical(a.label_line) in exact_keys for a in fa) and len(
                {canonical(a.label_line) for a in fa}) == 1:
            continue
        add(family, "family", family, fa, s_fam.get(family, []))

    # Rule 5: exact above family. Then strongest tier, then most failed products, then weight.
    suspects.sort(key=lambda s: (TIER_ORDER[Tier(s.tier)], 0 if s.match_type == "exact" else 1,
                                 -len({a.product_id for a in s.in_failed}), -s.failed_weight,
                                 s.ingredient))

    report = PatternReport(
        kind=kind, suspects=suspects,
        failed_products=_product_rows(failed, catalog, today),
        suited_products=_product_rows(suited, catalog, today),
        incomplete_products=f_incomplete + s_incomplete,
    )

    # Rule 3, the honest one-product case.
    if n_failed == 1:
        p = catalog.get(failed[0].product_id)
        n_ing = len(p.inci) if p else 0
        report.cannot_narrow = (
            f"One product can't tell us which of its {n_ing} ingredients did it. "
            "It takes a second product with the same problem, and ones that suited you, to narrow down.")
        # The lines on that one label that appear in nothing which suited you. Not leads: just
        # the shortlist that is left once the ones you've used without trouble are taken out.
        report.only_in_failed = [
            {"ingredient": key, "display": appearances[0].label_line, "match_type": "exact",
             "inci_position": appearances[0].inci_position,
             "inci_length": appearances[0].inci_length}
            for key, appearances in f_exact.items() if key not in s_exact]
        report.only_in_failed.sort(key=lambda r: r["inci_position"])

    # Rule 6.
    if report.incomplete_products:
        names = ", ".join(sorted({r["product_name"] for r in report.incomplete_products}))
        report.unknown_note = (f"Incomplete ingredient list on: {names}. Anything not printed there "
                               "stays unknown, and unknown is not a pass.")

    # Rule 7, breakouts only.
    if kind == "breakout":
        report.purge_offers = purge_offers(failed, catalog)

    report.headline = headline(report)
    return report


def purge_offers(breakouts: list[ProductOutcome], catalog: dict[str, Product]) -> list[PurgeOffer]:
    """Rule 7. All three conditions must hold, and the result is only ever an offer.

    A breakout is never silently reclassified as purging: the user is asked, because only they
    know whether those are their usual spots and whether it settled while they kept using it.
    """
    out: list[PurgeOffer] = []
    for o in breakouts:
        p = catalog.get(o.product_id)
        if p is None:
            continue
        capable = FAM.purge_capable_in(p.inci)
        if not capable:                                   # condition 1
            continue
        if o.usual_spots is not True:                     # condition 2
            continue
        if not o.settled_while_using:                     # condition 3
            continue
        week = o.settled_week
        if week is not None and week > PURGE_SETTLE_WEEKS:
            continue
        top = capable[0]
        when = f"by week {week}" if week is not None else "while you kept using it"
        out.append(PurgeOffer(
            product_id=p.id, product_name=p.name, ingredient=top["ingredient"],
            label_line=top["label_line"], strength=top["strength"], settled_week=week,
            question=(f"{p.name} lists {top['label_line']}, the spots were in your usual places, and it "
                      f"settled {when}. That pattern is consistent with purging rather than a "
                      f"breakout. Do you want to record it as purging instead?"),
            note=top["note"]))
    return out


def headline(r: PatternReport) -> str:
    """One sentence for the top of the screen. Inside the wording ceiling."""
    word = "itch, sting or burn" if r.kind == "irritation" else "break out"
    if not r.failed_products:
        return f"Nothing recorded yet that made you {word}, so there is no pattern to read."
    if r.cannot_narrow:
        p = r.failed_products[0]
        return (f"Can't narrow it down yet: only {p['product_name']} has made you {word}. "
                f"{r.cannot_narrow}")
    top = r.top()
    if top is None:
        return (f"{len(r.failed_products)} product(s) made you {word}, but no shared ingredient came "
                "through on the labels we have.")
    if top.tier == Tier.SUSPECT.value:
        return f"Suspect: {top.display}, {top.counts_line()}."
    if top.tier == Tier.LEAD.value:
        return f"Lead, not a suspect yet: {top.display}, {top.counts_line()}."
    return (f"No suspect: every shared ingredient also appears in something that suited you. "
            f"Closest is {top.display}, {top.counts_line()}.")


def run_both(outcomes: list[ProductOutcome], catalog: dict[str, Product],
             today: date | None = None) -> dict[str, PatternReport]:
    """Rule 1 in one call: two separate runs, two separate suspect lists."""
    return {k: analyse(k, outcomes, catalog, today) for k in KINDS}
