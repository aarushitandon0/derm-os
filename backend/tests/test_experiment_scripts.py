"""Experiment scripts: .env loading, the app's normalisation (one code path), exact cost and
no partial runs, stop-on-rejection, report gating, legacy palette results. Synthetic images,
a stand-in detector and a fake YouCam client: no network, no real photos, no units."""
import json
import os
from pathlib import Path

import pytest
from PIL import Image

from app import facecrop as F
from app.youcam import SkinResult, YouCamError, normalize
from scripts import crop_faces, run_experiments as rx


# -- helpers -------------------------------------------------------------------------------

def make_photo(path: Path, size=(1200, 1600), mode="RGB", shade=0) -> Path:
    g = Image.linear_gradient("L").resize(size)
    im = Image.merge("RGB", (g, g.transpose(Image.Transpose.ROTATE_180), Image.new("L", size, 120 + shade)))
    if mode == "P":
        im = im.quantize(64)
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path)
    return path


def detector(faces_by_size=None, frac=0.5):
    """One centred face at `frac` of the width, or the faces given for an image width."""
    def detect(img):
        w, h = img.size
        if faces_by_size and w in faces_by_size:
            return faces_by_size[w]
        fw = frac * w
        return [F.Box(w / 2 - fw / 2, h * 0.45 - fw / 2, fw, fw, 0.99)]
    return detect


def result(scores: dict[str, float]) -> SkinResult:
    """A YouCam task response in the documented JSON shape (no mask URLs)."""
    payload = {"status": 200, "data": {"task_status": "success", "results": {"output": [
        {"type": k, "ui_score": v, "raw_score": v, "mask_urls": []} for k, v in scores.items()]}}}
    return normalize(payload, "sd", list(scores), "task-1")


class FakeClient:
    version = "v2.1"
    upload_http = None

    def __init__(self, outcomes, balance=1000.0):
        self.outcomes = list(outcomes)
        self.sent, self.sizes, self.deleted = [], [], []
        self.balance = balance

    def unit_balance(self):
        return self.balance

    def analyze(self, path, actions):
        self.sent.append(Path(path).name.split(".")[0] + ".png")   # temp file is named <stem>.<random>.png
        with Image.open(path) as im:
            self.sizes.append((im.size, im.mode, im.format))
        out = self.outcomes.pop(0)
        if isinstance(out, Exception):
            raise out
        return out

    def delete_task(self, task_id):
        self.deleted.append(task_id)
        return {}


def face_too_small():
    return YouCamError("Task failed", code="error_src_face_too_small",
                       friendly="Hold the phone a little closer.")


def photo_set(folder: Path, n_window=2, n_lamp=2, mode="RGB") -> Path:
    for i in range(1, n_window + 1):
        make_photo(folder / f"window_{i}.png", mode=mode, shade=i)
    for i in range(1, n_lamp + 1):
        make_photo(folder / f"lamp_{i}.png", mode=mode, shade=40 + i)
    return folder


def run(folder, out, client=None, extra=(), det=None):
    return rx.main([str(folder), "--out", str(out), *extra], detect=det or detector(), client=client)


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
    out = tmp_path / "results"
    assert run(photo_set(tmp_path / "p"), out) == 1
    msg = capsys.readouterr().out
    assert "Cannot start a live run" in msg and "DERMOS_NO_DOTENV=1" in msg
    assert not (out / "report.md").exists()


# -- one code path with the app ------------------------------------------------------------

def test_sends_the_apps_normalised_image(tmp_path):
    folder = photo_set(tmp_path / "p")
    client = FakeClient([result({"redness": v}) for v in (60.0, 61.0, 50.0, 52.0)])
    assert run(folder, tmp_path / "r", client) == 0
    assert client.sizes == [((480, 640), "RGB", "PNG")] * 4
    # Byte-for-byte what the app's /api/scan would send for the same photo.
    app_png = F.normalise_file(str(folder / "window_1.png"), detector()).png_bytes()
    items, mode, _ = rx.prepare({"window": [folder / "window_1.png"]}, detector(), False)
    assert mode == "sd" and items[0].png == app_png


def test_far_photo_is_refused_before_anything_is_sent(tmp_path, capsys):
    folder = photo_set(tmp_path / "p")
    make_photo(folder / "window_2.png", size=(900, 1200))       # 450 px face is fine
    make_photo(folder / "lamp_2.png", size=(600, 800))          # 300 px face: would need upscaling
    client = FakeClient([])
    assert run(folder, tmp_path / "r", client) == 1
    out = capsys.readouterr().out
    assert client.sent == [] and "Nothing sent" in out and "lamp_2.png: Hold the phone a little closer." in out


def test_palette_input_is_converted_and_warned(tmp_path, capsys):
    folder = photo_set(tmp_path / "p", mode="P")
    client = FakeClient([result({"redness": v}) for v in (60.0, 61.0, 50.0, 52.0)])
    assert run(folder, tmp_path / "r", client) == 0
    out = capsys.readouterr().out
    assert "WARNING: window_1.png is a reduced-colour image (mode P, at most 256 colours)" in out
    assert all(m == "RGB" for _s, m, _f in client.sizes)
    assert "reduced-colour inputs" in (tmp_path / "r" / "report.md").read_text()


