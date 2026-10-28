"""False-change analysis (scripts/analyze_experiment.py) and the experiment script's pilot /
skip-done / action checks. Synthetic scores and images only: no network, no real photos, no units."""
import json
import socket
from pathlib import Path

import pytest

from app import evidence as E
from scripts import analyze_experiment as AX
from scripts import run_experiments as rx
from tests.test_experiment_scripts import FakeClient, detector, make_photo, result

# Same light for every window photo; a warm lamp for the lamp photos (red/blue 1.6 vs 1.2).
WINDOW_FP = {"width": 480, "height": 640, "luminance": 0.55, "red_blue_ratio": 1.20, "device": "Cam",
             "captured_hour": 10, "face_ratio": 0.75, "device_source": "exif", "hour_source": "exif"}
LAMP_FP = {**WINDOW_FP, "red_blue_ratio": 1.60}


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("the analysis must not touch the network")
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)


def save_shot(results: Path, stem: str, scores: dict, fp: dict) -> None:
    results.mkdir(parents=True, exist_ok=True)
    blob = {"meta": {"mode": "sd", "actions": list(scores), "task_id": stem},
            "response": {"data": {"task_status": "success", "results": {"output": [
                {"type": k, "raw_score": v, "ui_score": v, "mask_urls": []} for k, v in scores.items()]}}}}
    (results / f"{stem}.json").write_text(json.dumps(blob))
    (results / f"{stem}.fingerprint.json").write_text(json.dumps(fp))


def shoot(results: Path, window: list[float], lamp: list[float], concern="redness") -> Path:
    for i, v in enumerate(window, 1):
        save_shot(results, f"window_{i}", {concern: v}, WINDOW_FP)
    for i, v in enumerate(lamp, 1):
        save_shot(results, f"lamp_{i}", {concern: v}, LAMP_FP)
    return results


def analyse(results: Path) -> dict:
    return AX.analyse(AX.load_shots(results), results)


# -- b) fixed threshold, hand-checked --------------------------------------------------------

def test_fixed_threshold_rates_hand_checked(tmp_path):
    # Pair differences: 2 6 10 11 | 4 8 9 | 4 5 | 1  -> >5: 6 10 11 8 9 = 5/10; >4: also 5 = 6/10.
    a = analyse(shoot(tmp_path, [50, 52, 56, 60, 61], [40, 41]))
    ft = a["fixed_threshold"]
    assert ft["n_pairs"] == 10
    assert ft["by_threshold"]["5"]["flagged"] == 5 and ft["by_threshold"]["5"]["pct"] == 50.0
    assert ft["by_threshold"]["4"]["flagged"] == 6 and ft["by_threshold"]["4"]["pct"] == 60.0


# -- c) derm//os verdict, hand-checked -------------------------------------------------------

def test_dermos_rate_hand_checked(tmp_path):
    # 10 splits of [60 61 62 63 70] into 3 + 2. Ranges fail to overlap only for check-in {63,70}
    # vs baseline {60,61,62} and check-in {60,61} vs baseline {62,63,70}: 2/10.
    a = analyse(shoot(tmp_path, [60, 61, 62, 63, 70], [50, 51]))
    pre = a["dermos_preregistered"]
    assert pre["n_splits"] == 10 and pre["moved"] == 2 and pre["pct"] == 20.0
    assert pre["per_concern"]["redness"]["verdicts"] == {"moved_beyond_noise": 2, "no_detectable_change": 8}
    assert pre["tolerances"] == E.TOLERANCES and pre["min_band"] == E.MIN_BAND


def test_dermos_rate_calls_the_real_verdict_function(tmp_path, monkeypatch):
    calls = []
    real = E.evaluate

    def spy(*a, **k):
        calls.append(k.get("concerns"))
        return real(*a, **k)
    monkeypatch.setattr(E, "evaluate", spy)
    a = analyse(shoot(tmp_path, [60, 61, 62, 63, 70], [50, 51]))
    assert len(calls) == 10 and all(c == ["redness"] for c in calls)
    assert a["dermos_preregistered"]["moved"] == 2


