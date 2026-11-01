"""Product outcomes: what actually happened when you used a product.

This is the memory the rest of derm//os reads. It sits beside the three history record types in
app/decision.py (suspected reaction / avoid / clinician-confirmed allergy) and does NOT change
them or their rules: a record blocks things, an outcome only describes what happened.

The rules here are the ones from docs/STRATEGY.md section 4 that are about a single product:

  * Reaction types are kept apart. IRRITATION (itch, sting, redness) and BREAKOUT (spots, closed
    comedones) are different outcomes and never share a suspect list (app/patterns.py).
  * "Suited" only counts after >= 4 weeks of use. Under that it reads "too early to say", and
    app/patterns.py must not let it clear any ingredient.
  * Nothing is inferred. Zones, usual spots and whether it settled while still in use are only
    ever what the user said (or what app/writeback.py copied from a stored trial verdict).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import Enum

RULE_VERSION = "outcomes-1.0"

# A "suited" outcome is only evidence of suiting after this many weeks of use.
SUITED_MIN_WEEKS = 4

FACE_ZONES = ("forehead", "nose", "cheeks", "chin", "jaw")


class Outcome(str, Enum):
    SUITED = "suited"            # used it, skin was fine
    IRRITATION = "irritation"    # itch, sting, burn, redness
    BREAKOUT = "breakout"        # spots, closed comedones
    NOT_SURE = "not_sure"        # used it, can't say either way


# What the outcome reads as once SUITED_MIN_WEEKS is applied. "too_early" is deliberately a
# separate value from NOT_SURE: the user did say it suited them, we just can't count it yet.
TOO_EARLY = "too_early"

OUTCOME_LABEL = {
    Outcome.SUITED.value: "Suited me",
    Outcome.IRRITATION.value: "Itched, stung or burned",
    Outcome.BREAKOUT.value: "Broke me out",
    Outcome.NOT_SURE.value: "Not sure",
    TOO_EARLY: "Too early to say",
}

# Which pattern run an outcome counts as a failure in (patterns.py runs the two separately).
FAILURE_KIND = {Outcome.IRRITATION.value: "irritation", Outcome.BREAKOUT.value: "breakout"}


def _as_date(v) -> date | None:
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v)[:10])


def weeks_between(start: date | None, stop: date | None, today: date | None = None) -> int | None:
    """Whole weeks of use. None when the start date isn't known: never guessed, because the
    4-week rule hangs off it."""
    if start is None:
        return None
    end = stop or today or datetime.now(timezone.utc).date()
    return max(0, (end - start).days // 7)


@dataclass
class ProductOutcome:
    product_id: str
    outcome: str                              # one of Outcome
    leave_on: bool                            # leave-on products weigh more for breakouts
    started_on: date | None = None
    stopped_on: date | None = None
    weeks_used_given: int | None = None       # when the user says "about 12 weeks" and gives no dates
    # Breakout detail only. None means "not asked / not said", never "no".
    zones: list[str] = field(default_factory=list)
    usual_spots: bool | None = None
    settled_while_using: bool | None = None
    settled_week: int | None = None
    note: str = ""
    source: str = "user"                      # "user" | "writeback"
    trial_id: str | None = None
    id: str | None = None
    rule_version: str = RULE_VERSION

    def __post_init__(self):
        if self.outcome not in {o.value for o in Outcome}:
            raise ValueError(f"Unknown outcome {self.outcome!r}")
        self.started_on = _as_date(self.started_on)
        self.stopped_on = _as_date(self.stopped_on)
        if self.started_on and self.stopped_on and self.stopped_on < self.started_on:
            raise ValueError("stopped_on is before started_on")
        bad = [z for z in self.zones if z not in FACE_ZONES]
        if bad:
            raise ValueError(f"Unknown face zones {bad}")
        if self.outcome != Outcome.BREAKOUT.value:
            # Zones and "usual spots" are a breakout question. Keeping them off the other
            # outcomes stops them leaking into the irritation run.
            self.zones = []
            self.usual_spots = None

    # -- derived -----------------------------------------------------------
    def weeks_used(self, today: date | None = None) -> int | None:
        w = weeks_between(self.started_on, self.stopped_on, today)
        return self.weeks_used_given if w is None else w

    def counts_as_suited(self, today: date | None = None) -> bool:
        """The >= 4 week rule. An unknown length never counts as suited."""
        if self.outcome != Outcome.SUITED.value:
            return False
        w = self.weeks_used(today)
        return w is not None and w >= SUITED_MIN_WEEKS

    def effective_outcome(self, today: date | None = None) -> str:
        """What this reads as on screen and to patterns.py."""
        if self.outcome == Outcome.SUITED.value and not self.counts_as_suited(today):
            return TOO_EARLY
        return self.outcome

    def failure_kind(self) -> str | None:
        return FAILURE_KIND.get(self.outcome)

    def label(self, today: date | None = None) -> str:
        return OUTCOME_LABEL[self.effective_outcome(today)]

    def weeks_phrase(self, today: date | None = None) -> str:
        w = self.weeks_used(today)
        return "length of use not recorded" if w is None else f"{w} week{'' if w == 1 else 's'} of use"

    def plain_line(self, today: date | None = None) -> str:
        """One sentence, inside the wording ceiling (no "caused", no "safe")."""
        span = self.weeks_phrase(today)
        eff = self.effective_outcome(today)
        if eff == TOO_EARLY:
            return (f"You said it suited you, but that is {span}. Under {SUITED_MIN_WEEKS} weeks it is "
                    "too early to say, so it clears nothing.")
        if eff == Outcome.BREAKOUT.value:
            where = f" on the {', '.join(self.zones)}" if self.zones else ""
            usual = "" if self.usual_spots is None else (
                " Those are your usual spots." if self.usual_spots else " That is a new area for you.")
            settled = ""
            if self.settled_while_using:
                at = f" by week {self.settled_week}" if self.settled_week else ""
                settled = f" It settled{at} while you were still using it."
            return f"Broke out{where} after {span}.{usual}{settled}"
        if eff == Outcome.IRRITATION.value:
            return f"Itched, stung or burned after {span}."
        if eff == Outcome.SUITED.value:
            return f"Suited you over {span}."
        return f"Used for {span}; you couldn't say either way."

    def to_dict(self, today: date | None = None) -> dict:
        return {
            "id": self.id, "product_id": self.product_id, "outcome": self.outcome,
            "leave_on": self.leave_on,
            "started_on": self.started_on.isoformat() if self.started_on else None,
            "stopped_on": self.stopped_on.isoformat() if self.stopped_on else None,
            "weeks_used_given": self.weeks_used_given,
            "zones": list(self.zones), "usual_spots": self.usual_spots,
            "settled_while_using": self.settled_while_using, "settled_week": self.settled_week,
            "note": self.note, "source": self.source, "trial_id": self.trial_id,
            "rule_version": self.rule_version,
            "weeks_used": self.weeks_used(today),
            "effective_outcome": self.effective_outcome(today),
            "label": self.label(today),
            "plain_line": self.plain_line(today),
            "counts_as_suited": self.counts_as_suited(today),
        }

    @staticmethod
    def from_dict(row: dict) -> "ProductOutcome":
        keep = set(ProductOutcome.__dataclass_fields__)
        return ProductOutcome(**{k: v for k, v in row.items() if k in keep})


def split(outcomes: list[ProductOutcome], today: date | None = None) -> dict[str, list[ProductOutcome]]:
    """The three groups patterns.py needs, with the 4-week rule already applied."""
    return {
        "suited": [o for o in outcomes if o.counts_as_suited(today)],
        "irritation": [o for o in outcomes if o.outcome == Outcome.IRRITATION.value],
        "breakout": [o for o in outcomes if o.outcome == Outcome.BREAKOUT.value],
    }
