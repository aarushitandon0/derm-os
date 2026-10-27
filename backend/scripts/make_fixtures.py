"""Copy real YouCam results (from run_experiments.py) into demo fixtures.

    python scripts/make_fixtures.py                       # defaults below, persona "riya"
    python scripts/make_fixtures.py --persona me --map "window_1,window_2,window_3=baseline" "window_4,window_5=checkin" "lamp_*=lamp"
    python scripts/make_fixtures.py --dry-run

Each results/<stem>.json goes to fixtures/<persona>/<set>/<stem>.json, and any
masks in results/media/<stem>/ go to fixtures/<persona>/<set>/<stem>.masks/.
No API calls; no units spent. Existing synthetic fixtures in a target set are
removed so real and made-up scans are never mixed in one set.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import shutil
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
DEFAULT_MAP = ["window_1,window_2,window_3=baseline", "window_4,window_5=checkin", "lamp_*=lamp"]


def parse_map(items: list[str]) -> list[tuple[list[str], str]]:
    out = []
    for it in items:
        pats, _, target = it.partition("=")
        if not target:
            raise SystemExit(f"Bad --map entry {it!r}; use 'pattern,pattern=set'")
        out.append(([x.strip() for x in pats.split(",") if x.strip()], target.strip()))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=str(BACKEND / "results"))
    ap.add_argument("--fixtures", default=str(BACKEND / "fixtures"))
    ap.add_argument("--persona", default="riya")
    ap.add_argument("--map", nargs="+", default=DEFAULT_MAP)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    res, fix = Path(a.results), Path(a.fixtures) / a.persona
    stems = sorted(p.stem for p in res.glob("*.json") if p.stem != "report")
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
            blob = json.loads((res / f"{st}.json").read_text(encoding="utf-8"))
            blob.setdefault("meta", {})["recorded_from"] = f"results/{st}.json"
            (dest / f"{st}.json").write_text(json.dumps(blob, indent=2), encoding="utf-8")
            masks = res / "media" / st
            if masks.is_dir():
                shutil.copytree(masks, dest / f"{st}.masks", dirs_exist_ok=True)
    print("Dry run, nothing copied." if a.dry_run else f"Done. Fixtures in {fix}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