def test_gate_blocks_a_split_with_different_light(tmp_path):
    # Window photo 5 under a different light: splits that mix it into the check-in are "not comparable".
    r = shoot(tmp_path, [60, 61, 62, 63, 70], [50, 51])
    save_shot(r, "window_5", {"redness": 70}, {**WINDOW_FP, "luminance": 0.90})
    v = analyse(r)["dermos_preregistered"]["per_concern"]["redness"]["verdicts"]
    assert v.get("cant_tell_not_comparable", 0) > 0 and v.get("moved_beyond_noise", 0) <= 2


# -- a) and d) -----------------------------------------------------------------------------

def test_noise_and_lighting(tmp_path):
    a = analyse(shoot(tmp_path, [60, 61, 62, 63, 70], [50, 52, 54]))
    n = a["noise"]["redness"]
    assert (n["min"], n["max"], n["range"], n["n_subsets3"]) == (60, 70, 10, 10)
    # 3-photo ranges: 2 3 10 | 3 10 | 10 | 2 9 | 9 | 8 -> sorted 2 2 3 3 8 9 9 10 10 10: median 8.5, max 10
    assert n["subset3_median_range"] == 8.5 and n["subset3_max_range"] == 10
    li = a["lighting"]
    assert li["per_concern"]["redness"]["mean_shift_window_minus_lamp"] == 11.2   # 63.2 - 52
    assert li["n_pairs"] == 15 and li["pct_not_comparable"] == 100.0 and li["failed_fields"] == {"lighting": 15}


# -- refusals, report, pre-registration ----------------------------------------------------

@pytest.mark.parametrize("window,lamp", [([60, 61], [50, 51]), ([60, 61, 62], [50])])
def test_no_report_with_too_few_photos(tmp_path, window, lamp, capsys):
    r = shoot(tmp_path, window, lamp)
    assert AX.run(r) == 1
    assert "Needs at least 3 window and 2 lamp" in capsys.readouterr().out
    assert not (r / "report.md").exists() and not (r / AX.PREREG_FILE).exists()


def test_missing_fingerprint_is_refused(tmp_path):
    r = shoot(tmp_path, [60, 61, 62], [50, 51])
    (r / "window_2.fingerprint.json").unlink()
    with pytest.raises(AX.AnalysisError, match="no saved capture conditions"):
        AX.load_shots(r)


def test_report_section_states_n_and_non_independence_and_is_replaced_in_place(tmp_path):
    r = shoot(tmp_path, [60, 61, 62, 63, 70], [50, 51])
    (r / "report.md").write_text("# derm//os experiments (SD)\n\nExperiment tables\n")
    assert AX.run(r) == 0 and AX.run(r) == 0
    md = (r / "report.md").read_text(encoding="utf-8")
    assert md.startswith("# derm//os experiments (SD)") and md.count(AX.START) == 1
    assert "a fixed-threshold rule (±5 / ±4)" in md
    assert "not independent" in md and "not an independent evaluation" in md
    assert "5 photos of the same face" in md and "20.0% of 10 baseline/check-in splits" in md
    assert "40.0% of 10 photo-pair comparisons" in md      # 70 differs from 60-63 by more than 5


def test_preregistered_number_is_never_replaced(tmp_path, monkeypatch):
    r = shoot(tmp_path, [60, 61, 62, 63, 70], [50, 51])
    first = analyse(r)["dermos_preregistered"]
    frozen = (r / AX.PREREG_FILE).read_text()
    monkeypatch.setattr(E, "MIN_BAND", 5.0)          # someone "tunes" the constants later
    a = analyse(r)
    assert (r / AX.PREREG_FILE).read_text() == frozen
    assert a["dermos_preregistered"] == first and a["dermos_preregistered"]["pct"] == 20.0
    assert a["dermos_after_tuning"]["pct"] == 0.0 and a["dermos_after_tuning"]["min_band"] == 5.0
    md = AX.markdown(a)
    assert "after tuning on these same photos" in md and "The pre-registered number above is the one to quote" in md


def test_preregistration_for_other_photos_is_refused_not_overwritten(tmp_path):
    r = shoot(tmp_path, [60, 61, 62, 63, 70], [50, 51])
    analyse(r)
    save_shot(r, "window_1", {"redness": 99}, WINDOW_FP)
    with pytest.raises(AX.AnalysisError, match="never replaced"):
        analyse(r)


