"""Crop experiment photos so the face fills enough of the frame for YouCam.

One rule for every photo (so the lighting experiment stays fair):
  * 3:4 crop, centred on the face found by a local detector,
  * face width = --face-frac of the crop width (default 0.75, above YouCam's 60% minimum
    because YouCam may measure the face differently from this detector),
  * shifted (never resized) to stay inside the image; refused if it can't fit,
  * no resizing, colour, brightness or rotation changes: pixels are copied as they are.

Layout (all inside the git-ignored photos/ folder):
    photos/raw/       originals (moved here on first run, never overwritten or deleted)
    photos/cropped/   crops with the same file names + crop_log.json

Usage (from backend/):
    .venv\\Scripts\\python scripts/crop_faces.py ../photos
    .venv\\Scripts\\python scripts/crop_faces.py ../photos --face-frac 0.80
Prints numbers only. Exit code 1 if any photo was refused.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.face_tools import (DETECTOR_NAME, IMAGE_SUFFIXES, YOUCAM_MIN_FACE_PCT, Box,  # noqa: E402
                                CropError, face_pct, plan_crop)

Detector = Callable[[Path], tuple[tuple[int, int], list[Box]]]
ORIENTATION_TAG = 0x0112


def move_originals(photos: Path) -> tuple[Path, list[str], list[str]]:
    """Move top-level photos into photos/raw/. Returns (raw_dir, moved, kept_in_place).
    A file is never moved onto an existing file, so nothing is overwritten."""
    raw = photos / "raw"
    raw.mkdir(exist_ok=True)
    moved, kept = [], []
    for p in sorted(photos.iterdir()):
        if not p.is_file() or p.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        dest = raw / p.name
        if dest.exists():
            kept.append(p.name)       # a same-named original is already in raw/: leave both
            continue
        p.rename(dest)                # same folder tree: a rename, no copy, no delete
        moved.append(p.name)
    return raw, moved, kept


def crop_one(src: Path, dest_dir: Path, detect: Detector, face_frac: float,
             min_short_side: int) -> dict:
    """Crop one photo. Returns a log entry; entry['ok'] is False with a 'reason' if refused."""
    from PIL import Image, ImageChops

    entry: dict = {"file": src.name, "ok": False}
    with Image.open(src) as im:
        orient = im.getexif().get(ORIENTATION_TAG)
    if orient not in (None, 1):
        entry["reason"] = f"EXIF orientation tag is {orient}; refusing (cropping would not match what is displayed)"
        return entry

    (w, h), faces = detect(src)
    entry.update(image_size=[w, h], faces_found=len(faces))
    if len(faces) != 1:
        entry["reason"] = "no face found" if not faces else f"{len(faces)} faces found (need exactly one)"
        return entry
    face = faces[0]
    entry.update(face_box=[face.x, face.y, face.w, face.h], detector_score=face.score,
                 face_pct_before=face_pct(face, w))
    try:
        plan = plan_crop(w, h, face, face_frac, min_short_side)
    except CropError as e:
        entry["reason"] = str(e)
        return entry

    dest_dir.mkdir(parents=True, exist_ok=True)
    out = dest_dir / src.name
    tmp = out.with_name(out.stem + ".part" + out.suffix)
    with Image.open(src) as im:
        crop = im.crop(plan.box)
        params = {k: im.info[k] for k in ("icc_profile", "exif", "dpi", "transparency") if k in im.info}
        crop.save(tmp, format=im.format, **params)
        # Prove "no other edits": the saved pixels must equal the source region exactly.
        with Image.open(tmp) as saved:
            same = (saved.size == crop.size and saved.mode == crop.mode and
                    ImageChops.difference(saved.convert("RGBA"), crop.convert("RGBA")).getbbox() is None)
    if not same:
        tmp.unlink(missing_ok=True)
        entry["reason"] = "saved crop did not match the source pixels; nothing written"
        return entry
    tmp.replace(out)

    entry.update(ok=True, crop_box=list(plan.box), clamped=plan.clamped, output_size=[plan.width, plan.height],
                 short_side=min(plan.width, plan.height), face_pct_after_planned=plan.face_pct_after,
                 pixels_identical_to_source=True)
    # Re-detect on the written crop: the number the dry-run check will see.
    (cw, _), after = detect(out)
    entry["face_pct_after_measured"] = face_pct(after[0], cw) if len(after) == 1 else None
    entry["faces_found_after"] = len(after)
    return entry


def run(photos: Path, detect: Detector, face_frac: float = 0.75, min_short_side: int = 480) -> dict:
    raw, moved, kept = move_originals(photos)
    out_dir = photos / "cropped"
    entries = [crop_one(p, out_dir, detect, face_frac, min_short_side)
               for p in sorted(raw.iterdir()) if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES]
    log = {
        "rule": {"aspect": "3:4", "face_width_fraction_of_crop": face_frac, "centred_on": "detected face box centre",
                 "bounds": "shifted to stay inside the image, never resized or padded",
                 "edits": "none besides cropping: no resizing, colour, brightness or rotation changes",
                 "min_short_side_px": min_short_side},
        "detector": DETECTOR_NAME,
        "youcam_min_face_pct": YOUCAM_MIN_FACE_PCT,
        "moved_to_raw": moved,
        "already_in_raw_left_in_place": kept,
        "photos": entries,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "crop_log.json").write_text(json.dumps(log, indent=2))
    return log


def print_summary(log: dict) -> None:
    if log["moved_to_raw"]:
        print(f"Moved {len(log['moved_to_raw'])} original(s) to raw/: {', '.join(log['moved_to_raw'])}")
    if log["already_in_raw_left_in_place"]:
        print("Same name already in raw/, left in place (not overwritten): "
              + ", ".join(log["already_in_raw_left_in_place"]))
    frac = log["rule"]["face_width_fraction_of_crop"]
    print(f"\nRule: 3:4 crop centred on face, face width = {frac:.0%} of crop width. Detector: {log['detector']}")
    print(f"{'photo':14s} {'faces':>5s} {'face% before':>12s} {'crop box (l,t,r,b)':>26s} {'output':>11s} "
          f"{'short':>6s} {'face% after':>11s}  note")
    for e in log["photos"]:
        if not e["ok"]:
            print(f"{e['file']:14s} {e.get('faces_found', '-')!s:>5s} {e.get('face_pct_before', '-')!s:>12s} "
                  f"{'-':>26s} {'-':>11s} {'-':>6s} {'-':>11s}  REFUSED: {e['reason']}")
            continue
        box = ",".join(str(v) for v in e["crop_box"])
        size = f"{e['output_size'][0]}x{e['output_size'][1]}"
        after = e["face_pct_after_measured"]
        note = "SD ok" if e["short_side"] >= 480 else "below SD"
        if e["clamped"]:
            note += ", shifted to fit"
        if e["short_side"] >= 1080:
            note += ", HD ok"
        print(f"{e['file']:14s} {e['faces_found']:>5d} {e['face_pct_before']:>12.1f} {box:>26s} {size:>11s} "
              f"{e['short_side']:>6d} {after if after is not None else '?'!s:>11s}  {note}")
    refused = [e["file"] for e in log["photos"] if not e["ok"]]
    print(f"\n{len(log['photos']) - len(refused)} cropped, {len(refused)} refused"
          + (f": {', '.join(refused)}" if refused else ""))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("photos", nargs="?", default=str(Path(__file__).resolve().parents[2] / "photos"))
    ap.add_argument("--face-frac", type=float, default=0.75)
    ap.add_argument("--min-short-side", type=int, default=480)
    args = ap.parse_args(argv)
    photos = Path(args.photos)
    if not photos.is_dir():
        print(f"No folder {photos}")
        return 1
    from scripts.face_tools import FaceDetector
    det = FaceDetector()
    try:
        log = run(photos, det, args.face_frac, args.min_short_side)
    finally:
        det.close()
    print_summary(log)
    print(f"Log: {photos / 'cropped' / 'crop_log.json'}")
    return 0 if all(e["ok"] for e in log["photos"]) else 1


if __name__ == "__main__":
    sys.exit(main())
