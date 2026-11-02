"""The three moments end to end over the API: outcomes -> patterns -> cart check -> store,
breakout triage, and the verdict write-back landing back in history.

New cases only. YouCam is mocked, so no unit is ever spent here.
"""
import io
import itertools
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from PIL import Image

LIVE = {"X-Live-Passcode": "test-passcode"}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DERMOS_DB", str(tmp_path / "t.db"))
    monkeypatch.setenv("DERMOS_MEDIA", str(tmp_path / "media"))
    import importlib
    import app.main as m
    importlib.reload(m)

    # Lowest score = biggest concern, so pores and oiliness are her top concerns.
    scores = {"redness": 62.0, "acne": 72.0, "texture": 58.0, "pore": 55.0, "oiliness": 48.0}
    jitter = itertools.cycle([0.0, 0.4, -0.3])

    class FakeYouCam:
        def analyze(self, path, actions):
            from app.youcam import normalize
            d = next(jitter)
            return normalize({"data": {"results": {"output": [
                {"type": a, "raw_score": scores.get(a, 60.0) + d, "ui_score": 80}
                for a in actions]}}}, "sd", actions, "T")

    monkeypatch.setattr(m, "YouCamClient", lambda: FakeYouCam())
    return TestClient(m.app, headers=LIVE)


def jpg(color=(200, 160, 140)):
    b = io.BytesIO()
    Image.new("RGB", (720, 960), color).save(b, "JPEG")
    return b.getvalue()


def ago(weeks):
    return (datetime.now(timezone.utc).date() - timedelta(weeks=weeks)).isoformat()


def seed_riya(client):
    """Riya's story, written only through the app's own endpoints."""
    client.put("/api/shelf", json={"product_ids": ["cl-01", "sr-01", "mo-03", "sp-01"]})
    client.post("/api/history", json={"type": "suspected_reaction", "product_id": "mo-02"})
    client.post("/api/history", json={"type": "avoid", "ingredient": "fragrance"})
    rows = [
        {"product_id": "sr-02", "outcome": "irritation", "started_on": ago(60),
         "stopped_on": ago(58), "note": "Itched within a few days."},
        {"product_id": "tn-03", "outcome": "irritation", "started_on": ago(40),
         "stopped_on": ago(37), "note": "Itched again."},
        {"product_id": "sr-05", "outcome": "breakout", "started_on": ago(30),
         "stopped_on": ago(22), "zones": ["chin"], "usual_spots": True,
         "settled_while_using": True, "settled_week": 5},
        {"product_id": "es-01", "outcome": "suited", "started_on": ago(12)},
        {"product_id": "mo-03", "outcome": "suited", "started_on": ago(20)},
    ]
    for r in rows:
        assert client.post("/api/outcomes", json=r).status_code == 200, r


# ---------------------------------------------------------------- outcomes
def test_an_outcome_round_trips_with_its_derived_fields(client):
    client.post("/api/outcomes", json={"product_id": "es-01", "outcome": "suited",
                                       "started_on": ago(12)})
    row = client.get("/api/outcomes").json()[0]
    assert row["weeks_used"] == 12
    assert row["effective_outcome"] == "suited" and row["counts_as_suited"] is True
    assert row["label"] == "Suited me"


def test_a_short_suited_outcome_reads_as_too_early(client):
    client.post("/api/outcomes", json={"product_id": "es-01", "outcome": "suited",
                                       "started_on": ago(2)})
    row = client.get("/api/outcomes").json()[0]
    assert row["effective_outcome"] == "too_early"
    assert row["label"] == "Too early to say"
    assert "clears nothing" in row["plain_line"]


def test_leave_on_comes_from_the_catalog_not_the_client(client):
    client.post("/api/outcomes", json={"product_id": "cl-01", "outcome": "not_sure",
                                       "leave_on": True})
    assert client.get("/api/outcomes").json()[0]["leave_on"] is False


def test_recording_the_same_product_again_replaces_the_row(client):
    client.post("/api/outcomes", json={"product_id": "es-01", "outcome": "not_sure"})
    client.post("/api/outcomes", json={"product_id": "es-01", "outcome": "suited",
                                       "started_on": ago(12)})
    rows = client.get("/api/outcomes").json()
    assert len(rows) == 1 and rows[0]["outcome"] == "suited"


def test_an_unknown_product_is_refused(client):
    assert client.post("/api/outcomes", json={"product_id": "nope", "outcome": "suited"}).status_code == 404


def test_an_unknown_outcome_is_refused(client):
    r = client.post("/api/outcomes", json={"product_id": "es-01", "outcome": "works"})
    assert r.status_code == 422


