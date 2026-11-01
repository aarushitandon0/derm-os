"""Guided-demo scenes: prepared trials built from recorded fixture scores.

A scene writes only what the app's own endpoints would write: the shelf, history records, a
trial, its scans and its check-in logs. It never sets a verdict. The evidence endpoint then runs
the real comparability gate and verdict table on those rows, exactly as for any other trial.
Every scan is stored as source="replay" (the UI labels it "Prepared demo data"), and hand-made
fixtures keep synthetic=True.

Capture conditions: a fixture made from a real photo (scripts/make_fixtures.py) carries its own
measured fingerprint, which is used as is. Hand-made fixtures have none, so they get the prepared
conditions below: window light for every set except "lamp", which is the same scene under a warm
lamp (light colour and brightness are the only differences).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable

from . import decision as D
from . import demo
from . import outcomes as OC

# Prepared capture conditions for fixtures without a measured fingerprint (normalised SD capture).
WINDOW_FP = {"width": 480, "height": 640, "luminance": 0.55, "red_blue_ratio": 1.19, "device": "Demo phone",
             "captured_hour": 9, "face_ratio": 0.75, "face_px": 360.0, "yaw": 0.0, "pitch": 0.0, "roll": 0.0,
             "device_source": "exif", "hour_source": "exif"}
LAMP_FP = {**WINDOW_FP, "luminance": 0.47, "red_blue_ratio": 1.62}
# Small shot-to-shot differences, well inside the gate's tolerances.
JITTER = [(0.0, 0.0, 0.0), (0.012, -0.010, 1.5), (-0.009, 0.012, -1.0), (0.006, 0.008, 0.5), (-0.004, -0.006, -1.5)]

RIYA_SHELF = ["cl-01", "sr-01", "mo-01", "sp-01"]
RIYA_TRIAL_SHELF = ["cl-01", "sr-01", "mo-03", "sp-01"]   # the water gel replaced the barrier cream
RIYA_HISTORY = [
    {"id": "demo-riya-h1", "type": "suspected_reaction", "product_id": "mo-02", "ingredient": None,
     "note": "Itchy cheeks a week after starting it, last winter."},
    {"id": "demo-riya-h2", "type": "avoid", "product_id": None, "ingredient": "fragrance",
     "note": "My choice after the moisturiser reaction."},
]

# ------------------------------------------------------------------ outcomes (what happened)
# Riya's story from docs/STRATEGY.md section 2, as rows the app's own endpoints would write.
# A scene writes rows and nothing else: every suspect, lead, purge offer, verdict and next step on
# screen is worked out by the real engines from these rows.
#
# `weeks` is how long she used it. Dates are filled in relative to now when the scene is built, so
# the 4-week rule and the 2-8 week window stay true however long after writing this it is run.
RIYA_OUTCOMES = [
    # The two that itched. They share one drying alcohol, which is on neither suited product.
    {"product_id": "sr-02", "outcome": "irritation", "weeks": 2, "started_weeks_ago": 60,
     "note": "Itched within a few days of starting it."},
    {"product_id": "tn-03", "outcome": "irritation", "weeks": 3, "started_weeks_ago": 40,
     "note": "Itched again, the same way."},
    # The breakout that settled while she kept using it, in her usual spot: a purge offer.
    {"product_id": "sr-05", "outcome": "breakout", "weeks": 8, "started_weeks_ago": 30,
     "zones": ["chin"], "usual_spots": True, "settled_while_using": True, "settled_week": 5,
     "note": "Spots on the chin from about week 2, settled by week 5 while still using it."},
    # The two that suited her, both over 4 weeks, so they count and they clear ingredients.
    {"product_id": "es-01", "outcome": "suited", "weeks": 12, "started_weeks_ago": 12,
     "note": "Still using it. Nothing has gone wrong."},
    {"product_id": "mo-03", "outcome": "suited", "weeks": 20, "started_weeks_ago": 20,
     "note": "On the shelf since spring."},
]

# What is on her skin right now, and since when: the input to the 2-8 week window ranking.
# The sunscreen is the only thing inside the window.
RIYA_USING = [
    {"product_id": "cl-01", "started_weeks_ago": 30},
    {"product_id": "sr-01", "started_weeks_ago": 26},
    {"product_id": "mo-03", "started_weeks_ago": 20},
    {"product_id": "es-01", "started_weeks_ago": 12},
    {"product_id": "sp-01", "started_weeks_ago": 4},
]

# The breakout she is dealing with now: closed comedones on the cheeks, not her usual spots.
RIYA_BREAKOUT = {"zones": ["cheeks"], "usual_spots": False, "symptoms": [], "weeks_ago": 1}

# Riya's story told the way most people remember it: by ingredient (app/chips.py). Vitamin C
# itched; azelaic acid broke her out on the chin, her usual spot, and it settled by about week 5,
# so she has answered the purge question "yes" and the offer is waiting for her choice (never made
# for her); snail mucin suited her. Her product-level history above stays exactly as it was.
RIYA_CHIPS = [
    {"chip": "vitamin_c", "reaction": "itched"},
    {"chip": "azelaic_acid", "reaction": "broke_out", "usual_spots_settled": "yes"},
    {"chip": "snail_mucin", "reaction": "suited"},
]

# A beginner. No outcomes and no history at all, which is the whole point: the Start here path has
# to work from nothing. Her skin type comes from her answers, labelled as such, because no
# skin_type fixture exists to read one from.
BEGINNER_ANSWERS = {"midday": "shiny_tzone", "reacts": "sometimes", "breakouts": "monthly",
                    "using": "nothing"}


@dataclass
class Scans:
    persona: str
    fixture_set: str
    phase: str           # baseline | checkin
    day: int             # days after the trial started
    n: int


@dataclass
class Scene:
    persona: str
    shelf: list[str] | None        # None: leave the shared shelf alone
    history: list[dict] | None     # None: leave the shared history alone; [] clears it (beginner)
    product_id: str | None = None
    goal: str = "redness"
    held_fixed: list[str] = field(default_factory=list)
    started_days_ago: int = 0
    scans: list[Scans] = field(default_factory=list)
    logs: list[tuple[int, list[str]]] = field(default_factory=list)   # (day, symptoms) check-in logs
    # Product outcomes (app/outcomes.py). None leaves whatever is stored alone; [] clears them,
    # which is what the beginner scene needs.
    outcomes: list[dict] | None = None
    # Free-text notes the screens show, e.g. the breakout she is dealing with. Never a verdict.
    situation: dict | None = None
    # Quick history by ingredient (app/chips.py). None leaves the stored chips alone; [] clears them.
    chips: list[dict] | None = None


def _riya(started: int, scans: list[Scans], logs: list[tuple[int, list[str]]]) -> Scene:
    return Scene("riya", RIYA_TRIAL_SHELF, RIYA_HISTORY, "mo-03", "redness", ["cl-01", "sr-01", "sp-01"],
                 started, scans, logs)


_BASE = Scans("riya", "baseline", "baseline", 0, 3)
_LAMP = Scans("riya", "lamp", "checkin", 1, 2)
_DAY14 = Scans("riya", "checkin", "checkin", 14, 2)

SCENES: dict[str, Scene] = {
    # The hero flow from docs/DESIGN.md, one moment per scene.
    "riya-history": Scene("riya", RIYA_SHELF, RIYA_HISTORY),
    "riya-trial": _riya(0, [_BASE], []),
    "riya-lamp": _riya(1, [_BASE, _LAMP], [(1, [])]),
    "riya-day14": _riya(14, [_BASE, _LAMP, _DAY14], [(1, []), (14, [])]),
    "riya-stop": _riya(14, [_BASE, _LAMP, _DAY14], [(1, []), (14, ["itching"])]),
    # A second person whose comparable check-ins leave her own range.
    "meera": Scene("meera", None, None, "sr-05", "redness", ["cl-03", "mo-05", "sp-02"], 28,
                   [Scans("meera", "baseline", "baseline", 0, 3), Scans("meera", "checkin", "checkin", 28, 2)],
                   [(28, [])]),

    # ------------------------------------------------------------ the three moments
    # Moment 1. Her full story on record, plus a free scan so the store page's "From your skin"
    # has something to read. No trial: this is the moment before she buys anything.
    "riya-store": Scene("riya", RIYA_TRIAL_SHELF, RIYA_HISTORY, None, "pore", [], 0,
                        [Scans("riya", "baseline", "free", 0, 3)], [],
                        outcomes=RIYA_OUTCOMES),
    # Moment 2. The same story, plus the breakout she is dealing with right now.
    "riya-breakout": Scene("riya", RIYA_TRIAL_SHELF, RIYA_HISTORY, None, "acne", [], 0,
                           [Scans("riya", "baseline", "free", 0, 3)], [],
                           outcomes=RIYA_OUTCOMES,
                           situation={"kind": "breakout", "using": RIYA_USING, **RIYA_BREAKOUT}),
    # Moment 3, on the positive persona, with PORES as the concern that moves. Redness is never
    # the improvement concern in demo data (docs/STRATEGY.md section 5: redness sits at its
    # ceiling in the recorded data, so it could only ever get worse).
    "meera-pore": Scene("meera", None, [], "sr-05", "pore", ["cl-03", "mo-05", "sp-02"], 35,
                        [Scans("meera", "baseline", "baseline", 0, 3),
                         Scans("meera", "pore", "checkin", 35, 2)],
                        [(35, [])], outcomes=[]),
    # Strategy v2, the basket flow. Her history and shelf on record, and no scan: the face comes
    # from the basket endpoint's demo face (app/demo_faces.py), labelled "Demo data".
    "riya-basket": Scene("riya", RIYA_TRIAL_SHELF, RIYA_HISTORY, None, "pore", [], 0, [], [],
                         outcomes=RIYA_OUTCOMES, chips=RIYA_CHIPS),
    # Start here. Deliberately empty: no shelf, no history, no outcomes, no scan.
    "beginner": Scene("riya", [], [], None, "pore", [], 0, [], [], outcomes=[], chips=[],
                      situation={"kind": "beginner", "answers": BEGINNER_ANSWERS}),
}


def trial_id(name: str) -> str:
    return f"demo-{name}"


def fingerprint_for(replay: demo.Replay, fixture_set: str, i: int) -> dict:
    meta = json.loads(replay.path.read_text(encoding="utf-8")).get("meta", {})
    if meta.get("fingerprint"):
        return dict(meta["fingerprint"])
    fp = dict(LAMP_FP if fixture_set == "lamp" else WINDOW_FP)
    dl, drb, dyaw = JITTER[i % len(JITTER)]
    fp.update(luminance=round(fp["luminance"] + dl, 4), red_blue_ratio=round(fp["red_blue_ratio"] + drb, 4),
              yaw=dyaw, short_side=min(fp["width"], fp["height"]))
    return fp


def build(name: str, put: Callable[..., dict], all_: Callable[[str], list[dict]], delete: Callable[[str, str], None],
          catalog: dict[str, D.Product], now: datetime | None = None) -> dict:
    """Write the scene's rows and return {"scene", "trial_id"}. Rebuilding a scene replaces only its own rows."""
    if name not in SCENES:
        raise KeyError(name)
    sc = SCENES[name]
    now = now or datetime.now(timezone.utc)
    if sc.shelf is not None:
        put("shelf", {"product_ids": [p for p in sc.shelf if p in catalog]}, id="me")
    if sc.history == []:
        # The beginner starts from nothing: an earlier scene's records (riya's "avoid fragrance")
        # must not leak into a "nothing tried yet" basket.
        for h in all_("history"):
            delete("history", h["id"])
    for h in sc.history or []:
        put("history", dict(h))
    # The trial's exclusion check uses this persona's own records, as POST /api/trials would.
    records = [D.HistoryRecord(D.RecordType(h["type"]), h.get("product_id"), h.get("ingredient"), h.get("note", ""))
               for h in sc.history or []]
    if sc.chips is not None:
        put("chips", {"chips": [dict(c) for c in sc.chips]}, id="me")
    if sc.outcomes is not None:
        write_outcomes(sc.outcomes, put, all_, delete, catalog, now)

    tid = trial_id(name) if sc.product_id else None
    start = now - timedelta(days=sc.started_days_ago, hours=1)
    at = lambda day, minute: (start + timedelta(days=day, minutes=minute)).isoformat()  # noqa: E731
    cap_prefix = tid or f"demo-scene-{name}"
    # Rebuilding a scene replaces only its own rows.
    for c in all_("captures"):
        if c.get("trial_id") == tid and (tid or c.get("scene") == name):
            delete("captures", c["id"])
    if tid:
        check = D.check_product(catalog[sc.product_id], records)
        put("trials", {"id": tid, "goal_concern": sc.goal, "product_id": sc.product_id,
                       "held_fixed": sc.held_fixed,
                       "checkpoints_days": [14, 28], "status": "active", "check": check.to_dict(),
                       "started_at": start.isoformat(), "scene": name,
                       "checkins": [{"symptoms": s, "other_new_leave_on": [], "at": at(day, 30)}
                                    for day, s in sc.logs]})
    n = 0
    for block in sc.scans:
        for i in range(block.n):
            rp = demo.pick(block.persona, block.fixture_set, i)
            res = rp.result
            put("captures", {
                "trial_id": tid, "phase": block.phase, "mode": res.mode, "actions": list(res.actions),
                "place": "window" if block.phase in ("baseline", "free") else None,
                "fingerprint": fingerprint_for(rp, block.fixture_set, n),
                "raw_scores": res.raw_scores(), "result": {**res.to_dict(), "scores": {
                    k: {**v, "mask_urls": []} for k, v in res.to_dict()["scores"].items()}},
                "source": "replay", "youcam": None, "masks": {}, "scene": name,
                "replay": {"persona": rp.persona, "set": rp.set, "fixture": rp.path.name,
                           "synthetic": rp.synthetic, "reason": "guided_demo"},
                "taken_at": at(block.day, 2 * i + 1)}, id=f"{cap_prefix}-{n}")
            n += 1
    return {"scene": name, "trial_id": tid,
            "situation": dict(sc.situation) if sc.situation else None}


