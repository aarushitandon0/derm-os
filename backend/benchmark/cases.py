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
from datetime import date
from typing import Any, Callable

from app import cartcheck as CC
from app import decision as D
from app import evidence as E
from app import outcomes as OC
from app import patterns as PA
from app import products as PRD
from app import triage as TR
from app import writeback as WBK
from app.fingerprint import Fingerprint
from app.llm import explain as LX
from app.llm import intake as LI

from .fakes import ScriptedProvider

CAT = D.load_catalog()
# The full product index (catalogue + the shop's sale stock) for the three-moment cases.
IDX = PRD.index()
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
WORDING = "Wording stays at \"during this trial\""
NOTHING = "No exclusions recorded: nothing to check, never a pass"
LLM_DOWN = "LLM down or draft rejected: templates shown, core flow unaffected"
LLM_VALIDATOR = "LLM draft overclaims (\"caused by\" etc.): validator rejects it"
LLM_INTAKE = "LLM intake proposes; the user confirms"
POSITIVE = "Positive persona: a comparable move beyond noise, judged by the real engine"
REBUY = "Rebuy line follows the verdict"
UPLOAD = "Uploaded photos: same checks as the camera, honest baselines, no GPS"

# The three moments (docs/STRATEGY.md section 4). New rows; none of the above changes.
SEPARATE = "Irritation and breakout never share a suspect list"
CONTRAST = "Contrast decides: suited products clear, one failed product can't narrow"
MATCHING = "Synonyms and families match, exact first"
CART_LADDER = "Cart check: the verdict ladder, in order"
CART_SOURCES = "Cart check: three labelled sources, change nothing, one next step"
TRIAGE = "Breakout triage: the window, purging, usual spots, one next step"
LOOP = "The verdict is written back, and never upgrades a can't-tell"
PERSONA = "The demo personas produce the expected outcomes, from the real engines"

CATEGORIES = [EXCLUSION, SYNONYM, INCOMPLETE, NOTHING, REACTION, ADD_REPLACE, SEVERAL, OVERLAP,
              NOT_COMPARABLE, SYMPTOMS, PERSISTS, NO_BASELINE, WORDING, POSITIVE, REBUY, UPLOAD,
              LLM_DOWN, LLM_VALIDATOR, LLM_INTAKE,
              SEPARATE, CONTRAST, MATCHING, CART_LADDER, CART_SOURCES, TRIAGE, LOOP, PERSONA]

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
        os.environ["DEMO_MODE"] = "0"   # "live" here is the fake below
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


# ---------------------------------------------------------------- guided-demo scenes (app/scenes.py)
def api_scene(name: str, symptoms: tuple = (), other_new: tuple = ()) -> dict:
    """Build a prepared scene through the real app, optionally log a check-in, return /evidence."""
    with api() as c:
        import app.main as m
        tid = m.build_scene(name)["trial_id"]
        if symptoms or other_new:
            c.post(f"/api/trials/{tid}/checkin", json={"symptoms": list(symptoms), "other_new_leave_on": list(other_new)})
        return c.get(f"/api/trials/{tid}/evidence").json()


def meera_caps(lamp_checkin: bool = False) -> tuple[list, list]:
    """Meera's recorded scores as engine captures; optionally her check-ins under the warm-lamp conditions."""
    from app import demo, scenes
    out = []
    for fset, n in (("baseline", 3), ("checkin", 2)):
        caps_ = []
        for i in range(n):
            rp = demo.pick("meera", fset, i)
            fp_ = scenes.fingerprint_for(rp, "lamp" if (lamp_checkin and fset == "checkin") else fset, i)
            caps_.append(E.Capture(rp.result.raw_scores(), Fingerprint.from_dict(fp_), rp.result.mode,
                                   tuple(rp.result.actions)))
        out.append(caps_)
    return out[0], out[1]


def scene_source_mentions_verdicts() -> list[str]:
    """Names in app/scenes.py's code (not its docstrings) that could set or fake a verdict: identifiers,
    attributes, imported modules and dict keys. Should be none."""
    import ast
    from pathlib import Path
    tree = ast.parse((Path(E.__file__).parent / "scenes.py").read_text(encoding="utf-8"))
    banned = {"Verdict", "evaluate", "verdict", "compare_conditions", "beyond_noise", "MOVED", "evidence",
              "report", "comparable"}
    seen = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            seen.add(node.id)
        elif isinstance(node, ast.Attribute):
            seen.add(node.attr)
        elif isinstance(node, ast.alias):
            seen.update(node.name.split("."))
        elif isinstance(node, ast.ImportFrom) and node.module:
            seen.update(node.module.split("."))
        elif isinstance(node, ast.Dict):
            seen.update(k.value for k in node.keys if isinstance(k, ast.Constant) and isinstance(k.value, str))
    return sorted(seen & banned)


def rebuy(base, follow, new=1, symptoms=()) -> str:
    return report(base, follow, new, symptoms).rebuy


V = E.Verdict

# ---------------------------------------------------------------- the cases
# ---------------------------------------------------------------- uploaded photos
def _photo(color=(200, 160, 140), when: str | None = None, gps: bool = False) -> bytes:
    """A plain test photo with optional EXIF time and GPS. A corner mark sized by the colour keeps
    near-identical colours apart after JPEG compression (outside the face crop)."""
    from PIL import Image, ImageDraw
    e = Image.Exif()
    if when:
        e[0x0132] = when
        e.get_ifd(0x8769)[0x9003] = when
    if gps:
        e.get_ifd(0x8825).update({1: "N", 2: (12.0, 34.0, 56.789), 3: "E", 4: (76.0, 54.0, 32.1)})
    img = Image.new("RGB", (720, 960), color)
    side = 8 + (color[0] * 7 + color[1] * 3 + color[2]) % 50
    ImageDraw.Draw(img).rectangle((0, 0, side, side), fill=(0, 0, 0))
    b = io.BytesIO()
    img.save(b, "JPEG", exif=e)
    return b.getvalue()


WINDOW3 = [((200, 160, 140), "2026:10:28 09:00:00"), ((201, 160, 140), "2026:10:28 09:03:00"),
           ((199, 161, 140), "2026:10:28 09:06:00")]


def _files(blobs):
    return [("images", (f"p{i}.jpg", b, "image/jpeg")) for i, b in enumerate(blobs)]


def upload_check(blobs: list[bytes], phase: str = "baseline", **data) -> dict:
    """POST /api/upload/precheck on the real app (free: no YouCam call, nothing stored)."""
    with api() as c:
        return c.post("/api/upload/precheck", files=_files(blobs), data={"phase": phase, **data}).json()


def gate_parity(color) -> tuple[bool, bool]:
    """Same pixels sent as a camera check-in and as an uploaded check-in, against one baseline.
    Returns (identical gate results, comparable)."""
    with api([60, 61, 62, 63]) as c:
        tid = c.post("/api/trials", json={"goal_concern": "redness", "product_id": "sr-01"}).json()["id"]
        c.post("/api/upload/scan", files=_files([_photo(col, t) for col, t in WINDOW3]),
               data={"phase": "baseline", "trial_id": tid, "actions": "redness"})
        shot = _photo(color, "2026:10:28 09:10:00")
        other = _photo((color[0] - 1, color[1], color[2]), "2026:10:28 09:11:00")
        pre = c.post("/api/upload/precheck", files=_files([shot, other]),
                     data={"phase": "checkin", "trial_id": tid, "actions": "redness"}).json()
        cam = c.post("/api/scan", files={"image": ("c.jpg", shot, "image/jpeg")},
                     data={"actions": "redness", "trial_id": tid, "phase": "checkin"}).json()
        return pre["comparability"][0] == cam["comparability"], cam["comparability"]["comparable"]


