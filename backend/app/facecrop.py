"""Server-side face crop and size normalisation for every capture.

YouCam's input rules (face big enough in the frame, minimum resolution) are the app's job,
not the user's. Every photo goes through the same steps before it is measured or sent:

  1. Read the photo upright (its own EXIF orientation tag, which is how the phone showed it;
     the picture itself is not rotated or straightened) and as full-colour RGB.
  2. Find faces with a local detector (MediaPipe BlazeFace, on this server; nothing leaves it).
     Exactly one face is required.
  3. Crop 3:4 around that face so the face width is FACE_FRAC (75%) of the crop width.
     The box is shifted, never resized, to stay inside the photo.
  4. Scale DOWN, never up, so the face width is exactly the mode's fixed target in pixels.
     SD: face 360 px -> 480 x 640 output (SD's minimum short side is 480 px).
     HD: face 810 px -> 1080 x 1440 output (HD's minimum short side is 1080 px).

No colour, brightness or rotation edits. The only pixel operations are the crop and a
downscale. Refusals are only for photos that can't be handled without breaking a rule
above, each with one plain fix.
"""
from __future__ import annotations

import hashlib
import io
import logging
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from PIL import Image, ImageOps

from . import modelstore
from . import photometa  # noqa: F401  (registers the HEIC decoder before any photo is opened)

log = logging.getLogger("dermos")

NORMALISE_VERSION = "norm-1.0"
FACE_FRAC = 0.75                                  # face width / crop width
OUTPUT = {"sd": (480, 640), "hd": (1080, 1440)}   # width x height after scaling (3:4)
TARGET_FACE_PX = {m: round(w * FACE_FRAC) for m, (w, _h) in OUTPUT.items()}   # sd 360, hd 810
MIN_DETECTION_SCORE = 0.5
DETECTOR_NAME = "MediaPipe BlazeFace short-range (local)"
ORIENTATION_TAG = 0x0112

MODEL_NAME = "blaze_face_short_range.tflite"   # found by app/modelstore.py (DERMOS_MODEL_DIR)
MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/face_detector/"
             "blaze_face_short_range/float16/1/blaze_face_short_range.tflite")

# One plain-language fix per refusal. Shown to the user as is.
REFUSALS = {
    "no_face": "We couldn't find a face. Face the camera with your whole face in view.",
    "several_faces": "More than one face is in view. Make sure you're the only one in the photo.",
    "too_far": "Hold the phone a little closer.",
    "too_close": "Hold the phone a little further away.",
    "out_of_frame": "Move so your whole face is inside the frame.",
    "unreadable": "That file couldn't be read as a photo. Use a JPEG or PNG.",
}


@dataclass(frozen=True)
class Box:
    x: float
    y: float
    w: float
    h: float
    score: float = 1.0

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2

    def inside(self, left: float, top: float, width: float, height: float) -> bool:
        eps = 1e-6
        return (self.x >= left - eps and self.y >= top - eps and
                self.x + self.w <= left + width + eps and self.y + self.h <= top + height + eps)


class Refusal(ValueError):
    """A photo that can't be normalised. `code` is a key of REFUSALS; `fix` is the user message."""

    def __init__(self, code: str, detail: str = ""):
        self.code = code
        self.fix = REFUSALS[code]
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


@dataclass(frozen=True)
class Plan:
    mode: str
    crop: tuple[float, float, float, float]   # left, top, right, bottom in upright original pixels
    output: tuple[int, int]
    scale: float                               # output px per original px (always <= 1)
    clamped: bool                              # box shifted to stay inside the photo

    def to_dict(self) -> dict:
        d = asdict(self)
        d["crop"] = [round(v, 2) for v in self.crop]
        d["scale"] = round(self.scale, 6)
        return d


def min_face_px(mode: str) -> int:
    return TARGET_FACE_PX[mode]


