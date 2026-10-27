"""End-to-end API flow with YouCam mocked: history -> compare -> trial -> scans -> evidence."""
import io
import itertools

import pytest
from fastapi.testclient import TestClient
from PIL import Image


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DERMOS_DB", str(tmp_path / "t.db"))
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
    return TestClient(m.app)


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
