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

import math
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageOps, ImageStat


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
    # The EV the camera metered the scene at, normalised to ISO 100, from EXIF ExposureTime,
    # FNumber and ISO. None when any of those is absent, which never counts as a match.
    exposure_ev: float | None = None
    # "camera" | "upload": shown as a badge only. The comparability gate never reads it.
    capture_source: str | None = None

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
    """Camera label and capture hour only (DateTimeOriginal, else DateTime). GPS is never read."""
    try:
        raw = img.getexif()
    except Exception:
        return None, None
    device = " ".join(str(raw.get(t)).strip().rstrip("\x00") for t in (0x010F, 0x0110) if raw.get(t)) or None
    stamp = None
    try:
        stamp = raw.get_ifd(0x8769).get(0x9003)
    except Exception:
        stamp = None
    hour = None
    for v in (stamp, raw.get(0x0132)):
        if v:
            try:
                hour = datetime.strptime(str(v).strip().rstrip("\x00"), "%Y:%m:%d %H:%M:%S").hour
                break
            except ValueError:
                continue
    return clean_device_label(device), hour


# ---------------------------------------------------------------- exposure
# EXIF exposure tags, read by number like the ones above. No other tag is touched.
_TAG_EXPOSURE_TIME = 0x829A
_TAG_FNUMBER = 0x829D
_TAG_ISO = 0x8827
_TAG_PHOTOGRAPHIC_SENSITIVITY = 0x8833
_IFD_EXIF = 0x8769


def _num(v) -> float | None:
    """A float from an EXIF value, which may be a Rational, a tuple or a string."""
    if v is None or isinstance(v, (bytes, bytearray)):
        return None
    if isinstance(v, (list, tuple)):
        v = v[0] if v else None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f > 0 and f == f and f not in (float("inf"), float("-inf")) else None


def exposure_ev(img: Image.Image) -> float | None:
    """How much light the camera decided the scene had, from its own settings.

    This is the EV the camera metered the scene at, normalised to ISO 100:

        EV = log2(FNumber^2 / ExposureTime) - log2(ISO / 100)

    A brighter scene makes the camera pick a shorter exposure, a smaller aperture or a lower ISO,
    which all push EV up. That makes it an independent read on the light, measured by the camera at
    the moment of capture, rather than inferred from the pixels afterwards. It is useful precisely
    where pixel brightness is not: auto-exposure hides a lighting change by brightening a dim room,
    so two photos can match on luminance while the light they were taken in did not.

    Returns None when any of the three tags is missing, which is the normal case for a photo taken
    in the browser (a canvas JPEG carries no EXIF). None is never treated as a match.
    """
    try:
        raw = img.getexif()
        sub = raw.get_ifd(_IFD_EXIF)
    except Exception:  # noqa: BLE001 - a broken or absent EXIF block is the same as none
        return None
    t = _num(sub.get(_TAG_EXPOSURE_TIME))
    n = _num(sub.get(_TAG_FNUMBER))
    iso = _num(sub.get(_TAG_ISO)) or _num(sub.get(_TAG_PHOTOGRAPHIC_SENSITIVITY))
    if t is None or n is None or iso is None:
        return None
    try:
        ev = math.log2((n * n) / t) - math.log2(iso / 100.0)
    except (ValueError, ZeroDivisionError):
        return None
    return round(ev, 3)


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
            # Exposure always comes from the ORIGINAL photo: the normalised copy carries no EXIF.
            ev = exposure_ev(src)
    with Image.open(image_path) as im:
        if exif_path is None:
            device, hour = _exif(im)
            ev = exposure_ev(im)
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
    fp = Fingerprint(w, h, round(luma, 4), round(rb, 4), device, hour, face_ratio, yaw, pitch, roll,
                     device_src, hour_src)
    fp.exposure_ev = ev
    return fp


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
