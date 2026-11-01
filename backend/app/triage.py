"""Breakout triage: my skin just broke out, what changed?

docs/STRATEGY.md section 4, Moment 2. The order of the screen is the order of this module, and
it is not negotiable:

1. Symptoms first. Itching, burning or swelling hands straight over to the existing stop card and
   dermatologist brief (app/evidence.py STOP_SYMPTOMS). It outranks every score and every ranking
   below it, and when it fires the next step is the stop card's, not ours.
2. What changed 2-8 weeks ago. Breakouts from a product show up with a lag, so the window is the
   ranking, not the order you remember things in. Leave-on products in the window rank above
   wash-off ones. A product used 8 weeks or more without trouble ranks lowest, with the reason
   printed, and is NEVER excluded: "you've used it a long time" is a reason to look elsewhere
   first, not proof of innocence.
3. Could it be purging? Only if the candidate lists a purge-capable ingredient
   (app/families.json). No turnover ingredient, no purge, however convenient that would be.
   Purge-consistent also needs your usual spots and settling within about 6 weeks. Spots in a new
   area are breakout-consistent, not purge-consistent.
4. Where. Per-zone acne share is read from YouCam masks only where there are real mask fixtures to
   read; no image is ever opened here, only numbers passed in. With no mask numbers we use the
   zones the user tapped, and we say which of the two we used.
5. One next step: pause ONE leave-on product, hold everything else exactly as it is, check in on
   day 14. That is a trial, so it opens through the existing trial code.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from . import evidence as E
from . import families as FAM
from .decision import Product
from .outcomes import FACE_ZONES, weeks_between

RULE_VERSION = "triage-1.0"

# The lag window a product-driven breakout is expected in (STRATEGY section 2, Lab Muffin).
WINDOW_WEEKS = (2, 8)
# At or past this many weeks of trouble-free use, a product ranks lowest, with the reason shown.
LONG_USE_WEEKS = 8
# Purge-consistent means it settles within about this long (same constant as patterns.py).
PURGE_SETTLE_WEEKS = 6

# Rank tiers, lowest number ranks highest. Every candidate gets one; none is ever dropped.
TIER_IN_WINDOW_LEAVE_ON = 0
TIER_IN_WINDOW_WASH_OFF = 1
TIER_TOO_RECENT_LEAVE_ON = 2
TIER_TOO_RECENT_WASH_OFF = 3
TIER_LONG_USE = 4
TIER_UNKNOWN_START = 5

TIER_REASON = {
    TIER_IN_WINDOW_LEAVE_ON: "Started {weeks} weeks ago and stays on your skin. That is inside the "
                             "2–8 week window a product-driven breakout usually shows up in.",
    TIER_IN_WINDOW_WASH_OFF: "Started {weeks} weeks ago, inside the 2–8 week window, but it is "
                             "washed off, so it has less contact time than a leave-on product.",
    TIER_TOO_RECENT_LEAVE_ON: "Only started {weeks} week(s) ago. That is earlier than the usual "
                              "2–8 week lag, so it ranks below the products in the window.",
    TIER_TOO_RECENT_WASH_OFF: "Only started {weeks} week(s) ago and is washed off, so it ranks below "
                              "the leave-on products.",
    TIER_LONG_USE: "You have used this for {weeks} weeks without this problem, so it ranks lowest. "
                   "That is a reason to look at newer things first, not a clean bill: a product you "
                   "have used for a long time can still be involved.",
    TIER_UNKNOWN_START: "No start date recorded, so it can't be placed in the 2–8 week window. "
                        "It stays on the list rather than being guessed about.",
}

ZONE_SOURCE = {
    "masks": "Per-zone shares read from the YouCam acne masks for these scans.",
    "tapped": "Based on the zones you tapped. No per-zone mask numbers were available for this scan.",
    "none": "No zones recorded yet.",
}


@dataclass
class Candidate:
    product_id: str
    product_name: str
    leave_on: bool
    started_on: date | None
    weeks_used: int | None
    tier: int
    reason: str
    in_window: bool
    purge_capable: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"product_id": self.product_id, "product_name": self.product_name,
                "leave_on": self.leave_on,
                "started_on": self.started_on.isoformat() if self.started_on else None,
                "weeks_used": self.weeks_used, "tier": self.tier, "reason": self.reason,
                "in_window": self.in_window,
                "purge_capable": list(self.purge_capable)}


@dataclass
class PurgeRead:
    """Step 3. Never a verdict on its own; always says which of the three conditions held."""
    possible: bool
    consistent: bool
    ingredient: str | None
    label_line: str | None
    strength: str | None
    conditions: dict = field(default_factory=dict)
    line: str = ""

    def to_dict(self) -> dict:
        return {"possible": self.possible, "consistent": self.consistent,
                "ingredient": self.ingredient, "label_line": self.label_line,
                "strength": self.strength, "conditions": self.conditions, "line": self.line}


@dataclass
class ZoneRead:
    source: str                      # "masks" | "tapped" | "none"
    zones: list[str]
    usual_spots: bool | None
    shares: dict[str, float] = field(default_factory=dict)
    baseline_shares: dict[str, float] = field(default_factory=dict)
    line: str = ""

    def to_dict(self) -> dict:
        return {"source": self.source, "source_note": ZONE_SOURCE[self.source],
                "zones": list(self.zones), "usual_spots": self.usual_spots,
                "shares": dict(self.shares), "baseline_shares": dict(self.baseline_shares),
                "line": self.line}


@dataclass
class Triage:
    stop: bool
    stop_symptoms: list[str]
    headline: str
    candidates: list[Candidate]
    purge: PurgeRead
    zones: ZoneRead
    next_step: str
    next_action: dict
    inputs: dict = field(default_factory=dict)
    rule_version: str = RULE_VERSION
    families_version: str = FAM.FAMILIES_VERSION

    def lead(self) -> Candidate | None:
        return self.candidates[0] if self.candidates else None

    def to_dict(self) -> dict:
        return {"stop": self.stop, "stop_symptoms": list(self.stop_symptoms),
                "headline": self.headline,
                "candidates": [c.to_dict() for c in self.candidates],
                "purge": self.purge.to_dict(), "zones": self.zones.to_dict(),
                "next_step": self.next_step, "next_action": self.next_action,
                "inputs": self.inputs, "rule_version": self.rule_version,
                "families_version": self.families_version}


def _tier(leave_on: bool, weeks: int | None) -> int:
    if weeks is None:
        return TIER_UNKNOWN_START
    lo, hi = WINDOW_WEEKS
    if weeks >= LONG_USE_WEEKS:
        return TIER_LONG_USE
    if lo <= weeks <= hi:
        return TIER_IN_WINDOW_LEAVE_ON if leave_on else TIER_IN_WINDOW_WASH_OFF
    return TIER_TOO_RECENT_LEAVE_ON if leave_on else TIER_TOO_RECENT_WASH_OFF


def rank(using: list[dict], catalog: dict[str, Product], today: date | None = None) -> list[Candidate]:
    """Step 2. `using` is [{"product_id", "started_on"}]: what is on the skin and since when.

    Nothing is excluded. The order is the ranking, and every row carries the reason it sits there.
    """
    today = today or datetime.now(timezone.utc).date()
    out: list[Candidate] = []
    for item in using:
        p = catalog.get(item.get("product_id"))
        if p is None:
            continue
        start = item.get("started_on")
        start = None if not start else (start if isinstance(start, date) else date.fromisoformat(str(start)[:10]))
        weeks = weeks_between(start, None, today)
        tier = _tier(p.leave_on, weeks)
        lo, hi = WINDOW_WEEKS
        out.append(Candidate(
            product_id=p.id, product_name=p.name, leave_on=p.leave_on, started_on=start,
            weeks_used=weeks, tier=tier,
            reason=TIER_REASON[tier].format(weeks=weeks),
            in_window=weeks is not None and lo <= weeks <= hi and weeks < LONG_USE_WEEKS,
            purge_capable=FAM.purge_capable_in(p.inci)))
    # Inside a tier: the most recently started first, then by name so the order is stable.
    out.sort(key=lambda c: (c.tier, -(c.weeks_used if c.weeks_used is not None else 999), c.product_name))
    return out


def read_purge(lead: Candidate | None, usual_spots: bool | None,
               settled_while_using: bool | None = None,
               settled_week: int | None = None) -> PurgeRead:
    """Step 3. Purging needs a purge-capable ingredient first, then usual spots, then settling."""
    if lead is None:
        return PurgeRead(False, False, None, None, None,
                         {"purge_capable_ingredient": False, "usual_spots": usual_spots,
                          "settled_within_weeks": None},
                         "No candidate to read, so purging isn't on the table.")
    capable = lead.purge_capable
    conditions = {
        "purge_capable_ingredient": bool(capable),
        "usual_spots": usual_spots,
        "settled_within_weeks": (settled_week if settled_while_using else None),
    }
    if not capable:
        return PurgeRead(
            False, False, None, None, None, conditions,
            f"Not a purge. {lead.product_name} lists no ingredient that speeds up cell turnover, and "
            "purging only happens with those. This reads as a breakout, not a purge.")
    top = capable[0]
    settled_ok = bool(settled_while_using) and (settled_week is None or settled_week <= PURGE_SETTLE_WEEKS)
    if usual_spots is False:
        return PurgeRead(
            True, False, top["ingredient"], top["label_line"], top["strength"], conditions,
            f"{lead.product_name} does list {top['label_line']}, which can purge. But these spots are in "
            "a new area for you, and purging shows up in your usual spots. That points to a breakout.")
    if usual_spots is None:
        return PurgeRead(
            True, False, top["ingredient"], top["label_line"], top["strength"], conditions,
            f"{lead.product_name} lists {top['label_line']}, which can purge. Whether this is purging "
            "depends on something only you know: are these your usual spots?")
    if not settled_ok:
        return PurgeRead(
            True, False, top["ingredient"], top["label_line"], top["strength"], conditions,
            f"{lead.product_name} lists {top['label_line']} and these are your usual spots, so purging is "
            f"possible. It hasn't settled yet though. Purging usually settles within about "
            f"{PURGE_SETTLE_WEEKS} weeks; past that it reads as a breakout.")
    return PurgeRead(
        True, True, top["ingredient"], top["label_line"], top["strength"], conditions,
        f"Consistent with purging: {lead.product_name} lists {top['label_line']}, the spots are in your "
        f"usual places, and it settled within {PURGE_SETTLE_WEEKS} weeks. {top['note']}")


def read_zones(zones: list[str], usual_spots: bool | None,
               shares: dict[str, float] | None = None,
               baseline_shares: dict[str, float] | None = None) -> ZoneRead:
    """Step 4. Numbers only. No image file is opened anywhere in this module."""
    zones = [z for z in (zones or []) if z in FACE_ZONES]
    shares = {k: v for k, v in (shares or {}).items() if k in FACE_ZONES}
    baseline_shares = {k: v for k, v in (baseline_shares or {}).items() if k in FACE_ZONES}
    source = "masks" if shares else ("tapped" if zones else "none")
    r = ZoneRead(source, zones, usual_spots, shares, baseline_shares)
    if source == "masks":
        worst = max(shares, key=lambda k: shares[k])
        base = baseline_shares.get(worst)
        where = f"Most of the marked area is on your {worst} ({shares[worst]:.0%} of it)."
        if base is not None:
            moved = shares[worst] - base
            where += (f" At your baseline that zone held {base:.0%}, so it is up {moved:.0%}."
                      if moved > 0 else
                      f" At your baseline that zone held {base:.0%}, so it hasn't gone up.")
        r.line = where
    elif source == "tapped":
        where = ", ".join(zones)
        usual = ("" if usual_spots is None else
                 (" Those are your usual spots, which is where purging shows up."
                  if usual_spots else
                  " That is a new area for you, which points away from purging."))
        r.line = f"You tapped: {where}.{usual}"
    else:
        r.line = "No zones recorded, so there is nothing to compare by area."
    return r


def assess(symptoms: list[str], zones: list[str], usual_spots: bool | None,
           using: list[dict], catalog: dict[str, Product],
           settled_while_using: bool | None = None, settled_week: int | None = None,
           shares: dict[str, float] | None = None, baseline_shares: dict[str, float] | None = None,
           today: date | None = None) -> Triage:
    """The whole of Moment 2, in the order the screen shows it."""
    reported = [s.lower().strip() for s in (symptoms or [])]
    stop = [s for s in reported if s in E.STOP_SYMPTOMS]

    candidates = rank(using, catalog, today)
    lead = candidates[0] if candidates else None
    purge = read_purge(lead, usual_spots, settled_while_using, settled_week)
    zone_read = read_zones(zones, usual_spots, shares, baseline_shares)

    if stop:
        # Step 1 wins outright. We do not rank, pause or schedule anything over a reaction.
        headline = ("Stop first: you reported " + ", ".join(stop) +
                    ". A reaction you can feel outranks any ranking below.")
        next_step = ("Pause the newest leave-on product now and open your visit brief. "
                     "If it is severe or spreading, see a clinician.")
        next_action = {"kind": "stop_card", "brief": True}
    elif lead is None:
        headline = ("Nothing recorded as in use, so there is nothing to rank. Add what you are using "
                    "and when you started it.")
        next_step = "Add the products you are using, with the date you started each one."
        next_action = {"kind": "add_products"}
    else:
        kind = "purge" if purge.consistent else "breakout"
        headline = (f"{lead.product_name} is the top lead: {lead.reason} "
                    f"{'This reads as purging rather than a breakout.' if kind == 'purge' else ''}").strip()
        pause = lead if lead.leave_on else next((c for c in candidates if c.leave_on), lead)
        hold = [c for c in candidates if c.product_id != pause.product_id]
        rest = (", including " + " and ".join(c.product_name for c in hold[-2:])) if hold else ""
        if purge.consistent:
            # Pausing something that is settling would throw away the only reading we could get.
            next_step = (f"Keep using {pause.product_name} and change nothing else{rest}, then check in "
                         f"on day 14. If it is purging it should keep settling; if it doesn't, that is "
                         f"your answer.")
            next_action = {"kind": "open_trial", "keep_product_id": pause.product_id,
                           "pause_product_id": None,
                           "hold_fixed": [c.product_id for c in hold], "checkpoint_days": 14}
        else:
            next_step = (f"Pause {pause.product_name} only. Keep everything else exactly as it is"
                         f"{rest}, and check in on day 14. Changing one thing is the only way the next "
                         f"scan can say anything.")
            next_action = {"kind": "open_trial", "pause_product_id": pause.product_id,
                           "keep_product_id": None,
                           "hold_fixed": [c.product_id for c in hold], "checkpoint_days": 14}

    return Triage(
        stop=bool(stop), stop_symptoms=stop, headline=headline, candidates=candidates,
        purge=purge, zones=zone_read, next_step=next_step, next_action=next_action,
        inputs={"symptoms": reported, "zones": list(zones or []), "usual_spots": usual_spots,
                "using": [{"product_id": u.get("product_id"),
                           "started_on": str(u.get("started_on") or "") or None} for u in using],
                "settled_while_using": settled_while_using, "settled_week": settled_week,
                "shares": dict(shares or {}), "baseline_shares": dict(baseline_shares or {}),
                "window_weeks": list(WINDOW_WEEKS), "long_use_weeks": LONG_USE_WEEKS,
                "rule_versions": {"triage": RULE_VERSION, "families": FAM.FAMILIES_VERSION,
                                  "evidence": E.RULE_VERSION}},
    )
