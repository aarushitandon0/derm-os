"""Run derm//os Experiments 1 and 2 on real photos and print the numbers.

Experiment 1 (noise floor): 5 photos, same face, same light, same phone,
  re-framing between shots.        -> how much scores move with no change at all.
Experiment 2 (lighting):  3 photos by a window + 3 under a warm lamp, same
  session.                         -> how much a light change alone moves scores.

Name your photos by condition, then a number:
    photos/window_1.png ... window_5.png   (Experiment 1 + baseline for 2)
    photos/lamp_1.png   ... lamp_3.png     (Experiment 2)
YouCam needs the face to fill >= 60% of the frame width: run scripts/crop_faces.py first.

Usage (from backend/; the key is read from backend/.env):
    python scripts/run_experiments.py ../photos/cropped --dry-run   # sizes + local face-% check, no units
    python scripts/run_experiments.py ../photos/cropped             # real run (SD by default)
    python scripts/run_experiments.py ../photos/cropped --replay    # recompute from saved results, no API calls
    python scripts/run_experiments.py ../photos/cropped --hd        # HD actions (needs 1080 px short side)
    python scripts/run_experiments.py ../photos/cropped --max-live 8  # never send more than 8 live scans

A live run stops at the first image rejection (face too small, no face, too dark...)
instead of sending the rest. report.md/report.json are written only when every photo
has a result; otherwise the script says what is missing and leaves the old report alone.

Outputs results/<photo>.json (raw YouCam responses), results/media/<photo>/ (masks),
results/report.json and results/report.md. Then: python scripts/make_fixtures.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]


def load_env_file(path: Path = BACKEND_DIR / ".env") -> bool:
    """Load backend/.env (shell variables win). Tests set DERMOS_NO_DOTENV=1 to skip it.
    Only loads; never prints anything from the file."""
    if os.environ.get("DERMOS_NO_DOTENV") == "1":
        return False
    from dotenv import load_dotenv
    return load_dotenv(path, override=False)


load_env_file()
sys.path.insert(0, str(BACKEND_DIR))

import argparse  # noqa: E402
import json  # noqa: E402
from collections import defaultdict  # noqa: E402
from dataclasses import dataclass, field  # noqa: E402
from statistics import mean  # noqa: E402
from typing import Any, Callable  # noqa: E402

from app.evidence import Capture, compare_conditions, noise_summary, ranges  # noqa: E402
from app.fingerprint import measure  # noqa: E402
from app.youcam import (IMAGE_ERRORS, YouCamClient, YouCamError, delete_task_quietly,  # noqa: E402
                        download_masks, load_result, save_result, validate_actions)
from scripts.face_tools import YOUCAM_MIN_FACE_PCT, face_pct, sha256_file  # noqa: E402

DEFAULT_CONCERNS = ["redness", "texture", "acne", "pore", "oiliness", "moisture", "radiance", "age_spot"]


def group_photos(folder: Path) -> dict[str, list[Path]]:
    groups: dict[str, list[Path]] = defaultdict(list)
    for p in sorted(folder.iterdir()):
        if not p.is_file() or p.suffix.lower() not in (".jpg", ".jpeg", ".png"):
            continue
        cond = p.stem.rsplit("_", 1)[0] if "_" in p.stem else p.stem
        groups[cond].append(p)
    return dict(groups)


# -- dry-run face-size check ---------------------------------------------------------------

def face_check(paths: list[Path], detect: Callable, min_pct: float = YOUCAM_MIN_FACE_PCT) -> list[dict]:
    """Local face width as % of image width, per photo. ok=False if not exactly one face
    or the face is under min_pct. Numbers only."""
    rows = []
    for p in paths:
        (w, _h), faces = detect(p)
        row: dict[str, Any] = {"file": p.name, "faces": len(faces), "face_pct": None, "ok": False}
        if len(faces) == 1:
            row["face_pct"] = face_pct(faces[0], w)
            row["ok"] = row["face_pct"] >= min_pct
            row["note"] = "" if row["ok"] else f"under {min_pct:g}%: YouCam will likely reject (run crop_faces.py)"
        else:
            row["note"] = "no face found" if not faces else f"{len(faces)} faces found"
        rows.append(row)
    return rows


def print_face_check(rows: list[dict], min_pct: float = YOUCAM_MIN_FACE_PCT) -> None:
    print(f"\nFace size (local detector; YouCam may measure differently; YouCam minimum {min_pct:g}%):")
    print(f"  {'photo':16s} {'faces':>5s} {'face % of width':>16s}  check")
    for r in rows:
        pct = f"{r['face_pct']:.1f}" if r["face_pct"] is not None else "-"
        print(f"  {r['file']:16s} {r['faces']:>5d} {pct:>16s}  {'ok' if r['ok'] else 'FLAG: ' + r['note']}")
    bad = [r["file"] for r in rows if not r["ok"]]
    print(f"  {len(rows) - len(bad)}/{len(rows)} pass" + (f"; flagged: {', '.join(bad)}" if bad else ""))


# -- live / replay scans -------------------------------------------------------------------

def is_image_rejection(err: Exception) -> bool:
    """YouCam refused the photo itself (face too small, no face, too dark...). Sending
    the other photos from the same shoot would very likely fail the same way."""
    return isinstance(err, YouCamError) and str(err.code) in IMAGE_ERRORS


ACCOUNT_STOP_CODES = {"CreditInsufficiency", "unit_reserve", "no_key"}


def is_account_stop(err: Exception) -> bool:
    """The account can't scan at all (no credit, no key): every later request would fail too."""
    return isinstance(err, YouCamError) and str(err.code) in ACCOUNT_STOP_CODES