def test_hd_only_when_every_photo_reaches_it(tmp_path, capsys):
    folder = tmp_path / "p"
    for n in ("window_1", "window_2", "lamp_1", "lamp_2"):
        make_photo(folder / f"{n}.png", size=(1800, 2400))       # 900 px faces: HD possible
    client = FakeClient([result({"redness": v}) for v in (60.0, 61.0, 50.0, 52.0)])
    assert run(folder, tmp_path / "r", client, ["--hd", "--actions", "redness"]) == 0
    assert client.sizes[0][0] == (1080, 1440)
    make_photo(folder / "lamp_2.png", size=(1200, 1600))         # one photo can't reach HD
    items, mode, why = rx.prepare(rx.group_photos(folder), detector(), True)
    assert mode == "sd" and "lamp_2.png" in why


def test_dry_run_shows_normalisation_and_exact_cost_and_sends_nothing(tmp_path, capsys):
    folder = photo_set(tmp_path / "p")
    client = FakeClient([], balance=40)
    assert run(folder, tmp_path / "r", client, ["--dry-run", "--actions", "redness,texture,pore,radiance"]) == 0
    out = capsys.readouterr().out
    assert "360px face -> 480x640" in out and "600" in out and "50.0" in out
    assert "Cost: 4 live scan(s) x 9 units (SD, 4 concerns, built-in) = 36 units" in out
    assert "The balance covers this run." in out and client.sent == []


# -- cost: no partial runs -----------------------------------------------------------------

def test_refuses_when_balance_cannot_cover_the_whole_run(tmp_path, capsys):
    folder = photo_set(tmp_path / "p")
    client = FakeClient([result({"redness": 50.0})] * 4, balance=40)   # 4 x 12 = 48 > 40
    assert run(folder, tmp_path / "r", client) == 1
    out = capsys.readouterr().out
    assert client.sent == [] and "costs 48 units (4 x 12) and the balance is 40" in out


def test_four_units_cannot_pay_for_one_scan(tmp_path, capsys):
    folder = photo_set(tmp_path / "p")
    client = FakeClient([], balance=4)
    assert run(folder, tmp_path / "r", client, ["--actions", "redness"]) == 1
    assert client.sent == [] and "costs 36 units (4 x 9) and the balance is 4" in capsys.readouterr().out


def test_unknown_balance_is_refused(tmp_path, capsys):
    client = FakeClient([], balance=None)
    assert run(photo_set(tmp_path / "p"), tmp_path / "r", client) == 1
    assert client.sent == [] and "balance couldn't be read" in capsys.readouterr().out


def test_max_live_below_the_run_is_refused_not_partial(tmp_path, capsys):
    client = FakeClient([result({"redness": 50.0})] * 4)
    assert run(photo_set(tmp_path / "p"), tmp_path / "r", client, ["--max-live", "1"]) == 1
    assert client.sent == [] and "No partial runs" in capsys.readouterr().out


def test_one_scan_per_condition_is_refused_before_sending(tmp_path, capsys):
    folder = photo_set(tmp_path / "p", n_window=1, n_lamp=0)
    client = FakeClient([result({"redness": 50.0})])
    assert run(folder, tmp_path / "r", client) == 1
    assert "needs at least 2 scans" in capsys.readouterr().out and client.sent == []


# -- live run: stop on rejection, report gating --------------------------------------------

def test_live_run_stops_after_first_image_rejection_and_writes_no_report(tmp_path, capsys):
    folder = photo_set(tmp_path / "p", n_window=3, n_lamp=2)
    out = tmp_path / "results"
    out.mkdir()
    client = FakeClient([face_too_small()] * 5)
    assert run(folder, out, client) == 1
    text = capsys.readouterr().out
    assert len(client.sent) == 1                                  # the other 4 were never sent
    assert "STOPPED" in text and "error_src_face_too_small" in text
    assert "No report written" in text and "No scans succeeded" in text
    assert not (out / "report.md").exists() and not (out / "report.json").exists()


def test_existing_report_is_left_alone_when_no_scans_succeed(tmp_path):
    out = tmp_path / "results"
    out.mkdir()
    (out / "report.md").write_text("previous report\n")
    assert run(photo_set(tmp_path / "p"), out, FakeClient([face_too_small()] * 4)) == 1
    assert (out / "report.md").read_text() == "previous report\n"


def test_non_image_error_does_not_stop_but_blocks_partial_report(tmp_path, capsys):
    folder = photo_set(tmp_path / "p")     # order: lamp_1, lamp_2, window_1, window_2
    out = tmp_path / "results"
    ok = result({"redness": 50.0})
    client = FakeClient([ok, ok, YouCamError("timeout", code="timeout"), ok])
    assert run(folder, out, client) == 1
    assert len(client.sent) == 4
    assert "Only 3/4 photos have results" in capsys.readouterr().out
    assert not (out / "report.md").exists()
    # The successful results are kept, so a re-run only sends (and pays for) the missing photo.
    client2 = FakeClient([result({"redness": 51.0})])
    assert run(folder, out, client2) == 0
    assert client2.sent == ["window_1.png"]


