"""Benchmark cases. Each case: an id, a category (one row of the design doc's benchmark
table), what it checks, the expected output written from the design, and a function
that returns the engine's actual output. Pass = actual == expected.

Expected values come from the design (docs/DESIGN.md, section "Evidence benchmark"),
not from running the engine. If a case fails, the
engine and the design disagree: report it, don't edit the engine to match.
"""
from __future__ import annotations

import importlib
import io
import json
import os
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable

from app import decision as D
from app import evidence as E
from app.fingerprint import Fingerprint
from app.llm import explain as LX
from app.llm import intake as LI

from .fakes import ScriptedProvider

CAT = D.load_catalog()
CURRENT = ["cl-01", "sr-01", "mo-01", "sp-01"]   # cleanser, niacinamide serum, barrier cream, SPF


@dataclass
class Case:
    id: str
    category: str
    checks: str
    expected: Any
    run: Callable[[], Any]


# Categories in the order of the design doc's benchmark table.
EXCLUSION = "Avoided ingredient is blocked, with the label line"
SYNONYM = "Synonyms are still blocked"
INCOMPLETE = "Incomplete INCI is unknown, never pass"
REACTION = "Product-level reaction blocks that product only"
ADD_REPLACE = "Add switched to replace recalculates"
SEVERAL = "Several changes: can't tell"
OVERLAP = "Overlap: no detectable change"
NOT_COMPARABLE = "Different conditions: not comparable, re-guide"
SYMPTOMS = "Symptoms outrank improved scores"
PERSISTS = "Unresolved stop symptom persists"
NO_BASELINE = "Missing baseline: no trend claim"
WORDING = "Wording never claims cause"
NOTHING = "No exclusions recorded: nothing to check, never a pass"
LLM_DOWN = "LLM down or draft rejected: templates shown, core flow unaffected"
LLM_VALIDATOR = "LLM draft overclaims (\"caused by\" etc.): validator rejects it"
LLM_INTAKE = "LLM intake proposes; the user confirms"

CATEGORIES = [EXCLUSION, SYNONYM, INCOMPLETE, NOTHING, REACTION, ADD_REPLACE, SEVERAL, OVERLAP,
              NOT_COMPARABLE, SYMPTOMS, PERSISTS, NO_BASELINE, WORDING, LLM_DOWN, LLM_VALIDATOR, LLM_INTAKE]

# Rows of the design table this benchmark cannot test yet, with the reason. None left.
NOT_BUILT: list[tuple[str, str]] = []


# ---------------------------------------------------------------- helpers
def rec(kind: str, **kw) -> D.HistoryRecord:
    return D.HistoryRecord(D.RecordType(kind), **kw)


def status(pid: str, *records: D.HistoryRecord) -> str:
    return D.check_product(CAT[pid], list(records)).status.value


def lines(pid: str, *records: D.HistoryRecord) -> list[str]:
    return [m["label_line"] for m in D.check_product(CAT[pid], list(records)).matches]


AVOID_FRAGRANCE = rec("avoid", ingredient="fragrance")


def fp(lum=0.55, rb=1.20, face=0.70, yaw=0.0, device="PhoneX", hour=10, device_source=None):
    return Fingerprint(1080, 1440, lum, rb, device, hour, face, yaw, 0.0, 0.0, device_source=device_source)


def cap(score, mode="sd", **kw):
    return E.Capture({"redness": score}, fp(**kw), mode, ("redness",))


def device_gate(base_kw: dict, follow_kw: dict) -> tuple:
    """(comparable, failed fields, not-compared fields) for a device-only difference."""
    c = E.compare_conditions(caps(60, 62, **base_kw), caps(61, 63, **follow_kw))
    return c.comparable, sorted({f["field"] for f in c.failed}), [n["field"] for n in c.not_compared]


def caps(*scores, **kw):
    return [cap(s, **kw) for s in scores]


def verdict(base, follow, new=1, symptoms=()) -> str:
    return E.evaluate(base, follow, E.TrialContext(new, list(symptoms)), concerns=["redness"]).verdict.value


