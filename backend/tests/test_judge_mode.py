"""Judge-ready deploy: DEMO_MODE on by default, unit caps for live judge scans (counted in the
database) with a fall back to prepared data, /health without YouCam, guided-demo scenes, and
the session defaults. No network: YouCam is a fake that counts calls."""
import importlib
import io
import json

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import guard as G
from app.youcam import normalize

LIVE = {"X-Live-Passcode": "test-passcode"}


def jpg():
    b = io.BytesIO()
    Image.new("RGB", (720, 960), (200, 160, 140)).save(b, "JPEG")
    return b.getvalue()


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DERMOS_DB", str(tmp_path / "t.db"))
    monkeypatch.setenv("DERMOS_MEDIA", str(tmp_path / "media"))
    monkeypatch.setenv("DERMOS_FIXTURES", str(tmp_path / "fixtures"))
    monkeypatch.setenv("SCAN_RATE_LIMIT", "0")
    d = tmp_path / "fixtures" / "riya" / "baseline"
    d.mkdir(parents=True)
    (d / "b1.json").write_text(json.dumps({"meta": {"mode": "sd", "actions": ["redness"], "synthetic": True},
                                           "response": {"data": {"results": {"output": [
                                               {"type": "redness", "raw_score": 55}]}}}}))
    return monkeypatch


class Fake:
    """Counts analyze() calls. Balance high, so only the caps can stop a scan."""
    calls: list = []

    def __init__(self, balance=5000, fail=False):
        self.balance, self.fail = balance, fail

    def unit_balance(self):
        return self.balance

    def analyze(self, path, actions):
        Fake.calls.append(actions)
        if self.fail:
            from app.youcam import YouCamError
            raise YouCamError("boom", code="timeout")
        return normalize({"data": {"results": {"output": [{"type": a, "raw_score": 70} for a in actions]}}},
                         "sd", actions, "T")

    def delete_task(self, tid):
        return {}


def load(monkeypatch, **fake_kw):
    import app.main as m
    importlib.reload(m)
    Fake.calls = []
    monkeypatch.setattr(m, "YouCamClient", lambda: Fake(**fake_kw))
    return m


def scan(c, actions="redness,acne,texture,pore", headers=LIVE):
    return c.post("/api/scan", files={"image": ("a.jpg", jpg(), "image/jpeg")}, data={"actions": actions},
                  headers=headers)


# ---------------------------------------------------------------- defaults
def test_demo_mode_is_on_unless_explicitly_zero(monkeypatch):
    monkeypatch.delenv("DEMO_MODE", raising=False)
    assert G.demo_mode() is True
    monkeypatch.setenv("DEMO_MODE", "0")
    assert G.demo_mode() is False


def test_default_concerns_reserve_and_caps(env):
    m = load(env)
    assert m.DEFAULT_ACTIONS == ("redness", "acne", "texture", "pore")
    env.delenv("YOUCAM_UNIT_RESERVE", raising=False)
    assert m.unit_reserve() == 200
    env.delenv("JUDGE_UNIT_CAP_TOTAL", raising=False)
    env.delenv("JUDGE_UNIT_CAP_DAILY", raising=False)
    assert G.judge_caps() == (300, 100)
    # A scan with no actions given uses the 4 default concerns (SD, 9 units).
    c = TestClient(m.app)
    r = c.post("/api/scan", files={"image": ("a.jpg", jpg(), "image/jpeg")}, headers=LIVE)
    assert r.status_code == 200 and Fake.calls == [["redness", "acne", "texture", "pore"]]
    assert r.json()["capture"]["youcam"]["cost_units"] == 9


# ---------------------------------------------------------------- caps
def test_daily_cap_falls_back_to_prepared_data_with_a_plain_message(env):
    env.setenv("JUDGE_UNIT_CAP_DAILY", "18")       # room for two 9-unit scans
    m = load(env)
    c = TestClient(m.app)
    first, second, third = (scan(c).json() for _ in range(3))
    assert first["capture"]["source"] == "live" and second["capture"]["source"] == "live"
    assert third["capture"]["source"] == "replay" and third["capture"]["replay"]["reason"] == "judge_cap_daily"
    assert "today's 18 YouCam units" in third["notice"] and "prepared demo data" in third["notice"]
    assert "Nothing was sent to YouCam" in third["notice"]
    assert len(Fake.calls) == 2                       # the third scan never reached YouCam
    assert first["notice"] is None


