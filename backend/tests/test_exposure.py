"""EXIF exposure in the comparability fingerprint (B12).

Two properties are what matter, and each has its own test:

  * STRICTER ONLY. Adding this check can turn a comparable pair into a non-comparable one. It can
    never do the reverse, so every pair that failed before still fails.
  * MISSING EXIF IS NEVER A PASS. A photo with no exposure data doesn't get waved through: the
    check simply doesn't run, and every other measure still has to hold.

New cases only.
"""
import io

import pytest
from PIL import Image
from PIL.TiffImagePlugin import IFDRational

from app import evidence as E
from app import fingerprint as FP
from app.fingerprint import Fingerprint

# The three EXIF tags, by number, exactly as app/fingerprint.py reads them.
TAG_EXPOSURE_TIME = 0x829A
TAG_FNUMBER = 0x829D
TAG_ISO = 0x8827
IFD_EXIF = 0x8769


def photo(exposure=None, fnumber=None, iso=None, colour=(200, 160, 140), size=(640, 800)) -> bytes:
    """A plain JPEG, optionally carrying the three exposure tags and nothing else.
    Written with Pillow's own Exif object, the way the other tests build test photos."""
    e = Image.Exif()
    sub = e.get_ifd(IFD_EXIF)
    if exposure is not None:
        sub[TAG_EXPOSURE_TIME] = IFDRational(*exposure) if isinstance(exposure, tuple) else exposure
    if fnumber is not None:
        sub[TAG_FNUMBER] = IFDRational(*fnumber) if isinstance(fnumber, tuple) else fnumber
    if iso is not None:
        sub[TAG_ISO] = iso
    b = io.BytesIO()
    Image.new("RGB", size, colour).save(b, "JPEG", exif=e)
    return b.getvalue()


def ev_of(**kw) -> float | None:
    with Image.open(io.BytesIO(photo(**kw))) as im:
        return FP.exposure_ev(im)


def fp(ev=None, lum=0.55, rb=1.20, face=0.70, device="PhoneX", hour=10) -> Fingerprint:
    f = Fingerprint(1080, 1440, lum, rb, device, hour, face, 0.0, 0.0, 0.0)
    f.exposure_ev = ev
    return f


def cap(ev=None, score=60.0, **kw) -> E.Capture:
    return E.Capture({"redness": score}, fp(ev=ev, **kw), "sd", ("redness",))


def gate(base_ev, follow_ev, **kw) -> E.Comparability:
    return E.compare_conditions([cap(base_ev, **kw), cap(base_ev, **kw)],
                                [cap(follow_ev, **kw), cap(follow_ev, **kw)])


# ---------------------------------------------------------------- reading the tags
def test_ev_is_read_from_the_three_tags():
    # f/2.0, 1/125 s, ISO 100 -> log2(4 * 125) = 8.966
    assert ev_of(exposure=(1, 125), fnumber=(2, 1), iso=100) == pytest.approx(8.966, abs=0.01)


def test_a_higher_iso_means_the_scene_was_darker():
    bright = ev_of(exposure=(1, 125), fnumber=(2, 1), iso=100)
    dim = ev_of(exposure=(1, 125), fnumber=(2, 1), iso=800)
    assert dim < bright
    assert bright - dim == pytest.approx(3.0, abs=0.01)   # ISO 100 -> 800 is 3 stops


def test_a_longer_exposure_means_the_scene_was_darker():
    assert ev_of(exposure=(1, 30), fnumber=(2, 1), iso=100) < ev_of(exposure=(1, 250), fnumber=(2, 1), iso=100)


def test_a_smaller_aperture_means_the_scene_was_brighter():
    assert ev_of(exposure=(1, 125), fnumber=(8, 1), iso=100) > ev_of(exposure=(1, 125), fnumber=(2, 1), iso=100)


@pytest.mark.parametrize("kw", [
    {},                                                   # no EXIF at all (a canvas JPEG)
    {"exposure": (1, 125)},                               # exposure only
    {"fnumber": (2, 1)},                                  # aperture only
    {"iso": 100},                                         # ISO only
    {"exposure": (1, 125), "fnumber": (2, 1)},            # no ISO
    {"exposure": (1, 125), "iso": 100},                   # no aperture
    {"fnumber": (2, 1), "iso": 100},                      # no exposure time
])
def test_any_missing_tag_means_no_value_rather_than_a_guess(kw):
    assert ev_of(**kw) is None


@pytest.mark.parametrize("kw", [
    {"exposure": (0, 125), "fnumber": (2, 1), "iso": 100},    # zero exposure time
    {"exposure": (1, 125), "fnumber": (0, 1), "iso": 100},    # zero aperture
    {"exposure": (1, 125), "fnumber": (2, 1), "iso": 0},      # zero ISO
])
def test_nonsense_values_return_no_value_rather_than_raising(kw):
    assert ev_of(**kw) is None


def test_the_fingerprint_carries_the_exposure(tmp_path):
    p = tmp_path / "a.jpg"
    p.write_bytes(photo(exposure=(1, 125), fnumber=(2, 1), iso=100))
    assert FP.measure(p).exposure_ev == pytest.approx(8.966, abs=0.01)


def test_a_photo_with_no_exif_has_no_exposure_on_its_fingerprint(tmp_path):
    p = tmp_path / "a.jpg"
    p.write_bytes(photo())
    assert FP.measure(p).exposure_ev is None


def test_exposure_comes_from_the_original_when_a_normalised_copy_is_measured(tmp_path):
    """The normalised capture is re-encoded from pixels, so it has no EXIF of its own."""
    orig = tmp_path / "orig.jpg"
    orig.write_bytes(photo(exposure=(1, 125), fnumber=(2, 1), iso=100))
    norm = tmp_path / "norm.png"
    Image.new("RGB", (480, 640), (200, 160, 140)).save(norm)
    got = FP.measure(norm, exif_path=orig)
    assert got.exposure_ev == pytest.approx(8.966, abs=0.01)


