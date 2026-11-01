"""Cart check: should this one product go in your cart?

docs/STRATEGY.md section 4, Moment 1. The purchase moment, run against three things that are all
the user's own: their recorded history, their measured skin, and the shelf they already own.

The verdict is a deterministic ladder, first match wins:

    BLOCKED              it lists something you avoid, or a clinician-confirmed allergen
    REPEATS_A_PATTERN    it lists, by name, a SUSPECT from your own history (app/patterns.py)
    PATCH_TEST_FIRST     it lists a LEAD, or matches an ingredient family you have reacted to
    NO_CONFLICTS         nothing of yours matched. Never "safe"

Note which match gets which rung: "repeats a pattern" needs the *exact* ingredient on the label.
A family match is one rung softer however strong the family's own evidence is, because "something
from the same group" is a reason to patch-test, not the same ingredient turning up again. That is
the exact-above-family rule from STRATEGY section 4, rule 5, applied to the ladder.

On top of the rung, an incomplete ingredient list adds the `unknown` tag. Missing is not safe, so
an unreadable label can never reach the bottom rung's wording: when the rung would have been
NO_CONFLICTS and the list is incomplete, the line the user reads is
"Ingredient list incomplete -> unknown". A stronger rung still stands on its own and carries the
tag beside it, because what we *could* read already matched.

Two wording rules the claim linter enforces: the skin source says "aimed at", never "fixes"; and
nothing here is ever called safe. "Change nothing" is always one of the options, and there is
exactly one next step.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from . import decision as D
from . import patterns as P
from .inci import canonical
from .outcomes import ProductOutcome

RULE_VERSION = "cartcheck-1.0"

# How many measured concerns count as "your top concerns" for the skin source.
TOP_CONCERNS = 3


class Rung(str, Enum):
    BLOCKED = "blocked"
    REPEATS_A_PATTERN = "repeats_a_pattern"
    PATCH_TEST_FIRST = "patch_test_first"
    NO_CONFLICTS = "no_conflicts"


# The ladder, in the order it is applied. Index 0 is checked first.
LADDER = [Rung.BLOCKED, Rung.REPEATS_A_PATTERN, Rung.PATCH_TEST_FIRST, Rung.NO_CONFLICTS]

RUNG_LABEL = {
    Rung.BLOCKED.value: "Blocked",
    Rung.REPEATS_A_PATTERN.value: "Repeats a pattern",
    Rung.PATCH_TEST_FIRST.value: "Patch-test first",
    Rung.NO_CONFLICTS.value: "No conflicts with your history",
}

UNKNOWN_TAG = "ingredient_list_incomplete"
UNKNOWN_LABEL = "Ingredient list incomplete → unknown"
# With no records and no outcomes there is nothing to check this label against. That is not the
# same as "no conflicts", and app/decision.py already keeps the two apart (Status.NOTHING_TO_CHECK,
# "This is not a pass"). The bottom rung says so rather than borrowing a reassurance it hasn't
# earned, which matters most to a beginner, whose history is empty by definition.
NOTHING_TO_CHECK_LABEL = "Nothing to check against yet"

# Exactly one next step per rung (STRATEGY: every screen ends with ONE next step).
NEXT_STEP = {
    Rung.BLOCKED.value: "Leave this one. It lists something you already recorded, so there is nothing to test.",
    Rung.REPEATS_A_PATTERN.value: "Leave this one out of your cart. If you still want to try it, patch-test a "
                                  "small area for 7–10 days first and tell us what happened.",
    Rung.PATCH_TEST_FIRST.value: "If you buy it, patch-test a small area for 7–10 days, then start it as your "
                                 "only new product. We'll set day 14 and day 28 check-ins.",
    Rung.NO_CONFLICTS.value: "If you buy it, start it as your only new product. We'll set day 14 and day 28 "
                             "check-ins so there's something to read it against.",
}
UNKNOWN_NEXT_STEP = ("Ask the shop for the full ingredient list before you buy. Until the label is complete, "
                     "your own records can't be checked against it.")
NOTHING_TO_CHECK_NEXT_STEP = ("If you buy it, start it as your only new product and tell us what happens. "
                              "That first result is what every later check reads against.")

CHANGE_NOTHING = ("Change nothing. Your shelf as it is costs nothing more, and nothing new has to be tested.")

NO_SCAN_LINE = "No scan yet: scan to see if this is aimed at your skin's top concerns."

# Plain words for the measured concerns, matching the labels the UI already uses.
CONCERN_WORD = {"pore": "pores", "acne": "breakouts", "age_spot": "spots", "redness": "redness",
                "texture": "texture", "oiliness": "oiliness", "moisture": "moisture",
                "radiance": "radiance"}


def concern_word(c: str) -> str:
    return CONCERN_WORD.get(c, c.replace("_", " "))


def _and_list(words: list[str]) -> str:
    if len(words) < 2:
        return "".join(words)
    return f"{', '.join(words[:-1])} and {words[-1]}"


def top_concerns(measured: dict[str, float] | None, n: int = TOP_CONCERNS) -> list[str]:
    """Your top concerns = your lowest YouCam raw scores (raw_score is higher for healthier-looking
    skin, so the lowest scores are the ones you'd call your concerns)."""
    if not measured:
        return []
    scored = [(k, v) for k, v in measured.items() if isinstance(v, (int, float))]
    return [k for k, _ in sorted(scored, key=lambda kv: kv[1])[:n]]


@dataclass
class Source:
    """One labelled source. The label is shown to the user exactly as written here."""
    key: str                   # "history" | "skin" | "shelf"
    label: str
    lines: list[str] = field(default_factory=list)
    detail: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"key": self.key, "label": self.label, "lines": list(self.lines), "detail": self.detail}


