"""Run derm//os Experiments 1 and 2 on real photos and print the numbers.

Experiment 1 (noise floor): 5 photos, same face, same light, same phone,
  re-framing between shots.        -> how much scores move with no change at all.
Experiment 2 (lighting):  3 photos by a window + 3 under a warm lamp, same
  session.                         -> how much a light change alone moves scores.

Name your photos by condition, then a number:
    photos/window_1.jpg ... window_5.jpg   (Experiment 1 + baseline for 2)
    photos/lamp_1.jpg   ... lamp_3.jpg     (Experiment 2)

Usage:
    export YOUCAM_API_KEY=...
    python scripts/run_experiments.py photos --dry-run        # check plan + photo sizes, no units spent
    python scripts/run_experiments.py photos                  # real run (SD by default)
    python scripts/run_experiments.py photos --replay         # recompute from saved results, no API calls
    python scripts/run_experiments.py photos --hd             # HD actions (needs 1080 px short side)

Outputs results/<photo>.json (raw YouCam responses), results/report.json and results/report.md.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.settings  # noqa: E402,F401  (loads backend/.env)
from app.evidence import Capture, compare_conditions, noise_summary, ranges  # noqa: E402
from app.fingerprint import measure  # noqa: E402
from app.youcam import YouCamClient, YouCamError, load_result, save_result, validate_actions  # noqa: E402

DEFAULT_CONCERNS = ["redness", "texture", "acne", "pore", "oiliness", "moisture", "radiance", "age_spot"]


def group_photos(folder: Path) -> dict[str, list[Path]]:
    groups: dict[str, list[Path]] = defaultdict(list)
    for p in sorted(folder.iterdir()):
        if p.suffix.lower() not in (".jpg", ".jpeg", ".png"):
            continue
        cond = p.stem.rsplit("_", 1)[0] if "_" in p.stem else p.stem
        groups[cond].append(p)
    return dict(groups)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--baseline", default="window", help="condition name used for Experiment 1")
    ap.add_argument("--concerns", default=",".join(DEFAULT_CONCERNS))
    ap.add_argument("--hd", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--replay", action="store_true")
    ap.add_argument("--out", default="results")
    args = ap.parse_args()

    folder, out = Path(args.folder), Path(args.out)
    concerns = [c.strip() for c in args.concerns.split(",") if c.strip()]
    actions = [f"hd_{c}" if args.hd else c for c in concerns]
    if args.hd:
        actions = [a.replace("hd_dark_circle_v2", "hd_dark_circle") for a in actions]
    mode = validate_actions(actions)

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
        print("\nDry run: no API calls made. Remove --dry-run to run for real.")
        return 0

    client = None if args.replay else YouCamClient()
    captures: dict[str, list[Capture]] = defaultdict(list)
    for cond, photos in groups.items():
        for p in photos:
            res_path = out / f"{p.stem}.json"
            try:
                if args.replay or res_path.exists():
                    res = load_result(res_path)
                    src = "replay"
                else:
                    res = client.analyze(p, actions)
                    save_result(res, res_path)
                    src = "live"
            except (YouCamError, FileNotFoundError) as e:
                msg = getattr(e, "friendly", None) or str(e)
                print(f"  ! {p.name}: {msg}")
                continue
            print(f"  {src:6s} {p.name}: " + ", ".join(f"{k}={v:.1f}" for k, v in sorted(res.raw_scores().items())))
            captures[cond].append(Capture(res.raw_scores(), fps[p.name], mode, tuple(actions)))

    base = captures.get(args.baseline, [])
    report = {"mode": mode, "actions": actions, "baseline_condition": args.baseline,
              "experiment_1": noise_summary(base), "experiment_2": {}}

    print(f"\n=== Experiment 1: noise with no change ({args.baseline}, n={len(base)}) ===")
    print(f"{'concern':12s} {'min':>7s} {'max':>7s} {'range':>7s}")
    for k, s in report["experiment_1"].items():
        print(f"{k:12s} {s['min']:7.2f} {s['max']:7.2f} {s['range']:7.2f}")

    for cond, caps in captures.items():
        if cond == args.baseline:
            continue
        br, cr = ranges(base), ranges(caps)
        comp = compare_conditions(base, caps)
        rows = {}
        print(f"\n=== Experiment 2: {args.baseline} vs {cond} (n={len(base)} vs {len(caps)}) ===")
        print(f"{'concern':12s} {'base mean':>10s} {cond+' mean':>12s} {'shift':>7s} {'noise range':>12s}  beyond noise?")
        for k in sorted(set(br) & set(cr)):
            bm = mean(c.scores[k] for c in base if k in c.scores)
            cm = mean(c.scores[k] for c in caps if k in c.scores)
            outside = cr[k].lo > br[k].hi or cr[k].hi < br[k].lo
            rows[k] = {"baseline_mean": round(bm, 2), "condition_mean": round(cm, 2), "shift": round(cm - bm, 2),
                       "baseline_range": round(br[k].width, 2), "beyond_noise": outside}
            print(f"{k:12s} {bm:10.2f} {cm:12.2f} {cm - bm:+7.2f} {br[k].width:12.2f}  {'YES' if outside else 'no'}")
        print("comparability gate:", "comparable" if comp.comparable else "NOT comparable -> " + " ".join(comp.reasons))
        report["experiment_2"][cond] = {"concerns": rows, "gate_comparable": comp.comparable,
                                        "gate_reasons": comp.reasons}

    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(report, indent=2))
    lines = [f"# derm//os experiments ({mode.upper()})", "",
             f"## Experiment 1: {len(base)} scans, nothing changed", "",
             "| Concern | Min | Max | Range |", "| --- | --- | --- | --- |"]
    lines += [f"| {k} | {s['min']} | {s['max']} | {s['range']} |" for k, s in report["experiment_1"].items()]
    for cond, r in report["experiment_2"].items():
        lines += ["", f"## Experiment 2: {args.baseline} vs {cond}", "",
                  f"Gate: {'comparable' if r['gate_comparable'] else 'NOT comparable: ' + ' '.join(r['gate_reasons'])}", "",
                  "| Concern | Shift | Noise range | Beyond noise |", "| --- | --- | --- | --- |"]
        lines += [f"| {k} | {v['shift']:+} | {v['baseline_range']} | {'yes' if v['beyond_noise'] else 'no'} |"
                  for k, v in r["concerns"].items()]
    (out / "report.md").write_text("\n".join(lines) + "\n")
    print(f"\nSaved {out/'report.md'} and {out/'report.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
