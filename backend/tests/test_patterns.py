"""Patterns engine: rules 1-7 of docs/STRATEGY.md section 4, one test per rule and per edge.

New cases only. No existing expectation is touched.
"""
import pytest

from app import families as FAM
from app import outcomes as OC
from app import patterns as P
from app import products as PRD

CAT = PRD.index()


def out(pid, outcome, weeks=None, **kw):
    return OC.ProductOutcome(product_id=pid, outcome=outcome, leave_on=CAT[pid].leave_on,
                             weeks_used_given=weeks, **kw)


# Riya's history: two things that itched sharing one drying alcohol, one that broke her out,
# and two that suited her for long enough to count.
RIYA = [
    out("sr-02", "irritation", 2),
    out("tn-03", "irritation", 3),
    out("sr-05", "breakout", 8, zones=["chin"], usual_spots=True,
        settled_while_using=True, settled_week=5),
    out("es-01", "suited", 12),
    out("mo-03", "suited", 6),
]


def tiers(report):
    return {s.ingredient: s.tier for s in report.suspects}


# ---------------------------------------------------------------- rule 1: types kept apart
def test_irritation_and_breakout_never_share_a_suspect_list():
    both = P.run_both(RIYA, CAT)
    irr = {s.ingredient for s in both["irritation"].suspects}
    brk = {s.ingredient for s in both["breakout"].suspects}
    assert "alcohol denat" in irr
    assert "alcohol denat" not in brk
    assert both["irritation"].kind == "irritation" and both["breakout"].kind == "breakout"


def test_a_breakout_product_is_not_in_the_irritation_failure_set():
    r = P.analyse("irritation", RIYA, CAT)
    assert [p["product_id"] for p in r.failed_products] == ["sr-02", "tn-03"]


def test_unknown_kind_is_refused():
    with pytest.raises(ValueError):
        P.analyse("allergy", RIYA, CAT)


# ---------------------------------------------------------------- rule 3: contrast
def test_two_failed_none_suited_is_a_suspect():
    r = P.analyse("irritation", RIYA, CAT)
    assert tiers(r)["alcohol denat"] == P.Tier.SUSPECT.value


def test_the_top_suspect_is_the_exact_drying_alcohol():
    r = P.analyse("irritation", RIYA, CAT)
    top = r.top()
    assert top.ingredient == "alcohol denat"
    assert top.match_type == "exact"
    assert top.tier == P.Tier.SUSPECT.value


def test_counts_line_reads_as_designed():
    r = P.analyse("irritation", RIYA, CAT)
    assert r.top().counts_line() == ("in 2 of 2 products that made you itch, sting or burn, "
                                     "0 of 2 that suited you")


def test_one_failed_product_in_one_of_two_is_a_lead_not_a_suspect():
    rows = [out("sr-02", "irritation", 2), out("tn-03", "irritation", 3), out("es-01", "suited", 12)]
    r = P.analyse("irritation", rows, CAT)
    # Ferulic acid is only on the vitamin C label, so it is a lead.
    assert tiers(r)["ferulic acid"] == P.Tier.LEAD.value


def test_an_ingredient_in_a_suited_product_is_never_a_suspect():
    """Rule 3's hard edge: contrast decides, so anything you have used without the problem is out."""
    # Phenoxyethanol is on both labels that itched AND on ones that suited her, so contrast
    # takes it out of the running however often it appears in the failures.
    r = P.analyse("irritation", RIYA, CAT)
    assert tiers(r)["phenoxyethanol"] == P.Tier.CLEARED.value
    assert all(s.tier != P.Tier.SUSPECT.value for s in r.suspects if s.ingredient == "phenoxyethanol")


def test_cleared_entries_say_where_you_used_it_without_trouble():
    r = P.analyse("irritation", RIYA, CAT)
    cleared = next(s for s in r.suspects if s.ingredient == "phenoxyethanol")
    assert cleared.in_suited and cleared.tier == P.Tier.CLEARED.value


# ---------------------------------------------------------------- rule 2 feeding rule 3
def test_suited_under_four_weeks_clears_nothing():
    """The suited product is 2 weeks old, so it must not clear the shared ingredient."""
    short = [out("sr-02", "irritation", 2), out("tn-03", "irritation", 3),
             out("mo-02", "suited", 2)]   # Velvet Rose lists Parfum and Linalool
    r = P.analyse("irritation", short, CAT)
    assert r.suspects, "a 2-week suited product must not wipe out every suspect"
    assert tiers(r)["alcohol denat"] == P.Tier.SUSPECT.value
    assert tiers(r)["linalool"] == P.Tier.LEAD.value   # not cleared by the too-early product
    assert r.suspects[0].suited_total == 0


