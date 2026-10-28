"""Run derm//os Experiments 1 and 2 on real photos and print the numbers.

Experiment 1 (noise floor): 5 photos, same face, same light, same phone,
  re-framing between shots.        -> how much scores move with no change at all.
Experiment 2 (lighting):  3 photos by a window + 3 under a warm lamp, same
  session.                         -> how much a light change alone moves scores.

Name your photos by condition, then a number (JPEG or PNG straight from the phone):
    photos/window_1.jpg ... window_5.jpg   (Experiment 1 + baseline for 2)
    photos/lamp_1.jpg   ... lamp_3.jpg     (Experiment 2)

Every photo goes through the app's own crop and scale (app/facecrop.py, one code path):
3:4 around the single detected face, face width 75% of the crop, scaled DOWN so the face
is the same number of pixels in every photo. No upscaling, colour, brightness or rotation
edits. Photos the rule can't handle are listed before anything is sent.

Usage (from backend/; the key is read from backend/.env):
    python scripts/run_experiments.py ../photos --dry-run        # normalisation + exact cost, no units
    python scripts/run_experiments.py ../photos                  # real run (SD)
    python scripts/run_experiments.py ../photos --actions redness,texture,pore,radiance
    python scripts/run_experiments.py ../photos --hd             # HD, only if EVERY photo can reach it
    python scripts/run_experiments.py ../photos --replay         # recompute from saved results, no API calls

Before a live run the script prints the exact unit cost (from YouCam's price list) and
refuses unless the balance covers the WHOLE run: no partial runs. A live run stops at the
first image rejection. report.md/report.json are written only when every photo has a
result and every condition has at least 2 scans.

Outputs results/<photo>.json (raw YouCam responses), results/media/<photo>/ (masks),
results/report.json and results/report.md. Then: python scripts/make_fixtures.py
Results listed in results/legacy_palette.json (made from palette PNGs) are never reused or
reported; when a new scan of the same photo name succeeds, the old file is moved to
results/legacy_palette/.
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
import shutil  # noqa: E402
import tempfile  # noqa: E402
from collections import defaultdict  # noqa: E402
from dataclasses import dataclass, field  # noqa: E402
from statistics import mean  # noqa: E402
from typing import Any, Callable  # noqa: E402

from app import facecrop as F  # noqa: E402
from app.evidence import Capture, compare_conditions, noise_summary, ranges  # noqa: E402
from app.fingerprint import Fingerprint, measure_normalised  # noqa: E402
from app.youcam import (IMAGE_ERRORS, YouCamClient, YouCamError, actions_for_mode,  # noqa: E402
                        delete_task_quietly, download_masks, load_result, save_result, scan_cost_from,
                        validate_actions)

DEFAULT_CONCERNS = ["redness", "texture", "acne", "pore", "oiliness", "moisture", "radiance", "age_spot"]
IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png")
LEGACY_MARKER = "legacy_palette.json"


def group_photos(folder: Path) -> dict[str, list[Path]]:
    groups: dict[str, list[Path]] = defaultdict(list)
    for p in sorted(folder.iterdir()):
        if not p.is_file() or p.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        cond = p.stem.rsplit("_", 1)[0] if "_" in p.stem else p.stem
        groups[cond].append(p)
    return dict(groups)


def sha256_file(path: Path) -> str:
    return F.sha256_bytes(Path(path).read_bytes())


# -- normalisation (the app's code path) ---------------------------------------------------

@dataclass
class Prepared:
    path: Path
    cond: str
    sha256: str
    notes: dict = field(default_factory=dict)
    face: F.Box | None = None
    n_faces: int = 0
    refusal: str | None = None          # REFUSALS code
    png: bytes | None = None            # exactly what YouCam receives
    info: dict = field(default_factory=dict)
    fp: Fingerprint | None = None

    @property
    def ok(self) -> bool:
        return self.refusal is None and self.png is not None


def prepare(groups: dict[str, list[Path]], detect: F.Detector, want_hd: bool) -> tuple[list[Prepared], str, str]:
    """Normalise every photo with ONE mode for the whole run (never mixed). Returns
    (photos, mode, why). HD only when asked for and every photo's face can reach HD's size."""
    items: list[Prepared] = []
    for cond, photos in groups.items():
        for p in photos:
            it = Prepared(p, cond, sha256_file(p))
            try:
                img, it.notes = F.open_upright(str(p))
                it.notes["size"] = list(img.size)
                faces = detect(img)
                it.n_faces = len(faces)
                it.face = faces[0] if len(faces) == 1 else None
            except F.Refusal as e:
                it.refusal = e.code
            items.append(it)
    mode, why = "sd", "SD requested"
    if want_hd:
        small = [i.path.name for i in items if not i.face or i.face.w < F.TARGET_FACE_PX["hd"]]
        if small:
            why = (f"HD needs a {F.TARGET_FACE_PX['hd']}px face in every photo; not reached in "
                   f"{', '.join(small)}, so the whole run uses SD")
        else:
            mode, why = "hd", "every photo can reach HD without upscaling"
    for it in items:
        if it.refusal:
            continue
        try:
            img, _ = F.open_upright(str(it.path))
            faces = [it.face] if it.face else ([] if it.n_faces == 0 else [F.Box(0, 0, 1, 1)] * it.n_faces)
            n = F.normalise(img, faces, mode, locked=mode,
                            notes={k: v for k, v in it.notes.items() if k != "size"})
        except F.Refusal as e:
            it.refusal = e.code
            continue
        it.png, it.info = n.png_bytes(), n.info
        it.fp = fingerprint_of(it)
    return items, mode, why


def fingerprint_of(it: Prepared) -> Fingerprint:
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp.write(it.png)
        tmp_path = tmp.name
    try:
        return measure_normalised(tmp_path, it.path, it.info)
    finally:
        os.unlink(tmp_path)


def print_preparation(items: list[Prepared], mode: str, why: str, log: Callable = print) -> None:
    target = F.TARGET_FACE_PX[mode]
    ow, oh = F.OUTPUT[mode]
    log(f"\nNormalisation ({F.NORMALISE_VERSION}, same code as the app): 3:4 crop centred on the face, "
        f"face width {F.FACE_FRAC:.0%} of the crop, scaled down to a {target}px face -> {ow}x{oh} ({mode.upper()}; {why}).")
    log(f"  {'photo':16s} {'original':>11s} {'mode':>5s} {'faces':>5s} {'face px':>8s} {'face %':>7s} "
        f"{'scale':>6s} {'out':>9s} {'light':>6s} {'warmth':>7s}  note")
    for it in items:
        size = "x".join(str(v) for v in it.notes.get("size", [])) or "-"
        src_mode = it.notes.get("source_mode", "?")
        if not it.ok:
            log(f"  {it.path.name:16s} {size:>11s} {src_mode:>5s} {it.n_faces:>5d} "
                f"{(f'{it.face.w:.0f}' if it.face else '-'):>8s} {'-':>7s} {'-':>6s} {'-':>9s} {'-':>6s} {'-':>7s}"
                f"  REFUSED: {F.REFUSALS.get(it.refusal, it.refusal)}")
            continue
        note = []
        if it.info["clamped"]:
            note.append("shifted to fit")
        if it.notes.get("exif_orientation", 1) != 1:
            note.append(f"EXIF orientation {it.notes['exif_orientation']} read")
        log(f"  {it.path.name:16s} {size:>11s} {src_mode:>5s} {it.n_faces:>5d} {it.info['face_px_original']:>8.0f} "
            f"{it.info['face_pct_original']:>7.1f} {it.info['scale']:>6.3f} {f'{ow}x{oh}':>9s} "
            f"{it.fp.luminance:>6.2f} {it.fp.red_blue_ratio:>7.2f}  {', '.join(note)}")
    for it in items:
        if it.notes.get("reduced_colour"):
            log(f"\n  WARNING: {it.path.name} is a reduced-colour image (mode {it.notes['source_mode']}"
                f"{', at most 256 colours' if it.notes['source_mode'] in ('P', 'PA') else ''}). It was converted to "
                "full-colour RGB before measuring, but colours already lost can't come back, so light and skin "
                "scores from it are not trustworthy. Use the phone's original JPEG instead.")


# -- legacy palette results ----------------------------------------------------------------

def legacy_stems(out: Path) -> set[str]:
    m = out / LEGACY_MARKER
    if not m.exists():
        return set()
    return {Path(f).stem for f in json.loads(m.read_text()).get("files", [])}


def retire_legacy(out: Path, stem: str) -> None:
    """Move a palette-image result aside (never delete) once its replacement exists."""
    dest = out / "legacy_palette"
    dest.mkdir(parents=True, exist_ok=True)
    for name in (f"{stem}.json", f"{stem}.source.json"):
        if (out / name).exists():
            (out / name).replace(dest / name)
    if (out / "media" / stem).is_dir():
        (dest / "media").mkdir(exist_ok=True)
        shutil.move(str(out / "media" / stem), str(dest / "media" / stem))


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


def source_record(it: Prepared) -> dict:
    return {"file": it.path.name, "sha256": it.sha256, "normalisation": it.info.get("version"),
            "mode": it.info.get("mode"), "target_face_px": it.info.get("target_face_px")}


class StaleResultError(RuntimeError):
    pass


def reusable(out: Path, it: Prepared, legacy: set[str]) -> bool:
    """A saved result can stand in for this photo only if it was made from this exact file
    with this exact normalisation. Raises StaleResultError if a different image made it."""
    stem = it.path.stem
    if stem in legacy or not (out / f"{stem}.json").exists():
        return False
    sp = source_path(out, stem)
    saved = json.loads(sp.read_text()) if sp.exists() else {}
    if saved.get("sha256") != it.sha256:
        raise StaleResultError(f"results/{stem}.json came from a different image than {it.path}; "
                               "move it aside to scan this photo.")
    want = source_record(it)
    if any(saved.get(k) != want[k] for k in ("normalisation", "mode", "target_face_px")):
        raise StaleResultError(f"results/{stem}.json was made with a different crop/scale or mode; "
                               "move it aside to scan this photo again.")
    return True


@dataclass
class ScanRun:
    captures: dict[str, list[Capture]] = field(default_factory=lambda: defaultdict(list))
    succeeded: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)
    live_sent: int = 0
    stop_reason: str | None = None
    balance_after: float | None = None

    @property
    def n_success(self) -> int:
        return len(self.succeeded)


def run_scans(items: list[Prepared], actions: list[str], mode: str, out: Path, client: Any = None,
              replay: bool = False, log: Callable[[str], None] = print, legacy: set[str] = frozenset()) -> ScanRun:
    run = ScanRun()
    for it in items:
        p, stem = it.path, it.path.stem
        res_path = out / f"{stem}.json"
        try:
            if replay or reusable(out, it, legacy):
                if replay and not reusable(out, it, legacy):
                    raise FileNotFoundError(f"no saved result for {p.name} made with this normalisation")
                res, src = load_result(res_path), "replay"
            else:
                run.live_sent += 1
                with tempfile.NamedTemporaryFile(prefix=f"{stem}.", suffix=".png", delete=False) as tmp:
                    tmp.write(it.png)
                    send = tmp.name
                try:
                    res = client.analyze(send, actions)
                finally:
                    os.unlink(send)       # the normalised copy is never kept
                if stem in legacy:
                    retire_legacy(out, stem)
                save_result(res, res_path, client.version)
                source_path(out, stem).write_text(json.dumps(source_record(it)))
                # Mask URLs expire in ~2 h: save them now (plain GETs, no units).
                saved = download_masks(res, out / "media" / stem, client.upload_http)
                log(f"         saved {sum(len(v) for v in saved.values())} mask image(s)")
                # Masks are local now: ask YouCam to delete the task, photo and outputs.
                gone = delete_task_quietly(client, res.task_id)
                log("         YouCam task deleted" if gone else "         YouCam task delete failed (logged)")
                src = "live"
        except (YouCamError, FileNotFoundError, StaleResultError) as e:
            msg = getattr(e, "friendly", None) or str(e)
            run.failed[p.name] = msg
            log(f"  ! {p.name}: {msg}")
            if is_image_rejection(e):
                run.stop_reason = (f"YouCam rejected {p.name} ({e.code}): {msg} Stopped so the remaining "
                                   "photos are not sent.")
                log(f"\nSTOPPED: {run.stop_reason}")
                return run
            if is_account_stop(e):
                run.stop_reason = (f"YouCam refused the request for the account ({e.code}) at {p.name}. "
                                   "Stopped so the remaining photos are not sent.")
                log(f"\nSTOPPED: {run.stop_reason}")
                return run
            continue
        log(f"  {src:6s} {p.name}: " + ", ".join(f"{k}={v:.1f}" for k, v in sorted(res.raw_scores().items())))
        run.captures[it.cond].append(Capture(res.raw_scores(), it.fp, mode, tuple(actions)))
        run.succeeded.append(p.name)
    return run


# -- cost ----------------------------------------------------------------------------------

def scan_price(client: Any, actions: list[str]) -> tuple[float, str]:
    if client is not None and hasattr(client, "scan_cost"):
        return client.scan_cost(actions)
    return scan_cost_from({}, getattr(client, "version", "v2.1"), actions)


def cost_blocker(n_send: int, each: float, balance: float | None, max_live: int | None) -> str | None:
    total = n_send * each
    if max_live is not None and n_send > max_live:
        return (f"{n_send} photos need a live scan but --max-live is {max_live}. No partial runs: "
                "raise --max-live or remove photos.")
    if balance is None:
        return f"The unit balance couldn't be read, so the run ({total:g} units) can't be checked. Nothing sent."
    if balance < total:
        return (f"This run costs {total:g} units ({n_send} x {each:g}) and the balance is {balance:g}. "
                "No partial runs: top up, use fewer concerns (--actions), or fewer photos.")
    return None


# -- report --------------------------------------------------------------------------------

def report_blocker(groups: dict[str, list[Path]], run: ScanRun) -> str | None:
    """Why the report must not be written, or None if it can be."""
    total = sum(len(v) for v in groups.values())
    if run.n_success == 0:
        return "No scans succeeded, so there is nothing to report."
    if run.stop_reason:
        return f"Run stopped early ({run.n_success}/{total} photos have results)."
    thin = thin_conditions(groups)
    if thin:
        return thin
    if run.n_success < total:
        missing = sorted({p.name for v in groups.values() for p in v} - set(run.succeeded))
        return f"Only {run.n_success}/{total} photos have results (missing: {', '.join(missing)})."
    return None


def thin_conditions(groups: dict[str, list[Path]]) -> str | None:
    thin = {c: len(v) for c, v in groups.items() if len(v) < 2}
    if not thin:
        return None
    # A range from one scan is 0 by construction and would read as "no noise".
    return ("Each condition needs at least 2 scans to measure a range; "
            + ", ".join(f"{c} has {n}" for c, n in thin.items()) + ".")


def method_lines(items: list[Prepared], mode: str, legacy: set[str]) -> list[str]:
    target = F.TARGET_FACE_PX[mode]
    ow, oh = F.OUTPUT[mode]
    lines = ["## Method", "",
             f"Every photo was cropped and scaled the same way, by the app's own code ({F.NORMALISE_VERSION}, "
             f"app/facecrop.py): a 3:4 crop centred on the single detected face with the face at "
             f"{F.FACE_FRAC:.0%} of the crop width, then scaled down so the face is **{target} px** wide "
             f"(output {ow}x{oh}, {mode.upper()}). No upscaling, colour, brightness or rotation edits. "
             f"Detector: {F.DETECTOR_NAME}. Photos were read as full-colour RGB.", "",
             "| Photo | Original | Colour mode | Face px (original) | Face % (original) | Scale | Shifted to fit |",
             "| --- | --- | --- | --- | --- | --- | --- |"]
    for it in items:
        lines.append(f"| {it.path.name} | {'x'.join(str(v) for v in it.info['original_size'])} | "
                     f"{it.notes.get('source_mode')} | {it.info['face_px_original']:.0f} | "
                     f"{it.info['face_pct_original']} | {it.info['scale']:.3f} | {'yes' if it.info['clamped'] else 'no'} |")
    reduced = [it.path.name for it in items if it.notes.get("reduced_colour")]
    if reduced:
        lines += ["", f"**Warning:** reduced-colour inputs ({', '.join(reduced)}); their colours can't be trusted."]
    if legacy:
        lines += ["", f"Earlier results made from palette PNGs ({', '.join(sorted(legacy))}) are not used here."]
    return lines + [""]


def build_report(run: ScanRun, mode: str, actions: list[str], baseline: str, log: Callable = print) -> dict:
    base = run.captures.get(baseline, [])
    report = {"mode": mode, "actions": actions, "baseline_condition": baseline,
              "normalisation": {**F.describe(), "target_face_px": F.TARGET_FACE_PX[mode],
                                "output": list(F.OUTPUT[mode])},
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


def report_markdown(report: dict, method: list[str]) -> str:
    mode, baseline = report["mode"], report["baseline_condition"]
    n_base = report["n"].get(baseline, 0)
    lines = [f"# derm//os experiments ({mode.upper()})", "", *method,
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

def main(argv: list[str] | None = None, detect: F.Detector | None = None, client: Any = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--baseline", default="window", help="condition name used for Experiment 1")
    ap.add_argument("--actions", "--concerns", dest="actions", default=",".join(DEFAULT_CONCERNS),
                    help="comma-separated concerns (SD names; --hd maps them to HD)")
    ap.add_argument("--hd", action="store_true", help="HD, only if every photo can reach HD without upscaling")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--replay", action="store_true")
    ap.add_argument("--max-live", type=int, default=None, help="refuse a run that needs more live scans than this")
    ap.add_argument("--out", default="results")
    args = ap.parse_args(argv)

    folder, out = Path(args.folder), Path(args.out)
    concerns = [c.strip() for c in args.actions.split(",") if c.strip()]
    try:
        validate_actions(actions_for_mode(concerns, "sd"))
    except ValueError as e:
        print(f"Bad --actions: {e}")
        return 1

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

    if detect is None:
        try:
            detect = F.get_detector()
        except F.DetectorUnavailable as e:
            print(f"Face detector unavailable: {e}. Nothing sent.")
            return 1
    items, mode, why = prepare(groups, detect, args.hd)
    actions = actions_for_mode(concerns, mode)
    n_photos = len(items)
    print(f"\nPlan: {n_photos} photos, mode={mode.upper()}, actions={actions}")
    print_preparation(items, mode, why)
    refused = [it for it in items if not it.ok]
    legacy = legacy_stems(out)
    if legacy:
        print(f"\nMarked as palette-image results to be replaced (never reused or reported): "
              f"{', '.join(sorted(legacy))}")

    if not args.replay and client is None and not args.dry_run:
        try:
            client = YouCamClient()
        except YouCamError as e:
            hint = (" DERMOS_NO_DOTENV=1 is set in this shell, so backend/.env was skipped."
                    if os.environ.get("DERMOS_NO_DOTENV") == "1" else
                    f" Put YOUCAM_API_KEY in {BACKEND_DIR / '.env'} or set it in the shell.")
            print(f"Cannot start a live run: {e}.{hint}")
            return 1

    # Which photos would need a live scan, and the exact cost of that.
    try:
        to_send = [it for it in items if it.ok and not reusable(out, it, legacy)]
    except StaleResultError as e:
        print(f"\n{e}")
        return 1
    each, price_src = scan_price(client, actions)
    total = each * len(to_send)
    print(f"\nCost: {len(to_send)} live scan(s) x {each:g} units ({mode.upper()}, {len(actions)} concerns, "
          f"{price_src}) = {total:g} units. {n_photos - len(to_send) - len(refused)} reuse saved results.")

    bal = None
    if client is not None and not args.replay:
        try:
            bal = client.unit_balance()
        except Exception as e:  # noqa: BLE001 - reported below as "couldn't be read"
            print(f"YouCam unit balance unavailable ({type(e).__name__})")
        print(f"YouCam unit balance: {bal if bal is not None else 'unknown'}")

    if args.dry_run:
        if refused:
            print(f"\n{len(refused)} photo(s) would be refused: " + ", ".join(it.path.name for it in refused))
        thin = thin_conditions(groups)
        if thin:
            print(f"\n{thin}")
        if bal is not None:
            block = cost_blocker(len(to_send), each, bal, args.max_live)
            print("\n" + (f"A live run would be refused: {block}" if block else "The balance covers this run."))
        print("\nDry run: no scans sent. Remove --dry-run to run for real.")
        return 0

    # Nothing is sent unless every photo can be used and the run can produce a report.
    if refused:
        print(f"\nNothing sent: {len(refused)} photo(s) can't be prepared ("
              + "; ".join(f"{it.path.name}: {F.REFUSALS.get(it.refusal, it.refusal)}" for it in refused) + ").")
        return 1
    thin = thin_conditions(groups)
    if thin:
        print(f"\nNothing sent: {thin}")
        return 1
    if to_send and not args.replay:
        block = cost_blocker(len(to_send), each, bal, args.max_live)
        if block:
            print(f"\nNothing sent: {block}")
            return 1

    run = run_scans(items, actions, mode, out, client, args.replay, legacy=legacy)
    if not args.replay:
        print(f"\nLive scan requests sent this run: {run.live_sent} (YouCam only charges for successful scans)")
        try:
            after = client.unit_balance() if run.live_sent else None
        except Exception:  # noqa: BLE001 - informational
            after = None
        if after is not None:
            print(f"Units left: {after:g}")

    blocker = report_blocker(groups, run)
    if blocker:
        print(f"\nNo report written: {blocker} {out / 'report.md'} was left unchanged. "
              "Results that did succeed are saved and will be reused on the next run (no units).")
        return 1

    report = build_report(run, mode, actions, args.baseline)
    write_report(out, report, report_markdown(report, method_lines(items, mode, legacy)))
    print(f"\nSaved {out/'report.md'} and {out/'report.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
