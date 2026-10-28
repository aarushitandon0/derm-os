"""End-to-end API flow with YouCam mocked: history -> compare -> trial -> scans -> evidence."""
import io
import itertools

import pytest
from fastapi.testclient import TestClient
from PIL import Image

LIVE = {"X-Live-Passcode": "test-passcode"}  # live scans need it; see app/guard.py


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DERMOS_DB", str(tmp_path / "t.db"))
    monkeypatch.setenv("DERMOS_MEDIA", str(tmp_path / "media"))
    import importlib
    import app.main as m
    importlib.reload(m)

    scores = itertools.cycle([60.0, 62.0, 61.0, 63.0])

    class FakeYouCam:
        def analyze(self, path, actions):
            from app.youcam import normalize
            return normalize({"data": {"results": {"output": [
                {"type": a, "raw_score": next(scores), "ui_score": 80} for a in actions]}}}, "sd", actions, "T")

    monkeypatch.setattr(m, "YouCamClient", lambda: FakeYouCam())
    return TestClient(m.app, headers=LIVE)


def jpg(color=(200, 160, 140)):
    b = io.BytesIO()
    Image.new("RGB", (720, 960), color).save(b, "JPEG")
    return b.getvalue()


def test_demo_story(client):
    assert client.put("/api/shelf", json={"product_ids": ["cl-01", "sr-01", "mo-01", "sp-01"]}).status_code == 200
    client.post("/api/history", json={"type": "suspected_reaction", "product_id": "mo-02"})
    client.post("/api/history", json={"type": "avoid", "ingredient": "fragrance"})

    cmp = client.post("/api/compare", json={"options": [
        {"name": "A", "items": [{"product_id": "mo-02"}]},
        {"name": "B", "items": [{"product_id": "mo-04", "mode": "replace"}]},
    ]}).json()
    a, b = cmp["columns"][1], cmp["columns"][2]
    assert a["blocked"] is True
    assert b["unknowns"] == ["mo-04"]
    assert cmp["next_question"]["choices"] == ["replace", "add"]

    # A blocked product cannot start a trial.
    assert client.post("/api/trials", json={"goal_concern": "redness", "product_id": "mo-02"}).status_code == 409

    t = client.post("/api/trials", json={"goal_concern": "redness", "product_id": "mo-03"}).json()
    for _ in range(2):
        client.post("/api/scan", files={"image": ("a.jpg", jpg(), "image/jpeg")},
                    data={"actions": "redness", "trial_id": t["id"], "phase": "baseline", "face_ratio": 0.7})
    # Check-in under warm, dim light: the gate should catch it immediately.
    r = client.post("/api/scan", files={"image": ("b.jpg", jpg((120, 60, 30)), "image/jpeg")},
                    data={"actions": "redness", "trial_id": t["id"], "phase": "checkin", "face_ratio": 0.7}).json()
    assert r["comparability"]["comparable"] is False
    client.post("/api/scan", files={"image": ("c.jpg", jpg((120, 60, 30)), "image/jpeg")},
                data={"actions": "redness", "trial_id": t["id"], "phase": "checkin", "face_ratio": 0.7})
    ev = client.get(f"/api/trials/{t['id']}/evidence").json()
    assert ev["report"]["verdict"] == "cant_tell_not_comparable"

    client.post(f"/api/trials/{t['id']}/checkin", json={"symptoms": ["itching"]})
    ev = client.get(f"/api/trials/{t['id']}/evidence").json()
    assert ev["report"]["verdict"] == "stop_reaction"


def test_low_resolution_rejected_before_api_call(client):
    b = io.BytesIO()
    Image.new("RGB", (300, 400)).save(b, "JPEG")
    r = client.post("/api/scan", files={"image": ("s.jpg", b.getvalue(), "image/jpeg")}, data={"actions": "redness"})
    assert r.status_code == 422 and "480" in r.json()["detail"]


def test_ui_read_endpoints(client):
    client.put("/api/shelf", json={"product_ids": ["cl-01", "mo-01"]})
    t = client.post("/api/trials", json={"goal_concern": "redness", "product_id": "mo-03"}).json()
    for phase in ("baseline", "baseline", "checkin"):
        client.post("/api/scan", files={"image": ("a.jpg", jpg(), "image/jpeg")},
                    data={"actions": "redness", "trial_id": t["id"], "phase": phase, "face_ratio": 0.7})
    client.post(f"/api/trials/{t['id']}/checkin", json={"symptoms": ["dryness"], "other_new_leave_on": ["sr-01"]})
    assert [x["id"] for x in client.get("/api/trials").json()] == [t["id"]]
    assert client.get(f"/api/trials/{t['id']}").json()["goal_concern"] == "redness"
    ev = client.get(f"/api/trials/{t['id']}/evidence").json()
    assert len(ev["captures"]["baseline"]) == 2 and len(ev["captures"]["followup"]) == 1
    assert "result" not in ev["captures"]["baseline"][0]
    kinds = [e["kind"] for e in ev["timeline"]]
    assert kinds[0] == "start" and "checkin_log" in kinds
    assert ev["product"]["id"] == "mo-03"
    m = client.get("/api/meta").json()
    assert "itching" in m["stop_symptoms"] and "stop_reaction" in m["verdict_text"]
    assert client.post("/api/demo/reset").status_code == 403


# ---------------------------------------------------------------- reactions persist until resolved
def _matched_trial(client):
    """Trial with 2 baseline + 2 check-in scans under the same light (overlapping ranges)."""
    t = client.post("/api/trials", json={"goal_concern": "redness", "product_id": "mo-03"}).json()
    for phase in ("baseline", "baseline", "checkin", "checkin"):
        client.post("/api/scan", files={"image": ("a.jpg", jpg(), "image/jpeg")},
                    data={"actions": "redness", "trial_id": t["id"], "phase": phase, "face_ratio": 0.7})
    return t


