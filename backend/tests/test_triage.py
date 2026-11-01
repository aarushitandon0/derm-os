"""Breakout triage: symptoms first, the 2-8 week window, purge only with turnover ingredients,
usual spots vs new areas, zone numbers, one next step.

New cases only.
"""
from datetime import date, timedelta

from app import products as PRD
from app import triage as T

CAT = PRD.index()
TODAY = date(2026, 10, 31)


def ago(weeks):
    return (TODAY - timedelta(weeks=weeks)).isoformat()


# Riya: a long-standing routine plus a sunscreen started 4 weeks ago.
USING = [
    {"product_id": "cl-01", "started_on": ago(30)},    # wash-off, long use
    {"product_id": "es-01", "started_on": ago(12)},    # snail mucin, long use
    {"product_id": "mo-03", "started_on": ago(20)},    # gel moisturiser, long use
    {"product_id": "sp-01", "started_on": ago(4)},     # the new sunscreen
]


def assess(**kw):
    kw.setdefault("symptoms", [])
    kw.setdefault("zones", ["cheeks"])
    kw.setdefault("usual_spots", False)
    kw.setdefault("using", USING)
    kw.setdefault("catalog", CAT)
    kw.setdefault("today", TODAY)
    return T.assess(**kw)


# ---------------------------------------------------------------- step 1: symptoms outrank all
def test_a_stop_symptom_wins_over_the_whole_ranking():
    r = assess(symptoms=["itching"])
    assert r.stop is True and r.stop_symptoms == ["itching"]
    assert r.next_action["kind"] == "stop_card"
    assert r.next_action["brief"] is True
    assert "Stop first" in r.headline


def test_the_stop_next_step_opens_the_brief_not_a_trial():
    r = assess(symptoms=["burning"])
    assert "visit brief" in r.next_step
    assert r.next_action["kind"] != "open_trial"


def test_a_mild_symptom_is_not_a_stop():
    r = assess(symptoms=["dryness"])
    assert r.stop is False and r.stop_symptoms == []
    assert r.next_action["kind"] == "open_trial"


def test_symptoms_are_matched_case_insensitively():
    assert assess(symptoms=["Itching"]).stop is True


def test_the_ranking_is_still_computed_under_a_stop():
    """The stop decides the next step; it doesn't blank the rest of the screen."""
    r = assess(symptoms=["itching"])
    assert r.candidates and r.lead().product_id == "sp-01"


# ---------------------------------------------------------------- step 2: the 2-8 week window
def test_the_product_started_inside_the_window_is_the_top_lead():
    r = assess()
    assert r.lead().product_id == "sp-01"
    assert r.lead().tier == T.TIER_IN_WINDOW_LEAVE_ON
    assert r.lead().in_window is True
    assert "2–8 week window" in r.lead().reason


def test_a_leave_on_in_the_window_ranks_above_a_wash_off_in_the_window():
    using = [{"product_id": "cl-02", "started_on": ago(4)},    # wash-off, in window
             {"product_id": "sp-01", "started_on": ago(4)}]    # leave-on, in window
    r = assess(using=using)
    assert [c.product_id for c in r.candidates] == ["sp-01", "cl-02"]
    assert r.candidates[1].tier == T.TIER_IN_WINDOW_WASH_OFF
    assert "washed off" in r.candidates[1].reason


def test_long_use_ranks_lowest_with_the_reason_shown():
    r = assess()
    snail = next(c for c in r.candidates if c.product_id == "es-01")
    assert snail.tier == T.TIER_LONG_USE
    assert "used this for 12 weeks without this problem" in snail.reason
    assert "not a clean bill" in snail.reason


def test_long_use_is_ranked_lower_but_never_excluded():
    r = assess()
    ids = [c.product_id for c in r.candidates]
    assert set(ids) == {"sp-01", "es-01", "mo-03", "cl-01"}, "nothing may be dropped"
    assert ids[0] == "sp-01"
    assert ids.index("es-01") > 0 and ids.index("mo-03") > 0 and ids.index("cl-01") > 0


