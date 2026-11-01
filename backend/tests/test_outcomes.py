"""Product outcomes: the 4-week rule, the breakout-only fields, and what each one reads as.

These are new cases. Nothing here changes an existing expectation.
"""
from datetime import date

import pytest

from app import outcomes as OC


def out(**kw):
    kw.setdefault("product_id", "mo-03")
    kw.setdefault("leave_on", True)
    return OC.ProductOutcome(**kw)


# ---------------------------------------------------------------- the >= 4 week rule
@pytest.mark.parametrize("weeks,expected", [
    (0, OC.TOO_EARLY), (1, OC.TOO_EARLY), (3, OC.TOO_EARLY),
    (4, "suited"), (12, "suited"),
])
def test_suited_only_counts_after_four_weeks(weeks, expected):
    assert out(outcome="suited", weeks_used_given=weeks).effective_outcome() == expected


def test_suited_with_no_length_recorded_never_counts():
    o = out(outcome="suited")
    assert o.weeks_used() is None
    assert o.counts_as_suited() is False
    assert o.effective_outcome() == OC.TOO_EARLY


def test_too_early_says_it_clears_nothing():
    assert "clears nothing" in out(outcome="suited", weeks_used_given=2).plain_line()


def test_weeks_come_from_the_dates_when_there_are_dates():
    o = out(outcome="suited", started_on="2026-08-01", stopped_on="2026-10-31")
    assert o.weeks_used() == 13
    assert o.counts_as_suited() is True


def test_weeks_use_today_when_still_in_use():
    o = out(outcome="suited", started_on="2026-10-01")
    assert o.weeks_used(today=date(2026, 10, 31)) == 4
    assert o.counts_as_suited(today=date(2026, 10, 31)) is True
    assert o.counts_as_suited(today=date(2026, 10, 20)) is False


# ---------------------------------------------------------------- the three other outcomes
def test_irritation_and_breakout_are_separate_failure_kinds():
    assert out(outcome="irritation").failure_kind() == "irritation"
    assert out(outcome="breakout").failure_kind() == "breakout"
    assert out(outcome="suited").failure_kind() is None
    assert out(outcome="not_sure").failure_kind() is None


def test_not_sure_stays_not_sure():
    o = out(outcome="not_sure", weeks_used_given=20)
    assert o.effective_outcome() == "not_sure"
    assert "couldn't say either way" in o.plain_line()


def test_unknown_outcome_is_refused():
    with pytest.raises(ValueError):
        out(outcome="works")


# ---------------------------------------------------------------- breakout-only fields
def test_breakout_keeps_zones_and_usual_spots():
    o = out(outcome="breakout", zones=["chin"], usual_spots=True, weeks_used_given=6)
    assert o.zones == ["chin"] and o.usual_spots is True
    assert "usual spots" in o.plain_line()


def test_new_area_is_said_as_a_new_area():
    o = out(outcome="breakout", zones=["cheeks"], usual_spots=False, weeks_used_given=1)
    assert "new area" in o.plain_line()


def test_zones_do_not_leak_onto_an_irritation_outcome():
    """Zones are a breakout question. Letting them ride along on an irritation record would mix
    the two reaction types, which rule 1 forbids."""
    o = out(outcome="irritation", zones=["chin"], usual_spots=True)
    assert o.zones == [] and o.usual_spots is None


def test_unknown_zone_is_refused():
    with pytest.raises(ValueError):
        out(outcome="breakout", zones=["elbow"])


def test_settled_while_using_is_reported():
    o = out(outcome="breakout", zones=["chin"], usual_spots=True, weeks_used_given=8,
            settled_while_using=True, settled_week=5)
    assert "settled by week 5 while you were still using it" in o.plain_line()


def test_stopped_before_started_is_refused():
    with pytest.raises(ValueError):
        out(outcome="suited", started_on="2026-10-01", stopped_on="2026-09-01")


# ---------------------------------------------------------------- round trip and split
def test_round_trip_through_a_dict():
    o = out(outcome="breakout", zones=["chin"], usual_spots=True, started_on="2026-01-01",
            settled_while_using=True, settled_week=5, note="hi")
    again = OC.ProductOutcome.from_dict(o.to_dict())
    assert again.to_dict() == o.to_dict()


def test_split_applies_the_four_week_rule():
    rows = [
        out(product_id="es-01", outcome="suited", weeks_used_given=12),
        out(product_id="mo-03", outcome="suited", weeks_used_given=2),     # too early
        out(product_id="sr-02", outcome="irritation", weeks_used_given=2),
        out(product_id="sr-05", outcome="breakout", weeks_used_given=8),
        out(product_id="sr-01", outcome="not_sure", weeks_used_given=30),
    ]
    g = OC.split(rows)
    assert [o.product_id for o in g["suited"]] == ["es-01"]
    assert [o.product_id for o in g["irritation"]] == ["sr-02"]
    assert [o.product_id for o in g["breakout"]] == ["sr-05"]


def test_every_outcome_value_has_a_label():
    for v in [o.value for o in OC.Outcome] + [OC.TOO_EARLY]:
        assert OC.OUTCOME_LABEL[v]
