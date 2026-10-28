"""Copy real YouCam results (from run_experiments.py) into demo fixtures, stripped for publishing.

    python scripts/make_fixtures.py                       # defaults below, persona "riya"
    python scripts/make_fixtures.py --persona me --map "window_1,window_2,window_3=baseline" "window_4,window_5=checkin" "lamp_*=lamp"
    python scripts/make_fixtures.py --dry-run

Fixtures are committed to a public repo, so each one keeps ONLY:
  * scores (raw_score, ui_score, HD region raw scores, overall, skin age)
  * the action set and SD/HD mode
  * the engine version (YouCam API version the result came from)
  * the capture fingerprint (numbers measured from the photo: light, colour, size,
    EXIF device/hour), when the photo is still in --photos

Everything else is dropped: mask URLs, task ids, file names inside the response,
and any field this script doesn't know. Mask images are never copied.
No API calls; no units spent. Existing synthetic fixtures in a target set are
removed so real and made-up scans are never mixed in one set.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.fingerprint import measure  # noqa: E402
from app.youcam import SkinResult, load_result  # noqa: E402

BACKEND = Path(__file__).resolve().parents[1]
DEFAULT_MAP = ["window_1,window_2,window_3=baseline", "window_4,window_5=checkin", "lamp_*=lamp"]
DEFAULT_ENGINE = "v2.1"   # run_experiments.py always uses YouCamClient(version="v2.1")
PHOTO_EXTS = (".jpg", ".jpeg", ".png")


def parse_map(items: list[str]) -> list[tuple[list[str], str]]:
    out = []
    for it in items:
        pats, _, target = it.partition("=")
        if not target:
            raise SystemExit(f"Bad --map entry {it!r}; use 'pattern,pattern=set'")
        out.append(([x.strip() for x in pats.split(",") if x.strip()], target.strip()))
    return out


def _r(x: float | None) -> float | None:
    return None if x is None else round(float(x), 4)


def sanitize(res: SkinResult, engine: str, fingerprint: dict | None, stem: str) -> dict[str, Any]:
    """Rebuild a fixture from parsed numbers only, so nothing unexpected can ride along."""
    output = []
    for name, sc in sorted(res.scores.items()):
        item: dict[str, Any] = {"type": f"hd_{name}" if res.mode == "hd" else name,
                                "raw_score": _r(sc.raw_score), "ui_score": _r(sc.ui_score)}
        for reg, v in sorted(sc.regions.items()):
            if reg != "whole":
                item[reg] = {"raw_score": _r(v)}
        output.append(item)
    results: dict[str, Any] = {"output": output}
    if res.overall is not None:
        results["all"] = {"score": _r(res.overall)}
    if res.skin_age is not None:
        results["skin_age"] = _r(res.skin_age)
    return {"meta": {"mode": res.mode, "actions": list(res.actions), "engine": f"YouCam skin-analysis {engine}",
                     "fingerprint": fingerprint, "recorded_from": stem, "synthetic": False},
            "response": {"data": {"task_status": "success", "results": results}}}


_URLISH = re.compile(r"(https?:|://|\.(png|jpe?g|webp|heic|heif)\b)", re.I)


def leaks(blob: Any) -> list[str]:
    """Every string in the fixture that looks like a URL or an image path (should be none)."""
    found: list[str] = []
    if isinstance(blob, dict):
        for k, v in blob.items():
            found += leaks(k) + leaks(v)
    elif isinstance(blob, list):
        for v in blob:
            found += leaks(v)
    elif isinstance(blob, str) and _URLISH.search(blob):
        found.append(blob)
    return found


def find_photo(photos: Path, stem: str) -> Path | None:
    for ext in PHOTO_EXTS:
        for cand in (photos / f"{stem}{ext}", photos / f"{stem}{ext.upper()}"):
            if cand.is_file():
                return cand
    return None


def fingerprint_for(photos: Path | None, stem: str) -> dict | None:
    if photos is None:
        return None
    p = find_photo(photos, stem)
    if p is None:
        return None
    fp = measure(p).to_dict()   # numbers only; the photo itself is never read into the fixture
    return {k: v for k, v in fp.items() if v is not None}


def build_fixture(result_path: Path, photos: Path | None) -> dict[str, Any]:
    meta = json.loads(result_path.read_text(encoding="utf-8")).get("meta", {})
    res = load_result(result_path)
    blob = sanitize(res, meta.get("api_version") or DEFAULT_ENGINE, fingerprint_for(photos, result_path.stem),
                    result_path.stem)
    bad = leaks(blob)
    if bad:
        raise SystemExit(f"Refusing to write {result_path.stem}: URL or image path found in fixture.")
    return blob


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=str(BACKEND / "results"))
    ap.add_argument("--fixtures", default=str(BACKEND / "fixtures"))
    ap.add_argument("--photos", default=str(BACKEND.parent / "photos"),
                    help="where the original photos are, to measure the fingerprint (not copied)")
    ap.add_argument("--persona", default="riya")
    ap.add_argument("--map", nargs="+", default=DEFAULT_MAP)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    res, fix = Path(a.results), Path(a.fixtures) / a.persona
    photos = Path(a.photos) if Path(a.photos).is_dir() else None
    # Results made from palette PNGs (results/legacy_palette.json) are never turned into fixtures.
    marker = res / "legacy_palette.json"
    legacy = {Path(f).stem for f in json.loads(marker.read_text()).get("files", [])} if marker.exists() else set()
    stems = sorted(p.stem for p in res.glob("*.json")
                   if p.stem not in ("report", "benchmark", "legacy_palette") and not p.stem.endswith(".source")
                   and p.stem not in legacy)
    if legacy:
        print(f"Skipping palette-image results: {', '.join(sorted(legacy))}")
    if not stems:
        print(f"No result files in {res}. Run scripts/run_experiments.py first.")
        return 1

    plan: dict[str, list[str]] = {}
    for pats, target in parse_map(a.map):
        for st in stems:
            if any(fnmatch.fnmatch(st, pt) for pt in pats) and st not in sum(plan.values(), []):
                plan.setdefault(target, []).append(st)
    if not plan:
        print(f"No results matched {a.map}. Found: {stems}")
        return 1

    for target, members in plan.items():
        dest = fix / target
        print(f"{a.persona}/{target}: {', '.join(members)}")
        if a.dry_run:
            continue
        dest.mkdir(parents=True, exist_ok=True)
        for old in dest.glob("*.json"):
            if json.loads(old.read_text(encoding="utf-8")).get("meta", {}).get("synthetic"):
                old.unlink()
                shutil.rmtree(old.with_suffix(".masks"), ignore_errors=True)
        for st in members:
            blob = build_fixture(res / f"{st}.json", photos)
            (dest / f"{st}.json").write_text(json.dumps(blob, indent=2), encoding="utf-8")
            print(f"  {st}: scores + actions + engine" + (" + fingerprint" if blob["meta"]["fingerprint"] else
                                                          " (no photo found, fingerprint not recorded)"))
    print("Dry run, nothing copied." if a.dry_run else
          f"Done. Fixtures in {fix}. Mask images are never copied into fixtures.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
