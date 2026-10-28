"""Server-side crop and size normalisation, the gate's use of it, and exact unit costs.
Synthetic images and stand-in detectors only: no real photos, no model, no network, no units."""
import importlib
import io

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from app import evidence as E
from app import facecrop as F
from app.fingerprint import Fingerprint, measure_normalised
from app.youcam import (PRICE_FALLBACK, UnitReserveError, YouCamClient, check_unit_reserve, normalize,
                        parse_skin_prices, scan_cost_from)

LIVE = {"X-Live-Passcode": "test-passcode"}


def photo_with_face(size=(1200, 1600), face=(300, 400, 600, 660), colour=(200, 150, 120), face_colour=(255, 255, 255)):
    """A plain photo with a 'face' rectangle (white by default, so its width can be measured after scaling)."""
    im = Image.new("RGB", size, colour)
    x, y, w, h = face
    ImageDraw.Draw(im).rectangle([x, y, x + w - 1, y + h - 1], fill=face_colour)
    return im


def box(x, y, w, h):
    return F.Box(x, y, w, h, 0.99)


def white_width(im: Image.Image) -> int:
    row = im.convert("L").crop((0, im.height // 2, im.width, im.height // 2 + 1)).getdata()
    return sum(1 for v in row if v > 230)


# -- the rule ------------------------------------------------------------------------------

@pytest.mark.parametrize("face_w", [360, 500, 800, 1100])
def test_crop_is_3_by_4_with_face_at_75_percent_and_fixed_target(face_w):
    face = box(1500 - face_w / 2, 1800 - face_w / 2, face_w, face_w)
    p = F.plan(3000, 4000, face, "sd")
    l, t, r, b = p.crop
    assert (r - l) * 4 == pytest.approx((b - t) * 3)
    assert face.w / (r - l) == pytest.approx(0.75)
    assert p.output == (480, 640) and p.scale <= 1
    assert face.w * p.scale == pytest.approx(F.TARGET_FACE_PX["sd"])   # every capture: face = 360 px
    assert (l + r) / 2 == pytest.approx(face.cx) and (t + b) / 2 == pytest.approx(face.cy)


def test_target_meets_sd_and_hd_minimum_short_side():
    assert F.TARGET_FACE_PX == {"sd": 360, "hd": 810}
    assert F.OUTPUT["sd"][0] == 480 and F.OUTPUT["hd"][0] == 1080


def test_normalised_face_width_is_the_target_in_pixels():
    im = photo_with_face(face=(300, 400, 600, 660))
    n = F.normalise(im, [box(300, 400, 600, 660)])
    assert n.image.size == (480, 640) and n.mode == "sd"
    assert abs(white_width(n.image) - 360) <= 2
    assert n.info["face_px_original"] == 600 and n.info["face_pct_original"] == 50.0


def test_normalisation_is_deterministic():
    im = photo_with_face()
    a = F.normalise(im, [box(300, 400, 600, 660)]).png_bytes()
    b = F.normalise(im.copy(), [box(300, 400, 600, 660)]).png_bytes()
    assert a == b


def test_never_upscales_a_small_face():
    with pytest.raises(F.Refusal) as e:
        F.plan(3000, 4000, box(1000, 1000, 359, 359), "sd")
    assert e.value.code == "too_far" and e.value.fix == "Hold the phone a little closer."


def test_shifts_inside_the_photo_without_resizing_the_box():
    p = F.plan(1200, 1600, box(0, 0, 600, 600), "sd")      # face in the top-left corner
    assert p.crop[:2] == (0, 0) and p.clamped
    assert p.crop[2] - p.crop[0] == pytest.approx(800)


def test_no_colour_or_brightness_change():
    # A uniform photo stays exactly the same colour after crop + downscale.
    im = Image.new("RGB", (1200, 1600), (201, 152, 117))
    n = F.normalise(im, [box(300, 400, 600, 600)])
    assert n.image.getextrema() == ((201, 201), (152, 152), (117, 117))


def test_exif_orientation_is_read_not_added_rotation():
    # A photo stored sideways with an orientation tag is read the way the phone showed it.
    upright = photo_with_face(size=(1200, 1600))
    stored = upright.transpose(Image.Transpose.ROTATE_90)   # what the sensor wrote
    exif = Image.Exif()
    exif[F.ORIENTATION_TAG] = 6                              # "rotate 90 CW to display"
    b = io.BytesIO()
    stored.save(b, "PNG", exif=exif)
    img, notes = F.open_upright(b.getvalue())
    assert img.size == (1200, 1600) and notes["exif_orientation"] == 6
    assert img.tobytes() == upright.tobytes()


def test_palette_photo_is_converted_to_rgb_and_flagged():
    b = io.BytesIO()
    photo_with_face().quantize(64).save(b, "PNG")
    img, notes = F.open_upright(b.getvalue())
    assert img.mode == "RGB" and notes["source_mode"] == "P" and notes["reduced_colour"] is True
    _, ok = F.open_upright(_jpeg(photo_with_face()))
    assert ok["reduced_colour"] is False


def _jpeg(im):
    b = io.BytesIO()
    im.save(b, "JPEG")
    return b.getvalue()


# -- refusals ------------------------------------------------------------------------------

@pytest.mark.parametrize("faces,code", [
    ([], "no_face"),
    ([box(100, 100, 400, 400), box(600, 100, 400, 400)], "several_faces"),
    ([box(500, 500, 200, 200)], "too_far"),
    ([box(50, 100, 1100, 1100)], "too_close"),
    ([box(-50, 400, 600, 600)], "out_of_frame"),
])
def test_refusals_each_have_one_plain_fix(faces, code):
    with pytest.raises(F.Refusal) as e:
        F.normalise(Image.new("RGB", (1200, 1600)), faces)
    assert e.value.code == code and e.value.fix == F.REFUSALS[code]


def test_unreadable_file_is_refused():
    with pytest.raises(F.Refusal) as e:
        F.open_upright(b"not an image")
    assert e.value.code == "unreadable"


# -- SD / HD -------------------------------------------------------------------------------

def test_hd_only_when_the_face_can_reach_hd_without_upscaling():
    assert F.mode_for(box(0, 0, 900, 900), "hd", None) == "hd"
    assert F.mode_for(box(0, 0, 700, 700), "hd", None) == "sd"
    assert F.mode_for(box(0, 0, 900, 900), "sd", None) == "sd"


def test_trial_mode_is_never_mixed():
    assert F.mode_for(box(0, 0, 900, 900), "hd", "sd") == "sd"
    im = Image.new("RGB", (1500, 2000))
    with pytest.raises(F.Refusal) as e:   # an HD trial can't take an SD-sized face
        F.normalise(im, [box(400, 400, 600, 600)], "sd", locked="hd")
    assert e.value.code == "too_far"
    n = F.normalise(Image.new("RGB", (3000, 4000)), [box(1000, 1000, 1000, 1000)], "hd")
    assert n.mode == "hd" and n.image.size == (1080, 1440)


# -- the gate ------------------------------------------------------------------------------

def _fp(tmp_path, name, face_px, size=(3000, 4000), colour=(200, 150, 120)):
    w, h = size
    im = photo_with_face(size, (int(w / 2 - face_px / 2), int(h / 2 - face_px / 2), face_px, face_px), colour, colour)
    orig = tmp_path / f"{name}.jpg"
    im.save(orig, "JPEG", quality=95)
    n = F.normalise_file(str(orig), detect=lambda _i: [box(w / 2 - face_px / 2, h / 2 - face_px / 2,
                                                         face_px, face_px)])
    norm = tmp_path / f"{name}.norm.png"
    norm.write_bytes(n.png_bytes())
    return measure_normalised(norm, orig, n.info, 0, 0, 0)


def test_gate_uses_normalised_face_size_so_distance_no_longer_fails(tmp_path):
    near, far = _fp(tmp_path, "near", 1400), _fp(tmp_path, "far", 500)
    # Original framing differs a lot (35% vs 12.5% of the width) ...
    assert abs(near.face_pct_original - far.face_pct_original) / 100 > E.TOLERANCES["face_ratio"]
    # ... but the normalised captures are the same size.
    assert near.face_ratio == far.face_ratio == 0.75 and near.face_px == far.face_px == 360
    assert near.width == far.width == 480
    c = E.compare_conditions([E.Capture({"redness": 60}, near)] * 2, [E.Capture({"redness": 60}, far)] * 2)
    assert "face_size" in c.checked and c.comparable


def test_fingerprint_stores_original_and_normalised_sizes(tmp_path):
    fp = _fp(tmp_path, "a", 1200)
    d = fp.to_dict()
    assert d["face_px_original"] == 1200 and d["face_pct_original"] == 40.0
    assert d["original_width"] == 3000 and d["original_height"] == 4000
    assert d["face_px"] == 360 and d["face_ratio"] == 0.75
    assert d["normalisation"]["target_face_px"] == 360 and d["normalisation"]["version"] == F.NORMALISE_VERSION
    assert Fingerprint.from_dict(d).face_px_original == 1200


def test_other_gate_rules_and_tolerances_are_unchanged(tmp_path):
    assert E.TOLERANCES == {"luminance": 0.12, "red_blue_ratio": 0.15, "face_ratio": 0.10, "angle": 8.0, "hour": 6}
    assert E.MIN_BAND == 0.0
    base = [E.Capture({"redness": 60}, _fp(tmp_path, f"b{i}", 1000)) for i in range(2)]
    warm = [E.Capture({"redness": 60}, _fp(tmp_path, f"w{i}", 1000, colour=(230, 150, 70))) for i in range(2)]
    dark = [E.Capture({"redness": 60}, _fp(tmp_path, f"d{i}", 1000, colour=(60, 45, 36))) for i in range(2)]
    assert {f["field"] for f in E.compare_conditions(base, warm).failed} == {"lighting"}
    assert any("Brightness" in r for r in E.compare_conditions(base, dark).reasons)
    # Old fingerprints (no normalisation) still fail face size by the same rule.
    a = Fingerprint(720, 960, 0.5, 1.3, face_ratio=0.62)
    b = Fingerprint(720, 960, 0.5, 1.3, face_ratio=0.75)
    assert not E.compare_conditions([E.Capture({}, a)], [E.Capture({}, b)]).comparable
    turned = Fingerprint(480, 640, base[0].fingerprint.luminance, base[0].fingerprint.red_blue_ratio,
                         face_ratio=0.75, yaw=12)
    assert "head_pose" in {f["field"] for f in E.compare_conditions(base, [E.Capture({}, turned)]).failed}


# -- API -----------------------------------------------------------------------------------

@pytest.fixture()
def m(tmp_path, monkeypatch):
    monkeypatch.setenv("DERMOS_DB", str(tmp_path / "t.db"))
    monkeypatch.setenv("DERMOS_MEDIA", str(tmp_path / "media"))
    import app.main as main
    importlib.reload(main)
    return main


class FakeYouCam:
    version = "v2.1"
    upload_http = None

    def __init__(self, balance=1000.0):
        self.sent, self.balance = [], balance

    def unit_balance(self):
        return self.balance

    def scan_cost(self, actions):
        return scan_cost_from({}, self.version, actions)

    def analyze(self, path, actions):
        with Image.open(path) as im:
            self.sent.append({"size": im.size, "format": im.format, "actions": list(actions)})
        return normalize({"data": {"results": {"output": [{"type": a, "raw_score": 60} for a in actions]}}},
                         "hd" if actions[0].startswith("hd_") else "sd", actions, "T1")

    def delete_task(self, task_id):
        return {}


def scan(c, img_bytes, **data):
    return c.post("/api/scan", files={"image": ("a.jpg", img_bytes, "image/jpeg")},
                  data={"actions": "redness,texture", **data})


@pytest.mark.parametrize("faces,code", [([], "no_face"), ([box(10, 10, 400, 400), box(700, 10, 400, 400)],
                                                         "several_faces"), ([box(500, 600, 200, 200)], "too_far")])
def test_scan_refuses_before_anything_is_sent(m, monkeypatch, faces, code):
    yc = FakeYouCam()
    monkeypatch.setattr(m, "YouCamClient", lambda: yc)
    F.set_detector(lambda _img: faces)
    r = scan(TestClient(m.app, headers=LIVE), _jpeg(Image.new("RGB", (1200, 1600))))
    assert r.status_code == 422 and r.json()["detail"] == {"code": code, "message": F.REFUSALS[code]}
    assert yc.sent == []


def test_scan_sends_only_the_normalised_image(m, monkeypatch):
    yc = FakeYouCam()
    monkeypatch.setattr(m, "YouCamClient", lambda: yc)
    F.set_detector(lambda img: [box(300, 400, 600, 660)])
    r = scan(TestClient(m.app, headers=LIVE), _jpeg(photo_with_face()), face_ratio="0.42")
    assert r.status_code == 200
    assert yc.sent == [{"size": (480, 640), "format": "PNG", "actions": ["redness", "texture"]}]
    fp = r.json()["capture"]["fingerprint"]
    assert fp["face_ratio"] == 0.75 and fp["face_px"] == 360 and fp["face_px_original"] == 600
    assert fp["face_ratio_live"] == 0.42 and fp["original_width"] == 1200
    assert r.json()["capture"]["youcam"]["cost_units"] == 9.0


def test_detector_unavailable_refuses_the_scan(m, monkeypatch):
    yc = FakeYouCam()
    monkeypatch.setattr(m, "YouCamClient", lambda: yc)

    def broken(_img):
        raise F.DetectorUnavailable("no model")
    F.set_detector(broken)
    r = scan(TestClient(m.app, headers=LIVE), _jpeg(photo_with_face()))
    assert r.status_code == 503 and yc.sent == []


def test_trial_keeps_one_mode(m, monkeypatch):
    yc = FakeYouCam()
    monkeypatch.setattr(m, "YouCamClient", lambda: yc)
    c = TestClient(m.app, headers=LIVE)
    tid = c.post("/api/trials", json={"goal_concern": "redness", "product_id": "sr-02"}).json()["id"]
    big = photo_with_face((3000, 4000), (1000, 1200, 1000, 1000))
    F.set_detector(lambda img: [box(1000, 1200, 1000, 1000)])
    r1 = c.post("/api/scan", files={"image": ("a.jpg", _jpeg(big), "image/jpeg")},
                data={"actions": "redness", "trial_id": tid, "phase": "baseline"})
    assert r1.json()["capture"]["mode"] == "sd"
    # Asking for HD later, even with a face big enough for HD, stays SD inside this trial.
    r2 = c.post("/api/scan", files={"image": ("a.jpg", _jpeg(big), "image/jpeg")},
                data={"actions": "hd_redness", "trial_id": tid, "phase": "baseline"})
    assert r2.json()["capture"]["mode"] == "sd" and r2.json()["capture"]["actions"] == ["redness"]
    # A new scan outside any trial may use HD when the face is big enough.
    r3 = c.post("/api/scan", files={"image": ("a.jpg", _jpeg(big), "image/jpeg")}, data={"actions": "hd_redness"})
    assert r3.json()["capture"]["mode"] == "hd" and yc.sent[-1]["size"] == (1080, 1440)


def test_live_scan_refused_when_balance_cannot_pay_exact_cost(m, monkeypatch):
    """Balance 4, scan costs 9: the balance floor stops it before anything is sent."""
    monkeypatch.setenv("LIVE_SCAN_MIN_BALANCE", "0")
    yc = FakeYouCam(balance=4)
    monkeypatch.setattr(m, "YouCamClient", lambda: yc)
    F.set_detector(lambda img: [box(300, 400, 600, 660)])
    r = scan(TestClient(m.app, headers=LIVE), _jpeg(photo_with_face()))
    assert r.status_code == 200 and r.json()["capture"]["replay"]["reason"] == "balance_floor"
    assert yc.sent == []
    # The reserve check itself still refuses an unpayable scan when called on its own.
    from app.youcam import UnitReserveError, check_unit_reserve
    with pytest.raises(UnitReserveError) as e:
        check_unit_reserve(yc, 0, 9.0)
    assert "costs 9 YouCam units and 4 are left" in e.value.friendly


def test_meta_publishes_the_method():
    import app.main as main
    cap = TestClient(main.app).get("/api/meta").json()["capture"]
    assert cap["face_frac"] == 0.75 and cap["target_face_px"] == {"sd": 360, "hd": 810} and cap["upscaling"] is False


# -- unit costs ----------------------------------------------------------------------------

def test_cost_is_tiered_by_number_of_concerns():
    sd = ["redness", "texture", "acne", "pore", "oiliness", "moisture", "radiance", "age_spot", "wrinkle"]
    assert [scan_cost_from({}, "v2.1", sd[:n])[0] for n in (1, 4, 5, 8, 9)] == [9, 9, 12, 12, 14]
    assert scan_cost_from({}, "v2.1", ["hd_redness"] * 1)[0] == 12
    assert scan_cost_from({}, "v2.1", [f"hd_{a}" for a in sd[:5]])[0] == 16


def test_guard_needs_cost_plus_reserve():
    class Bal:
        def __init__(self, b):
            self.b = b

        def unit_balance(self):
            return self.b
    with pytest.raises(UnitReserveError, match="can't pay"):
        check_unit_reserve(Bal(4), 0, cost=9)
    with pytest.raises(UnitReserveError, match="below reserve"):
        check_unit_reserve(Bal(105), 100, cost=12)
    assert check_unit_reserve(Bal(112), 100, cost=12) == 112


SKUS_P1 = [{"description": "AI Photo Enhance V1.0", "amount": 2.0},
           {"description": "AI Skin Analysis V2.1 SD (1-4 concerns)", "amount": 9.0}]
SKUS_P2 = [{"description": "AI Skin Analysis V2.1 SD (5-8 concerns)", "amount": 12.0},
           {"description": "AI Skin Analysis V2.1 HD (1-4 concerns)", "amount": 12.0}]


def test_client_reads_paged_price_list(monkeypatch):
    monkeypatch.setenv("YOUCAM_API_KEY", "k")
    seen = []

    def handler(req: httpx.Request):
        seen.append(dict(req.url.params))
        tok = req.url.params.get("starting_token")
        body = {"status": 200, "result": {"skus": SKUS_P2, "next_token": None}} if tok == "p2" else \
            {"status": 200, "result": {"skus": SKUS_P1, "next_token": "p2"}}
        return httpx.Response(200, json=body)
    c = YouCamClient(transport=httpx.MockTransport(handler))
    assert c.scan_cost(["redness"]) == (9.0, "price list")
    assert c.scan_cost(["redness", "texture", "acne", "pore", "oiliness"]) == (12.0, "price list")
    assert seen == [{}, {"starting_token": "p2"}]          # read once, cached
    assert parse_skin_prices(SKUS_P1 + SKUS_P2)[("2.1", "hd")] == [(1, 4, 12.0)]


def test_built_in_prices_match_the_list_read_on_28_oct():
    assert PRICE_FALLBACK[("2.1", "sd")] == [(1, 4, 9.0), (5, 8, 12.0), (9, 12, 14.0), (13, 16, 16.0)]
    assert PRICE_FALLBACK[("2.1", "hd")] == [(1, 4, 12.0), (5, 8, 16.0), (9, 12, 20.0), (13, 16, 22.0)]


def test_baseline_place_is_stored_only_when_chosen(m, monkeypatch):
    monkeypatch.setattr(m, "YouCamClient", lambda: FakeYouCam())
    F.set_detector(lambda img: [box(300, 400, 600, 660)])
    c = TestClient(m.app, headers=LIVE)
    assert scan(c, _jpeg(photo_with_face()), place="window").json()["capture"]["place"] == "window"
    assert scan(c, _jpeg(photo_with_face())).json()["capture"]["place"] is None
    assert scan(c, _jpeg(photo_with_face()), place="kitchen").status_code == 422
