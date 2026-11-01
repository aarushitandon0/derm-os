"""Demo personas over the API: riya's chips, and a beginner who starts from a CLEARED history.
Demo mode only; YouCam is never constructed."""
import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def m(tmp_path, monkeypatch):
    monkeypatch.setenv("DERMOS_DB", str(tmp_path / "t.db"))
    monkeypatch.setenv("DERMOS_MEDIA", str(tmp_path / "media"))
    monkeypatch.setenv("DEMO_MODE", "1")
    import app.main as main
    importlib.reload(main)
    monkeypatch.setattr(main, "YouCamClient", lambda: pytest.fail("YouCam must not be called"))
    return main


def test_beginner_after_riya_has_no_leftover_history(m):
    c = TestClient(m.app)
    assert c.post("/api/demo/scene/riya-basket").status_code == 200
    assert m.all_("history")                                  # riya's records are there first
    assert c.post("/api/demo/scene/beginner").status_code == 200
    assert m.all_("history") == [] and c.get("/api/chips").json()["chips"] == []
    b = c.post("/api/basket", json={"persona": "beginner", "answers": {}}).json()
    assert b["beginner"] is True
    assert all(s["kind"] not in ("history", "tried") for s in b["skipped"])
    lines = [l for j in b["jobs"] for l in j["look_for"]["lines"]]
    assert not [l for l in lines if l.startswith("Avoid:")], lines
    assert all(j["label"] == "Gentle start for new routines" for j in b["jobs"])
    assert b["start_plan"]["steps"]


def test_riya_scene_brings_her_chips_and_purge_offer(m):
    c = TestClient(m.app)
    c.post("/api/demo/scene/riya-basket")
    b = c.post("/api/basket", json={"persona": "riya", "answers": {"finish": "dewy"}}).json()
    kinds = {s["product_id"]: s["kind"] for s in b["skipped"]}
    assert kinds["mo-17"] == "tried" and kinds["mo-18"] == "tried" and kinds["tt-01"] == "history"
    pq = b["tried"]["purge_questions"]
    assert len(pq) == 1 and pq[0]["purge_offer"] and pq[0]["purge_choice"] is None
