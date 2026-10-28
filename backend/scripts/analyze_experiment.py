"""False-change analysis: how often does each rule call a change when nothing changed?

Runs on saved results only (no network, no units):
    python scripts/analyze_experiment.py                 # reads results/, updates results/report.md
    python scripts/analyze_experiment.py --results path  # another results folder

run_experiments.py calls this after a full live run (or --replay). Inputs, per photo:
    results/<cond>_<n>.json              the YouCam result (raw scores)
    results/<cond>_<n>.fingerprint.json  capture conditions of the normalised photo
"window_*" photos are the no-change set; "lamp_*" photos are the same face under a warm lamp.

What it computes (report.md section "False-change analysis"):
  a) Noise: per concern, min/max/range over every window photo, and the median and max range
     over every 3-photo subset (the app's baseline is 3 scans).
  b) A fixed-threshold rule (+-5 / +-4): over every window pair x concern, the % where the
     absolute score difference is bigger than 5 (and 4).
  c) derm//os, PRE-REGISTERED: every split of the window photos into a 3-photo baseline and a
     disjoint 2-photo check-in, judged by the engine's own verdict function (app.evidence.evaluate,
     with the current TOLERANCES and MIN_BAND, unchanged). Per concern, the % of splits whose
     verdict is "moved beyond your noise". The first result is frozen in
     results/preregistered.json and never replaced; a later run with different constants is
     reported beside it as "after tuning on these same photos".
  d) Lighting: per concern, the mean window-minus-lamp shift beside the 3-photo range, and the %
     of window-vs-lamp photo pairs the comparability gate marks "not comparable".
  e) One plain headline sentence, with n.

Nothing is written unless there are at least 3 window and 2 lamp photos with results.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path
from statistics import mean, median

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app import evidence as E  # noqa: E402  (module import: tests can watch E.evaluate)
from app.fingerprint import Fingerprint  # noqa: E402
from app.youcam import load_result  # noqa: E402

NO_CHANGE, LAMP = "window", "lamp"
MIN_WINDOW, MIN_LAMP = 3, 2
BASELINE_N, CHECKIN_N = 3, 2           # the app's baseline and check-in sizes
THRESHOLDS = (5.0, 4.0)
FIXED_LABEL = "a fixed-threshold rule (±5 / ±4)"
TUNED_LABEL = "after tuning on these same photos"
PREREG_FILE = "preregistered.json"
START, END = "<!-- false-change:start -->", "<!-- false-change:end -->"
_STEM = re.compile(r"^([a-z]+)_(\d+)$")


class AnalysisError(RuntimeError):
    """Why the analysis can't be written (shown to the user as is)."""


@dataclass
class Shot:
    name: str
    cond: str
    capture: E.Capture


# -- loading -------------------------------------------------------------------------------

def load_shots(results: Path) -> list[Shot]:
    """Every <cond>_<n>.json result in `results` that has a saved fingerprint, in name order."""
    legacy = set()
    marker = results / "legacy_palette.json"
    if marker.exists():
        legacy = {Path(f).stem for f in json.loads(marker.read_text()).get("files", [])}
    shots = []
    for p in sorted(results.glob("*.json")):
        m = _STEM.match(p.stem)
        if not m or p.stem in legacy:
            continue
        fp_path = results / f"{p.stem}.fingerprint.json"
        if not fp_path.exists():
            raise AnalysisError(f"{p.name} has no saved capture conditions ({fp_path.name}). Re-run "
                                "scripts/run_experiments.py on the photos (with --replay: no units) to save them.")
        res = load_result(p)
        fp = Fingerprint.from_dict(json.loads(fp_path.read_text()))
        shots.append(Shot(p.stem, m.group(1), E.Capture(res.raw_scores(), fp, res.mode, tuple(res.actions))))
    return shots


def split(shots: list[Shot]) -> tuple[list[Shot], list[Shot]]:
    window = [s for s in shots if s.cond == NO_CHANGE]
    lamp = [s for s in shots if s.cond == LAMP]
    if len(window) < MIN_WINDOW or len(lamp) < MIN_LAMP:
        raise AnalysisError(f"Needs at least {MIN_WINDOW} window and {MIN_LAMP} lamp photos with results; "
                            f"found {len(window)} window and {len(lamp)} lamp. Nothing written.")
    return window, lamp


