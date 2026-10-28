"""Experiment scripts: --no-change-prefix / --shift-prefix, report labels, and HEIC through the
app's own decode path. Synthetic images (HEIC encoded in the test), a stand-in detector and a
fake YouCam client: no network, no real photos, no units."""
import io
import json
import socket
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from PIL import Image

from app import facecrop as F
from app import photometa as P
from scripts import analyze_experiment as AX
from scripts import run_experiments as rx
from tests.test_analyze_experiment import LAMP_FP, WINDOW_FP, save_shot
from tests.test_experiment_scripts import FakeClient, detector, make_photo, result

BACKEND = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("no network in these tests")
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)


def exif(when: datetime, orientation: int | None = None) -> bytes:
    ex = Image.Exif()
    ex[0x010F], ex[0x0110] = "Acme", "Phone 7"
    ex.get_ifd(0x8769)[0x9003] = when.strftime("%Y:%m:%d %H:%M:%S")
    if orientation:
        ex[0x0112] = orientation
    return ex.tobytes()


def jpeg_with_exif(path: Path, when: datetime, shade=0, size=(900, 1200)) -> Path:
    tmp = make_photo(path.with_suffix(".tmp.png"), size=size, shade=shade)
    with Image.open(tmp) as im:
        im.save(path, "JPEG", quality=95, exif=exif(when))
    tmp.unlink()
    return path