def gps_stored() -> bool:
    """Scan 3 uploaded photos that carry GPS; is any GPS value in the stored records?"""
    import sqlite3
    with api([60, 61, 62]) as c:
        r = c.post("/api/upload/scan", files=_files([_photo(col, t, gps=True) for col, t in WINDOW3]),
                   data={"phase": "baseline", "actions": "redness"})
        assert r.status_code == 200, r.text
        with sqlite3.connect(os.environ["DERMOS_DB"]) as con:
            dump = "\n".join(row[0] for row in con.execute("SELECT body FROM captures"))
    return "56.789" in dump or "gps" in dump.lower()


# ---------------------------------------------------------------- the three moments
# Riya's recorded story, as rows. Everything asserted below is worked out from these by the real
# engines; no expected value here is copied from engine output.
def o(pid: str, outcome: str, weeks: int | None = None, **kw) -> OC.ProductOutcome:
    return OC.ProductOutcome(product_id=pid, outcome=outcome, leave_on=IDX[pid].leave_on,
                             weeks_used_given=weeks, **kw)


RIYA_OUT = [
    o("sr-02", "irritation", 2),
    o("tn-03", "irritation", 3),
    o("sr-05", "breakout", 8, zones=["chin"], usual_spots=True,
      settled_while_using=True, settled_week=5),
    o("es-01", "suited", 12),
    o("mo-03", "suited", 20),
]
RIYA_RECS = [D.HistoryRecord(D.RecordType.SUSPECTED_REACTION, product_id="mo-02"),
             D.HistoryRecord(D.RecordType.AVOID, ingredient="fragrance")]
# Her baseline fixture means. raw_score is higher for healthier skin, so the lowest are her
# concerns: oiliness, then pores, then texture.
RIYA_SCORES = {"redness": 62.1, "texture": 58.6, "acne": 72.2, "pore": 55.2,
               "oiliness": 48.1, "moisture": 63.2}
RIYA_SHELF = ["cl-01", "sr-01", "mo-03", "sp-01"]


# A fictional product whose only match with her history is a fragrance-family cross-reactor she
# has never chosen to avoid by name. It is the clean test of "family match ranks one rung softer":
# citral is in the fragrance family but is not one of the components her "avoid fragrance" record
# expands to, so nothing blocks it.
CITRAL = D.Product("x-01", "Test Serum", "Nimbus Skin", "serum", True, 500, ["Aqua", "Citral"], True)
IDX_X = {**IDX, "x-01": CITRAL}


def cart_citral() -> CC.CartCheck:
    return CC.check(CITRAL, RIYA_RECS, RIYA_OUT, IDX_X, RIYA_SCORES, RIYA_SHELF)


def pat(kind: str, rows=None) -> PA.PatternReport:
    return PA.analyse(kind, RIYA_OUT if rows is None else rows, IDX)


def tier_of(kind: str, ingredient: str, rows=None, match: str = "exact") -> str | None:
    for s in pat(kind, rows).suspects:
        if s.ingredient == ingredient and s.match_type == match:
            return s.tier
    return None


def top_suspect(kind: str, rows=None) -> tuple:
    r = pat(kind, rows)
    t = r.top()
    return (None, None, None) if t is None else (t.ingredient, t.match_type, t.tier)


def cart(pid: str, scores=RIYA_SCORES, rows=None, recs=None) -> CC.CartCheck:
    rows = RIYA_OUT if rows is None else rows
    return CC.check(IDX[pid], RIYA_RECS if recs is None else recs, rows, IDX, scores, RIYA_SHELF)


def cart_src(pid: str, key: str, **kw) -> list[str]:
    return next(s for s in cart(pid, **kw).sources if s.key == key).lines


def triage_of(**kw) -> TR.Triage:
    from datetime import date, timedelta
    today = date(2026, 10, 31)
    ago = lambda w: (today - timedelta(weeks=w)).isoformat()  # noqa: E731
    kw.setdefault("using", [{"product_id": "cl-01", "started_on": ago(30)},
                            {"product_id": "es-01", "started_on": ago(12)},
                            {"product_id": "mo-03", "started_on": ago(20)},
                            {"product_id": "sp-01", "started_on": ago(4)}])
    kw.setdefault("symptoms", [])
    kw.setdefault("zones", ["cheeks"])
    kw.setdefault("usual_spots", False)
    return TR.assess(catalog=IDX, today=today, **kw)


def wb_of(verdict: str, direction: str = "better", weeks: int = 12, symptoms=()) -> str:
    from datetime import date, timedelta
    today = date(2026, 10, 31)
    rep = {"verdict": verdict, "symptoms": list(symptoms),
           "findings": [{"concern": "pore", "direction": direction, "beyond_noise": True,
                         "baseline": None, "followup": None, "delta_mid": 1.0}]}
    return WBK.plan(rep, "sr-09", True, (today - timedelta(weeks=weeks)).isoformat(),
                    goal_concern="pore", trial_id="t", today=today).outcome.outcome


def scene_patterns(name: str, kind: str) -> dict:
    """Load a demo scene through the real app and read the pattern run it produces."""
    with api() as c:
        import app.main as m
        m.build_scene(name)
        return c.get("/api/patterns").json()[kind]


def scene_cart(name: str, pid: str) -> dict:
    with api() as c:
        import app.main as m
        m.build_scene(name)
        return c.post("/api/cartcheck", json={"product_id": pid}).json()


def scene_cart_no_scan(pid: str) -> list[str]:
    with api() as c:
        import app.main as m
        m.build_scene("riya-store")
        res = c.post("/api/cartcheck", json={"product_id": pid, "use_scan": False}).json()
        return next(s for s in res["sources"] if s["key"] == "skin")["lines"]


def scene_writeback(name: str) -> tuple:
    with api() as c:
        import app.main as m
        tid = m.build_scene(name)["trial_id"]
        wb = c.post(f"/api/trials/{tid}/writeback").json()
        rows = c.get("/api/outcomes").json()
        return wb["outcome"]["outcome"], [r["product_id"] for r in rows]


def scene_writeback_cant_tell() -> tuple:
    """A trial whose verdict is a can't-tell: the write-back must not make it "suited"."""
    with api([60.0, 61.0, 62.0, 63.0]) as c:
        t = c.post("/api/trials", json={"goal_concern": "pore", "product_id": "sr-09"}).json()
        for _ in range(3):
            _scan(c, t["id"], "baseline")
        _scan(c, t["id"], "checkin")        # one check-in only: no comparable pair
        ev = c.get(f"/api/trials/{t['id']}/evidence").json()
        wb = c.post(f"/api/trials/{t['id']}/writeback").json()
        return ev["report"]["verdict"], wb["outcome"]["outcome"]


def _fp_ev(ev: float | None) -> Fingerprint:
    """A fingerprint that matches on everything the gate measures except the metered exposure."""
    f = fp()
    f.exposure_ev = ev
    return f


def _beginner_blank() -> tuple:
    """The beginner scene must clear a full story: no outcomes, no shelf, no trial."""
    with api() as c:
        import app.main as m
        m.build_scene("riya-store")
        tid = m.build_scene("beginner")["trial_id"]
        return (c.get("/api/outcomes").json(), c.get("/api/shelf").json()["product_ids"], tid)


def _beginner_plan() -> dict:
    with api() as c:
        import app.main as m
        answers = m.build_scene("beginner")["situation"]["answers"]
        return c.post("/api/beginner/plan", json={"answers": answers}).json()


def _beginner_type() -> tuple:
    st = _beginner_plan()["skin_type"]
    return (st["value"], st["source"], st["label"])