def shared_concerns(shots: list[Shot]) -> list[str]:
    keys = [set(s.capture.scores) for s in shots]
    return sorted(set.intersection(*keys)) if keys else []


def _pct(k: int, n: int) -> float | None:
    return round(100.0 * k / n, 1) if n else None


# -- a) noise ------------------------------------------------------------------------------

def noise(window: list[Shot], concerns: list[str]) -> dict[str, dict]:
    out = {}
    for k in concerns:
        vals = [s.capture.scores[k] for s in window]
        subs = [max(c) - min(c) for c in combinations(vals, BASELINE_N)]
        out[k] = {"n": len(vals), "min": round(min(vals), 2), "max": round(max(vals), 2),
                  "range": round(max(vals) - min(vals), 2), "n_subsets3": len(subs),
                  "subset3_median_range": round(median(subs), 2), "subset3_max_range": round(max(subs), 2)}
    return out


# -- b) fixed threshold --------------------------------------------------------------------

def fixed_threshold(window: list[Shot], concerns: list[str], thresholds=THRESHOLDS) -> dict:
    pairs = list(combinations(window, 2))
    out = {"n_photos": len(window), "n_pairs": len(pairs), "concerns": concerns, "by_threshold": {}}
    for t in thresholds:
        per = {}
        for k in concerns:
            hits = sum(abs(a.capture.scores[k] - b.capture.scores[k]) > t for a, b in pairs)
            per[k] = {"n": len(pairs), "flagged": hits, "pct": _pct(hits, len(pairs))}
        n = len(pairs) * len(concerns)
        flagged = sum(v["flagged"] for v in per.values())
        out["by_threshold"][f"{t:g}"] = {"n": n, "flagged": flagged, "pct": _pct(flagged, n), "per_concern": per}
    return out


# -- c) derm//os verdict -------------------------------------------------------------------

def splits(window: list[Shot]) -> list[tuple[list[Shot], list[Shot]]]:
    """Every 3-photo baseline with a disjoint 2-photo check-in."""
    out = []
    for bi in combinations(range(len(window)), BASELINE_N):
        rest = [i for i in range(len(window)) if i not in bi]
        for ci in combinations(rest, CHECKIN_N):
            out.append(([window[i] for i in bi], [window[i] for i in ci]))
    return out


def constants() -> dict:
    return {"rule_version": E.RULE_VERSION, "tolerances": dict(E.TOLERANCES), "min_band": E.MIN_BAND}


def dermos_false_change(window: list[Shot], concerns: list[str]) -> dict:
    """The engine's own verdict on every split. Nothing changed, so any "moved" is a false change."""
    sp = splits(window)
    per = {}
    for k in concerns:
        verdicts: dict[str, int] = {}
        for base, chk in sp:
            rep = E.evaluate([s.capture for s in base], [s.capture for s in chk], E.TrialContext(1, []),
                             concerns=[k], band=E.MIN_BAND)
            verdicts[rep.verdict.value] = verdicts.get(rep.verdict.value, 0) + 1
        moved = verdicts.get(E.Verdict.MOVED.value, 0)
        per[k] = {"n": len(sp), "moved": moved, "pct": _pct(moved, len(sp)), "verdicts": verdicts}
    n = len(sp) * len(concerns)
    moved = sum(v["moved"] for v in per.values())
    return {"n_photos": len(window), "n_splits": len(sp), "n": n, "moved": moved, "pct": _pct(moved, n),
            "per_concern": per, **constants()}


# -- d) lighting ---------------------------------------------------------------------------

def lighting(window: list[Shot], lamp: list[Shot], concerns: list[str], noise_rows: dict) -> dict:
    per = {}
    for k in concerns:
        shift = mean(s.capture.scores[k] for s in window) - mean(s.capture.scores[k] for s in lamp)
        per[k] = {"mean_shift_window_minus_lamp": round(shift, 2),
                  "subset3_median_range": noise_rows[k]["subset3_median_range"],
                  "subset3_max_range": noise_rows[k]["subset3_max_range"],
                  "shift_beyond_max_range": abs(shift) > noise_rows[k]["subset3_max_range"]}
    pairs = [(w, la) for w in window for la in lamp]
    failed_fields: dict[str, int] = {}
    blocked = 0
    for w, la in pairs:
        comp = E.compare_conditions([w.capture], [la.capture])
        if not comp.comparable:
            blocked += 1
            for f in {x["field"] for x in comp.failed}:
                failed_fields[f] = failed_fields.get(f, 0) + 1
    return {"n_window": len(window), "n_lamp": len(lamp), "n_pairs": len(pairs), "not_comparable": blocked,
            "pct_not_comparable": _pct(blocked, len(pairs)), "failed_fields": failed_fields, "per_concern": per}