def source_path(out: Path, stem: str) -> Path:
    return out / f"{stem}.source.json"


@dataclass
class ScanRun:
    captures: dict[str, list[Capture]] = field(default_factory=lambda: defaultdict(list))
    succeeded: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)
    live_sent: int = 0
    stop_reason: str | None = None
    unit_cost: float | None = None      # measured from the balance around the first live scan
    balance_after: float | None = None

    @property
    def n_success(self) -> int:
        return len(self.succeeded)


def run_scans(groups: dict[str, list[Path]], actions: list[str], mode: str, fps: dict, out: Path,
              client: Any = None, replay: bool = False, max_live: int | None = None,
              log: Callable[[str], None] = print, balance: float | None = None) -> ScanRun:
    """`balance` is the unit balance read before the run (None = unknown). After the first
    live scan the cost per scan is measured, and the run stops before a scan it can't pay for."""
    run = ScanRun()
    run.balance_after = balance
    for cond, photos in groups.items():
        for p in photos:
            res_path = out / f"{p.stem}.json"
            try:
                if replay or res_path.exists():
                    if res_path.exists() and not replay:
                        check_saved_source(out, p)
                    res = load_result(res_path)
                    src = "replay"
                else:
                    if max_live is not None and run.live_sent >= max_live:
                        run.stop_reason = (f"--max-live {max_live} reached; {p.name} and later photos were "
                                           "not sent.")
                        log(f"\nSTOPPED: {run.stop_reason}")
                        return run
                    if run.unit_cost and run.balance_after is not None and run.balance_after < run.unit_cost:
                        run.stop_reason = (f"only {run.balance_after:g} YouCam units left and one scan costs "
                                           f"{run.unit_cost:g}; {p.name} and later photos were not sent.")
                        log(f"\nSTOPPED: {run.stop_reason}")
                        return run
                    run.live_sent += 1
                    res = client.analyze(p, actions)
                    save_result(res, res_path, client.version)
                    source_path(out, p.stem).write_text(json.dumps({"file": p.name, "sha256": sha256_file(p)}))
                    # Mask URLs expire in ~2 h: save them now (plain GETs, no units).
                    saved = download_masks(res, out / "media" / p.stem, client.upload_http)
                    log(f"         saved {sum(len(v) for v in saved.values())} mask image(s)")
                    # Masks are local now: ask YouCam to delete the task, photo and outputs.
                    gone = delete_task_quietly(client, res.task_id)
                    log("         YouCam task deleted" if gone else "         YouCam task delete failed (logged)")
                    src = "live"
                    track_units(run, client, log)
            except (YouCamError, FileNotFoundError, StaleResultError) as e:
                msg = getattr(e, "friendly", None) or str(e)
                run.failed[p.name] = msg
                log(f"  ! {p.name}: {msg}")
                if is_image_rejection(e):
                    run.stop_reason = (f"YouCam rejected {p.name} ({e.code}): {msg} Stopped so the remaining "
                                       "photos are not sent; fix the framing (scripts/crop_faces.py) and re-run.")
                    log(f"\nSTOPPED: {run.stop_reason}")
                    return run
                if is_account_stop(e):
                    run.stop_reason = (f"YouCam refused the request for the account ({e.code}) at {p.name}. "
                                       "Stopped so the remaining photos are not sent.")
                    log(f"\nSTOPPED: {run.stop_reason}")
                    return run
                continue
            log(f"  {src:6s} {p.name}: " + ", ".join(f"{k}={v:.1f}" for k, v in sorted(res.raw_scores().items())))
            run.captures[cond].append(Capture(res.raw_scores(), fps[p.name], mode, tuple(actions)))
            run.succeeded.append(p.name)
    return run


