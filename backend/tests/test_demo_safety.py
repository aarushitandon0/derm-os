"""Demo safety: DEMO_MODE replay, the unit guard, and mask download. No network."""
import importlib
import io
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.youcam import (UnitReserveError, check_unit_reserve, download_masks, normalize,
                        parse_balance)

LIVE = {"X-Live-Passcode": "test-passcode"}  # live scans need it; see app/guard.py

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


def jpg(color=(200, 160, 140)):
    b = io.BytesIO()
    Image.new("RGB", (720, 960), color).save(b, "JPEG")
    return b.getvalue()


def write_fixture(root, persona, fset, name, redness, synthetic=False, mask=False):
    d = root / persona / fset
    d.mkdir(parents=True, exist_ok=True)
    blob = {"meta": {"mode": "sd", "actions": ["redness"], "task_id": name, "synthetic": synthetic},
            "response": {"data": {"task_status": "success", "results": {"output": [
                {"type": "redness", "raw_score": redness, "ui_score": 80, "mask_urls": []}]}}}}
    (d / f"{name}.json").write_text(json.dumps(blob))
    if mask:
        (d / f"{name}.masks").mkdir()
        (d / f"{name}.masks" / "redness_0.png").write_bytes(PNG)


@pytest.fixture()
def app_module(tmp_path, monkeypatch):
    monkeypatch.setenv("DERMOS_DB", str(tmp_path / "t.db"))
    monkeypatch.setenv("DERMOS_MEDIA", str(tmp_path / "media"))
    monkeypatch.setenv("DERMOS_FIXTURES", str(tmp_path / "fixtures"))
    import app.main as m
    importlib.reload(m)
    return m


def scan(client, **data):
    return client.post("/api/scan", files={"image": ("a.jpg", jpg(), "image/jpeg")},
                       data={"actions": "redness", **data})


# ---------------------------------------------------------------- DEMO_MODE
def test_demo_mode_replays_fixtures_in_rotation_without_calling_youcam(app_module, tmp_path, monkeypatch):
    m = app_module
    monkeypatch.setenv("DEMO_MODE", "1")
    fx = tmp_path / "fixtures"
    for i, v in enumerate([60.0, 62.0, 61.0], 1):
        write_fixture(fx, "riya", "baseline", f"b{i}", v, synthetic=True, mask=(i == 1))

    def boom(*a, **k):
        raise AssertionError("YouCam must not be called in DEMO_MODE")
    monkeypatch.setattr(m, "YouCamClient", boom)
    c = TestClient(m.app, headers=LIVE)

    caps = [scan(c, trial_id="t1", phase="baseline").json()["capture"] for _ in range(4)]
    assert [x["raw_scores"]["redness"] for x in caps] == [60.0, 62.0, 61.0, 60.0]
    assert all(x["source"] == "replay" and x["replay"]["synthetic"] for x in caps)
    # Fingerprint still comes from the real uploaded pixels.
    assert caps[0]["fingerprint"]["width"] == 720
    # Recorded masks are copied into media and served.
    url = caps[0]["masks"]["redness"][0]
    assert url.startswith("/media/") and c.get(url).content == PNG
    assert c.get("/api/health").json()["demo_mode"] is True


def test_demo_mode_explicit_set_and_missing_persona(app_module, tmp_path, monkeypatch):
    m = app_module
    monkeypatch.setenv("DEMO_MODE", "1")
    write_fixture(tmp_path / "fixtures", "riya", "lamp", "l1", 54.0)
    c = TestClient(m.app, headers=LIVE)
    r = scan(c, phase="checkin", trial_id="t", fixture_set="lamp").json()
    assert r["capture"]["raw_scores"]["redness"] == 54.0 and r["capture"]["replay"]["set"] == "lamp"

    r = scan(c, phase="baseline", persona="nobody")
    assert r.status_code == 503 and "No recorded scans" in r.json()["detail"]
    assert scan(c, phase="baseline", persona="../etc").status_code == 503


def test_live_mode_with_passcode(app_module, monkeypatch):
    m = app_module
    called = []

    class Fake:
        def unit_balance(self):
            return 5000

        def analyze(self, path, actions):
            called.append(actions)
            return normalize({"data": {"results": {"output": [
                {"type": "redness", "raw_score": 70, "ui_score": 80}]}}}, "sd", actions, "T")

    monkeypatch.setattr(m, "YouCamClient", lambda: Fake())
    r = scan(TestClient(m.app, headers=LIVE)).json()
    assert called and r["capture"]["source"] == "live" and r["capture"]["replay"] is None