# -- pre-registration ----------------------------------------------------------------------

def inputs_hash(shots: list[Shot]) -> str:
    blob = json.dumps([[s.name, sorted(s.capture.scores.items())] for s in shots], sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def preregistration(results: Path, shots: list[Shot], current: dict) -> tuple[dict, dict | None]:
    """(pre-registered result, result after tuning or None). The first result for this set of photos
    is frozen in preregistered.json; it is never replaced."""
    path = results / PREREG_FILE
    h = inputs_hash(shots)
    if not path.exists():
        frozen = {"frozen_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "inputs": h,
                  "result": current}
        path.write_text(json.dumps(frozen, indent=2))
        return current, None
    frozen = json.loads(path.read_text())
    if frozen.get("inputs") != h:
        raise AnalysisError(f"{path.name} was frozen for a different set of photos or scores. It is never "
                            "replaced: move it aside by hand if this is a new shoot.")
    pre = frozen["result"]
    same = all(pre.get(k) == current.get(k) for k in ("rule_version", "tolerances", "min_band"))
    return pre, (None if same else current)


# -- e) report -----------------------------------------------------------------------------

def analyse(shots: list[Shot], results: Path) -> dict:
    window, lamp = split(shots)
    concerns = shared_concerns(window + lamp)
    if not concerns:
        raise AnalysisError("The window and lamp results share no concern. Nothing written.")
    nz = noise(window, concerns)
    out = {"concerns": concerns, "noise": nz, "fixed_threshold": fixed_threshold(window, concerns),
           "lighting": lighting(window, lamp, concerns, nz)}
    pre, tuned = preregistration(results, shots, dermos_false_change(window, concerns))
    out["dermos_preregistered"] = pre
    out["dermos_after_tuning"] = tuned
    out["headline"] = headline(out)
    return out


def headline(a: dict) -> str:
    ft, pre, li = a["fixed_threshold"], a["dermos_preregistered"], a["lighting"]
    five = ft["by_threshold"]["5"]
    return (f"With nothing changed ({ft['n_photos']} photos of the same face, same window light, "
            f"{len(a['concerns'])} concern{'' if len(a['concerns']) == 1 else 's'}), a fixed ±5-point rule called a change in {five['pct']}% of "
            f"{five['n']} photo-pair comparisons; derm//os's pre-registered verdict said "
            f"\"moved beyond your noise\" in {pre['pct']}% of {pre['n']} baseline/check-in splits. "
            f"Under a warm lamp, the comparability gate marked {li['pct_not_comparable']}% of "
            f"{li['n_pairs']} window-vs-lamp photo pairs not comparable.")


def markdown(a: dict) -> str:
    c = a["concerns"]
    ft, pre, tuned, li = a["fixed_threshold"], a["dermos_preregistered"], a["dermos_after_tuning"], a["lighting"]
    L = [START, "## False-change analysis", "", f"**Headline:** {a['headline']}", "",
         "These comparisons share photos (every pair and every split reuses the same few scans), so they "
         "are not independent and the percentages are not error rates with confidence intervals. "
         "This analysis and the benchmark are ours (we wrote both), not an independent evaluation.", "",
         f"### a) Noise with nothing changed (n={ft['n_photos']} window photos)", "",
         "| Concern | Min | Max | Range (all) | 3-photo range, median | 3-photo range, max |",
         "| --- | --- | --- | --- | --- | --- |"]
    L += [f"| {k} | {r['min']} | {r['max']} | {r['range']} | {r['subset3_median_range']} | {r['subset3_max_range']} |"
          for k, r in a["noise"].items()]
    L += ["", f"3-photo subsets per concern: {a['noise'][c[0]]['n_subsets3']} (the app's baseline is 3 scans).", "",
          f"### b) False changes under {FIXED_LABEL}", "",
          f"Every pair of window photos ({ft['n_pairs']} pairs) x {len(c)} concerns. A pair counts as a "
          "false change when the scores differ by more than the threshold.", "",
          "| Threshold | " + " | ".join(c) + " | All |", "| --- | " + " | ".join("---" for _ in c) + " | --- |"]
    for t, row in ft["by_threshold"].items():
        L.append(f"| > {t} | " + " | ".join(f"{row['per_concern'][k]['pct']}% ({row['per_concern'][k]['flagged']}/"
                                            f"{row['per_concern'][k]['n']})" for k in c)
                 + f" | **{row['pct']}%** ({row['flagged']}/{row['n']}) |")
    L += ["", "### c) derm//os verdict, pre-registered", "",
          f"Every split of the {pre['n_photos']} window photos into a 3-photo baseline and a disjoint 2-photo "
          f"check-in ({pre['n_splits']} splits), judged by `app.evidence.evaluate` with rule set "
          f"{pre['rule_version']}, TOLERANCES {json.dumps(pre['tolerances'])} and MIN_BAND {pre['min_band']}, "
          "unchanged. A split counts as a false change when the verdict is \"moved beyond your noise\".", ""]
    L += _verdict_table(pre, c)
    if tuned:
        L += ["", f"### c') derm//os verdict, {TUNED_LABEL}", "",
              f"Rule set {tuned['rule_version']}, TOLERANCES {json.dumps(tuned['tolerances'])}, MIN_BAND "
              f"{tuned['min_band']}. These constants were chosen after seeing these photos, so this number "
              "is optimistic. The pre-registered number above is the one to quote.", ""]
        L += _verdict_table(tuned, c)
    L += ["", f"### d) Lighting: window vs warm lamp (n={li['n_window']} vs {li['n_lamp']})", "",
          "| Concern | Mean shift (window - lamp) | 3-photo range, median | 3-photo range, max | Shift bigger than max range |",
          "| --- | --- | --- | --- | --- |"]
    L += [f"| {k} | {r['mean_shift_window_minus_lamp']:+} | {r['subset3_median_range']} | {r['subset3_max_range']} | "
          f"{'yes' if r['shift_beyond_max_range'] else 'no'} |" for k, r in li["per_concern"].items()]
    fields = ", ".join(f"{f} {n}" for f, n in sorted(li["failed_fields"].items())) or "none"
    L += ["", f"Comparability gate on every window-vs-lamp photo pair: **{li['pct_not_comparable']}% not comparable** "
              f"({li['not_comparable']}/{li['n_pairs']}). Failed checks: {fields}.", "", END]
    return "\n".join(L) + "\n"


def _verdict_table(r: dict, concerns: list[str]) -> list[str]:
    rows = ["| Concern | \"Moved beyond your noise\" | Other verdicts |", "| --- | --- | --- |"]
    for k in concerns:
        p = r["per_concern"][k]
        other = ", ".join(f"{v} {n}" for v, n in sorted(p["verdicts"].items()) if v != E.Verdict.MOVED.value)
        rows.append(f"| {k} | {p['pct']}% ({p['moved']}/{p['n']}) | {other or '-'} |")
    rows.append(f"| **All** | **{r['pct']}%** ({r['moved']}/{r['n']}) | |")
    return rows


def write(results: Path, a: dict) -> Path:
    (results / "false_change.json").write_text(json.dumps(a, indent=2))
    md_path = results / "report.md"
    section = markdown(a)
    old = md_path.read_text(encoding="utf-8") if md_path.exists() else "# derm//os experiments\n"
    if START in old and END in old:
        new = old[:old.index(START)] + section.rstrip("\n") + old[old.index(END) + len(END):]
    else:
        new = old.rstrip("\n") + "\n\n" + section
    md_path.write_text(new, encoding="utf-8")
    return md_path


def run(results: Path, log=print) -> int:
    try:
        a = analyse(load_shots(results), results)
    except AnalysisError as e:
        log(f"False-change analysis not written: {e}")
        return 1
    path = write(results, a)
    log(f"\n=== False-change analysis ===\n{a['headline']}")
    if a["dermos_after_tuning"]:
        log(f"After tuning on these same photos: {a['dermos_after_tuning']['pct']}% "
            f"(pre-registered number kept: {a['dermos_preregistered']['pct']}%).")
    log(f"Saved {path} and {results / 'false_change.json'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--results", default=str(BACKEND_DIR / "results"))
    return run(Path(ap.parse_args(argv).results))


if __name__ == "__main__":
    sys.exit(main())
