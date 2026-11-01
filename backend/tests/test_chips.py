"""Quick history by ingredient (app/chips.py, chips-1.0)."""
import pytest

from app import chips as CH
from app import decision as D
from benchmark import cases as C

CAT = D.load_catalog()
CALM = ["Water", "Glycerin", "Squalane", "Panthenol", "Allantoin", "Sodium Hyaluronate"]


def chips(*rows):
    return CH.parse_all([dict(r) for r in rows])


def test_itched_skips_with_reason_exact_and_family():
    c = chips({"chip": "vitamin_c", "reaction": "itched"})
    exact = CH.evaluate(CALM + ["Ascorbic Acid"], c)["skip"]
    fam = CH.evaluate(C.IDX["mo-17"].inci, c)["skip"]
    assert exact[0]["match_type"] == "exact" and "itched, stung or burned on you before" in exact[0]["line"]
    assert fam[0]["match_type"] == "family" and "same group as vitamin C" in fam[0]["line"]


def test_broke_out_skips_only_a_key_active_with_formula_caveat():
    c = chips({"chip": "azelaic_acid", "reaction": "broke_out"})
    key = CH.evaluate(C.IDX["mo-18"].inci, c)["skip"]
    assert key and "may have been the rest of that product's formula, not azelaic acid itself" in key[0]["line"]
    # Seventh line, no percentage: not a key active, so not skipped.
    assert CH.evaluate(CALM + ["Azelaic Acid"], c)["skip"] == []
    assert CH.evaluate(CALM + ["Azelaic Acid 5%"], c)["skip"]          # a printed % makes it key


def test_suited_never_excludes():
    c = chips({"chip": "snail_mucin", "reaction": "suited"})
    out = CH.evaluate(CALM + ["Snail Secretion Filtrate"], c)
    assert out["skip"] == [] and out["worked"] and CH.avoid_items(c) == []
    assert c[0].line() == "Snail mucin worked for you."


def test_clinician_confirmed_is_the_existing_hard_block():
    c = chips({"chip": "vitamin_c", "reaction": "itched", "confirmed_allergy": True})
    recs = CH.records_from(c)
    assert recs and all(r.type == D.RecordType.CONFIRMED_ALLERGY for r in recs)
    assert D.check_product(C.IDX["mo-17"], recs).status == D.Status.BLOCKED
    # Only an "itched" chip can carry the clinician tick.
    assert CH.records_from(chips({"chip": "vitamin_c", "reaction": "broke_out", "confirmed_allergy": True})) == []


def test_purge_is_offered_only_after_yes_and_never_applied_silently():
    asked = chips({"chip": "azelaic_acid", "reaction": "broke_out"})[0]
    assert asked.purge_question() == CH.PURGE_QUESTION and asked.purge_offer() is None
    yes = chips({"chip": "azelaic_acid", "reaction": "broke_out", "usual_spots_settled": "yes"})[0]
    assert yes.purge_offer() == CH.PURGE_OFFER and not yes.purging
    assert CH.evaluate(C.IDX["mo-18"].inci, [yes])["skip"]               # still a breakout until chosen
    # A purge choice without the yes is dropped: never decided for the user.
    sneaky = chips({"chip": "azelaic_acid", "reaction": "broke_out", "purge_choice": "purging"})[0]
    assert sneaky.purge_choice is None
    chosen = chips({"chip": "azelaic_acid", "reaction": "broke_out", "usual_spots_settled": "yes",
                    "purge_choice": "purging"})[0]
    out = CH.evaluate(C.IDX["mo-18"].inci, [chosen])
    assert out["skip"] == [] and "patch-test it first" in out["notes"][0]
    # Not purge-capable: no question at all.
    assert chips({"chip": "snail_mucin", "reaction": "broke_out"})[0].purge_question() is None


def test_product_level_history_ranks_above_chips():
    b = C.basket_of(chips=[{"chip": "fragrance", "reaction": "itched"}])
    s = next(s for s in b["skipped"] if s["product_id"] == "mo-13")
    assert s["kind"] == "history" and "you chose to avoid fragrance" in s["reason"]
    assert any("itched, stung or burned" in r for r in s["all_reasons"][1:])


def test_free_text_matches_families_and_unknown_is_none():
    assert CH.match_text("glycolic acid")["id"] == "aha"
    assert CH.match_text("zzzz not an ingredient") is None
    with pytest.raises(ValueError):
        CH.Chip(chip="vitamin_c", reaction="loved it")
