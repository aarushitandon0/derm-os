"""Account storage: profiles, scans (results only), history, shelf and saved baskets.

Every function takes the verified user id (app/auth.py) and every query is scoped by it, so one
user can never read, change or delete another user's rows. The demo never calls these.

Face photos are never stored, by anyone. A scan row holds results only (zone types, concern
values, undertone and how it was worked out, engine versions), and anything saved passes
`results_only` first, which drops every image, mask, render, URL and file reference.
"""
from __future__ import annotations

import re
import uuid
from typing import Any

from . import db as DBL
from . import findings as FD

# A key that names a picture or a link, or a value that is one, never reaches the database.
_BANNED_KEY = re.compile(r"photo|image|selfie|img|url|mask|render|file_id|src_file|thumbnail|avatar", re.I)
_BANNED_VALUE = re.compile(r"^(data:|https?://|/media/|blob:)", re.I)

FINISHES = ("dewy", "natural", "matte")
BUDGETS = ("under_700", "under_1000", "any")  # the basket's own (app/basket.py)
PHOTO_LINE = "Your photo is never stored, only the results."


def results_only(v: Any, keep: frozenset[str] = frozenset()) -> Any:
    """A copy with every picture, mask, render, link and file reference removed. `keep` is the
    app's own curated source links (curated_links()): only those exact strings survive."""
    if isinstance(v, dict):
        return {k: results_only(x, keep) for k, x in v.items()
                if not _BANNED_KEY.search(str(k)) or (isinstance(x, str) and x in keep)}
    if isinstance(v, list):
        return [results_only(x, keep) for x in v
                if not (isinstance(x, str) and _BANNED_VALUE.match(x) and x not in keep)]
    if isinstance(v, str) and _BANNED_VALUE.match(v) and v not in keep:
        return None
    return v


# A link to YouCam, to a stored file or to a picture is never kept, even if listed in the data.
_NEVER_LINK = re.compile(r"youcam|perfectcorp|/media/|\.(png|jpe?g|webp|gif|svg)(\?|$)", re.I)


def curated_links() -> frozenset[str]:
    """The https source links in the app's own data (app/needs.json "facts")."""
    from . import needs as N
    urls = (f.get("url") for f in N.data().get("facts", []))
    return frozenset(u for u in urls if isinstance(u, str) and u.startswith("https://")
                     and not _NEVER_LINK.search(u))


def clean_basket(basket: dict) -> dict:
    """What a saved basket keeps: results only, plus the start plan's curated source links."""
    clean = results_only(basket)
    if isinstance(basket.get("start_plan"), dict):
        clean["start_plan"] = results_only(basket["start_plan"], curated_links())
    return clean


def _id() -> str:
    return uuid.uuid4().hex[:12]


# ---------------------------------------------------------------- profile
def get_profile(uid: str) -> dict | None:
    with DBL.connect() as con:
        r = con.execute("SELECT user_id, display_name, finish_goal, budget, beginner, created_at, updated_at "
                        "FROM profiles WHERE user_id = ?", (uid,)).fetchone()
    if not r:
        return None
    return {"user_id": r[0], "display_name": r[1] or "", "finish_goal": r[2], "budget": r[3],
            "beginner": bool(r[4]), "created_at": DBL.ts(r[5]), "updated_at": DBL.ts(r[6])}


def ensure_profile(uid: str) -> tuple[dict, bool]:
    """(profile, created_now). Created empty on the first call after sign-up."""
    p = get_profile(uid)
    if p:
        return p, False
    now = DBL.now()
    with DBL.connect() as con:
        con.execute("INSERT INTO profiles (user_id, display_name, finish_goal, budget, beginner, created_at, "
                    "updated_at) VALUES (?, '', NULL, NULL, ?, ?, ?) ON CONFLICT (user_id) DO NOTHING",
                    (uid, False, now, now))
    return get_profile(uid), True


def set_profile(uid: str, display_name: str, finish_goal: str | None, budget: str | None, beginner: bool) -> dict:
    ensure_profile(uid)
    with DBL.connect() as con:
        con.execute("UPDATE profiles SET display_name = ?, finish_goal = ?, budget = ?, beginner = ?, "
                    "updated_at = ? WHERE user_id = ?",
                    (display_name, finish_goal, budget, bool(beginner), DBL.now(), uid))
    return get_profile(uid)