# ---------------------------------------------------------------- unit guard
@pytest.mark.parametrize("body,expected", [
    ({"status": 200, "data": {"amount": 420}}, 420),
    ({"result": [{"amount": 300}, {"amount": 200}]}, 500),
    ({"data": {"credit": {"remaining": "75"}}}, 75),
    ({"data": {"something": "else"}}, None),
    ("not json", None),
])
def test_parse_balance_tolerates_shapes(body, expected):
    assert parse_balance(body) == expected


class Bal:
    def __init__(self, value=None, exc=None):
        self.value, self.exc = value, exc

    def unit_balance(self):
        if self.exc:
            raise self.exc
        return self.value


def test_guard_refuses_below_reserve():
    with pytest.raises(UnitReserveError) as e:
        check_unit_reserve(Bal(40), 100)
    assert "40" in e.value.friendly and "100" in e.value.friendly and "DEMO_MODE" in e.value.friendly
    assert check_unit_reserve(Bal(100), 100) == 100


def test_guard_failure_is_logged_and_scan_continues(caplog):
    assert check_unit_reserve(Bal(exc=httpx.ConnectError("down")), 100) is None
    assert check_unit_reserve(Bal(None), 100) is None
    assert "continuing" in caplog.text


def test_scan_blocked_by_guard_never_calls_analyze(app_module, monkeypatch):
    m = app_module
    monkeypatch.setenv("YOUCAM_UNIT_RESERVE", "150")

    class Low(Bal):
        def analyze(self, *a):
            raise AssertionError("must not spend units below reserve")
    monkeypatch.setattr(m, "YouCamClient", lambda: Low(120))
    r = scan(TestClient(m.app, headers=LIVE))
    assert r.status_code == 402 and "150" in r.json()["detail"]


def test_scan_continues_when_credit_call_fails(app_module, monkeypatch):
    m = app_module

    class Flaky(Bal):
        def analyze(self, path, actions):
            return normalize({"data": {"results": {"output": [
                {"type": "redness", "raw_score": 70}]}}}, "sd", actions, "T")
    monkeypatch.setattr(m, "YouCamClient", lambda: Flaky(exc=RuntimeError("500")))
    assert scan(TestClient(m.app, headers=LIVE)).status_code == 200


# ---------------------------------------------------------------- masks
def _mask_transport(seen):
    def handler(req: httpx.Request):
        seen.append(dict(req.headers))
        if req.url.path.endswith("bad.png"):
            return httpx.Response(403)
        if req.url.path.endswith(".html"):
            return httpx.Response(200, content=b"<html>", headers={"content-type": "text/html"})
        return httpx.Response(200, content=PNG, headers={"content-type": "image/png"})
    return httpx.MockTransport(handler)


def test_download_masks_saves_files_and_skips_failures(tmp_path):
    res = normalize({"data": {"results": {"output": [
        {"type": "redness", "raw_score": 60, "mask_urls": ["https://s3.example/r.png", "https://s3.example/bad.png"]},
        {"type": "pore", "raw_score": 70, "mask_urls": ["https://s3.example/p.html", "file:///etc/passwd"]},
    ]}}}, "sd", ["redness", "pore"])
    seen = []
    saved = download_masks(res, tmp_path / "cap", httpx.Client(transport=_mask_transport(seen)))
    assert list(saved) == ["redness"] and saved["redness"][0].read_bytes() == PNG
    assert len(seen) == 3  # file:// never requested
    assert all("authorization" not in {k.lower() for k in h} for h in seen)


def test_live_scan_stores_local_mask_paths(app_module, monkeypatch):
    m = app_module
    seen = []

    class Live(Bal):
        upload_http = httpx.Client(transport=_mask_transport(seen))

        def analyze(self, path, actions):
            return normalize({"data": {"results": {"output": [
                {"type": "redness", "raw_score": 70, "mask_urls": ["https://s3.example/r.png"]}]}}},
                "sd", actions, "T")
    monkeypatch.setattr(m, "YouCamClient", lambda: Live(1000))
    c = TestClient(m.app, headers=LIVE)
    cap = scan(c).json()["capture"]
    url = cap["masks"]["redness"][0]
    assert url == f"/media/{cap['id']}/redness_0.png"
    assert c.get(url).content == PNG