@dataclass
class CartCheck:
    product_id: str
    rung: str
    verdict_line: str
    tags: list[str]
    sources: list[Source]
    next_step: str
    change_nothing: str = CHANGE_NOTHING
    unknown: bool = False
    nothing_to_check: bool = False
    # Every result stores the inputs it was computed from, so a stored check can be re-read later.
    inputs: dict = field(default_factory=dict)
    rule_version: str = RULE_VERSION

    def to_dict(self) -> dict:
        return {
            "product_id": self.product_id, "rung": self.rung, "rung_label": RUNG_LABEL[self.rung],
            "verdict_line": self.verdict_line, "tags": list(self.tags), "unknown": self.unknown,
            "nothing_to_check": self.nothing_to_check,
            "sources": [s.to_dict() for s in self.sources],
            "next_step": self.next_step, "change_nothing": self.change_nothing,
            "inputs": self.inputs, "rule_version": self.rule_version,
        }


def _matched(product: D.Product, report: P.PatternReport) -> list[dict]:
    """Which of this product's label lines match something in one pattern run, and how."""
    keys = {canonical(raw): raw.strip() for raw in product.inci}
    out = []
    for s in report.suspects:
        if s.tier == P.Tier.CLEARED.value:
            continue
        if s.match_type == "exact":
            raw = keys.get(s.ingredient)
            if raw is None:
                continue
            hit = {"label_line": raw, "match_type": "exact"}
        else:
            members = [keys[k] for k in sorted(keys) if k in set(P.FAM.members_of(s.ingredient))]
            if not members:
                continue
            hit = {"label_line": ", ".join(members), "match_type": "family"}
        out.append({**hit, "ingredient": s.ingredient, "display": s.display, "tier": s.tier,
                    "kind": report.kind, "counts_line": s.counts_line(),
                    "family": s.family, "evidence": s.evidence, "general_note": s.general_note})
    # Exact before family, suspect before lead: the same order patterns.py sorted by.
    out.sort(key=lambda m: (0 if m["tier"] == P.Tier.SUSPECT.value else 1,
                            0 if m["match_type"] == "exact" else 1))
    return out


def _history_source(product: D.Product, check: D.Check, matches: list[dict]) -> Source:
    s = Source("history", "From your history")
    for r in check.reasons:
        if check.status == D.Status.BLOCKED:
            s.lines.append(r)
    # The matches that decided the rung are shown in full. Any weaker ones are counted, not
    # listed: with two failed labels, every excipient on one of them is technically a lead, and
    # printing all of them would bury the line that actually matters.
    shown = [m for m in matches
             if m["tier"] == P.Tier.SUSPECT.value and m["match_type"] == "exact"] or matches[:1]
    rest = [m for m in matches if m not in shown]
    for m in shown:
        word = "Suspect" if m["tier"] == P.Tier.SUSPECT.value else "Lead"
        how = "" if m["match_type"] == "exact" else " (a family match, which ranks below an exact one)"
        s.lines.append(f"{word}: label lists “{m['label_line']}”{how} — {m['counts_line']}.")
    if rest:
        s.lines.append(f"{len(rest)} weaker match{'' if len(rest) == 1 else 'es'} on this label "
                       f"(each in one product that bothered you and none that suited you). "
                       f"Listed in full below.")
    general = [m["general_note"] for m in shown if m.get("general_note")]
    if not s.lines:
        s.lines.append("Nothing on this label matches a product you've recorded a problem with. "
                       "That isn't a pass: it's the absence of a match.")
    s.detail = {"status": check.status.value, "matches": matches,
                # Rule 4: general knowledge is kept under its own label, never mixed in above.
                "general_knowledge": list(dict.fromkeys(general)),
                "decision_matches": check.matches}
    return s


def _skin_source(product: D.Product, measured: dict[str, float] | None,
                 zones: dict[str, str] | None = None) -> Source:
    s = Source("skin", "From your skin (YouCam)")
    tops = top_concerns(measured)
    if not tops:
        s.lines.append(NO_SCAN_LINE)
        s.detail = {"scanned": False, "top_concerns": [], "aimed_at": list(product.aimed_at), "matched": []}
        return s
    matched = [c for c in tops if c in product.aimed_at]
    if matched:
        # Named worst-score first, so the strongest match leads.
        matched = [c for c in tops if c in matched]
        names = _and_list([concern_word(c) for c in matched])
        best = matched[0]
        rank = tops.index(best) + 1
        where = f", {zones[best]}" if zones and zones.get(best) else ""
        place = ("your lowest YouCam score" if rank == 1
                 else f"your {_ordinal(rank)} lowest YouCam score")
        s.lines.append(f"Aimed at {names}. {concern_word(best).capitalize()} is {place} "
                       f"of the {len(tops)} we measured{where}.")
    else:
        s.lines.append(f"Not aimed at any of your top {len(tops)} measured concerns "
                       f"({_and_list([concern_word(c) for c in tops])}).")
    s.lines.append("“Aimed at” is what the product is for. It is not a reading of what it will do "
                   "to your skin.")
    s.detail = {"scanned": True, "top_concerns": tops, "aimed_at": list(product.aimed_at),
                "matched": matched, "scores": {k: measured[k] for k in tops if k in measured}}
    return s