def test_outcomes_do_not_appear_as_history_records(client):
    """The three record types and their blocking rules are untouched by an outcome."""
    client.post("/api/outcomes", json={"product_id": "es-01", "outcome": "suited",
                                       "started_on": ago(12)})
    assert client.get("/api/history").json() == []
    chk = client.post("/api/cartcheck", json={"product_id": "es-01"}).json()
    assert chk["rung"] != "blocked"


# ---------------------------------------------------------------- patterns
def test_the_two_pattern_runs_are_separate(client):
    seed_riya(client)
    p = client.get("/api/patterns").json()
    assert p["irritation"]["kind"] == "irritation" and p["breakout"]["kind"] == "breakout"
    irr = [s["ingredient"] for s in p["irritation"]["suspects"]]
    brk = [s["ingredient"] for s in p["breakout"]["suspects"]]
    assert "alcohol denat" in irr and "alcohol denat" not in brk


def test_the_irritation_suspect_is_the_shared_drying_alcohol(client):
    seed_riya(client)
    top = client.get("/api/patterns").json()["irritation"]["suspects"][0]
    assert top["ingredient"] == "alcohol denat" and top["tier"] == "suspect"
    assert top["match_type"] == "exact"
    assert top["counts_line"] == ("in 2 of 2 products that made you itch, sting or burn, "
                                  "0 of 2 that suited you")


def test_the_single_breakout_product_cannot_be_narrowed_down(client):
    seed_riya(client)
    brk = client.get("/api/patterns").json()["breakout"]
    assert "One product can't tell us" in brk["cannot_narrow"]
    assert [s for s in brk["suspects"] if s["tier"] in ("suspect", "lead")] == []


def test_the_purge_offer_is_offered_and_changes_nothing(client):
    seed_riya(client)
    offers = client.get("/api/patterns").json()["breakout"]["purge_offers"]
    assert [o["product_id"] for o in offers] == ["sr-05"]
    assert "Do you want to record it as purging instead?" in offers[0]["question"]
    # The stored row is still a breakout: the offer is a question, not a change.
    row = next(r for r in client.get("/api/outcomes").json() if r["product_id"] == "sr-05")
    assert row["outcome"] == "breakout"


# ---------------------------------------------------------------- cart check and the store
def test_the_store_lists_the_sale_with_both_prices(client):
    s = client.get("/api/store").json()
    assert s["name"] == "Glowcart Big Sale"
    assert len(s["items"]) == 4
    for i in s["items"]:
        assert i["sale_price_inr"] < i["product"]["price_inr"]
        assert i["blurb"] and i["product"]["id"]


def test_the_three_sale_verdicts_are_the_ones_the_demo_promises(client):
    seed_riya(client)
    verdicts = {}
    for pid in ("sr-08", "mo-07", "sr-09"):
        verdicts[pid] = client.post("/api/cartcheck", json={"product_id": pid}).json()
    assert verdicts["sr-08"]["rung"] == "repeats_a_pattern"
    assert verdicts["mo-07"]["verdict_line"] == "Ingredient list incomplete → unknown"
    assert verdicts["sr-09"]["rung"] == "no_conflicts"


def test_a_cart_check_with_no_scan_says_to_scan_first(client):
    seed_riya(client)
    res = client.post("/api/cartcheck", json={"product_id": "sr-09"}).json()
    skin = next(s for s in res["sources"] if s["key"] == "skin")
    assert skin["lines"] == ["No scan yet: scan to see if this is aimed at your skin's top concerns."]
    assert skin["detail"]["scanned"] is False


def test_a_cart_check_after_a_scan_names_the_measured_concern(client):
    seed_riya(client)
    client.post("/api/scan", files={"image": ("a.jpg", jpg(), "image/jpeg")},
                data={"phase": "free", "actions": "redness,acne,texture,pore,oiliness"})
    res = client.post("/api/cartcheck", json={"product_id": "sr-09"}).json()
    skin = next(s for s in res["sources"] if s["key"] == "skin")
    assert "Aimed at pores" in skin["lines"][0]
    assert skin["detail"]["scanned"] is True
    assert skin["detail"]["top_concerns"][0] == "oiliness"


def test_use_scan_false_gives_the_no_scan_wording_without_deleting_anything(client):
    seed_riya(client)
    client.post("/api/scan", files={"image": ("a.jpg", jpg(), "image/jpeg")},
                data={"phase": "free", "actions": "redness,pore"})
    res = client.post("/api/cartcheck", json={"product_id": "sr-09", "use_scan": False}).json()
    skin = next(s for s in res["sources"] if s["key"] == "skin")
    assert skin["detail"]["scanned"] is False
    assert len(client.get("/api/trials").json()) == 0


def test_every_cart_check_has_three_sources_change_nothing_and_one_next_step(client):
    seed_riya(client)
    for pid in ("sr-08", "mo-07", "sr-09", "sp-04", "mo-02"):
        res = client.post("/api/cartcheck", json={"product_id": pid}).json()
        assert [s["key"] for s in res["sources"]] == ["history", "skin", "shelf"]
        assert res["change_nothing"].startswith("Change nothing.")
        assert res["next_step"] and "\n" not in res["next_step"]
        assert res["rule_version"] == "cartcheck-1.0"


