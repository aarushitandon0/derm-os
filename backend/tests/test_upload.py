"""Uploaded photos: the free precheck, baseline integrity, the same crop / fingerprint / gate as
camera shots, and metadata stripping. No network: YouCam is a fake, or must never be called."""
import importlib
import io
import json
import sqlite3

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from app import photometa as P
from app.youcam import normalize

LIVE = {"X-Live-Passcode": "test-passcode"}
GPS_LAT = (12.0, 34.0, 56.789)   # distinctive numbers to search the database for
GPS_SECRET = "56.789"


def photo(color=(200, 160, 140), when: str | None = None, gps: bool = False, make: str | None = None,
          size=(720, 960), fmt="JPEG") -> bytes:
    e = Image.Exif()
    if when:
        e[0x0132] = when
        e.get_ifd(0x8769)[0x9003] = when
    if make:
        e[0x010F], e[0x0110] = make, "Model 7"
    if gps:
        e.get_ifd(0x8825).update({1: "N", 2: GPS_LAT, 3: "E", 4: (76.0, 54.0, 32.1)})
    img = Image.new("RGB", size, color)
    # A corner mark sized by the colour, so photos of near-identical colours still differ in pixels
    # after JPEG compression. It sits outside the face crop, so it doesn't change the light reading.
    side = 8 + (color[0] * 7 + color[1] * 3 + color[2]) % 50
    if size[0] > 100:
        ImageDraw.Draw(img).rectangle((0, 0, side, side), fill=(0, 0, 0))
    b = io.BytesIO()
    img.save(b, fmt, exif=e)
    return b.getvalue()


def files(*blobs, ctype="image/jpeg"):
    return [("images", (f"p{i}.jpg", b, ctype)) for i, b in enumerate(blobs)]


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DERMOS_DB", str(tmp_path / "t.db"))
    monkeypatch.setenv("DERMOS_MEDIA", str(tmp_path / "media"))
    monkeypatch.setenv("SCAN_RATE_LIMIT", "0")
    return monkeypatch


def load(monkeypatch, demo=True):
    monkeypatch.setenv("DEMO_MODE", "1" if demo else "0")
    import app.main as m
    importlib.reload(m)

    def no_youcam(*a, **k):
        raise AssertionError("YouCam must not be called")
    monkeypatch.setattr(m, "YouCamClient", no_youcam)
    return m


BASE3 = [photo((200, 160, 140), "2026:10:28 09:00:00"), photo((201, 160, 140), "2026:10:28 09:03:00"),
         photo((199, 161, 140), "2026:10:28 09:06:00")]


def precheck(c, blobs, phase="baseline", **data):
    return c.post("/api/upload/precheck", files=files(*blobs), data={"phase": phase, **data}).json()


# ---------------------------------------------------------------- precheck
def test_precheck_passes_and_never_calls_youcam(env):
    m = load(env)
    r = precheck(TestClient(m.app), BASE3)
    assert r["ok"] is True and r["timing"] == "exif" and r["message"] is None
    assert [p["ok"] for p in r["photos"]] == [True, True, True]
    assert r["photos"][0]["hour"] == 9
    assert m.all_("captures") == []                   # a precheck stores nothing


def test_baseline_needs_exactly_three_and_checkin_two(env):
    m = load(env)
    c = TestClient(m.app)
    assert precheck(c, BASE3[:2])["code"] == "count"
    assert "exactly 3 photos" in precheck(c, BASE3[:2])["message"]
    assert precheck(c, BASE3, phase="checkin")["code"] == "count"


def test_duplicate_baseline_is_refused(env):
    m = load(env)
    # Same pixels, different metadata: still the same photo.
    dup = photo((200, 160, 140), "2026:10:28 09:04:00", make="Other")
    r = precheck(TestClient(m.app), [BASE3[0], dup, BASE3[2]])
    assert r["ok"] is False and r["code"] == "duplicate"
    assert r["message"] == "These look like the same photo. Upload 3 different shots."