# -- run_experiments: actions, pilot, skip-done, spare/ ---------------------------------------

def photos(folder: Path, n_window=3, n_lamp=2) -> Path:
    for i in range(1, n_window + 1):
        make_photo(folder / f"window_{i}.png", shade=i)
    for i in range(1, n_lamp + 1):
        make_photo(folder / f"lamp_{i}.png", shade=40 + i)
    return folder


def run(folder, out, client=None, extra=()):
    return rx.main([str(folder), "--out", str(out), *extra], detect=detector(), client=client)


@pytest.mark.parametrize("actions,why", [("redness,glow", "glow"), ("hd_redness", "hd_redness"),
                                         ("dark_circle", "dark_circle"), ("redness,redness", "listed twice")])
def test_unknown_or_non_sd_actions_are_refused_before_any_call(tmp_path, capsys, actions, why):
    client = FakeClient([])
    assert run(photos(tmp_path / "p"), tmp_path / "r", client, ["--actions", actions]) == 1
    out = capsys.readouterr().out
    assert "Bad --actions" in out and why in out and client.sent == []


def test_default_concerns_are_the_apps_four():
    assert rx.DEFAULT_CONCERNS == ["redness", "acne", "texture", "pore"]


class MeteredClient(FakeClient):
    """Balance drops by 9 per successful scan, like YouCam's SD 1-4 concern tier."""

    def analyze(self, path, actions):
        out = super().analyze(path, actions)
        self.balance -= 9
        return out


def test_pilot_reports_units_charged_and_full_run_reuses_it(tmp_path, capsys):
    folder, out = photos(tmp_path / "p"), tmp_path / "r"
    pilot = MeteredClient([result({"redness": 60.0})], balance=1004)
    assert run(folder, out, pilot, ["--only", "window_1"]) == 0
    text = capsys.readouterr().out
    assert pilot.sent == ["window_1.png"]
    assert "balance 1004 before, 995 after: 9 units actually charged for 1 live scan(s)" in text
    assert "no report written" in text and not (out / "report.md").exists()
    assert (out / "window_1.json").exists() and (out / "window_1.fingerprint.json").exists()

    full = MeteredClient([result({"redness": v}) for v in (50.0, 51.0, 61.0, 62.0)], balance=995)
    assert run(folder, out, full, ["--skip-done"]) == 0
    text = capsys.readouterr().out
    assert "window_1.png" not in full.sent and len(full.sent) == 4
    assert "Skipping 1 photo(s) already scanned in this shoot" in text
    assert "False-change analysis" in text and (out / "false_change.json").exists()
    assert AX.START in (out / "report.md").read_text(encoding="utf-8")


def test_pilot_with_unknown_photo_sends_nothing(tmp_path, capsys):
    client = FakeClient([])
    assert run(photos(tmp_path / "p"), tmp_path / "r", client, ["--only", "window_9"]) == 1
    assert client.sent == [] and "window_9" in capsys.readouterr().out


def test_spare_folder_is_ignored(tmp_path):
    folder = photos(tmp_path / "p")
    make_photo(folder / "spare" / "window_7.png")
    make_photo(folder / "spare" / "lamp_9.png")
    groups = rx.group_photos(folder)
    names = sorted(p.name for v in groups.values() for p in v)
    assert names == ["lamp_1.png", "lamp_2.png", "window_1.png", "window_2.png", "window_3.png"]


def test_two_lamp_minimum_keeps_the_analysis_out_of_a_thin_run(tmp_path, capsys):
    # 2 window + 2 lamp: the experiment report is written, the false-change analysis is not.
    folder, out = photos(tmp_path / "p", n_window=2, n_lamp=2), tmp_path / "r"
    client = FakeClient([result({"redness": v}) for v in (50.0, 51.0, 60.0, 61.0)])
    assert run(folder, out, client) == 0
    assert "False-change analysis not written" in capsys.readouterr().out
    assert AX.START not in (out / "report.md").read_text(encoding="utf-8")
