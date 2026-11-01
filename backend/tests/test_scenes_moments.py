"""The new demo scenes, checked against the expected outcomes in the session brief.

The point of every test here is the same: the scene writes rows, and the REAL engines produce the
text on screen. So each test asserts on engine output reached through the API, never on anything
the scene itself wrote.

New cases only.
"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DERMOS_DB", str(tmp_path / "t.db"))
    monkeypatch.setenv("DERMOS_MEDIA", str(tmp_path / "media"))
    monkeypatch.setenv("DEMO_MODE", "1")
    import importlib
    import app.main as m
    importlib.reload(m)
    return TestClient(m.app)


def scene(client, name):
    r = client.post(f"/api/demo/scene/{name}")
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------- the scenes exist and are listed
def test_the_new_scenes_are_offered(client):
    names = client.get("/api/demo/scenes").json()["scenes"]
    for n in ("riya-store", "riya-breakout", "meera-pore", "beginner"):
        assert n in names


def test_the_old_scenes_are_still_offered(client):
    names = client.get("/api/demo/scenes").json()["scenes"]
    for n in ("riya-history", "riya-trial", "riya-lamp", "riya-day14", "riya-stop", "meera"):
        assert n in names


# ---------------------------------------------------------------- riya's recorded story
def test_the_store_scene_writes_her_five_outcomes(client):
    scene(client, "riya-store")
    rows = {r["product_id"]: r for r in client.get("/api/outcomes").json()}
    assert set(rows) == {"sr-02", "tn-03", "sr-05", "es-01", "mo-03"}
    assert rows["sr-02"]["outcome"] == "irritation" and rows["sr-02"]["weeks_used"] == 2
    assert rows["tn-03"]["outcome"] == "irritation" and rows["tn-03"]["weeks_used"] == 3
    assert rows["sr-05"]["outcome"] == "breakout" and rows["sr-05"]["weeks_used"] == 8
    assert rows["es-01"]["outcome"] == "suited" and rows["es-01"]["weeks_used"] == 12
    assert rows["mo-03"]["outcome"] == "suited" and rows["mo-03"]["weeks_used"] == 20


def test_both_suited_outcomes_are_past_four_weeks_so_they_count(client):
    scene(client, "riya-store")
    rows = {r["product_id"]: r for r in client.get("/api/outcomes").json()}
    assert rows["es-01"]["counts_as_suited"] is True
    assert rows["mo-03"]["counts_as_suited"] is True


def test_the_scene_never_writes_a_suspect_or_a_verdict(client):
    """A scene writes rows. Every judgement is the engine's."""
    scene(client, "riya-store")
    dump = client.get("/api/outcomes").text.lower()
    for word in ("suspect", "lead", "verdict", "repeats a pattern", "no conflicts"):
        assert word not in dump


# ---------------------------------------------------------------- expected outcome 1
def test_her_irritation_suspect_is_alcohol_denat(client):
    scene(client, "riya-store")
    top = client.get("/api/patterns").json()["irritation"]["suspects"][0]
    assert top["ingredient"] == "alcohol denat"
    assert top["tier"] == "suspect" and top["match_type"] == "exact"
    assert top["counts_line"] == ("in 2 of 2 products that made you itch, sting or burn, "
                                  "0 of 2 that suited you")


def test_the_two_products_that_itched_are_the_vitamin_c_and_the_rose_toner(client):
    scene(client, "riya-store")
    top = client.get("/api/patterns").json()["irritation"]["suspects"][0]
    assert {a["product_id"] for a in top["in_failed"]} == {"sr-02", "tn-03"}
    assert top["suited_count"] == 0


# ---------------------------------------------------------------- expected outcome 2
def test_the_azelaic_breakout_offers_a_purge_reclassification(client):
    scene(client, "riya-store")
    offers = client.get("/api/patterns").json()["breakout"]["purge_offers"]
    assert [o["product_id"] for o in offers] == ["sr-05"]
    assert offers[0]["settled_week"] == 5 and offers[0]["strength"] == "mild"


def test_the_purge_offer_leaves_the_recorded_outcome_alone(client):
    scene(client, "riya-store")
    client.get("/api/patterns")
    row = next(r for r in client.get("/api/outcomes").json() if r["product_id"] == "sr-05")
    assert row["outcome"] == "breakout"


