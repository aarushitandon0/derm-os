"""Privacy: YouCam task delete after each scan, "Delete my saved scans", and fixtures that
carry no URLs or images. No network: every HTTP call goes to a mock transport."""
import importlib
import io
import json
import sys
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.youcam import YouCamClient, YouCamError, delete_task_quietly, load_result, normalize

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import make_fixtures as MF  # noqa: E402

LIVE = {"X-Live-Passcode": "test-passcode"}  # live scans need it; see app/guard.py

def _png() -> bytes:
    from PIL import Image as _I
    b = io.BytesIO()
    _I.new("RGBA", (4, 4), (220, 40, 40, 128)).save(b, "PNG")
    return b.getvalue()


PNG = _png()   # a real image: stored masks are re-encoded from their pixels, so fake bytes aren't kept
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def jpg():
    b = io.BytesIO()
    Image.new("RGB", (720, 960), (200, 160, 140)).save(b, "JPEG")
    return b.getvalue()


@pytest.fixture()
def m(tmp_path, monkeypatch):
    monkeypatch.setenv("DERMOS_DB", str(tmp_path / "t.db"))
    monkeypatch.setenv("DERMOS_MEDIA", str(tmp_path / "media"))
    monkeypatch.setenv("DERMOS_FIXTURES", str(tmp_path / "fixtures"))
    import app.main as mod
    importlib.reload(mod)
    return mod


def scan(c):
    return c.post("/api/scan", files={"image": ("a.jpg", jpg(), "image/jpeg")}, data={"actions": "redness"})


def live_client(events, delete_exc=None, task_id="T1"):
    def handler(req):
        events.append("mask")
        return httpx.Response(200, content=PNG, headers={"content-type": "image/png"})

    class Live:
        upload_http = httpx.Client(transport=httpx.MockTransport(handler))

        def unit_balance(self):
            return 1000

        def analyze(self, path, actions):
            events.append("analyze")
            return normalize({"data": {"results": {"output": [
                {"type": "redness", "raw_score": 70, "mask_urls": ["https://s3.example/r.png?sig=SECRET"]}]}}},
                "sd", actions, task_id)

        def delete_task(self, tid):
            events.append(("delete", tid))
            if delete_exc:
                raise delete_exc
            return {"status": 200}
    return Live


# ---------------------------------------------------------------- client request shape
def test_delete_task_request_shape():
    seen = []

    def handler(req):
        seen.append((req.method, req.url.path, json.loads(req.content), req.headers.get("authorization")))
        return httpx.Response(200, json={"status": 200})
    c = YouCamClient(api_key="k", transport=httpx.MockTransport(handler))
    c.delete_task("T9")
    assert seen == [("POST", "/s2s/v2.0/task/delete", {"task_id": "T9"}, "Bearer k")]


def test_delete_quietly_logs_without_secrets(caplog):
    class Bad:
        def delete_task(self, tid):
            raise YouCamError("POST /s2s/v2.0/task/delete -> 400: {'url': 'https://s3/x.png?sig=S'}",
                              code="InvalidTaskId")
    assert delete_task_quietly(Bad(), "T1") is False
    assert "T1" in caplog.text and "InvalidTaskId" in caplog.text
    assert "https://" not in caplog.text and "sig=" not in caplog.text
    assert delete_task_quietly(Bad(), None) is False


# ---------------------------------------------------------------- scan
def test_delete_called_after_mask_download(m, monkeypatch):
    events = []
    monkeypatch.setattr(m, "YouCamClient", live_client(events))
    r = scan(TestClient(m.app, headers=LIVE))
    assert r.status_code == 200
    assert events == ["analyze", "mask", ("delete", "T1")]
    cap = r.json()["capture"]
    assert cap["youcam"] == {"task_id": "T1", "deleted": True, "cost_units": 9.0}   # built-in SD 1-4 concern price
    assert cap["masks"]["redness"]          # the local mask copy survives the remote delete
    stored = json.dumps(m.get("captures", cap["id"]))
    assert "https://" not in stored and "SECRET" not in stored


def test_delete_failure_does_not_fail_the_scan(m, monkeypatch, caplog):
    events = []
    monkeypatch.setattr(m, "YouCamClient", live_client(events, delete_exc=httpx.ConnectError("down")))
    r = scan(TestClient(m.app, headers=LIVE))
    assert r.status_code == 200
    assert r.json()["capture"]["youcam"] == {"task_id": "T1", "deleted": False, "cost_units": 9.0}   # built-in SD 1-4 concern price
    assert r.json()["capture"]["raw_scores"]["redness"] == 70
    assert "delete failed" in caplog.text and "SECRET" not in caplog.text


def test_demo_mode_never_calls_youcam_delete(m, tmp_path, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "1")
    d = tmp_path / "fixtures" / "riya" / "baseline"
    d.mkdir(parents=True)
    (d / "b1.json").write_text(json.dumps({"meta": {"mode": "sd", "actions": ["redness"]}, "response": {
        "data": {"results": {"output": [{"type": "redness", "raw_score": 60}]}}}}))

    def boom(*a, **k):
        raise AssertionError("no YouCam client in demo mode")
    monkeypatch.setattr(m, "YouCamClient", boom)
    cap = scan(TestClient(m.app, headers=LIVE)).json()["capture"]
    assert cap["youcam"] is None and cap["source"] == "replay"


