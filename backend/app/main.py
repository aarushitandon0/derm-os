"""derm//os API.

Run:  uvicorn app.main:app --reload  (from backend/)
"""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from . import settings  # noqa: F401  (loads backend/.env first)
from . import decision as D
from . import evidence as E
from .fingerprint import Fingerprint, measure
from .youcam import YouCamClient, YouCamError, validate_actions

DB_PATH = Path(os.environ.get("DERMOS_DB", Path(__file__).resolve().parents[1] / "dermos.db"))
CATALOG = D.load_catalog()

app = FastAPI(title="derm//os", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
                   allow_methods=["*"], allow_headers=["*"])


# ---------------------------------------------------------------- storage
# One table per kind, JSON bodies. Small on purpose: swap for Postgres by
# replacing these four functions.
KINDS = ("history", "shelf", "captures", "trials")


def _db() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    for k in KINDS:
        con.execute(f"CREATE TABLE IF NOT EXISTS {k} (id TEXT PRIMARY KEY, body TEXT, created TEXT)")
    return con


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


# ---------------------------------------------------------------- basics
@app.get("/api/health")
def health():
    return {"ok": True, "youcam_key": bool(os.environ.get("YOUCAM_API_KEY")),
            "rules": [D.RULE_VERSION, E.RULE_VERSION]}


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


@app.post("/api/scan")
async def scan(image: UploadFile = File(...),
               actions: str = Form("redness,texture,acne,pore,oiliness,moisture"),
               trial_id: str | None = Form(None),
               phase: Literal["baseline", "checkin", "free"] = Form("free"),
               face_ratio: float | None = Form(None), yaw: float | None = Form(None),
               pitch: float | None = Form(None), roll: float | None = Form(None)):
    acts = [a.strip() for a in actions.split(",") if a.strip()]
    try:
        mode = validate_actions(acts)
    except ValueError as e:
        raise HTTPException(422, str(e))
    suffix = Path(image.filename or "x.jpg").suffix or ".jpg"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(await image.read())
        path = tmp.name
    try:
        fp = measure(path, face_ratio, yaw, pitch, roll)
        need = 1080 if mode == "hd" else 480
        if fp.short_side < need:
            raise HTTPException(422, f"Photo short side is {fp.short_side}px; {mode.upper()} needs {need}px.")
        try:
            res = YouCamClient().analyze(path, acts)
        except YouCamError as e:
            raise HTTPException(502 if e.code not in (None, "no_key") else 503, e.friendly)
    finally:
        os.unlink(path)

    cap = put("captures", {"trial_id": trial_id, "phase": phase, "mode": mode, "actions": acts,
                           "fingerprint": fp.to_dict(), "raw_scores": res.raw_scores(),
                           "result": res.to_dict(), "taken_at": datetime.now(timezone.utc).isoformat()})
    # Immediate feedback: is this capture comparable to the trial baseline?
    check = None
    if trial_id and phase == "checkin":
        base = [_to_capture(c) for c in all_("captures") if c.get("trial_id") == trial_id and c["phase"] == "baseline"]
        if base:
            comp = E.compare_conditions(base, [_to_capture(cap)])
            check = {"comparable": comp.comparable, "reasons": comp.reasons, "fixes": comp.fixes}
    return {"capture": cap, "comparability": check}


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
    ctx = E.TrialContext(new_leave_on_products=1 + len(last.get("other_new_leave_on", [])),
                         symptoms=last.get("symptoms", []))
    report = E.evaluate(base, follow, ctx, concerns=[t["goal_concern"]])
    return {"trial": t, "report": report.to_dict()}
