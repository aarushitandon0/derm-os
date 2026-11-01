"""Basket engine (app/basket.py): the zone split, finish, history skips, unknown labels, owned
products, shades, and the wording rules. No YouCam call anywhere: the faces are synthetic dicts
of the documented response shapes."""
import json
import re
from datetime import datetime, timezone

import pytest

from app import basket as BK
from app import decision as D
from app import needs as N
from app import outcomes as OC
from app import products as PRD
from app import scenes as S
from app import undertone as U
from app.demo_faces import BASKET_ACTIONS, DEMO_FACES, load_face
from app.youcam import normalize

CAT = PRD.index()
STOCK = PRD.shop_tags()


def riya_history():
    rows = []
    S.write_outcomes(S.RIYA_OUTCOMES, lambda k, b, id=None: rows.append(b) or b, lambda k: [],
                     lambda k, i: None, CAT, datetime.now(timezone.utc))
    outs = [OC.ProductOutcome.from_dict(r) for r in rows]
    recs = [D.HistoryRecord(D.RecordType(h["type"]), h.get("product_id"), h.get("ingredient"))
            for h in S.RIYA_HISTORY]
    return recs, outs


def skin(t="Oily", u="Dry", whole="Combination", **scores):
    out = [{"type": "skin_type", "whole": {"skin_type": whole}, "t_zone": {"skin_type": t},
            "u_zone": {"skin_type": u}}]
    out += [{"type": k, "raw_score": v, "ui_score": 80} for k, v in scores.items()]
    return {"data": {"task_status": "success", "results": {"output": out}}}


def tone(hex_="#b9947c"):
    return {"data": {"task_status": "success", "results": {"color": {"skin_color": hex_}}}}


def make(skin_payload=None, tone_payload=None, answers=None, shelf=None, history=True, stock=None):
    answers = {"finish": "dewy", **(answers or {})}
    recs, outs = riya_history() if history else ([], [])
    zones = N.read_zones(skin_payload, answers)
    measured = normalize(skin_payload, "sd", BASKET_ACTIONS).raw_scores() if skin_payload else {}
    ut = U.from_payload(tone_payload, answers)
    return BK.build(zones=zones, measured=measured, ut=ut, answers=answers, stock=stock or STOCK,
                    catalog=CAT, records=recs, outcomes=outs,
                    shelf=S.RIYA_TRIAL_SHELF if shelf is None else shelf).to_dict()


def riya():
    f = DEMO_FACES["riya"]
    return make(f["skin"], f["tone"], f["answers"])


def job(b, title):
    return next(j for j in b["jobs"] if j["title"] == title)


def picks(b):
    return {j["title"]: (j["pick"] or {}).get("product", {}).get("id") for j in b["jobs"]}


# ---------------------------------------------------------------- the zone split
def test_oily_tzone_dry_cheeks_gets_two_moisturisers():
    b = riya()
    titles = [j["title"] for j in b["jobs"]]
    assert titles == ["Cleanser", "T-zone moisturiser", "Cheek moisturiser", "Sunscreen / skin tint"]
    t, u = job(b, "T-zone moisturiser"), job(b, "Cheek moisturiser")
    assert t["pick"]["product"]["id"] != u["pick"]["product"]["id"]
    assert STOCK[t["pick"]["product"]["id"]]["texture"] == "gel"
    assert STOCK[u["pick"]["product"]["id"]]["texture"] in ("cream", "balm")
    assert t["how_to_use"].startswith("T-zone only")
    assert u["how_to_use"].startswith("Cheeks")


@pytest.mark.parametrize("kind", ["Dry", "Oily", "Normal"])
def test_same_type_in_both_zones_gets_one_moisturiser(kind):
    b = make(skin(kind, kind, kind), tone(), {"finish": "natural"}, history=False, shelf=[])
    moist = [j for j in b["jobs"] if j["job"] == "moisturiser"]
    assert len(moist) == 1 and moist[0]["title"] == "Moisturiser" and moist[0]["zone"] == "whole"
    assert moist[0]["how_to_use"].startswith("Whole face")