def test_something_started_too_recently_ranks_below_the_window():
    using = [{"product_id": "sp-01", "started_on": ago(4)},
             {"product_id": "sr-06", "started_on": ago(1)}]
    r = assess(using=using)
    recent = next(c for c in r.candidates if c.product_id == "sr-06")
    assert recent.tier == T.TIER_TOO_RECENT_LEAVE_ON
    assert recent.in_window is False
    assert "earlier than the usual 2–8 week lag" in recent.reason


def test_a_missing_start_date_is_said_rather_than_guessed():
    r = assess(using=[{"product_id": "sp-01", "started_on": None}])
    c = r.candidates[0]
    assert c.tier == T.TIER_UNKNOWN_START and c.weeks_used is None
    assert "No start date recorded" in c.reason


def test_the_window_boundaries_are_inclusive():
    assert T._tier(True, 2) == T.TIER_IN_WINDOW_LEAVE_ON
    assert T._tier(True, 7) == T.TIER_IN_WINDOW_LEAVE_ON
    assert T._tier(True, 1) == T.TIER_TOO_RECENT_LEAVE_ON
    # 8 weeks is where long use takes over, per "if it isn't better after ~6-8 weeks".
    assert T._tier(True, 8) == T.TIER_LONG_USE


# ---------------------------------------------------------------- step 3: purge
def test_no_purge_without_a_turnover_ingredient():
    r = assess()
    assert r.purge.possible is False and r.purge.consistent is False
    assert "Not a purge" in r.purge.line
    assert "no ingredient that speeds up cell turnover" in r.purge.line
    assert r.purge.conditions["purge_capable_ingredient"] is False


def test_a_new_area_points_away_from_purging_even_with_a_turnover_ingredient():
    using = [{"product_id": "tr-01", "started_on": ago(5)}]      # lists Retinal
    r = assess(using=using, zones=["cheeks"], usual_spots=False)
    assert r.purge.possible is True and r.purge.consistent is False
    assert "new area" in r.purge.line and "points to a breakout" in r.purge.line


def test_purge_consistent_needs_all_three_conditions():
    using = [{"product_id": "tr-01", "started_on": ago(5)}]
    r = assess(using=using, zones=["chin"], usual_spots=True,
               settled_while_using=True, settled_week=5)
    assert r.purge.consistent is True
    assert "Consistent with purging" in r.purge.line
    assert r.purge.ingredient == "retinal"


def test_purge_is_not_consistent_when_it_settled_too_late():
    using = [{"product_id": "tr-01", "started_on": ago(10)}]
    r = assess(using=using, zones=["chin"], usual_spots=True,
               settled_while_using=True, settled_week=9)
    assert r.purge.possible is True and r.purge.consistent is False
    assert "settles within about 6 weeks" in r.purge.line


def test_purge_is_not_consistent_when_it_has_not_settled():
    using = [{"product_id": "tr-01", "started_on": ago(5)}]
    r = assess(using=using, zones=["chin"], usual_spots=True, settled_while_using=False)
    assert r.purge.consistent is False and "hasn't settled yet" in r.purge.line


def test_unanswered_usual_spots_asks_rather_than_assumes():
    using = [{"product_id": "tr-01", "started_on": ago(5)}]
    r = assess(using=using, zones=[], usual_spots=None)
    assert r.purge.consistent is False
    assert "are these your usual spots?" in r.purge.line


def test_a_purge_consistent_read_does_not_tell_her_to_pause_it():
    """Pausing something that is settling throws away the only reading available."""
    using = [{"product_id": "tr-01", "started_on": ago(5)}]
    r = assess(using=using, zones=["chin"], usual_spots=True,
               settled_while_using=True, settled_week=5)
    assert "Keep using" in r.next_step
    assert r.next_action["pause_product_id"] is None
    assert r.next_action["keep_product_id"] == "tr-01"


