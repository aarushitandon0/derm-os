"""Free photo check before a paid tone scan: head pose and light, on this server, no YouCam call.

Head pose (yaw / pitch / roll, degrees) comes from MediaPipe Face Landmarker's facial
transformation matrix, the same model and the same maths as the live camera guide
(frontend/src/capture/faceGuide.ts), so a camera shot and an upload are measured alike.
Camera shots can send the browser's own numbers instead.

This check only blocks photos that can't be read at all. A slightly turned selfie is normal and
passes; the tone scan itself is sent at the most lenient face-angle strictness YouCam allows
(youcam.TONE_STRICTNESS). Thresholds are set well past a normal selfie and short of a side profile:

    |yaw|   > 35   side profile: one cheek is mostly hidden, so a skin colour can't be read
    |pitch| > 30   chin far up or down: the forehead or cheeks drop out of view
    |roll|  > 30   head lying on one side
    luminance < 0.12 on the face region (0..1): too dark to read a colour

A face cut off by the frame is already refused by app/facecrop.py (out_of_frame).
"""
from __future__ import annotations

import math
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from PIL import Image

RULE_VERSION = "precheck-1.0"
MAX_YAW = 35.0
MAX_PITCH = 30.0
MAX_ROLL = 30.0
MIN_LUMINANCE = 0.12

FIXES = {
    "side_profile": "Turn a little more toward the camera so both cheeks are in view, and try again.",
    "head_tilt_up_down": "Level your chin so your whole face is in view, and try again.",
    "head_on_side": "Hold your head upright and try again.",
    "too_dark": "It's too dark. Face a window or a bright, even light and try again.",
}

_APP = Path(__file__).resolve().parent
MODEL_NAME = "face_landmarker.task"
MODEL_PATHS = (_APP / "models" / MODEL_NAME, _APP.parent / "scripts" / "models" / MODEL_NAME)
MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/face_landmarker/"
             "face_landmarker/float16/1/face_landmarker.task")


@dataclass(frozen=True)
class Pose:
    yaw: float
    pitch: float
    roll: float
    source: str = "server"    # "server" (measured here) | "client" (the browser's live guide)

    def to_dict(self) -> dict:
        return {k: (round(v, 1) if isinstance(v, float) else v) for k, v in asdict(self).items()}


def angles_from_matrix(m) -> tuple[float, float, float]:
    """(yaw, pitch, roll) in degrees from a 4x4 facial transformation matrix (row-major,
    m[row][col]), exactly as faceGuide.ts reads its column-major copy."""
    r00, r10, r20, r21, r22 = m[0][0], m[1][0], m[2][0], m[2][1], m[2][2]
    pitch = math.degrees(math.atan2(r21, r22))
    yaw = math.degrees(math.asin(max(-1.0, min(1.0, -r20))))
    roll = math.degrees(math.atan2(r10, r00))
    return yaw, pitch, roll


def check(pose: Pose | None, luminance: float | None) -> tuple[str, str] | None:
    """(code, plain fix) for a photo that can't be read, else None. An unknown pose is not a
    reason to refuse (YouCam's own check still runs)."""
    if luminance is not None and luminance < MIN_LUMINANCE:
        return "too_dark", FIXES["too_dark"]
    if pose is None:
        return None
    if abs(pose.yaw) > MAX_YAW:
        return "side_profile", FIXES["side_profile"]
    if abs(pose.pitch) > MAX_PITCH:
        return "head_tilt_up_down", FIXES["head_tilt_up_down"]
    if abs(pose.roll) > MAX_ROLL:
        return "head_on_side", FIXES["head_on_side"]
    return None


def thresholds() -> dict:
    return {"rule_version": RULE_VERSION, "max_yaw": MAX_YAW, "max_pitch": MAX_PITCH,
            "max_roll": MAX_ROLL, "min_luminance": MIN_LUMINANCE}


# ---------------------------------------------------------------- the estimator
Estimator = Callable[[Image.Image], "Pose | None"]


def ensure_model() -> Path:
    for p in MODEL_PATHS:
        if p.exists():
            return p
    import urllib.request
    dest = MODEL_PATHS[0]
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part")
    urllib.request.urlretrieve(MODEL_URL, tmp)  # model weights only; nothing is uploaded
    tmp.replace(dest)
    return dest


class Landmarker:
    """Head pose of the single face in an upright RGB image, or None if no face is found."""

    def __init__(self):
        import mediapipe as mp
        from mediapipe.tasks.python import BaseOptions, vision
        self._mp = mp
        opts = vision.FaceLandmarkerOptions(base_options=BaseOptions(model_asset_path=str(ensure_model())),
                                            num_faces=1, output_facial_transformation_matrixes=True)
        self._det = vision.FaceLandmarker.create_from_options(opts)
        self._lock = threading.Lock()

    def __call__(self, img: Image.Image) -> Pose | None:
        import numpy as np
        rgb = np.ascontiguousarray(np.asarray(img.convert("RGB")))
        with self._lock:
            res = self._det.detect(self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb))
        mats = getattr(res, "facial_transformation_matrixes", None) or []
        if not mats:
            return None
        return Pose(*angles_from_matrix(np.asarray(mats[0])), source="server")


_est: Estimator | None = None
_est_failed = False
_lock = threading.Lock()


def estimate(img: Image.Image) -> Pose | None:
    """The pose, or None when no face is found or the model can't run here (never raises:
    the precheck must not be the reason a photo can't be scanned)."""
    global _est, _est_failed
    with _lock:
        if _est is None and not _est_failed:
            try:
                _est = Landmarker()
            except Exception:  # noqa: BLE001 - missing package, no network for the model, ...
                _est_failed = True
        est = _est
    if est is None:
        return None
    try:
        return est(img)
    except Exception:  # noqa: BLE001
        return None


def set_estimator(est: Estimator | None) -> None:
    """Tests replace the model with a fake."""
    global _est, _est_failed
    with _lock:
        _est, _est_failed = est, False