def test_the_same_product_at_four_weeks_does_clear_it():
    long = [out("sr-02", "irritation", 2), out("tn-03", "irritation", 3),
            out("mo-02", "suited", 4)]
    r = P.analyse("irritation", long, CAT)
    assert tiers(r)["linalool"] == P.Tier.CLEARED.value


# ---------------------------------------------------------------- rule 3: one failed product
def test_one_failed_product_cannot_narrow_down():
    rows = [out("sr-05", "breakout", 8), out("es-01", "suited", 12)]
    r = P.analyse("breakout", rows, CAT)
    assert r.cannot_narrow is not None
    assert "One product can't tell us which of its 6 ingredients did it" in r.cannot_narrow


def test_one_failed_product_names_no_suspects_and_no_leads():
    rows = [out("sr-05", "breakout", 8), out("es-01", "suited", 12)]
    r = P.analyse("breakout", rows, CAT)
    assert not [s for s in r.suspects if s.tier in (P.Tier.SUSPECT.value, P.Tier.LEAD.value)]


def test_one_failed_product_lists_what_is_not_in_any_suited_product():
    rows = [out("sr-05", "breakout", 8), out("es-01", "suited", 12), out("mo-03", "suited", 6)]
    r = P.analyse("breakout", rows, CAT)
    names = [x["display"] for x in r.only_in_failed]
    assert "Azelaic Acid" in names
    # Aqua, Glycerin and Phenoxyethanol are all on products that suited her, so they are out.
    assert "Aqua" not in names and "Glycerin" not in names and "Phenoxyethanol" not in names


def test_the_headline_says_it_cannot_narrow_down():
    rows = [out("sr-05", "breakout", 8), out("es-01", "suited", 12)]
    assert "Can't narrow it down yet" in P.analyse("breakout", rows, CAT).headline


# ---------------------------------------------------------------- rule 5: families, exact first
def test_a_family_match_is_reported_as_a_family_match():
    r = P.analyse("irritation", RIYA, CAT)
    fam = next(s for s in r.suspects if s.ingredient == "fragrance" and s.match_type == "family")
    assert fam.family == "fragrance"
    assert fam.tier == P.Tier.SUSPECT.value


def test_an_exact_match_ranks_above_a_family_match_of_the_same_tier():
    r = P.analyse("irritation", RIYA, CAT)
    order = [(s.ingredient, s.match_type) for s in r.suspects if s.tier == P.Tier.SUSPECT.value]
    assert order[0] == ("alcohol denat", "exact")
    assert ("fragrance", "family") in order
    assert order.index(("alcohol denat", "exact")) < order.index(("fragrance", "family"))


def test_a_synonym_is_matched_as_the_same_ingredient():
    """"Parfum (Fragrance)" and "Fragrance" are one ingredient, so they count as one."""
    rows = [out("sr-02", "irritation", 2), out("tn-02", "irritation", 2), out("es-01", "suited", 12)]
    r = P.analyse("irritation", rows, CAT)
    # sr-02 lists "Parfum (Fragrance)", tn-02 lists "Fragrance": 2 of 2 products.
    assert tiers(r)["fragrance"] == P.Tier.SUSPECT.value
    frag = next(s for s in r.suspects if s.ingredient == "fragrance" and s.match_type == "exact")
    assert {a.product_id for a in frag.in_failed} == {"sr-02", "tn-02"}


def test_families_version_is_carried_on_every_report():
    r = P.analyse("irritation", RIYA, CAT)
    assert r.families_version == FAM.FAMILIES_VERSION == "families-1.0"
    assert r.rule_version == "patterns-1.0"


def test_fatty_alcohol_is_not_in_the_drying_alcohol_family():
    assert FAM.family_of("Cetearyl Alcohol") == []
    assert FAM.family_of("Alcohol Denat.") == ["drying alcohols"]


# ---------------------------------------------------------------- rule 4: labels kept apart
def test_general_knowledge_is_labelled_separately_from_personal_evidence():
    r = P.analyse("irritation", RIYA, CAT)
    for s in r.suspects:
        assert s.evidence == "personal"
    # An exact suspect carries its own family's general note, so "known common irritant" is
    # available under its own label without being mixed into the counts.
    alc = next(s for s in r.suspects if s.ingredient == "alcohol denat")
    assert alc.family == "drying alcohols"
    assert alc.general_note and "often reported" in alc.general_note


def test_a_family_of_one_is_not_reported_twice():
    """"Drying alcohols" has one member, so a family row would just repeat the exact match."""
    r = P.analyse("irritation", RIYA, CAT)
    assert not [s for s in r.suspects if s.match_type == "family" and s.family == "drying alcohols"]
    assert len(FAM.members_of("drying alcohols")) == 1


