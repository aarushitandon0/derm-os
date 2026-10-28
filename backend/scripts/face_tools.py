"""Local face detection and crop geometry for the experiment scripts.

Detection runs on this machine only (MediaPipe BlazeFace short-range); no image
leaves the computer. Geometry is plain arithmetic so tests need no detector.

Install (experiments only, not needed by the app):
    .venv\\Scripts\\python -m pip install -r requirements-experiments.txt
The model file (~230 KB) is downloaded to scripts/models/ on first use.
"""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from pathlib import Path

MODEL_PATH = Path(__file__).resolve().parent / "models" / "blaze_face_short_range.tflite"
MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/face_detector/"
             "blaze_face_short_range/float16/1/blaze_face_short_range.tflite")
DETECTOR_NAME = "MediaPipe BlazeFace short-range (local)"
MIN_DETECTION_SCORE = 0.5
YOUCAM_MIN_FACE_PCT = 60.0   # YouCam's documented minimum: face >= 60% of frame width
IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png")


@dataclass(frozen=True)
class Box:
    x: int
    y: int
    w: int
    h: int
    score: float = 1.0

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2

    def inside(self, left: int, top: int, width: int, height: int) -> bool:
        return (self.x >= left and self.y >= top and
                self.x + self.w <= left + width and self.y + self.h <= top + height)


def face_pct(face: Box, image_width: int) -> float:
    return round(100.0 * face.w / image_width, 1)


class CropError(ValueError):
    """A photo the fixed crop rule can't handle. The message says why."""


@dataclass(frozen=True)
class CropPlan:
    left: int
    top: int
    width: int
    height: int
    clamped: bool          # True if the box had to shift to stay inside the image
    face_pct_after: float  # detector face width as % of crop width

    @property
    def box(self) -> tuple[int, int, int, int]:
        return (self.left, self.top, self.left + self.width, self.top + self.height)

    def to_dict(self) -> dict:
        return asdict(self)


def plan_crop(img_w: int, img_h: int, face: Box, face_frac: float = 0.75,
              min_short_side: int = 480) -> CropPlan:
    """One rule for every photo: a 3:4 box centred on the face, with the face width set to
    `face_frac` of the crop width. The box is shifted (never resized) to stay inside the
    image. Raises CropError instead of distorting, padding or upscaling."""
    if not 0 < face_frac < 1:
        raise CropError(f"face_frac must be between 0 and 1, got {face_frac}")
    if face.w <= 0 or face.h <= 0:
        raise CropError("empty face box")
    k = round(face.w / face_frac / 3)       # width 3k, height 4k: exact 3:4
    cw, ch = 3 * k, 4 * k
    if cw > img_w or ch > img_h:
        raise CropError(f"a {cw}x{ch} crop does not fit in the {img_w}x{img_h} image "
                        f"(face is already {face_pct(face, img_w)}% of the width)")
    if cw < min_short_side:
        raise CropError(f"crop short side would be {cw}px, below the {min_short_side}px minimum; "
                        "move closer or use a higher-resolution photo (no upscaling)")
    want_left, want_top = round(face.cx - cw / 2), round(face.cy - ch / 2)
    left = min(max(want_left, 0), img_w - cw)
    top = min(max(want_top, 0), img_h - ch)
    if not face.inside(left, top, cw, ch):
        raise CropError("the face would not fit fully inside the crop")
    return CropPlan(left, top, cw, ch, (left, top) != (want_left, want_top),
                    round(100.0 * face.w / cw, 1))


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# -- detector (needs mediapipe; imported lazily so tests and the app never need it) ----------

def ensure_model() -> Path:
    if not MODEL_PATH.exists():
        import urllib.request
        MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = MODEL_PATH.with_suffix(".part")
        urllib.request.urlretrieve(MODEL_URL, tmp)  # model weights only, nothing is uploaded
        tmp.replace(MODEL_PATH)
    return MODEL_PATH


class FaceDetector:
    """Returns face boxes in the image's stored pixel coordinates (the same pixels a crop
    cuts and YouCam receives). Photos with an EXIF rotation tag are refused by the crop
    script, so stored and displayed pixels agree."""

    def __init__(self, min_score: float = MIN_DETECTION_SCORE):
        try:
            import mediapipe as mp
            from mediapipe.tasks.python import BaseOptions, vision
        except ImportError as e:  # pragma: no cover - depends on the local install
            raise RuntimeError("mediapipe is not installed in this venv: "
                               "pip install -r requirements-experiments.txt") from e
        self._mp = mp
        opts = vision.FaceDetectorOptions(base_options=BaseOptions(model_asset_path=str(ensure_model())),
                                          min_detection_confidence=min_score)
        self._det = vision.FaceDetector.create_from_options(opts)

    def __call__(self, path: str | Path) -> tuple[tuple[int, int], list[Box]]:
        import numpy as np
        from PIL import Image
        with Image.open(path) as im:
            size = im.size
            rgb = np.ascontiguousarray(np.asarray(im.convert("RGB")))
        res = self._det.detect(self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb))
        boxes = []
        for d in res.detections:
            b = d.bounding_box
            boxes.append(Box(int(b.origin_x), int(b.origin_y), int(b.width), int(b.height),
                             round(float(d.categories[0].score), 3) if d.categories else 1.0))
        return size, boxes

    def close(self) -> None:
        self._det.close()