def _beginner_starter() -> tuple:
    steps = _beginner_plan()["steps"]
    return ([s["role"] for s in steps], [s["check"]["rule_version"] for s in steps])


def _scene_rows_have_no_verdicts() -> list[str]:
    """A scene writes rows; the engines judge. So no judgement word may appear in what it stored.
    Returns the offending words, so the expected value is an empty list."""
    import json as _json
    with api() as c:
        import app.main as m
        m.build_scene("riya-store")
        stored = _json.dumps(c.get("/api/outcomes").json()).lower()
    return [w for w in ("suspect", "lead", "verdict", "repeats a pattern", "no conflicts",
                        "patch-test", "purge") if w in stored]


def one_next_step_everywhere() -> list[str]:
    """Every result the three moments produce must carry exactly one next step. Returns the
    offenders, so the expected value is an empty list."""
    bad = []
    for pid in ("mo-02", "sr-08", "mo-07", "sr-09", "sp-04", "tr-01"):
        ns = cart(pid).next_step
        if not ns or "\n" in ns:
            bad.append(f"cartcheck:{pid}")
    for kw in ({}, {"symptoms": ["itching"]}, {"usual_spots": True}, {"using": []}):
        ns = triage_of(**kw).next_step
        if not ns or "\n" in ns:
            bad.append(f"triage:{kw}")
    return bad


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
    Case("wd-02", WORDING, "Strongest result says 'during this trial' and that it can't show the product was the reason",
         (True, True),
         lambda: (lambda m: ("during this trial" in m, E.MOVED_CAVEAT in m))(report(caps(60, 62), caps(70, 71)).message)),
    # Positive persona (prepared fixtures; the gate and verdict run as for any trial)
    Case("pos-01", POSITIVE, "Meera: comparable check-ins leave her redness range", V.MOVED.value,
         lambda: api_scene("meera")["report"]["verdict"]),
    Case("pos-02", POSITIVE, "The pair passed the gate on light, face size, head pose, time and device",
         (True, ["device", "face_size", "head_pose", "lighting", "mode", "time_of_day"]),
         lambda: (lambda c: (c["comparable"], sorted(c["checked"])))(api_scene("meera")["report"]["comparability"])),
    Case("pos-03", POSITIVE, "Wording: 'dropped beyond your usual variation during this trial', plus the caveat",
         "Redness dropped beyond your usual variation during this trial. " + E.MOVED_CAVEAT,
         lambda: api_scene("meera")["report"]["message"]),
    Case("pos-04", POSITIVE, "Same scores, check-ins under a warm lamp: not comparable (no special-casing)",
         V.NOT_COMPARABLE.value,
         lambda: E.evaluate(*meera_caps(lamp_checkin=True), E.TrialContext(), concerns=["redness"]).verdict.value),
    Case("pos-05", POSITIVE, "Itching logged at her check-in: Stop outranks the better scores", V.STOP_REACTION.value,
         lambda: api_scene("meera", symptoms=("itching",))["report"]["verdict"]),
    Case("pos-06", POSITIVE, "Another new leave-on product logged: can't tell which", V.SEVERAL_CHANGES.value,
         lambda: api_scene("meera", other_new=("sr-04",))["report"]["verdict"]),
    Case("pos-07", POSITIVE, "Every scan in the scene is labelled prepared data", (5, {"replay"}),
         lambda: (lambda s: (len(s), {c["source"] for c in s}))(api_scene("meera")["series"])),
    Case("pos-08", POSITIVE, "The scene builder never names a verdict, the gate or the engine", [],
         scene_source_mentions_verdicts),
    # Rebuy line
    Case("rb-01", REBUY, "Moved beyond noise, better", E.REBUY["supports"], lambda: rebuy(caps(60, 62), caps(70, 71))),
    Case("rb-02", REBUY, "No detectable change", E.REBUY["finish"], lambda: rebuy(caps(60, 64), caps(62, 63))),
    Case("rb-03", REBUY, "Not comparable", E.REBUY["cant_tell"], lambda: rebuy(caps(60, 62), caps(70, 71, lum=0.3))),
    Case("rb-04", REBUY, "Several changes, even with better scores", E.REBUY["cant_tell"],
         lambda: rebuy(caps(60, 62), caps(70, 71), new=2)),
    Case("rb-05", REBUY, "No baseline", E.REBUY["cant_tell"], lambda: rebuy(caps(60), caps(70, 71))),
    Case("rb-06", REBUY, "Itching with better scores: don't rebuy", E.REBUY["stop"],
         lambda: rebuy(caps(60, 62), caps(75, 76), symptoms=["itching"])),
    Case("rb-07", REBUY, "Moved beyond noise, worse: never 'supports rebuying'", E.REBUY["moved_worse"],
         lambda: rebuy(caps(70, 71), caps(60, 62))),
    Case("rb-08", REBUY, "API: Meera supports; Riya lamp / day 14 / itching = can't tell / finish / don't rebuy",
         (E.REBUY["supports"], E.REBUY["cant_tell"], E.REBUY["finish"], E.REBUY["stop"]),
         lambda: tuple(api_scene(n)["report"]["rebuy"] for n in ("meera", "riya-lamp", "riya-day14", "riya-stop"))),
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
    # Uploaded photos
    Case("up-01", UPLOAD, "Baseline with two pixel-identical photos (their metadata differs)",
         (False, "duplicate"),
         lambda: (lambda r: (r["ok"], r["code"]))(upload_check(
             [_photo(*WINDOW3[0]), _photo(WINDOW3[0][0], "2026:10:28 09:04:00"), _photo(*WINDOW3[2])]))),
    Case("up-02", UPLOAD, "Baseline photo times spread over 30 minutes", (False, "spread"),
         lambda: (lambda r: (r["ok"], r["code"]))(upload_check(
             [_photo(*WINDOW3[0]), _photo(*WINDOW3[1]), _photo((198, 160, 141), "2026:10:28 09:30:00")]))),
    Case("up-03", UPLOAD, "A baseline photo has no capture time: ask, don't assume",
         (False, "confirm_sitting", True),
         lambda: (lambda r: (r["ok"], r["code"], r["needs_confirmation"]))(upload_check(
             [_photo(*WINDOW3[0]), _photo(*WINDOW3[1]), _photo((198, 162, 140))]))),
    Case("up-04", UPLOAD, "...and the user says yes: stored as user-confirmed", (True, "user-confirmed"),
         lambda: (lambda r: (r["ok"], r["timing"]))(upload_check(
             [_photo(*WINDOW3[0]), _photo(*WINDOW3[1]), _photo((198, 162, 140))], same_sitting="true"))),
    Case("up-05", UPLOAD, "Same pixels by camera and by upload, warm lamp vs window baseline: same gate result",
         (True, False), lambda: gate_parity((240, 150, 60))),
    Case("up-06", UPLOAD, "Same pixels by camera and by upload, same window light: same gate result",
         (True, True), lambda: gate_parity((200, 160, 140))),
    Case("up-07", UPLOAD, "Uploaded photos carry GPS: none of it is stored", False, gps_stored),
    Case("up-08", UPLOAD, "Upload over 15 MB is refused before decoding", "too_big",
         lambda: upload_check([b"\xff\xd8\xff" + b"0" * (15 * 1024 * 1024), _photo(*WINDOW3[1]),
                               _photo(*WINDOW3[2])])["code"]),

    # ---- EXIF exposure in the gate (B12): additional and stricter only.
    Case("nc-13", NOT_COMPARABLE, "Camera metered 4 stops of difference: not comparable, even though "
         "the photos look equally bright", (True, False),
         lambda: (lambda b, f: (
             E.compare_conditions(b, f, tol={**E.TOLERANCES, "exposure_ev": 99}).comparable,
             E.compare_conditions(b, f).comparable))(
             [E.Capture({"redness": 60.0}, _fp_ev(9.0), "sd", ("redness",))] * 2,
             [E.Capture({"redness": 60.0}, _fp_ev(5.0), "sd", ("redness",))] * 2)),
    Case("nc-14", NOT_COMPARABLE, "No exposure recorded on either side: not a failure, and not "
         "counted as a matching field either", (True, False),
         lambda: (lambda c: (c.comparable, "exposure" in c.checked))(
             E.compare_conditions([E.Capture({"redness": 60.0}, _fp_ev(None), "sd", ("redness",))] * 2,
                                  [E.Capture({"redness": 60.0}, _fp_ev(None), "sd", ("redness",))] * 2))),

    # ---------------------------------------------------------------- reaction types kept apart
    Case("sep-01", SEPARATE, "Her irritation suspect (a drying alcohol) is not in the breakout run",
         (True, False),
         lambda: ("alcohol denat" in [s.ingredient for s in pat("irritation").suspects],
                  "alcohol denat" in [s.ingredient for s in pat("breakout").suspects])),
    Case("sep-02", SEPARATE, "The irritation run's failure set is only the products that itched",
         ["sr-02", "tn-03"],
         lambda: [p["product_id"] for p in pat("irritation").failed_products]),
    Case("sep-03", SEPARATE, "The breakout run's failure set is only the product that broke her out",
         ["sr-05"], lambda: [p["product_id"] for p in pat("breakout").failed_products]),
    Case("sep-04", SEPARATE, "Azelaic acid is a breakout candidate and never an irritation one",
         (None, True),
         lambda: (tier_of("irritation", "azelaic acid"),
                  any(x["ingredient"] == "azelaic acid" for x in pat("breakout").only_in_failed))),
    Case("sep-05", SEPARATE, "A cleanser that stings is NOT down-weighted (only breakouts are)",
         (1.0, 0.5),
         lambda: (max(a.weight for s in pat("irritation", [o("cl-02", "irritation", 6),
                                                           o("sr-05", "irritation", 8)]).suspects
                      for a in s.in_failed if a.product_id == "cl-02"),
                  max(a.weight for s in pat("breakout", [o("cl-02", "breakout", 6),
                                                         o("sr-05", "breakout", 8)]).suspects
                      for a in s.in_failed if a.product_id == "cl-02"))),

    # ---------------------------------------------------------------- contrast
    Case("con-01", CONTRAST, "In 2 of 2 products that itched and 0 that suited: a suspect",
         ("alcohol denat", "exact", "suspect"), lambda: top_suspect("irritation")),
    Case("con-02", CONTRAST, "The counts read 'in 2 of 2 ... 0 of 2 that suited you'",
         "in 2 of 2 products that made you itch, sting or burn, 0 of 2 that suited you",
         lambda: pat("irritation").top().counts_line()),
    Case("con-03", CONTRAST, "An ingredient that is also in a suited product is cleared, never a suspect",
         "cleared_so_far", lambda: tier_of("irritation", "phenoxyethanol")),
    Case("con-04", CONTRAST, "In 1 failed product of 2 and 0 suited: a lead, not a suspect",
         "lead", lambda: tier_of("irritation", "ferulic acid")),
    Case("con-05", CONTRAST, "A 2-week 'suited' product clears nothing: the shared alcohol is still a suspect",
         ("suspect", "lead"),
         lambda: (lambda rows: (tier_of("irritation", "alcohol denat", rows),
                                tier_of("irritation", "linalool", rows)))(
             [o("sr-02", "irritation", 2), o("tn-03", "irritation", 3), o("mo-02", "suited", 2)])),
    Case("con-06", CONTRAST, "The same product at 4 weeks does clear it", "cleared_so_far",
         lambda: tier_of("irritation", "linalool",
                         [o("sr-02", "irritation", 2), o("tn-03", "irritation", 3),
                          o("mo-02", "suited", 4)])),
    Case("con-07", CONTRAST, "A 2-week 'suited' outcome reads as too early to say", "too_early",
         lambda: o("mo-02", "suited", 2).effective_outcome()),
    Case("con-08", CONTRAST, "One failed product: says plainly it can't narrow down which ingredient",
         "One product can't tell us which of its 6 ingredients did it. It takes a second product "
         "with the same problem, and ones that suited you, to narrow down.",
         lambda: pat("breakout").cannot_narrow),
    Case("con-09", CONTRAST, "One failed product names no suspects and no leads at all", [],
         lambda: [s.ingredient for s in pat("breakout").suspects
                  if s.tier in ("suspect", "lead")]),
    Case("con-10", CONTRAST, "One failed product lists only what is in nothing that suited her",
         (True, False, False),
         lambda: (lambda names: ("Azelaic Acid" in names, "Aqua" in names, "Glycerin" in names))(
             [x["display"] for x in pat("breakout").only_in_failed])),

    # ---------------------------------------------------------------- synonyms and families
    Case("mat-01", MATCHING, "'Parfum (Fragrance)' and 'Fragrance' count as one ingredient: a suspect",
         "suspect", lambda: tier_of("irritation", "fragrance",
                                    [o("sr-02", "irritation", 2), o("tn-02", "irritation", 2),
                                     o("es-01", "suited", 12)])),
    Case("mat-02", MATCHING, "...and the synonym match names both products", {"sr-02", "tn-02"},
         lambda: {a.product_id for s in pat("irritation",
                                            [o("sr-02", "irritation", 2), o("tn-02", "irritation", 2),
                                             o("es-01", "suited", 12)]).suspects
                  if s.ingredient == "fragrance" and s.match_type == "exact"
                  for a in s.in_failed}),
    Case("mat-03", MATCHING, "The fragrance FAMILY is matched across differently-named components",
         "suspect", lambda: tier_of("irritation", "fragrance", match="family")),
    Case("mat-04", MATCHING, "An exact match ranks above a family match of the same tier",
         ("alcohol denat", "exact"),
         lambda: (lambda s: (s.ingredient, s.match_type))(
             [x for x in pat("irritation").suspects if x.tier == "suspect"][0])),
    Case("mat-05", MATCHING, "A cross-reactor with no exact history is a family match, so patch-test",
         ("patch_test_first", "family"),
         lambda: (lambda r: (r.rung, next(m["match_type"] for m in
                                          next(s for s in r.sources if s.key == "history")
                                          .detail["matches"])))(cart_citral())),
    Case("mat-06", MATCHING, "A fatty alcohol is not in the drying-alcohol family", ([], ["drying alcohols"]),
         lambda: (PA.FAM.family_of("Cetearyl Alcohol"), PA.FAM.family_of("Alcohol Denat."))),
    Case("mat-07", MATCHING, "Every ingredient family and the purge list are versioned data",
         ("families-1.0", "patterns-1.0"),
         lambda: (pat("irritation").families_version, pat("irritation").rule_version)),

    # ---------------------------------------------------------------- the cart-check ladder
    Case("cl-01b", CART_LADDER, "The ladder is Blocked, Repeats a pattern, Patch-test first, No conflicts",
         ["blocked", "repeats_a_pattern", "patch_test_first", "no_conflicts"],
         lambda: [r.value for r in CC.LADDER]),
    Case("cl-02b", CART_LADDER, "Blocked wins: she avoids fragrance and it lists Parfum", "blocked",
         lambda: cart("mo-02").rung),
    Case("cl-03b", CART_LADDER, "Repeats a pattern: it lists her exact irritation suspect",
         ("repeats_a_pattern", "Repeats a pattern"),
         lambda: (cart("sr-08").rung, cart("sr-08").verdict_line)),
    Case("cl-04b", CART_LADDER, "Patch-test first: it lists a lead", "patch_test_first",
         lambda: cart("tr-01").rung),
    Case("cl-05b", CART_LADDER, "No conflicts with your history: nothing of hers matched",
         ("no_conflicts", "No conflicts with your history"),
         lambda: (cart("sr-09").rung, cart("sr-09").verdict_line)),
    Case("cl-06b", CART_LADDER, "The bottom rung is never worded as 'safe'", False,
         lambda: "safe" in " ".join([cart("sr-09").verdict_line, cart("sr-09").next_step]
                                    + cart_src("sr-09", "history")).lower()),
    Case("cl-07b", CART_LADDER, "Incomplete INCI can never read as no conflicts: it reads unknown",
         (True, "Ingredient list incomplete → unknown"),
         lambda: (cart("mo-07").unknown, cart("mo-07").verdict_line)),
    Case("cl-08b", CART_LADDER, "A stronger rung still stands on an incomplete label, and carries the tag",
         ("blocked", True, False),
         lambda: (lambda r: (r.rung, CC.UNKNOWN_TAG in r.tags, r.unknown))(
             cart("cl-04", recs=[D.HistoryRecord(D.RecordType.AVOID, ingredient="niacinamide")]))),
    Case("cl-09b", CART_LADDER, "A complete label is never tagged incomplete", ([], False),
         lambda: (cart("sr-09").tags, cart("sr-09").unknown)),
    Case("cl-10b", CART_LADDER, "A family-level suspect is one rung softer than an exact one",
         ("repeats_a_pattern", "patch_test_first"),
         lambda: (cart("sr-08").rung,                      # lists Alcohol Denat. by name
                  cart_citral().rung)),                    # fragrance family only

    # ---------------------------------------------------------------- the three sources
    Case("cs-01", CART_SOURCES, "Exactly three sources, labelled from history, skin and shelf",
         ["From your history", "From your skin (YouCam)", "From your shelf"],
         lambda: [s.label for s in cart("sr-09").sources]),
    Case("cs-02", CART_SOURCES, "With no scan, the skin source says to scan first",
         ["No scan yet: scan to see if this is aimed at your skin's top concerns."],
         lambda: cart_src("sr-09", "skin", scores=None)),
    Case("cs-03", CART_SOURCES, "Through the API with no scan, the same line is shown",
         ["No scan yet: scan to see if this is aimed at your skin's top concerns."],
         lambda: scene_cart_no_scan("sr-09")),
    Case("cs-04", CART_SOURCES, "No scan does not change the verdict rung", ("no_conflicts", "no_conflicts"),
         lambda: (cart("sr-09", scores=None).rung, cart("sr-09").rung)),
    Case("cs-05", CART_SOURCES, "Aimed at names a measured top concern, and says which",
         "Aimed at pores. Pores is your 2nd lowest YouCam score of the 3 we measured.",
         lambda: cart_src("sr-09", "skin")[0]),
    Case("cs-06", CART_SOURCES, "Her lowest measured score is named as the lowest",
         "Aimed at oiliness and pores. Oiliness is your lowest YouCam score of the 3 we measured.",
         lambda: cart_src("sp-04", "skin")[0]),
    Case("cs-07", CART_SOURCES, "Not aimed at a top concern is said plainly",
         "Not aimed at any of your top 3 measured concerns (oiliness, pores and texture).",
         lambda: cart_src("sr-08", "skin")[0]),
    Case("cs-08", CART_SOURCES, "The skin source says 'aimed at' and never that it fixes anything",
         False,
         lambda: any(w in " ".join(cart_src(p, "skin")).lower()
                     for p in ("sr-09", "sp-04", "sr-08") for w in ("fixes", "treats", "cures"))),
    Case("cs-09", CART_SOURCES, "The shelf source names the duplicate and the new spend",
         (True, "New spend if you buy it: ₹1,290."),
         lambda: (lambda l: ("10% Niacinamide Serum" in l[0], l[1]))(cart_src("sr-09", "shelf"))),
    Case("cs-10", CART_SOURCES, "Change nothing is always one of the options", [],
         lambda: [p for p in ("mo-02", "sr-08", "mo-07", "sr-09", "sp-04", "tr-01")
                  if not cart(p).change_nothing.startswith("Change nothing.")]),
    Case("cs-11", CART_SOURCES, "Exactly one next step on every cart check and every triage", [],
         one_next_step_everywhere),
    Case("cs-12", CART_SOURCES, "Each rung has its own next step", 3,
         lambda: len({cart(p).next_step for p in ("mo-02", "sr-08", "sr-09")})),
    Case("cs-13", CART_SOURCES, "Every result stores its inputs and its rule versions",
         ("cartcheck-1.0", "decision-1.0", "patterns-1.0", "families-1.0"),
         lambda: (lambda v: (v["cartcheck"], v["decision"], v["patterns"], v["families"]))(
             cart("sr-09").inputs["rule_versions"])),
    Case("cs-14", CART_SOURCES, "General knowledge is kept under its own key, out of the counts line",
         (True, False),
         lambda: (any("often reported" in n for n in
                      next(s for s in cart("sr-08").sources if s.key == "history")
                      .detail["general_knowledge"]),
                  any("often reported" in ln for ln in cart_src("sr-08", "history")))),

    # ---------------------------------------------------------------- breakout triage
    Case("tg-01", TRIAGE, "The product started inside the 2-8 week window is the top lead",
         ("sp-01", True), lambda: (lambda c: (c.product_id, c.in_window))(triage_of().lead())),
    Case("tg-02", TRIAGE, "A leave-on in the window ranks above a wash-off in the window",
         ["sp-01", "cl-02"],
         lambda: [c.product_id for c in triage_of(using=[
             {"product_id": "cl-02", "started_on": "2026-10-03"},
             {"product_id": "sp-01", "started_on": "2026-10-03"}]).candidates]),
    Case("tg-03", TRIAGE, "A product used 12 weeks without trouble ranks lowest, with the reason",
         (True, True),
         lambda: (lambda c: (c.tier == TR.TIER_LONG_USE,
                             "used this for 12 weeks without this problem" in c.reason))(
             next(c for c in triage_of().candidates if c.product_id == "es-01"))),
    Case("tg-04", TRIAGE, "...and it is never excluded from the list",
         {"sp-01", "es-01", "mo-03", "cl-01"},
         lambda: {c.product_id for c in triage_of().candidates}),
    Case("tg-05", TRIAGE, "The long-use reason says it is not a clean bill", True,
         lambda: "not a clean bill" in next(
             c for c in triage_of().candidates if c.product_id == "es-01").reason),
    Case("tg-06", TRIAGE, "Something started a week ago ranks below the window", TR.TIER_TOO_RECENT_LEAVE_ON,
         lambda: next(c for c in triage_of(using=[
             {"product_id": "sp-01", "started_on": "2026-10-03"},
             {"product_id": "sr-06", "started_on": "2026-10-24"}]).candidates
             if c.product_id == "sr-06").tier),
    Case("tg-07", TRIAGE, "No purge without a turnover ingredient, and it says why",
         (False, True),
         lambda: (triage_of().purge.possible,
                  "no ingredient that speeds up cell turnover" in triage_of().purge.line)),
    Case("tg-08", TRIAGE, "A turnover ingredient plus her usual spots plus settling: purge-consistent",
         (True, True),
         lambda: (lambda p: (p.possible, p.consistent))(triage_of(
             using=[{"product_id": "tr-01", "started_on": "2026-09-26"}], zones=["chin"],
             usual_spots=True, settled_while_using=True, settled_week=5).purge)),
    Case("tg-09", TRIAGE, "The same turnover ingredient, but spots in a NEW area: not a purge",
         (True, False),
         lambda: (lambda p: (p.possible, p.consistent))(triage_of(
             using=[{"product_id": "tr-01", "started_on": "2026-09-26"}], zones=["cheeks"],
             usual_spots=False, settled_while_using=True, settled_week=5).purge)),
    Case("tg-10", TRIAGE, "A new area is said to point away from purging", True,
         lambda: "points away from purging" in triage_of().zones.line),
    Case("tg-11", TRIAGE, "Usual spots are said to be where purging shows up", True,
         lambda: "usual spots, which is where purging shows up" in triage_of(
             zones=["chin"], usual_spots=True).zones.line),
    Case("tg-12", TRIAGE, "Settling later than ~6 weeks is not purge-consistent", False,
         lambda: triage_of(using=[{"product_id": "tr-01", "started_on": "2026-08-22"}],
                           zones=["chin"], usual_spots=True, settled_while_using=True,
                           settled_week=9).purge.consistent),
    Case("tg-13", TRIAGE, "Symptoms outrank the whole ranking: stop wins",
         (True, "stop_card"),
         lambda: (lambda t: (t.stop, t.next_action["kind"]))(triage_of(symptoms=["itching"]))),
    Case("tg-14", TRIAGE, "The stop next step opens the visit brief, not a trial", True,
         lambda: "visit brief" in triage_of(symptoms=["burning"]).next_step),
    Case("tg-15", TRIAGE, "A mild symptom is not a stop", (False, "open_trial"),
         lambda: (lambda t: (t.stop, t.next_action["kind"]))(triage_of(symptoms=["dryness"]))),
    Case("tg-16", TRIAGE, "One next step: pause one leave-on product and hold the rest",
         ("sp-01", {"cl-01", "es-01", "mo-03"}, 14),
         lambda: (lambda a: (a["pause_product_id"], set(a["hold_fixed"]), a["checkpoint_days"]))(
             triage_of().next_action)),
    Case("tg-17", TRIAGE, "Zone shares come from masks when there are numbers, and say so",
         ("masks", True),
         lambda: (lambda z: (z.source, "62% of it" in z.line))(triage_of(
             shares={"cheeks": 0.62, "forehead": 0.2, "chin": 0.18},
             baseline_shares={"cheeks": 0.11, "forehead": 0.46, "chin": 0.43}).zones)),
    Case("tg-18", TRIAGE, "With no mask numbers it uses the tapped zones and says which it used",
         ("tapped", True),
         lambda: (lambda z: (z.source, "No per-zone mask numbers were available"
                             in z.to_dict()["source_note"]))(triage_of().zones)),

    # ---------------------------------------------------------------- the loop closes
    Case("lp-01", LOOP, "A comparable move in the good direction after 4 weeks writes 'suited'",
         "suited", lambda: wb_of(E.Verdict.MOVED.value)),
    Case("lp-02", LOOP, "The same move under 4 weeks stays 'not sure'", "not_sure",
         lambda: wb_of(E.Verdict.MOVED.value, weeks=2)),
    Case("lp-03", LOOP, "A move in the wrong direction is not 'suited'", "not_sure",
         lambda: wb_of(E.Verdict.MOVED.value, direction="worse")),
    Case("lp-04", LOOP, "No detectable change never writes 'suited'", "not_sure",
         lambda: wb_of(E.Verdict.NO_CHANGE.value)),
    Case("lp-05", LOOP, "Not comparable never writes 'suited'", "not_sure",
         lambda: wb_of(E.Verdict.NOT_COMPARABLE.value)),
    Case("lp-06", LOOP, "Several changes never writes 'suited'", "not_sure",
         lambda: wb_of(E.Verdict.SEVERAL_CHANGES.value)),
    Case("lp-07", LOOP, "No baseline never writes 'suited'", "not_sure",
         lambda: wb_of(E.Verdict.NO_BASELINE.value)),
    Case("lp-08", LOOP, "A stop on an itch writes an irritation outcome", "irritation",
         lambda: wb_of(E.Verdict.STOP_REACTION.value, symptoms=["itching"])),
    Case("lp-09", LOOP, "A stop on spots writes a breakout outcome", "breakout",
         lambda: wb_of(E.Verdict.STOP_REACTION.value, symptoms=["new_breakouts"])),
    Case("lp-10", LOOP, "A can't-tell verdict can't soften a reaction she already recorded",
         ("irritation", True),
         lambda: (lambda w: (w.outcome.outcome, w.refused_upgrade))(WBK.plan(
             {"verdict": E.Verdict.NO_CHANGE.value, "findings": [], "symptoms": []},
             "sr-09", True, "2026-01-01", trial_id="t",
             existing=OC.ProductOutcome("sr-09", "irritation", True, id="o1")))),
    Case("lp-11", LOOP, "Through the real app: a can't-tell verdict writes 'not sure', never 'suited'",
         ("cant_tell_no_baseline", "not_sure"), scene_writeback_cant_tell),
    Case("lp-12", LOOP, "Meera's positive trial writes 'suited' into her history",
         ("suited", ["sr-05"]), lambda: scene_writeback("meera-pore")),

    # ---------------------------------------------------------------- the demo personas
    Case("ps-01", PERSONA, "Riya's scene: her irritation suspect is the shared drying alcohol",
         ("alcohol denat", "suspect", "exact"),
         lambda: (lambda s: (s["ingredient"], s["tier"], s["match_type"]))(
             scene_patterns("riya-store", "irritation")["suspects"][0])),
    Case("ps-02", PERSONA, "Riya's scene: the suspect's counts line",
         "in 2 of 2 products that made you itch, sting or burn, 0 of 2 that suited you",
         lambda: scene_patterns("riya-store", "irritation")["suspects"][0]["counts_line"]),
    Case("ps-03", PERSONA, "Riya's scene: the azelaic breakout offers a purge reclassification",
         (["sr-05"], 5),
         lambda: (lambda offers: ([x["product_id"] for x in offers], offers[0]["settled_week"]))(
             scene_patterns("riya-store", "breakout")["purge_offers"])),
    Case("ps-04", PERSONA, "Riya's scene: the purge offer changes nothing by itself", "breakout",
         lambda: next(p for p in scene_patterns("riya-store", "breakout")["failed_products"]
                      if p["product_id"] == "sr-05")["outcome"]),
    Case("ps-05", PERSONA, "Store product A repeats a pattern", "Repeats a pattern",
         lambda: scene_cart("riya-store", "sr-08")["verdict_line"]),
    Case("ps-06", PERSONA, "Store product B's label is incomplete, so it reads unknown",
         "Ingredient list incomplete → unknown",
         lambda: scene_cart("riya-store", "mo-07")["verdict_line"]),
    Case("ps-07", PERSONA, "Store product C has no conflicts and is aimed at her measured pores",
         ("No conflicts with your history", True),
         lambda: (lambda r: (r["verdict_line"], "Aimed at pores" in next(
             s for s in r["sources"] if s["key"] == "skin")["lines"][0]))(
             scene_cart("riya-store", "sr-09"))),
    Case("ps-08", PERSONA, "Riya's breakout: the new sunscreen is the top lead, and it is not a purge",
         ("sp-01", False), lambda: (triage_of().lead().product_id, triage_of().purge.possible)),
    Case("ps-09", PERSONA, "Riya's breakout: the snail mucin ranks low with its reason shown",
         (True, True),
         lambda: (lambda c: (c.tier > triage_of().lead().tier,
                             "12 weeks without this problem" in c.reason))(
             next(c for c in triage_of().candidates if c.product_id == "es-01"))),
    Case("ps-10", PERSONA, "Meera's positive verdict is on PORES, not redness",
         ("moved_beyond_noise", ["pore"]),
         lambda: (lambda ev: (ev["report"]["verdict"],
                              [f["concern"] for f in ev["report"]["findings"]
                               if f["beyond_noise"]]))(api_scene("meera-pore"))),
    Case("ps-11", PERSONA, "Meera's wording stays at 'during this trial', with the caveat",
         "Pores looked smaller beyond your usual variation during this trial. " + E.MOVED_CAVEAT,
         lambda: api_scene("meera-pore")["report"]["message"]),
    Case("ps-12", PERSONA, "Meera's raw move is 6.0 points, which the 'typical app' line is built from",
         6.0,
         lambda: next(f for f in api_scene("meera-pore")["report"]["findings"]
                      if f["concern"] == "pore")["delta_mid"]),
    Case("ps-13", PERSONA, "Itching at Meera's check-in: stop outranks her better scores",
         "stop_reaction",
         lambda: api_scene("meera-pore", symptoms=("itching",))["report"]["verdict"]),
    Case("ps-14", PERSONA, "The beginner scene starts from nothing at all", ([], [], None),
         lambda: (lambda t: t)(_beginner_blank())),
    Case("ps-15", PERSONA, "The beginner's skin type is labelled 'from your answers'",
         ("combination", "answers", "from your answers"), _beginner_type),
    Case("ps-16", PERSONA, "The beginner's starter is 3 steps, each run through the cart check",
         (["cleanser", "moisturiser", "sunscreen"], ["cartcheck-1.0"] * 3), _beginner_starter),
    Case("ps-17", PERSONA, "A scene writes rows only: no verdict word appears in what it stored", [],
         _scene_rows_have_no_verdicts),
]


