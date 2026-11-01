"""Check any product (pastecheck-1.0): paste a real product's ingredient list, choose its job.

The pasted list runs through the same engines as the shop's own stock: the cart check ladder
(app/cartcheck.py) against product-level history, then the ingredient chips (app/chips.py), then
zone fit and finish from the basket's needs (app/needs.py). Nothing here is stored.

Brand names: the pasted text is never stored, and nothing from it is shown except the ingredient
lines themselves. Anything before an "Ingredients:" marker (where a product or brand name usually
sits) is dropped, and so is any item carrying a trademark sign or that is too long to be an
ingredient. The product is called by the user's optional nickname, or "Your pasted product".

Incomplete -> unknown. A list that looks cut off (an ellipsis, "etc.", "and more", "see pack", or
fewer than MIN_LINES lines) is treated as incomplete, so it can never read as "no conflicts".

The verdict ladder, first match wins. It is the cart check's ladder with one rung added for chips,
and the chips rung sits BELOW the product-level ones (product-level history ranks above chips):

    BLOCKED            cart check
    REPEATS_A_PATTERN  cart check
    TRIED_BEFORE       an ingredient chip says skip (itched; or broke out as a key active)
    PATCH_TEST_FIRST   cart check
    NO_CONFLICTS       cart check ("Nothing to check against yet" with an empty history)
"""
from __future__ import annotations

import re

from . import cartcheck as CC
from . import chips as CH
from . import decision as D
from . import needs as N
from . import patterns as P
from .inci import canonical, clean
from .outcomes import ProductOutcome

RULE_VERSION = "pastecheck-1.0"
MIN_LINES = 4
MAX_TEXT = 4000
JOBS = {"cleanser": ("cleanser", False), "moisturiser": ("moisturiser", True),
        "sunscreen": ("sunscreen", True), "serum": ("serum", True)}
FINISHES = ("dewy", "natural", "matte")
TRIED_RUNG = "tried_before"
TRIED_LABEL = "Lists something you said bothered you"
TRIED_NEXT = ("Leave this one. It lists an ingredient from your own history; the line above says which "
              "and why.")
DEFAULT_NAME = "Your pasted product"

_CUT = re.compile(r"(\.\.\.|…|\betc\b\.?|\band more\b|\bsee (?:pack|packaging|box|label)\b|\band others\b)", re.I)
_MARK = re.compile(r"ingredients?\s*(?:list)?\s*[:\-]", re.I)


def parse(text: str) -> tuple[list[str], bool, list[str]]:
    """Pasted text -> (ingredient lines, looks complete, notes about what was dropped)."""
    text = (text or "")[:MAX_TEXT]
    notes: list[str] = []
    m = _MARK.search(text)
    if m:
        text = text[m.end():]
        notes.append("Anything before “Ingredients:” was left out.")
    cut = bool(_CUT.search(text))
    text = _CUT.sub(",", text)
    parts = re.split(r"[,;\n•·]|\s\|\s", text)
    lines: list[str] = []
    dropped = 0
    for i, raw in enumerate(parts):
        s = raw.strip()
        if i == len(parts) - 1:
            s = s.rstrip(".").strip()        # the full stop that ends the list, not "Denat."
        if not s:
            continue
        if "™" in s or "®" in s or len(s) > 60 or not clean(s):
            dropped += 1
            continue
        lines.append(s)
    if dropped:
        notes.append(f"{dropped} item{'' if dropped == 1 else 's'} that didn't look like ingredients "
                     f"{'was' if dropped == 1 else 'were'} left out.")
    complete = not cut and len(lines) >= MIN_LINES
    return lines, complete, notes


def check(*, text: str, job: str, nickname: str | None, finish: str | None,
          records: list[D.HistoryRecord], outcomes: list[ProductOutcome], chips: list,
          catalog: dict[str, D.Product], zones: dict[str, N.ZoneRead] | None,
          measured: dict[str, float] | None, goal_finish: str | None) -> dict:
    if job not in JOBS:
        raise ValueError(f"job must be one of {sorted(JOBS)}")
    lines, complete, notes = parse(text)
    if not lines:
        raise ValueError("No ingredients found in the pasted text.")
    name = (nickname or "").strip()[:40] or DEFAULT_NAME
    role, leave_on = JOBS[job]
    product = D.Product(id="pasted", name=name, brand="", role=role, leave_on=leave_on, price_inr=0,
                        inci=lines, inci_complete=complete, aimed_at=[], source="pasted by you")
    chip_objs = CH.parse_all(chips)
    recs = list(records) + CH.records_from(chip_objs)
    reports = P.run_both(outcomes, catalog)
    cc = CC.check(product, recs, outcomes, catalog, measured, [], reports=reports)
    hist = next(s for s in cc.sources if s.key == "history")
    tried = CH.evaluate(lines, chip_objs)

    rung, label, next_step = cc.rung, cc.verdict_line, cc.next_step
    if tried["skip"] and cc.rung not in (CC.Rung.BLOCKED.value, CC.Rung.REPEATS_A_PATTERN.value):
        rung, label, next_step = TRIED_RUNG, TRIED_LABEL, TRIED_NEXT
        if not complete:
            label = f"{TRIED_LABEL} · {CC.UNKNOWN_LABEL}"
    unknown = cc.unknown and rung == cc.rung

    # Zone fit: which of the needs' target ingredients for the zones this job covers are listed.
    fit_lines: list[str] = []
    if zones:
        needs = N.build_needs(zones, measured, CH.itched_members(chip_objs))
        for z in (("whole",) if job in ("cleanser", "sunscreen") or N.same_type(zones) else N.ZONES):
            targets = set(N.targets_for(needs, z))
            hits = [raw for raw in lines if canonical(raw) in targets]
            where = "your face" if z == "whole" else f"your {N.zone_in_sentence(z)}"
            if hits:
                fit_lines.append(f"For {where}: lists {', '.join(hits[:3])}, which your needs are aimed at.")
            else:
                fit_lines.append(f"For {where}: lists none of the ingredients your needs are aimed at.")
    else:
        fit_lines.append("No face map yet: build your basket to see which zone this suits.")

    finish_line = None
    if finish in FINISHES and goal_finish in FINISHES:
        fin_ok = finish not in N.finish_spec(goal_finish)[1]["clash"]
        finish_line = (f"{finish.capitalize()} finish: " +
                       ("fits the finish you asked for." if fin_ok else
                        f"clashes with the {N.finish_spec(goal_finish)[1]['words']} finish you asked for."))

    sources = [
        {"key": "history", "label": "From your history", "lines": list(hist.lines)},
        {"key": "tried", "label": "From what you've tried",
         "lines": [s["line"] for s in tried["skip"]] + tried["worked"] + tried["notes"]
                  or ["None of your ingredient chips are on this list."]},
        {"key": "fit", "label": "Zone fit", "lines": fit_lines + ([finish_line] if finish_line else [])},
    ]
    return {"name": name, "job": job, "rung": rung, "verdict_line": label, "unknown": unknown,
            "complete": complete, "lines": lines, "parse_notes": notes, "sources": sources,
            "next_step": next_step, "change_nothing": cc.change_nothing,
            "stored": False, "rule_version": RULE_VERSION,
            "rule_versions": {"pastecheck": RULE_VERSION, "cartcheck": CC.RULE_VERSION,
                              "chips": CH.RULE_VERSION, "patterns": P.RULE_VERSION}}