def report(base, follow, new=1, symptoms=()) -> E.EvidenceReport:
    return E.evaluate(base, follow, E.TrialContext(new, list(symptoms)), concerns=["redness"])


def gate_fields(follow_kw: dict, mode="sd") -> list[str]:
    c = E.compare_conditions(caps(60, 62), [cap(70, mode=mode, **follow_kw), cap(71, mode=mode, **follow_kw)])
    return sorted({f["field"] for f in c.failed})


def raises(fn: Callable[[], Any]) -> str:
    try:
        fn()
    except Exception as e:  # noqa: BLE001
        return type(e).__name__
    return "no error"


# ---------------------------------------------------------------- API sandbox
@contextmanager
def api(scores: list[float] = ()):
    """The real FastAPI app on a throwaway SQLite file, with YouCam replaced by a fake
    that returns `scores` in order. No network, no units, no backend/.env."""
    from fastapi.testclient import TestClient

    keys = ("DERMOS_DB", "DERMOS_MEDIA", "DERMOS_NO_DOTENV", "DEMO_MODE", "DERMOS_FIXTURES",
            "LIVE_SCAN_PASSCODE", "SCAN_RATE_LIMIT")
    old = {k: os.environ.get(k) for k in keys}
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
        os.environ.update(DERMOS_DB=os.path.join(d, "bench.db"), DERMOS_MEDIA=os.path.join(d, "media"),
                          DERMOS_NO_DOTENV="1", LIVE_SCAN_PASSCODE="bench", SCAN_RATE_LIMIT="0")
        os.environ.pop("DEMO_MODE", None)
        try:
            import app.main as m
            m = importlib.reload(m)
            queue = iter(scores)

            class FakeYouCam:
                def unit_balance(self):
                    return 10_000

                def analyze(self, path, actions):
                    from app.youcam import normalize
                    return normalize({"data": {"results": {"output": [
                        {"type": a, "raw_score": next(queue)} for a in actions]}}}, "sd", actions, None)

            m.YouCamClient = lambda: FakeYouCam()
            # The sandbox photo is a plain colour, so a stand-in detector reports one centred face
            # (the benchmark tests the evidence rules, not face detection; see tests/test_facecrop.py).
            from app import facecrop
            facecrop.set_detector(_centred_face)
            # "Live" here means the fake above: the passcode only routes scans to it.
            yield TestClient(m.app, headers={"X-Live-Passcode": "bench"})
        finally:
            from app import facecrop
            facecrop.set_detector(None)
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


def _centred_face(img):
    from app.facecrop import Box
    w, h = img.size
    return [Box(w / 4, h * 0.45 - w * 0.275, w / 2, w * 0.55, 0.99)]


def _jpg() -> bytes:
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", (720, 960), (200, 160, 140)).save(b, "JPEG")
    return b.getvalue()


def _scan(c, tid: str, phase: str):
    r = c.post("/api/scan", files={"image": ("a.jpg", _jpg(), "image/jpeg")},
               data={"actions": "redness", "trial_id": tid, "phase": phase, "face_ratio": 0.7,
                     "client_hour": "10", "client_device": "Bench Camera"})
    assert r.status_code == 200, r.text


def _trial(c, product="mo-03") -> str:
    r = c.post("/api/trials", json={"goal_concern": "redness", "product_id": product})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def api_blocked_trial_status() -> int:
    with api() as c:
        c.post("/api/history", json={"type": "avoid", "ingredient": "fragrance"})
        return c.post("/api/trials", json={"goal_concern": "redness", "product_id": "mo-02"}).status_code


def api_reaction_records() -> list[tuple]:
    with api() as c:
        c.post("/api/history", json={"type": "suspected_reaction", "product_id": "mo-02"})
        return [(r["type"], r.get("product_id"), r.get("ingredient")) for r in c.get("/api/history").json()]


def api_several_changes() -> str:
    with api([60, 62, 70, 71]) as c:
        tid = _trial(c)
        for ph in ("baseline", "baseline", "checkin", "checkin"):
            _scan(c, tid, ph)
        c.post(f"/api/trials/{tid}/checkin", json={"symptoms": [], "other_new_leave_on": ["sr-04"]})
        return c.get(f"/api/trials/{tid}/evidence").json()["report"]["verdict"]


