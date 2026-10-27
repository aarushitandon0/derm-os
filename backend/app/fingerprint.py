"""Capture fingerprint: the conditions a photo was taken under.

Server-side we measure what the pixels tell us (light level, colour cast,
resolution, device from EXIF). Face size and head pose come from the browser
(MediaPipe Face Landmarker) because the client already computes them for the
live capture guide.
"""
from __future__ import annotations

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


def measure(image_path: str | Path, face_ratio: float | None = None, yaw: float | None = None,
            pitch: float | None = None, roll: float | None = None) -> Fingerprint:
    with Image.open(image_path) as im:
        device, hour = _exif(im)
        im = ImageOps.exif_transpose(im).convert("RGB")
        w, h = im.size
        # Central region approximates the face in a guided capture (face fills 60-80% of width).
        box = (int(w * 0.30), int(h * 0.30), int(w * 0.70), int(h * 0.65))
        crop = im.crop(box)
        r, g, b = ImageStat.Stat(crop).mean
        luma = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255.0
        rb = r / b if b > 0 else 99.0
    return Fingerprint(w, h, round(luma, 4), round(rb, 4), device, hour, face_ratio, yaw, pitch, roll)
