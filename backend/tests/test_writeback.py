"""Verdict write-back: a stored trial verdict becomes the product's history outcome.

The rule under the most pressure here is the one the brief singles out: a "can't tell" verdict
must NEVER be written as "suited". There is a test per can't-tell verdict, plus the 4-week guard.

New cases only.
"""
import pytest

from app import evidence as E
from app import outcomes as OC
from app import products as PRD
from app import writeback as WB

CAT = PRD.index()
STARTED = "2026-07-01"          # 17+ weeks before the dates used below
TODAY = __import__("datetime").date(2026, 10, 31)


def report(verdict, findings=(), symptoms=()):
    return {"verdict": verdict, "findings": list(findings), "symptoms": list(symptoms),
            "message": "", "rebuy": "", "comparability": None, "rule_version": E.RULE_VERSION}


def finding(concern="pore", direction="better", beyond=True):
    return {"concern": concern, "direction": direction, "beyond_noise": beyond,
            "baseline": None, "followup": None, "delta_mid": 1.0}


def plan(rep, started=STARTED, pid="sr-09", existing=None, **kw):
    return WB.plan(rep, pid, CAT[pid].leave_on, started, goal_concern=kw.pop("goal", "pore"),
                   trial_id="t1", existing=existing, today=TODAY, **kw)


ALL_CANT_TELL = [
    E.Verdict.NO_BASELINE.value,
    E.Verdict.NOT_COMPARABLE.value,
    E.Verdict.SEVERAL_CHANGES.value,
    E.Verdict.NO_CHANGE.value,
]


# ---------------------------------------------------------------- the rule that must not bend
@pytest.mark.parametrize("verdict", ALL_CANT_TELL)
def test_a_cant_tell_verdict_is_never_written_as_suited(verdict):
    wb = plan(report(verdict))
    assert wb.outcome.outcome == "not_sure"
    assert wb.outcome.outcome != "suited"


@pytest.mark.parametrize("verdict", ALL_CANT_TELL)
def test_a_cant_tell_verdict_never_counts_as_suited_even_after_many_weeks(verdict):
    wb = plan(report(verdict), started="2020-01-01")
    assert wb.outcome.counts_as_suited(TODAY) is False


@pytest.mark.parametrize("verdict", ALL_CANT_TELL)
def test_a_cant_tell_verdict_leaves_a_note_saying_which_kind(verdict):
    wb = plan(report(verdict))
    assert wb.note == WB.CANT_TELL_NOTE[verdict]
    assert wb.outcome.note == wb.note


@pytest.mark.parametrize("verdict", ALL_CANT_TELL)
def test_a_cant_tell_verdict_cannot_soften_a_reaction_she_already_recorded(verdict):
    prior = OC.ProductOutcome("sr-09", "irritation", True, note="itched last month", id="o1")
    wb = plan(report(verdict), existing=prior)
    assert wb.outcome.outcome == "irritation"
    assert wb.changed is False and wb.refused_upgrade is True
    assert "doesn't undo a reaction you reported" in wb.note


def test_a_cant_tell_verdict_with_good_looking_findings_is_still_not_sure():
    """Findings that moved are present, but the verdict says they can't be attributed."""
    wb = plan(report(E.Verdict.NOT_COMPARABLE.value, [finding()]))
    assert wb.outcome.outcome == "not_sure"


# ---------------------------------------------------------------- the only path to "suited"
def test_a_comparable_move_in_the_good_direction_after_four_weeks_writes_suited():
    wb = plan(report(E.Verdict.MOVED.value, [finding()]))
    assert wb.outcome.outcome == "suited"
    assert wb.outcome.counts_as_suited(TODAY) is True
    assert "under matching conditions" in wb.note


def test_a_good_move_under_four_weeks_stays_not_sure():
    wb = plan(report(E.Verdict.MOVED.value, [finding()]), started="2026-10-15")
    assert wb.outcome.outcome == "not_sure"
    assert wb.refused_upgrade is True
    assert "too early to say it suited you" in wb.note