def test_a_cart_check_stores_the_inputs_it_used(client):
    seed_riya(client)
    res = client.post("/api/cartcheck", json={"product_id": "sr-09"}).json()
    assert res["inputs"]["shelf"] == ["cl-01", "sr-01", "mo-03", "sp-01"]
    assert len(res["inputs"]["outcomes"]) == 5
    assert res["inputs"]["rule_versions"]["patterns"] == "patterns-1.0"


def test_an_unknown_product_cannot_be_cart_checked(client):
    assert client.post("/api/cartcheck", json={"product_id": "nope"}).status_code == 404


# ---------------------------------------------------------------- triage
def test_riyas_breakout_puts_the_new_sunscreen_top_and_rules_out_purging(client):
    seed_riya(client)
    r = client.post("/api/triage", json={
        "symptoms": [], "zones": ["cheeks"], "usual_spots": False,
        "using": [{"product_id": "cl-01", "started_on": ago(30)},
                  {"product_id": "es-01", "started_on": ago(12)},
                  {"product_id": "mo-03", "started_on": ago(20)},
                  {"product_id": "sp-01", "started_on": ago(4)}]}).json()
    assert r["candidates"][0]["product_id"] == "sp-01"
    assert r["purge"]["consistent"] is False
    assert "no ingredient that speeds up cell turnover" in r["purge"]["line"]
    assert r["next_action"]["pause_product_id"] == "sp-01"
    assert r["next_action"]["checkpoint_days"] == 14


def test_the_snail_mucin_ranks_low_with_its_reason_shown(client):
    seed_riya(client)
    r = client.post("/api/triage", json={
        "zones": ["cheeks"], "usual_spots": False,
        "using": [{"product_id": "es-01", "started_on": ago(12)},
                  {"product_id": "sp-01", "started_on": ago(4)}]}).json()
    snail = next(c for c in r["candidates"] if c["product_id"] == "es-01")
    assert snail["tier"] > r["candidates"][0]["tier"]
    assert "used this for 12 weeks without this problem" in snail["reason"]
    assert "not a clean bill" in snail["reason"]


def test_a_stop_symptom_in_triage_outranks_the_ranking(client):
    seed_riya(client)
    r = client.post("/api/triage", json={
        "symptoms": ["itching"], "zones": ["cheeks"], "usual_spots": False,
        "using": [{"product_id": "sp-01", "started_on": ago(4)}]}).json()
    assert r["stop"] is True
    assert r["next_action"]["kind"] == "stop_card"


def test_triage_falls_back_to_the_shelf_with_no_dates(client):
    seed_riya(client)
    r = client.post("/api/triage", json={"zones": ["cheeks"], "usual_spots": False}).json()
    assert len(r["candidates"]) == 4
    assert all(c["weeks_used"] is None for c in r["candidates"])
    assert all("No start date recorded" in c["reason"] for c in r["candidates"])


def test_with_no_mask_numbers_triage_uses_the_tapped_zones_and_says_so(client):
    seed_riya(client)
    r = client.post("/api/triage", json={"zones": ["cheeks"], "usual_spots": False}).json()
    assert r["zones"]["source"] == "tapped"
    assert "No per-zone mask numbers were available" in r["zones"]["source_note"]


def test_triage_refuses_an_unknown_product(client):
    r = client.post("/api/triage", json={"using": [{"product_id": "nope"}]})
    assert r.status_code == 404


# ---------------------------------------------------------------- write-back
def baseline_and_checkin(client, product_id="sr-09", goal="pore"):
    t = client.post("/api/trials", json={"goal_concern": goal, "product_id": product_id,
                                         "held_fixed": ["cl-01"]}).json()
    for _ in range(3):
        client.post("/api/scan", files={"image": ("a.jpg", jpg(), "image/jpeg")},
                    data={"phase": "baseline", "trial_id": t["id"], "actions": goal})
    return t


def test_a_cant_tell_verdict_writes_not_sure_and_says_why(client):
    t = baseline_and_checkin(client)
    # One check-in scan only, so there is no comparable pair: a can't-tell.
    client.post("/api/scan", files={"image": ("a.jpg", jpg(), "image/jpeg")},
                data={"phase": "checkin", "trial_id": t["id"], "actions": "pore"})
    pre = client.get(f"/api/trials/{t['id']}/writeback").json()
    assert pre["outcome"]["outcome"] == "not_sure"
    assert client.get("/api/outcomes").json() == [], "a preview must write nothing"

    done = client.post(f"/api/trials/{t['id']}/writeback").json()
    assert done["outcome"]["outcome"] == "not_sure"
    assert done["outcome"]["source"] == "writeback"
    row = client.get("/api/outcomes").json()[0]
    assert row["product_id"] == "sr-09" and row["outcome"] == "not_sure"
    assert row["counts_as_suited"] is False


