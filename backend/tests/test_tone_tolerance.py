"""Skin Tone tolerant of normal selfies: lenient strictness, tone before analysis, a free pose and
light precheck, plain error lines, and a full basket even when the tone check refuses the photo.
YouCam is faked throughout: no network and no units."""
import io
import json
import math

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import pose as PO
from app import undertone as U
from app import youcam as Y
from app.youcam import YouCamClient, YouCamError
from tests.test_api_basket import LIVE, FakeYouCam, jpg  # noqa: F401  (the shared fake)


# ---------------------------------------------------------------- 1. strictness
UPLOAD = {("POST", "/s2s/v2.0/file"): {"data": {"files": [{"file_id": "F1", "requests": [
    {"method": "PUT", "url": "https://upload.example/put", "headers": {"Content-Type": "image/jpeg"}}]}]}}}
OK_TONE = {"data": {"task_status": "success", "results": {"color": {"skin_color": "#b9947c"}}}}


def tone_client(seen, refuse=()):
    """A mocked YouCam whose tone endpoint answers 400 InvalidParameters for the levels in `refuse`."""
    def handler(req: httpx.Request):
        body = json.loads(req.content) if req.content and req.headers.get("content-type", "").startswith(
            "application/json") else None
        seen.append((req.method, req.url.path, body))
        if req.url.host == "upload.example":
            return httpx.Response(200)
        if (req.method, req.url.path) in UPLOAD:
            return httpx.Response(200, json=UPLOAD[(req.method, req.url.path)])
        if req.method == "POST" and req.url.path == "/s2s/v2.0/task/skin-tone-analysis":
            if body["face_angle_strictness_level"] in refuse:
                return httpx.Response(400, json={"status": 400, "error_code": "InvalidParameters"})
            return httpx.Response(200, json={"data": {"task_id": "T1"}})
        if req.url.path == "/s2s/v2.0/task/skin-tone-analysis/T1":
            return httpx.Response(200, json=OK_TONE)
        return httpx.Response(404, json={"error": "not mocked"})

    c = YouCamClient(api_key="k", transport=httpx.MockTransport(handler))
    c.poll_sleep = lambda s: None
    return c


@pytest.fixture()
def photo(tmp_path):
    p = tmp_path / "selfie.jpg"
    p.write_bytes(b"\xff\xd8\xff" + b"0" * 100)
    return p


def levels(seen):
    return [b["face_angle_strictness_level"] for m, path, b in seen if path.endswith("skin-tone-analysis")]


def test_default_strictness_is_the_most_lenient_documented_level(monkeypatch):
    monkeypatch.delenv("YOUCAM_FACE_ANGLE_STRICTNESS", raising=False)
    assert Y.tone_strictness() == "flexible" == Y.TONE_STRICTNESS_LEVELS[0]
    assert Y.TONE_STRICTNESS_LEVELS == ("flexible", "low", "medium", "high", "strict")
    monkeypatch.setenv("YOUCAM_FACE_ANGLE_STRICTNESS", "LOW")
    assert Y.tone_strictness() == "low"
    monkeypatch.setenv("YOUCAM_FACE_ANGLE_STRICTNESS", "sideways")      # not a level: lenient default
    assert Y.tone_strictness() == "flexible"


def test_never_high_by_default(photo, monkeypatch):
    monkeypatch.delenv("YOUCAM_FACE_ANGLE_STRICTNESS", raising=False)
    seen = []
    res = tone_client(seen).skin_tone(photo)
    assert levels(seen) == ["flexible"] and res.strictness == "flexible"


def test_invalid_parameter_steps_to_the_next_level_with_one_upload(photo):
    seen = []
    res = tone_client(seen, refuse={"flexible"}).skin_tone(photo)
    assert levels(seen) == ["flexible", "low"] and res.strictness == "low" and res.skin_color == "#b9947c"
    assert sum(1 for s in seen if s[1] == "/s2s/v2.0/file") == 1


