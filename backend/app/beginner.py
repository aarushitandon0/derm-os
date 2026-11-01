"""Start here: the beginner path.

docs/STRATEGY.md section 4, "Start here". A 4-question quiz, then (when a scan is live) one SD
request for skin_type plus the concern set, then a 3-step starter checked through the cart check,
then their first one-change trial.

Two honesty points that decide how this module is written:

* **Skin type is labelled by where it came from.** Whether SD `skin_type` returns a T-zone/U-zone
  split is unverified: there is no recorded skin_type fixture, and finding out costs a unit. So
  until a verification scan has run, the skin type shown is `source="answers"` and the screen says
  "from your answers". `parse_skin_type()` below is written to cope with whatever shape the real
  response turns out to be, and is tested on synthetic dicts rather than on an invented fixture
  file, because a fake fixture would look like recorded data and isn't.

* **The starter is checked, not recommended.** Each of the three steps goes through
  app/cartcheck.py like any other purchase, so a beginner's first routine is held to the same bar
  as an experimenter's next buy.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import cartcheck as CC
from .decision import HistoryRecord, Product

RULE_VERSION = "beginner-1.0"

# The four questions. Short on purpose: a beginner who doesn't know their skin type can still
# answer all four honestly in under a minute.
QUESTIONS = [
    {
        "id": "midday",
        "text": "By the middle of the day, how does your face usually feel?",
        "why": "This is the single most useful question for skin type, and it needs no jargon.",
        "choices": [
            {"value": "tight", "label": "Tight or flaky", "type_points": {"dry": 2}},
            {"value": "comfortable", "label": "About the same as the morning", "type_points": {"normal": 2}},
            {"value": "shiny_tzone", "label": "Shiny on the nose and forehead only", "type_points": {"combination": 2}},
            {"value": "shiny_all", "label": "Shiny all over", "type_points": {"oily": 2}},
        ],
    },
    {
        "id": "reacts",
        "text": "Do new products often sting, itch or turn you red?",
        "why": "Sensitivity changes how fast you should add anything, whatever your skin type is.",
        "choices": [
            {"value": "often", "label": "Often", "type_points": {"sensitive": 2}},
            {"value": "sometimes", "label": "Now and then", "type_points": {"sensitive": 1}},
            {"value": "rarely", "label": "Rarely", "type_points": {}},
            {"value": "unknown", "label": "I haven't used enough to know", "type_points": {}},
        ],
    },
    {
        "id": "breakouts",
        "text": "How often do you get spots?",
        "why": "It sets whether the starter leaves room for a treatment step later.",
        "choices": [
            {"value": "weekly", "label": "Most weeks", "type_points": {"oily": 1}},
            {"value": "monthly", "label": "Around once a month", "type_points": {}},
            {"value": "rarely", "label": "Rarely", "type_points": {}},
        ],
    },
    {
        "id": "using",
        "text": "What are you using on your face right now?",
        "why": "A starter has to start from what you already do, not from nothing.",
        "choices": [
            {"value": "nothing", "label": "Nothing, or just water", "type_points": {}},
            {"value": "cleanser", "label": "A face wash", "type_points": {}},
            {"value": "few", "label": "A few things I picked up", "type_points": {}},
        ],
    },
]

SKIN_TYPES = ("dry", "normal", "combination", "oily")

TYPE_LINE = {
    "dry": "Your answers point to dry skin: it feels tight or flaky rather than shiny.",
    "normal": "Your answers point to normal skin: it feels much the same through the day.",
    "combination": "Your answers point to combination skin: shiny through the middle of the face, "
                   "comfortable or dry on the cheeks.",
    "oily": "Your answers point to oily skin: shiny across the whole face by the middle of the day.",
}
SENSITIVE_LINE = ("You also said new products often bother you. That doesn't change your skin type; it "
                  "changes the pace. One new product at a time, patch-tested first.")

# Plain sentences for the measured concerns, one each. No numbers, no claims.
CONCERN_SENTENCE = {
    "pore": "Pores: how visible the openings in your skin are, mostly around the nose and cheeks.",
    "acne": "Breakouts: how much of your face has spots right now.",
    "redness": "Redness: how flushed your skin reads, which is also what an irritated patch looks like.",
    "texture": "Texture: how even the surface is when light falls across it.",
    "oiliness": "Oiliness: how much shine your skin is putting out.",
    "moisture": "Moisture: how much water your skin's surface is holding.",
    "radiance": "Radiance: how much light your skin bounces back.",
    "age_spot": "Spots: patches that read darker than the skin around them.",
}

# The 3-step starter. Cleanse, moisturise, protect: nothing active, because a beginner has no
# baseline to read an active against yet.
STARTER_ROLES = ("cleanser", "moisturiser", "sunscreen")
STARTER_BY_TYPE: dict[str, list[str]] = {
    "dry": ["cl-03", "mo-01", "sp-02"],
    "normal": ["cl-01", "mo-01", "sp-01"],
    "combination": ["cl-01", "mo-03", "sp-01"],
    "oily": ["cl-02", "mo-06", "sp-04"],
}
SENSITIVE_STARTER = ["cl-03", "mo-05", "sp-02"]

ONE_AT_A_TIME = ("Start one at a time. Add the cleanser and the moisturiser together if you like, then "
                 "the sunscreen on its own, so that if something bothers you there is only one thing it "
                 "could be.")

FROM_ANSWERS_LABEL = "from your answers"
FROM_SCAN_LABEL = "from your scan"


@dataclass
class SkinType:
    value: str | None
    source: str                      # "answers" | "scan"
    label: str                       # what the screen prints beside it
    zones: dict[str, str] = field(default_factory=dict)
    sensitive: bool = False
    line: str = ""

    def to_dict(self) -> dict:
        return {"value": self.value, "source": self.source, "label": self.label,
                "zones": dict(self.zones), "sensitive": self.sensitive, "line": self.line}


def skin_type_from_answers(answers: dict[str, str]) -> SkinType:
    """The quiz's own read. This is what is shown until a verification scan has been run."""
    points: dict[str, int] = {}
    for q in QUESTIONS:
        chosen = answers.get(q["id"])
        choice = next((c for c in q["choices"] if c["value"] == chosen), None)
        for k, v in (choice or {}).get("type_points", {}).items():
            points[k] = points.get(k, 0) + v
    sensitive = points.get("sensitive", 0) >= 2
    ranked = [(t, points.get(t, 0)) for t in SKIN_TYPES]
    best = max(ranked, key=lambda tv: tv[1])
    value = best[0] if best[1] > 0 else None
    line = TYPE_LINE.get(value, "Your answers don't point clearly to one skin type yet.")
    if sensitive:
        line = f"{line} {SENSITIVE_LINE}"
    return SkinType(value, "answers", FROM_ANSWERS_LABEL, {}, sensitive, line)