def _ordinal(n: int) -> str:
    return {1: "1st", 2: "2nd", 3: "3rd"}.get(n, f"{n}th")


def _shelf_source(product: D.Product, shelf: list[str], catalog: dict[str, D.Product]) -> Source:
    s = Source("shelf", "From your shelf")
    same_role = [i for i in shelf if i in catalog and catalog[i].role == product.role]
    if product.id in shelf:
        s.lines.append("You already own this one.")
    elif same_role:
        names = ", ".join(catalog[i].name for i in same_role)
        s.lines.append(f"You already have a {product.role} on your shelf: {names}. "
                       f"Either this replaces it or your routine grows by a step.")
    else:
        s.lines.append(f"Nothing on your shelf fills the {product.role} step, so this would add one.")
    s.lines.append(f"New spend if you buy it: ₹{product.price_inr:,}.")
    s.detail = {"duplicates": same_role, "already_owned": product.id in shelf,
                "role": product.role, "new_spend_inr": product.price_inr,
                "steps_now": len(shelf), "steps_after": len(shelf) + (0 if same_role or product.id in shelf else 1)}
    return s


def check(product: D.Product, records: list[D.HistoryRecord], outcomes: list[ProductOutcome],
          catalog: dict[str, D.Product], measured: dict[str, float] | None = None,
          shelf: list[str] | None = None, zones: dict[str, str] | None = None,
          reports: dict[str, P.PatternReport] | None = None) -> CartCheck:
    """One product, the whole ladder, three labelled sources and one next step."""
    shelf = list(shelf or [])
    reports = reports or P.run_both(outcomes, catalog)
    d_check = D.check_product(product, records)
    # Both runs are read, but they stay apart: each match says which kind it came from.
    matches = _matched(product, reports["irritation"]) + _matched(product, reports["breakout"])

    incomplete = not product.inci_complete
    tags = [UNKNOWN_TAG] if incomplete else []

    if d_check.status == D.Status.BLOCKED:
        rung = Rung.BLOCKED
    elif any(m["tier"] == P.Tier.SUSPECT.value and m["match_type"] == "exact" for m in matches):
        rung = Rung.REPEATS_A_PATTERN
    elif matches:          # a lead, or any family match: both land here
        rung = Rung.PATCH_TEST_FIRST
    else:
        rung = Rung.NO_CONFLICTS

    # Missing is not safe: an unreadable label never reads as "no conflicts".
    unknown = incomplete and rung == Rung.NO_CONFLICTS
    # Nothing recorded at all is its own thing, and it isn't reassurance either.
    nothing_to_check = (rung == Rung.NO_CONFLICTS and not unknown
                        and d_check.status == D.Status.NOTHING_TO_CHECK and not outcomes)
    if unknown:
        verdict_line, next_step = UNKNOWN_LABEL, UNKNOWN_NEXT_STEP
    elif nothing_to_check:
        verdict_line, next_step = NOTHING_TO_CHECK_LABEL, NOTHING_TO_CHECK_NEXT_STEP
    else:
        verdict_line, next_step = RUNG_LABEL[rung.value], NEXT_STEP[rung.value]
        if incomplete:
            verdict_line = f"{RUNG_LABEL[rung.value]} · {UNKNOWN_LABEL}"

    sources = [
        _history_source(product, d_check, matches),
        _skin_source(product, measured, zones),
        _shelf_source(product, shelf, catalog),
    ]
    return CartCheck(
        product_id=product.id, rung=rung.value, verdict_line=verdict_line, tags=tags,
        sources=sources, next_step=next_step, unknown=unknown,
        nothing_to_check=nothing_to_check,
        inputs={
            "product": {"id": product.id, "name": product.name, "inci": list(product.inci),
                        "inci_complete": product.inci_complete, "aimed_at": list(product.aimed_at),
                        "price_inr": product.price_inr, "role": product.role},
            "records": [{"type": r.type.value, "product_id": r.product_id,
                         "ingredient": r.ingredient} for r in records],
            "outcomes": [{"product_id": o.product_id, "outcome": o.outcome,
                          "weeks_used": o.weeks_used()} for o in outcomes],
            "measured": dict(measured or {}), "shelf": shelf,
            "rule_versions": {"cartcheck": RULE_VERSION, "decision": D.RULE_VERSION,
                              "patterns": P.RULE_VERSION, "families": P.FAM.FAMILIES_VERSION},
        },
    )