def test_whole_face_combination_with_no_zone_split_still_splits():
    payload = {"data": {"results": {"output": [{"type": "skin_type", "whole": {"skin_type": "Combination"}}]}}}
    zones = N.parse_zones(payload)
    assert (zones["t_zone"].type, zones["u_zone"].type) == ("oily", "normal")


# ---------------------------------------------------------------- finish
def test_finish_changes_the_texture_and_finish_picks():
    f = DEMO_FACES["riya"]
    dewy = make(f["skin"], f["tone"], {"finish": "dewy"})
    matte = make(f["skin"], f["tone"], {"finish": "matte"})
    assert picks(dewy)["T-zone moisturiser"] != picks(matte)["T-zone moisturiser"]
    assert picks(dewy)["Sunscreen / skin tint"] != picks(matte)["Sunscreen / skin tint"]
    assert STOCK[picks(matte)["T-zone moisturiser"]]["finish"] == "matte"
    assert STOCK[picks(dewy)["Sunscreen / skin tint"]]["finish"] == "dewy"
    assert STOCK[picks(matte)["Sunscreen / skin tint"]]["finish"] == "matte"
    # A matte product is skipped as the wrong finish on a dewy basket, and the reverse.
    assert any(s["kind"] == "finish" and "Matte" in s["reason"] for s in dewy["skipped"])
    assert any(s["kind"] == "finish" and "Dewy" in s["reason"] for s in matte["skipped"])


# ---------------------------------------------------------------- history
def test_the_history_suspect_is_skipped_with_its_exact_reason():
    b = riya()
    s = next(s for s in b["skipped"] if s["product_id"] == "tt-01")
    assert s["kind"] == "history" and s["label"] == "From your history"
    assert s["reason"].startswith("Contains Alcohol Denat., in 2 of 2 products that made you itch")
    assert "tt-01" not in picks(b).values()


def test_an_avoided_ingredient_is_skipped_with_the_label_line():
    s = next(s for s in riya()["skipped"] if s["product_id"] == "mo-13")
    assert s["kind"] == "history" and "Parfum" in s["reason"] and "fragrance" in s["reason"]


def test_choosing_to_skip_history_says_so_and_lets_the_suspect_back_in():
    f = DEMO_FACES["riya"]
    b = make(f["skin"], f["tone"], {"finish": "dewy", "history": "ignore"})
    assert all(s["kind"] != "history" for s in b["skipped"])
    lines = [w["line"] for j in b["jobs"] if j["status"] == "pick" for w in j["why"] if w["key"] == "history"]
    assert lines and set(lines) == {BK.HISTORY_IGNORED}


def test_an_empty_history_is_nothing_to_check_not_a_pass():
    f = DEMO_FACES["riya"]
    b = make(f["skin"], f["tone"], {"finish": "dewy"}, history=False, shelf=[])
    lines = {w["line"] for j in b["jobs"] for w in j["why"] if w["key"] == "history"}
    assert lines == {BK.HISTORY_NOTHING}


# ---------------------------------------------------------------- unknown labels
def test_incomplete_inci_is_never_picked():
    b = riya()
    s = next(s for s in b["skipped"] if s["product_id"] == "mo-07")
    assert s["kind"] == "unknown" and s["reason"].startswith("Ingredient list incomplete → unknown")
    assert "mo-07" not in picks(b).values()


def test_incomplete_inci_is_not_picked_even_when_it_is_the_only_candidate():
    only = {"mo-07": STOCK["mo-07"], "cl-12": STOCK["cl-12"], "tt-02": STOCK["tt-02"]}
    b = make(skin("Dry", "Dry", "Dry"), tone(), {"finish": "dewy"}, history=False, shelf=[], stock=only)
    m = next(j for j in b["jobs"] if j["job"] == "moisturiser")
    assert m["status"] == "none" and m["pick"] is None
    assert "Keep what you use now" in m["note"]
    assert any(s["product_id"] == "mo-07" and s["kind"] == "unknown" for s in b["skipped"])


# ---------------------------------------------------------------- already own
def test_an_owned_cleanser_is_not_bought_again():
    b = riya()
    c = job(b, "Cleanser")
    assert c["status"] == "owned" and c["pick"]["product"]["id"] == "cl-01" and c["pick"]["price_inr"] == 0
    assert any(o["product_id"] == "cl-01" and "skip buying" in o["line"] for o in b["already_own"])


