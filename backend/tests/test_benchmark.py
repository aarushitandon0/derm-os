"""derm//os evidence benchmark: the behaviours the product promises.

Each test is one row of the benchmark table in the design doc. Run: pytest -q
"""
import pytest

from app import decision as D
from app import evidence as E
from app.fingerprint import Fingerprint
from app.inci import canonical, expand_avoid

CAT = D.load_catalog()


def fp(lum=0.55, rb=1.20, face=0.70, yaw=0.0, device="PhoneX", hour=10):
    return Fingerprint(1080, 1440, lum, rb, device, hour, face, yaw, 0.0, 0.0)


def cap(score, **kw):
    return E.Capture({"redness": score}, fp(**kw), "sd", ("redness",))


# ---------------------------------------------------------------- catalog sanity
def test_catalog_has_25_products_with_valid_roles():
    assert len(CAT) == 25
    assert all(p.role in D.ROLE_ORDER for p in CAT.values())
    assert all(not p.leave_on for p in CAT.values() if p.role == "cleanser")


# ---------------------------------------------------------------- INCI
@pytest.mark.parametrize("label", ["Parfum", "Parfum (Fragrance)", "FRAGRANCE", "Aroma", "Perfume"])
def test_fragrance_synonyms_normalise(label):
    assert canonical(label) == "fragrance"


def test_percentages_stripped():
    assert canonical("Niacinamide 10%") == "niacinamide"


def test_avoid_fragrance_includes_declared_components():
    assert {"linalool", "limonene", "essential oils"} <= expand_avoid("fragrance")


# ---------------------------------------------------------------- exclusions
def test_avoided_ingredient_blocks_with_exact_label_line():
    recs = [D.HistoryRecord(D.RecordType.AVOID, ingredient="fragrance")]
    c = D.check_product(CAT["mo-02"], recs)   # lists "Parfum"
    assert c.status == D.Status.BLOCKED
    assert any(m["label_line"] == "Parfum" for m in c.matches)


def test_synonym_still_blocks():
    recs = [D.HistoryRecord(D.RecordType.AVOID, ingredient="Parfum")]
    assert D.check_product(CAT["tn-02"], recs).status == D.Status.BLOCKED   # lists "Fragrance"


def test_essential_oil_blocked_under_fragrance_avoidance():
    recs = [D.HistoryRecord(D.RecordType.AVOID, ingredient="fragrance")]
    assert D.check_product(CAT["tr-02"], recs).status == D.Status.BLOCKED   # tea tree oil


def test_incomplete_inci_is_unknown_never_pass():
    recs = [D.HistoryRecord(D.RecordType.AVOID, ingredient="fragrance")]
    c = D.check_product(CAT["mo-04"], recs)
    assert c.status == D.Status.UNKNOWN
    assert "not a pass" in c.reasons[0]


def test_product_reaction_blocks_only_that_product():
    recs = [D.HistoryRecord(D.RecordType.SUSPECTED_REACTION, product_id="mo-02")]
    assert D.check_product(CAT["mo-02"], recs).status == D.Status.BLOCKED
    # Another product sharing ingredients (Parfum, Linalool) is NOT blocked: no ingredient allergy invented.
    assert D.check_product(CAT["tn-03"], recs).status == D.Status.PASS


def test_reaction_record_requires_product():
    with pytest.raises(ValueError):
        D.HistoryRecord(D.RecordType.SUSPECTED_REACTION, ingredient="fragrance")


def test_confirmed_allergy_blocks():
    recs = [D.HistoryRecord(D.RecordType.CONFIRMED_ALLERGY, ingredient="Salicylic Acid")]
    c = D.check_product(CAT["tr-02"], recs)   # lists "Salicylic Acid 2%"
    assert c.status == D.Status.BLOCKED
    assert c.matches[0]["record"] == "confirmed_allergy"
    assert D.check_product(CAT["mo-01"], recs).status == D.Status.PASS


# ---------------------------------------------------------------- routine comparison
CURRENT = ["cl-01", "sr-01", "mo-01", "sp-01"]