def test_exposure_survives_a_round_trip_through_a_dict():
    f = fp(ev=8.5)
    assert Fingerprint.from_dict(f.to_dict()).exposure_ev == 8.5


def test_a_fingerprint_saved_before_exposure_existed_still_loads():
    old = {"width": 1080, "height": 1440, "luminance": 0.5, "red_blue_ratio": 1.2}
    assert Fingerprint.from_dict(old).exposure_ev is None


# ---------------------------------------------------------------- the gate: stricter only
def test_matching_exposure_is_comparable_and_reported_as_checked():
    c = gate(8.9, 8.9)
    assert c.comparable is True
    assert "exposure" in c.checked


def test_a_small_exposure_difference_is_still_comparable():
    c = gate(8.9, 9.9)      # 1 stop, inside the named constant
    assert c.comparable is True


def test_exposure_beyond_the_named_constant_is_not_comparable():
    c = gate(8.9, 11.0)     # 2.1 stops apart
    assert c.comparable is False
    assert any(f["field"] == "exposure" for f in c.failed)
    assert "metered very different light" in " ".join(c.reasons)
    assert c.fixes


def test_the_tolerance_is_a_named_constant_and_not_in_tolerances():
    """TOLERANCES is unchanged on purpose: this check is additional, not a tuning of the old ones."""
    assert E.EXPOSURE_EV_TOLERANCE == 1.5
    assert "exposure_ev" not in E.TOLERANCES
    assert set(E.TOLERANCES) == {"luminance", "red_blue_ratio", "face_ratio", "angle", "hour"}


def test_the_boundary_is_inclusive():
    assert gate(8.0, 8.0 + E.EXPOSURE_EV_TOLERANCE).comparable is True
    assert gate(8.0, 8.0 + E.EXPOSURE_EV_TOLERANCE + 0.01).comparable is False


def test_exposure_catches_a_light_change_that_pixel_brightness_hides():
    """This is the whole point: auto-exposure brightened a dim room back to a normal-looking
    photo, so luminance matches while the light did not."""
    base = [E.Capture({"redness": 60.0}, fp(ev=9.0, lum=0.55), "sd", ("redness",))] * 2
    follow = [E.Capture({"redness": 60.0}, fp(ev=5.0, lum=0.55), "sd", ("redness",))] * 2
    lum_only = E.compare_conditions(base, follow, tol={**E.TOLERANCES, "exposure_ev": 99})
    with_exposure = E.compare_conditions(base, follow)
    assert lum_only.comparable is True, "luminance alone cannot see this"
    assert with_exposure.comparable is False
    assert [f["field"] for f in with_exposure.failed] == ["exposure"]


def test_the_check_can_only_add_a_mismatch_never_remove_one():
    """Stricter only: a pair that already failed on something else still fails, whatever the
    exposure says, and a pair that passes everything else can only be made to fail."""
    # Already failing on light colour, with identical exposure.
    base = [cap(9.0, rb=1.2)] * 2
    follow = [cap(9.0, rb=2.2)] * 2
    assert E.compare_conditions(base, follow).comparable is False
    # Passing everything else, with exposure far apart.
    assert gate(9.0, 4.0).comparable is False
    # Passing everything else, with exposure close.
    assert gate(9.0, 9.2).comparable is True


@pytest.mark.parametrize("base_ev,follow_ev", [(None, None), (9.0, None), (None, 9.0)])
def test_missing_exposure_never_fails_and_never_passes_the_pair_on_its_own(base_ev, follow_ev):
    c = gate(base_ev, follow_ev)
    # It does not fail the pair...
    assert not any(f["field"] == "exposure" for f in c.failed)
    # ...and it is not counted as a matching field either.
    assert "exposure" not in c.checked


def test_only_one_side_having_exposure_is_reported_as_not_compared():
    c = gate(9.0, None)
    assert any(x["field"] == "exposure" for x in c.not_compared)
    assert "not counted as a match" in " ".join(x["reason"] for x in c.not_compared)


def test_missing_exposure_does_not_rescue_a_pair_that_fails_elsewhere():
    """"Missing EXIF never counts as a pass": every other measure still has to hold."""
    base = [cap(None, lum=0.55)] * 2
    follow = [cap(None, lum=0.20)] * 2
    c = E.compare_conditions(base, follow)
    assert c.comparable is False
    assert any(f["field"] == "lighting" for f in c.failed)


def test_a_comparable_pair_with_no_exposure_is_still_comparable():
    """The check is additional. With nothing to read it must not block a pair that was fine."""
    assert gate(None, None).comparable is True


# ---------------------------------------------------------------- it reaches the verdict
def test_an_exposure_mismatch_makes_the_verdict_not_comparable():
    base = [cap(9.0, score=60.0), cap(9.0, score=61.0)]
    follow = [cap(4.0, score=75.0), cap(4.0, score=76.0)]
    r = E.evaluate(base, follow, E.TrialContext(), concerns=["redness"])
    assert r.verdict == E.Verdict.NOT_COMPARABLE
    assert "different conditions" in r.message


def test_the_same_scores_with_matching_exposure_do_read_as_a_move():
    base = [cap(9.0, score=60.0), cap(9.0, score=61.0)]
    follow = [cap(9.0, score=75.0), cap(9.0, score=76.0)]
    r = E.evaluate(base, follow, E.TrialContext(), concerns=["redness"])
    assert r.verdict == E.Verdict.MOVED