def test_total_cap_falls_back_and_is_counted_in_the_database(env):
    env.setenv("JUDGE_UNIT_CAP_TOTAL", "9")
    m = load(env)
    c = TestClient(m.app)
    assert scan(c).json()["capture"]["source"] == "live"
    r = scan(c).json()
    assert r["capture"]["replay"]["reason"] == "judge_cap_total" and "this demo's 9 YouCam units" in r["notice"]
    assert m.units_spent() == {"total": 9.0, "today": 9.0}
    # Counted in the database, not in memory: a reloaded app (same DB) still sees the spend.
    m2 = load(env)
    assert m2.units_spent()["total"] == 9.0
    assert scan(TestClient(m2.app)).json()["capture"]["source"] == "replay" and Fake.calls == []
    h = TestClient(m2.app).get("/api/health").json()["judge_caps"]
    assert h == {"total": 9.0, "daily": 100.0, "spent": {"total": 9.0, "today": 9.0}}


def test_failed_live_scan_does_not_count_against_the_caps(env):
    env.setenv("JUDGE_UNIT_CAP_TOTAL", "9")
    m = load(env, fail=True)
    c = TestClient(m.app)
    assert scan(c).status_code == 502
    assert m.units_spent()["total"] == 0.0


def test_a_scan_bigger_than_the_cap_is_never_sent(env):
    env.setenv("JUDGE_UNIT_CAP_DAILY", "10")
    m = load(env)
    r = scan(TestClient(m.app), actions="redness,acne,texture,pore,oiliness").json()   # 5 concerns: 12 units
    assert r["capture"]["source"] == "replay" and Fake.calls == []


def test_reserve_still_applies_under_the_caps(env):
    env.setenv("YOUCAM_UNIT_RESERVE", "200")
    env.setenv("LIVE_SCAN_MIN_BALANCE", "0")          # floor lets it through; the reserve still refuses
    m = load(env, balance=205)                       # 205 - 9 < 200
    r = scan(TestClient(m.app))
    assert r.status_code == 402 and Fake.calls == [] and m.units_spent()["total"] == 0.0


def test_rate_limit_still_applies(env):
    env.setenv("SCAN_RATE_LIMIT", "1/600")
    m = load(env)
    c = TestClient(m.app)
    assert [scan(c).status_code for _ in range(2)] == [200, 429]


def test_demo_mode_replays_and_never_counts(env):
    env.setenv("DEMO_MODE", "1")
    m = load(env)
    r = scan(TestClient(m.app)).json()
    assert r["capture"]["source"] == "replay" and Fake.calls == [] and m.units_spent()["total"] == 0.0


# ---------------------------------------------------------------- health
def test_health_never_calls_youcam(env):
    import app.main as m
    importlib.reload(m)

    def boom(*a, **k):
        raise AssertionError("health must not touch YouCam")
    env.setattr(m, "YouCamClient", boom)
    c = TestClient(m.app)
    assert c.get("/health").json() == {"ok": True}
    assert c.get("/api/health").status_code == 200


# ---------------------------------------------------------------- guided-demo scenes
def test_scenes_only_in_demo_mode(env):
    env.delenv("DERMOS_FIXTURES")                 # the real committed fixtures
    m = load(env)
    c = TestClient(m.app)
    assert c.post("/api/demo/scene/meera").status_code == 403
    env.setenv("DEMO_MODE", "1")
    assert c.post("/api/demo/scene/nobody").status_code == 404
    r = c.post("/api/demo/scene/meera").json()
    assert r["trial_id"] == "demo-meera"
    ev = c.get("/api/trials/demo-meera/evidence").json()
    assert ev["report"]["verdict"] == "moved_beyond_noise" and all(s["source"] == "replay" for s in ev["series"])
    assert all(s["replay"]["synthetic"] for s in ev["series"])
    # Rebuilding a scene replaces only its own scans.
    c.post("/api/demo/scene/meera")
    assert len(c.get("/api/trials/demo-meera/evidence").json()["series"]) == 5


def test_riya_scenes_tell_the_hero_story(env):
    env.delenv("DERMOS_FIXTURES")
    env.setenv("DEMO_MODE", "1")
    m = load(env)
    c = TestClient(m.app)
    verdicts = {}
    for name in ("riya-trial", "riya-lamp", "riya-day14", "riya-stop"):
        tid = c.post(f"/api/demo/scene/{name}").json()["trial_id"]
        verdicts[name] = c.get(f"/api/trials/{tid}/evidence").json()["report"]["verdict"]
    assert verdicts == {"riya-trial": "cant_tell_no_baseline", "riya-lamp": "cant_tell_not_comparable",
                        "riya-day14": "no_detectable_change", "riya-stop": "stop_reaction"}
    hist = {(h["type"], h.get("product_id"), h.get("ingredient")) for h in c.get("/api/history").json()}
    assert hist == {("suspected_reaction", "mo-02", None), ("avoid", None, "fragrance")}
    # Option A (fragranced serum) is blocked with its label line; Option B's label is incomplete: unknown.
    cols = c.post("/api/compare", json={"options": [{"name": "A", "items": [{"product_id": "sr-02"}]},
                                                    {"name": "B", "items": [{"product_id": "mo-04"}]}]}).json()["columns"]
    a, b = cols[1]["checks"][0], cols[2]["checks"][0]
    assert a["status"] == "blocked" and a["matches"][0]["label_line"]
    assert b["status"] == "unknown"