def test_spread_timestamps_are_refused(env):
    m = load(env)
    late = photo((198, 160, 141), "2026:10:28 09:30:00")
    r = precheck(TestClient(m.app), [BASE3[0], BASE3[1], late])
    assert r["ok"] is False and r["code"] == "spread"
    assert r["message"] == "Your first photos need to be taken a few minutes apart, in one sitting."


def test_missing_timestamps_need_confirmation(env):
    m = load(env)
    c = TestClient(m.app)
    blobs = [BASE3[0], BASE3[1], photo((198, 162, 140))]          # third has no EXIF time
    r = precheck(c, blobs)
    assert r["ok"] is False and r["needs_confirmation"] is True and r["code"] == "confirm_sitting"
    assert r["message"] == "Were these taken within a few minutes of each other, in the same spot?"
    yes = precheck(c, blobs, same_sitting="true")
    assert yes["ok"] is True and yes["timing"] == "user-confirmed"
    no = precheck(c, blobs, same_sitting="false")
    assert no["ok"] is False and no["code"] == "spread"


def test_user_confirmation_is_stored_with_the_baseline(env):
    m = load(env)
    c = TestClient(m.app)
    blobs = [photo((200, 160, 140)), photo((201, 160, 140)), photo((199, 161, 140))]
    r = c.post("/api/upload/scan", files=files(*blobs), data={"phase": "baseline", "same_sitting": "true"})
    assert r.status_code == 200
    caps = r.json()["captures"]
    assert len(caps) == 3 and all(cp["baseline_timing"] == "user-confirmed" for cp in caps)
    assert all(cp["fingerprint"]["capture_source"] == "upload" for cp in caps)
    assert all(cp["source"] == "replay" for cp in caps)          # demo mode: prepared data, labelled