# ---------------------------------------------------------------- the unverified response shape
# SD skin_type's response shape is not documented and has not been seen. Rather than guess one
# shape and crash on the real thing, this walks whatever comes back looking for a known skin-type
# word, and reports which zone it was found under when the response happens to be split by zone.
_TYPE_WORDS = {
    "dry": "dry", "normal": "normal", "combination": "combination", "combo": "combination",
    "oily": "oily", "oil": "oily",
}
ZONE_KEYS = ("t_zone", "u_zone", "tzone", "uzone", "forehead", "nose", "cheek", "cheeks", "whole")
ZONE_LABEL = {"t_zone": "T-zone", "tzone": "T-zone", "u_zone": "U-zone", "uzone": "U-zone",
              "forehead": "forehead", "nose": "nose", "cheek": "cheeks", "cheeks": "cheeks",
              "whole": "whole face"}


def _word(v) -> str | None:
    if not isinstance(v, str):
        return None
    return _TYPE_WORDS.get(v.strip().lower().replace("-", "").replace("_", "").replace(" ", ""))


def parse_skin_type(payload) -> SkinType:
    """Pull a skin type out of a YouCam skin_type response of unknown shape.

    Tolerant on purpose: it accepts a bare string, {"skin_type": "oily"}, a nested
    data/results/output structure, and a per-zone split, because which of those YouCam actually
    returns is unverified. When nothing recognisable is found it returns value=None rather than a
    guess, and the caller keeps showing the quiz's answer.
    """
    zones: dict[str, str] = {}
    found: list[str] = []

    def walk(node, zone: str | None = None) -> None:
        if isinstance(node, str):
            w = _word(node)
            if w:
                found.append(w)
                if zone:
                    zones[ZONE_LABEL.get(zone, zone)] = w
            return
        if isinstance(node, list):
            for item in node:
                walk(item, zone)
            return
        if not isinstance(node, dict):
            return
        for k, v in node.items():
            key = str(k).strip().lower()
            if key in ZONE_KEYS:
                walk(v, key)
            elif key in ("skin_type", "hd_skin_type", "type", "value", "label", "result",
                         "results", "data", "output", "class", "category"):
                walk(v, zone)
            else:
                walk(v, zone)

    walk(payload)
    if not found:
        return SkinType(None, "scan", FROM_SCAN_LABEL, {}, False,
                        "The scan came back without a skin type we could read, so this is still "
                        "from your answers.")
    # A whole-face reading wins over a zone one; otherwise the most common word.
    value = zones.get("whole face") or max(set(found), key=found.count)
    line = TYPE_LINE.get(value, f"Your scan reads as {value}.")
    if zones and set(zones) - {"whole face"}:
        bits = ", ".join(f"{z}: {t}" for z, t in sorted(zones.items()) if z != "whole face")
        line = f"{line} By zone — {bits}."
    return SkinType(value, "scan", FROM_SCAN_LABEL, zones, False, line)


