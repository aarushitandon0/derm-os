"""Capture fingerprint: the conditions a photo was taken under.

Server-side we measure what the pixels tell us (light level, colour cast,
resolution, device from EXIF). Face size and head pose come from the browser
(MediaPipe Face Landmarker) because the client already computes them for the
live capture guide.

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
            client_hour: int | None = None, client_device: str | None = None) -> Fingerprint:
    with Image.open(image_path) as im:
        device, hour = _exif(im)
        device_src = "exif" if device else None
        hour_src = "exif" if hour is not None else None
        if device is None and clean_device_label(client_device):
            device, device_src = clean_device_label(client_device), "client"
        if hour is None and client_hour is not None and 0 <= int(client_hour) <= 23:
            hour, hour_src = int(client_hour), "client"
        im = ImageOps.exif_transpose(im).convert("RGB")
        w, h = im.size
        # Central region approximates the face in a guided capture (face fills 60-80% of width).
        box = (int(w * 0.30), int(h * 0.30), int(w * 0.70), int(h * 0.65))
        crop = im.crop(box)
        r, g, b = ImageStat.Stat(crop).mean
        luma = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255.0
        rb = r / b if b > 0 else 99.0
    return Fingerprint(w, h, round(luma, 4), round(rb, 4), device, hour, face_ratio, yaw, pitch, roll,
                       device_src, hour_src)
