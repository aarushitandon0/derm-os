"""Evidence engine: is a change in skin scores real, and can it be attributed?

Three ideas, each testable:
  1. Personal noise floor  - a baseline is several scans; each concern gets a
     [min, max] range instead of a single number.
  2. Comparability gate    - two capture sets are only compared when their
     fingerprints match within tolerance.
  3. Verdict levels        - applied top-down, first match wins; symptoms
     always outrank scores; several simultaneous changes block attribution.

All scores are YouCam raw_score (1-100, higher = healthier-looking skin).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from statistics import mean

from .fingerprint import Fingerprint

RULE_VERSION = "evidence-1.0"

# Starting tolerances. TUNE these from Experiment 1/2 results (scripts/run_experiments.py).
TOLERANCES = {
    "luminance": 0.12,        # absolute difference on a 0..1 scale
    "red_blue_ratio": 0.15,   # relative difference (warm lamp vs daylight)
    "face_ratio": 0.10,       # absolute difference in face width / frame width
    "angle": 8.0,             # degrees, yaw/pitch/roll each
    "hour": 6,                # hours apart (time-of-day light)
}
MIN_BAND = 0.0  # extra half-width added to every range; raise after Experiment 1 if needed.

STOP_SYMPTOMS = {"burning", "stinging", "swelling", "itching", "hives", "blistering",
                 "rash", "peeling_painful", "oozing"}


class Verdict(str, Enum):
    STOP_REACTION = "stop_reaction"
    NO_BASELINE = "cant_tell_no_baseline"
    NOT_COMPARABLE = "cant_tell_not_comparable"
    SEVERAL_CHANGES = "cant_tell_several_changes"
    NO_CHANGE = "no_detectable_change"
    MOVED = "moved_beyond_noise"


VERDICT_TEXT = {
    Verdict.STOP_REACTION: "Stop: you reported a reaction. Pause the new product and see the visit brief.",
    Verdict.NO_BASELINE: "Can't tell yet: there isn't a baseline of at least 2 matched scans to compare with.",
    Verdict.NOT_COMPARABLE: "Can't tell: these photos were taken under different conditions. Retake to match your baseline.",
    Verdict.SEVERAL_CHANGES: "Can't tell which product: more than one new leave-on product started during this trial.",
    Verdict.NO_CHANGE: "No detectable change yet: your new scores sit inside your own normal scan-to-scan range.",
    Verdict.MOVED: "Changed beyond your normal range during this trial.",
}

# The strongest result names what moved and adds this caveat. Never a cause.
MOVED_CAVEAT = "This alone can't show the product was the reason: seasons, sleep and cycles move skin too."

# How a move reads for each concern. YouCam raw scores are higher for healthier-looking skin, so
# "better" means less redness or fewer breakouts, but more moisture or radiance.
MOVE_WORDS = {
    "redness": ("Redness dropped", "Redness rose"),
    "acne": ("Breakouts dropped", "Breakouts rose"),
    "pore": ("Pores looked smaller", "Pores looked larger"),
    "texture": ("Texture looked smoother", "Texture looked rougher"),
    "oiliness": ("Oiliness dropped", "Oiliness rose"),
    "moisture": ("Moisture rose", "Moisture dropped"),
    "radiance": ("Radiance rose", "Radiance dropped"),
    "age_spot": ("Spots looked lighter", "Spots looked darker"),
}


def moved_sentence(concern: str, direction: str) -> str:
    better, worse = MOVE_WORDS.get(concern, (f"The {concern.replace('_', ' ')} score rose",
                                             f"The {concern.replace('_', ' ')} score dropped"))
    return f"{better if direction == 'better' else worse} beyond your usual variation during this trial."


# The rebuy line: the shopping decision, mapped strictly from the verdict (never from scores alone).
REBUY = {
    "supports": "The evidence supports rebuying, if you like using it.",
    "finish": "Finish the trial before you rebuy.",
    "cant_tell": "Can't tell yet, so this isn't a reason to rebuy.",
    "stop": "Don't rebuy. If it persists, take the visit brief to a clinician.",
    "moved_worse": "Scores moved the wrong way during this trial, so this isn't a reason to rebuy.",
}


def rebuy_line(verdict: "Verdict", findings: list["ConcernFinding"]) -> str:
    if verdict == Verdict.STOP_REACTION:
        return REBUY["stop"]
    if verdict == Verdict.NO_CHANGE:
        return REBUY["finish"]
    if verdict == Verdict.MOVED:
        moved = [f for f in findings if f.beyond_noise]
        return REBUY["supports"] if moved and all(f.direction == "better" for f in moved) else REBUY["moved_worse"]
    return REBUY["cant_tell"]   # no baseline, not comparable, several changes


@dataclass
class Capture:
    scores: dict[str, float]          # concern -> raw_score
    fingerprint: Fingerprint
    mode: str = "sd"                  # sd | hd
    actions: tuple[str, ...] = ()


@dataclass
class Range:
    lo: float
    hi: float
    n: int

    @property
    def mid(self) -> float:
        return (self.lo + self.hi) / 2

    @property
    def width(self) -> float:
        return self.hi - self.lo

    def padded(self, band: float) -> "Range":
        return Range(self.lo - band, self.hi + band, self.n)

    def to_dict(self) -> dict:
        return {"lo": round(self.lo, 2), "hi": round(self.hi, 2), "n": self.n, "width": round(self.width, 2)}


def ranges(captures: list[Capture]) -> dict[str, Range]:
    out: dict[str, Range] = {}
    concerns = set().union(*(c.scores.keys() for c in captures)) if captures else set()
    for k in concerns:
        vals = [c.scores[k] for c in captures if k in c.scores and c.scores[k] is not None]
        if vals:
            out[k] = Range(min(vals), max(vals), len(vals))
    return out


@dataclass
class Comparability:
    comparable: bool
    reasons: list[str] = field(default_factory=list)   # human-readable mismatches
    fixes: list[str] = field(default_factory=list)     # what to do on the retake
    # Structured view of the same result, for the capture-quality screen:
    # which fields had data on both sides, and each mismatch with its own fix.
    checked: list[str] = field(default_factory=list)
    failed: list[dict] = field(default_factory=list)   # {"field", "reason", "fix"}
    # Fields with data on both sides that still can't be compared fairly. Neutral: never fail the pair.
    not_compared: list[dict] = field(default_factory=list)   # {"field", "reason"}

    def to_dict(self) -> dict:
        return {"comparable": self.comparable, "reasons": self.reasons, "fixes": self.fixes,
                "checked": self.checked, "failed": self.failed, "not_compared": self.not_compared}


def _avg(vals):
    vals = [v for v in vals if v is not None]
    return mean(vals) if vals else None


def _device_source(f: Fingerprint) -> str | None:
    """Where the device label came from. Fingerprints saved before `device_source` existed
    only ever took the device from EXIF, so a label with no source is an EXIF label."""
    if not f.device:
        return None
    return f.device_source or "exif"


def compare_conditions(base: list[Capture], follow: list[Capture], tol: dict = TOLERANCES) -> Comparability:
    reasons, fixes, checked, failed, not_compared = [], [], [], [], []

    def miss(field_name: str, reason: str, fix: str) -> None:
        reasons.append(reason)
        fixes.append(fix)
        failed.append({"field": field_name, "reason": reason, "fix": fix})

    checked.append("mode")
    if {c.mode for c in base} != {c.mode for c in follow} or len({c.mode for c in base + follow}) > 1:
        miss("mode", "Scans used different analysis modes (SD vs HD).", "Use the same scan mode as your baseline.")
    b_act = {tuple(sorted(c.actions)) for c in base}
    f_act = {tuple(sorted(c.actions)) for c in follow}
    if b_act and f_act and b_act != f_act:
        # Different concern sets are fine as long as the compared concern was in both; noted only.
        pass

    bf = [c.fingerprint for c in base]
    ff = [c.fingerprint for c in follow]

    bl, fl = _avg([f.luminance for f in bf]), _avg([f.luminance for f in ff])
    brb, frb = _avg([f.red_blue_ratio for f in bf]), _avg([f.red_blue_ratio for f in ff])
    if (bl is not None and fl is not None) or (brb and frb):
        checked.append("lighting")
    if bl is not None and fl is not None and abs(bl - fl) > tol["luminance"]:
        miss("lighting", f"Brightness differs ({bl:.2f} vs {fl:.2f}).",
             "Stand in the same spot and light as your baseline." if fl < bl else
             "The light is much brighter than your baseline; move out of direct light.")

    if brb and frb and abs(brb - frb) / brb > tol["red_blue_ratio"]:
        warmer = frb > brb
        miss("lighting", f"Light colour differs: this light is {'warmer' if warmer else 'cooler'} than your baseline.",
             "Use the same light source as your baseline (e.g. daylight from a window, not a warm lamp).")

    bfr, ffr = _avg([f.face_ratio for f in bf]), _avg([f.face_ratio for f in ff])
    if bfr is not None and ffr is not None:
        checked.append("face_size")
        if abs(bfr - ffr) > tol["face_ratio"]:
            miss("face_size", "Your face fills a different share of the frame.",
                 "Hold the phone at the same distance: match the face outline.")

    pose_checked = False
    for axis in ("yaw", "pitch", "roll"):
        ba, fa = _avg([getattr(f, axis) for f in bf]), _avg([getattr(f, axis) for f in ff])
        if ba is not None and fa is not None:
            pose_checked = True
            if abs(ba - fa) > tol["angle"]:
                miss("head_pose", f"Head angle differs ({axis}).", "Look straight into the camera.")
                break
    if pose_checked:
        checked.append("head_pose")

    bdev = {f.device for f in bf if f.device}
    fdev = {f.device for f in ff if f.device}
    if bdev and fdev:
        # An EXIF label ("Acme Phone 7") and a live-camera label ("Front Camera") name the same
        # phone differently, so labels are compared only when every one came from the same source.
        sources = {_device_source(f) for f in bf + ff if f.device}
        if len(sources) == 1:
            checked.append("device")
            if bdev.isdisjoint(fdev):
                miss("device", "A different camera was used.", "Use the same phone as your baseline.")
        else:
            not_compared.append({"field": "device",
                                 "reason": "Camera labels came from different sources (photo file vs live camera), "
                                           "so they can't be compared."})

    bh, fh = _avg([f.captured_hour for f in bf]), _avg([f.captured_hour for f in ff])
    if bh is not None and fh is not None:
        checked.append("time_of_day")
        gap = abs(bh - fh)
        gap = min(gap, 24 - gap)
        if gap > tol["hour"]:
            miss("time_of_day", "Taken at a very different time of day.",
                 "Scan at roughly the same time of day as your baseline.")

    return Comparability(not reasons, reasons, list(dict.fromkeys(fixes)), checked, failed, not_compared)


@dataclass
class TrialContext:
    new_leave_on_products: int = 1     # new leave-on products started since baseline
    symptoms: list[str] = field(default_factory=list)


@dataclass
class ConcernFinding:
    concern: str
    baseline: Range | None
    followup: Range | None
    direction: str | None   # "better" | "worse" | None
    delta_mid: float | None
    beyond_noise: bool

    def to_dict(self) -> dict:
        return {
            "concern": self.concern,
            "baseline": self.baseline.to_dict() if self.baseline else None,
            "followup": self.followup.to_dict() if self.followup else None,
            "direction": self.direction,
            "delta_mid": None if self.delta_mid is None else round(self.delta_mid, 2),
            "beyond_noise": self.beyond_noise,
        }


@dataclass
class EvidenceReport:
    verdict: Verdict
    message: str
    findings: list[ConcernFinding]
    comparability: Comparability | None
    symptoms: list[str]
    rule_version: str = RULE_VERSION

    @property
    def rebuy(self) -> str:
        return rebuy_line(self.verdict, self.findings)

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict.value,
            "message": self.message,
            "rebuy": self.rebuy,
            "findings": [f.to_dict() for f in self.findings],
            "comparability": None if self.comparability is None else self.comparability.to_dict(),
            "symptoms": self.symptoms,
            "rule_version": self.rule_version,
        }


def _findings(base: list[Capture], follow: list[Capture], concerns: list[str] | None, band: float):
    br, fr = ranges(base), ranges(follow)
    keys = concerns or sorted(set(br) & set(fr))
    out = []
    for k in keys:
        b, f = br.get(k), fr.get(k)
        if not b or not f:
            out.append(ConcernFinding(k, b, f, None, None, False))
            continue
        bp, fp = b.padded(band), f.padded(band)
        overlap = not (fp.lo > bp.hi or fp.hi < bp.lo)
        delta = f.mid - b.mid
        direction = None if overlap else ("better" if delta > 0 else "worse")
        out.append(ConcernFinding(k, b, f, direction, delta, not overlap))
    return out


def evaluate(base: list[Capture], follow: list[Capture], ctx: TrialContext,
             concerns: list[str] | None = None, band: float = MIN_BAND) -> EvidenceReport:
    """Apply the verdict table top-down. First matching rule wins."""
    reported = [s.lower().strip() for s in ctx.symptoms]
    stop = [s for s in reported if s in STOP_SYMPTOMS]

    # Findings are computed whenever possible so the UI can still show the bars,
    # but the verdict text never overrides a higher-priority rule.
    findings = _findings(base, follow, concerns, band) if base and follow else []
    comp = compare_conditions(base, follow) if base and follow else None

    if stop:
        v = Verdict.STOP_REACTION
    elif len(base) < 2 or len(follow) < 2:
        v = Verdict.NO_BASELINE
    elif comp is not None and not comp.comparable:
        v = Verdict.NOT_COMPARABLE
    elif ctx.new_leave_on_products > 1:
        v = Verdict.SEVERAL_CHANGES
    elif any(f.beyond_noise for f in findings):
        v = Verdict.MOVED
    else:
        v = Verdict.NO_CHANGE

    msg = VERDICT_TEXT[v]
    if v == Verdict.MOVED:
        moved = [f for f in findings if f.beyond_noise]
        msg = " ".join(moved_sentence(f.concern, f.direction) for f in moved) + " " + MOVED_CAVEAT
    if reported and v != Verdict.STOP_REACTION:
        msg += f" You also logged: {', '.join(reported)}. Keep an eye on it."
    return EvidenceReport(v, msg, findings, comp, reported)


def noise_summary(captures: list[Capture]) -> dict[str, dict]:
    """Experiment 1 helper: per-concern spread across repeat scans of an unchanged face."""
    out = {}
    for k, r in sorted(ranges(captures).items()):
        vals = [c.scores[k] for c in captures if k in c.scores]
        out[k] = {"min": round(r.lo, 2), "max": round(r.hi, 2), "range": round(r.width, 2),
                  "mean": round(mean(vals), 2), "n": r.n}
    return out