def plan(img_w: int, img_h: int, face: Box, mode: str = "sd") -> Plan:
    """The one crop-and-scale rule. Pure arithmetic, so it is deterministic and testable."""
    if mode not in OUTPUT:
        raise ValueError(f"unknown mode {mode!r}")
    if face.w <= 0 or face.h <= 0:
        raise Refusal("no_face", "empty face box")
    if face.x < 0 or face.y < 0 or face.x + face.w > img_w or face.y + face.h > img_h:
        raise Refusal("out_of_frame", "face box runs past the edge of the photo")
    target = TARGET_FACE_PX[mode]
    if face.w < target:
        raise Refusal("too_far", f"face is {face.w:.0f}px wide; {mode.upper()} needs {target}px without upscaling")
    cw = face.w / FACE_FRAC
    ch = cw * 4 / 3
    if cw > img_w or ch > img_h:
        raise Refusal("too_close", f"a {cw:.0f}x{ch:.0f} crop does not fit in the {img_w}x{img_h} photo")
    want_l, want_t = face.cx - cw / 2, face.cy - ch / 2
    left = min(max(want_l, 0.0), img_w - cw)
    top = min(max(want_t, 0.0), img_h - ch)
    if not face.inside(left, top, cw, ch):
        raise Refusal("out_of_frame", "the face would not fit fully inside the crop")
    out_w, out_h = OUTPUT[mode]
    return Plan(mode, (left, top, left + cw, top + ch), (out_w, out_h), out_w / cw,
                abs(left - want_l) > 1e-6 or abs(top - want_t) > 1e-6)


def mode_for(face: Box | None, requested: str, locked: str | None) -> str:
    """SD or HD for this capture. A trial keeps one mode for every capture (never mixed).
    HD only when asked for and the face is big enough to reach HD's size without upscaling."""
    if locked:
        return locked
    if requested == "hd" and face is not None and face.w >= TARGET_FACE_PX["hd"]:
        return "hd"
    return "sd"


@dataclass
class Normalised:
    image: Image.Image          # RGB, OUTPUT[mode] in size
    mode: str
    info: dict = field(default_factory=dict)

    def png_bytes(self) -> bytes:
        b = io.BytesIO()
        photometa.clean_copy(self.image).save(b, format="PNG")   # no metadata; lossless: no extra compression on top of the crop
        return b.getvalue()


Detector = Callable[[Image.Image], list[Box]]


def open_upright(path_or_bytes) -> tuple[Image.Image, dict]:
    """Open a photo as upright full-colour RGB. Returns (image, notes). Notes record the
    original colour mode (a palette or greyscale image can't regain colours it lost) and
    whether the EXIF orientation tag was applied."""
    try:
        src = Image.open(io.BytesIO(path_or_bytes) if isinstance(path_or_bytes, bytes) else path_or_bytes)
        src.load()
    except Exception as e:  # noqa: BLE001 - any decode failure is the same refusal
        raise Refusal("unreadable", type(e).__name__) from e
    with src:
        orient = src.getexif().get(ORIENTATION_TAG) or 1
        mode = src.mode
        up = ImageOps.exif_transpose(src) if orient != 1 else src
        rgb = up.convert("RGB")
    return rgb, {"source_mode": mode, "reduced_colour": mode not in ("RGB", "RGBA", "RGBX", "YCbCr", "CMYK"),
                 "exif_orientation": orient}


def normalise(img: Image.Image, faces: list[Box], requested: str = "sd", locked: str | None = None,
              notes: dict | None = None) -> Normalised:
    """Crop and scale one upright RGB photo with its detected faces."""
    if not faces:
        raise Refusal("no_face")
    if len(faces) > 1:
        raise Refusal("several_faces", f"{len(faces)} faces found")
    face = faces[0]
    w, h = img.size
    mode = mode_for(face, requested, locked)
    p = plan(w, h, face, mode)
    # One call does the crop and the downscale (scale <= 1 is guaranteed by plan()).
    out = img.resize(p.output, Image.Resampling.LANCZOS, box=p.crop)
    out.info = {}   # pixels only: the original's EXIF (GPS included) never reaches the crop
    info = {
        "version": NORMALISE_VERSION,
        "mode": mode,
        "face_frac": FACE_FRAC,
        "target_face_px": TARGET_FACE_PX[mode],
        "output": list(p.output),
        "crop_box": [round(v, 2) for v in p.crop],
        "scale": round(p.scale, 6),
        "clamped": p.clamped,
        "detector": DETECTOR_NAME,
        "detector_score": face.score,
        "original_size": [w, h],
        "face_px_original": round(face.w, 1),
        "face_pct_original": round(100.0 * face.w / w, 1),
        **(notes or {}),
    }
    return Normalised(out, mode, info)


