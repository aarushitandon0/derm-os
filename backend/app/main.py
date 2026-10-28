"""derm//os API.

Run:  uvicorn app.main:app --reload  (from backend/)
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import sqlite3
import tempfile
import threading
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from contextlib import asynccontextmanager
from dataclasses import dataclass

from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import settings  # noqa: F401  (loads backend/.env first)
from . import decision as D
from . import demo
from . import evidence as E
from . import guard as G
from . import photometa as P
from . import facecrop as F
from . import llm as L
from . import scenes as S
from .fingerprint import Fingerprint, measure_normalised
from .settings import flag
from .youcam import (YouCamClient, YouCamError, actions_for_mode, check_unit_reserve, delete_task_quietly,
                     download_masks, scan_cost_from, strip_urls, validate_actions)

log = logging.getLogger("dermos")
BACKEND_DIR = Path(__file__).resolve().parents[1]
DB_PATH = Path(os.environ.get("DERMOS_DB", BACKEND_DIR / "dermos.db"))
MEDIA_DIR = Path(os.environ.get("DERMOS_MEDIA", BACKEND_DIR / "media"))
MEDIA_DIR.mkdir(parents=True, exist_ok=True)
CATALOG = D.load_catalog()
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

@asynccontextmanager
async def lifespan(_app: FastAPI):
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
# One table per kind, JSON bodies. Small on purpose: swap for Postgres by
# replacing these four functions.
KINDS = ("history", "shelf", "captures", "trials")


def _db() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    for k in KINDS:
        con.execute(f"CREATE TABLE IF NOT EXISTS {k} (id TEXT PRIMARY KEY, body TEXT, created TEXT)")
    # Live YouCam units spent through this server, for the judge caps. Not touched by demo reset.
    con.execute("CREATE TABLE IF NOT EXISTS spend (id TEXT PRIMARY KEY, day TEXT, units REAL, state TEXT, at TEXT)")
    return con


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


def settle_units(hid: str | None, spent: bool) -> None:
    """A scan that went through stays counted; one that failed (YouCam doesn't charge) is released."""
    if not hid:
        return
    with _SPEND_LOCK, _db() as con:
        if spent:
            con.execute("UPDATE spend SET state = 'spent' WHERE id = ?", (hid,))
        else:
            con.execute("DELETE FROM spend WHERE id = ?", (hid,))


def put(kind: str, body: dict, id: str | None = None) -> dict:
    id = id or body.get("id") or uuid.uuid4().hex[:12]
    body = {**body, "id": id}
    with _db() as con:
        con.execute(f"INSERT OR REPLACE INTO {kind} VALUES (?, ?, ?)",
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
            "llm": L.get_provider() is not None}


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
    log.warning("Face detector unavailable; photo refused.")
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


@app.get("/api/meta")
def meta():
    """Rules the UI needs to show, straight from the engine so copy never drifts."""
    return {"stop_symptoms": sorted(E.STOP_SYMPTOMS), "verdict_text": {v.value: m for v, m in E.VERDICT_TEXT.items()},
            "tolerances": E.TOLERANCES, "min_band": E.MIN_BAND, "capture": F.describe(),
            "record_types": [r.value for r in D.RecordType], "rules": [D.RULE_VERSION, E.RULE_VERSION]}


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
