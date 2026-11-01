"""Undertone engine (undertone-1.0): the skin colour YouCam returns -> an undertone and a shade family.

What the API gives (YouCam AI Facial Color Tones Analyzer, POST /s2s/v2.0/task/skin-tone-analysis):
a colour, not an undertone. The documented success payload is

    {"data": {"task_status": "success", "results": {
        "face_quality": {"has_face": true, "area": "good", "frontal": "good", "lighting": "good", ...},
        "color": {"skin_color": "#b9947c", "eye_color": "#62432e", "lip_color": "#b26a5e", ...}}}}

So the undertone is DERIVED here, by a written rule, and every result says so ("worked out from
your skin colour"). The rule, on the colour converted to CIELAB (D65):

    hue angle h = atan2(b*, a*) in degrees: how yellow (higher) or pink (lower) the colour sits
    olive        a* < 8 and h >= 68           (little red, strongly yellow: the greenish cast)
    warm         h >= 64
    warm-neutral 58 <= h < 64
    neutral      52 <= h < 58
    cool-neutral 46 <= h < 52
    cool         h < 46

    depth from L*: fair >= 75, light 65-75, medium 55-65, tan 45-55, deep < 45

The thresholds are a house rule, versioned with RULE_VERSION, not a measurement. The family for
shade matching lists the primary undertone first and the neutral neighbour second.

With no colour at all (no tone scan, or an unreadable one) the shopping flow still answers: it
uses the quiz's undertone if one was given, labelled "from your answers", and otherwise neutral
shades, labelled as a middle-of-range default.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

RULE_VERSION = "undertone-1.0"

FAMILIES = {
    "warm": ["warm", "neutral"],
    "warm-neutral": ["warm", "neutral"],
    "neutral": ["neutral", "warm", "cool"],
    "cool-neutral": ["cool", "neutral"],
    "cool": ["cool", "neutral"],
    "olive": ["olive", "neutral"],
}
DEPTHS = ("fair", "light", "medium", "tan", "deep")

FROM_FACE = "From your face (YouCam)"
FROM_ANSWERS = "from your answers"
DEFAULT_LABEL = "not measured: neutral shades, the middle of the range"
DERIVED_NOTE = ("YouCam returns your skin colour; the undertone is worked out from that colour by "
                "rule undertone-1.0.")

_HEX = re.compile(r"^#?([0-9a-fA-F]{6})$")


def hex_to_lab(hex_: str) -> tuple[float, float, float]:
    m = _HEX.match(hex_.strip())
    if not m:
        raise ValueError(f"Not a #rrggbb colour: {hex_!r}")
    v = m.group(1)
    rgb = [int(v[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    r, g, b = lin
    x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
    y = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 1.0
    z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883

    def f(t: float) -> float:
        return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116

    fx, fy, fz = f(x), f(y), f(z)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def classify(hex_: str) -> tuple[str, str, dict]:
    L, a, b = hex_to_lab(hex_)
    h = math.degrees(math.atan2(b, a))
    if a < 8 and h >= 68:
        tone = "olive"
    elif h >= 64:
        tone = "warm"
    elif h >= 58:
        tone = "warm-neutral"
    elif h >= 52:
        tone = "neutral"
    elif h >= 46:
        tone = "cool-neutral"
    else:
        tone = "cool"
    depth = ("fair" if L >= 75 else "light" if L >= 65 else "medium" if L >= 55
             else "tan" if L >= 45 else "deep")
    return tone, depth, {"L": round(L, 1), "a": round(a, 1), "b": round(b, 1), "hue": round(h, 1)}


def skin_color(payload) -> str | None:
    """data.results.color.skin_color, tolerant of the envelope being present or not."""
    node = payload
    for k in ("data", "results"):
        if isinstance(node, dict) and k in node:
            node = node[k]
    color = node.get("color") if isinstance(node, dict) else None
    v = (color or {}).get("skin_color") if isinstance(color, dict) else None
    if isinstance(v, str) and _HEX.match(v.strip()):
        return v.strip() if v.strip().startswith("#") else f"#{v.strip()}"
    return None


@dataclass
class Undertone:
    tone: str                  # warm | warm-neutral | neutral | cool-neutral | cool | olive
    depth: str                 # fair | light | medium | tan | deep
    family: list[str]          # undertone families to match shades against, in order
    source: str                # face | answers | default
    label: str
    skin_color: str | None = None
    lab: dict = field(default_factory=dict)
    note: str = ""
    rule_version: str = RULE_VERSION

    def line(self) -> str:
        return f"Undertone: {self.tone}"

    def to_dict(self) -> dict:
        return {"tone": self.tone, "depth": self.depth, "family": list(self.family),
                "source": self.source, "label": self.label, "skin_color": self.skin_color,
                "lab": dict(self.lab), "note": self.note, "line": self.line(),
                "rule_version": self.rule_version}


def from_payload(payload, answers: dict | None = None) -> Undertone:
    """Measured when the tone payload has a colour; otherwise the answers; otherwise the default."""
    hex_ = skin_color(payload) if payload is not None else None
    if hex_:
        tone, depth, lab = classify(hex_)
        return Undertone(tone, depth, FAMILIES[tone], "face", FROM_FACE, hex_, lab, DERIVED_NOTE)
    answers = answers or {}
    tone = answers.get("undertone")
    depth = answers.get("depth") if answers.get("depth") in DEPTHS else "medium"
    if tone in FAMILIES:
        return Undertone(tone, depth, FAMILIES[tone], "answers", FROM_ANSWERS)
    return Undertone("neutral", depth, FAMILIES["neutral"], "default", DEFAULT_LABEL)


def match_shade(shades: list[dict], ut: Undertone) -> dict | None:
    """The product's shade at your depth in your family, primary undertone first. None if the
    range has nothing at your depth in your family (the basket then says so and skips it)."""
    at_depth = [s for s in shades or [] if s.get("depth") == ut.depth]
    for fam in ut.family:
        hit = next((s for s in at_depth if s.get("undertone") == fam), None)
        if hit:
            return hit
    return None
