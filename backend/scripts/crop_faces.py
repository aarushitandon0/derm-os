"""Preview what YouCam would receive: writes the app's normalised copy of each photo.

Uses the app's own crop and scale (app/facecrop.py), the same code run_experiments.py and
/api/scan use. Nothing here is a second rule: run_experiments.py normalises the originals
itself and never reads these previews. Originals are not moved or changed.

    .venv\Scripts\python scripts/crop_faces.py ../photos            # -> ../photos/normalised/*.png
    .venv\Scripts\python scripts/crop_faces.py ../photos --hd

The output folder sits inside the git-ignored photos/ folder. Prints numbers only.
Exit code 1 if any photo was refused.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import facecrop as F  # noqa: E402

IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png")


def run(photos: Path, detect: F.Detector, want_hd: bool = False, out_name: str = "normalised") -> dict:
    out = photos / out_name
    entries = []
    for p in sorted(photos.iterdir()):
        if not p.is_file() or p.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        e: dict = {"file": p.name, "ok": False}
        try:
            n = F.normalise_file(str(p), detect, "hd" if want_hd else "sd")
        except F.Refusal as r:
            e.update(refusal=r.code, fix=r.fix)
            entries.append(e)
            continue
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{p.stem}.png").write_bytes(n.png_bytes())
        e.update(ok=True, **{k: n.info[k] for k in ("mode", "original_size", "face_px_original", "face_pct_original",
                                                     "scale", "clamped", "output", "source_mode", "exif_orientation")})
        entries.append(e)
    log = {"method": F.describe(), "photos": entries}
    if entries:
        out.mkdir(parents=True, exist_ok=True)
        (out / "normalise_log.json").write_text(json.dumps(log, indent=2))
    return log


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("photos", nargs="?", default=str(Path(__file__).resolve().parents[2] / "photos"))
    ap.add_argument("--hd", action="store_true")
    args = ap.parse_args(argv)
    photos = Path(args.photos)
    if not photos.is_dir():
        print(f"No folder {photos}")
        return 1
    log = run(photos, F.get_detector(), args.hd)
    for e in log["photos"]:
        if e["ok"]:
            print(f"{e['file']:16s} {e['mode']}  face {e['face_px_original']:.0f}px ({e['face_pct_original']}%) "
                  f"x{e['scale']:.3f} -> {e['output'][0]}x{e['output'][1]}  colour mode {e['source_mode']}")
        else:
            print(f"{e['file']:16s} REFUSED: {e['fix']}")
    return 0 if all(e["ok"] for e in log["photos"]) else 1


if __name__ == "__main__":
    sys.exit(main())
