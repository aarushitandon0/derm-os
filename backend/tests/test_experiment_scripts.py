"""Experiment scripts: .env loading, crop rule, face-size check, stop-on-rejection and
report gating. Synthetic images, a fake detector and a fake YouCam client: no network,
no real photos, no units."""
import json
import os
from pathlib import Path

import pytest
from PIL import Image

from app.youcam import SkinResult, YouCamError, normalize
from scripts import crop_faces, run_experiments as rx
from scripts.face_tools import Box, CropError, plan_crop


# -- helpers -------------------------------------------------------------------------------

def make_photo(path: Path, size=(1200, 1600), mode="P") -> Path:
    im = Image.new("RGB", size)
    # A gradient so pixel-identity checks mean something.
    im.putdata([((x * 7) % 256, (y * 3) % 256, (x + y) % 256) for y in range(size[1]) for x in range(size[0])])
    if mode == "P":
        im = im.quantize(64)
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path)
    return path


def fake_detector(faces_by_name: dict[str, list[Box]], default: list[Box] | None = None):
    """Faces for originals by file name; for anything else (a crop) a face filling 75%."""
    def detect(path):
        path = Path(path)
        with Image.open(path) as im:
            w, h = im.size
        if path.parent.name == "cropped":
            return (w, h), [Box(int(w * 0.125), int(h * 0.3), int(w * 0.75), int(w * 0.8))]
        return (w, h), faces_by_name.get(path.name, default or [])
    return detect


def result(scores: dict[str, float]) -> SkinResult:
    """A YouCam task response in the documented JSON shape (no mask URLs)."""
    payload = {"status": 200, "data": {"task_status": "success", "results": {"output": [
        {"type": k, "ui_score": v, "raw_score": v, "mask_urls": []} for k, v in scores.items()]}}}
    return normalize(payload, "sd", list(scores), "task-1")


class FakeClient:
    version = "v2.1"
    upload_http = None

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.sent = []
        self.deleted = []

    def unit_balance(self):
        return 42.0

    def analyze(self, path, actions):
        self.sent.append(Path(path).name)
        out = self.outcomes.pop(0)
        if isinstance(out, Exception):
            raise out
        return out

    def delete_task(self, task_id):
        self.deleted.append(task_id)
        return {}


def face_too_small():
    return YouCamError("Task failed", code="error_src_face_too_small",
                       friendly="Move closer: your face should fill at least 60% of the frame width.")


def photo_set(folder: Path, n_window=2, n_lamp=1) -> Path:
    for i in range(1, n_window + 1):
        make_photo(folder / f"window_{i}.png", (600, 800), "RGB")
    for i in range(1, n_lamp + 1):
        make_photo(folder / f"lamp_{i}.png", (600, 800), "RGB")
    return folder


# -- .env loading --------------------------------------------------------------------------

def test_env_file_is_skipped_in_tests(tmp_path):
    env = tmp_path / ".env"
    env.write_text("DERMOS_TEST_ONLY_VAR=from-file\n")
    assert os.environ.get("DERMOS_NO_DOTENV") == "1"
    assert rx.load_env_file(env) is False
    assert "DERMOS_TEST_ONLY_VAR" not in os.environ