def test_an_owned_store_product_moves_to_already_own_and_out_of_the_total():
    f = DEMO_FACES["riya"]
    before = make(f["skin"], f["tone"], f["answers"])
    pid = job(before, "Cheek moisturiser")["pick"]["product"]["id"]
    after = make(f["skin"], f["tone"], f["answers"], shelf=S.RIYA_TRIAL_SHELF + [pid])
    cheek = job(after, "Cheek moisturiser")
    assert cheek["status"] == "owned" and cheek["pick"]["product"]["id"] == pid
    assert any(o["product_id"] == pid for o in after["already_own"])
    assert after["total_inr"] == before["total_inr"] - CAT[pid].price_inr


# ---------------------------------------------------------------- undertone -> shade
@pytest.mark.parametrize("hex_,tone_,undertone", [
    ("#b9947c", "warm-neutral", "warm"),
    ("#c8a07c", "warm", "warm"),
    ("#c8a7a0", "cool", "cool"),
    ("#b9a07c", "olive", "olive"),
])
def test_undertone_picks_the_shade_family(hex_, tone_, undertone):
    b = make(DEMO_FACES["riya"]["skin"], tone(hex_), {"finish": "dewy"})
    base = job(b, "Sunscreen / skin tint")
    ut = b["face_map"]["undertone"]
    assert ut["tone"] == tone_ and ut["source"] == "face"
    assert base["pick"]["shade"]["undertone"] == undertone
    assert base["pick"]["shade"]["depth"] == ut["depth"]
    assert b["tryon"]["shade"] == base["pick"]["shade"]


def test_a_range_with_no_shade_for_you_is_skipped_as_such():
    s = next(s for s in riya()["skipped"] if s["product_id"] == "tt-04")
    assert s["kind"] == "shade" and "medium warm-neutral" in s["reason"]


# ---------------------------------------------------------------- always an answer
def test_no_measurement_falls_back_to_answers_labelled():
    b = make(None, None, {"finish": "natural", "midday": "shiny_tzone"}, history=False, shelf=[])
    fm = b["face_map"]
    assert fm["source"] == "answers" and fm["label"] == "from your answers"
    assert [z["source"] for z in fm["zones"]] == ["answers", "answers"]
    assert fm["undertone"]["source"] == "default"
    assert all(j["status"] in ("pick", "owned") for j in b["jobs"])
    face_labels = {w["label"] for j in b["jobs"] for w in j["why"] if w["key"] == "face"}
    assert face_labels == {"From your answers"}


def test_unreadable_skin_type_uses_the_answers_for_the_zones():
    payload = {"data": {"results": {"output": [{"type": "oiliness", "raw_score": 50}]}}}
    zones = N.read_zones(payload, {"midday": "tight"})
    assert {z.type for z in zones.values()} == {"dry"} and {z.source for z in zones.values()} == {"answers"}


USER_TEXT_KEYS = {"line", "reason", "next_step", "how_to_use", "note", "needs_line", "label", "title",
                  "all_reasons", "fields_note"}


def _user_text(node, out):
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "inputs":
                continue
            if k in USER_TEXT_KEYS:
                if isinstance(v, str):
                    out.append(v)
                elif isinstance(v, list):
                    out += [x for x in v if isinstance(x, str)]
            _user_text(v, out)
    elif isinstance(node, list):
        for x in node:
            _user_text(x, out)
    return out


@pytest.mark.parametrize("finish", ["dewy", "natural", "matte"])
def test_no_scores_and_no_cant_tell_in_any_user_sentence(finish):
    f = DEMO_FACES["riya"]
    b = make(f["skin"], f["tone"], {"finish": finish})
    text = _user_text(b, [])
    assert text
    raw = {str(v) for v in normalize(f["skin"], "sd", BASKET_ACTIONS).raw_scores().values()}
    for t in text:
        assert not re.search(r"\b(scores?|points?)\b", t, re.I), t
        assert not re.search(r"can['’]?t tell|cannot tell", t, re.I), t
        assert not re.search(r"\bsafe\b|\bworks?\b|\bcures?\b|\btreats?\b", t, re.I), t
        assert not any(r in t for r in raw), t


