"""Deploy safety: live scans need DEMO_MODE=0 AND the passcode, per-IP scan rate limit,
CORS from env, and seeding an empty database. No network."""
import importlib
import io
import json

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.guard import RateLimiter, _parse_limit
from app.youcam import normalize


def jpg():
    b = io.BytesIO()
    Image.new("RGB", (720, 960), (200, 160, 140)).save(b, "JPEG")
    return b.getvalue()


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DERMOS_DB", str(tmp_path / "t.db"))
    monkeypatch.setenv("DERMOS_MEDIA", str(tmp_path / "media"))
    monkeypatch.setenv("DERMOS_FIXTURES", str(tmp_path / "fixtures"))
    d = tmp_path / "fixtures" / "riya" / "baseline"
    d.mkdir(parents=True)
    (d / "b1.json").write_text(json.dumps({"meta": {"mode": "sd", "actions": ["redness"], "synthetic": True},
                                           "response": {"data": {"results": {"output": [
                                               {"type": "redness", "raw_score": 55}]}}}}))
    return monkeypatch


def load(monkeypatch):
    import app.main as m
    importlib.reload(m)
    calls = []

    class Fake:
        def unit_balance(self):
            return 1000

        def analyze(self, path, actions):
            calls.append(actions)
            return normalize({"data": {"results": {"output": [{"type": "redness", "raw_score": 70}]}}},
                             "sd", actions, None)
    monkeypatch.setattr(m, "YouCamClient", lambda: Fake())
    return m, calls


def scan(c, **headers):
    return c.post("/api/scan", files={"image": ("a.jpg", jpg(), "image/jpeg")},
                  data={"actions": "redness"}, headers=headers)


# ---------------------------------------------------------------- live gate
def test_no_passcode_header_replays_fixtures(env):
    m, calls = load(env)
    cap = scan(TestClient(m.app)).json()["capture"]
    assert calls == [] and cap["source"] == "replay" and cap["replay"]["reason"] == "no_passcode"
    assert cap["raw_scores"]["redness"] == 55


def test_right_passcode_goes_live(env):
    m, calls = load(env)
    cap = scan(TestClient(m.app), **{"X-Live-Passcode": "test-passcode"}).json()["capture"]
    assert calls and cap["source"] == "live"


def test_wrong_passcode_is_refused_not_replayed(env):
    m, calls = load(env)
    r = scan(TestClient(m.app), **{"X-Live-Passcode": "nope"})
    assert r.status_code == 403 and calls == []


def test_demo_mode_replays_even_with_passcode(env):
    env.setenv("DEMO_MODE", "1")
    m, calls = load(env)
    cap = scan(TestClient(m.app), **{"X-Live-Passcode": "test-passcode"}).json()["capture"]
    assert calls == [] and cap["replay"]["reason"] == "demo_mode"


def test_live_disabled_when_no_passcode_configured(env):
    env.delenv("LIVE_SCAN_PASSCODE")
    m, calls = load(env)
    c = TestClient(m.app)
    assert scan(c, **{"X-Live-Passcode": "anything"}).status_code == 403
    assert scan(c).json()["capture"]["source"] == "replay" and calls == []
    assert c.get("/api/health").json()["live_scans"] == "disabled"


def test_health_reports_what_this_caller_gets(env):
    m, _ = load(env)
    c = TestClient(m.app)
    h = c.get("/api/health").json()
    assert h["demo_mode"] is True and h["server_demo_mode"] is False and h["live_scans"] == "passcode"
    assert h["passcode"] == "none"
    h = c.get("/api/health", headers={"X-Live-Passcode": "test-passcode"}).json()
    assert h["demo_mode"] is False and h["passcode"] == "ok"
    assert c.get("/api/health", headers={"X-Live-Passcode": "x"}).json()["passcode"] == "wrong"
    assert "test-passcode" not in json.dumps(h)


# ---------------------------------------------------------------- rate limit
def test_scan_rate_limit_per_ip(env):
    env.setenv("SCAN_RATE_LIMIT", "2/600")
    m, _ = load(env)
    c = TestClient(m.app)
    assert [scan(c).status_code for _ in range(3)] == [200, 200, 429]
    r = scan(c)
    assert r.status_code == 429 and int(r.headers["Retry-After"]) > 0


def test_limiter_window_and_keys():
    t = [0.0]
    rl = RateLimiter((2, 60), clock=lambda: t[0])
    rl.check("a")
    rl.check("a")
    with pytest.raises(Exception):
        rl.check("a")
    rl.check("b")              # another IP has its own budget
    t[0] = 61
    rl.check("a")              # window passed


@pytest.mark.parametrize("raw,expected", [(None, (30, 600.0)), ("5/60", (5, 60.0)), ("0", None),
                                          ("off", None), ("junk", (30, 600.0))])
def test_parse_limit(raw, expected):
    assert _parse_limit(raw) == expected


def test_trust_proxy_uses_last_forwarded_hop(env):
    env.setenv("SCAN_RATE_LIMIT", "1/600")
    env.setenv("TRUST_PROXY", "1")
    m, _ = load(env)
    c = TestClient(m.app)
    # A client can prepend fake hops; only the proxy-appended last hop counts.
    assert scan(c, **{"X-Forwarded-For": "1.1.1.1, 9.9.9.9"}).status_code == 200
    assert scan(c, **{"X-Forwarded-For": "2.2.2.2, 9.9.9.9"}).status_code == 429
    assert scan(c, **{"X-Forwarded-For": "8.8.8.8"}).status_code == 200


# ---------------------------------------------------------------- CORS
def test_cors_from_env(env):
    env.setenv("CORS_ORIGINS", "https://dermos.example.app, https://other.example/")
    m, _ = load(env)
    c = TestClient(m.app)
    pre = {"Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "x-live-passcode"}
    ok = c.options("/api/scan", headers={"Origin": "https://dermos.example.app", **pre})
    assert ok.headers.get("access-control-allow-origin") == "https://dermos.example.app"
    assert c.options("/api/scan", headers={"Origin": "https://other.example", **pre}).status_code == 200
    bad = c.options("/api/scan", headers={"Origin": "https://evil.example", **pre})
    assert "access-control-allow-origin" not in bad.headers


# ---------------------------------------------------------------- seeding
def test_seed_only_when_empty_and_enabled(env):
    m, _ = load(env)
    with TestClient(m.app) as c:              # startup ran, DERMOS_SEED unset: nothing seeded
        assert c.get("/api/shelf").json()["product_ids"] == []
    env.setenv("DERMOS_SEED", "1")
    with TestClient(m.app) as c:
        assert c.get("/api/shelf").json()["product_ids"] == ["cl-01", "sr-01", "mo-01", "sp-01"]
        c.post("/api/history", json={"type": "avoid", "ingredient": "fragrance"})
        c.put("/api/shelf", json={"product_ids": ["cl-01"]})
    assert m.seed_if_empty() == []            # existing data is never touched
    assert m.get_shelf()["product_ids"] == ["cl-01"]
