"""Write-back: a stored trial verdict becomes the product's history outcome.

This is what closes the loop in docs/STRATEGY.md section 4: the verdict from Moment 3 is written
into the product's record, so the next cart check in Moment 1 is better informed than the last one.

The mapping is deliberately narrow, and the one rule that matters most is the one it refuses to
break:

    A "can't tell" verdict NEVER becomes "suited".

There are four of those (no baseline, not comparable, several changes, and a move that is only
"no detectable change") and each one leaves the outcome at "not sure" with a note saying which
kind of can't-tell it was. Only a comparable move in the good direction can write "suited", and
even then only once the product has been used for >= 4 weeks (app/outcomes.py). Under 4 weeks it
is written as "not sure", because a short "suited" would clear ingredients it has no right to.

    verdict                     direction  weeks      outcome written
    --------------------------  ---------  ---------  ------------------------------------
    stop_reaction               -          -          irritation or breakout, by the logged symptom
    moved_beyond_noise          better     >= 4       suited
    moved_beyond_noise          better     < 4        not_sure ("too early to call it suited")
    moved_beyond_noise          worse      -          not_sure (scores moved the wrong way)
    no_detectable_change        -          -          not_sure
    cant_tell_* (any)           -          -          not_sure
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone

from . import evidence as E
from .outcomes import SUITED_MIN_WEEKS, Outcome, ProductOutcome, weeks_between

RULE_VERSION = "writeback-1.0"

# Which reaction a stop symptom is. Itch / sting / burn style symptoms are irritation; spots are a
# breakout. Reaction types are kept apart (STRATEGY rule 1), so this mapping is explicit, never
# guessed, and anything unrecognised falls back to irritation, which is the stop-card's own kind.
BREAKOUT_SYMPTOMS = {"new_breakouts", "spots", "closed_comedones", "pustules", "papules"}
IRRITATION_SYMPTOMS = {"itching", "burning", "stinging", "swelling", "hives", "blistering",
                       "rash", "peeling_painful", "oozing", "dryness", "tightness"}

# The verdicts that can't say anything either way, with the note each one leaves behind.
CANT_TELL_NOTE = {
    E.Verdict.NO_BASELINE.value: "No detectable change recorded: there weren't enough matched scans "
                                 "to compare, so this trial couldn't say either way.",
    E.Verdict.NOT_COMPARABLE.value: "No detectable change recorded: the check-in photos didn't match "
                                    "the baseline conditions, so this trial couldn't say either way.",
    E.Verdict.SEVERAL_CHANGES.value: "No detectable change recorded: more than one new leave-on "
                                     "product was running, so no single one could be credited.",
    E.Verdict.NO_CHANGE.value: "No detectable change during this trial: the check-in scores sat "
                               "inside this skin's own scan-to-scan range.",
}


@dataclass
class WriteBack:
    outcome: ProductOutcome
    changed: bool
    note: str
    from_verdict: str
    refused_upgrade: bool = False
    rule_version: str = RULE_VERSION

    def to_dict(self) -> dict:
        return {"outcome": self.outcome.to_dict(), "changed": self.changed, "note": self.note,
                "from_verdict": self.from_verdict, "refused_upgrade": self.refused_upgrade,
                "rule_version": self.rule_version}


def symptom_kind(symptoms: list[str]) -> str:
    """Which reaction type a set of logged symptoms is. Breakout only when a spot symptom is the
    one logged; anything else the stop card fires on is irritation."""
    reported = {s.lower().strip() for s in (symptoms or [])}
    if reported & BREAKOUT_SYMPTOMS and not (reported & IRRITATION_SYMPTOMS):
        return Outcome.BREAKOUT.value
    return Outcome.IRRITATION.value


def plan(report: dict, product_id: str, leave_on: bool, started_at: str | date,
         goal_concern: str | None = None, trial_id: str | None = None,
         existing: ProductOutcome | None = None, today: date | None = None,
         zones: list[str] | None = None, usual_spots: bool | None = None) -> WriteBack:
    """Work out the outcome a stored evidence report writes, without storing anything.

    `report` is evidence.EvidenceReport.to_dict(), i.e. exactly what GET /evidence already returns,
    so the write-back reads the stored verdict rather than recomputing one of its own.
    """
    today = today or datetime.now(timezone.utc).date()
    verdict = report.get("verdict")
    findings = report.get("findings") or []
    symptoms = report.get("symptoms") or []
    start = started_at if isinstance(started_at, date) else date.fromisoformat(str(started_at)[:10])
    weeks = weeks_between(start, None, today)

    def build(outcome: str, note: str, refused: bool = False,
              zs: list[str] | None = None, usual: bool | None = None) -> WriteBack:
        o = ProductOutcome(
            product_id=product_id, outcome=outcome, leave_on=leave_on, started_on=start,
            zones=list(zs or []), usual_spots=usual,
            note=note, source="writeback", trial_id=trial_id,
            id=(existing.id if existing else None))
        changed = existing is None or existing.outcome != outcome
        return WriteBack(o, changed, note, str(verdict), refused)

    if verdict == E.Verdict.STOP_REACTION.value:
        kind = symptom_kind(symptoms)
        said = ", ".join(symptoms) or "a reaction"
        if kind == Outcome.BREAKOUT.value:
            return build(kind, f"Stopped during this trial: you logged {said}.",
                         zs=zones, usual=usual_spots)
        return build(kind, f"Stopped during this trial: you logged {said}.")

    if verdict == E.Verdict.MOVED.value:
        moved = [f for f in findings if f.get("beyond_noise")]
        goal_moved = [f for f in moved if goal_concern is None or f.get("concern") == goal_concern] or moved
        better = bool(goal_moved) and all(f.get("direction") == "better" for f in goal_moved)
        if not better:
            return build(Outcome.NOT_SURE.value,
                         "Scores moved beyond this skin's own range during this trial, but in the "
                         "wrong direction, so this isn't recorded as suiting you.")
        if weeks is None or weeks < SUITED_MIN_WEEKS:
            # The 4-week rule. A short run of good scores is still too early to call.
            return build(Outcome.NOT_SURE.value,
                         f"Moved beyond this skin's own range in the good direction, but only "
                         f"{weeks if weeks is not None else 'an unrecorded number of'} week(s) in. "
                         f"Under {SUITED_MIN_WEEKS} weeks it is too early to say it suited you.",
                         refused=True)
        return build(Outcome.SUITED.value,
                     f"Moved beyond this skin's own range in the good direction, on photos taken "
                     f"under matching conditions, over {weeks} weeks of use.")

    # Everything else is a can't-tell. It stays "not sure", with its own note, and it may never
    # overwrite a reaction the user already recorded with something softer.
    note = CANT_TELL_NOTE.get(str(verdict), "This trial couldn't say either way.")
    if existing is not None and existing.outcome in (Outcome.IRRITATION.value, Outcome.BREAKOUT.value):
        return WriteBack(existing, False,
                         f"Left as recorded: {existing.label()}. A trial that can't say either way "
                         f"doesn't undo a reaction you reported.",
                         str(verdict), refused_upgrade=True)
    return build(Outcome.NOT_SURE.value, note)