# ---------------------------------------------------------------- history (chips + records)
def list_history(uid: str, kind: str | None = None) -> list[dict]:
    q = "SELECT id, kind, body, clinician_confirmed, created_at FROM user_history WHERE user_id = ?"
    args: tuple = (uid,)
    if kind:
        q, args = q + " AND kind = ?", (uid, kind)
    with DBL.connect() as con:
        rows = con.execute(q + " ORDER BY created_at, id", args).fetchall()
    return [{"id": r[0], "kind": r[1], **DBL.loads(r[2]), "clinician_confirmed": bool(r[3]),
             "created_at": DBL.ts(r[4])} for r in rows]


def add_history(uid: str, kind: str, body: dict, clinician_confirmed: bool) -> dict:
    rid = _id()
    with DBL.connect() as con:
        con.execute("INSERT INTO user_history (id, user_id, kind, body, clinician_confirmed, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (rid, uid, kind, DBL.dumps(results_only(body)), bool(clinician_confirmed), DBL.now()))
    return next(h for h in list_history(uid) if h["id"] == rid)


def replace_chips(uid: str, chips: list[dict]) -> list[dict]:
    """The whole chip list, like the guest PUT /api/chips."""
    with DBL.connect() as con:
        con.execute("DELETE FROM user_history WHERE user_id = ? AND kind = 'chip'", (uid,))
    for c in chips:
        add_history(uid, "chip", c, bool(c.get("confirmed_allergy")))
    return list_history(uid, "chip")


def delete_history(uid: str, rid: str) -> bool:
    with DBL.connect() as con:
        n = con.execute("DELETE FROM user_history WHERE id = ? AND user_id = ?", (rid, uid)).rowcount
    return n > 0


# ---------------------------------------------------------------- shelf
def get_shelf(uid: str) -> list[str]:
    with DBL.connect() as con:
        r = con.execute("SELECT product_ids FROM user_shelf WHERE user_id = ?", (uid,)).fetchone()
    return list(DBL.loads(r[0])) if r else []


def set_shelf(uid: str, ids: list[str]) -> list[str]:
    with DBL.connect() as con:
        con.execute("INSERT INTO user_shelf (user_id, product_ids, updated_at) VALUES (?, ?, ?) "
                    "ON CONFLICT (user_id) DO UPDATE SET product_ids = excluded.product_ids, "
                    "updated_at = excluded.updated_at", (uid, DBL.dumps(list(ids)), DBL.now()))
    return get_shelf(uid)


# ---------------------------------------------------------------- the basket, from the profile
def basket_history(uid: str, use: dict | None = None) -> dict:
    """This user's own history and shelf, for one basket. `use` lists the saved ids kept for this
    basket ({"chips": [...], "records": [...], "shelf": [...]}; a missing key keeps them all). It
    only narrows: an id that isn't the user's own is ignored. Clinician-confirmed items are always
    kept, and come back in "always" as hard-block records the basket applies whatever the answers."""
    from . import chips as CH
    from . import decision as D
    use = use or {}

    def kept(rows: list[dict], key: str) -> list[dict]:
        ids = use.get(key)
        return rows if ids is None else [r for r in rows if r["clinician_confirmed"] or r["id"] in set(ids)]

    chips = kept(list_history(uid, "chip"), "chips")
    recs = kept(list_history(uid, "record"), "records")
    shelf = get_shelf(uid)
    if use.get("shelf") is not None:
        shelf = [p for p in shelf if p in set(use["shelf"])]
    chip_rows = [{k: c.get(k) for k in ("chip", "reaction", "product_name", "confirmed_allergy",
                                        "usual_spots_settled", "purge_choice")} for c in chips]
    records, always = [], []
    for r in recs:
        t = D.RecordType(r["type"])
        if r["clinician_confirmed"] and r.get("ingredient"):
            t = D.RecordType.CONFIRMED_ALLERGY  # a doctor confirmed it: the hard-block type
        rec = D.HistoryRecord(t, r.get("product_id"), r.get("ingredient"), r.get("note", ""))
        (always if r["clinician_confirmed"] else records).append(rec)
    always += CH.records_from([c for c in CH.parse_all(chip_rows) if c.confirmed_allergy])
    return {"records": records, "always": always, "chips": chip_rows, "shelf": shelf}


# ---------------------------------------------------------------- scans (results only)
def scan_from_basket(basket: dict) -> dict:
    inp = basket.get("inputs") or {}
    ut = inp.get("undertone") or {}
    return {"zone_types": {z: r.get("type") for z, r in (inp.get("zones") or {}).items()},
            "concern_values": dict(inp.get("measured") or {}),
            "undertone": ut.get("tone"), "undertone_method": ut.get("label"),
            "engine_versions": dict(inp.get("rule_versions") or {})}


def add_scan(uid: str, scan: dict) -> dict:
    sid = _id()
    s = results_only(scan)
    with DBL.connect() as con:
        con.execute("INSERT INTO scans (id, user_id, created_at, zone_types, concern_values, undertone, "
                    "undertone_method, engine_versions) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (sid, uid, DBL.now(), DBL.dumps(s.get("zone_types") or {}),
                     DBL.dumps(s.get("concern_values") or {}), s.get("undertone"), s.get("undertone_method"),
                     DBL.dumps(s.get("engine_versions") or {})))
    return {"id": sid, **s}