def _ev(client, tid):
    return client.get(f"/api/trials/{tid}/evidence").json()


def test_stop_symptom_stays_until_resolved(client):
    t = _matched_trial(client)
    assert _ev(client, t["id"])["report"]["verdict"] == "no_detectable_change"

    client.post(f"/api/trials/{t['id']}/checkin", json={"symptoms": ["itching"]})     # day 14
    assert _ev(client, t["id"])["report"]["verdict"] == "stop_reaction"
    client.post(f"/api/trials/{t['id']}/checkin", json={"symptoms": []})              # day 28
    ev = _ev(client, t["id"])
    assert ev["report"]["verdict"] == "stop_reaction"
    [r] = ev["reactions"]
    assert r["symptom"] == "itching" and r["resolved"] is False and r["logged_at"]

    res = client.post(f"/api/trials/{t['id']}/reactions/{r['id']}/resolve",
                      json={"note": "Settled after pausing"})
    assert res.status_code == 200
    ev = _ev(client, t["id"])
    assert ev["report"]["verdict"] == "no_detectable_change"     # normal logic applies again
    [r] = ev["reactions"]                                         # still on record
    assert r["resolved"] is True and r["resolution_note"] == "Settled after pausing" and r["resolved_on"]
    assert any(e["kind"] == "reaction_resolved" for e in ev["timeline"])


def test_resolve_errors(client):
    t = _matched_trial(client)
    client.post(f"/api/trials/{t['id']}/checkin", json={"symptoms": ["burning"]})
    [r] = _ev(client, t["id"])["reactions"]
    url = f"/api/trials/{t['id']}/reactions/{r['id']}/resolve"
    assert client.post(f"/api/trials/{t['id']}/reactions/nope/resolve", json={}).status_code == 404
    assert client.post(f"/api/trials/missing/reactions/{r['id']}/resolve", json={}).status_code == 404
    assert client.post(url, json={"resolved_on": "2001-01-01"}).status_code == 422   # before it was logged
    assert client.post(url, json={"resolved_on": "2999-01-01"}).status_code == 422   # in the future
    assert client.post(url, json={}).status_code == 200
    assert client.post(url, json={}).status_code == 409                              # already resolved


def test_mild_symptoms_never_create_reactions(client):
    t = _matched_trial(client)
    client.post(f"/api/trials/{t['id']}/checkin", json={"symptoms": ["dryness"]})
    ev = _ev(client, t["id"])
    assert ev["reactions"] == [] and ev["report"]["verdict"] == "no_detectable_change"


def test_same_episode_then_recurrence(client):
    t = _matched_trial(client)
    tid = t["id"]
    client.post(f"/api/trials/{tid}/checkin", json={"symptoms": ["itching"]})
    client.post(f"/api/trials/{tid}/checkin", json={"symptoms": ["Itching"]})   # still the same episode
    [r] = _ev(client, tid)["reactions"]
    client.post(f"/api/trials/{tid}/reactions/{r['id']}/resolve", json={})
    assert _ev(client, tid)["report"]["verdict"] == "no_detectable_change"

    client.post(f"/api/trials/{tid}/checkin", json={"symptoms": ["itching"]})   # comes back after resolving
    ev = _ev(client, tid)
    assert ev["report"]["verdict"] == "stop_reaction"
    assert [x["resolved"] for x in ev["reactions"]] == [True, False]


def test_delete_my_photos_removes_captures_and_masks(client, tmp_path):
    import app.main as m
    t = _matched_trial(client)
    caps = m.all_("captures")
    assert len(caps) == 4
    mask_dir = m.MEDIA_DIR / caps[0]["id"]
    mask_dir.mkdir(parents=True, exist_ok=True)
    (mask_dir / "redness_0.png").write_bytes(b"x")
    keep = m.MEDIA_DIR.parent / "keep.txt"          # nothing outside capture folders is touched
    keep.write_text("x")

    r = client.delete("/api/captures").json()
    assert r["deleted"] == 4
    assert m.all_("captures") == [] and not mask_dir.exists() and keep.exists()
    assert m.MEDIA_DIR.exists()
    ev = _ev(client, t["id"])
    assert ev["captures"]["baseline"] == [] and ev["report"]["verdict"] == "cant_tell_no_baseline"


def test_evidence_series_gates_each_checkin(client):
    t = client.post("/api/trials", json={"goal_concern": "redness", "product_id": "mo-03"}).json()
    for phase, color in (("baseline", None), ("baseline", None), ("checkin", None), ("checkin", (120, 60, 30))):
        client.post("/api/scan", files={"image": ("a.jpg", jpg(color) if color else jpg(), "image/jpeg")},
                    data={"actions": "redness", "trial_id": t["id"], "phase": phase, "face_ratio": 0.7})
    ev = _ev(client, t["id"])
    assert [s["comparable"] for s in ev["series"]] == [None, None, True, False]
    assert [s["phase"] for s in ev["series"]] == ["baseline", "baseline", "checkin", "checkin"]
    assert set(ev["baseline_ranges"]["redness"]) >= {"lo", "hi", "n"}
    r = client.post("/api/scan", files={"image": ("b.jpg", jpg((120, 60, 30)), "image/jpeg")},
                    data={"actions": "redness", "trial_id": t["id"], "phase": "checkin", "face_ratio": 0.7}).json()
    assert r["comparability"]["failed"][0]["field"] == "lighting"
    assert "lighting" in r["comparability"]["checked"]