# ---------------------------------------------------------------- expected outcome 3: the store
def test_the_three_store_verdicts_are_the_ones_promised(client):
    scene(client, "riya-store")
    got = {}
    for pid in ("sr-08", "mo-07", "sr-09"):
        got[pid] = client.post("/api/cartcheck", json={"product_id": pid}).json()
    assert got["sr-08"]["verdict_line"] == "Repeats a pattern"
    assert got["mo-07"]["verdict_line"] == "Ingredient list incomplete → unknown"
    assert got["sr-09"]["verdict_line"] == "No conflicts with your history"


def test_the_passing_store_product_is_aimed_at_her_measured_pores(client):
    scene(client, "riya-store")
    res = client.post("/api/cartcheck", json={"product_id": "sr-09"}).json()
    skin = next(s for s in res["sources"] if s["key"] == "skin")
    assert "Aimed at pores" in skin["lines"][0]
    assert skin["detail"]["scanned"] is True
    assert "pore" in skin["detail"]["top_concerns"]


def test_the_blocked_product_shows_the_suspect_with_its_label_line(client):
    scene(client, "riya-store")
    res = client.post("/api/cartcheck", json={"product_id": "sr-08"}).json()
    hist = next(s for s in res["sources"] if s["key"] == "history")
    assert "Alcohol Denat." in hist["lines"][0]
    assert "Suspect" in hist["lines"][0]


# ---------------------------------------------------------------- expected outcome 4: triage
def test_the_breakout_scene_carries_what_she_is_using_and_since_when(client):
    s = scene(client, "riya-breakout")
    assert s["situation"]["kind"] == "breakout"
    assert s["situation"]["zones"] == ["cheeks"] and s["situation"]["usual_spots"] is False
    using = {u["product_id"]: u["started_weeks_ago"] for u in s["situation"]["using"]}
    assert using["sp-01"] == 4 and using["es-01"] == 12


def test_the_sunscreen_is_the_top_lead_and_it_is_not_a_purge(client):
    s = scene(client, "riya-breakout")
    sit = s["situation"]
    using = [{"product_id": u["product_id"],
              "started_on": _weeks_ago(u["started_weeks_ago"])} for u in sit["using"]]
    r = client.post("/api/triage", json={"symptoms": sit["symptoms"], "zones": sit["zones"],
                                         "usual_spots": sit["usual_spots"], "using": using}).json()
    assert r["candidates"][0]["product_id"] == "sp-01"
    assert r["candidates"][0]["in_window"] is True
    assert r["purge"]["possible"] is False and r["purge"]["consistent"] is False
    assert r["next_action"]["pause_product_id"] == "sp-01"


def test_the_snail_mucin_is_ranked_low_with_its_reason(client):
    s = scene(client, "riya-breakout")
    sit = s["situation"]
    using = [{"product_id": u["product_id"],
              "started_on": _weeks_ago(u["started_weeks_ago"])} for u in sit["using"]]
    r = client.post("/api/triage", json={"zones": sit["zones"], "usual_spots": sit["usual_spots"],
                                         "using": using}).json()
    snail = next(c for c in r["candidates"] if c["product_id"] == "es-01")
    assert snail["tier"] > r["candidates"][0]["tier"]
    assert "12 weeks without this problem" in snail["reason"]


def _weeks_ago(w):
    from datetime import date, timedelta
    return (date.today() - timedelta(weeks=w)).isoformat()


# ---------------------------------------------------------------- expected outcome 5: meera
def test_meeras_positive_verdict_is_on_pores_and_not_on_redness(client):
    s = scene(client, "meera-pore")
    ev = client.get(f"/api/trials/{s['trial_id']}/evidence").json()
    assert ev["trial"]["goal_concern"] == "pore"
    assert ev["report"]["verdict"] == "moved_beyond_noise"
    moved = [f["concern"] for f in ev["report"]["findings"] if f["beyond_noise"]]
    assert moved == ["pore"]
    assert "redness" not in moved


def test_meeras_move_is_in_the_good_direction_and_comparable(client):
    s = scene(client, "meera-pore")
    ev = client.get(f"/api/trials/{s['trial_id']}/evidence").json()
    pore = next(f for f in ev["report"]["findings"] if f["concern"] == "pore")
    assert pore["direction"] == "better"
    assert ev["report"]["comparability"]["comparable"] is True


