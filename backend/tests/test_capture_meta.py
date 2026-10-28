"""Capture time and device from the phone, used only when the photo has no EXIF. Gate rules unchanged."""
import importlib
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import evidence as E
from app.fingerprint import Fingerprint, clean_device_label, measure

LIVE = {"X-Live-Passcode": "test-passcode"}  # live scans need it; see app/guard.py


def photo(path=None, exif=False):
    im = Image.new("RGB", (720, 960), (200, 160, 140))
    kw = {}
    if exif:
        ex = Image.Exif()
        ex[0x010F] = "Acme"                 # Make
        ex[0x0110] = "Phone 7"              # Model
        ex[0x0132] = "2026:10:28 07:15:00"  # DateTime
        kw["exif"] = ex
    if path:
        im.save(path, "JPEG", **kw)
        return path
    b = io.BytesIO()
    im.save(b, "JPEG", **kw)
    return b.getvalue()


def test_client_values_used_when_exif_missing(tmp_path):
    fp = measure(photo(tmp_path / "a.jpg"), client_hour=21, client_device="Front Camera · 1080×1440")
    assert fp.captured_hour == 21 and fp.hour_source == "client"
    assert fp.device == "Front Camera · 1080×1440" and fp.device_source == "client"


def test_exif_wins_over_client(tmp_path):
    fp = measure(photo(tmp_path / "a.jpg", exif=True), client_hour=21, client_device="Front Camera")
    assert fp.device == "Acme Phone 7" and fp.device_source == "exif"
    assert fp.captured_hour == 7 and fp.hour_source == "exif"


def test_still_not_recorded_without_either(tmp_path):
    fp = measure(photo(tmp_path / "a.jpg"))
    assert fp.device is None and fp.captured_hour is None
    assert fp.device_source is None and fp.hour_source is None
    other = Fingerprint(720, 960, fp.luminance, fp.red_blue_ratio)
    c = E.compare_conditions([E.Capture({"redness": 60}, fp)], [E.Capture({"redness": 60}, other)])
    assert "device" not in c.checked and "time_of_day" not in c.checked


def test_device_label_is_cleaned_and_capped():
    assert clean_device_label("Front\x00 Camera\n\t· 1080×1440") == "Front Camera · 1080×1440"
    assert len(clean_device_label("x" * 500)) == 80
    assert clean_device_label("   ") is None and clean_device_label(None) is None


def test_old_fingerprints_without_source_fields_still_load():
    fp = Fingerprint.from_dict({"width": 1, "height": 1, "luminance": 0.5, "red_blue_ratio": 1.0, "short_side": 1})
    assert fp.device_source is None and fp.hour_source is None


def test_gate_uses_client_values_with_unchanged_rules(tmp_path):
    def cap(hour, dev):
        return E.Capture({"redness": 60}, measure(photo(tmp_path / "p.jpg"), 0.7, 0, 0, 0, hour, dev))
    base = [cap(9, "Front Camera · 1080×1440"), cap(9, "Front Camera · 1080×1440")]
    same = E.compare_conditions(base, [cap(10, "Front Camera · 1080×1440")])
    assert same.comparable and {"device", "time_of_day"} <= set(same.checked)
    diff = E.compare_conditions(base, [cap(9 + E.TOLERANCES["hour"] + 1, "Back Camera · 3024×4032")])
    assert {f["field"] for f in diff.failed} == {"device", "time_of_day"}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DERMOS_DB", str(tmp_path / "t.db"))
    monkeypatch.setenv("DERMOS_MEDIA", str(tmp_path / "media"))
    import app.main as m
    importlib.reload(m)
    from app.youcam import normalize

    class Fake:
        def analyze(self, path, actions):
            return normalize({"data": {"results": {"output": [{"type": "redness", "raw_score": 60}]}}},
                             "sd", actions, None)
    monkeypatch.setattr(m, "YouCamClient", lambda: Fake())
    return TestClient(m.app, headers=LIVE)


def post(c, img, **data):
    return c.post("/api/scan", files={"image": ("a.jpg", img, "image/jpeg")}, data={"actions": "redness", **data})


def test_scan_records_client_hour_and_device(client):
    fp = post(client, photo(), client_hour="8", client_device="Front Camera · 1080×1440").json()["capture"]["fingerprint"]
    assert fp["captured_hour"] == 8 and fp["hour_source"] == "client"
    assert fp["device"] == "Front Camera · 1080×1440" and fp["device_source"] == "client"


def test_scan_without_client_values_stays_not_recorded(client):
    fp = post(client, photo()).json()["capture"]["fingerprint"]
    assert fp["captured_hour"] is None and fp["device"] is None


def test_scan_prefers_exif(client):
    fp = post(client, photo(exif=True), client_hour="22", client_device="Front Camera").json()["capture"]["fingerprint"]
    assert fp["device"] == "Acme Phone 7" and fp["captured_hour"] == 7


@pytest.mark.parametrize("hour", ["24", "-1", "noon"])
def test_scan_rejects_invalid_hour(client, hour):
    assert post(client, photo(), client_hour=hour).status_code == 422