# ---------------------------------------------------------------- Strategy v2: the basket
# docs/strategy.md sections 4-5. Expected values are written from the strategy, not from a run.
from app import basket as BK  # noqa: E402
from app import needs as ND  # noqa: E402
from app import undertone as UT  # noqa: E402
from app.demo_faces import BASKET_ACTIONS, DEMO_FACES  # noqa: E402
from app.youcam import normalize as _yc_normalize  # noqa: E402

BASKET = "Basket: zone split, finish, history skips, unknown labels, owned, shade, wording"
CATEGORIES.append(BASKET)
_STOCK = PRD.shop_tags()


def _skin(t: str, u: str) -> dict:
    return {"data": {"results": {"output": [{"type": "skin_type", "t_zone": {"skin_type": t},
                                              "u_zone": {"skin_type": u}}]}}}


def _tone(hex_: str = "#b9947c") -> dict:
    return {"data": {"results": {"color": {"skin_color": hex_}}}}


def basket_of(skin=None, tone=None, answers=None, shelf=None, history=True, chips=None, today=None) -> dict:
    face = DEMO_FACES["riya"]
    skin = face["skin"] if skin is None else skin
    tone = face["tone"] if tone is None else tone
    answers = {"finish": "dewy", **(answers or {})}
    zones = ND.read_zones(skin, answers)
    measured = _yc_normalize(skin, "sd", BASKET_ACTIONS).raw_scores() if skin else {}
    return BK.build(zones=zones, measured=measured, ut=UT.from_payload(tone, answers), answers=answers,
                    stock=_STOCK, catalog=IDX, records=RIYA_RECS if history else [],
                    outcomes=RIYA_OUT if history else [],
                    shelf=RIYA_SHELF if shelf is None else shelf, chips=chips,
                    today=today or date(2026, 11, 2)).to_dict()