# ---------------------------------------------------------------- delete my saved scans
def test_delete_saved_scans_rerequests_only_unconfirmed_live_tasks(m, monkeypatch):
    events = []
    c = TestClient(m.app, headers=LIVE)
    monkeypatch.setattr(m, "YouCamClient", live_client(events, task_id="OK1"))
    scan(c)
    monkeypatch.setattr(m, "YouCamClient", live_client(events, delete_exc=YouCamError("x", code="e"), task_id="BAD1"))
    scan(c)
    # A replayed capture has no YouCam task of its own.
    m.put("captures", {"phase": "free", "source": "replay", "result": {"task_id": "synthetic-1"}, "raw_scores": {}})
    events.clear()
    monkeypatch.setattr(m, "YouCamClient", live_client(events))
    r = c.delete("/api/captures").json()
    assert r["deleted"] == 3
    assert r["youcam"] == {"already_deleted": 1, "requested": 1, "deleted": 1, "failed": 0, "skipped_reason": None}
    assert events == [("delete", "BAD1")]
    assert m.all_("captures") == []
    assert not any(Path(m.MEDIA_DIR).iterdir())


def test_delete_saved_scans_without_key_still_deletes_locally(m, monkeypatch):
    events = []
    c = TestClient(m.app, headers=LIVE)
    monkeypatch.setattr(m, "YouCamClient", live_client(events, delete_exc=RuntimeError("x")))
    scan(c)

    def nokey():
        raise YouCamError("YOUCAM_API_KEY is not set", code="no_key")
    monkeypatch.setattr(m, "YouCamClient", nokey)
    r = c.delete("/api/captures").json()
    assert r["deleted"] == 1 and r["youcam"]["skipped_reason"] == "no_key" and r["youcam"]["requested"] == 1
    assert m.all_("captures") == []


# ---------------------------------------------------------------- fixtures
def _write_result(path: Path, hd=False):
    if hd:
        resp = {"hd_redness": {"raw_score": 72.0, "ui_score": 77, "output_mask_name": "hd_redness_output.png"},
                "hd_pore": {"whole": {"raw_score": 49.2, "ui_score": 67}, "nose": {"raw_score": 29.1}},
                "all": {"score": 75.7}, "skin_age": 30}
        meta = {"mode": "hd", "actions": ["hd_redness", "hd_pore"], "task_id": "T-secret", "api_version": "v2.1"}
    else:
        resp = {"status": 200, "data": {"task_status": "success", "results": {"output": [
            {"type": "redness", "raw_score": 61.2, "ui_score": 75,
             "mask_urls": ["https://yce.example/m/redness.png?X-Amz-Signature=abc"]},
            {"type": "pore", "raw_score": 55.0, "ui_score": 71, "mask_urls": ["https://yce.example/p.jpg"],
             "extra_field": "https://unexpected.example/x"}]}}}
        meta = {"mode": "sd", "actions": ["redness", "pore"], "task_id": "T-secret"}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"meta": meta, "response": resp}))


@pytest.mark.parametrize("hd", [False, True])
def test_fixture_keeps_scores_actions_engine_fingerprint_only(tmp_path, hd):
    res = tmp_path / "results" / "window_1.json"
    _write_result(res, hd)
    photos = tmp_path / "photos"
    photos.mkdir()
    Image.new("RGB", (720, 960), (190, 150, 130)).save(photos / "window_1.jpg")
    blob = MF.build_fixture(res, photos)
    text = json.dumps(blob)
    assert MF.leaks(blob) == []
    for bad in ("http", "://", ".png", ".jpg", "mask", "T-secret", "unexpected"):
        assert bad not in text, bad
    assert set(blob["meta"]) == {"mode", "actions", "engine", "fingerprint", "recorded_from", "synthetic"}
    assert blob["meta"]["engine"] == "YouCam skin-analysis v2.1"
    assert blob["meta"]["fingerprint"]["width"] == 720 and "luminance" in blob["meta"]["fingerprint"]
    # Still replays to the same scores.
    out = tmp_path / "fx.json"
    out.write_text(text)
    assert load_result(out).raw_scores()["redness"] == (72.0 if hd else 61.2)


def test_fixture_script_never_copies_mask_images(tmp_path, monkeypatch):
    results = tmp_path / "results"
    for st in ("window_1", "window_2", "window_3", "lamp_1"):
        _write_result(results / f"{st}.json")
        (results / "media" / st).mkdir(parents=True)
        (results / "media" / st / "redness_0.png").write_bytes(PNG)
    fx = tmp_path / "fixtures"
    monkeypatch.setattr(sys, "argv", ["make_fixtures.py", "--results", str(results), "--fixtures", str(fx),
                                      "--photos", str(tmp_path / "nophotos")])
    assert MF.main() == 0
    files = [p for p in fx.rglob("*") if p.is_file()]
    assert files and all(p.suffix == ".json" for p in files)
    assert not any(p.is_dir() and p.name.endswith(".masks") for p in fx.rglob("*"))
    for p in files:
        assert MF.leaks(json.loads(p.read_text(encoding="utf-8"))) == []


def test_committed_fixtures_have_no_urls_or_images():
    files = [p for p in FIXTURES.rglob("*") if p.is_file()]
    assert files
    assert all(p.suffix == ".json" for p in files), "only JSON belongs in committed fixtures"
    for p in files:
        assert MF.leaks(json.loads(p.read_text(encoding="utf-8"))) == [], p.name
