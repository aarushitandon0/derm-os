"""Uploaded photos: what is accepted, what is read from them, and what is kept.

Accepted: JPEG, PNG, and HEIC/HEIF (decoded by pillow-heif, which ships Python 3.12 wheels for
Linux and Windows) up to 15 MB. Anything else gets one plain fix.

Read from EXIF, and nothing else: the capture time (DateTimeOriginal, else DateTime) and a coarse
camera label (Make + Model). GPS and every other tag are never read, stored or logged.

Kept: the photo itself never is. Every image this server writes (the crop sent to YouCam, saved
masks) is re-encoded from its pixels alone, so no EXIF, GPS, ICC, XMP or text chunk survives.

Baseline integrity (uploads; approved rules):
  a) two pixel-identical photos (after decoding) are refused;
  b) EXIF times all within 15 minutes: accepted. Any time missing: the user is asked whether the
     photos were taken in one sitting; "yes" is stored as "user-confirmed". Times spread over more
     than 15 minutes: refused as a baseline.
"""
from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass
from datetime import datetime, timedelta

from PIL import Image

try:   # HEIC/HEIF support. Without it, HEIC photos get the "save as JPEG" fix.
    import pillow_heif

    pillow_heif.register_heif_opener()
    HEIC_SUPPORTED = True
except Exception:  # noqa: BLE001 - optional at runtime
    HEIC_SUPPORTED = False

MAX_UPLOAD_BYTES = 15 * 1024 * 1024
BASELINE_WINDOW = timedelta(minutes=15)
UPLOAD_COUNT = {"baseline": 3, "checkin": 2}

MSG = {
    "too_big": "That photo is over 15 MB. Choose the original photo from your camera, not a large export.",
    "format": "That file type isn't supported. Use a JPEG or PNG photo.",
    "heic": "Save the photo as JPEG (on iPhone: Settings → Camera → Formats → Most Compatible).",
    "empty": "That file is empty. Choose the photo again.",
    "duplicate": "These look like the same photo. Upload 3 different shots.",
    "spread": "Your first photos need to be taken a few minutes apart, in one sitting.",
    "confirm_sitting": "Were these taken within a few minutes of each other, in the same spot?",
    "palette": "This photo has reduced colours (it may be a screenshot or an edited copy). The original photo works best.",
}

_TAG_DATETIME = 0x0132
_TAG_MAKE, _TAG_MODEL = 0x010F, 0x0110
_IFD_EXIF = 0x8769
_TAG_DATETIME_ORIGINAL = 0x9003


class UploadRefused(ValueError):
    def __init__(self, code: str):
        self.code = code
        self.fix = MSG[code]
        super().__init__(code)