def list_scans(uid: str) -> list[dict]:
    with DBL.connect() as con:
        rows = con.execute("SELECT id, created_at, zone_types, concern_values, undertone, undertone_method, "
                           "engine_versions FROM scans WHERE user_id = ? ORDER BY created_at DESC, id",
                           (uid,)).fetchall()
    return [{"id": r[0], "created_at": DBL.ts(r[1]), "zone_types": DBL.loads(r[2]),
             "concern_values": DBL.loads(r[3]), "undertone": r[4], "undertone_method": r[5],
             "engine_versions": DBL.loads(r[6]),
             # The same "What your scan found" lines as the face map, from the saved values.
             "findings": FD.from_saved(DBL.loads(r[2]), DBL.loads(r[3]))} for r in rows]


# ---------------------------------------------------------------- saved baskets
def save_basket(uid: str, basket: dict, demo: bool) -> dict:
    bid = _id()
    clean = clean_basket(basket)
    versions = dict((clean.get("inputs") or {}).get("rule_versions") or {})
    with DBL.connect() as con:
        con.execute("INSERT INTO user_baskets (id, user_id, created_at, demo, basket, start_plan, engine_versions) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (bid, uid, DBL.now(), bool(demo), DBL.dumps(clean), DBL.dumps(clean.get("start_plan")),
                     DBL.dumps(versions)))
    return get_basket(uid, bid)


def _basket_row(r) -> dict:
    return {"id": r[0], "created_at": DBL.ts(r[1]), "demo": bool(r[2]), "basket": DBL.loads(r[3]),
            "start_plan": DBL.loads(r[4]), "engine_versions": DBL.loads(r[5])}


def list_baskets(uid: str) -> list[dict]:
    with DBL.connect() as con:
        rows = con.execute("SELECT id, created_at, demo, basket, start_plan, engine_versions FROM user_baskets "
                           "WHERE user_id = ? ORDER BY created_at DESC, id", (uid,)).fetchall()
    return [_basket_row(r) for r in rows]


def get_basket(uid: str, bid: str) -> dict | None:
    with DBL.connect() as con:
        r = con.execute("SELECT id, created_at, demo, basket, start_plan, engine_versions FROM user_baskets "
                        "WHERE id = ? AND user_id = ?", (bid, uid)).fetchone()
    return _basket_row(r) if r else None


def delete_basket(uid: str, bid: str) -> bool:
    with DBL.connect() as con:
        n = con.execute("DELETE FROM user_baskets WHERE id = ? AND user_id = ?", (bid, uid)).rowcount
    return n > 0


# ---------------------------------------------------------------- export + delete
def export(uid: str) -> dict:
    return {"profile": get_profile(uid), "history": list_history(uid), "shelf": get_shelf(uid),
            "scans": list_scans(uid), "baskets": list_baskets(uid),
            "note": PHOTO_LINE + " This file is everything derm//os keeps for your account."}


def delete_all(uid: str) -> dict:
    """Every row this user owns, in every account table."""
    out = {}
    with DBL.connect() as con:
        for t in DBL.USER_TABLES:
            out[t] = con.execute(f"DELETE FROM {t} WHERE user_id = ?", (uid,)).rowcount
    return out