def test_meeras_message_stays_at_during_this_trial(client):
    s = scene(client, "meera-pore")
    ev = client.get(f"/api/trials/{s['trial_id']}/evidence").json()
    msg = ev["report"]["message"]
    assert "Pores looked smaller beyond your usual variation during this trial." in msg
    assert "seasons, sleep and cycles move skin too" in msg
    for banned in ("caused", "works", "proven", "safe"):
        assert banned not in msg.lower()


def test_the_raw_difference_the_typical_app_line_is_built_from(client):
    """The grey "a typical app would say" line is the raw score difference, nothing else."""
    s = scene(client, "meera-pore")
    ev = client.get(f"/api/trials/{s['trial_id']}/evidence").json()
    pore = next(f for f in ev["report"]["findings"] if f["concern"] == "pore")
    assert pore["delta_mid"] == 6.0
    assert round(pore["baseline"]["lo"], 1) == 57.2 and round(pore["baseline"]["hi"], 1) == 58.4
    assert round(pore["followup"]["lo"], 1) == 63.4 and round(pore["followup"]["hi"], 1) == 64.2


def test_meeras_write_back_records_suited_after_five_weeks(client):
    s = scene(client, "meera-pore")
    wb = client.post(f"/api/trials/{s['trial_id']}/writeback").json()
    assert wb["outcome"]["outcome"] == "suited"
    assert wb["outcome"]["weeks_used"] == 5
    assert wb["outcome"]["counts_as_suited"] is True


def test_the_original_meera_scene_still_judges_redness(client):
    """The existing scene and its benchmark cases are untouched by the new one."""
    s = scene(client, "meera")
    ev = client.get(f"/api/trials/{s['trial_id']}/evidence").json()
    assert ev["trial"]["goal_concern"] == "redness"
    assert ev["report"]["verdict"] == "moved_beyond_noise"


# ---------------------------------------------------------------- expected outcome 6: beginner
def test_the_beginner_scene_starts_from_nothing(client):
    scene(client, "riya-store")          # load a full story first...
    s = scene(client, "beginner")        # ...then the beginner must clear it
    assert client.get("/api/outcomes").json() == []
    assert client.get("/api/shelf").json()["product_ids"] == []
    assert s["trial_id"] is None


def test_the_beginners_skin_type_is_labelled_from_her_answers(client):
    s = scene(client, "beginner")
    answers = s["situation"]["answers"]
    p = client.post("/api/beginner/plan", json={"answers": answers}).json()
    assert p["skin_type"]["source"] == "answers"
    assert p["skin_type"]["label"] == "from your answers"
    assert p["skin_type"]["value"] == "combination"


def test_the_beginner_gets_a_three_step_starter_that_was_checked(client):
    s = scene(client, "beginner")
    p = client.post("/api/beginner/plan", json={"answers": s["situation"]["answers"]}).json()
    assert [st["role"] for st in p["steps"]] == ["cleanser", "moisturiser", "sunscreen"]
    for st in p["steps"]:
        assert st["check"]["rule_version"] == "cartcheck-1.0"
        # With no records and no scan, nothing can be called a pass or aimed at anything.
        skin = next(x for x in st["check"]["sources"] if x["key"] == "skin")
        assert skin["lines"][0].startswith("No scan yet")


def test_the_beginner_has_no_measured_concerns_until_she_scans(client):
    s = scene(client, "beginner")
    p = client.post("/api/beginner/plan", json={"answers": s["situation"]["answers"]}).json()
    assert p["concerns"] == []


# ---------------------------------------------------------------- rebuilding is idempotent
def test_rebuilding_a_scene_replaces_its_rows_rather_than_doubling_them(client):
    scene(client, "riya-store")
    scene(client, "riya-store")
    assert len(client.get("/api/outcomes").json()) == 5
    caps = [c for c in client.get("/api/trials").json()]
    assert len(caps) == 0, "the store scene opens no trial"


def test_every_scene_builds_without_error(client):
    for name in client.get("/api/demo/scenes").json()["scenes"]:
        assert client.post(f"/api/demo/scene/{name}").status_code == 200, name