def test_change_nothing_is_always_first_column():
    out = D.compare(CURRENT, [D.Option("A", [D.OptionItem("mo-03", "replace")])], CAT, [])
    assert out["columns"][0]["name"] == "Change nothing"
    assert out["columns"][0]["new_spend_inr"] == 0


def test_add_vs_replace_changes_routine_spend_and_duplicates():
    add = D.build(CURRENT, D.Option("A", [D.OptionItem("mo-03", "add")]), CAT, [])
    rep = D.build(CURRENT, D.Option("A", [D.OptionItem("mo-03", "replace")]), CAT, [])
    assert "mo-01" in add.steps and "mo-01" not in rep.steps
    assert add.duplicate_roles == ["moisturiser"] and rep.duplicate_roles == []
    assert rep.replaced == [{"out": "mo-01", "in": "mo-03"}]
    assert add.new_spend_inr == rep.new_spend_inr == CAT["mo-03"].price_inr


def test_unanswered_mode_raises_the_question_that_matters():
    out = D.compare(CURRENT, [D.Option("B", [D.OptionItem("mo-03")])], CAT, [])
    q = out["next_question"]
    assert q and q["choices"] == ["replace", "add"]


def test_no_question_for_new_role():
    out = D.compare(CURRENT, [D.Option("B", [D.OptionItem("tn-01")])], CAT, [])
    assert out["next_question"] is None


def test_option_counts_new_leave_on_products():
    r = D.build(CURRENT, D.Option("Two at once", [D.OptionItem("sr-04", "add"), D.OptionItem("mo-03", "replace")]), CAT, [])
    assert r.new_leave_on == 2


# ---------------------------------------------------------------- evidence
def test_overlapping_ranges_mean_no_detectable_change():
    rep = E.evaluate([cap(60), cap(64)], [cap(62), cap(65)], E.TrialContext())
    assert rep.verdict == E.Verdict.NO_CHANGE


def test_non_overlapping_ranges_move_beyond_noise_without_causal_claim():
    rep = E.evaluate([cap(60), cap(62)], [cap(70), cap(71)], E.TrialContext())
    assert rep.verdict == E.Verdict.MOVED
    assert rep.findings[0].direction == "better"
    assert "does not prove" in rep.message


def test_different_light_is_not_comparable():
    rep = E.evaluate([cap(60), cap(62)], [cap(70, lum=0.30), cap(71, lum=0.31)], E.TrialContext())
    assert rep.verdict == E.Verdict.NOT_COMPARABLE
    assert rep.comparability.fixes


def test_warm_lamp_is_not_comparable():
    rep = E.evaluate([cap(60, rb=1.15), cap(61, rb=1.18)], [cap(66, rb=1.60), cap(67, rb=1.62)], E.TrialContext())
    assert rep.verdict == E.Verdict.NOT_COMPARABLE
    assert any("warmer" in r for r in rep.comparability.reasons)


def test_different_face_size_is_not_comparable():
    rep = E.evaluate([cap(60), cap(61)], [cap(60, face=0.50), cap(61, face=0.52)], E.TrialContext())
    assert rep.verdict == E.Verdict.NOT_COMPARABLE


def test_several_changes_block_attribution():
    rep = E.evaluate([cap(60), cap(62)], [cap(70), cap(71)], E.TrialContext(new_leave_on_products=2))
    assert rep.verdict == E.Verdict.SEVERAL_CHANGES


def test_symptoms_outrank_better_scores():
    rep = E.evaluate([cap(60), cap(62)], [cap(75), cap(76)], E.TrialContext(symptoms=["itching"]))
    assert rep.verdict == E.Verdict.STOP_REACTION


def test_single_scan_baseline_gives_no_trend_claim():
    rep = E.evaluate([cap(60)], [cap(75), cap(76)], E.TrialContext())
    assert rep.verdict == E.Verdict.NO_BASELINE


def test_missing_baseline_gives_no_trend_claim():
    rep = E.evaluate([], [cap(75), cap(76)], E.TrialContext())
    assert rep.verdict == E.Verdict.NO_BASELINE


def test_noise_summary_reports_range():
    s = E.noise_summary([cap(60), cap(63.5), cap(61)])
    assert s["redness"]["range"] == 3.5 and s["redness"]["n"] == 3
