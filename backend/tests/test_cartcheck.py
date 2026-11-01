"""Cart check: the verdict ladder, the three labelled sources, change nothing, one next step.

New cases only.
"""
import pytest

from app import cartcheck as CC
from app import decision as D
from app import outcomes as OC
from app import patterns as P
from app import products as PRD

CAT = PRD.index()


def out(pid, outcome, weeks=None, **kw):
    return OC.ProductOutcome(product_id=pid, outcome=outcome, leave_on=CAT[pid].leave_on,
                             weeks_used_given=weeks, **kw)


RECORDS = [D.HistoryRecord(D.RecordType.SUSPECTED_REACTION, product_id="mo-02"),
           D.HistoryRecord(D.RecordType.AVOID, ingredient="fragrance")]
OUTS = [
    out("sr-02", "irritation", 2),
    out("tn-03", "irritation", 3),
    out("sr-05", "breakout", 8, zones=["chin"], usual_spots=True,
        settled_while_using=True, settled_week=5),
    out("es-01", "suited", 12),
    out("mo-03", "suited", 6),
]
# Riya's baseline fixture means. Lowest score = biggest concern.
MEASURED = {"redness": 62.1, "texture": 58.6, "acne": 72.2, "pore": 55.2,
            "oiliness": 48.1, "moisture": 63.2}
SHELF = ["cl-01", "sr-01", "mo-03", "sp-01"]
REPORTS = P.run_both(OUTS, CAT)


def check(pid, records=None, outs=None, measured=MEASURED, shelf=SHELF, reports=REPORTS):
    return CC.check(CAT[pid], RECORDS if records is None else records,
                    OUTS if outs is None else outs, CAT, measured, shelf, reports=reports)


def source(res, key):
    return next(s for s in res.sources if s.key == key)


# ---------------------------------------------------------------- the ladder, in order
def test_the_ladder_has_four_rungs_in_the_designed_order():
    assert [r.value for r in CC.LADDER] == ["blocked", "repeats_a_pattern",
                                            "patch_test_first", "no_conflicts"]


def test_blocked_wins_over_everything_below_it():
    """mo-02 lists Parfum and she avoids fragrance, and it is also the product she reacted to."""
    res = check("mo-02")
    assert res.rung == "blocked"
    assert res.verdict_line == "Blocked"


def test_repeats_a_pattern_when_the_label_lists_a_suspect():
    res = check("sr-08")                       # lists Alcohol Denat., her irritation suspect
    assert res.rung == "repeats_a_pattern"
    assert res.verdict_line == "Repeats a pattern"


def test_repeats_a_pattern_shows_the_suspect_with_its_counts():
    line = source(check("sr-08"), "history").lines[0]
    assert "Suspect" in line and "Alcohol Denat." in line
    assert "in 2 of 2 products that made you itch, sting or burn, 0 of 2 that suited you" in line


def test_patch_test_first_for_a_lead():
    """Tocopherol is on one label that itched and none that suited her, so it is a lead."""
    res = check("tr-01")                       # Night Retinal lists Tocopherol
    assert res.rung == "patch_test_first"
    assert "Lead" in source(res, "history").lines[0]


def test_patch_test_first_for_a_family_match_with_no_exact_match():
    """She has not reacted to citral itself, but it is in the fragrance family she has."""
    p = D.Product(id="x-01", name="Test Serum", brand="Nimbus Skin", role="serum", leave_on=True,
                  price_inr=500, inci=["Aqua", "Citral"], inci_complete=True)
    cat = {**CAT, "x-01": p}
    res = CC.check(p, RECORDS, OUTS, cat, MEASURED, SHELF, reports=REPORTS)
    assert res.rung == "patch_test_first"
    hit = source(res, "history").detail["matches"][0]
    assert hit["match_type"] == "family"
    assert "family match, which ranks below an exact one" in source(res, "history").lines[0]


def test_no_conflicts_when_nothing_of_hers_matches():
    res = check("sr-09")
    assert res.rung == "no_conflicts"
    assert res.verdict_line == "No conflicts with your history"


def test_no_conflicts_is_never_worded_as_safe():
    res = check("sr-09")
    text = " ".join(res.verdict_line.split() + [res.next_step] +
                    [ln for s in res.sources for ln in s.lines]).lower()
    assert "safe" not in text
    assert "isn't a pass" in source(res, "history").lines[0]