def test_fallback_stops_at_medium_and_never_reaches_high(photo):
    seen = []
    with pytest.raises(YouCamError) as e:
        tone_client(seen, refuse={"flexible", "low", "medium", "high", "strict"}).skin_tone(photo)
    assert levels(seen) == ["flexible", "low", "medium"]
    assert "InvalidParameters" not in e.value.friendly


def test_an_explicit_level_is_sent_as_is(photo):
    seen = []
    tone_client(seen).skin_tone(photo, strictness="medium")
    assert levels(seen) == ["medium"]


# ---------------------------------------------------------------- 4. friendly errors
ANGLE_CODES = ["error_face_angle_leftward", "error_face_angle_rightward", "error_face_angle_upward",
               "error_face_angle_downward", "error_face_angle_left_tilt", "error_face_angle_right_tilt"]


@pytest.mark.parametrize("code", ANGLE_CODES + sorted(Y.UNUSABLE_PHOTO_ERRORS) +
                         ["error_face_angle_new_kind", "error_something_new", "InvalidParameters", None])
def test_every_error_is_one_plain_sentence_without_the_code(code):
    line = Y.friendly_error(code)
    assert line and line.endswith(".") and "error_" not in line and "Invalid" not in line
    assert line.rstrip(".").count(". ") == 0                              # one sentence


def test_sideways_turn_reads_turn_toward_the_camera():
    assert Y.friendly_error("error_face_angle_leftward") == "Turn a little more toward the camera and try again."
    assert Y.friendly_error("error_face_angle_rightward") == "Turn a little more toward the camera and try again."


def test_a_task_error_carries_the_plain_line(photo):
    def handler(req):
        if req.url.host == "upload.example":
            return httpx.Response(200)
        if req.url.path == "/s2s/v2.0/file":
            return httpx.Response(200, json=UPLOAD[("POST", "/s2s/v2.0/file")])
        if req.method == "POST":
            return httpx.Response(200, json={"data": {"task_id": "T1"}})
        return httpx.Response(200, json={"data": {"task_status": "error", "error": "error_face_angle_leftward"}})
    c = YouCamClient(api_key="k", transport=httpx.MockTransport(handler))
    c.poll_sleep = lambda s: None
    with pytest.raises(YouCamError) as e:
        c.skin_tone(photo)
    assert e.value.code == "error_face_angle_leftward"
    assert e.value.friendly == "Turn a little more toward the camera and try again."


# ---------------------------------------------------------------- 3. pose precheck
def rot(yaw=0.0, pitch=0.0, roll=0.0):
    """Row-major 4x4 R = Rz(roll) @ Ry(yaw) @ Rx(pitch), the convention faceGuide.ts reads."""
    cy, sy = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
    cp, sp = math.cos(math.radians(pitch)), math.sin(math.radians(pitch))
    cr, sr = math.cos(math.radians(roll)), math.sin(math.radians(roll))
    rz = [[cr, -sr, 0], [sr, cr, 0], [0, 0, 1]]
    ry = [[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]]
    rx = [[1, 0, 0], [0, cp, -sp], [0, sp, cp]]

    def mul(a, b):
        return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
    r = mul(mul(rz, ry), rx)
    return [r[0] + [0], r[1] + [0], r[2] + [0], [0, 0, 0, 1]]


@pytest.mark.parametrize("yaw,pitch,roll", [(0, 0, 0), (-11.1, -3.6, 7.7), (20, 10, -5), (-40, 0, 0)])
def test_angles_from_matrix_round_trip(yaw, pitch, roll):
    y, p, r = PO.angles_from_matrix(rot(yaw, pitch, roll))
    assert (round(y, 3), round(p, 3), round(r, 3)) == (yaw, pitch, roll)