def test_azelaic_acid_is_purge_capable_as_mild():
    using = [{"product_id": "sr-05", "started_on": ago(5)}]
    r = assess(using=using, zones=["chin"], usual_spots=True,
               settled_while_using=True, settled_week=5)
    assert r.purge.strength == "mild" and r.purge.ingredient == "azelaic acid"


# ---------------------------------------------------------------- step 4: where
def test_tapped_zones_are_used_when_there_are_no_mask_numbers():
    r = assess()
    assert r.zones.source == "tapped"
    assert "You tapped: cheeks." in r.zones.line
    assert "new area for you" in r.zones.line
    assert "No per-zone mask numbers were available" in r.zones.to_dict()["source_note"]


def test_usual_spots_are_said_to_be_where_purging_shows_up():
    r = assess(zones=["chin"], usual_spots=True)
    assert "usual spots, which is where purging shows up" in r.zones.line


def test_mask_numbers_are_used_when_they_exist():
    r = assess(shares={"cheeks": 0.62, "forehead": 0.2, "chin": 0.18},
               baseline_shares={"cheeks": 0.11, "forehead": 0.46, "chin": 0.43})
    assert r.zones.source == "masks"
    assert "Most of the marked area is on your cheeks (62% of it)" in r.zones.line
    assert "baseline that zone held 11%" in r.zones.line


def test_mask_numbers_say_when_a_zone_has_not_gone_up():
    r = assess(shares={"cheeks": 0.2, "forehead": 0.5},
               baseline_shares={"cheeks": 0.3, "forehead": 0.6})
    assert "hasn't gone up" in r.zones.line


def test_unknown_zones_are_dropped_rather_than_shown():
    assert assess(zones=["cheeks", "elbow"]).zones.zones == ["cheeks"]


def test_no_zones_at_all_is_said_plainly():
    r = assess(zones=[], usual_spots=None)
    assert r.zones.source == "none"
    assert "No zones recorded" in r.zones.line


# ---------------------------------------------------------------- step 5: one next step
def test_exactly_one_next_step_naming_one_product_to_pause():
    r = assess()
    assert r.next_step.startswith("Pause Invisible Fluid SPF 50 only.")
    assert "\n" not in r.next_step
    assert r.next_action["kind"] == "open_trial"
    assert r.next_action["pause_product_id"] == "sp-01"
    assert r.next_action["checkpoint_days"] == 14


def test_everything_else_is_held_fixed():
    r = assess()
    assert set(r.next_action["hold_fixed"]) == {"cl-01", "es-01", "mo-03"}
    assert "sp-01" not in r.next_action["hold_fixed"]


def test_the_paused_product_is_a_leave_on_one():
    """Pausing a cleanser teaches nothing about a breakout with a 2-8 week lag."""
    using = [{"product_id": "cl-02", "started_on": ago(4)},
             {"product_id": "sr-06", "started_on": ago(3)}]
    r = assess(using=using)
    assert r.lead().product_id == "sr-06"
    assert CAT[r.next_action["pause_product_id"]].leave_on is True


def test_nothing_in_use_asks_for_products_rather_than_guessing():
    r = assess(using=[])
    assert r.candidates == []
    assert r.next_action["kind"] == "add_products"
    assert "Add the products you are using" in r.next_step


# ---------------------------------------------------------------- stored inputs and versions
def test_the_result_stores_its_inputs_and_rule_versions():
    r = assess()
    assert r.rule_version == "triage-1.0"
    assert r.families_version == "families-1.0"
    i = r.inputs
    assert i["zones"] == ["cheeks"] and i["usual_spots"] is False
    assert i["window_weeks"] == [2, 8] and i["long_use_weeks"] == 8
    assert i["rule_versions"]["triage"] == "triage-1.0"
    assert len(i["using"]) == 4


def test_the_whole_result_serialises():
    d = assess().to_dict()
    assert set(d) >= {"stop", "headline", "candidates", "purge", "zones", "next_step",
                      "next_action", "inputs", "rule_version"}
    assert len(d["candidates"]) == 4