def normalise_file(path_or_bytes, detect: Detector | None = None, requested: str = "sd",
                   locked: str | None = None) -> Normalised:
    img, notes = open_upright(path_or_bytes)
    faces = (detect or get_detector())(img)
    return normalise(img, faces, requested, locked, notes)


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


# ---------------------------------------------------------------- detector
class DetectorUnavailable(RuntimeError):
    pass


def ensure_model() -> Path:
    """The face model file. Never downloads at runtime (see app/modelstore.py)."""
    return modelstore.resolve(MODEL_NAME)


class BlazeFace:
    """Face boxes in the upright image's pixel coordinates. Thread-safe (one lock)."""

    def __init__(self, min_score: float = MIN_DETECTION_SCORE):
        try:
            import mediapipe as mp
            from mediapipe.tasks.python import BaseOptions, vision
        except ImportError as e:  # pragma: no cover - depends on the install
            raise DetectorUnavailable("mediapipe is not installed (pip install -r requirements.txt)") from e
        self._mp = mp
        opts = vision.FaceDetectorOptions(base_options=BaseOptions(model_asset_path=str(ensure_model())),
                                          min_detection_confidence=min_score)
        self._det = vision.FaceDetector.create_from_options(opts)
        self._lock = threading.Lock()

    def __call__(self, img: Image.Image) -> list[Box]:
        import numpy as np
        rgb = np.ascontiguousarray(np.asarray(img.convert("RGB")))
        with self._lock:
            res = self._det.detect(self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb))
        out = []
        for d in res.detections:
            b = d.bounding_box
            out.append(Box(float(b.origin_x), float(b.origin_y), float(b.width), float(b.height),
                           round(float(d.categories[0].score), 3) if d.categories else 1.0))
        return out

    def close(self) -> None:
        self._det.close()


_detector: Detector | None = None
_detector_lock = threading.Lock()
_failure_logged = False
_disabled: str | None = None   # set when the startup probe failed: MediaPipe is never loaded in-process


def disable(reason: str) -> None:
    """Never create the MediaPipe detector in this process (the child-process probe failed, and a
    native abort here would take the whole server down). Photo checks answer 503 instead."""
    global _disabled
    with _detector_lock:
        _disabled = reason


def get_detector() -> Detector:
    """The shared detector, created on first use. Tests replace it with set_detector()."""
    global _detector, _failure_logged
    with _detector_lock:
        if _detector is None and _disabled is not None:
            raise DetectorUnavailable(f"face detector disabled on this server ({_disabled})")
        if _detector is None:
            try:
                _detector = BlazeFace()
            except Exception as e:  # noqa: BLE001 - missing model, missing library, runtime failure
                reason = f"{type(e).__name__}: {e}"
                if not _failure_logged:   # the real cause, once per process (no image data here)
                    log.error("Face detector failed to start: %s", reason)
                    _failure_logged = True
                if isinstance(e, DetectorUnavailable):
                    raise
                raise DetectorUnavailable(f"face detector failed to start ({reason})") from e
        return _detector


def set_detector(det: Detector | None) -> None:
    """Tests replace the detector; this also clears disable()."""
    global _detector, _disabled
    with _detector_lock:
        _detector, _disabled = det, None


def describe() -> dict:
    """The method, for /api/meta and reports."""
    return {"version": NORMALISE_VERSION, "aspect": "3:4", "face_frac": FACE_FRAC,
            "target_face_px": dict(TARGET_FACE_PX), "output": {m: list(v) for m, v in OUTPUT.items()},
            "detector": DETECTOR_NAME, "upscaling": False, "edits": "crop and downscale only"}