def test_window_2_pose_passes_and_only_unusable_photos_are_blocked():
    # window_2 (morning, by a window), measured on the crop YouCam sees: yaw -11.1, pitch -3.6, roll 7.7.
    assert PO.check(PO.Pose(-11.1, -3.6, 7.7), 0.61) is None
    assert PO.check(PO.Pose(-34.9, 29.9, -29.9), 0.13) is None        # still readable
    assert PO.check(None, 0.5) is None                                  # unknown pose never refuses
    assert PO.check(PO.Pose(-50, 0, 0), 0.6)[0] == "side_profile"
    assert PO.check(PO.Pose(0, 40, 0), 0.6)[0] == "head_tilt_up_down"
    assert PO.check(PO.Pose(0, 0, -45), 0.6)[0] == "head_on_side"
    assert PO.check(PO.Pose(0, 0, 0), 0.05)[0] == "too_dark"
    for code, fix in PO.FIXES.items():
        assert fix.endswith(".") and "_" not in fix


def test_estimate_never_raises():
    PO.set_estimator(lambda img: 1 / 0)
    assert PO.estimate(Image.new("RGB", (10, 10))) is None


# ---------------------------------------------------------------- 5. always an answer
def test_veins_answer_gives_a_labelled_undertone():
    for veins, tone in (("green", "warm"), ("blue_purple", "cool"), ("mix", "neutral")):
        ut = U.from_payload(None, {"veins": veins})
        assert (ut.tone, ut.source, ut.label) == (tone, "answers", "from your answers")
    assert U.from_payload(None, {}).source == "default"
    # A measured colour still wins over the answer.
    assert U.from_payload(OK_TONE, {"veins": "blue_purple"}).source == "face"


# ---------------------------------------------------------------- the API
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


def scan(m, answers=None, image=None, **form):
    data = {"answers": json.dumps(answers or {"finish": "dewy"}), **{k: str(v) for k, v in form.items()}}
    return TestClient(m.app, headers=LIVE).post("/api/basket/scan",
                                                files={"image": ("s.jpg", image or jpg(), "image/jpeg")}, data=data)


def youcam_calls(fake):
    return [c if isinstance(c, str) else c[0] for c in fake.calls if c != "balance"]


def refuse_tone(fake, code):
    def tone(path):
        fake.calls.append("tone")
        raise YouCamError(f"Task failed: {code}", code=code, friendly=Y.friendly_error(code))
    fake.skin_tone = tone


def test_tone_runs_before_the_analysis(env):
    m, fake = env
    assert scan(m).status_code == 200
    calls = youcam_calls(fake)
    assert calls.index("tone") < calls.index("analyze")


def test_angle_refusal_still_returns_the_full_basket_from_the_answer(env):
    m, fake = env
    refuse_tone(fake, "error_face_angle_leftward")
    r = scan(m, {"finish": "dewy", "veins": "blue_purple"})
    assert r.status_code == 200, r.text
    b = r.json()
    assert "error_face" not in r.text                                    # no raw code reaches the user
    ut = b["face_map"]["undertone"]
    assert (ut["tone"], ut["source"], ut["label"]) == ("cool", "answers", "from your answers")
    assert b["jobs"] and b["source"] == "live" and b["face_map"]["zones"]
    assert "Turn a little more toward the camera" in b["notice"] and "wrist veins" in b["notice"]
    assert "analyze" in youcam_calls(fake)                               # the skin scan is kept
    assert b["tryon"]["undertone"] == "cool"                             # shade picks follow the answer
    assert m.units_spent()["total"] == 14.0                              # 12 + 2 x 1; the refused tone is free
    stored = m.all_("baskets")[-1]
    assert stored["youcam"]["cost_units"] == 14.0 and stored["youcam"]["tone"]["ok"] is False


def test_angle_refusal_without_the_answer_asks_for_it(env):
    m, fake = env
    refuse_tone(fake, "error_face_angle_upward")
    b = scan(m, {"finish": "dewy"}).json()
    assert b["face_map"]["undertone"]["source"] == "default"
    assert "Answer the wrist-vein question" in b["notice"] and "Lower your chin" in b["notice"]