# ---------------------------------------------------------------- privacy claims in the README
def test_uploaded_photo_and_its_crop_are_deleted_after_the_scan(env):
    import os
    m = load(env)
    removed = []
    real = os.unlink
    env.setattr(m.os, "unlink", lambda p: (removed.append(p), real(p)))
    assert scan(TestClient(m.app)).status_code == 200
    assert len(removed) == 2 and not any(os.path.exists(p) for p in removed)   # original + normalised copy


def test_stored_scans_never_keep_mask_urls(env):
    m = load(env)

    class WithMasks(Fake):
        def analyze(self, path, actions):
            return normalize({"data": {"results": {"output": [
                {"type": a, "raw_score": 70, "mask_urls": [f"https://signed.example/{a}.png"]} for a in actions]}}},
                "sd", actions, "T")
    env.setattr(m, "YouCamClient", lambda: WithMasks())
    env.setattr(m, "download_masks", lambda *a, **k: {})        # no network in tests
    c = TestClient(m.app)
    cap = scan(c).json()["capture"]
    stored = json.dumps(m.get("captures", cap["id"]))
    assert "signed.example" not in stored and "https://" not in stored


# ---------------------------------------------------------------- balance floor (LIVE_SCAN_MIN_BALANCE)
def test_balance_floor_blocks_and_survives_a_restart(env, tmp_path):
    env.setenv("LIVE_SCAN_MIN_BALANCE", "700")
    m = load(env, balance=705)                       # 705 - 9 < 700
    r = scan(TestClient(m.app)).json()
    assert r["capture"]["source"] == "replay" and r["capture"]["replay"]["reason"] == "balance_floor"
    assert Fake.calls == [] and "Nothing was sent to YouCam" in r["notice"]
    # A restart wipes the database counters; the floor reads the real balance, so it still holds.
    env.setenv("DERMOS_DB", str(tmp_path / "fresh.db"))
    m = load(env, balance=705)
    assert m.units_spent()["total"] == 0.0
    assert scan(TestClient(m.app)).json()["capture"]["source"] == "replay" and Fake.calls == []


def test_balance_floor_allows_a_scan_that_stays_above_it(env):
    env.setenv("LIVE_SCAN_MIN_BALANCE", "700")
    m = load(env, balance=709)                       # 709 - 9 = 700: not below the floor
    r = scan(TestClient(m.app)).json()
    assert r["capture"]["source"] == "live" and len(Fake.calls) == 1 and r["notice"] is None


def test_balance_read_failure_blocks_the_scan(env):
    env.setenv("LIVE_SCAN_MIN_BALANCE", "0")
    m = load(env)

    class NoBalance(Fake):
        def unit_balance(self):
            raise RuntimeError("credit endpoint down")
    env.setattr(m, "YouCamClient", lambda: NoBalance())
    r = scan(TestClient(m.app)).json()
    assert r["capture"]["source"] == "replay" and r["capture"]["replay"]["reason"] == "balance_unreadable"
    assert Fake.calls == []

    class NoNumber(Fake):
        def unit_balance(self):
            return None
    env.setattr(m, "YouCamClient", lambda: NoNumber())
    assert scan(TestClient(m.app)).json()["capture"]["source"] == "replay" and Fake.calls == []


def test_balance_floor_setting_fails_safe(monkeypatch):
    monkeypatch.delenv("LIVE_SCAN_MIN_BALANCE", raising=False)
    monkeypatch.setenv("YOUCAM_UNIT_RESERVE", "200")
    assert G.min_balance() == 200.0                 # unset: falls back to the reserve
    monkeypatch.setenv("LIVE_SCAN_MIN_BALANCE", "lots")
    assert G.min_balance() == float("inf")          # not a number: no live scans at all
    monkeypatch.setenv("LIVE_SCAN_MIN_BALANCE", "-5")
    assert G.min_balance() == float("inf")
    monkeypatch.setenv("LIVE_SCAN_MIN_BALANCE", "704")
    assert G.min_balance() == 704.0