def test_a_suspect_outranks_a_lead_on_the_same_label():
    """sr-08 lists both a suspect and several leads; the rung must come from the suspect."""
    res = check("sr-08")
    matches = source(res, "history").detail["matches"]
    assert matches[0]["tier"] == "suspect"
    assert res.rung == "repeats_a_pattern"


# ---------------------------------------------------------------- incomplete INCI -> unknown
def test_an_incomplete_label_can_never_read_as_no_conflicts():
    res = check("mo-07")
    assert res.unknown is True
    assert res.verdict_line == "Ingredient list incomplete → unknown"
    assert CC.UNKNOWN_TAG in res.tags


def test_an_incomplete_label_asks_for_the_full_list_as_its_next_step():
    assert "full ingredient list" in check("mo-07").next_step


def test_a_stronger_rung_still_stands_on_an_incomplete_label_and_carries_the_tag():
    """cl-04's list is incomplete but does name niacinamide, so blocked still wins."""
    recs = [D.HistoryRecord(D.RecordType.AVOID, ingredient="niacinamide")]
    res = check("cl-04", records=recs)
    assert res.rung == "blocked"
    assert CC.UNKNOWN_TAG in res.tags
    assert res.verdict_line.startswith("Blocked ·")
    assert res.unknown is False


def test_a_complete_label_is_never_tagged_incomplete():
    res = check("sr-09")
    assert res.tags == [] and res.unknown is False


# ---------------------------------------------------------------- three labelled sources
def test_exactly_three_sources_with_their_labels():
    res = check("sr-09")
    assert [s.key for s in res.sources] == ["history", "skin", "shelf"]
    assert [s.label for s in res.sources] == ["From your history", "From your skin (YouCam)",
                                              "From your shelf"]


def test_every_source_always_says_something():
    for pid in ("mo-02", "sr-08", "mo-07", "sr-09", "sp-04"):
        for s in check(pid).sources:
            assert s.lines, f"{pid}: {s.key} said nothing"


# ---------------------------------------------------------------- from your skin
def test_aimed_at_names_a_measured_top_concern():
    line = source(check("sr-09"), "skin").lines[0]
    assert line == ("Aimed at pores. Pores is your 2nd lowest YouCam score of the 3 we measured.")


def test_aimed_at_names_the_lowest_score_as_the_lowest():
    line = source(check("sp-04"), "skin").lines[0]
    assert line == ("Aimed at oiliness and pores. Oiliness is your lowest YouCam score "
                    "of the 3 we measured.")


def test_not_aimed_at_any_top_concern_is_said_plainly():
    line = source(check("sr-08"), "skin").lines[0]
    assert line.startswith("Not aimed at any of your top 3 measured concerns")


def test_the_wording_is_aimed_at_and_never_fixes():
    for pid in ("sr-09", "sp-04", "sr-08", "mo-07"):
        text = " ".join(source(check(pid), "skin").lines).lower()
        for banned in ("fixes", "will fix", "treats", "cures", "works"):
            assert banned not in text


def test_with_no_scan_the_skin_source_says_scan_first():
    res = check("sr-09", measured=None)
    assert source(res, "skin").lines == [CC.NO_SCAN_LINE]
    assert source(res, "skin").detail["scanned"] is False
    assert "No scan yet" in CC.NO_SCAN_LINE


def test_no_scan_does_not_change_the_rung():
    assert check("sr-09", measured=None).rung == check("sr-09").rung


def test_top_concerns_are_the_lowest_raw_scores():
    assert CC.top_concerns(MEASURED) == ["oiliness", "pore", "texture"]
    assert CC.top_concerns(MEASURED, 1) == ["oiliness"]
    assert CC.top_concerns({}) == []
    assert CC.top_concerns(None) == []


# ---------------------------------------------------------------- from your shelf
def test_the_shelf_source_names_what_it_duplicates_and_the_spend():
    lines = source(check("sr-09"), "shelf").lines
    assert "10% Niacinamide Serum" in lines[0]
    assert "New spend if you buy it: ₹1,290." == lines[1]


def test_the_shelf_source_notices_a_product_you_already_own():
    assert "You already own this one." in source(check("mo-03"), "shelf").lines[0]


def test_the_shelf_source_says_when_it_adds_a_step():
    res = check("sr-09", shelf=["cl-01"])
    assert "would add one" in source(res, "shelf").lines[0]
    assert source(res, "shelf").detail["steps_after"] == 2