# ---------------------------------------------------------------- the starter
def starter_ids(st: SkinType) -> list[str]:
    if st.sensitive:
        return list(SENSITIVE_STARTER)
    return list(STARTER_BY_TYPE.get(st.value or "normal", STARTER_BY_TYPE["normal"]))


def concern_lines(measured: dict[str, float] | None, n: int = 3) -> list[dict]:
    """The top measured concerns, each with one plain sentence. Empty with no scan."""
    out = []
    for c in CC.top_concerns(measured, n):
        out.append({"concern": c, "word": CC.concern_word(c),
                    "score": (measured or {}).get(c),
                    "sentence": CONCERN_SENTENCE.get(c, f"{CC.concern_word(c).capitalize()}: "
                                                        f"one of the things YouCam measures.")})
    return out


@dataclass
class StarterPlan:
    skin_type: SkinType
    concerns: list[dict]
    steps: list[dict]                # one per role: the product and its cart check
    one_at_a_time: str = ONE_AT_A_TIME
    next_step: str = ""
    rule_version: str = RULE_VERSION

    def to_dict(self) -> dict:
        return {"skin_type": self.skin_type.to_dict(), "concerns": self.concerns,
                "steps": self.steps, "one_at_a_time": self.one_at_a_time,
                "next_step": self.next_step, "rule_version": self.rule_version}


def plan(answers: dict[str, str], catalog: dict[str, Product],
         records: list[HistoryRecord] | None = None,
         measured: dict[str, float] | None = None,
         scan_payload=None, shelf: list[str] | None = None) -> StarterPlan:
    """Quiz (plus a scan when there is one) into a checked 3-step starter and one next step."""
    st = skin_type_from_answers(answers)
    if scan_payload is not None:
        scanned = parse_skin_type(scan_payload)
        if scanned.value:
            scanned.sensitive = st.sensitive
            if st.sensitive:
                scanned.line = f"{scanned.line} {SENSITIVE_LINE}"
            st = scanned
    steps = []
    for pid in starter_ids(st):
        p = catalog.get(pid)
        if p is None:
            continue
        chk = CC.check(p, list(records or []), [], catalog, measured, list(shelf or []))
        steps.append({"role": p.role, "product": p.__dict__, "check": chk.to_dict()})
    first = next((s for s in steps if s["role"] == "cleanser"), steps[0] if steps else None)
    plan_ = StarterPlan(st, concern_lines(measured), steps)
    plan_.next_step = (
        f"Start with {first['product']['name']} and your moisturiser. We'll open a trial on "
        f"{first['product']['name']} with day 14 and day 28 check-ins, so your first scan has "
        f"something to be read against." if first else
        "Add the products you can get hold of, then we'll open your first trial.")
    return plan_
