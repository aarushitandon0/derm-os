"""Capture fingerprint: the conditions a photo was taken under.

Server-side we measure what the pixels tell us (light level, colour cast,
resolution, device from EXIF). Head pose comes from the browser (MediaPipe Face
Landmarker) because the client already computes it for the live capture guide.

Face size: every capture is cropped and scaled the same way first (app/facecrop.py),
so the fingerprint keeps both the ORIGINAL face size (face_px_original, % of the
original frame) and the NORMALISED one (face_px, face_ratio). The comparability gate
reads face_ratio, which is the normalised value, so a normal change in distance from
the camera no longer makes two photos "not comparable". Light is measured on the
normalised image, which is the image YouCam analyses.

Camera shots taken in the browser carry no EXIF (the canvas JPEG has none), so
the phone also sends its local capture hour and a coarse device label (camera
track label or platform, plus resolution). Those are used only when EXIF has
nothing; `device_source` / `hour_source` record where each value came from.
A field with neither stays None and the gate reports it as "not recorded".
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from PIL import ExifTags, Image, ImageOps, ImageStat


@dataclass
class Fingerprint:
    width: int
    height: int
    luminance: float            # 0..1, mean luma of the central face region
    red_blue_ratio: float       # >1 = warmer light, <1 = cooler light
    device: str | None = None   # EXIF make+model when present
    captured_hour: int | None = None
    face_ratio: float | None = None   # face width / image width (client)
    yaw: float | None = None          # degrees (client)
    pitch: float | None = None
    roll: float | None = None
    device_source: str | None = None  # "exif" | "client" | None
    hour_source: str | None = None    # "exif" | "client" | None
    # Normalisation (None on fingerprints saved before it existed).
    face_px: float | None = None             # face width in the normalised capture
    face_px_original: float | None = None    # face width in the original photo
    face_pct_original: float | None = None   # ... as % of the original photo's width
    original_width: int | None = None
    original_height: int | None = None
    face_ratio_live: float | None = None     # the browser's own live estimate, for reference only
    normalisation: dict | None = None        # method, target, crop box, scale (facecrop.normalise info)

    @property
    def short_side(self) -> int:
        return min(self.width, self.height)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["short_side"] = self.short_side
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Fingerprint":
        keys = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in keys})


def _exif(img: Image.Image) -> tuple[str | None, int | None]:
    try:
        raw = img.getexif()
    except Exception:
        return None, None
    tags = {ExifTags.TAGS.get(k, k): v for k, v in raw.items()}
    device = " ".join(str(tags[k]).strip() for k in ("Make", "Model") if tags.get(k)) or None
    hour = None
    stamp = tags.get("DateTime")
    if stamp:
        try:
            hour = datetime.strptime(str(stamp), "%Y:%m:%d %H:%M:%S").hour
        except ValueError:
            pass
    return device, hour


_CTRL = re.compile(r"[\x00-\x1f\x7f]+")
MAX_DEVICE_LABEL = 80


def clean_device_label(label: str | None) -> str | None:
    """Coarse, display-safe device label from the client: no control characters, capped length."""
    if not label:
        return None
    s = re.sub(r"\s+", " ", _CTRL.sub(" ", str(label))).strip()
    return s[:MAX_DEVICE_LABEL] or None


def measure(image_path: str | Path, face_ratio: float | None = None, yaw: float | None = None,
            pitch: float | None = None, roll: float | None = None,
            client_hour: int | None = None, client_device: str | None = None,
            exif_path: str | Path | None = None) -> Fingerprint:
    """`exif_path`: read camera and time from this file instead (the original photo, when
    `image_path` is its normalised copy, which carries no EXIF)."""
    if exif_path is not None:
        with Image.open(exif_path) as src:
            device, hour = _exif(src)
    with Image.open(image_path) as im:
        if exif_path is None:
            device, hour = _exif(im)
        device_src = "exif" if device else None
        hour_src = "exif" if hour is not None else None
        if device is None and clean_device_label(client_device):
            device, device_src = clean_device_label(client_device), "client"
        if hour is None and client_hour is not None and 0 <= int(client_hour) <= 23:
            hour, hour_src = int(client_hour), "client"
        im = ImageOps.exif_transpose(im).convert("RGB")
        w, h = im.size
        # In a normalised capture (app/facecrop.py) the face is centred at 75% of the width, so this
        # region is forehead, eyes, nose and cheeks. On an un-normalised photo it is the frame centre.
        box = (int(w * 0.30), int(h * 0.30), int(w * 0.70), int(h * 0.65))
        crop = im.crop(box)
        r, g, b = ImageStat.Stat(crop).mean
        luma = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255.0
        rb = r / b if b > 0 else 99.0
    return Fingerprint(w, h, round(luma, 4), round(rb, 4), device, hour, face_ratio, yaw, pitch, roll,
                       device_src, hour_src)


def measure_normalised(norm_path: str | Path, original_path: str | Path, info: dict,
                       yaw: float | None = None, pitch: float | None = None, roll: float | None = None,
                       client_hour: int | None = None, client_device: str | None = None,
                       face_ratio_live: float | None = None) -> Fingerprint:
    """Fingerprint of a normalised capture (see app/facecrop.py) with the original face size kept."""
    out_w = info["output"][0]
    fp = measure(norm_path, info["target_face_px"] / out_w, yaw, pitch, roll, client_hour, client_device,
                 exif_path=original_path)
    fp.face_px = float(info["target_face_px"])
    fp.face_px_original = info["face_px_original"]
    fp.face_pct_original = info["face_pct_original"]
    fp.original_width, fp.original_height = info["original_size"]
    fp.face_ratio_live = face_ratio_live
    fp.normalisation = {k: info[k] for k in ("version", "mode", "face_frac", "target_face_px", "output",
                                             "crop_box", "scale", "clamped", "source_mode",
                                             "exif_orientation") if k in info}
    return fp