# ---------------------------------------------------------------- change nothing, one next step
def test_change_nothing_is_always_shown():
    for pid in ("mo-02", "sr-08", "mo-07", "sr-09", "sp-04", "tr-01"):
        res = check(pid)
        assert res.change_nothing and res.change_nothing.startswith("Change nothing.")


def test_exactly_one_next_step_per_result():
    for pid in ("mo-02", "sr-08", "mo-07", "sr-09", "sp-04", "tr-01"):
        res = check(pid)
        assert isinstance(res.next_step, str) and res.next_step
        # One step means one instruction, not a menu: no bullet list, no "or".
        assert "\n" not in res.next_step
        assert res.to_dict()["next_step"] == res.next_step


def test_each_rung_has_its_own_next_step():
    steps = {check(pid).next_step for pid in ("mo-02", "sr-08", "sr-09")}
    assert len(steps) == 3


# ---------------------------------------------------------------- stored inputs and versions
def test_every_result_stores_its_inputs_and_rule_versions():
    res = check("sr-09")
    assert res.rule_version == "cartcheck-1.0"
    i = res.inputs
    assert i["product"]["id"] == "sr-09"
    assert i["measured"] == MEASURED and i["shelf"] == SHELF
    assert [r["type"] for r in i["records"]] == ["suspected_reaction", "avoid"]
    assert i["rule_versions"] == {"cartcheck": "cartcheck-1.0", "decision": "decision-1.0",
                                  "patterns": "patterns-1.0", "families": "families-1.0"}


def test_the_result_serialises_with_its_rung_label():
    d = check("sr-08").to_dict()
    assert d["rung"] == "repeats_a_pattern" and d["rung_label"] == "Repeats a pattern"
    assert len(d["sources"]) == 3


# ---------------------------------------------------------------- reaction types stay apart
def test_an_irritation_suspect_is_labelled_as_one_and_not_as_a_breakout():
    matches = source(check("sr-08"), "history").detail["matches"]
    kinds = {m["kind"] for m in matches if m["tier"] == "suspect"}
    assert kinds == {"irritation"}


def test_one_breakout_product_produces_no_breakout_matches_at_all():
    """With a single breakout product, patterns names no suspects, so nothing leaks in here."""
    matches = source(check("sr-09"), "history").detail["matches"]
    assert [m for m in matches if m["kind"] == "breakout"] == []


def test_general_knowledge_is_kept_under_its_own_key():
    res = check("sr-08")
    notes = source(res, "history").detail["general_knowledge"]
    assert notes and any("often reported" in n for n in notes)
    # ...and never folded into the counts line.
    assert all("often reported" not in ln for ln in source(res, "history").lines)


# ---------------------------------------------------------------- nothing recorded at all
def test_with_no_records_and_no_outcomes_it_says_nothing_to_check():
    """A beginner's history is empty by definition, so "no conflicts with your history" would be
    reassurance it hasn't earned. app/decision.py already keeps these apart; so does the ladder."""
    res = CC.check(CAT["sr-09"], [], [], CAT, MEASURED, [])
    assert res.rung == "no_conflicts"
    assert res.nothing_to_check is True
    assert res.verdict_line == "Nothing to check against yet"
    assert "safe" not in res.verdict_line.lower()


def test_the_nothing_to_check_next_step_asks_for_the_first_result():
    res = CC.check(CAT["sr-09"], [], [], CAT, MEASURED, [])
    assert "tell us what happens" in res.next_step


def test_one_recorded_outcome_is_enough_to_stop_saying_nothing_to_check():
    res = CC.check(CAT["sr-09"], [], [out("es-01", "suited", 12)], CAT, MEASURED, [])
    assert res.nothing_to_check is False
    assert res.verdict_line == "No conflicts with your history"


def test_riyas_pass_is_not_nothing_to_check():
    """She has an avoid record and five outcomes, so her label check really was run."""
    assert check("sr-09").nothing_to_check is False


def test_nothing_to_check_never_applies_to_a_stronger_rung():
    for pid in ("mo-02", "sr-08"):
        assert check(pid).nothing_to_check is False


def test_an_incomplete_label_with_nothing_recorded_still_reads_unknown():
    """Unknown outranks "nothing to check": the label can't be read either way."""
    res = CC.check(CAT["mo-07"], [], [], CAT, MEASURED, [])
    assert res.unknown is True and res.nothing_to_check is False
    assert res.verdict_line == "Ingredient list incomplete → unknown"