def track_units(run: ScanRun, client: Any, log: Callable[[str], None]) -> None:
    """Re-read the balance after a live scan (a free request) and learn the cost per scan."""
    try:
        now = client.unit_balance()
    except Exception:  # noqa: BLE001 - balance is advisory
        now = None
    if now is None:
        return
    if run.unit_cost is None and run.balance_after is not None and run.balance_after > now:
        run.unit_cost = run.balance_after - now
        log(f"         this scan cost {run.unit_cost:g} units")
    run.balance_after = now
    log(f"         units left: {now:g}")


class StaleResultError(RuntimeError):
    pass


def check_saved_source(out: Path, photo: Path) -> None:
    """Refuse to reuse results/<stem>.json if it was made from a different image file."""
    sp = source_path(out, photo.stem)
    if not sp.exists():
        return  # older result without a record: reused as before
    saved = json.loads(sp.read_text()).get("sha256")
    if saved and saved != sha256_file(photo):
        raise StaleResultError(f"results/{photo.stem}.json came from a different image than {photo}; "
                               "move it aside to scan this photo.")


# -- report --------------------------------------------------------------------------------

def report_blocker(groups: dict[str, list[Path]], run: ScanRun) -> str | None:
    """Why the report must not be written, or None if it can be."""
    total = sum(len(v) for v in groups.values())
    if run.n_success == 0:
        return "No scans succeeded, so there is nothing to report."
    if run.stop_reason:
        return f"Run stopped early ({run.n_success}/{total} photos have results)."
    thin = {c: len(v) for c, v in groups.items() if len(v) < 2}
    if thin:
        # A range from one scan is 0 by construction and would read as "no noise".
        return ("Each condition needs at least 2 scans to measure a range; "
                + ", ".join(f"{c} has {n}" for c, n in thin.items()) + ".")
    if run.n_success < total:
        missing = sorted({p.name for v in groups.values() for p in v} - set(run.succeeded))
        return f"Only {run.n_success}/{total} photos have results (missing: {', '.join(missing)})."
    return None


def crop_method_lines(folder: Path, photo_names: list[str]) -> list[str]:
    """Report section describing how photos were prepared, from crop_log.json (numbers only)."""
    log_path = folder / "crop_log.json"
    if not log_path.exists():
        return ["## Method", "", "Photos were used as supplied (no crop_log.json found next to them).", ""]
    log = json.loads(log_path.read_text())
    rule = log.get("rule", {})
    frac = rule.get("face_width_fraction_of_crop")
    by_name = {e["file"]: e for e in log.get("photos", []) if e.get("ok")}
    used = [by_name[n] for n in photo_names if n in by_name]
    lines = ["## Method", "",
             f"All {len(used)} of {len(photo_names)} photos were cropped automatically with the same rule: "
             f"a {rule.get('aspect', '3:4')} crop centred on the detected face, face width = "
             f"{frac:.0%} of crop width (YouCam's minimum is {log.get('youcam_min_face_pct', 60):g}%), "
             "shifted to stay inside the image. No resizing, colour, brightness or rotation changes. "
             f"Detector: {log.get('detector', 'unknown')}.", ""]
    if used:
        lines += ["| Photo | Face % before | Face % after | Crop size | Shifted to fit |",
                  "| --- | --- | --- | --- | --- |"]
        lines += [f"| {e['file']} | {e['face_pct_before']} | {e.get('face_pct_after_measured')} | "
                  f"{e['output_size'][0]}x{e['output_size'][1]} | {'yes' if e['clamped'] else 'no'} |" for e in used]
        lines.append("")
    return lines