def heic(path: Path, size=(900, 1200), orientation: int | None = None, when: datetime | None = None) -> Path:
    pytest.importorskip("pillow_heif")
    im = make_photo(path.with_suffix(".tmp.png"), size=size)
    with Image.open(im) as src:
        src = src.copy()
    src.paste((20, 40, 220), (0, 0, size[0], size[1] // 8))      # a band along the stored TOP edge
    kw = {"exif": exif(when or datetime(2026, 10, 28, 21, 0), orientation)}
    src.save(path, format="HEIF", quality=-1, **kw)
    im.unlink()
    return path


def run(folder, out, client=None, extra=(), det=None):
    return rx.main([str(folder), "--out", str(out), *extra], detect=det or detector(), client=client)


# -- prefixes -------------------------------------------------------------------------------

def test_prefixes_read_only_the_two_named_conditions(tmp_path, capsys):
    folder = tmp_path / "p"
    for i in (1, 2, 3):
        make_photo(folder / f"white_{i}.png", shade=i)
    for i in (1, 2):
        make_photo(folder / f"warm_{i}.png", shade=40 + i)
    make_photo(folder / "window_1.png")
    client = FakeClient([], balance=1004)
    assert run(folder, tmp_path / "r", client, ["--dry-run", "--no-change-prefix", "white",
                                                "--shift-prefix", "warm"]) == 0
    out = capsys.readouterr().out
    assert "Ignored (not white_N or warm_N): window" in out
    assert "Cost: 5 live scan(s) x 9 units" in out and client.sent == []


def test_defaults_are_still_window_and_lamp(tmp_path, capsys):
    folder = tmp_path / "p"
    make_photo(folder / "white_1.png")
    assert run(folder, tmp_path / "r", FakeClient([]), ["--dry-run"]) == 1
    assert "No photos named window_N or lamp_N" in capsys.readouterr().out


def test_same_prefix_twice_is_refused(tmp_path, capsys):
    folder = tmp_path / "p"
    make_photo(folder / "white_1.png")
    assert run(folder, tmp_path / "r", FakeClient([]), ["--no-change-prefix", "white",
                                                        "--shift-prefix", "white"]) == 1
    assert "must differ" in capsys.readouterr().out


def test_pilot_only_finds_photos_of_the_two_prefixes(tmp_path, capsys):
    folder = tmp_path / "p"
    make_photo(folder / "white_1.png")
    make_photo(folder / "window_1.png")
    client = FakeClient([result({"redness": 50.0})], balance=1004)
    assert run(folder, tmp_path / "r", client, ["--only", "window_1", "--no-change-prefix", "white",
                                                "--shift-prefix", "warm"]) == 1
    assert client.sent == []


def test_full_run_report_uses_light_labels_and_states_the_setup(tmp_path, capsys):
    folder, out = tmp_path / "p", tmp_path / "r"
    t0 = datetime(2026, 10, 28, 21, 0, 0)
    for i in range(1, 4):
        jpeg_with_exif(folder / f"white_{i}.jpg", t0 + timedelta(minutes=i), shade=i)
    for i in range(1, 3):
        jpeg_with_exif(folder / f"warm_{i}.jpg", t0 + timedelta(minutes=20 + i), shade=40 + i)
    # File order is warm_1, warm_2, white_1..3: warm gets 60, 61 and white 50, 51, 52.
    client = FakeClient([result({"redness": float(s)}) for s in (60, 61, 50, 51, 52)], balance=1004)
    assert run(folder, out, client, ["--no-change-prefix", "white", "--shift-prefix", "warm"]) == 0
    md = (out / "report.md").read_text(encoding="utf-8")
    assert "Setup: one sitting (EXIF capture times span 21 minutes), every indoor white light photo taken " \
           "before every warm light photo; indoor light; n=3 indoor white light, n=2 warm light; " \
           "same phone (one EXIF camera model on every photo)." in md
    assert "## Experiment 1: 3 scans, nothing changed (indoor white light)" in md
    assert "## Experiment 2: indoor white light vs warm light (n=3 vs 2)" in md
    assert "### d) Lighting: indoor white light vs warm light (n=3 vs 2)" in md
    assert "same indoor white light" in md and "Under warm light (2 photos)" in md
    low = md.lower()
    assert "window" not in low and "lamp" not in low                 # never the old labels
    assert "Acme" not in md and "Phone 7" not in md                  # the camera is not named
    fc = json.loads((out / "false_change.json").read_text())
    assert fc["conditions"] == {"no_change": "white", "shift": "warm"}


def test_setup_line_does_not_claim_one_sitting_when_times_are_far_apart(tmp_path):
    folder = tmp_path / "p"
    t0 = datetime(2026, 10, 28, 9, 0)
    jpeg_with_exif(folder / "white_1.jpg", t0)
    jpeg_with_exif(folder / "warm_1.jpg", t0 + timedelta(hours=12))
    make_photo(folder / "warm_2.png")    # no EXIF time
    items, _, _ = rx.prepare(rx.group_photos(folder), detector(), False)
    line = rx.setup_line(items, "white", "warm")
    assert "one sitting" not in line and "capture time not recorded on 1 of 3 photos" in line
    line2 = rx.setup_line([i for i in items if i.path.suffix == ".jpg"], "white", "warm")
    assert "not one sitting: EXIF capture times span 720 minutes" in line2


def test_analysis_reads_only_the_named_prefixes(tmp_path, capsys):
    r = tmp_path / "r"
    for i, v in enumerate([60, 61, 62], 1):
        save_shot(r, f"white_{i}", {"redness": v}, WINDOW_FP)
    for i, v in enumerate([50, 51], 1):
        save_shot(r, f"warm_{i}", {"redness": v}, LAMP_FP)
    (r / "window_1.json").write_text("{}")      # another shoot, no fingerprint: must not be read
    assert AX.main(["--results", str(r), "--no-change-prefix", "white", "--shift-prefix", "warm"]) == 0
    md = (r / "report.md").read_text(encoding="utf-8")
    assert "n=3 indoor white light photos" in md and "indoor white light vs warm light" in md
    assert "window" not in md.split(AX.START)[1].lower()
    # The same folder with the default prefixes finds no white/warm and writes nothing new.
    assert AX.run(r, no_change="window", shift="lamp") == 1


# -- HEIC -----------------------------------------------------------------------------------

def test_heic_extensions_match_case_insensitively(tmp_path):
    folder = tmp_path / "p"
    for name in ("white_1.HEIC", "white_2.heic", "warm_1.HeIf", "warm_2.JPG", "notes.txt"):
        (folder / name).parent.mkdir(parents=True, exist_ok=True)
        (folder / name).write_bytes(b"x")
    g = rx.group_photos(folder)
    assert sorted(p.name for p in g["white"]) == ["white_1.HEIC", "white_2.heic"]
    assert sorted(p.name for p in g["warm"]) == ["warm_1.HeIf", "warm_2.JPG"]


def test_heic_is_decoded_upright_to_8bit_rgb_by_the_apps_path(tmp_path):
    path = heic(tmp_path / "p" / "white_1.HEIC", size=(1200, 1600), orientation=6)
    # Upright it is landscape (1600x1200), so the stand-in face is narrower to leave room for a 3:4 crop.
    items, mode, _ = rx.prepare({"white": [path]}, detector(frac=0.3), False)
    it = items[0]
    assert it.ok and mode == "sd" and it.bit_depth == 8
    assert it.notes["source_mode"] == "RGB" and not it.notes["reduced_colour"]
    assert it.notes["size"] == [1600, 1200]                     # orientation 6 applied exactly once
    assert it.meta.taken_at == datetime(2026, 10, 28, 21, 0)    # EXIF time read from the HEIC
    # The script and the app decode identically: same function, same pixels.
    app_img, _ = F.open_upright(path.read_bytes())
    script_img, _ = F.open_upright(str(path))
    assert app_img.mode == "RGB" and app_img.tobytes() == script_img.tobytes()
    assert P.check_file(path.read_bytes()) == "heic"
    # The band on the stored top edge is on the right after turning upright (not the left: no double turn).
    right = app_img.getpixel((app_img.width - 3, app_img.height // 2))
    left = app_img.getpixel((2, app_img.height // 2))
    assert right[2] > 180 and left[2] < 180


def test_ten_bit_heic_is_reported_and_converted_to_8bit_rgb(tmp_path):
    pillow_heif = pytest.importorskip("pillow_heif")
    import numpy as np
    a = np.full((1200, 900, 3), 40000, dtype=np.uint16)
    path = tmp_path / "p" / "white_1.heic"
    path.parent.mkdir(parents=True)
    pillow_heif.from_bytes(mode="RGB;16", size=(900, 1200), data=a.tobytes()).save(str(path), quality=-1)
    assert rx.source_bit_depth(path) == 10
    img, notes = F.open_upright(str(path))
    assert img.mode == "RGB" and notes["source_mode"] == "RGB"
    assert abs(img.getpixel((450, 600))[0] - round(40000 / 65535 * 255)) <= 2


def test_heic_decoder_is_registered_in_one_place_only():
    hits = [p.relative_to(BACKEND).as_posix() for d in ("app", "scripts") for p in (BACKEND / d).rglob("*.py")
            if "register_heif_opener" in p.read_text(encoding="utf-8")]
    assert hits == ["app/photometa.py"]


# -- the crop sent to YouCam --------------------------------------------------------------

@pytest.mark.parametrize("kind", ["heic", "jpeg", "png"])
def test_crop_sent_to_youcam_is_lossless_png_of_the_normalised_pixels(tmp_path, kind):
    folder = tmp_path / "p"
    if kind == "heic":
        src = heic(folder / "white_1.HEIC")
    elif kind == "jpeg":
        src = jpeg_with_exif(folder / "white_1.jpg", datetime(2026, 10, 28, 21, 0))
    else:
        src = make_photo(folder / "white_1.png", size=(900, 1200))
    items, _, _ = rx.prepare({"white": [src]}, detector(), False)
    sent = items[0].png
    assert sent[:8] == b"\x89PNG\r\n\x1a\n"
    with Image.open(io.BytesIO(sent)) as im:
        im.load()
        assert im.format == "PNG" and im.mode == "RGB" and im.size == (480, 640)
        assert not P.has_metadata(sent)
        img, _ = F.open_upright(str(src))
        expected = F.normalise(img, detector()(img), "sd").image
        assert im.tobytes() == expected.tobytes()               # lossless: exactly the crop's pixels