def test_a_cant_tell_verdict_never_writes_suited_even_on_an_old_trial(client):
    t = baseline_and_checkin(client)
    client.post("/api/scan", files={"image": ("a.jpg", jpg(), "image/jpeg")},
                data={"phase": "checkin", "trial_id": t["id"], "actions": "pore"})
    wb = client.post(f"/api/trials/{t['id']}/writeback").json()
    assert wb["outcome"]["outcome"] != "suited"


def test_a_stop_verdict_writes_the_reaction_into_history(client):
    t = baseline_and_checkin(client)
    client.post(f"/api/trials/{t['id']}/checkin", json={"symptoms": ["itching"],
                                                        "other_new_leave_on": []})
    wb = client.post(f"/api/trials/{t['id']}/writeback").json()
    assert wb["outcome"]["outcome"] == "irritation"
    assert "you logged itching" in wb["outcome"]["note"]


def test_the_write_back_feeds_the_next_cart_check(client):
    """The loop: a stop on one product becomes evidence the next purchase check reads."""
    seed_riya(client)
    t = baseline_and_checkin(client, product_id="sr-08", goal="pore")
    client.post(f"/api/trials/{t['id']}/checkin", json={"symptoms": ["itching"],
                                                        "other_new_leave_on": []})
    client.post(f"/api/trials/{t['id']}/writeback")
    # sr-08 is now a third product that itched, so its alcohol stays a suspect with new counts.
    top = client.get("/api/patterns").json()["irritation"]["suspects"][0]
    assert top["ingredient"] == "alcohol denat"
    assert top["failed_count"] == 3 and top["failed_total"] == 3


def test_a_write_back_updates_the_same_row_rather_than_piling_up(client):
    t = baseline_and_checkin(client)
    client.post("/api/scan", files={"image": ("a.jpg", jpg(), "image/jpeg")},
                data={"phase": "checkin", "trial_id": t["id"], "actions": "pore"})
    client.post(f"/api/trials/{t['id']}/writeback")
    client.post(f"/api/trials/{t['id']}/writeback")
    assert len(client.get("/api/outcomes").json()) == 1


# ---------------------------------------------------------------- start here
def test_the_beginner_questions_are_served(client):
    q = client.get("/api/beginner/questions").json()
    assert len(q["questions"]) == 4


def test_the_beginner_plan_is_three_checked_steps_labelled_from_your_answers(client):
    p = client.post("/api/beginner/plan", json={"answers": {
        "midday": "shiny_tzone", "reacts": "rarely", "breakouts": "monthly",
        "using": "nothing"}}).json()
    assert p["skin_type"]["value"] == "combination"
    assert p["skin_type"]["label"] == "from your answers"
    assert [s["role"] for s in p["steps"]] == ["cleanser", "moisturiser", "sunscreen"]
    for s in p["steps"]:
        assert s["check"]["rule_version"] == "cartcheck-1.0"
    assert p["next_step"]


def test_the_beginner_plan_shows_concerns_only_after_a_scan(client):
    answers = {"answers": {"midday": "shiny_all", "reacts": "rarely",
                           "breakouts": "weekly", "using": "nothing"}}
    assert client.post("/api/beginner/plan", json=answers).json()["concerns"] == []
    client.post("/api/scan", files={"image": ("a.jpg", jpg(), "image/jpeg")},
                data={"phase": "free", "actions": "redness,acne,texture,pore,oiliness"})
    p = client.post("/api/beginner/plan", json=answers).json()
    assert [c["concern"] for c in p["concerns"]] == ["oiliness", "pore", "texture"]
    assert all(c["sentence"] for c in p["concerns"])


# ---------------------------------------------------------------- meta
def test_meta_publishes_the_new_engines_rules(client):
    m = client.get("/api/meta").json()
    for v in ("outcomes-1.0", "patterns-1.0", "cartcheck-1.0", "triage-1.0",
              "writeback-1.0", "beginner-1.0", "families-1.0"):
        assert v in m["engine_rules"]
    assert m["cartcheck"]["ladder"] == ["blocked", "repeats_a_pattern", "patch_test_first",
                                        "no_conflicts"]
    assert m["outcomes"]["suited_min_weeks"] == 4
    assert m["triage"]["window_weeks"] == [2, 8]


def test_the_old_meta_keys_are_still_there(client):
    m = client.get("/api/meta").json()
    assert m["rules"] == ["decision-1.0", "evidence-1.0"]
    assert m["record_types"] == ["suspected_reaction", "avoid", "confirmed_allergy"]
