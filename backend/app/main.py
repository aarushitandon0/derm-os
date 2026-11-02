"""derm//os API.

Run:  uvicorn app.main:app --reload  (from backend/)
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
import threading
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from contextlib import asynccontextmanager
from dataclasses import dataclass

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import settings  # noqa: F401  (loads backend/.env first)
from . import accounts as AC
from . import auth as AU
from . import basket as BK
from . import beginner as B
from . import db as DBL
from . import cartcheck as CKT
from . import chips as CH
from . import pastecheck as PC
from . import decision as D
from . import demo
from . import demo_faces as DF
from . import evidence as E
from . import guard as G
from . import outcomes as OC
from . import patterns as PAT
from . import photometa as P
from . import pose as PO
from . import facecrop as F
from . import llm as L
from . import needs as ND
from . import products as PRD
from . import scenes as S
from . import triage as TRI
from . import undertone as UT
from . import writeback as WB
from .fingerprint import Fingerprint, measure_normalised
from .settings import flag
from .youcam import (MAKEUP_VTO, SKIN_TONE, UNUSABLE_PHOTO_ERRORS, YouCamClient, YouCamError, actions_for_mode,
                     check_unit_reserve, is_face_angle_error,
                     delete_task_quietly, download_masks, download_render, normalize, scan_cost_from,
                     strip_urls, validate_actions)

log = logging.getLogger("dermos")
if not log.handlers:   # uvicorn only configures its own loggers; without this, INFO lines are dropped
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(levelname)s:     %(name)s: %(message)s"))
    log.addHandler(_handler)
    log.setLevel(logging.INFO)
BACKEND_DIR = Path(__file__).resolve().parents[1]
DB_PATH = Path(os.environ.get("DERMOS_DB", BACKEND_DIR / "dermos.db"))
MEDIA_DIR = Path(os.environ.get("DERMOS_MEDIA", BACKEND_DIR / "media"))
MEDIA_DIR.mkdir(parents=True, exist_ok=True)
# Every product the app can check: its own catalogue plus the shop's sale stock (app/products.py).
CATALOG = PRD.index()
# The app's default concern set: 4 SD concerns = the 9-unit price tier.
DEFAULT_ACTIONS = ("redness", "acne", "texture", "pore")
DEFAULT_UNIT_RESERVE = 200


def demo_mode() -> bool:
    return G.demo_mode()


def unit_reserve() -> float:
    try:
        return float(os.environ.get("YOUCAM_UNIT_RESERVE", str(DEFAULT_UNIT_RESERVE)))
    except ValueError:
        return float(DEFAULT_UNIT_RESERVE)

def face_check() -> bool:
    """Whether the face detector loads on this server (cached after the first success)."""
    try:
        F.get_detector()
        return True
    except F.DetectorUnavailable:
        return False


def model_self_check() -> dict:
    """Load both models at startup and say so in the log, so a broken image shows up at once."""
    face = face_check()   # on failure, get_detector() has already logged the real cause
    if face:
        log.info("face model OK (%s)", F.ensure_model())
    else:
        log.error("face model FAILED: photo checks will answer 503 until this is fixed")
    pose_err = PO.warm()
    if pose_err is None:
        log.info("pose model OK (%s)", PO.ensure_model())
    else:
        log.error("pose model FAILED: %s", pose_err)
    return {"face": face, "pose": pose_err is None}


@asynccontextmanager
async def lifespan(_app: FastAPI):
    model_self_check()
    if flag("DERMOS_SEED"):
        seeded = seed_if_empty()
        if seeded:
            log.info("Seeded demo data: %s", ", ".join(seeded))
        missing = [p for p in ("riya", "meera") if p not in demo.personas()]
        if missing:
            log.warning("Demo fixtures missing for: %s. The guided demo needs them.", ", ".join(missing))
    yield


app = FastAPI(title="derm//os", version="0.1.0", lifespan=lifespan)
# CORS_ORIGINS: comma-separated origins, e.g. the Vercel URL. Defaults to "*" for local dev.
app.add_middleware(CORSMiddleware, allow_origins=G.cors_origins(),
                   allow_methods=["*"], allow_headers=["*"])
SCAN_LIMITER = G.make_scan_limiter()
# Upload prechecks are free (no YouCam call) but run the face detector, so they get their own limit.
PRECHECK_LIMITER = G.make_scan_limiter()
# Locally saved YouCam masks (the original URLs expire).
app.mount("/media", StaticFiles(directory=MEDIA_DIR), name="media")


# ---------------------------------------------------------------- storage
# One table per kind, JSON bodies. Small on purpose: SQLite or Postgres behind
# the same four functions (app/db.py). These are the guest / demo tables; accounts live in
# their own tables (app/accounts.py), which the demo never writes to.
# "outcomes" is what happened when a product was used (app/outcomes.py). It is a separate kind
# from "history" on purpose: the three history record types and their blocking rules are
# untouched, and an outcome only ever describes, never blocks.
# "baskets" stores each basket the shopping flow built, with every input it was built from.
# "chips" is the quick history by ingredient (app/chips.py): one row holding the whole list.
KINDS = DBL.LEGACY_KINDS


def _db():
    """SQLite file by default, Postgres when DATABASE_URL is set (app/db.py)."""
    return DBL.connect(DB_PATH)


# ---------------------------------------------------------------- judge unit caps
_SPEND_LOCK = threading.Lock()


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def units_spent() -> dict:
    """Units counted against the caps: confirmed live scans plus scans in flight."""
    with _db() as con:
        total = con.execute("SELECT COALESCE(SUM(units), 0) FROM spend").fetchone()[0]
        today = con.execute("SELECT COALESCE(SUM(units), 0) FROM spend WHERE day = ?", (_today(),)).fetchone()[0]
    return {"total": float(total), "today": float(today)}


def hold_units(units: float) -> tuple[str | None, str | None]:
    """Count a live scan against the caps before it is sent. Returns (hold id, None) or
    (None, cap reason) when this scan would go over JUDGE_UNIT_CAP_TOTAL or JUDGE_UNIT_CAP_DAILY."""
    cap_total, cap_daily = G.judge_caps()
    with _SPEND_LOCK:
        spent = units_spent()
        if spent["total"] + units > cap_total:
            return None, "judge_cap_total"
        if spent["today"] + units > cap_daily:
            return None, "judge_cap_daily"
        hid = uuid.uuid4().hex[:12]
        with _db() as con:
            con.execute("INSERT INTO spend VALUES (?, ?, ?, 'held', ?)",
                        (hid, _today(), units, datetime.now(timezone.utc).isoformat()))
        return hid, None


def settle_units(hid: str | None, spent: bool, units: float | None = None) -> None:
    """A scan that went through stays counted; one that failed (YouCam doesn't charge) is released.
    `units`: what was actually charged, when a chained run spent only part of what it held."""
    if not hid:
        return
    if spent and units is not None and units <= 0:
        spent = False
    with _SPEND_LOCK, _db() as con:
        if spent and units is not None:
            con.execute("UPDATE spend SET state = 'spent', units = ? WHERE id = ?", (units, hid))
        elif spent:
            con.execute("UPDATE spend SET state = 'spent' WHERE id = ?", (hid,))
        else:
            con.execute("DELETE FROM spend WHERE id = ?", (hid,))


def put(kind: str, body: dict, id: str | None = None) -> dict:
    id = id or body.get("id") or uuid.uuid4().hex[:12]
    body = {**body, "id": id}
    with _db() as con:
        con.execute(f"INSERT INTO {kind} (id, body, created) VALUES (?, ?, ?) "
                    "ON CONFLICT (id) DO UPDATE SET body = excluded.body, created = excluded.created",
                    (id, json.dumps(body), datetime.now(timezone.utc).isoformat()))
    return body


def get(kind: str, id: str) -> dict | None:
    with _db() as con:
        row = con.execute(f"SELECT body FROM {kind} WHERE id = ?", (id,)).fetchone()
    return json.loads(row[0]) if row else None


def all_(kind: str) -> list[dict]:
    with _db() as con:
        rows = con.execute(f"SELECT body FROM {kind} ORDER BY created").fetchall()
    return [json.loads(r[0]) for r in rows]


def delete(kind: str, id: str) -> None:
    with _db() as con:
        con.execute(f"DELETE FROM {kind} WHERE id = ?", (id,))


def seed_if_empty(persona: str = "riya") -> list[str]:
    """Fresh deploys (ephemeral SQLite) start with the demo persona's routine on the shelf.
    Only runs when every table is empty, so it never touches real data. The catalog is a
    static file (app/catalog.json) and needs no seeding."""
    with _db() as con:
        if any(con.execute(f"SELECT 1 FROM {k} LIMIT 1").fetchone() for k in KINDS):
            return []
    seed = demo.PERSONA_SEED.get(persona) or {}
    done = []
    if seed.get("shelf"):
        put("shelf", {"product_ids": [i for i in seed["shelf"] if i in CATALOG]}, id="me")
        done.append(f"{persona} shelf")
    return done


# ---------------------------------------------------------------- basics
@app.get("/health")
def liveness():
    """For the host's health check and the app's wake-up ping. No YouCam call, no database write."""
    return {"ok": True}


@app.get("/api/health")
def health(x_live_passcode: str | None = Header(None)):
    """What this caller gets. Never calls YouCam."""
    live = not demo_mode() and G.passcode_status(x_live_passcode) == "ok"
    cap_total, cap_daily = G.judge_caps()
    return {"ok": True, "youcam_key": bool(os.environ.get("YOUCAM_API_KEY")),
            # demo_mode is what THIS caller gets: true unless their scans would really go to YouCam.
            "demo_mode": not live, "server_demo_mode": demo_mode(),
            "live_scans": G.live_scans_setting(), "passcode": G.passcode_status(x_live_passcode),
            "personas": demo.personas() if not live else {},
            "unit_reserve": unit_reserve(), "rules": [D.RULE_VERSION, E.RULE_VERSION],
            "judge_caps": {"total": cap_total, "daily": cap_daily, "spent": units_spent()},
            # Only whether the optional language layer is on, never which key.
            "llm": L.get_provider() is not None,
            # Whether this server can check sign-in tokens. Never which project or key.
            "accounts": AU.configured(),
            # Whether photos can be checked here (the local face detector loads). No YouCam call.
            "face_check": face_check()}


@app.get("/api/catalog")
def catalog():
    return [p.__dict__ for p in CATALOG.values()]


# ---------------------------------------------------------------- history
class RecordIn(BaseModel):
    type: D.RecordType
    product_id: str | None = None
    ingredient: str | None = None
    note: str = ""


@app.post("/api/history")
def add_record(r: RecordIn):
    try:
        D.HistoryRecord(r.type, r.product_id, r.ingredient, r.note)  # validates
    except ValueError as e:
        raise HTTPException(422, str(e))
    if r.product_id and r.product_id not in CATALOG:
        raise HTTPException(404, f"Unknown product {r.product_id}")
    return put("history", r.model_dump(mode="json"))


class IntakeIn(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


@app.post("/api/history/intake")
def history_intake(body: IntakeIn):
    """Free text -> PROPOSED records. Saves nothing: the user confirms each one, which then
    goes through POST /api/history like any typed record."""
    return L.propose(body.text, CATALOG, L.get_provider())


@app.get("/api/history")
def list_records():
    return all_("history")


@app.delete("/api/history/{rid}")
def remove_record(rid: str):
    delete("history", rid)
    return {"deleted": rid}


def _records() -> list[D.HistoryRecord]:
    return [D.HistoryRecord(D.RecordType(r["type"]), r.get("product_id"), r.get("ingredient"), r.get("note", ""))
            for r in all_("history")]


# ---------------------------------------------------------------- shelf + compare
class ShelfIn(BaseModel):
    product_ids: list[str]


@app.put("/api/shelf")
def set_shelf(s: ShelfIn):
    bad = [i for i in s.product_ids if i not in CATALOG]
    if bad:
        raise HTTPException(404, f"Unknown products {bad}")
    return put("shelf", {"product_ids": s.product_ids}, id="me")


@app.get("/api/shelf")
def get_shelf():
    return get("shelf", "me") or {"id": "me", "product_ids": []}


class ItemIn(BaseModel):
    product_id: str
    mode: Literal["add", "replace"] | None = None


class OptionIn(BaseModel):
    name: str
    items: list[ItemIn]


class CompareIn(BaseModel):
    options: list[OptionIn] = Field(max_length=3)
    current: list[str] | None = None   # defaults to the saved shelf


@app.post("/api/compare")
def compare(c: CompareIn):
    current = c.current if c.current is not None else get_shelf()["product_ids"]
    for o in c.options:
        for it in o.items:
            if it.product_id not in CATALOG:
                raise HTTPException(404, f"Unknown product {it.product_id}")
    opts = [D.Option(o.name, [D.OptionItem(i.product_id, i.mode) for i in o.items]) for o in c.options]
    return D.compare(current, opts, CATALOG, _records())


# ---------------------------------------------------------------- scans
def _to_capture(c: dict) -> E.Capture:
    return E.Capture(c["raw_scores"], Fingerprint.from_dict(c["fingerprint"]), c["mode"], tuple(c["actions"]))


def _trial_mode(trial_id: str | None) -> str | None:
    """The scan mode a trial already uses (its first capture's), so SD and HD never mix in one trial."""
    if not trial_id:
        return None
    modes = [c.get("mode") for c in all_("captures") if c.get("trial_id") == trial_id and c.get("mode")]
    return modes[0] if modes else None


def _scan_cost(client, acts: list[str]) -> float | None:
    """Exact units this scan costs, from YouCam's price list (built-in table as fallback)."""
    fn = getattr(client, "scan_cost", None)
    if fn is None:
        return None
    try:
        return fn(acts)[0]
    except Exception as e:  # noqa: BLE001 - YouCam itself still refuses a scan it can't charge for
        log.warning("Couldn't work out this scan's cost (%s).", type(e).__name__)
        return None


def _media_url(path: Path) -> str:
    return "/media/" + path.relative_to(MEDIA_DIR).as_posix()


def _parse_actions(actions: str) -> tuple[list[str], str]:
    acts = [a.strip() for a in actions.split(",") if a.strip()]
    try:
        return acts, validate_actions(acts)
    except ValueError as e:
        raise HTTPException(422, str(e))


@dataclass
class Prepared:
    """One photo after the free checks: cropped, measured, ready to scan. Its two temp files
    (the original and the crop) are deleted by cleanup(); nothing of the photo is kept."""
    norm: F.Normalised
    fp: Fingerprint
    meta: P.ExifMeta
    pixels: str                 # hash of the decoded pixels, for the duplicate-baseline check
    warning: str | None
    orig_path: str
    norm_path: str

    def cleanup(self) -> None:
        for p in (self.orig_path, self.norm_path):
            if p and os.path.exists(p):
                os.unlink(p)


def _prepare(raw: bytes, requested: str, locked: str | None, capture_source: str,
             yaw: float | None = None, pitch: float | None = None, roll: float | None = None,
             client_hour: int | None = None, client_device: str | None = None,
             face_ratio: float | None = None) -> Prepared:
    """The same free checks for camera and uploaded photos, with no YouCam call: file type and
    size, decode upright (EXIF orientation), one face, the crop and scale of app/facecrop.py, and
    the light fingerprint. Raises P.UploadRefused, F.Refusal or F.DetectorUnavailable.

    `client_hour` / `client_device` are only for live camera shots (which carry no EXIF); uploads
    never send them, so an upload's hour and camera come from its own EXIF or are "not recorded"."""
    P.check_file(raw)
    img, notes = F.open_upright(raw)
    pixels = P.pixel_hash(img)
    norm = F.normalise(img, F.get_detector()(img), requested, locked, notes)
    with tempfile.NamedTemporaryFile(suffix=".img", delete=False) as tmp:
        tmp.write(raw)
        orig_path = tmp.name
    norm_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp2:
            tmp2.write(norm.png_bytes())
            norm_path = tmp2.name
        # The fingerprint always comes from the real pixels, demo or not: light from the
        # normalised image (what YouCam analyses), camera and time from the original's EXIF.
        fp = measure_normalised(norm_path, orig_path, norm.info, yaw, pitch, roll, client_hour, client_device,
                                face_ratio_live=face_ratio)
    except Exception:
        for p in (orig_path, norm_path):
            if p and os.path.exists(p):
                os.unlink(p)
        raise
    fp.capture_source = capture_source
    warning = P.MSG["palette"] if norm.info.get("reduced_colour") else None
    return Prepared(norm, fp, P.read_meta(raw), pixels, warning, orig_path, norm_path)


def _refusal(e: Exception) -> HTTPException:
    """One plain fix for any photo the free checks refuse."""
    if isinstance(e, (F.Refusal, P.UploadRefused)):
        return HTTPException(422, {"code": e.code, "message": e.fix})
    log.warning("Face detector unavailable; photo refused (%s).", e)
    return HTTPException(503, "The face check isn't available on this server right now, so the photo "
                              "can't be prepared for analysis. Try again in a minute.")


def _gate(trial_id: str | None, prep: Prepared, mode: str, acts: list[str]) -> dict | None:
    """The comparability gate against the trial's baseline, exactly as a stored check-in is gated
    (E.compare_conditions on the fingerprints). None when there is no baseline to compare with."""
    if not trial_id:
        return None
    base = [_to_capture(c) for c in all_("captures") if c.get("trial_id") == trial_id and c["phase"] == "baseline"]
    if not base:
        return None
    return E.compare_conditions(base, [E.Capture({}, prep.fp, mode, tuple(acts))]).to_dict()


def _scan_prepared(prep: Prepared, acts: list[str], want: str, replay_reason: str | None, *,
                   trial_id: str | None, phase: str, persona: str, fixture_set: str | None,
                   place: str | None, extra: dict | None = None) -> dict:
    """Scan one prepared photo: live through YouCam (after the balance floor and the judge caps)
    or a replay of prepared data. Stores the capture; never the photo."""
    youcam, notice, hold, replay_info = None, None, None, None
    source = "live"
    mode, acts = prep.norm.mode, actions_for_mode(acts, prep.norm.mode)
    fp = prep.fp
    need = 1080 if mode == "hd" else 480
    if fp.short_side < need:   # can't happen after normalisation; kept as a last check
        raise HTTPException(422, f"Photo short side is {fp.short_side}px; {mode.upper()} needs {need}px.")
    client = cost = bal = None
    if want == "live":
        try:
            client = YouCamClient()
        except YouCamError as e:
            raise HTTPException(503, e.friendly)
        cost = _scan_cost(client, acts) or scan_cost_from({}, client.version if hasattr(client, "version")
                                                          else "v2.1", acts)[0]
        # The real cap: the YouCam balance itself, read (free) before every live scan. It survives
        # restarts, unlike the database counters below. Unreadable balance = nothing is sent.
        bal, floored = G.balance_floor(client, cost)
        if floored:
            want, replay_reason, notice = "replay", floored, G.floor_message(floored)
            log.info("Live scan replayed instead: %s.", floored)
        else:
            # Second limit: the judge caps counted in this server's database.
            hold, capped = hold_units(cost)
            if capped:
                want, replay_reason, notice = "replay", capped, G.cap_message(capped)
                log.info("Live scan replayed instead: %s.", capped)
    if want == "replay":
        fset = fixture_set or ("baseline" if phase == "free" else phase)
        prior = [c for c in all_("captures") if c.get("source") == "replay"
                 and c.get("trial_id") == trial_id and (c.get("replay") or {}).get("set") == fset]
        try:
            rp = demo.pick(persona, fset, len(prior))
        except demo.FixtureError as e:
            raise HTTPException(503, str(e))
        res, source = rp.result, "replay"
        mode, acts = res.mode, list(res.actions)
        replay_info = {"persona": rp.persona, "set": rp.set, "fixture": rp.path.name,
                       "synthetic": rp.synthetic, "reason": replay_reason}
        cap_id = uuid.uuid4().hex[:12]
        masks = demo.copy_masks(rp, MEDIA_DIR / cap_id)
    else:
        cap_id = uuid.uuid4().hex[:12]
        try:
            check_unit_reserve(client, unit_reserve(), cost, balance=bal)
            log.info("YouCam scan: %s %s concerns, cost %s units; balance %s (reserve %s, floor %s).",
                     len(acts), mode.upper(), cost, bal, unit_reserve(), G.min_balance())
            res = client.analyze(prep.norm_path, acts)
        except YouCamError as e:
            settle_units(hold, spent=False)
            if e.code == "unit_reserve":
                raise HTTPException(402, e.friendly)
            raise HTTPException(502 if e.code not in (None, "no_key") else 503, e.friendly)
        except Exception:
            settle_units(hold, spent=False)
            raise
        settle_units(hold, spent=True)
        masks = download_masks(res, MEDIA_DIR / cap_id, getattr(client, "upload_http", None))
        # Masks are saved locally, so the copy at YouCam (photo + outputs) is no longer needed.
        youcam = {"task_id": res.task_id, "deleted": delete_task_quietly(client, res.task_id),
                  "cost_units": cost}

    cap = put("captures", {"trial_id": trial_id, "phase": phase, "mode": mode, "actions": acts, "place": place,
                           "fingerprint": fp.to_dict(), "raw_scores": res.raw_scores(),
                           # Stored without mask URLs: they are signed links to images of a face.
                           "result": strip_urls(res.to_dict()), "source": source, "replay": replay_info,
                           "youcam": youcam,
                           "masks": {k: [_media_url(p) for p in v] for k, v in masks.items()},
                           "taken_at": datetime.now(timezone.utc).isoformat(), **(extra or {})}, id=cap_id)
    # Immediate feedback: is this capture comparable to the trial baseline?
    check = None
    if trial_id and phase == "checkin":
        base = [_to_capture(c) for c in all_("captures") if c.get("trial_id") == trial_id and c["phase"] == "baseline"]
        if base:
            check = E.compare_conditions(base, [_to_capture(cap)]).to_dict()
    return {"capture": cap, "comparability": check, "notice": notice}


@app.post("/api/scan")
async def scan(request: Request,
               image: UploadFile = File(...),
               actions: str = Form(",".join(DEFAULT_ACTIONS)),
               trial_id: str | None = Form(None),
               phase: Literal["baseline", "checkin", "free"] = Form("free"),
               face_ratio: float | None = Form(None), yaw: float | None = Form(None),
               pitch: float | None = Form(None), roll: float | None = Form(None),
               persona: str = Form("riya"), fixture_set: str | None = Form(None),
               # Sent by the phone for live camera shots, which carry no EXIF.
               # Used only when the photo's own EXIF has no time / camera.
               client_hour: int | None = Form(None, ge=0, le=23),
               client_device: str | None = Form(None, max_length=200),
               # Optional, chosen by the user at the baseline: where the photos were taken, so a
               # check-in can say "Your first photos: by a window, around 9 am". Never inferred.
               place: Literal["window", "ceiling", "lamp", "outdoors", "other"] | None = Form(None),
               x_live_passcode: str | None = Header(None)):
    """One live camera shot."""
    SCAN_LIMITER.check(G.client_ip(request))
    # Live only with DEMO_MODE=0 AND the right passcode; otherwise replay recorded fixtures.
    want, replay_reason = G.scan_source(x_live_passcode)
    acts, requested = _parse_actions(actions)
    raw = await image.read()
    # Every capture is cropped and scaled the same way (app/facecrop.py) before it is measured
    # or sent, so distance from the camera doesn't change the comparison. One mode per trial.
    try:
        prep = _prepare(raw, requested, _trial_mode(trial_id), "camera", yaw, pitch, roll,
                        client_hour, client_device, face_ratio)
    except (F.Refusal, P.UploadRefused, F.DetectorUnavailable) as e:
        raise _refusal(e)
    try:
        return _scan_prepared(prep, acts, want, replay_reason, trial_id=trial_id, phase=phase,
                              persona=persona, fixture_set=fixture_set, place=place)
    finally:
        prep.cleanup()


# ---------------------------------------------------------------- uploaded photos
UPLOAD_FIELDS = "images"


async def _read_uploads(images: list[UploadFile]) -> list[bytes]:
    out = []
    for f in images:
        # Read at most one byte over the limit, so a huge file is refused without loading it all.
        data = await f.read(P.MAX_UPLOAD_BYTES + 1)
        out.append(data)
    return out


def _precheck(raws: list[bytes], phase: str, trial_id: str | None, requested: str, acts: list[str],
              same_sitting: bool | None) -> tuple[dict, list[Prepared]]:
    """The free checks for a set of uploaded photos. Returns (result, prepared photos); the caller
    must clean up the prepared photos. result["ok"] is True only when every check passed."""
    need = P.UPLOAD_COUNT[phase]
    result = {"ok": False, "code": None, "message": None, "needs_confirmation": False, "timing": None,
              "photos": [], "comparability": None}

    def fail(code: str, message: str, ask: bool = False):
        result.update(code=code, message=message, needs_confirmation=ask)
        return result

    if len(raws) != need:
        what = "Your first photos need" if phase == "baseline" else "A check-in needs"
        return fail("count", f"{what} exactly {need} photos. You chose {len(raws)}."), []
    prepared: list[Prepared] = []
    locked = _trial_mode(trial_id)
    try:
        for i, raw in enumerate(raws, 1):
            try:
                p = _prepare(raw, requested, locked, "upload")
            except (F.Refusal, P.UploadRefused) as e:
                result["photos"].append({"index": i, "ok": False, "code": e.code, "message": e.fix})
                return fail(e.code, f"Photo {i}: {e.fix}"), prepared
            prepared.append(p)
            # A trial keeps one scan mode: the first photo's mode locks the rest of this set.
            locked = locked or p.norm.mode
            result["photos"].append({"index": i, "ok": True, "warning": p.warning,
                                     "hour": p.fp.captured_hour, "device": p.fp.device or "not recorded",
                                     "luminance": p.fp.luminance, "red_blue_ratio": p.fp.red_blue_ratio,
                                     "mode": p.norm.mode})
        if phase == "baseline":
            integ = P.baseline_integrity([p.pixels for p in prepared], [p.meta.taken_at for p in prepared],
                                         same_sitting)
            result["timing"] = integ["timing"]
            if not integ["ok"]:
                return fail(integ["code"], integ["message"], integ["needs_confirmation"]), prepared
        else:
            checks = [_gate(trial_id, p, p.norm.mode, actions_for_mode(acts, p.norm.mode)) for p in prepared]
            result["comparability"] = checks
            for i, chk in enumerate(checks, 1):
                if chk and not chk["comparable"]:
                    fix = (chk["fixes"] or ["Retake in the same conditions as your first photos."])[0]
                    return fail("not_comparable", f"Photo {i} doesn't match your first photos. {fix}"), prepared
    except F.DetectorUnavailable as e:
        for p in prepared:
            p.cleanup()
        raise _refusal(e)
    result["ok"] = True
    return result, prepared


@app.post("/api/upload/precheck")
async def upload_precheck(request: Request,
                          images: list[UploadFile] = File(...),
                          phase: Literal["baseline", "checkin"] = Form(...),
                          trial_id: str | None = Form(None),
                          actions: str = Form(",".join(DEFAULT_ACTIONS)),
                          same_sitting: bool | None = Form(None)):
    """Free checks on uploaded photos before any scan: zero YouCam calls, nothing stored.
    Returns pass, or one plain-language fix."""
    PRECHECK_LIMITER.check(G.client_ip(request))
    acts, requested = _parse_actions(actions)
    result, prepared = _precheck(await _read_uploads(images), phase, trial_id, requested, acts, same_sitting)
    for p in prepared:
        p.cleanup()
    return result


@app.post("/api/upload/scan")
async def upload_scan(request: Request,
                      images: list[UploadFile] = File(...),
                      phase: Literal["baseline", "checkin"] = Form(...),
                      trial_id: str | None = Form(None),
                      actions: str = Form(",".join(DEFAULT_ACTIONS)),
                      same_sitting: bool | None = Form(None),
                      persona: str = Form("riya"), fixture_set: str | None = Form(None),
                      place: Literal["window", "ceiling", "lamp", "outdoors", "other"] | None = Form(None),
                      x_live_passcode: str | None = Header(None)):
    """Scan uploaded photos (3 for the first photos, 2 for a check-in). Re-runs every precheck on
    the server first and never trusts the client's own precheck."""
    ip = G.client_ip(request)
    want, replay_reason = G.scan_source(x_live_passcode)
    acts, requested = _parse_actions(actions)
    result, prepared = _precheck(await _read_uploads(images), phase, trial_id, requested, acts, same_sitting)
    try:
        if not result["ok"]:
            raise HTTPException(422, {"code": result["code"], "message": result["message"],
                                      "needs_confirmation": result["needs_confirmation"]})
        for _ in prepared:
            SCAN_LIMITER.check(ip)
        extra = {"baseline_timing": result["timing"]} if phase == "baseline" else {}
        out = [_scan_prepared(p, acts, want, replay_reason, trial_id=trial_id, phase=phase, persona=persona,
                              fixture_set=fixture_set, place=place, extra=extra) for p in prepared]
    finally:
        for p in prepared:
            p.cleanup()
    return {"captures": [o["capture"] for o in out], "comparability": [o["comparability"] for o in out],
            "notice": next((o["notice"] for o in out if o["notice"]), None)}


def _youcam_task_id(c: dict) -> str | None:
    if c.get("source") != "live":
        return None   # replayed scans never created a YouCam task for this user
    return (c.get("youcam") or {}).get("task_id") or (c.get("result") or {}).get("task_id")


@app.delete("/api/captures")
def delete_captures():
    """Delete every stored scan.

    On this server: scores, capture conditions (fingerprints) and the saved YouCam mask images.
    At YouCam: every live scan's task delete was already requested right after the scan. Any
    task YouCam hasn't confirmed deleted is requested again here; that removes the uploaded
    photo and its outputs at YouCam.
    The uploaded photo itself is never kept on this server.
    Only folders this app created for a capture are removed.
    """
    caps = all_("captures")
    live = [c for c in caps if _youcam_task_id(c)]
    confirmed = {_youcam_task_id(c) for c in live if (c.get("youcam") or {}).get("deleted")}
    task_ids = list(dict.fromkeys(_youcam_task_id(c) for c in live if _youcam_task_id(c) not in confirmed))
    yc = {"already_deleted": len(confirmed), "requested": len(task_ids), "deleted": 0, "failed": 0,
          "skipped_reason": None}
    if task_ids:
        try:
            client = YouCamClient()
        except YouCamError:
            client = None
            yc["skipped_reason"] = "no_key"
            log.warning("Can't request YouCam task delete for %d task(s): no API key on this server.", len(task_ids))
        if client is not None:
            for tid in task_ids:
                yc["deleted" if delete_task_quietly(client, tid) else "failed"] += 1
    for c in caps:
        folder = (MEDIA_DIR / c["id"]).resolve()
        if folder.parent == MEDIA_DIR.resolve() and folder.is_dir():
            shutil.rmtree(folder)
        delete("captures", c["id"])
    return {"deleted": len(caps), "youcam": yc}


# ---------------------------------------------------------------- trials
class TrialIn(BaseModel):
    goal_concern: str
    product_id: str
    held_fixed: list[str] = []
    checkpoints_days: list[int] = [14, 28]


@app.post("/api/trials")
def start_trial(t: TrialIn):
    if t.product_id not in CATALOG:
        raise HTTPException(404, f"Unknown product {t.product_id}")
    chk = D.check_product(CATALOG[t.product_id], _records())
    if chk.status == D.Status.BLOCKED:
        raise HTTPException(409, {"message": "This product conflicts with your history.", "check": chk.to_dict()})
    return put("trials", {**t.model_dump(), "status": "active", "check": chk.to_dict(),
                          "started_at": datetime.now(timezone.utc).isoformat(), "checkins": []})


class CheckinIn(BaseModel):
    symptoms: list[str] = []
    other_new_leave_on: list[str] = []   # products started besides the trial product


@app.post("/api/trials/{tid}/checkin")
def checkin(tid: str, c: CheckinIn):
    t = get("trials", tid)
    if not t:
        raise HTTPException(404, "Trial not found")
    t["checkins"].append({**c.model_dump(), "at": datetime.now(timezone.utc).isoformat()})
    return put("trials", t)


def _norm_symptom(s: str) -> str:
    return s.lower().strip()


def _when(iso: str) -> datetime:
    return datetime.fromisoformat(iso)


def _reactions(t: dict) -> list[dict]:
    """Stop-symptom reactions, derived from the dated check-ins plus stored resolutions.

    A stop symptom opens a reaction that stays in force until the user marks it
    resolved. Logging the same symptom again while it is open (or before the
    resolution was recorded) is the same episode; logging it after the
    resolution was recorded opens a new reaction.
    """
    resolutions = t.get("resolutions", {})
    out: list[dict] = []
    latest: dict[str, dict] = {}   # symptom -> most recent reaction for it
    for i, ci in enumerate(t.get("checkins", [])):
        for s in dict.fromkeys(_norm_symptom(x) for x in ci.get("symptoms", [])):
            if s not in E.STOP_SYMPTOMS:
                continue
            cur = latest.get(s)
            if cur is not None:
                res = resolutions.get(cur["id"])
                if res is None or _when(res["recorded_at"]) > _when(ci["at"]):
                    cur["last_logged_at"] = ci["at"]
                    continue
            cur = {"id": f"{i}-{s}", "symptom": s, "logged_at": ci["at"], "last_logged_at": ci["at"]}
            latest[s] = cur
            out.append(cur)
    for r in out:
        res = resolutions.get(r["id"])
        r["resolved"] = res is not None
        r["resolved_on"] = res["resolved_on"] if res else None
        r["resolution_note"] = res["note"] if res else ""
    return out


@app.get("/api/trials/{tid}/evidence")
def trial_evidence(tid: str):
    t = get("trials", tid)
    if not t:
        raise HTTPException(404, "Trial not found")
    caps = [c for c in all_("captures") if c.get("trial_id") == tid]
    base = [_to_capture(c) for c in caps if c["phase"] == "baseline"]
    follow_all = [c for c in caps if c["phase"] == "checkin"]
    follow = [_to_capture(c) for c in follow_all[-2:]]   # latest check-in pair
    last = t["checkins"][-1] if t["checkins"] else {"symptoms": [], "other_new_leave_on": []}
    reactions = _reactions(t)
    # Unresolved stop symptoms from any check-in stay in force; other symptoms
    # come from the latest check-in only, as before.
    open_stop = [r["symptom"] for r in reactions if not r["resolved"]]
    latest_other = [s for s in last.get("symptoms", []) if _norm_symptom(s) not in E.STOP_SYMPTOMS]
    ctx = E.TrialContext(new_leave_on_products=1 + len(last.get("other_new_leave_on", [])),
                         symptoms=list(dict.fromkeys(open_stop + latest_other)))
    report = E.evaluate(base, follow, ctx, concerns=[t["goal_concern"]])
    slim = [_slim(c) for c in caps]
    return {"trial": t, "report": report.to_dict(),
            "product": CATALOG[t["product_id"]].__dict__,
            "captures": {"baseline": [c for c in slim if c["phase"] == "baseline"],
                         "followup": [_slim(c) for c in follow_all[-2:]]},
            "reactions": reactions,
            # Every scan in order, each check-in gated against the baseline on its own,
            # so the progress chart can plot only comparable scans.
            "series": [{**c, "comparable": None if c["phase"] != "checkin" or not base
                        else E.compare_conditions(base, [_to_capture(raw)]).comparable}
                       for c, raw in zip(slim, caps)],
            "baseline_ranges": {k: r.to_dict() for k, r in E.ranges(base).items()},
            "timeline": _timeline(t, slim, reactions)}


_EXPLAIN_CACHE: dict[str, dict] = {}


@app.get("/api/trials/{tid}/explanation")
def trial_explanation(tid: str):
    """1-3 plain sentences about the stored result, checked by the claim validator.
    Falls back to the verdict template whenever the LLM is off, fails or is rejected."""
    ev = trial_evidence(tid)
    report, t = ev["report"], ev["trial"]
    confirmed = any(r["type"] == D.RecordType.CONFIRMED_ALLERGY.value for r in all_("history"))
    record = L.record_for(report, CATALOG[t["product_id"]], t["goal_concern"], confirmed)
    provider = L.get_provider()
    if provider is None:
        return {"text": report["message"], "source": "template", "rejected": None}
    key = json.dumps(record, sort_keys=True)
    if key in _EXPLAIN_CACHE:
        return _EXPLAIN_CACHE[key]
    out = L.explain_result(record, report["message"], CATALOG, provider)
    if out["rejected"] != "provider_failed":   # a timeout is retried next time; a verdict on a draft is kept
        _EXPLAIN_CACHE[key] = out
    return out


class ResolveIn(BaseModel):
    resolved_on: date | None = None   # the user's own date; defaults to today
    note: str = ""


@app.post("/api/trials/{tid}/reactions/{rid}/resolve")
def resolve_reaction(tid: str, rid: str, body: ResolveIn):
    t = get("trials", tid)
    if not t:
        raise HTTPException(404, "Trial not found")
    r = next((x for x in _reactions(t) if x["id"] == rid), None)
    if r is None:
        raise HTTPException(404, "Reaction not found")
    if r["resolved"]:
        raise HTTPException(409, "This reaction is already marked resolved.")
    now = datetime.now(timezone.utc)
    on = body.resolved_on or now.date()
    # One day of slack either side for time zones (dates are the user's local dates).
    if on < _when(r["logged_at"]).date() - timedelta(days=1):
        raise HTTPException(422, "The resolved date is before the reaction was logged.")
    if on > now.date() + timedelta(days=1):
        raise HTTPException(422, "The resolved date can't be in the future.")
    t.setdefault("resolutions", {})[rid] = {"resolved_on": on.isoformat(), "note": body.note.strip(),
                                            "recorded_at": now.isoformat()}
    put("trials", t)
    return {"reaction": next(x for x in _reactions(t) if x["id"] == rid), "reactions": _reactions(t)}


def _slim(c: dict) -> dict:
    keys = ("id", "phase", "taken_at", "source", "replay", "masks", "fingerprint", "raw_scores", "mode", "place",
            "baseline_timing")
    return {k: c.get(k) for k in keys}


def _timeline(t: dict, caps: list[dict], reactions: list[dict] = ()) -> list[dict]:
    ev = [{"at": t["started_at"], "kind": "start", "text": f"Started {CATALOG[t['product_id']].name}"}]
    for c in caps:
        label = "Baseline scan" if c["phase"] == "baseline" else "Check-in scan"
        ev.append({"at": c["taken_at"], "kind": c["phase"],
                   "text": label + (" (prepared data)" if c.get("source") == "replay" else "")})
    for ci in t.get("checkins", []):
        bits = []
        if ci.get("symptoms"):
            bits.append("logged " + ", ".join(ci["symptoms"]))
        others = [CATALOG[i].name if i in CATALOG else i for i in ci.get("other_new_leave_on", [])]
        if others:
            bits.append("also started " + ", ".join(others))
        ev.append({"at": ci["at"], "kind": "checkin_log",
                   "text": "Check-in: " + ("; ".join(bits) if bits else "no symptoms, nothing else new")})
    for r in reactions:
        if r["resolved"]:
            res = t["resolutions"][r["id"]]
            d = date.fromisoformat(r["resolved_on"])
            text = f"Marked {r['symptom'].replace('_', ' ')} resolved (as of {d.day} {d.strftime('%b')})"
            ev.append({"at": res["recorded_at"], "kind": "reaction_resolved",
                       "text": text + (f": {r['resolution_note']}" if r["resolution_note"] else "")})
    return sorted(ev, key=lambda e: _when(e["at"]))


@app.get("/api/trials")
def list_trials():
    return all_("trials")


@app.get("/api/trials/{tid}")
def get_trial(tid: str):
    t = get("trials", tid)
    if not t:
        raise HTTPException(404, "Trial not found")
    return t


# ---------------------------------------------------------------- outcomes (what happened)
class OutcomeIn(BaseModel):
    product_id: str
    outcome: Literal["suited", "irritation", "breakout", "not_sure"]
    started_on: date | None = None
    stopped_on: date | None = None
    weeks_used_given: int | None = Field(None, ge=0, le=520)
    zones: list[str] = []
    usual_spots: bool | None = None
    settled_while_using: bool | None = None
    settled_week: int | None = Field(None, ge=0, le=104)
    note: str = ""


def _outcome(row: dict) -> OC.ProductOutcome:
    return OC.ProductOutcome.from_dict(row)


def _outcomes() -> list[OC.ProductOutcome]:
    return [_outcome(r) for r in all_("outcomes") if r.get("product_id") in CATALOG]


@app.get("/api/outcomes")
def list_outcomes():
    return [o.to_dict() for o in _outcomes()]


@app.post("/api/outcomes")
def add_outcome(o: OutcomeIn):
    """One product, what happened. `leave_on` is never taken from the client: it is the catalog's."""
    if o.product_id not in CATALOG:
        raise HTTPException(404, f"Unknown product {o.product_id}")
    try:
        built = OC.ProductOutcome(leave_on=CATALOG[o.product_id].leave_on,
                                  **o.model_dump(mode="json"))
    except ValueError as e:
        raise HTTPException(422, str(e))
    # One outcome per product: recording what happened again replaces the earlier row.
    prior = next((r for r in all_("outcomes") if r.get("product_id") == o.product_id), None)
    row = built.to_dict()
    return put("outcomes", row, id=(prior or {}).get("id"))


@app.delete("/api/outcomes/{oid}")
def remove_outcome(oid: str):
    delete("outcomes", oid)
    return {"deleted": oid}


# ---------------------------------------------------------------- patterns
def _measured() -> dict[str, float]:
    """The user's most recent measured scores, averaged over that one scan set.

    "Most recent" is the latest capture's own sitting: every capture taken within a few minutes of
    the newest one. Nothing is averaged across different lighting or different days, because that
    is exactly what the comparability gate exists to stop.
    """
    caps = [c for c in all_("captures") if c.get("raw_scores")]
    if not caps:
        return {}
    caps.sort(key=lambda c: c.get("taken_at") or "")
    newest = _when(caps[-1]["taken_at"])
    sitting = [c for c in caps if abs((newest - _when(c["taken_at"])).total_seconds()) <= 3600]
    out: dict[str, list[float]] = {}
    for c in sitting:
        for k, v in (c["raw_scores"] or {}).items():
            if isinstance(v, (int, float)):
                out.setdefault(k, []).append(float(v))
    return {k: round(sum(v) / len(v), 2) for k, v in out.items()}


def _reports() -> dict[str, PAT.PatternReport]:
    return PAT.run_both(_outcomes(), CATALOG)


@app.get("/api/patterns")
def patterns():
    """Both runs, kept apart: irritation and breakout never share a suspect list."""
    r = _reports()
    return {"irritation": r["irritation"].to_dict(), "breakout": r["breakout"].to_dict(),
            "rule_version": PAT.RULE_VERSION, "families_version": PAT.FAM.FAMILIES_VERSION}


# ---------------------------------------------------------------- cart check (before you buy)
class CartCheckIn(BaseModel):
    product_id: str
    # Lets the store page ask "what would this say with no scan yet?" without deleting scans.
    use_scan: bool = True


@app.post("/api/cartcheck")
def cart_check(body: CartCheckIn):
    if body.product_id not in CATALOG:
        raise HTTPException(404, f"Unknown product {body.product_id}")
    measured = _measured() if body.use_scan else {}
    res = CKT.check(CATALOG[body.product_id], _records(), _outcomes(), CATALOG,
                    measured, get_shelf()["product_ids"], reports=_reports())
    return res.to_dict()


@app.get("/api/store")
def store():
    """The sale page's listings, each with its normal price, its sale price and the shop's blurb."""
    s = PRD.sale()
    items = []
    for i in s["items"]:
        p = CATALOG.get(i["product_id"])
        if p is None:
            continue
        items.append({**i, "product": p.__dict__})
    return {"name": s["name"], "line": s["line"], "items": items,
            "disclaimer": "A fictional shop, invented for this demo. The blurbs are the shop's; "
                          "derm//os checks the label instead of trusting them."}


# ---------------------------------------------------------------- triage (after a breakout)
class TriageIn(BaseModel):
    symptoms: list[str] = []
    zones: list[str] = []
    usual_spots: bool | None = None
    # What is on the skin and since when. Defaults to the shelf with no dates, which the engine
    # then reports as "no start date recorded" rather than guessing one.
    using: list[dict] | None = None
    settled_while_using: bool | None = None
    settled_week: int | None = Field(None, ge=0, le=104)


@app.post("/api/triage")
def triage(body: TriageIn):
    using = body.using
    if using is None:
        using = [{"product_id": i, "started_on": None} for i in get_shelf()["product_ids"]]
    bad = [u.get("product_id") for u in using if u.get("product_id") not in CATALOG]
    if bad:
        raise HTTPException(404, f"Unknown products {bad}")
    shares, baseline_shares = _zone_shares()
    res = TRI.assess(body.symptoms, body.zones, body.usual_spots, using, CATALOG,
                     body.settled_while_using, body.settled_week, shares, baseline_shares)
    return res.to_dict()


def _zone_shares() -> tuple[dict, dict]:
    """Per-zone acne share, from stored mask measurements only.

    Nothing here opens an image. A capture may carry `zone_shares` written when its masks were
    measured; where no capture has them, this returns empty and triage falls back to the zones the
    user tapped and says so. That is why there is no mask-reading code in this file.
    """
    caps = [c for c in all_("captures") if (c.get("zone_shares") or {}).get("acne")]
    if not caps:
        return {}, {}
    caps.sort(key=lambda c: c.get("taken_at") or "")
    base = next((c for c in caps if c.get("phase") == "baseline"), None)
    return (caps[-1]["zone_shares"]["acne"],
            (base or {}).get("zone_shares", {}).get("acne", {}))


# ---------------------------------------------------------------- verdict write-back
def _writeback_plan(tid: str) -> WB.WriteBack:
    ev = trial_evidence(tid)
    t = ev["trial"]
    p = CATALOG[t["product_id"]]
    prior = next((r for r in all_("outcomes") if r.get("product_id") == p.id), None)
    return WB.plan(ev["report"], p.id, p.leave_on, t["started_at"],
                   goal_concern=t.get("goal_concern"), trial_id=tid,
                   existing=_outcome(prior) if prior else None)


@app.get("/api/trials/{tid}/writeback")
def writeback_preview(tid: str):
    """What this trial's stored verdict would write into the product's history. Writes nothing."""
    return _writeback_plan(tid).to_dict()


@app.post("/api/trials/{tid}/writeback")
def writeback_apply(tid: str):
    """Write this trial's stored verdict into the product's history outcome.

    The verdict is read from GET /evidence, never recomputed here, and a can't-tell verdict can
    never be written as "suited" (app/writeback.py).
    """
    wb = _writeback_plan(tid)
    prior = next((r for r in all_("outcomes") if r.get("product_id") == wb.outcome.product_id), None)
    row = put("outcomes", wb.outcome.to_dict(), id=(prior or {}).get("id"))
    return {**wb.to_dict(), "outcome": row}


# ---------------------------------------------------------------- start here (beginners)
class BeginnerIn(BaseModel):
    answers: dict[str, str] = {}


@app.get("/api/beginner/questions")
def beginner_questions():
    return {"questions": B.QUESTIONS, "rule_version": B.RULE_VERSION}


@app.post("/api/beginner/plan")
def beginner_plan(body: BeginnerIn):
    """Quiz into a skin type, the top measured concerns, and a 3-step starter that has been run
    through the cart check. Skin type is labelled "from your answers" until a scan supplies one."""
    return B.plan(body.answers, CATALOG, _records(), _measured(),
                  shelf=get_shelf()["product_ids"]).to_dict()


# ---------------------------------------------------------------- the basket (shop by your face)
BASKET_QUESTIONS = [
    {"id": "finish", "text": "Which finish do you want?",
     "why": "It decides textures: a glow finish for dewy, oil control for matte.",
     "choices": [{"value": "dewy", "label": "Glowy / dewy"}, {"value": "natural", "label": "Natural"},
                 {"value": "matte", "label": "Matte"}]},
    {"id": "history", "text": "Anything that itched or broke you out before?",
     "why": "Your saved history is checked against every label, so nothing that bothered you comes back.",
     "skippable": True,
     "choices": [{"value": "use", "label": "Check against my history"},
                 {"value": "ignore", "label": "Skip for this basket"},
                 # A beginner: no history step, and a gentle start (app/basket.py GENTLE_LABEL).
                 {"value": "new", "label": "Nothing tried yet"}]},
    {"id": "budget", "text": "Budget per product (optional)", "skippable": True,
     "why": "Over-budget products are skipped while something under it fits.",
     "choices": [{"value": "under_700", "label": "Under ₹700"}, {"value": "under_1000", "label": "Under ₹1,000"},
                 {"value": "any", "label": "Any price"}]},
    {"id": "veins", "text": UT.VEINS_QUESTION, "skippable": True,
     "why": "Only used if your photo can't give your skin colour: your shades then follow this answer.",
     "choices": [{"value": "green", "label": "Green"}, {"value": "blue_purple", "label": "Blue / purple"},
                 {"value": "mix", "label": "A mix / can't tell"}]},
]
TONE_FALLBACK_NOTICE = ("We couldn't read your skin colour from this photo. {fix} Your skin scan is kept, and your "
                        "undertone comes from your answer about your wrist veins.")
TONE_FALLBACK_NOTICE_NO_ANSWER = ("We couldn't read your skin colour from this photo. {fix} Your skin scan is kept. "
                                  "Answer the wrist-vein question so your shades follow your undertone; until then "
                                  "they are neutral, the middle of the range.")
TRYON_FAILED_LINE = "The try-on preview couldn't be made this time. Your basket is unchanged."


class BasketIn(BaseModel):
    answers: dict[str, str] = {}
    persona: str = "riya"


@app.get("/api/basket/questions")
def basket_questions():
    recs, outs = _records(), _outcomes()
    return {"questions": BASKET_QUESTIONS, "on_record": {"records": len(recs), "outcomes": len(outs),
            "bothered": sum(1 for o in outs if o.outcome in ("irritation", "breakout"))},
            # Kept apart from on_record: chips are their own kind of history (app/chips.py).
            "chips": [c.to_dict() for c in CH.parse_all(_chip_rows())],
            "chip_catalogue": [{"id": c["id"], "label": c["label"], "purge_capable": c["purge_capable"]}
                               for c in CH.catalogue()],
            "reactions": CH.REACTIONS, "purge_question": CH.PURGE_QUESTION,
            "rule_version": BK.RULE_VERSION}


# ---------------------------------------------------------------- quick history by ingredient
def _chip_rows() -> list[dict]:
    return (get("chips", "me") or {}).get("chips", [])


class ChipIn(BaseModel):
    chip: str = Field(min_length=1, max_length=80)
    reaction: str
    product_name: str = Field("", max_length=80)
    confirmed_allergy: bool = False
    usual_spots_settled: Literal["yes", "no", "not_sure"] | None = None
    purge_choice: Literal["purging", "breakout"] | None = None


class ChipsIn(BaseModel):
    chips: list[ChipIn] = Field(max_length=40)


class ChipMatchIn(BaseModel):
    text: str = Field(min_length=1, max_length=60)


@app.get("/api/chips")
def list_chips():
    return {"chips": [c.to_dict() for c in CH.parse_all(_chip_rows())],
            "catalogue": CH.catalogue(), "reactions": CH.REACTIONS,
            "purge_question": CH.PURGE_QUESTION, "rule_version": CH.RULE_VERSION}


@app.put("/api/chips")
def set_chips(body: ChipsIn):
    """Replace the whole list. Each chip is validated by the engine; nothing is inferred."""
    try:
        built = [CH.Chip(**c.model_dump()) for c in body.chips]
    except ValueError as e:
        raise HTTPException(422, str(e))
    put("chips", {"chips": [{k: v for k, v in c.to_dict().items()
                             if k in ("chip", "reaction", "product_name", "confirmed_allergy",
                                      "usual_spots_settled", "purge_choice")} for c in built]}, id="me")
    return list_chips()


@app.post("/api/chips/match")
def match_chip(body: ChipMatchIn):
    """Free text -> a chip, matched against the chips, families.json and the INCI synonyms."""
    spec = CH.match_text(body.text)
    if spec is None:
        return {"match": None, "line": "No ingredient matched that. Try a chip above, or add the product "
                                       "itself in your history."}
    return {"match": {"id": spec["id"], "label": spec["label"], "purge_capable": spec["purge_capable"]},
            "line": f"Matched: {spec['label']}."}


class PasteCheckIn(BaseModel):
    text: str = Field(min_length=1, max_length=PC.MAX_TEXT)
    job: Literal["cleanser", "moisturiser", "sunscreen", "serum"]
    nickname: str | None = Field(None, max_length=40)
    finish: Literal["dewy", "natural", "matte"] | None = None
    basket_id: str | None = None


@app.post("/api/pastecheck")
def paste_check(body: PasteCheckIn):
    """A pasted ingredient list, checked like the shop's own stock. Nothing is stored. The face map
    and finish come from the basket named (or the latest one), so zone fit reads your own zones."""
    row = _guest_basket(body.basket_id)
    if row is None:
        rows = sorted((r for r in all_("baskets") if not r.get("owner")), key=lambda r: r.get("taken_at") or "")
        row = rows[-1] if rows else None
    zones = measured = goal = None
    if row:
        inp = row["basket"]["inputs"]
        zones = {z: ND.ZoneRead(z, r["type"], r["redness"], r["source"]) for z, r in inp["zones"].items()}
        measured, goal = inp.get("measured") or {}, inp.get("finish")
    try:
        return PC.check(text=body.text, job=body.job, nickname=body.nickname, finish=body.finish,
                        records=_records(), outcomes=_outcomes(), chips=_chip_rows(), catalog=CATALOG,
                        zones=zones, measured=measured, goal_finish=goal)
    except ValueError as e:
        raise HTTPException(422, str(e))


def _basket_from(skin_payload, tone_payload, answers: dict, *, demo_: bool, source: str,
                 src_file_id: str | None = None, renders: dict | None = None,
                 extra: dict | None = None, account: tuple[str, dict] | None = None) -> dict:
    """Payloads of the documented shapes -> face map, basket and try-on. Stored with its inputs.
    `account` = (user id, AC.basket_history(...)): the basket reads that user's own history and
    shelf instead of the guest ones, and the stored row is marked as theirs (guest reads skip it)."""
    zones = ND.read_zones(skin_payload, answers)
    measured = normalize(skin_payload, "sd", DF.BASKET_ACTIONS).raw_scores() if skin_payload else {}
    ut = UT.from_payload(tone_payload, answers)
    if account:
        uid, h = account
        hist = {"records": h["records"], "outcomes": [], "shelf": h["shelf"], "chips": h["chips"],
                "always": h["always"]}
    else:
        hist = {"records": _records(), "outcomes": _outcomes(), "shelf": get_shelf()["product_ids"],
                "chips": _chip_rows(), "always": None}
    b = BK.build(zones=zones, measured=measured, ut=ut, answers=answers, stock=PRD.shop_tags(),
                 catalog=CATALOG, demo=demo_, src_file_id=src_file_id, **hist)
    out = b.to_dict()
    if renders:
        out["tryon"]["looks"] = [{**lk, "image": renders.get(lk["look"])} for lk in out["tryon"]["looks"]]
        if all(lk["image"] for lk in out["tryon"]["looks"]):
            out["tryon"].update(status="ready", line=None)
    row = put("baskets", {"source": source, "demo": demo_, "basket": out,
                          "taken_at": datetime.now(timezone.utc).isoformat(), **(extra or {}),
                          **({"owner": account[0]} if account else {})})
    res = {**out, "id": row["id"], "source": source}
    if account:
        res["from_profile"] = True
    return res


def _guest_basket(bid: str | None) -> dict | None:
    """A basket row any visitor may read: never one built from an account's history."""
    row = get("baskets", bid) if bid else None
    return None if row is None or row.get("owner") else row


def _replay_basket(persona: str, answers: dict, reason: str | None, notice: str | None = None,
                   account: tuple[str, dict] | None = None) -> dict:
    face = DF.load_face(persona)
    if face is None:
        raise HTTPException(404, f"No demo face for persona {persona!r}.")
    res = _basket_from(face["skin"], face["tone"], answers, demo_=True, source="replay",
                       renders=face.get("renders"),
                       extra={"replay": {"persona": persona, "synthetic": face["synthetic"], "reason": reason}},
                       account=account)
    res["demo_label"] = face["label"]
    res["notice"] = notice
    return res


@app.post("/api/basket")
def basket(body: BasketIn):
    """The demo persona's face (prepared data, labelled) -> face map, basket, try-on. No YouCam call."""
    answers = {**(DF.load_face(body.persona) or {}).get("answers", {}), **body.answers}
    return _replay_basket(body.persona, answers, "demo_persona")


def _photo_check(prep: Prepared) -> dict:
    """The free precheck for a basket photo (app/pose.py): pose from the browser when it sent
    one, otherwise measured here on the crop YouCam will see; light from the fingerprint."""
    fp = prep.fp
    if fp.yaw is not None and fp.pitch is not None and fp.roll is not None:
        pose = PO.Pose(float(fp.yaw), float(fp.pitch), float(fp.roll), source="client")
    else:
        pose = PO.estimate(prep.norm.image)
    bad = PO.check(pose, fp.luminance)
    return {"ok": bad is None, "code": bad[0] if bad else None, "message": bad[1] if bad else None,
            "pose": pose.to_dict() if pose else None, "luminance": fp.luminance, "rule": PO.thresholds()}


def _has_undertone_answer(answers: dict) -> bool:
    return answers.get("undertone") in UT.FAMILIES or answers.get("veins") in UT.VEINS


def _live_basket(prep: Prepared, answers: dict, account: tuple[str, dict] | None = None) -> dict | None:
    """One live run, cheapest refusal first: skin tone, then skin analysis (skin_type + 7
    concerns), then two try-on renders. Returns a "_replay" marker when the balance floor or the
    judge caps say no.

    Always an answer: a photo YouCam can't use at all stops before the analysis is paid for. A
    tone check that only refuses the photo (a face angle, say) doesn't stop the run: the basket is
    built with the undertone from the wrist-vein answer, labelled "from your answers". A try-on
    that fails leaves the basket as it is. Only what YouCam actually charged is counted."""
    client = YouCamClient()
    skin_cost = scan_cost_from({}, client.version, DF.BASKET_ACTIONS)[0]
    try:
        skin_cost = client.scan_cost(DF.BASKET_ACTIONS)[0]
    except Exception:  # noqa: BLE001 - the built-in price stands
        pass
    tone_cost = client.feature_cost(SKIN_TONE)[0]
    vto_cost = client.feature_cost(MAKEUP_VTO)[0]
    total = skin_cost + tone_cost + 2 * vto_cost
    bal, floored = G.balance_floor(client, total)
    if floored:
        return {"_replay": floored, "_notice": G.floor_message(floored)}
    hold, capped = hold_units(total)
    if capped:
        return {"_replay": capped, "_notice": G.cap_message(capped)}
    spent = 0.0
    task_ids: list[str] = []
    tone = None
    notice = None
    tone_info: dict = {}
    tryon_failed = False
    try:
        check_unit_reserve(client, unit_reserve(), total, balance=bal)
        log.info("YouCam basket run: tone %s + skin %s + 2 x try-on %s = %s units; balance %s.",
                 tone_cost, skin_cost, vto_cost, total, bal)
        try:
            tone = client.skin_tone(prep.norm_path)
            spent += tone_cost
            task_ids.append(tone.task_id)
            tone_info = {"ok": True, "strictness": tone.strictness}
        except YouCamError as e:
            # A failed task is not charged. A photo that can't be used at all stops here,
            # before the analysis is paid for.
            if e.code in UNUSABLE_PHOTO_ERRORS:
                raise HTTPException(422, {"code": "photo_unusable", "message": e.friendly})
            if not (is_face_angle_error(e.code) or str(e.code or "").startswith("error_")):
                raise
            log.info("Skin Tone refused the photo (%s); undertone from the answers.", e.code)
            tried = getattr(client, "tone_attempts", None) or [None]
            tone_info = {"ok": False, "code": e.code, "strictness": tried[-1]}
            tmpl = TONE_FALLBACK_NOTICE if _has_undertone_answer(answers) else TONE_FALLBACK_NOTICE_NO_ANSWER
            notice = tmpl.format(fix=e.friendly)
        skin = client.analyze(prep.norm_path, DF.BASKET_ACTIONS)
        spent += skin_cost
        task_ids.append(skin.task_id)
        tone_raw = tone.raw if tone else None
        first = _basket_from(skin.raw, tone_raw, answers, demo_=False, source="live", account=account)
        renders: dict[str, str] = {}
        cap_id = first["id"]
        shade = (first["tryon"] or {}).get("shade")
        for req in (first["tryon"] or {}).get("requests", []) if shade else []:
            try:
                vto = client.makeup_vto(req["body"]["effects"], image_path=prep.norm_path)
            except YouCamError as e:
                log.warning("Try-on render failed (%s); the basket is kept.", e.code)
                tryon_failed = True
                continue
            spent += vto_cost
            task_ids.append(vto.task_id)
            saved = download_render(vto.image_url, MEDIA_DIR / cap_id / f"tryon_{req['look']}",
                                    getattr(client, "upload_http", None))
            if saved:
                renders[req["look"]] = _media_url(saved)
            else:
                tryon_failed = True
    except YouCamError as e:
        settle_units(hold, spent=spent > 0, units=spent)
        if e.code == "unit_reserve":
            raise HTTPException(402, e.friendly)
        raise HTTPException(502 if e.code not in (None, "no_key") else 503, e.friendly)
    except Exception:
        settle_units(hold, spent=spent > 0, units=spent)
        raise
    finally:
        # Results are saved locally, so the copies at YouCam (photo + outputs) are not needed.
        deleted = [delete_task_quietly(client, t) for t in task_ids if t]
    settle_units(hold, spent=True, units=spent)
    delete("baskets", first["id"])
    out = _basket_from(skin.raw, tone_raw, answers, demo_=False, source="live", renders=renders,
                       extra={"youcam": {"task_ids": task_ids, "deleted": all(deleted), "cost_units": spent,
                                         "tone": tone_info}}, account=account)
    if tryon_failed and out["tryon"].get("status") != "ready":
        out["tryon"]["line"] = TRYON_FAILED_LINE
    out["notice"] = notice
    # The raw YouCam code stays in the stored row; the user only ever sees the plain notice.
    out["tone_check"] = {"ok": bool(tone_info.get("ok")), "strictness": tone_info.get("strictness")}
    return out


@app.post("/api/basket/precheck")
async def basket_precheck(request: Request, image: UploadFile = File(...),
                          yaw: float | None = Form(None), pitch: float | None = Form(None),
                          roll: float | None = Form(None)):
    """Free check of one basket photo: one face fully in frame, not a side profile, not too dark.
    Zero YouCam calls, nothing stored. Returns pass, or one plain fix."""
    PRECHECK_LIMITER.check(G.client_ip(request))
    raw = await image.read(P.MAX_UPLOAD_BYTES + 1)
    try:
        prep = _prepare(raw, "sd", None, "upload", yaw, pitch, roll)
    except (F.Refusal, P.UploadRefused) as e:
        return {"ok": False, "code": e.code, "message": e.fix, "pose": None, "luminance": None,
                "rule": PO.thresholds()}
    except F.DetectorUnavailable as e:
        raise _refusal(e)
    try:
        return _photo_check(prep)
    finally:
        prep.cleanup()


@app.post("/api/basket/scan")
async def basket_scan(request: Request, image: UploadFile | None = File(None),
                      answers: str = Form("{}"), persona: str = Form("riya"),
                      yaw: float | None = Form(None), pitch: float | None = Form(None),
                      roll: float | None = Form(None), profile: str = Form(""),
                      x_live_passcode: str | None = Header(None),
                      authorization: str | None = Header(None)):
    """A selfie -> face map + basket + try-on. Live only with DEMO_MODE=0 and the passcode; any
    other case replays the demo persona's prepared face, labelled, and never calls YouCam.
    A live photo passes the free precheck (app/pose.py) before any unit is spent."""
    SCAN_LIMITER.check(G.client_ip(request))
    try:
        ans = json.loads(answers or "{}")
        if not isinstance(ans, dict):
            raise ValueError
    except ValueError:
        raise HTTPException(422, "answers must be a JSON object")
    ans = {**(DF.load_face(persona) or {}).get("answers", {}), **{k: str(v) for k, v in ans.items()}}
    account = None
    if profile:  # a logged-in basket: the user's own history, never a demo persona's
        uid = AU.current_user(authorization)
        account = (uid, AC.basket_history(uid, _profile_use(profile)))
        ans = {k: str(v) for k, v in json.loads(answers or "{}").items()}  # no persona answers
    want, reason = G.scan_source(x_live_passcode)
    if want != "live" or image is None:
        return _replay_basket(persona, ans, reason or "no_photo", account=account)
    raw = await image.read()
    try:
        prep = _prepare(raw, "sd", None, "upload", yaw, pitch, roll)
    except (F.Refusal, P.UploadRefused, F.DetectorUnavailable) as e:
        raise _refusal(e)
    try:
        chk = _photo_check(prep)
        if not chk["ok"]:
            raise HTTPException(422, {"code": chk["code"], "message": chk["message"]})
        res = _live_basket(prep, ans, account)
    except YouCamError as e:
        raise HTTPException(503, e.friendly)
    finally:
        prep.cleanup()
    if res and "_replay" in res:
        return _replay_basket(persona, ans, res["_replay"], res["_notice"], account=account)
    return res


@app.get("/api/meta")
def meta():
    """Rules the UI needs to show, straight from the engine so copy never drifts."""
    return {"stop_symptoms": sorted(E.STOP_SYMPTOMS), "verdict_text": {v.value: m for v, m in E.VERDICT_TEXT.items()},
            "tolerances": E.TOLERANCES, "min_band": E.MIN_BAND, "capture": F.describe(),
            "record_types": [r.value for r in D.RecordType], "rules": [D.RULE_VERSION, E.RULE_VERSION],
            # The new engines' own rules and vocabulary, so the UI never hard-codes a list.
            "outcomes": {"values": [o.value for o in OC.Outcome], "labels": OC.OUTCOME_LABEL,
                         "too_early": OC.TOO_EARLY, "suited_min_weeks": OC.SUITED_MIN_WEEKS,
                         "zones": list(OC.FACE_ZONES)},
            "cartcheck": {"ladder": [r.value for r in CKT.LADDER], "labels": CKT.RUNG_LABEL,
                          "unknown_label": CKT.UNKNOWN_LABEL, "no_scan_line": CKT.NO_SCAN_LINE},
            "patterns": {"tiers": [t.value for t in PAT.Tier], "labels": PAT.TIER_LABEL},
            "triage": {"window_weeks": list(TRI.WINDOW_WEEKS), "long_use_weeks": TRI.LONG_USE_WEEKS,
                       "purge_settle_weeks": TRI.PURGE_SETTLE_WEEKS},
            "engine_rules": [D.RULE_VERSION, E.RULE_VERSION, OC.RULE_VERSION, PAT.RULE_VERSION,
                             CKT.RULE_VERSION, TRI.RULE_VERSION, WB.RULE_VERSION, B.RULE_VERSION,
                             PAT.FAM.FAMILIES_VERSION, BK.RULE_VERSION, ND.RULE_VERSION, UT.RULE_VERSION,
                             CH.RULE_VERSION, PC.RULE_VERSION, BK.LF.RULE_VERSION, BK.SP.RULE_VERSION]}


def build_scene(name: str) -> dict:
    """Write one guided-demo scene (app/scenes.py). The verdict comes from GET /evidence as usual."""
    return S.build(name, put, all_, delete, CATALOG)


@app.get("/api/demo/scenes")
def demo_scenes():
    return {"scenes": list(S.SCENES), "available": demo_mode()}


@app.post("/api/demo/scene/{name}")
def demo_scene(name: str):
    """Load a prepared scene for the guided demo. Only in DEMO_MODE, where no units are ever spent."""
    if not demo_mode():
        raise HTTPException(403, "The guided demo runs only when the server is in demo mode.")
    if name not in S.SCENES:
        raise HTTPException(404, f"Unknown scene {name!r}")
    try:
        return build_scene(name)
    except demo.FixtureError as e:
        raise HTTPException(503, str(e))


@app.post("/api/demo/reset")
def demo_reset():
    """Wipe local data between demo takes. Only available in DEMO_MODE."""
    if not demo_mode():
        raise HTTPException(403, "Reset is only available in DEMO_MODE.")
    with _db() as con:
        for k in KINDS:
            con.execute(f"DELETE FROM {k}")
    return {"reset": True}


# ---------------------------------------------------------------- accounts (/api/me)
# Every endpoint here needs a verified Supabase token (app/auth.py); the user id comes only from
# it. The demo never calls these, and nothing here touches the guest / demo tables except reading
# the one basket a user asks to save. Face photos are never stored: only results (app/accounts.py).
@app.middleware("http")
async def no_store_user_data(request: Request, call_next):
    """Account responses, and anything sent with a sign-in token, are never cached by anyone."""
    resp = await call_next(request)
    if request.url.path.startswith("/api/me") or request.headers.get("authorization"):
        resp.headers["Cache-Control"] = "no-store, private"
        resp.headers["Vary"] = "Authorization"
    return resp


class ProfileIn(BaseModel):
    display_name: str = Field("", max_length=60)
    finish_goal: Literal["dewy", "natural", "matte"] | None = None
    budget: Literal["under_700", "under_1000", "any"] | None = None
    beginner: bool = False


class MeRecordIn(RecordIn):
    clinician_confirmed: bool = False


class SaveBasketIn(BaseModel):
    basket_id: str = Field(min_length=1, max_length=40)


class ImportIn(BaseModel):
    chips: list[ChipIn] = Field(default_factory=list, max_length=40)
    records: list[RecordIn] = Field(default_factory=list, max_length=100)
    shelf: list[str] = Field(default_factory=list, max_length=60)


def _valid_chips(chips: list[ChipIn]) -> list[dict]:
    try:
        built = [CH.Chip(**c.model_dump()) for c in chips]
    except ValueError as e:
        raise HTTPException(422, str(e))
    keep = ("chip", "reaction", "product_name", "confirmed_allergy", "usual_spots_settled", "purge_choice")
    return [{k: v for k, v in c.to_dict().items() if k in keep} for c in built]


def _valid_record(r: RecordIn) -> dict:
    try:
        D.HistoryRecord(r.type, r.product_id, r.ingredient, r.note)
    except ValueError as e:
        raise HTTPException(422, str(e))
    if r.product_id and r.product_id not in CATALOG:
        raise HTTPException(404, f"Unknown product {r.product_id}")
    return {"type": r.type.value, "product_id": r.product_id, "ingredient": r.ingredient, "note": r.note}


def _valid_shelf(ids: list[str]) -> list[str]:
    bad = [i for i in ids if i not in CATALOG]
    if bad:
        raise HTTPException(404, f"Unknown products {bad}")
    return list(dict.fromkeys(ids))


@app.get("/api/me")
def me(uid: str = Depends(AU.current_user)):
    profile, created = AC.ensure_profile(uid)
    return {"profile": profile, "first_login": created, "photo_line": AC.PHOTO_LINE}


@app.put("/api/me/profile")
def me_profile(body: ProfileIn, uid: str = Depends(AU.current_user)):
    return AC.set_profile(uid, body.display_name.strip(), body.finish_goal, body.budget, body.beginner)


@app.get("/api/me/history")
def me_history(uid: str = Depends(AU.current_user)):
    return {"chips": AC.list_history(uid, "chip"), "records": AC.list_history(uid, "record"),
            "catalogue": CH.catalogue(), "reactions": CH.REACTIONS}


@app.put("/api/me/chips")
def me_chips(body: ChipsIn, uid: str = Depends(AU.current_user)):
    return {"chips": AC.replace_chips(uid, _valid_chips(body.chips))}


@app.post("/api/me/history")
def me_add_record(body: MeRecordIn, uid: str = Depends(AU.current_user)):
    # Clinician-confirmed: the existing confirmed_allergy record type, or the user's own tick.
    confirmed = body.clinician_confirmed or body.type == D.RecordType.CONFIRMED_ALLERGY
    return AC.add_history(uid, "record", _valid_record(body), confirmed)


@app.delete("/api/me/history/{rid}")
def me_delete_record(rid: str, uid: str = Depends(AU.current_user)):
    if not AC.delete_history(uid, rid):
        raise HTTPException(404, "Not in your history.")
    return {"deleted": rid}


@app.get("/api/me/shelf")
def me_shelf(uid: str = Depends(AU.current_user)):
    return {"product_ids": AC.get_shelf(uid)}


@app.put("/api/me/shelf")
def me_set_shelf(body: ShelfIn, uid: str = Depends(AU.current_user)):
    return {"product_ids": AC.set_shelf(uid, _valid_shelf(body.product_ids))}


@app.get("/api/me/baskets")
def me_baskets(uid: str = Depends(AU.current_user)):
    return AC.list_baskets(uid)


@app.post("/api/me/baskets")
def me_save_basket(body: SaveBasketIn, uid: str = Depends(AU.current_user)):
    """Save the basket the user was looking at. A prepared demo basket is saved labelled as demo
    data and adds no scan: only a scan of the user's own face becomes a scan row."""
    row = get("baskets", body.basket_id)
    if row is None or row.get("owner") not in (None, uid):  # someone else's profile basket: not found
        raise HTTPException(404, "That basket isn't on the server any more. Build it again, then save.")
    is_demo = bool(row.get("demo")) or row.get("source") == "replay"
    saved = AC.save_basket(uid, {**row["basket"], "source": row.get("source")}, is_demo)
    if not is_demo:
        AC.add_scan(uid, AC.scan_from_basket(row["basket"]))
    return saved


@app.get("/api/me/baskets/{bid}")
def me_basket(bid: str, uid: str = Depends(AU.current_user)):
    b = AC.get_basket(uid, bid)
    if b is None:
        raise HTTPException(404, "Not one of your saved baskets.")
    return b


@app.delete("/api/me/baskets/{bid}")
def me_delete_basket(bid: str, uid: str = Depends(AU.current_user)):
    if not AC.delete_basket(uid, bid):
        raise HTTPException(404, "Not one of your saved baskets.")
    return {"deleted": bid}


class ProfileUseIn(BaseModel):
    """The saved ids kept for this one basket. A missing list keeps them all."""
    chips: list[str] | None = Field(None, max_length=100)
    records: list[str] | None = Field(None, max_length=200)
    shelf: list[str] | None = Field(None, max_length=100)


class MeBasketIn(BaseModel):
    answers: dict[str, str] = {}
    persona: Literal["riya", "beginner"] = "riya"  # the prepared face only, never its history
    use: ProfileUseIn = Field(default_factory=ProfileUseIn)
    update_profile: bool = False


def _profile_use(raw: str) -> dict:
    try:
        return ProfileUseIn.model_validate_json(raw).model_dump()
    except ValueError:
        raise HTTPException(422, "profile must be a JSON object of saved ids")


def _profile_from_answers(uid: str, answers: dict) -> dict:
    """"Update my profile too": this basket's finish, budget and beginner answers become the profile's."""
    p, _ = AC.ensure_profile(uid)
    finish = answers.get("finish") if answers.get("finish") in AC.FINISHES else p["finish_goal"]
    budget = answers.get("budget") if answers.get("budget") in AC.BUDGETS else p["budget"]
    beginner = answers["history"] == "new" if answers.get("history") in ("new", "use") else p["beginner"]
    return AC.set_profile(uid, p["display_name"], finish, budget, beginner)


@app.post("/api/me/basket")
def me_basket_build(body: MeBasketIn, uid: str = Depends(AU.current_user)):
    """A logged-in basket on a prepared face: the answers the user confirmed (pre-filled from the
    profile) and their own history and shelf. The profile changes only with update_profile."""
    answers = {k: str(v) for k, v in body.answers.items()}
    if body.update_profile:
        _profile_from_answers(uid, answers)
    return _replay_basket(body.persona, answers, "no_photo",
                          account=(uid, AC.basket_history(uid, body.use.model_dump())))


@app.get("/api/me/scans")
def me_scans(uid: str = Depends(AU.current_user)):
    return {"scans": AC.list_scans(uid), "photo_line": AC.PHOTO_LINE}


@app.post("/api/me/import")
def me_import(body: ImportIn, uid: str = Depends(AU.current_user)):
    """The history and shelf saved on this device, added only after the user said yes."""
    chips = _valid_chips(body.chips)
    records = [_valid_record(r) for r in body.records]
    shelf = _valid_shelf(body.shelf)
    have = {c["chip"] for c in AC.list_history(uid, "chip")}
    for c in chips:
        if c["chip"] not in have:
            AC.add_history(uid, "chip", c, bool(c.get("confirmed_allergy")))
    for r in records:
        AC.add_history(uid, "record", r, r["type"] == D.RecordType.CONFIRMED_ALLERGY.value)
    if shelf:
        AC.set_shelf(uid, list(dict.fromkeys(AC.get_shelf(uid) + shelf)))
    return {"chips": len(chips), "records": len(records), "shelf": len(shelf)}


@app.get("/api/me/export")
def me_export(uid: str = Depends(AU.current_user)):
    return AC.export(uid)


@app.delete("/api/me")
def me_delete(uid: str = Depends(AU.current_user)):
    """Every row first, then the sign-in account itself (service role key, server-side only)."""
    rows = AC.delete_all(uid)
    try:
        AU.delete_auth_user(uid)
    except AU.AuthError as e:
        raise HTTPException(502, f"Your saved data is deleted, but the account itself couldn't be removed "
                                 f"yet: {e} Try again in a minute.")
    return {"deleted": True, "rows": rows}