def build_report(run: ScanRun, mode: str, actions: list[str], baseline: str, log: Callable = print) -> dict:
    base = run.captures.get(baseline, [])
    report = {"mode": mode, "actions": actions, "baseline_condition": baseline,
              "n": {c: len(v) for c, v in run.captures.items()},
              "experiment_1": noise_summary(base), "experiment_2": {}}
    log(f"\n=== Experiment 1: noise with no change ({baseline}, n={len(base)}) ===")
    log(f"{'concern':12s} {'min':>7s} {'max':>7s} {'range':>7s}")
    for k, s in report["experiment_1"].items():
        log(f"{k:12s} {s['min']:7.2f} {s['max']:7.2f} {s['range']:7.2f}")
    for cond, caps in run.captures.items():
        if cond == baseline:
            continue
        br, cr = ranges(base), ranges(caps)
        comp = compare_conditions(base, caps)
        rows = {}
        log(f"\n=== Experiment 2: {baseline} vs {cond} (n={len(base)} vs {len(caps)}) ===")
        log(f"{'concern':12s} {'base mean':>10s} {cond+' mean':>12s} {'shift':>7s} {'noise range':>12s}  beyond noise?")
        for k in sorted(set(br) & set(cr)):
            bm = mean(c.scores[k] for c in base if k in c.scores)
            cm = mean(c.scores[k] for c in caps if k in c.scores)
            outside = cr[k].lo > br[k].hi or cr[k].hi < br[k].lo
            rows[k] = {"baseline_mean": round(bm, 2), "condition_mean": round(cm, 2), "shift": round(cm - bm, 2),
                       "baseline_range": round(br[k].width, 2), "condition_range": round(cr[k].width, 2),
                       "beyond_noise": outside}
            log(f"{k:12s} {bm:10.2f} {cm:12.2f} {cm - bm:+7.2f} {br[k].width:12.2f}  {'YES' if outside else 'no'}")
        log("comparability gate: " + ("comparable" if comp.comparable else "NOT comparable -> " + " ".join(comp.reasons)))
        report["experiment_2"][cond] = {"concerns": rows, "gate_comparable": comp.comparable,
                                        "gate_reasons": comp.reasons}
    return report


def report_markdown(report: dict, method_lines: list[str]) -> str:
    mode, baseline = report["mode"], report["baseline_condition"]
    n_base = report["n"].get(baseline, 0)
    lines = [f"# derm//os experiments ({mode.upper()})", "", *method_lines,
             f"## Experiment 1: {n_base} scans, nothing changed", "",
             "| Concern | Min | Max | Range | Mean |", "| --- | --- | --- | --- | --- |"]
    lines += [f"| {k} | {s['min']} | {s['max']} | {s['range']} | {s['mean']} |"
              for k, s in report["experiment_1"].items()]
    for cond, r in report["experiment_2"].items():
        lines += ["", f"## Experiment 2: {baseline} vs {cond} (n={n_base} vs {report['n'].get(cond, 0)})", "",
                  f"Gate: {'comparable' if r['gate_comparable'] else 'NOT comparable: ' + ' '.join(r['gate_reasons'])}",
                  "", f"| Concern | {baseline} mean | {cond} mean | Shift | {baseline} range | {cond} range | Beyond noise |",
                  "| --- | --- | --- | --- | --- | --- | --- |"]
        lines += [f"| {k} | {v['baseline_mean']} | {v['condition_mean']} | {v['shift']:+} | {v['baseline_range']} | "
                  f"{v['condition_range']} | {'yes' if v['beyond_noise'] else 'no'} |" for k, v in r["concerns"].items()]
    lines += ["", "Beyond noise = the two conditions' score ranges do not overlap."]
    return "\n".join(lines) + "\n"