@pytest.mark.parametrize("answers,shelf", [
    ({"finish": "dewy"}, None),
    ({"finish": "matte", "budget": "under_700"}, None),
    ({"finish": "natural", "history": "ignore"}, []),
])
def test_every_basket_has_exactly_one_next_step(answers, shelf):
    f = DEMO_FACES["riya"]
    b = make(f["skin"], f["tone"], answers, shelf=shelf)
    assert isinstance(b["next_step"], str) and b["next_step"]
    assert sum(1 for k in json.dumps({k: v for k, v in b.items() if k != "inputs"}).split('"')
               if k == "next_step") == 1


def test_nothing_new_to_buy_still_has_one_next_step():
    owned = [j["pick"]["product"]["id"] for j in riya()["jobs"] if j["pick"]]
    f = DEMO_FACES["riya"]
    b = make(f["skin"], f["tone"], f["answers"], shelf=S.RIYA_TRIAL_SHELF + owned)
    assert all(j["status"] == "owned" for j in b["jobs"])
    assert b["total_inr"] == 0 and b["next_step"] == BK.NEXT_STEP_NOTHING_NEW


# ---------------------------------------------------------------- budget, inputs, versions
def test_budget_skips_over_budget_products_while_something_under_fits():
    f = DEMO_FACES["riya"]
    b = make(f["skin"], f["tone"], {"finish": "dewy", "budget": "under_700"})
    for j in b["jobs"]:
        if j["status"] == "pick" and not j["note"]:
            assert j["pick"]["price_inr"] <= 700
    base = job(b, "Sunscreen / skin tint")
    assert base["status"] == "pick" and "closest fit" in base["note"]


def test_inputs_and_rule_versions_are_stored():
    b = riya()
    rv = b["inputs"]["rule_versions"]
    assert rv["basket"] == "basket-1.0" and rv["needs"] == "needs-1.0" and rv["undertone"] == "undertone-1.0"
    assert b["inputs"]["shelf"] == S.RIYA_TRIAL_SHELF and b["inputs"]["finish"] == "dewy"


def test_riya_full_basket():
    b = riya()
    assert picks(b) == {"Cleanser": "cl-01", "T-zone moisturiser": "mo-11", "Cheek moisturiser": "mo-14",
                        "Sunscreen / skin tint": "tt-02"}
    assert b["total_inr"] == CAT["mo-11"].price_inr + CAT["mo-14"].price_inr + CAT["tt-02"].price_inr
    assert [z["line"] for z in b["face_map"]["zones"]] == ["T-zone: oily", "Cheeks: dry"]
    assert b["face_map"]["undertone"]["line"] == "Undertone: warm-neutral"
    assert b["tryon"]["status"] == "pending_live" and b["tryon"]["line"] == "Preview appears on a live scan"
    assert [r["look"] for r in b["tryon"]["requests"]] == ["matte", "dewy"]
    for j in b["jobs"]:
        if j["status"] == "pick":
            assert [w["label"] for w in j["why"]] == ["From your face (YouCam)", "From your history",
                                                    "Matches your finish"]


def test_demo_face_is_labelled_recorded_values_with_a_synthetic_fallback():
    from app.demo_faces import DEMO_FACES
    f = load_face("riya")      # fixtures/riya/basket_face.json: values from the 2026-11-01 live scan
    assert f["synthetic"] is False and f["label"] == "Demo data" and f["source"] == "live scan 2026-11-01"
    assert DEMO_FACES["riya"]["synthetic"] is True and DEMO_FACES["riya"]["label"] == "Demo data"
    assert load_face("../x") is None and load_face("nobody") is None


def test_store_has_16_to_20_tagged_fictional_products():
    store = json.loads(PRD.STORE_PATH.read_text(encoding="utf-8"))
    prods = store["products"]
    assert 16 <= len(prods) <= 20
    for p in prods:
        tags = p["shop"]
        assert {"job", "suits", "texture", "finish"} <= set(tags)
        if tags.get("tinted"):
            assert tags["shades"] and all({"depth", "undertone", "hex"} <= set(s) for s in tags["shades"])
    assert any(not p["inci_complete"] for p in prods)
    assert any("Alcohol Denat." in p["inci"] for p in prods if p["shop"]["job"] != "serum")