def test_an_unusable_photo_stops_before_the_analysis_is_paid_for(env):
    m, fake = env
    refuse_tone(fake, "error_no_face")
    r = scan(m)
    assert r.status_code == 422
    assert r.json()["detail"]["message"] == Y.IMAGE_ERRORS["error_no_face"]
    assert "analyze" not in youcam_calls(fake) and m.units_spent()["total"] == 0.0


def test_a_failed_try_on_keeps_the_basket(env):
    m, fake = env

    def vto(effects, image_path=None):
        fake.calls.append(("vto", 0))
        raise YouCamError("Task failed: error_x", code="error_x", friendly="x")
    fake.makeup_vto = vto
    r = scan(m)
    assert r.status_code == 200
    b = r.json()
    assert b["jobs"] and b["tryon"]["line"] == m.TRYON_FAILED_LINE
    assert m.units_spent()["total"] == 32.0                              # 20 + 12, no renders charged


def test_precheck_blocks_a_side_profile_before_any_youcam_call(env):
    m, fake = env
    PO.set_estimator(lambda img: PO.Pose(55.0, 0.0, 0.0))
    r = scan(m)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "side_profile"
    assert "Turn a little more toward the camera" in r.json()["detail"]["message"]
    assert fake.calls == [] and m.units_spent()["total"] == 0.0


def test_precheck_blocks_a_dark_photo(env):
    m, fake = env
    b = io.BytesIO()
    Image.new("RGB", (720, 960), (12, 10, 9)).save(b, "JPEG")
    r = scan(m, image=b.getvalue())
    assert r.status_code == 422 and r.json()["detail"]["code"] == "too_dark" and fake.calls == []


def test_the_browser_pose_is_used_when_sent(env):
    m, fake = env
    PO.set_estimator(lambda img: PO.Pose(0.0, 0.0, 0.0))
    r = scan(m, yaw=60, pitch=0, roll=0)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "side_profile" and fake.calls == []


def test_free_precheck_endpoint_reports_angles_and_the_rule(env):
    m, fake = env
    c = TestClient(m.app)
    r = c.post("/api/basket/precheck", files={"image": ("s.jpg", jpg(), "image/jpeg")})
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] is True and j["pose"] == {"yaw": -11.0, "pitch": -3.5, "roll": 7.5, "source": "server"}
    assert j["rule"]["max_yaw"] == 35.0 and fake.calls == []
    PO.set_estimator(lambda img: PO.Pose(-60.0, 0.0, 0.0))
    j = c.post("/api/basket/precheck", files={"image": ("s.jpg", jpg(), "image/jpeg")}).json()
    assert j["ok"] is False and j["code"] == "side_profile" and fake.calls == []


# ---------------------------------------------------------------- the recorded demo face
def test_demo_persona_uses_the_recorded_face_and_keeps_the_demo_label(env):
    m, fake = env
    from app import demo_faces as DF
    face = DF.load_face("riya")
    assert face["synthetic"] is False and face["label"] == "Demo data" and face["renders"] == {}
    blob = json.loads((m.demo.fixtures_dir() / "riya" / "basket_face.json").read_text(encoding="utf-8"))
    assert blob["source"] == "live scan 2026-11-01" and len(blob["raw_scores"]) == 7
    assert "http" not in json.dumps({k: v for k, v in blob.items() if k != "note"})
    m.build_scene("riya-basket")
    b = TestClient(m.app).post("/api/basket", json={"persona": "riya"}).json()
    assert b["demo_label"] == "Demo data" and b["source"] == "replay" and fake.calls == []
    ut = b["face_map"]["undertone"]
    assert (ut["tone"], ut["depth"], ut["skin_color"]) == (blob["undertone"]["tone"], blob["undertone"]["depth"],
                                                          blob["skin_color"])
    assert {z["zone"]: z["type"] for z in b["face_map"]["zones"]} == {k: v["type"] for k, v in blob["zones"].items()}
    assert b["tryon"]["line"] == "Preview appears on a live scan"
