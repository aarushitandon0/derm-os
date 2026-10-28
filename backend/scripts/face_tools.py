"""Kept for older imports. The crop rule and detector now live in app/facecrop.py, which the
app and scripts/run_experiments.py both use (one code path)."""
from __future__ import annotations

from app.facecrop import (DETECTOR_NAME, FACE_FRAC, OUTPUT, REFUSALS, TARGET_FACE_PX, BlazeFace,  # noqa: F401
                          Box, Refusal, normalise, normalise_file, open_upright, plan, sha256_bytes)

IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png")


def face_pct(face: Box, image_width: int) -> float:
    return round(100.0 * face.w / image_width, 1)


def sha256_file(path) -> str:
    with open(path, "rb") as f:
        return sha256_bytes(f.read())
