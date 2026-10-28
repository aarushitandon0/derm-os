"""DEMO_MODE: replay recorded YouCam responses instead of spending units.

Layout:
    backend/fixtures/<persona>/<set>/<name>.json        save_result() format
    backend/fixtures/<persona>/<set>/<name>.masks/*.png  optional mask images

<set> defaults to the scan phase ("baseline", "checkin"); extra sets such as
"lamp" can be requested explicitly. Files are served in name order, rotating,
so a 3-shot baseline replays the 3 recorded baseline scans.

The uploaded photo is still fingerprinted from its real pixels, so the
comparability gate reacts to the real light even in demo mode. Every replayed
capture is labelled source="replay" (and synthetic=True for hand-made data) so
the UI can say "prepared data".
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from . import photometa
from .youcam import SkinResult, load_result

BACKEND_DIR = Path(__file__).resolve().parents[1]
_SAFE = re.compile(r"^[a-z0-9][a-z0-9_\-]{0,40}$")


# What a fresh deploy starts with (only when the database is empty; see main.seed_if_empty).
# Riya's 4-step routine from the design doc's hero flow. Her history is logged during the demo.
PERSONA_SEED: dict[str, dict] = {
    "riya": {"shelf": ["cl-01", "sr-01", "mo-01", "sp-01"]},
}


def fixtures_dir() -> Path:
    return Path(os.environ.get("DERMOS_FIXTURES", BACKEND_DIR / "fixtures"))


class FixtureError(LookupError):
    pass


@dataclass
class Replay:
    result: SkinResult
    path: Path
    persona: str
    set: str
    synthetic: bool
    mask_dir: Path | None


def personas() -> dict[str, list[str]]:
    root = fixtures_dir()
    if not root.is_dir():
        return {}
    return {p.name: sorted(s.name for s in p.iterdir() if s.is_dir() and any(s.glob("*.json")))
            for p in sorted(root.iterdir()) if p.is_dir()}


def pick(persona: str, fixture_set: str, index: int) -> Replay:
    for name, val in (("persona", persona), ("fixture set", fixture_set)):
        if not _SAFE.match(val or ""):
            raise FixtureError(f"Invalid {name} {val!r}")
    folder = fixtures_dir() / persona / fixture_set
    files = sorted(folder.glob("*.json"))
    if not files:
        have = personas()
        raise FixtureError(
            f"No recorded scans for persona '{persona}', set '{fixture_set}'. "
            f"Available: {have or 'none'}. Run scripts/make_fixtures.py or turn DEMO_MODE off.")
    path = files[index % len(files)]
    meta = json.loads(path.read_text(encoding="utf-8")).get("meta", {})
    mask_dir = path.with_suffix(".masks")
    return Replay(load_result(path), path, persona, fixture_set, bool(meta.get("synthetic")),
                  mask_dir if mask_dir.is_dir() else None)


def copy_masks(replay: Replay, dest: Path) -> dict[str, list[Path]]:
    """Copy recorded mask images into this capture's media folder.
    Mask files are named <concern>_<n>.<ext>."""
    out: dict[str, list[Path]] = {}
    if not replay.mask_dir:
        return out
    for f in sorted(replay.mask_dir.iterdir()):
        if f.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp") or "_" not in f.stem:
            continue
        clean = photometa.clean_bytes(f.read_bytes())   # stored from pixels only: no metadata
        if clean is None:
            continue
        dest.mkdir(parents=True, exist_ok=True)
        target = dest / (f.stem + clean[1])
        target.write_bytes(clean[0])
        out.setdefault(f.stem.rsplit("_", 1)[0], []).append(target)
    return out