def sniff(data: bytes) -> str | None:
    """'jpeg' | 'png' | 'heic' from the file's own bytes (never the file name), else None."""
    if data[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[4:8] == b"ftyp" and data[8:12] in (b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis",
                                               b"hevm", b"hevs", b"mif1", b"msf1"):
        return "heic"
    return None


def check_file(data: bytes) -> str:
    """Size and type check before decoding. Returns the format or raises UploadRefused."""
    if not data:
        raise UploadRefused("empty")
    if len(data) > MAX_UPLOAD_BYTES:
        raise UploadRefused("too_big")
    kind = sniff(data)
    if kind is None:
        raise UploadRefused("format")
    if kind == "heic" and not HEIC_SUPPORTED:
        raise UploadRefused("heic")
    return kind


@dataclass(frozen=True)
class ExifMeta:
    taken_at: datetime | None    # local camera time, no zone (EXIF has none); used only for the baseline check
    hour: int | None
    device: str | None           # "Make Model", trimmed; None when the photo has neither

    def to_public(self) -> dict:
        return {"hour": self.hour, "device": self.device or "not recorded"}


def _parse_time(v) -> datetime | None:
    try:
        return datetime.strptime(str(v).strip().rstrip("\x00"), "%Y:%m:%d %H:%M:%S")
    except (TypeError, ValueError):
        return None


def read_meta(data: bytes) -> ExifMeta:
    """Capture time and camera label only. Reads three tags by number; GPS is never touched."""
    try:
        with Image.open(io.BytesIO(data)) as im:
            ex = im.getexif()
            taken = None
            try:
                taken = _parse_time(ex.get_ifd(_IFD_EXIF).get(_TAG_DATETIME_ORIGINAL))
            except Exception:  # noqa: BLE001 - a broken sub-IFD is the same as none
                taken = None
            taken = taken or _parse_time(ex.get(_TAG_DATETIME))
            device = " ".join(str(ex.get(t)).strip().rstrip("\x00") for t in (_TAG_MAKE, _TAG_MODEL)
                              if ex.get(t)) or None
    except Exception:  # noqa: BLE001 - unreadable EXIF = no EXIF
        return ExifMeta(None, None, None)
    from .fingerprint import clean_device_label
    return ExifMeta(taken, taken.hour if taken else None, clean_device_label(device))


def pixel_hash(img: Image.Image) -> str:
    """Hash of the decoded, upright RGB pixels: two files with the same picture match even when
    their metadata differs."""
    rgb = img.convert("RGB")
    h = hashlib.sha256(f"{rgb.width}x{rgb.height}:".encode())
    h.update(rgb.tobytes())
    return h.hexdigest()


def clean_copy(img: Image.Image) -> Image.Image:
    """A copy built from pixels alone: no EXIF, GPS, ICC profile, XMP or text."""
    out = Image.new(img.mode, img.size)
    out.paste(img)
    if img.mode == "P" and img.getpalette():
        out.putpalette(img.getpalette())
    out.info = {}
    return out


def clean_bytes(data: bytes) -> tuple[bytes, str] | None:
    """Re-encode an image file from its pixels only. Returns (bytes, extension) or None when the
    data isn't a decodable image (the caller then doesn't store it)."""
    try:
        with Image.open(io.BytesIO(data)) as im:
            im.load()
            fmt = (im.format or "").upper()
            clean = clean_copy(im)
    except Exception:  # noqa: BLE001
        return None
    b = io.BytesIO()
    if fmt in ("JPEG", "MPO"):
        clean.convert("RGB").save(b, "JPEG", quality=95)
        return b.getvalue(), ".jpg"
    if fmt == "WEBP":
        clean.save(b, "WEBP", lossless=True)
        return b.getvalue(), ".webp"
    clean.save(b, "PNG")
    return b.getvalue(), ".png"


def has_metadata(data: bytes) -> bool:
    """True when an image file carries EXIF, XMP, ICC or PNG text. For tests and checks."""
    with Image.open(io.BytesIO(data)) as im:
        im.load()
        if len(im.getexif()):
            return True
        if any(k in im.info for k in ("exif", "xmp", "XML:com.adobe.xmp", "icc_profile", "comment")):
            return True
        return bool(getattr(im, "text", None))   # PNG tEXt / iTXt chunks


def baseline_integrity(hashes: list[str], times: list[datetime | None], same_sitting: bool | None) -> dict:
    """Rules (a) and (b) above. Returns {"ok", "code", "message", "timing", "needs_confirmation"}."""
    def out(ok, code=None, timing=None, ask=False):
        return {"ok": ok, "code": code, "message": MSG[code] if code else None, "timing": timing,
                "needs_confirmation": ask}

    if len(set(hashes)) < len(hashes):
        return out(False, "duplicate")
    known = [t for t in times if t is not None]
    if len(known) >= 2 and max(known) - min(known) > BASELINE_WINDOW:
        return out(False, "spread")
    if len(known) == len(times):
        return out(True, timing="exif")
    if same_sitting is True:
        return out(True, timing="user-confirmed")
    if same_sitting is False:
        return out(False, "spread")
    return out(False, "confirm_sitting", ask=True)