def test_env_file_loads_when_allowed_and_shell_wins(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("DERMOS_TEST_ONLY_VAR=from-file\nDERMOS_TEST_SHELL_VAR=from-file\n")
    monkeypatch.delenv("DERMOS_NO_DOTENV")
    monkeypatch.setenv("DERMOS_TEST_ONLY_VAR", "x")   # registers clean-up, then remove
    monkeypatch.delenv("DERMOS_TEST_ONLY_VAR")
    monkeypatch.setenv("DERMOS_TEST_SHELL_VAR", "from-shell")
    assert rx.load_env_file(env) is True
    assert os.environ["DERMOS_TEST_ONLY_VAR"] == "from-file"
    assert os.environ["DERMOS_TEST_SHELL_VAR"] == "from-shell"


def test_missing_key_gives_clear_message_and_no_report(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("YOUCAM_API_KEY", raising=False)
    folder = photo_set(tmp_path / "p")
    out = tmp_path / "results"
    assert rx.main([str(folder), "--out", str(out)]) == 1
    msg = capsys.readouterr().out
    assert "Cannot start a live run" in msg and "DERMOS_NO_DOTENV=1" in msg
    assert not (out / "report.md").exists()


# -- crop geometry -------------------------------------------------------------------------

def test_plan_crop_is_3_by_4_centred_with_face_at_75_percent():
    face = Box(900, 1000, 930, 1100)
    p = plan_crop(2316, 3088, face, 0.75)
    assert p.width * 4 == p.height * 3
    assert p.face_pct_after == pytest.approx(75.0, abs=0.3)
    assert abs((p.left + p.width / 2) - face.cx) <= 1 and abs((p.top + p.height / 2) - face.cy) <= 1
    assert not p.clamped and face.inside(p.left, p.top, p.width, p.height)


def test_plan_crop_shifts_inside_bounds_without_resizing():
    face = Box(10, 20, 900, 1000)          # face near the top-left corner
    p = plan_crop(2316, 3088, face, 0.75)
    assert (p.left, p.top) == (0, 0) and p.clamped
    assert p.width == 1200 and p.height == 1600


def test_plan_crop_refuses_when_crop_cannot_fit():
    with pytest.raises(CropError, match="does not fit"):
        plan_crop(1000, 1200, Box(100, 100, 800, 800), 0.75)


def test_plan_crop_refuses_below_sd_short_side_instead_of_upscaling():
    with pytest.raises(CropError, match="480px"):
        plan_crop(2316, 3088, Box(1000, 1000, 300, 300), 0.75)


# -- crop_faces.py -------------------------------------------------------------------------

def test_crop_faces_moves_originals_crops_same_names_and_logs(tmp_path):
    photos = tmp_path / "photos"
    a = make_photo(photos / "window_1.png")
    b = make_photo(photos / "lamp_1.png")
    original_bytes = {p.name: p.read_bytes() for p in (a, b)}
    (photos / "notes.HEIC").write_bytes(b"not an image we process")
    det = fake_detector({}, default=[Box(400, 500, 480, 520)])

    log = crop_faces.run(photos, det, 0.75)

    raw, cropped = photos / "raw", photos / "cropped"
    assert sorted(p.name for p in raw.iterdir()) == ["lamp_1.png", "window_1.png"]
    assert {p.name: p.read_bytes() for p in raw.iterdir()} == original_bytes   # untouched
    assert (photos / "notes.HEIC").exists()                                  # other files left alone
    assert sorted(p.name for p in cropped.glob("*.png")) == ["lamp_1.png", "window_1.png"]
    for e in log["photos"]:
        assert e["ok"] and e["pixels_identical_to_source"]
        assert e["output_size"][0] * 4 == e["output_size"][1] * 3
        assert e["face_pct_after_planned"] == pytest.approx(75.0, abs=0.3)
        assert e["face_pct_before"] == 40.0
        with Image.open(cropped / e["file"]) as c, Image.open(raw / e["file"]) as o:
            assert c.mode == o.mode == "P"                                    # no colour conversion
            assert c.convert("RGB").tobytes() == o.crop(tuple(e["crop_box"])).convert("RGB").tobytes()
    saved = json.loads((cropped / "crop_log.json").read_text())
    assert saved["rule"]["face_width_fraction_of_crop"] == 0.75 and saved["rule"]["aspect"] == "3:4"


def test_crop_faces_refuses_zero_or_many_faces_and_says_which(tmp_path):
    photos = tmp_path / "photos"
    for n in ("window_1.png", "window_2.png", "window_3.png"):
        make_photo(photos / n)
    det = fake_detector({"window_1.png": [],
                         "window_2.png": [Box(100, 100, 300, 300), Box(700, 100, 300, 300)],
                         "window_3.png": [Box(400, 500, 480, 520)]})
    log = crop_faces.run(photos, det, 0.75)
    by = {e["file"]: e for e in log["photos"]}
    assert not by["window_1.png"]["ok"] and by["window_1.png"]["reason"] == "no face found"
    assert not by["window_2.png"]["ok"] and "2 faces" in by["window_2.png"]["reason"]
    assert by["window_3.png"]["ok"]
    assert sorted(p.name for p in (photos / "cropped").glob("*.png")) == ["window_3.png"]


def test_crop_faces_never_overwrites_an_original_already_in_raw(tmp_path):
    photos = tmp_path / "photos"
    make_photo(photos / "raw" / "window_1.png")
    first = (photos / "raw" / "window_1.png").read_bytes()
    make_photo(photos / "window_1.png", (1300, 1700))
    raw, moved, kept = crop_faces.move_originals(photos)
    assert moved == [] and kept == ["window_1.png"]
    assert (photos / "raw" / "window_1.png").read_bytes() == first
    assert (photos / "window_1.png").exists()


def test_crop_faces_refuses_rotated_exif(tmp_path):
    photos = tmp_path / "photos"
    p = photos / "window_1.jpg"
    photos.mkdir()
    im = Image.new("RGB", (1200, 1600))
    exif = im.getexif()
    exif[0x0112] = 6
    im.save(p, exif=exif)
    log = crop_faces.run(photos, fake_detector({}, default=[Box(400, 500, 480, 520)]), 0.75)
    assert not log["photos"][0]["ok"] and "orientation" in log["photos"][0]["reason"]


# -- dry-run face check --------------------------------------------------------------------

def test_face_check_flags_under_60_percent_and_bad_face_counts(tmp_path):
    paths = [make_photo(tmp_path / n, (1000, 1000), "RGB") for n in ("a.png", "b.png", "c.png", "d.png")]
    det = fake_detector({"a.png": [Box(0, 0, 750, 750)], "b.png": [Box(0, 0, 400, 400)],
                         "c.png": [], "d.png": [Box(0, 0, 700, 700), Box(0, 0, 100, 100)]})
    rows = {r["file"]: r for r in rx.face_check(paths, det)}
    assert rows["a.png"]["ok"] and rows["a.png"]["face_pct"] == 75.0
    assert not rows["b.png"]["ok"] and rows["b.png"]["face_pct"] == 40.0
    assert not rows["c.png"]["ok"] and rows["c.png"]["faces"] == 0
    assert not rows["d.png"]["ok"] and rows["d.png"]["faces"] == 2


def test_dry_run_prints_face_table_and_sends_nothing(tmp_path, capsys):
    folder = photo_set(tmp_path / "p")
    client = FakeClient([])
    det = fake_detector({}, default=[Box(0, 0, 240, 260)])   # 40% of 600
    assert rx.main([str(folder), "--dry-run", "--out", str(tmp_path / "r")], detect=det, client=client) == 0
    out = capsys.readouterr().out
    assert "face % of width" in out and "40.0" in out and "FLAG" in out and "0/3 pass" in out
    assert client.sent == []


# -- live run: stop on rejection, report gating --------------------------------------------

def test_live_run_stops_after_first_image_rejection_and_writes_no_report(tmp_path, capsys):
    folder = photo_set(tmp_path / "p", n_window=3, n_lamp=2)
    out = tmp_path / "results"
    out.mkdir()
    client = FakeClient([face_too_small()] * 5)
    assert rx.main([str(folder), "--out", str(out)], client=client) == 1
    text = capsys.readouterr().out
    assert len(client.sent) == 1                                  # the other 4 were never sent
    assert "STOPPED" in text and "error_src_face_too_small" in text
    assert "No report written" in text and "No scans succeeded" in text
    assert not (out / "report.md").exists() and not (out / "report.json").exists()


def test_existing_report_is_left_alone_when_no_scans_succeed(tmp_path):
    folder = photo_set(tmp_path / "p")
    out = tmp_path / "results"
    out.mkdir()
    (out / "report.md").write_text("previous report\n")
    assert rx.main([str(folder), "--out", str(out)], client=FakeClient([face_too_small()] * 3)) == 1
    assert (out / "report.md").read_text() == "previous report\n"


def test_non_image_error_does_not_stop_but_blocks_partial_report(tmp_path, capsys):
    folder = photo_set(tmp_path / "p", n_window=2, n_lamp=2)     # order: lamp_1, lamp_2, window_1, window_2
    out = tmp_path / "results"
    ok = result({"redness": 50.0})
    client = FakeClient([ok, ok, YouCamError("timeout", code="timeout"), ok])
    assert rx.main([str(folder), "--out", str(out)], client=client) == 1
    assert len(client.sent) == 4
    assert "Only 3/4 photos have results" in capsys.readouterr().out
    assert not (out / "report.md").exists()
    # The successful results are kept, so a re-run only sends the missing photo.
    client2 = FakeClient([result({"redness": 51.0})])
    assert rx.main([str(folder), "--out", str(out)], client=client2) == 0
    assert client2.sent == ["window_1.png"]


def test_full_success_writes_report_with_crop_method(tmp_path):
    folder = photo_set(tmp_path / "p", n_window=2, n_lamp=2)
    names = ("lamp_1.png", "lamp_2.png", "window_1.png", "window_2.png")
    (folder / "crop_log.json").write_text(json.dumps({
        "rule": {"aspect": "3:4", "face_width_fraction_of_crop": 0.75}, "detector": "fake", "youcam_min_face_pct": 60,
        "photos": [{"file": n, "ok": True, "face_pct_before": 40.0, "face_pct_after_measured": 75.1,
                    "output_size": [600, 800], "clamped": False} for n in names]}))
    out = tmp_path / "results"
    client = FakeClient([result({"redness": v}) for v in (60.0, 61.0, 50.0, 52.0)])
    assert rx.main([str(folder), "--out", str(out)], client=client) == 0
    md = (out / "report.md").read_text()
    assert "All 4 of 4 photos were cropped automatically with the same rule" in md
    assert "face width = 75% of crop width" in md and "3:4" in md
    assert "| redness | 50.0 | 52.0 | 2.0 | 51.0 |" in md
    assert "| redness | 51.0 | 60.5 | +9.5 | 2.0 | 1.0 | yes |" in md
    assert client.deleted == ["task-1"] * 4
    assert json.loads((out / "report.json").read_text())["n"] == {"lamp": 2, "window": 2}


def test_one_scan_per_condition_is_not_reported_as_zero_noise(tmp_path, capsys):
    folder = photo_set(tmp_path / "p", n_window=1, n_lamp=0)
    out = tmp_path / "results"
    assert rx.main([str(folder), "--out", str(out)], client=FakeClient([result({"redness": 50.0})])) == 1
    assert "needs at least 2 scans" in capsys.readouterr().out
    assert not (out / "report.md").exists()
    assert (out / "window_1.json").exists()          # the scan itself is kept for reuse


def test_out_of_credit_stops_the_run(tmp_path, capsys):
    folder = photo_set(tmp_path / "p", n_window=3, n_lamp=2)
    credit = YouCamError("400", code="CreditInsufficiency")
    client = FakeClient([result({"redness": 50.0}), credit, credit, credit, credit])
    assert rx.main([str(folder), "--out", str(tmp_path / "r")], client=client) == 1
    assert len(client.sent) == 2 and "CreditInsufficiency" in capsys.readouterr().out


class MeteredClient(FakeClient):
    """Balance drops by `cost` per successful scan, like YouCam's credit endpoint."""

    def __init__(self, outcomes, balance, cost):
        super().__init__(outcomes)
        self.balance, self.cost = balance, cost

    def unit_balance(self):
        return self.balance

    def analyze(self, path, actions):
        res = super().analyze(path, actions)
        self.balance -= self.cost
        return res


def test_run_stops_before_a_scan_the_balance_cannot_pay_for(tmp_path, capsys):
    folder = photo_set(tmp_path / "p", n_window=3, n_lamp=2)
    client = MeteredClient([result({"redness": 50.0})] * 5, balance=40, cost=12)
    assert rx.main([str(folder), "--out", str(tmp_path / "r")], client=client) == 1
    out = capsys.readouterr().out
    assert len(client.sent) == 3 and client.balance == 4          # 40 -> 28 -> 16 -> 4, then stop
    assert "this scan cost 12 units" in out and "only 4 YouCam units left" in out


def test_max_live_caps_units_spent(tmp_path, capsys):
    folder = photo_set(tmp_path / "p")
    client = FakeClient([result({"redness": 50.0})] * 3)
    assert rx.main([str(folder), "--out", str(tmp_path / "r"), "--max-live", "1"], client=client) == 1
    assert len(client.sent) == 1 and "--max-live 1 reached" in capsys.readouterr().out


def test_saved_result_from_a_different_image_is_not_reused(tmp_path, capsys):
    folder = photo_set(tmp_path / "p", n_window=1, n_lamp=0)
    out = tmp_path / "results"
    rx.main([str(folder), "--out", str(out)], client=FakeClient([result({"redness": 50.0})]))
    assert (out / "window_1.source.json").exists()
    make_photo(folder / "window_1.png", (640, 800), "RGB")      # a different image, same name
    client = FakeClient([])
    assert rx.main([str(folder), "--out", str(out)], client=client) == 1
    assert client.sent == [] and "different image" in capsys.readouterr().out