# ---------------------------------------------------------------- rule 6: missing is not safe
def test_an_incomplete_label_is_flagged_not_assumed_clean():
    rows = [out("sr-02", "irritation", 2), out("sr-03", "irritation", 2), out("es-01", "suited", 12)]
    r = P.analyse("irritation", rows, CAT)
    assert any(x["product_id"] == "sr-03" for x in r.incomplete_products)
    assert "unknown is not a pass" in r.unknown_note


def test_complete_labels_only_means_no_unknown_note():
    rows = [out("sr-02", "irritation", 2), out("tn-03", "irritation", 3)]
    assert P.analyse("irritation", rows, CAT).unknown_note is None


# ---------------------------------------------------------------- rule 8: wash-off weighting
def test_a_wash_off_product_counts_for_less_in_a_breakout_run():
    rows = [out("cl-02", "breakout", 6), out("sr-05", "breakout", 8), out("es-01", "suited", 12)]
    r = P.analyse("breakout", rows, CAT)
    washed = [a for s in r.suspects for a in s.in_failed if a.product_id == "cl-02"]
    assert washed and all(a.weight == P.WASH_OFF_WEIGHT for a in washed)
    assert all(a.weight_label == P.WASH_OFF_LABEL for a in washed)


def test_a_wash_off_product_is_not_down_weighted_for_irritation():
    """A cleanser that stings, stings. Only breakouts get the contact-time discount."""
    rows = [out("cl-02", "irritation", 6), out("sr-05", "irritation", 8)]
    r = P.analyse("irritation", rows, CAT)
    washed = [a for s in r.suspects for a in s.in_failed if a.product_id == "cl-02"]
    assert washed and all(a.weight == P.LEAVE_ON_WEIGHT for a in washed)


# ---------------------------------------------------------------- INCI positions
def test_every_appearance_carries_its_position_on_the_label():
    r = P.analyse("irritation", RIYA, CAT)
    alc = next(s for s in r.suspects if s.ingredient == "alcohol denat")
    spots = {a.product_id: a.inci_position for a in alc.in_failed}
    assert spots == {"sr-02": 2, "tn-03": 2}
    assert all(a.inci_length > 0 for a in alc.in_failed)


# ---------------------------------------------------------------- rule 7: purge is offered only
def test_purge_is_offered_when_all_three_conditions_hold():
    offers = P.analyse("breakout", RIYA, CAT).purge_offers
    assert [o.product_id for o in offers] == ["sr-05"]
    o = offers[0]
    assert o.ingredient == "azelaic acid" and o.strength == "mild"
    assert "Do you want to record it as purging instead?" in o.question


def test_no_purge_offer_without_a_purge_capable_ingredient():
    rows = [out("sp-01", "breakout", 4, zones=["cheeks"], usual_spots=True,
                settled_while_using=True, settled_week=3)]
    assert P.analyse("breakout", rows, CAT).purge_offers == []


def test_no_purge_offer_when_the_spots_are_in_a_new_area():
    rows = [out("sr-05", "breakout", 8, zones=["cheeks"], usual_spots=False,
                settled_while_using=True, settled_week=4)]
    assert P.analyse("breakout", rows, CAT).purge_offers == []


def test_no_purge_offer_when_usual_spots_was_never_answered():
    rows = [out("sr-05", "breakout", 8, zones=["chin"], settled_while_using=True, settled_week=4)]
    assert P.analyse("breakout", rows, CAT).purge_offers == []


def test_no_purge_offer_when_it_never_settled():
    rows = [out("sr-05", "breakout", 8, zones=["chin"], usual_spots=True,
                settled_while_using=False)]
    assert P.analyse("breakout", rows, CAT).purge_offers == []


def test_no_purge_offer_when_it_settled_later_than_six_weeks():
    rows = [out("sr-05", "breakout", 12, zones=["chin"], usual_spots=True,
                settled_while_using=True, settled_week=9)]
    assert P.analyse("breakout", rows, CAT).purge_offers == []


def test_a_purge_offer_never_changes_the_recorded_outcome():
    """The engine offers; only the user decides. Nothing in the report rewrites the row."""
    rows = list(RIYA)
    before = [o.outcome for o in rows]
    P.analyse("breakout", rows, CAT)
    assert [o.outcome for o in rows] == before
    assert all(o.outcome == "breakout" for o in rows if o.product_id == "sr-05")


def test_irritation_runs_never_offer_a_purge():
    rows = [out("sr-05", "irritation", 8, zones=["chin"], usual_spots=True,
                settled_while_using=True, settled_week=4)]
    assert P.analyse("irritation", rows, CAT).purge_offers == []


# ---------------------------------------------------------------- nothing recorded
def test_no_records_means_no_pattern_rather_than_a_clean_bill():
    r = P.analyse("irritation", [], CAT)
    assert r.suspects == [] and r.cannot_narrow is None
    assert "no pattern to read" in r.headline
