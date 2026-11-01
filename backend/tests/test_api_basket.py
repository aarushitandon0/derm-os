"""The basket endpoints over the API. YouCam is faked: no network and no units, ever."""
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.demo_faces import DEMO_FACES

LIVE = {"X-Live-Passcode": "test-passcode"}


class FakeYouCam:
    version = "v2.1"
    upload_http = None

    def __init__(self, balance=992.0):
        self.calls = []
        self.balance = balance

    def unit_balance(self):
        self.calls.append("balance")
        return self.balance

    def scan_cost(self, actions):
        return 12.0, "price list"

    def feature_cost(self, feature):
        return {"skin-tone-analysis": 20.0, "makeup-vto": 1.0}[feature], "price list"

    def analyze(self, path, actions):
        from app.youcam import normalize
        self.calls.append(("analyze", tuple(actions)))
        return normalize(DEMO_FACES["riya"]["skin"], "sd", actions, "S1")

    def skin_tone(self, path):
        from app.youcam import normalize_tone
        self.calls.append("tone")
        return normalize_tone(DEMO_FACES["riya"]["tone"], "T1")

    def makeup_vto(self, effects, image_path=None):
        from app.youcam import VtoResult
        self.calls.append(("vto", effects[0]["palettes"][0]["glowIntensity"]))
        return VtoResult(f"V{len(self.calls)}", "https://cdn.example/render.jpg", {})

    def delete_task(self, task_id):
        self.calls.append(("delete", task_id))
        return {}


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DERMOS_DB", str(tmp_path / "t.db"))
    monkeypatch.setenv("DERMOS_MEDIA", str(tmp_path / "media"))
    import importlib
    import app.main as m
    importlib.reload(m)
    fake = FakeYouCam()
    monkeypatch.setattr(m, "YouCamClient", lambda: fake)

    def fake_download(url, dest, http=None):
        dest.parent.mkdir(parents=True, exist_ok=True)
        out = dest.with_suffix(".png")
        out.write_bytes(b"png")
        return out

    monkeypatch.setattr(m, "download_render", fake_download)
    return m, fake


def jpg():
    b = io.BytesIO()
    Image.new("RGB", (720, 960), (200, 160, 140)).save(b, "JPEG")
    return b.getvalue()


def test_demo_basket_for_riya_after_her_scene(env):
    m, fake = env
    m.build_scene("riya-basket")
    c = TestClient(m.app)
    r = c.post("/api/basket", json={"persona": "riya", "answers": {"finish": "dewy"}})
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["source"] == "replay" and b["demo_label"] == "Demo data" and b["face_map"]["demo"] is True
    assert [j["title"] for j in b["jobs"]] == ["Cleanser", "T-zone moisturiser", "Cheek moisturiser",
                                               "Sunscreen / skin tint"]
    assert {s["product_id"] for s in b["skipped"]} >= {"tt-01", "mo-07", "mo-13"}
    assert b["tryon"]["line"] == "Preview appears on a live scan"
    assert fake.calls == []                                   # no YouCam call at all
    stored = m.all_("baskets")
    assert stored and stored[-1]["basket"]["inputs"]["rule_versions"]["basket"] == "basket-1.0"


def test_questions_report_what_is_on_record(env):
    m, _ = env
    m.build_scene("riya-basket")
    q = TestClient(m.app).get("/api/basket/questions").json()
    assert [x["id"] for x in q["questions"]] == ["finish", "history", "budget"]
    assert q["on_record"] == {"records": 2, "outcomes": 5, "bothered": 3}


def test_scan_without_passcode_replays_and_never_calls_youcam(env):
    m, fake = env
    r = TestClient(m.app).post("/api/basket/scan", files={"image": ("s.jpg", jpg(), "image/jpeg")},
                               data={"answers": '{"finish": "matte"}'})
    assert r.status_code == 200, r.text
    assert r.json()["source"] == "replay" and fake.calls == []
    assert r.json()["inputs"]["finish"] == "matte"


def test_bad_answers_are_refused(env):
    m, _ = env
    r = TestClient(m.app).post("/api/basket/scan", data={"answers": "[1, 2]"})
    assert r.status_code == 422


def test_live_run_chains_analysis_tone_and_two_renders_then_deletes(env):
    m, fake = env
    r = TestClient(m.app, headers=LIVE).post("/api/basket/scan",
                                              files={"image": ("s.jpg", jpg(), "image/jpeg")},
                                              data={"answers": '{"finish": "dewy"}'})
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["source"] == "live" and b["face_map"]["demo"] is False
    analyses = [c for c in fake.calls if isinstance(c, tuple) and c[0] == "analyze"]
    assert analyses == [("analyze", ("skin_type", "oiliness", "moisture", "pore", "acne", "redness",
                                     "radiance", "texture"))]
    assert "tone" in fake.calls
    assert [c[1] for c in fake.calls if isinstance(c, tuple) and c[0] == "vto"] == [0, 70]
    deletes = [c[1] for c in fake.calls if isinstance(c, tuple) and c[0] == "delete"]
    assert deletes[:2] == ["S1", "T1"] and len(deletes) == 4
    assert b["tryon"]["status"] == "ready" and all(lk["image"] for lk in b["tryon"]["looks"])
    assert m.units_spent()["total"] == 34.0                     # 12 + 20 + 2 x 1
    stored = m.all_("baskets")
    assert len(stored) == 1 and stored[0]["youcam"]["cost_units"] == 34.0


def test_live_run_below_the_floor_replays_and_sends_nothing(env, monkeypatch):
    m, fake = env
    fake.balance = 210.0                                        # 210 - 34 < 200 reserve
    r = TestClient(m.app, headers=LIVE).post("/api/basket/scan",
                                              files={"image": ("s.jpg", jpg(), "image/jpeg")})
    assert r.status_code == 200
    assert r.json()["source"] == "replay" and "Nothing was sent to YouCam" in r.json()["notice"]
    assert fake.calls == ["balance"] and m.units_spent()["total"] == 0.0


def test_meta_lists_the_new_rule_versions(env):
    m, _ = env
    rules = TestClient(m.app).get("/api/meta").json()["engine_rules"]
    assert {"basket-1.0", "needs-1.0", "undertone-1.0"} <= set(rules)
