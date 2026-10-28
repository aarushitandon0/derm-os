"""Per-field comparability results (for the capture-quality screen). Same rules, structured output."""
from app import evidence as E
from app.fingerprint import Fingerprint


def cap(lum=0.55, rb=1.20, face=0.70, yaw=0.0, device="PhoneX", hour=10, mode="sd"):
    return E.Capture({"redness": 60.0}, Fingerprint(1080, 1440, lum, rb, device, hour, face, yaw, 0.0, 0.0), mode)


def test_all_fields_checked_and_passing():
    c = E.compare_conditions([cap(), cap()], [cap()])
    assert c.comparable and c.failed == []
    assert set(c.checked) == {"mode", "lighting", "face_size", "head_pose", "device", "time_of_day"}


def test_failed_fields_carry_their_reason_and_fix():
    c = E.compare_conditions([cap()], [cap(rb=1.6, face=0.5, hour=20)])
    by = {f["field"]: f for f in c.failed}
    assert set(by) == {"lighting", "face_size", "time_of_day"}
    assert by["lighting"]["reason"] in c.reasons and by["lighting"]["fix"] in c.fixes
    assert "warmer" in by["lighting"]["reason"]
    assert by["face_size"]["fix"] == "Hold the phone at the same distance: match the face outline."
    # Same reasons and fixes as before, in the same order.
    assert [f["reason"] for f in c.failed] == c.reasons


def test_missing_data_is_not_checked_rather_than_passed():
    c = E.compare_conditions([cap(device=None, hour=None, face=None, yaw=None)], [cap(device=None, hour=None)])
    assert "device" not in c.checked and "time_of_day" not in c.checked and "face_size" not in c.checked
    assert c.comparable


def test_brightness_and_colour_both_count_as_lighting():
    c = E.compare_conditions([cap()], [cap(lum=0.2, rb=1.6)])
    assert [f["field"] for f in c.failed] == ["lighting", "lighting"]


def src_cap(device, source):
    f = Fingerprint(1080, 1440, 0.55, 1.20, device, 10, 0.70, 0.0, 0.0, 0.0, device_source=source)
    return E.Capture({"redness": 60.0}, f, "sd")


def test_same_label_source_different_device_fails():
    for src in ("exif", "client"):
        c = E.compare_conditions([src_cap("A", src)], [src_cap("B", src)])
        assert not c.comparable and [f["field"] for f in c.failed] == ["device"]
        assert c.not_compared == []


def test_different_label_sources_are_not_compared_and_dont_fail():
    c = E.compare_conditions([src_cap("Acme Phone 7", "exif")], [src_cap("Front Camera · 1080×1440", "client")])
    assert c.comparable and c.failed == []
    assert "device" not in c.checked
    assert [n["field"] for n in c.not_compared] == ["device"]


def test_mixed_sources_within_one_side_are_not_compared():
    c = E.compare_conditions([src_cap("A", "exif"), src_cap("Front", "client")], [src_cap("Front", "client")])
    assert c.comparable and "device" not in c.checked and c.not_compared


def test_old_label_without_source_counts_as_exif():
    # Before device_source existed the label only ever came from EXIF.
    c = E.compare_conditions([src_cap("Acme Phone 7", None)], [src_cap("Acme Phone 8", "exif")])
    assert [f["field"] for f in c.failed] == ["device"]