def write_outcomes(rows: list[dict], put: Callable[..., dict], all_: Callable[[str], list[dict]],
                   delete: Callable[[str, str], None], catalog: dict[str, D.Product],
                   now: datetime) -> list[dict]:
    """Write a scene's product outcomes, exactly as POST /api/outcomes would.

    The scene only ever supplies what the user would have typed: which product, what happened,
    how long, and for a breakout the zones and whether it settled. Everything derived (the 4-week
    rule, the label, the plain sentence) comes from app/outcomes.py, so the screen never shows a
    judgement the scene wrote.

    Start and stop dates are worked out from `started_weeks_ago` and `weeks` at build time, so a
    scene stays correct however long after it was written it is replayed.
    """
    # A scene sets this persona's whole state, so any outcome already stored goes first.
    for r in all_("outcomes"):
        delete("outcomes", r["id"])
    out = []
    today = now.date()
    for row in rows:
        pid = row["product_id"]
        if pid not in catalog:
            continue
        started = today - timedelta(weeks=row.get("started_weeks_ago", 0))
        weeks = row.get("weeks")
        stopped = None if row["outcome"] == "suited" else (
            started + timedelta(weeks=weeks) if weeks is not None else None)
        built = OC.ProductOutcome(
            product_id=pid, outcome=row["outcome"], leave_on=catalog[pid].leave_on,
            started_on=started, stopped_on=stopped,
            zones=list(row.get("zones", [])), usual_spots=row.get("usual_spots"),
            settled_while_using=row.get("settled_while_using"),
            settled_week=row.get("settled_week"), note=row.get("note", ""), source="user")
        out.append(put("outcomes", built.to_dict(today), id=f"demo-outcome-{pid}"))
    return out