def write_report(out: Path, report: dict, markdown: str) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(report, indent=2))
    (out / "report.md").write_text(markdown)


# -- main ----------------------------------------------------------------------------------

def main(argv: list[str] | None = None, detect: Callable | None = None, client: Any = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--baseline", default="window", help="condition name used for Experiment 1")
    ap.add_argument("--concerns", default=",".join(DEFAULT_CONCERNS))
    ap.add_argument("--hd", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--replay", action="store_true")
    ap.add_argument("--max-live", type=int, default=None, help="never send more than this many live scans")
    ap.add_argument("--out", default="results")
    args = ap.parse_args(argv)

    folder, out = Path(args.folder), Path(args.out)
    concerns = [c.strip() for c in args.concerns.split(",") if c.strip()]
    actions = [f"hd_{c}" if args.hd else c for c in concerns]
    if args.hd:
        actions = [a.replace("hd_dark_circle_v2", "hd_dark_circle") for a in actions]
    mode = validate_actions(actions)

    if not folder.is_dir():
        print(f"No folder {folder}")
        return 1
    groups = group_photos(folder)
    if not groups:
        print(f"No .jpg/.png photos found in {folder}")
        return 1
    if args.baseline not in groups:
        print(f"No photos named '{args.baseline}_N' found. Conditions found: {list(groups)}")
        return 1

    need = 1080 if mode == "hd" else 480
    print(f"\nPlan: {sum(len(v) for v in groups.values())} photos, mode={mode.upper()}, actions={actions}")
    fps = {}
    for cond, photos in groups.items():
        for p in photos:
            fp = measure(p)
            fps[p.name] = fp
            flag = "" if fp.short_side >= need else f"  <-- too small for {mode.upper()} (needs {need}px)"
            print(f"  {cond:10s} {p.name:20s} {fp.width}x{fp.height} light={fp.luminance:.2f} "
                  f"warmth(R/B)={fp.red_blue_ratio:.2f} device={fp.device}{flag}")
    if args.dry_run:
        all_photos = [p for v in groups.values() for p in v]
        det = detect
        if det is None:
            try:
                from scripts.face_tools import FaceDetector
                det = FaceDetector()
            except Exception as e:  # noqa: BLE001 - the check is advisory; say why it was skipped
                print(f"\nFace-size check skipped: {e}")
        if det is not None:
            print_face_check(face_check(all_photos, det))
        print("\nDry run: no API calls made. Remove --dry-run to run for real.")
        return 0

    if client is None and not args.replay:
        try:
            client = YouCamClient()
        except YouCamError as e:
            hint = (" DERMOS_NO_DOTENV=1 is set in this shell, so backend/.env was skipped."
                    if os.environ.get("DERMOS_NO_DOTENV") == "1" else
                    f" Put YOUCAM_API_KEY in {BACKEND_DIR / '.env'} or set it in the shell.")
            print(f"Cannot start a live run: {e}.{hint}")
            return 1
    bal = None
    if not args.replay:
        try:
            bal = client.unit_balance()
            print(f"\nYouCam unit balance before run: {bal if bal is not None else 'unknown'}")
        except Exception as e:  # noqa: BLE001 - balance is informational
            print(f"\nYouCam unit balance unavailable ({type(e).__name__})")

    run = run_scans(groups, actions, mode, fps, out, client, args.replay, args.max_live, balance=bal)
    if not args.replay:
        print(f"\nLive scan requests sent this run: {run.live_sent} (YouCam only charges for successful scans)")
        if run.balance_after is not None:
            print(f"Units left: {run.balance_after:g}"
                  + (f" (one scan of {len(actions)} concerns costs {run.unit_cost:g})" if run.unit_cost else ""))

    blocker = report_blocker(groups, run)
    if blocker:
        print(f"\nNo report written: {blocker} {out / 'report.md'} was left unchanged. "
              "Results that did succeed are saved and will be reused on the next run (no units).")
        return 1

    report = build_report(run, mode, actions, args.baseline)
    names = [p.name for v in groups.values() for p in v]
    write_report(out, report, report_markdown(report, crop_method_lines(folder, names)))
    print(f"\nSaved {out/'report.md'} and {out/'report.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