def test_full_success_writes_report_with_method_and_target(tmp_path):
    folder = photo_set(tmp_path / "p")
    out = tmp_path / "results"
    client = FakeClient([result({"redness": v}) for v in (60.0, 61.0, 50.0, 52.0)])
    assert run(folder, out, client) == 0
    md = (out / "report.md").read_text()
    assert "cropped and scaled the same way, by the app's own code" in md
    assert "face is **360 px** wide (output 480x640, SD)" in md and "No upscaling" in md
    assert "| window_1.png | 1200x1600 | RGB | 600 | 50.0 | 0.600 | no |" in md
    assert "| redness | 50.0 | 52.0 | 2.0 | 51.0 |" in md
    assert "| redness | 51.0 | 60.5 | +9.5 | 2.0 | 1.0 | yes |" in md
    assert client.deleted == ["task-1"] * 4
    rep = json.loads((out / "report.json").read_text())
    assert rep["n"] == {"lamp": 2, "window": 2} and rep["normalisation"]["target_face_px"] == 360


def test_out_of_credit_stops_the_run(tmp_path, capsys):
    folder = photo_set(tmp_path / "p", n_window=3, n_lamp=2)
    credit = YouCamError("400", code="CreditInsufficiency")
    client = FakeClient([result({"redness": 50.0}), credit, credit, credit, credit])
    assert run(folder, tmp_path / "r", client) == 1
    assert len(client.sent) == 2 and "CreditInsufficiency" in capsys.readouterr().out


def test_saved_result_from_a_different_image_is_not_reused(tmp_path, capsys):
    folder = photo_set(tmp_path / "p")
    out = tmp_path / "results"
    run(folder, out, FakeClient([result({"redness": 50.0})] * 4))
    assert (out / "window_1.source.json").exists()
    make_photo(folder / "window_1.png", (1300, 1700))      # a different image, same name
    client = FakeClient([])
    assert run(folder, out, client) == 1
    assert client.sent == [] and "different image" in capsys.readouterr().out


# -- legacy palette results ----------------------------------------------------------------

def test_legacy_palette_results_are_never_reused_and_are_moved_aside_when_replaced(tmp_path, capsys):
    folder = photo_set(tmp_path / "p")
    out = tmp_path / "results"
    out.mkdir()
    old = json.dumps({"meta": {"mode": "sd", "actions": ["redness"], "task_id": "old"},
                      "response": {"data": {"results": {"output": [{"type": "redness", "raw_score": 99}]}}}})
    (out / "window_1.json").write_text(old)
    (out / "window_1.source.json").write_text(json.dumps({"file": "window_1.png", "sha256": "x"}))
    (out / "legacy_palette.json").write_text(json.dumps({"files": ["window_1.json"]}))
    client = FakeClient([result({"redness": v}) for v in (60.0, 61.0, 50.0, 52.0)])
    assert run(folder, out, client) == 0
    assert "window_1.png" in client.sent                                   # scanned again, not reused
    assert (out / "legacy_palette" / "window_1.json").read_text() == old   # kept, moved aside
    md = (out / "report.md").read_text()
    assert "99" not in md.split("## Experiment 1")[1]
    assert "Earlier results made from palette PNGs (window_1) are not used here." in md


def test_replay_ignores_legacy_results(tmp_path, capsys):
    folder = photo_set(tmp_path / "p")
    out = tmp_path / "results"
    out.mkdir()
    for n in ("window_1", "window_2", "lamp_1", "lamp_2"):
        (out / f"{n}.json").write_text(json.dumps({"meta": {"mode": "sd", "actions": ["redness"]},
                                                   "response": {"data": {"results": {"output": []}}}}))
    (out / "legacy_palette.json").write_text(json.dumps({"files": ["window_1.json", "window_2.json",
                                                                  "lamp_1.json", "lamp_2.json"]}))
    assert run(folder, out, None, ["--replay"]) == 1
    assert not (out / "report.md").exists()


# -- crop_faces.py preview -----------------------------------------------------------------

def test_crop_preview_uses_the_app_rule_and_leaves_originals(tmp_path):
    photos = tmp_path / "photos"
    a = make_photo(photos / "window_1.png")
    make_photo(photos / "lamp_1.png", size=(600, 800))
    before = a.read_bytes()
    log = crop_faces.run(photos, detector())
    by = {e["file"]: e for e in log["photos"]}
    assert by["window_1.png"]["ok"] and by["window_1.png"]["output"] == [480, 640]
    assert not by["lamp_1.png"]["ok"] and by["lamp_1.png"]["fix"] == "Hold the phone a little closer."
    assert a.read_bytes() == before
    assert (photos / "normalised" / "window_1.png").read_bytes() == \
        F.normalise_file(str(a), detector()).png_bytes()