def _pick(b: dict, title: str) -> str | None:
    j = next(j for j in b["jobs"] if j["title"] == title)
    return (j["pick"] or {}).get("product", {}).get("id")


def _moisturisers(b: dict) -> int:
    return sum(1 for j in b["jobs"] if j["job"] == "moisturiser")


def _user_lines(b: dict) -> list[str]:
    out = [z["line"] for z in b["face_map"]["zones"]] + [b["face_map"]["needs_line"], b["next_step"]]
    for j in b["jobs"]:
        out += [w["line"] for w in j["why"]] + [j["how_to_use"], j["note"] or ""]
    out += [s["reason"] for s in b["skipped"]] + [o["line"] for o in b["already_own"]]
    return out


def _bad_words(b: dict) -> list[str]:
    import re
    rx = re.compile(r"\b(scores?|points?)\b|can['’]?t tell|cannot tell|\d+\.\d", re.I)
    return [t for t in _user_lines(b) if rx.search(t)]


def _skip(b: dict, pid: str) -> tuple:
    s = next((s for s in b["skipped"] if s["product_id"] == pid), None)
    return (None, None) if s is None else (s["kind"], s["reason"].split(",")[0])


CASES += [
    Case("bk-01", BASKET, "Oily T-zone, dry cheeks: two moisturisers, one per zone", 2,
         lambda: _moisturisers(basket_of())),
    Case("bk-02", BASKET, "The two moisturisers are different products, gel on the T-zone, cream on the cheeks",
         ("gel", "cream"),
         lambda: (lambda b: (_STOCK[_pick(b, "T-zone moisturiser")]["texture"],
                             _STOCK[_pick(b, "Cheek moisturiser")]["texture"]))(basket_of())),
    Case("bk-03", BASKET, "Both zones the same type: one moisturiser for the whole face", 1,
         lambda: _moisturisers(basket_of(_skin("Dry", "Dry"), history=False, shelf=[]))),
    Case("bk-04", BASKET, "Matte instead of dewy changes the T-zone pick to a matte finish", "matte",
         lambda: _STOCK[_pick(basket_of(answers={"finish": "matte"}), "T-zone moisturiser")]["finish"]),
    Case("bk-05", BASKET, "Dewy: the base pick has a dewy finish, and a matte tint is skipped as the wrong finish",
         ("dewy", "finish"),
         lambda: (lambda b: (_STOCK[_pick(b, "Sunscreen / skin tint")]["finish"], _skip(b, "tt-03")[0]))(basket_of())),
    Case("bk-06", BASKET, "The history suspect is skipped with its exact reason",
         ("history", "Contains Alcohol Denat."), lambda: _skip(basket_of(), "tt-01")),
    Case("bk-07", BASKET, "An incomplete ingredient list is never picked; it is skipped as unknown",
         (False, "unknown"),
         lambda: (lambda b: ("mo-07" in {_pick(b, j["title"]) for j in b["jobs"]}, _skip(b, "mo-07")[0]))(basket_of())),
    Case("bk-08", BASKET, "An owned cleanser is not bought again", ("owned", "cl-01", 0),
         lambda: (lambda j: (j["status"], j["pick"]["product"]["id"], j["pick"]["price_inr"]))(
             next(j for j in basket_of()["jobs"] if j["job"] == "cleanser"))),
    Case("bk-09", BASKET, "A store product already on the shelf moves to 'You already own'", ("owned", True),
         lambda: (lambda b: (next(j for j in b["jobs"] if j["title"] == "Cheek moisturiser")["status"],
                             any(o["product_id"] == "mo-14" for o in b["already_own"])))(
             basket_of(shelf=RIYA_SHELF + ["mo-14"]))),
    Case("bk-10", BASKET, "Warm-neutral skin colour: a warm shade at her depth", ("warm-neutral", "warm", "medium"),
         lambda: (lambda b: (b["face_map"]["undertone"]["tone"],
                             next(j for j in b["jobs"] if j["job"] == "base")["pick"]["shade"]["undertone"],
                             next(j for j in b["jobs"] if j["job"] == "base")["pick"]["shade"]["depth"]))(basket_of())),
    Case("bk-11", BASKET, "Cool skin colour: a cool shade", "cool",
         lambda: next(j for j in basket_of(tone=_tone("#c8a7a0"))["jobs"] if j["job"] == "base")["pick"]["shade"]["undertone"]),
    Case("bk-12", BASKET, "No score, number or 'can't tell' in any user sentence, for every finish", [],
         lambda: [t for f in ("dewy", "natural", "matte") for t in _bad_words(basket_of(answers={"finish": f}))]),
    Case("bk-13", BASKET, "Every basket has exactly one next step", [BK.NEXT_STEP] * 3,
         lambda: [basket_of(answers=a)["next_step"] for a in
                  ({"finish": "dewy"}, {"finish": "matte", "budget": "under_700"}, {"history": "ignore"})]),
    Case("bk-14", BASKET, "No face measurement: the zones come from the answers, labelled, and every job answers",
         ("from your answers", True),
         lambda: (lambda b: (b["face_map"]["label"], all(j["status"] in ("pick", "owned") for j in b["jobs"])))(
             basket_of(skin={}, tone={}, answers={"midday": "shiny_tzone"}, history=False, shelf=[]))),
    Case("bk-15", BASKET, "Riya's basket: owned cleanser, gel T-zone, cream cheeks, dewy tint in her shade",
         ("cl-01", "mo-11", "mo-14", "tt-02"),
         lambda: tuple(_pick(basket_of(), t) for t in ("Cleanser", "T-zone moisturiser", "Cheek moisturiser",
                                                      "Sunscreen / skin tint"))),
]