def api_stop_flow() -> dict:
    """itching, then a clean check-in, then resolve, then itching again."""
    out = {}
    with api([60, 62, 75, 76]) as c:
        tid = _trial(c)
        for ph in ("baseline", "baseline", "checkin", "checkin"):
            _scan(c, tid, ph)
        ev = lambda: c.get(f"/api/trials/{tid}/evidence").json()  # noqa: E731
        c.post(f"/api/trials/{tid}/checkin", json={"symptoms": ["itching"]})
        c.post(f"/api/trials/{tid}/checkin", json={"symptoms": []})
        e = ev()
        out["after_clean_checkin"] = e["report"]["verdict"]
        out["open_reactions"] = [r["symptom"] for r in e["reactions"] if not r["resolved"]]
        rid = e["reactions"][0]["id"]
        c.post(f"/api/trials/{tid}/reactions/{rid}/resolve", json={"note": "settled"})
        out["after_resolve"] = ev()["report"]["verdict"]
        c.post(f"/api/trials/{tid}/checkin", json={"symptoms": ["itching"]})
        out["after_relog"] = ev()["report"]["verdict"]
    return out


_STOP_FLOW: dict | None = None


def stop_flow(key: str):
    global _STOP_FLOW
    if _STOP_FLOW is None:
        _STOP_FLOW = api_stop_flow()
    return _STOP_FLOW[key]


def build(*items: tuple[str, str | None]) -> D.RoutineResult:
    return D.build(CURRENT, D.Option("X", [D.OptionItem(p, mode) for p, mode in items]), CAT, [])


def compare_q(mode):
    return D.compare(CURRENT, [D.Option("B", [D.OptionItem("mo-03", mode)])], CAT, [])["next_question"]


def tags(pid: str, *records: D.HistoryRecord) -> tuple:
    c = D.check_product(CAT[pid], list(records))
    return c.status.value, c.tags


# ---------------------------------------------------------------- LLM (scripted provider, no network)
def _rec_no_change() -> tuple[dict, str]:
    rep = E.evaluate(caps(60, 64), caps(62, 63), E.TrialContext(), concerns=["redness"]).to_dict()
    return LX.record_for(rep, CAT["sr-04"], "redness"), rep["message"]


def explain_with(*outputs) -> dict:
    """outputs empty = LLM off."""
    rec, template = _rec_no_change()
    out = LX.explain(rec, template, CAT, ScriptedProvider(*outputs) if outputs else None)
    return {**out, "is_template": out["text"] == template}


def rejects(draft: str) -> str | None:
    return LX.validate(draft, _rec_no_change()[0], CAT)


def intake_json(*recs) -> str:
    return json.dumps({"records": [{"product": None, "ingredient": None, "clinician_confirmed": False, **r}
                                   for r in recs]})


INTAKE_TEXT = "I broke out from a fragranced moisturiser last year and my dermat said I'm allergic to lanolin"
INTAKE_GOOD = intake_json(
    {"kind": "product_reaction", "product": "fragranced moisturiser", "quote": "I broke out from a fragranced moisturiser"},
    {"kind": "ingredient_allergy", "ingredient": "lanolin", "clinician_confirmed": True,
     "quote": "my dermat said I'm allergic to lanolin"})


def intake(text: str, *outputs) -> dict:
    return LI.propose(text, CAT, ScriptedProvider(*outputs))


def first_proposal(text: str, *recs) -> dict:
    return intake(text, intake_json(*recs))["proposals"][0]


def api_llm(outputs: tuple, path: str):
    """The real API with a scripted provider (outputs empty = LLM off)."""
    with api([60, 62, 61, 63]) as c:
        import app.main as m
        original = m.L.get_provider
        m.L.get_provider = (lambda: ScriptedProvider(*outputs)) if outputs else (lambda: None)
        try:
            if path == "intake":
                r = c.post("/api/history/intake", json={"text": INTAKE_TEXT}).json()
                return [p["type"] for p in r["proposals"]], c.get("/api/history").json()
            tid = _trial(c)
            for ph in ("baseline", "baseline", "checkin", "checkin"):
                _scan(c, tid, ph)
            ev = c.get(f"/api/trials/{tid}/evidence")
            ex = c.get(f"/api/trials/{tid}/explanation").json()
            return ev.status_code, ex["source"], ex["text"] == ev.json()["report"]["message"]
        finally:
            m.L.get_provider = original