def test_a_move_in_the_wrong_direction_is_not_suited():
    wb = plan(report(E.Verdict.MOVED.value, [finding(direction="worse")]))
    assert wb.outcome.outcome == "not_sure"
    assert "wrong direction" in wb.note


def test_a_mixed_move_on_the_goal_concern_follows_the_goal_concern():
    rep = report(E.Verdict.MOVED.value,
                 [finding("pore", "better"), finding("redness", "worse")])
    assert plan(rep, goal="pore").outcome.outcome == "suited"
    assert plan(rep, goal="redness").outcome.outcome == "not_sure"


def test_the_write_back_is_marked_as_coming_from_a_trial():
    wb = plan(report(E.Verdict.MOVED.value, [finding()]))
    assert wb.outcome.source == "writeback"
    assert wb.outcome.trial_id == "t1"
    assert wb.rule_version == "writeback-1.0"
    assert wb.from_verdict == E.Verdict.MOVED.value


# ---------------------------------------------------------------- a stop writes a reaction
def test_a_stop_on_an_itch_writes_irritation():
    wb = plan(report(E.Verdict.STOP_REACTION.value, symptoms=["itching"]))
    assert wb.outcome.outcome == "irritation"
    assert "you logged itching" in wb.note


def test_a_stop_on_spots_writes_a_breakout():
    wb = plan(report(E.Verdict.STOP_REACTION.value, symptoms=["new_breakouts"]))
    assert wb.outcome.outcome == "breakout"


def test_a_stop_breakout_carries_the_zones_it_was_given():
    wb = plan(report(E.Verdict.STOP_REACTION.value, symptoms=["new_breakouts"]),
              zones=["cheeks"], usual_spots=False)
    assert wb.outcome.zones == ["cheeks"] and wb.outcome.usual_spots is False


def test_a_stop_irritation_carries_no_zones():
    """Zones belong to the breakout run only; rule 1 keeps the two apart."""
    wb = plan(report(E.Verdict.STOP_REACTION.value, symptoms=["itching"]),
              zones=["cheeks"], usual_spots=False)
    assert wb.outcome.zones == [] and wb.outcome.usual_spots is None


def test_both_kinds_of_symptom_at_once_reads_as_irritation():
    """An itch alongside spots is the stop card's own kind, so it is not filed as a breakout."""
    wb = plan(report(E.Verdict.STOP_REACTION.value, symptoms=["itching", "new_breakouts"]))
    assert wb.outcome.outcome == "irritation"


@pytest.mark.parametrize("symptom", sorted(E.STOP_SYMPTOMS))
def test_every_stop_symptom_maps_to_one_of_the_two_reaction_types(symptom):
    wb = plan(report(E.Verdict.STOP_REACTION.value, symptoms=[symptom]))
    assert wb.outcome.outcome in ("irritation", "breakout")


def test_a_stop_overwrites_a_softer_earlier_outcome():
    prior = OC.ProductOutcome("sr-09", "not_sure", True, id="o1")
    wb = plan(report(E.Verdict.STOP_REACTION.value, symptoms=["burning"]), existing=prior)
    assert wb.outcome.outcome == "irritation" and wb.changed is True
    assert wb.outcome.id == "o1", "it must update the same row, not pile up a second one"


# ---------------------------------------------------------------- the mapping as a whole
def test_the_symptom_kind_helper():
    assert WB.symptom_kind(["itching"]) == "irritation"
    assert WB.symptom_kind(["new_breakouts"]) == "breakout"
    assert WB.symptom_kind([]) == "irritation"
    assert WB.symptom_kind(["something odd"]) == "irritation"


def test_every_verdict_in_the_engine_has_a_write_back_path():
    for v in E.Verdict:
        wb = plan(report(v.value, [finding()], ["itching"] if v == E.Verdict.STOP_REACTION else []))
        assert wb.outcome.outcome in {o.value for o in OC.Outcome}


def test_the_plan_writes_nothing_by_itself():
    """plan() only works out what would be written; storing is the endpoint's job."""
    wb = plan(report(E.Verdict.MOVED.value, [finding()]))
    assert isinstance(wb.outcome, OC.ProductOutcome)
    assert wb.to_dict()["outcome"]["product_id"] == "sr-09"