def test_scan_reruns_the_checks_and_never_trusts_the_client(env):
    m = load(env)
    c = TestClient(m.app)
    r = c.post("/api/upload/scan", files=files(BASE3[0], BASE3[0], BASE3[2]), data={"phase": "baseline"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "duplicate"
    assert m.all_("captures") == []


def test_files_over_15_mb_and_other_types_are_refused(env):
    m = load(env)
    c = TestClient(m.app)
    big = b"\xff\xd8\xff" + b"0" * (15 * 1024 * 1024)
    r = precheck(c, [big, BASE3[1], BASE3[2]])
    assert r["code"] == "too_big" and r["message"].startswith("Photo 1:")
    gif = io.BytesIO()
    Image.new("RGB", (720, 960)).save(gif, "GIF")
    assert precheck(c, [BASE3[0], gif.getvalue(), BASE3[2]])["code"] == "format"


def test_heic_is_accepted_when_the_decoder_is_installed(env, monkeypatch):
    pytest.importorskip("pillow_heif")
    m = load(env)
    c = TestClient(m.app)
    heic = io.BytesIO()
    Image.new("RGB", (720, 960), (190, 150, 130)).save(heic, "HEIF")
    r = precheck(c, [heic.getvalue(), BASE3[1], BASE3[2]], same_sitting="true")
    assert r["photos"][0]["ok"] is True and r["ok"] is True
    monkeypatch.setattr(P, "HEIC_SUPPORTED", False)
    r = precheck(c, [heic.getvalue(), BASE3[1], BASE3[2]])
    assert r["code"] == "heic" and "Most Compatible" in r["message"]


def test_palette_photo_gets_a_warning_not_a_refusal(env):
    m = load(env)
    pal = io.BytesIO()
    Image.new("RGB", (720, 960), (200, 160, 140)).convert("P").save(pal, "PNG")
    r = precheck(TestClient(m.app), [pal.getvalue(), BASE3[1], BASE3[2]], same_sitting="true")
    assert r["ok"] is True and "reduced colours" in r["photos"][0]["warning"]


def test_no_face_gives_one_plain_fix(env):
    from app import facecrop
    m = load(env)
    facecrop.set_detector(lambda img: [])
    r = precheck(TestClient(m.app), BASE3)
    assert r["ok"] is False and r["code"] == "no_face" and r["message"].startswith("Photo 1: We couldn't find a face")


# ---------------------------------------------------------------- the gate: same for camera and upload
def _trial_with_upload_baseline(c):
    tid = c.post("/api/trials", json={"goal_concern": "redness", "product_id": "sr-01"}).json()["id"]
    r = c.post("/api/upload/scan", files=files(*BASE3), data={"phase": "baseline", "trial_id": tid})
    assert r.status_code == 200, r.text
    return tid


@pytest.mark.parametrize("color,comparable", [((200, 160, 140), True), ((240, 150, 60), False)])
def test_uploaded_and_camera_photos_get_identical_gate_results(env, color, comparable):
    m = load(env)
    c = TestClient(m.app)
    tid = _trial_with_upload_baseline(c)
    shot = photo(color, "2026:10:28 09:10:00")
    other = photo((color[0] - 1, color[1], color[2]), "2026:10:28 09:11:00")
    pre = precheck(c, [shot, other], phase="checkin", trial_id=tid)
    cam = c.post("/api/scan", files={"image": ("cam.jpg", shot, "image/jpeg")},
                 data={"phase": "checkin", "trial_id": tid, "actions": "redness,acne,texture,pore"}).json()
    assert pre["comparability"][0] == cam["comparability"]
    assert cam["comparability"]["comparable"] is comparable and pre["ok"] is comparable
    if not comparable:
        assert pre["code"] == "not_comparable" and pre["message"].startswith("Photo 1 doesn't match")
    # capture_source is display only: the stored fingerprints differ in nothing else
    up = m._prepare(shot, "sd", None, "upload").fp.to_dict()
    ca = m._prepare(shot, "sd", None, "camera").fp.to_dict()
    assert {k for k in up if up[k] != ca[k]} == {"capture_source"}


def test_scan_refuses_a_checkin_the_gate_rejects(env):
    m = load(env)
    c = TestClient(m.app)
    tid = _trial_with_upload_baseline(c)
    lamp = [photo((240, 150, 60), "2026:10:28 09:10:00"), photo((241, 150, 60), "2026:10:28 09:11:00")]
    r = c.post("/api/upload/scan", files=files(*lamp), data={"phase": "checkin", "trial_id": tid})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "not_comparable"
    assert not [cp for cp in m.all_("captures") if cp["phase"] == "checkin"]


# ---------------------------------------------------------------- privacy: metadata and GPS
def test_upload_input_really_carries_gps_and_exif():
    raw = photo(when="2026:10:28 09:00:00", gps=True, make="Acme")
    with Image.open(io.BytesIO(raw)) as im:
        assert im.getexif().get_ifd(0x8825).get(2) is not None      # the test photo has GPS
    meta = P.read_meta(raw)
    assert meta.hour == 9 and meta.device == "Acme Model 7"
    assert set(vars(meta)) == {"taken_at", "hour", "device"}          # nothing else is read


def test_gps_is_never_stored_and_stored_files_have_no_exif(env, tmp_path, caplog):
    env.setenv("LIVE_SCAN_MIN_BALANCE", "0")
    m = load(env, demo=False)
    sent = []
    mask_jpeg = photo((10, 200, 10), "2026:10:28 09:00:00", gps=True, make="Acme", size=(48, 64))

    class Live:
        version = "v2.1"
        upload_http = httpx.Client(transport=httpx.MockTransport(
            lambda req: httpx.Response(200, content=mask_jpeg, headers={"content-type": "image/jpeg"})))

        def unit_balance(self):
            return 1000.0

        def scan_cost(self, actions):
            return 9.0, "built-in"

        def analyze(self, path, actions):
            data = open(path, "rb").read()
            sent.append(data)
            return normalize({"data": {"results": {"output": [
                {"type": a, "raw_score": 60, "mask_urls": [f"https://s3.example/{a}.jpg"]} for a in actions]}}},
                "sd", actions, "T1")

        def delete_task(self, tid):
            return {}
    env.setattr(m, "YouCamClient", lambda: Live())
    blobs = [photo((200 + i, 160, 140), f"2026:10:28 09:0{i}:00", gps=True, make="Acme") for i in range(3)]
    r = TestClient(m.app, headers=LIVE).post("/api/upload/scan", files=files(*blobs), data={"phase": "baseline"})
    assert r.status_code == 200, r.text
    caps = r.json()["captures"]
    assert all(cp["source"] == "live" for cp in caps) and len(sent) == 3
    # What went to YouCam: pixels only.
    assert not any(P.has_metadata(b) for b in sent)
    # What this server stored on disk (the saved masks): pixels only.
    media = list((tmp_path / "media").rglob("*.*"))
    assert media and not any(P.has_metadata(f.read_bytes()) for f in media)
    # The database: hour and a coarse camera label, never GPS.
    with sqlite3.connect(tmp_path / "t.db") as con:
        dump = "\n".join(row[0] for row in con.execute("SELECT body FROM captures"))
    assert GPS_SECRET not in dump and "gps" not in dump.lower() and "GPSInfo" not in dump
    fp = caps[0]["fingerprint"]
    assert fp["captured_hour"] == 9 and fp["device"] == "Acme Model 7" and fp["capture_source"] == "upload"
    assert GPS_SECRET not in caplog.text


def test_camera_crop_sent_to_youcam_has_no_metadata(env):
    env.setenv("LIVE_SCAN_MIN_BALANCE", "0")
    m = load(env, demo=False)
    sent = []

    class Live:
        version = "v2.1"
        upload_http = None

        def unit_balance(self):
            return 1000.0

        def scan_cost(self, actions):
            return 9.0, "built-in"

        def analyze(self, path, actions):
            sent.append(open(path, "rb").read())
            return normalize({"data": {"results": {"output": [{"type": a, "raw_score": 60} for a in actions]}}},
                             "sd", actions, "T1")

        def delete_task(self, tid):
            return {}
    env.setattr(m, "YouCamClient", lambda: Live())
    raw = photo(when="2026:10:28 09:00:00", gps=True, make="Acme")
    r = TestClient(m.app, headers=LIVE).post("/api/scan", files={"image": ("a.jpg", raw, "image/jpeg")},
                                             data={"actions": "redness"})
    assert r.status_code == 200 and len(sent) == 1 and not P.has_metadata(sent[0])
    assert r.json()["capture"]["fingerprint"]["capture_source"] == "camera"
    assert GPS_SECRET not in json.dumps(r.json())


def test_clean_bytes_drops_every_tag():
    raw = photo(when="2026:10:28 09:00:00", gps=True, make="Acme", size=(32, 32))
    assert P.has_metadata(raw)
    clean, ext = P.clean_bytes(raw)
    assert ext == ".jpg" and not P.has_metadata(clean)
    assert P.clean_bytes(b"not an image") is None


def test_integrity_rules_directly():
    from datetime import datetime as dt
    t = [dt(2026, 10, 28, 9, 0), dt(2026, 10, 28, 9, 14), dt(2026, 10, 28, 9, 15)]
    assert P.baseline_integrity(["a", "b", "c"], t, None)["timing"] == "exif"
    t2 = [dt(2026, 10, 28, 9, 0), dt(2026, 10, 28, 9, 10), dt(2026, 10, 28, 9, 15, 1)]
    assert P.baseline_integrity(["a", "b", "c"], t2, True)["code"] == "spread"   # yes can't override real times
    assert P.baseline_integrity(["a", "a", "c"], t, None)["code"] == "duplicate"