# ---------------------------------------------------------------- history-aware, safe to start
# Ingredient chips, the start plan, "what to look for", the paste check, one need per zone.
from app import chips as CHP  # noqa: E402
from app import pastecheck as PCK  # noqa: E402
from app import startplan as SPL  # noqa: E402
from app.scenes import RIYA_CHIPS  # noqa: E402

HISTORY_AWARE = "History by ingredient, start plan, what to look for, paste check"
CATEGORIES.append(HISTORY_AWARE)


def _chip_skip(inci: list[str], *rows: dict) -> list[str]:
    return [s["match_type"] for s in CHP.evaluate(inci, CHP.parse_all(list(rows)))["skip"]]


def _paste(text: str) -> tuple:
    r = PCK.check(text=text, job="moisturiser", nickname=None, finish=None, records=RIYA_RECS,
                  outcomes=RIYA_OUT, chips=RIYA_CHIPS, catalog=IDX, zones=None, measured=None, goal_finish=None)
    return r["rung"], r["unknown"]


_CALM = ["Water", "Glycerin", "Squalane", "Panthenol", "Allantoin", "Sodium Hyaluronate"]

CASES += [
    Case("ha-01", HISTORY_AWARE, "Itched chip skips exact and same-group products", (["exact"], ["family"]),
         lambda: (_chip_skip(_CALM + ["Ascorbic Acid"], {"chip": "vitamin_c", "reaction": "itched"}),
                  _chip_skip(IDX["mo-17"].inci, {"chip": "vitamin_c", "reaction": "itched"}))),
    Case("ha-02", HISTORY_AWARE, "Broke-out chip skips only a key active", (["exact"], []),
         lambda: (_chip_skip(IDX["mo-18"].inci, {"chip": "azelaic_acid", "reaction": "broke_out"}),
                  _chip_skip(_CALM + ["Azelaic Acid"], {"chip": "azelaic_acid", "reaction": "broke_out"}))),
    Case("ha-03", HISTORY_AWARE, "'Suited me' never excludes anything", [],
         lambda: _chip_skip(_CALM + ["Snail Secretion Filtrate"], {"chip": "snail_mucin", "reaction": "suited"})),
    Case("ha-04", HISTORY_AWARE, "Purge: offered only after a yes, never applied without the user's choice",
         (None, CHP.PURGE_OFFER, None, ["exact"]),
         lambda: (lambda no, yes: (no.purge_offer(), yes.purge_offer(), yes.purge_choice,
                                   _chip_skip(IDX["mo-18"].inci, yes.to_dict())))(
             CHP.Chip("azelaic_acid", "broke_out"), CHP.Chip("azelaic_acid", "broke_out", usual_spots_settled="yes"))),
    Case("ha-05", HISTORY_AWARE, "Product-level history ranks above a chip on the same product", "history",
         lambda: next(s["kind"] for s in basket_of(chips=[{"chip": "fragrance", "reaction": "itched"}])["skipped"]
                      if s["product_id"] == "mo-13")),
    Case("ha-06", HISTORY_AWARE, "Start plan: gentle, then sunscreen, then actives, 14 days apart, owned kept",
         (["mo-14", "tt-02", "sr-01"], [14, 14], ["cl-01"]),
         lambda: (lambda p: ([s["product_id"] for s in p["steps"]],
                             [(date.fromisoformat(b["start_on"]) - date.fromisoformat(a["start_on"])).days
                              for a, b in zip(p["steps"], p["steps"][1:])],
                             [k["product_id"] for k in p["keep"]]))(
             SPL.plan([{"title": t, "job": j, "status": st, "pick": {"product": {"id": pid}}} for t, j, pid, st in
                       (("Serum", "serum", "sr-01", "pick"), ("Tint", "base", "tt-02", "pick"),
                        ("Cleanser", "cleanser", "cl-01", "owned"), ("Cheeks", "moisturiser", "mo-14", "pick"))],
                      IDX, date(2026, 11, 2)))),
    Case("ha-07", HISTORY_AWARE, "What to look for: no exfoliant in the base, Avoid lists her own reasons",
         (False, True),
         lambda: (lambda b: (
             any("BHA" in i or "AHA" in i for i in next(j for j in b["jobs"] if j["job"] == "base")["look_for"]["ingredients"]),
             {"what": "vitamin C", "why": "itched, stung or burned on you before"}
             in next(j for j in b["jobs"] if j["job"] == "moisturiser")["look_for"]["avoid"]))(basket_of(chips=RIYA_CHIPS))),
    Case("ha-08", HISTORY_AWARE, "Paste check: suspect repeats a pattern, clean has no conflicts, cut-off is unknown",
         (("repeats_a_pattern", False), ("no_conflicts", False), True),
         lambda: (_paste("Water, Glycerin, Alcohol Denat., Niacinamide, Zinc PCA, Dimethicone."),
                  _paste("Water, Glycerin, Squalane, Panthenol, Allantoin, Sodium Hyaluronate."),
                  _paste("Water, Glycerin, Squalane...")[1])),
    Case("ha-09", HISTORY_AWARE, "One need per zone: normal cheeks with low moisture read hydration once",
         [("hydration", "u_zone")],
         lambda: [(n.key, n.zone) for n in ND.build_needs(
             {"t_zone": ND.ZoneRead("t_zone", "oily", False, "face"),
              "u_zone": ND.ZoneRead("u_zone", "normal", False, "face")}, {"moisture": 40.0}) if n.zone == "u_zone"]),
    Case("ha-10", HISTORY_AWARE, "Beginner: gentle label on every card, no history step",
         (True, True, []),
         lambda: (lambda b: (b["beginner"], all(j.get("label") == BK.GENTLE_LABEL for j in b["jobs"]), b["tried"]["chips"]))(
             basket_of(answers={"history": "new"}, chips=RIYA_CHIPS, shelf=[]))),
]