V = E.Verdict

# ---------------------------------------------------------------- the cases
CASES: list[Case] = [
    # Exclusions
    Case("ex-01", EXCLUSION, "Avoid fragrance; Velvet Rose lists Parfum", "blocked", lambda: status("mo-02", AVOID_FRAGRANCE)),
    Case("ex-02", EXCLUSION, "The block shows the exact label line", ["Parfum", "Linalool"], lambda: lines("mo-02", AVOID_FRAGRANCE)),
    Case("ex-03", EXCLUSION, "Avoid fragrance also catches declared components (Linalool, Citronellol, Geraniol)",
         "blocked", lambda: status("tn-03", AVOID_FRAGRANCE)),
    Case("ex-04", EXCLUSION, "Confirmed salicylic acid allergy blocks the BHA gel, label line and record type shown",
         [("Salicylic Acid 2%", "confirmed_allergy")],
         lambda: [(m["label_line"], m["record"]) for m in D.check_product(
             CAT["tr-02"], [rec("confirmed_allergy", ingredient="Salicylic Acid")]).matches]),
    Case("ex-05", EXCLUSION, "Same allergy: a moisturiser without it passes", "pass",
         lambda: status("mo-01", rec("confirmed_allergy", ingredient="Salicylic Acid"))),
    Case("ex-06", EXCLUSION, "API refuses to start a trial with a blocked product", 409, api_blocked_trial_status),
    # Synonyms
    Case("syn-01", SYNONYM, "Avoid 'Parfum'; toner lists 'Fragrance'", "blocked",
         lambda: status("tn-02", rec("avoid", ingredient="Parfum"))),
    Case("syn-02", SYNONYM, "Avoid 'FRAGRANCE' (case) still matches 'Parfum'", "blocked",
         lambda: status("mo-02", rec("avoid", ingredient="FRAGRANCE"))),
    Case("syn-03", SYNONYM, "Avoid fragrance catches tea tree oil by its INCI name", ["Melaleuca Alternifolia Leaf Oil"],
         lambda: lines("tr-02", AVOID_FRAGRANCE)),
    Case("syn-04", SYNONYM, "Avoid fragrance: SPF lists orange peel oil, Fragrance and Limonene; all three shown",
         ["Citrus Aurantium Dulcis Peel Oil", "Fragrance", "Limonene"], lambda: lines("sp-03", AVOID_FRAGRANCE)),
    Case("syn-05", SYNONYM, "Avoid 'nicotinamide'; serum lists 'Niacinamide 10%' (percentage stripped)",
         ["Niacinamide 10%"], lambda: lines("sr-01", rec("avoid", ingredient="nicotinamide"))),
    Case("syn-06", SYNONYM, "Avoid 'alcohol' does not catch the fatty alcohol 'Cetearyl Alcohol'", "pass",
         lambda: status("mo-01", rec("avoid", ingredient="alcohol"))),
    # Incomplete INCI
    Case("inc-01", INCOMPLETE, "Incomplete list, avoid fragrance: unknown", "unknown",
         lambda: status("mo-04", AVOID_FRAGRANCE)),
    Case("inc-02", INCOMPLETE, "The reason says it is not a pass", True,
         lambda: "not a pass" in D.check_product(CAT["mo-04"], [AVOID_FRAGRANCE]).reasons[0]),
    Case("inc-03", INCOMPLETE, "Incomplete list with a confirmed allergy: unknown", "unknown",
         lambda: status("sr-03", rec("confirmed_allergy", ingredient="retinol"))),
    Case("inc-04", INCOMPLETE, "Incomplete list that does list the avoided ingredient: blocked", "blocked",
         lambda: status("cl-04", rec("avoid", ingredient="niacinamide"))),
    Case("inc-05", INCOMPLETE, "Compare column lists it under unknowns and doesn't call it blocked", (["mo-04"], False),
         lambda: (lambda col: (col["unknowns"], col["blocked"]))(D.compare(
             CURRENT, [D.Option("B", [D.OptionItem("mo-04", "replace")])], CAT, [AVOID_FRAGRANCE])["columns"][1])),
    # Nothing to check
    Case("nt-01", NOTHING, "No records at all: a complete product is 'nothing to check'", "nothing_to_check",
         lambda: status("mo-01")),
    Case("nt-02", NOTHING, "Every catalog product with no records: none says 'pass'", [],
         lambda: [p for p in CAT if status(p) == "pass"]),
    Case("nt-03", NOTHING, "The reason says it is not a pass", True,
         lambda: "not a pass" in D.check_product(CAT["mo-01"], []).reasons[0]),
    Case("nt-04", NOTHING, "Incomplete list, no exclusions: nothing to check AND tagged incomplete",
         ("nothing_to_check", [D.INCOMPLETE_TAG]), lambda: tags("mo-04")),
    Case("nt-05", NOTHING, "Incomplete list, avoid fragrance: unknown AND tagged incomplete",
         ("unknown", [D.INCOMPLETE_TAG]), lambda: tags("mo-04", AVOID_FRAGRANCE)),
    Case("nt-06", NOTHING, "Incomplete list that lists the avoided ingredient: blocked AND tagged incomplete",
         ("blocked", [D.INCOMPLETE_TAG]), lambda: tags("cl-04", rec("avoid", ingredient="niacinamide"))),
    Case("nt-07", NOTHING, "A complete list is never tagged incomplete", ("pass", []),
         lambda: tags("mo-01", AVOID_FRAGRANCE)),
    # Product-level reaction
    Case("pr-01", REACTION, "Reaction to Velvet Rose blocks Velvet Rose", "blocked",
         lambda: status("mo-02", rec("suspected_reaction", product_id="mo-02"))),
    Case("pr-02", REACTION, "Rose toner sharing Linalool is not blocked (no ingredient allergy invented); "
         "with no ingredient exclusions it is 'nothing to check'", "nothing_to_check",
         lambda: status("tn-03", rec("suspected_reaction", product_id="mo-02"))),
    Case("pr-03", REACTION, "A reaction record must name a product", "ValueError",
         lambda: raises(lambda: rec("suspected_reaction", ingredient="fragrance"))),
    Case("pr-04", REACTION, "API stores one product-level record, no ingredient",
         [("suspected_reaction", "mo-02", None)], api_reaction_records),
    # Add -> replace
    Case("ar-01", ADD_REPLACE, "Add: old moisturiser kept, duplicate role flagged", (True, ["moisturiser"]),
         lambda: (lambda r: ("mo-01" in r.steps, r.duplicate_roles))(build(("mo-03", "add")))),
    Case("ar-02", ADD_REPLACE, "Replace: routine swaps the moisturiser, no duplicate",
         (["cl-01", "sr-01", "mo-03", "sp-01"], [{"out": "mo-01", "in": "mo-03"}], []),
         lambda: (lambda r: (r.steps, r.replaced, r.duplicate_roles))(build(("mo-03", "replace")))),
    Case("ar-03", ADD_REPLACE, "New spend counts only the new product (Rs 650) either way", (650, 650),
         lambda: (build(("mo-03", "add")).new_spend_inr, build(("mo-03", "replace")).new_spend_inr)),
    Case("ar-04", ADD_REPLACE, "Unanswered: asks 'replace or add', naming both products", (["replace", "add"], True),
         lambda: (lambda q: (q["choices"], "Water Gel Moisturiser" in q["text"] and "Daily Barrier Cream" in q["text"]))(
             compare_q(None))),
    Case("ar-05", ADD_REPLACE, "Answered 'replace': the question goes away", None, lambda: compare_q("replace")),
    Case("ar-06", ADD_REPLACE, "Add: 5 steps after, stop using nothing", (5, []),
         lambda: (lambda r: (r.step_count, r.stopped))(build(("mo-03", "add")))),
    Case("ar-07", ADD_REPLACE, "Replace: 4 steps after, stop using the Daily Barrier Cream", (4, ["mo-01"]),
         lambda: (lambda r: (r.step_count, r.stopped))(build(("mo-03", "replace")))),
    Case("ar-08", ADD_REPLACE, "'Replace' with nothing in that role adds a step and stops nothing", (5, [], ["tr-02"]),
         lambda: (lambda r: (r.step_count, r.stopped, r.added))(build(("tr-02", "replace")))),
    # Several changes
    Case("sc-01", SEVERAL, "Two new leave-on products and scores moved", V.SEVERAL_CHANGES.value,
         lambda: verdict(caps(60, 62), caps(70, 71), new=2)),
    Case("sc-02", SEVERAL, "Two new leave-on products and scores flat (still can't tell, not 'no change')",
         V.SEVERAL_CHANGES.value, lambda: verdict(caps(60, 64), caps(62, 63), new=2)),
    Case("sc-03", SEVERAL, "Compare counts a two-product option as 2 new leave-on", 2,
         lambda: build(("sr-04", "add"), ("mo-03", "replace")).new_leave_on),
    Case("sc-04", SEVERAL, "API: check-in logs another new product", V.SEVERAL_CHANGES.value, api_several_changes),
    # Overlap
    Case("ov-01", OVERLAP, "Baseline 60-64, check-in 62-65", V.NO_CHANGE.value, lambda: verdict(caps(60, 64), caps(62, 65))),
    Case("ov-02", OVERLAP, "Ranges touch at one point (60-64 vs 64-66)", V.NO_CHANGE.value,
         lambda: verdict(caps(60, 64), caps(64, 66))),
    Case("ov-03", OVERLAP, "Check-in inside a wide baseline", V.NO_CHANGE.value, lambda: verdict(caps(58, 66), caps(61, 62))),
    Case("ov-04", OVERLAP, "Overlap gives no direction", (None, False),
         lambda: (lambda f: (f.direction, f.beyond_noise))(report(caps(60, 64), caps(62, 65)).findings[0])),
    Case("ov-05", OVERLAP, "Control: no overlap moves beyond noise", V.MOVED.value, lambda: verdict(caps(60, 62), caps(70, 71))),
    # Not comparable
    Case("nc-01", NOT_COMPARABLE, "Much dimmer light", V.NOT_COMPARABLE.value,
         lambda: verdict(caps(60, 62), caps(70, 71, lum=0.30))),
    Case("nc-02", NOT_COMPARABLE, "Warm lamp: says the light is warmer", True,
         lambda: any("warmer" in r for r in report(caps(60, 62), caps(66, 67, rb=1.60)).comparability.reasons)),
    Case("nc-03", NOT_COMPARABLE, "Face fills less of the frame", ["face_size"], lambda: gate_fields({"face": 0.50})),
    Case("nc-04", NOT_COMPARABLE, "Head turned 20 degrees", ["head_pose"], lambda: gate_fields({"yaw": 20.0})),
    Case("nc-05", NOT_COMPARABLE, "Another camera", ["device"], lambda: gate_fields({"device": "PhoneY"})),
    Case("nc-06", NOT_COMPARABLE, "Ten hours later", ["time_of_day"], lambda: gate_fields({"hour": 20})),
    Case("nc-07", NOT_COMPARABLE, "SD baseline vs HD check-in", ["mode"], lambda: gate_fields({}, mode="hd")),
    Case("nc-08", NOT_COMPARABLE, "Every mismatch carries a re-guide fix", True,
         lambda: (lambda c: bool(c.failed) and all(f["fix"] for f in c.failed) and bool(c.fixes))(
             E.compare_conditions(caps(60, 62), caps(70, 71, lum=0.3, face=0.5, hour=20)))),
    Case("nc-11", NOT_COMPARABLE, "Same label source (both live camera), different camera: fails",
         (False, ["device"], []),
         lambda: device_gate({"device_source": "client"}, {"device": "PhoneY", "device_source": "client"})),
    Case("nc-12", NOT_COMPARABLE, "Photo-file label vs live-camera label: device 'not compared', pair still comparable",
         (True, [], ["device"]),
         lambda: device_gate({"device": "Acme Phone 7", "device_source": "exif"},
                             {"device": "Front Camera", "device_source": "client"})),
    Case("nc-09", NOT_COMPARABLE, "Not comparable outranks big score gains", V.NOT_COMPARABLE.value,
         lambda: verdict(caps(60, 62), caps(80, 81, rb=1.60))),
    Case("nc-10", NOT_COMPARABLE, "Small light change within tolerance stays comparable", V.NO_CHANGE.value,
         lambda: verdict(caps(60, 64), caps(62, 63, lum=0.60))),
    # Symptoms
    Case("sy-01", SYMPTOMS, "Scores improve, itching reported", V.STOP_REACTION.value,
         lambda: verdict(caps(60, 62), caps(75, 76), symptoms=["itching"])),
    Case("sy-02", SYMPTOMS, "Burning outranks 'not comparable'", V.STOP_REACTION.value,
         lambda: verdict(caps(60, 62), caps(75, 76, lum=0.3), symptoms=["burning"])),
    Case("sy-03", SYMPTOMS, "Swelling outranks 'several changes'", V.STOP_REACTION.value,
         lambda: verdict(caps(60, 62), caps(75, 76), new=2, symptoms=["swelling"])),
    Case("sy-04", SYMPTOMS, "Swelling with no baseline yet still stops", V.STOP_REACTION.value,
         lambda: verdict([], [], symptoms=["swelling"])),
    Case("sy-05", SYMPTOMS, "' Itching ' with stray case and spaces still stops", V.STOP_REACTION.value,
         lambda: verdict(caps(60, 62), caps(75, 76), symptoms=[" Itching "])),
    Case("sy-06", SYMPTOMS, "A non-stop symptom (dryness) is shown beside the result", (V.MOVED.value, True),
         lambda: (lambda r: (r.verdict.value, "dryness" in r.message))(
             report(caps(60, 62), caps(75, 76), symptoms=["dryness"]))),
    # Unresolved stop symptom persists (API)
    Case("sp-01", PERSISTS, "Itching, then a clean check-in: still Stop", V.STOP_REACTION.value,
         lambda: stop_flow("after_clean_checkin")),
    Case("sp-02", PERSISTS, "The reaction stays open until resolved", ["itching"], lambda: stop_flow("open_reactions")),
    Case("sp-03", PERSISTS, "Marked resolved: Stop lifts, scores speak again", V.MOVED.value,
         lambda: stop_flow("after_resolve")),
    Case("sp-04", PERSISTS, "Itching logged again after resolving: Stop again", V.STOP_REACTION.value,
         lambda: stop_flow("after_relog")),
    # Missing baseline
    Case("mb-01", NO_BASELINE, "No baseline scans", V.NO_BASELINE.value, lambda: verdict([], caps(75, 76))),
    Case("mb-02", NO_BASELINE, "One baseline scan only", V.NO_BASELINE.value, lambda: verdict(caps(60), caps(75, 76))),
    Case("mb-03", NO_BASELINE, "One check-in scan only", V.NO_BASELINE.value, lambda: verdict(caps(60, 62), caps(75))),
    Case("mb-04", NO_BASELINE, "No trend wording when the baseline is missing", E.VERDICT_TEXT[V.NO_BASELINE],
         lambda: report(caps(60), caps(75, 76)).message),
    # Wording
    Case("wd-01", WORDING, "No verdict text says 'caused' or 'because of'", [],
         lambda: [v.value for v, t in E.VERDICT_TEXT.items() if "caused" in t.lower() or "because of" in t.lower()]),
    Case("wd-02", WORDING, "Strongest result says 'during the trial' and 'does not prove'", (True, True),
         lambda: (lambda m: ("during the trial" in m, "does not prove" in m))(report(caps(60, 62), caps(70, 71)).message)),
    # LLM down or draft rejected (scripted provider, no network)
    Case("llm-01", LLM_DOWN, "LLM off: explanation is the template", ("template", True),
         lambda: (lambda o: (o["source"], o["is_template"]))(explain_with())),
    Case("llm-02", LLM_DOWN, "Provider times out twice (one retry): template", ("template", "provider_failed", True),
         lambda: (lambda o: (o["source"], o["rejected"], o["is_template"]))(explain_with(TimeoutError(), TimeoutError()))),
    Case("llm-03", LLM_DOWN, "Rejected draft: template shown", ("template", True),
         lambda: (lambda o: (o["source"], o["is_template"]))(explain_with("The serum caused this."))),
    Case("llm-04", LLM_DOWN, "A clean draft passes and is used", "llm",
         lambda: explain_with("Your redness scores sit inside your own range, so no detectable change yet.")["source"]),
    Case("llm-05", LLM_DOWN, "API, LLM off: evidence and explanation work, template text", (200, "template", True),
         lambda: api_llm((), "explain")),
    Case("llm-06", LLM_DOWN, "API, provider failing: same template, core flow unaffected", (200, "template", True),
         lambda: api_llm((TimeoutError(), TimeoutError()), "explain")),
    Case("llm-07", LLM_DOWN, "Intake output that isn't JSON is rejected: no proposals", ([], "not_json"),
         lambda: (lambda o: (o["proposals"], o["rejected"]))(intake("I avoid fragrance", "Sure! Fragrance."))),
    # Claim validator
    Case("llm-08", LLM_VALIDATOR, "Draft says 'caused by'", "causal_wording",
         lambda: rejects("Your redness was caused by the serum.")),
    Case("llm-09", LLM_VALIDATOR, "Draft says 'thanks to'", "causal_wording",
         lambda: rejects("Redness sits in range thanks to the serum.")),
    Case("llm-10", LLM_VALIDATOR, "Draft names a diagnosis", "diagnosis_word", lambda: rejects("This may be rosacea.")),
    Case("llm-11", LLM_VALIDATOR, "Draft names a product not in the record", "name_not_in_record",
         lambda: rejects("Try Velvet Rose Moisturiser next.")),
    Case("llm-12", LLM_VALIDATOR, "Draft claims improvement when the verdict is 'no detectable change'",
         "stronger_verdict", lambda: rejects("Your redness improved.")),
    Case("llm-13", LLM_VALIDATOR, "Draft gives a number not in the record", "number_not_in_record",
         lambda: rejects("Your redness moved 17 points.")),
    # Intake
    Case("llm-14", LLM_INTAKE, "Example text: product reaction + clinician-confirmed lanolin allergy",
         [("suspected_reaction", None, None), ("confirmed_allergy", None, "lanolin")],
         lambda: [(p["type"], p["product_id"], p["ingredient"]) for p in intake(INTAKE_TEXT, INTAKE_GOOD)["proposals"]]),
    Case("llm-15", LLM_INTAKE, "Unmatched product stays as typed text and needs confirmation",
         ("fragranced moisturiser", False, ["product_id"]),
         lambda: (lambda p: (p["product_text"], p["product_matched"], p["needs_confirmation"]))(
             intake(INTAKE_TEXT, INTAKE_GOOD)["proposals"][0])),
    Case("llm-16", LLM_INTAKE, "LLM attaches an ingredient to a product reaction: dropped, stays product-level",
         ("suspected_reaction", "mo-02", None),
         lambda: (lambda p: (p["type"], p["product_id"], p["ingredient"]))(first_proposal(
             "Velvet Rose Moisturiser made me itchy",
             {"kind": "product_reaction", "product": "Velvet Rose Moisturiser", "ingredient": "fragrance",
              "clinician_confirmed": True, "quote": "Velvet Rose Moisturiser made me itchy"}))),
    Case("llm-17", LLM_INTAKE, "Allergy with no clinician in the text: proposed as 'avoid', type needs confirmation",
         ("avoid", True),
         lambda: (lambda p: (p["type"], "type" in p["needs_confirmation"]))(first_proposal(
             "I'm allergic to lanolin",
             {"kind": "ingredient_allergy", "ingredient": "lanolin", "clinician_confirmed": True,
              "quote": "I'm allergic to lanolin"}))),
    Case("llm-18", LLM_INTAKE, "API intake proposes but saves nothing",
         (["suspected_reaction", "confirmed_allergy"], []), lambda: api_llm((INTAKE_GOOD,), "intake")),
]
