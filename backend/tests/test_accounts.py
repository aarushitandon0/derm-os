"""Accounts: token checks, per-user isolation, demo separation, no photos, account deletion.

No network: a local RSA key signs the tokens and the JWKS fetch is replaced. SQLite only.
"""
import base64
import json
import re
import sqlite3
import time
from pathlib import Path

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

SUPA = "https://testproj.supabase.co"
ISS = SUPA + "/auth/v1"
SECRET = "legacy-test-secret-at-least-32-bytes-long!!"
A = "11111111-1111-4111-8111-111111111111"
B = "22222222-2222-4222-8222-222222222222"
MIGRATION = Path(__file__).resolve().parents[1] / "migrations" / "001_accounts.sql"
BANNED = re.compile(r"photo|image|selfie|img|url", re.I)

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_OTHER = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _jwk(key, kid):
    d = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    return {**d, "kid": kid, "alg": "RS256", "use": "sig"}


def tok(sub=A, *, key=_KEY, kid="k1", alg="RS256", **claims):
    now = int(time.time())
    body = {"sub": sub, "aud": "authenticated", "iss": ISS, "iat": now, "exp": now + 3600,
            "role": "authenticated", **claims}
    body = {k: v for k, v in body.items() if v is not None}
    return jwt.encode(body, key, algorithm=alg, headers={"kid": kid} if kid else None)


def bearer(t):
    return {"Authorization": f"Bearer {t}"}


@pytest.fixture()
def env(tmp_path, monkeypatch):
    db = tmp_path / "t.db"
    monkeypatch.setenv("DERMOS_DB", str(db))
    monkeypatch.setenv("DERMOS_MEDIA", str(tmp_path / "media"))
    monkeypatch.setenv("DEMO_MODE", "1")
    monkeypatch.setenv("YOUCAM_API_KEY", "")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("SUPABASE_URL", SUPA)
    monkeypatch.delenv("SUPABASE_JWT_SECRET", raising=False)
    import importlib
    import app.auth as AU
    import app.main as m
    importlib.reload(m)
    AU.reset_cache()
    calls = {"jwks": 0, "deleted": []}

    def fake_jwks(url):
        assert url == ISS + "/.well-known/jwks.json"
        calls["jwks"] += 1
        return {"keys": [_jwk(_KEY, "k1")]}

    monkeypatch.setattr(AU, "fetch_jwks", fake_jwks)
    monkeypatch.setattr(AU, "delete_auth_user", lambda uid: calls["deleted"].append(uid))
    return {"c": TestClient(m.app), "db": db, "calls": calls, "m": m, "AU": AU}


def user_rows(db: Path) -> dict:
    con = sqlite3.connect(db)
    try:
        from app.db import USER_TABLES
        return {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in USER_TABLES}
    finally:
        con.close()


def demo_basket(c) -> dict:
    r = c.post("/api/basket", json={"answers": {}, "persona": "riya"})
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------- token checks
def test_valid_token_reads_the_user_from_the_token(env):
    r = env["c"].get("/api/me", headers=bearer(tok()))
    assert r.status_code == 200, r.text
    assert r.json()["profile"]["user_id"] == A
    assert r.json()["first_login"] is True
    assert env["c"].get("/api/me", headers=bearer(tok())).json()["first_login"] is False
    assert r.headers["cache-control"].startswith("no-store")


@pytest.mark.parametrize("name,make", [
    ("expired", lambda: tok(exp=int(time.time()) - 60)),
    ("wrong aud", lambda: tok(aud="anon")),
    ("wrong iss", lambda: tok(iss="https://evil.supabase.co/auth/v1")),
    ("no exp", lambda: tok(exp=None)),
    ("other key, same kid", lambda: tok(key=_OTHER)),
    ("unknown kid", lambda: tok(kid="nope")),
    ("hs256 with no secret set", lambda: tok(key=SECRET, alg="HS256", kid=None)),
    ("garbage", lambda: "not.a.token"),
])
def test_bad_tokens_get_401(env, name, make):
    r = env["c"].get("/api/me", headers=bearer(make()))
    assert r.status_code == 401, name


def test_tampered_payload_gets_401(env):
    h, p, s = tok(A).split(".")
    body = json.loads(base64.urlsafe_b64decode(p + "=" * (-len(p) % 4)))
    body["sub"] = B
    p2 = base64.urlsafe_b64encode(json.dumps(body).encode()).rstrip(b"=").decode()
    assert env["c"].get("/api/me", headers=bearer(f"{h}.{p2}.{s}")).status_code == 401


def test_alg_none_gets_401(env):
    t = jwt.encode({"sub": A, "aud": "authenticated", "iss": ISS, "exp": int(time.time()) + 60}, None,
                   algorithm="none")
    assert env["c"].get("/api/me", headers=bearer(t)).status_code == 401


def test_hs256_fallback_with_the_legacy_secret(env, monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", SECRET)
    ok = tok(key=SECRET, alg="HS256", kid=None)
    assert env["c"].get("/api/me", headers=bearer(ok)).status_code == 200
    wrong = tok(key="another-secret-that-is-also-32-bytes-long", alg="HS256", kid=None)
    assert env["c"].get("/api/me", headers=bearer(wrong)).status_code == 401
    assert env["c"].get("/api/me", headers=bearer(tok(key=SECRET, alg="HS256", kid=None, aud="x"))).status_code == 401


def test_missing_token_gets_401_on_every_user_endpoint(env):
    c = env["c"]
    for method, path in [("get", "/api/me"), ("put", "/api/me/profile"), ("get", "/api/me/history"),
                         ("put", "/api/me/chips"), ("post", "/api/me/history"), ("delete", "/api/me/history/x"),
                         ("get", "/api/me/shelf"), ("put", "/api/me/shelf"), ("get", "/api/me/baskets"),
                         ("post", "/api/me/baskets"), ("get", "/api/me/baskets/x"), ("delete", "/api/me/baskets/x"),
                         ("get", "/api/me/scans"), ("post", "/api/me/import"), ("get", "/api/me/export"),
                         ("delete", "/api/me")]:
        r = getattr(c, method)(path)
        assert r.status_code == 401, (method, path)
        r = getattr(c, method)(path, headers={"Authorization": "Basic abc"})
        assert r.status_code == 401, (method, path)


def test_jwks_is_cached(env):
    for _ in range(5):
        env["c"].get("/api/me", headers=bearer(tok()))
    assert env["calls"]["jwks"] == 1


def test_no_supabase_url_means_401_not_a_crash(env, monkeypatch):
    monkeypatch.delenv("SUPABASE_URL")
    assert env["c"].get("/api/me", headers=bearer(tok())).status_code == 401
    assert env["c"].get("/api/health").json()["accounts"] is False


def test_demo_needs_no_token(env):
    assert env["c"].get("/api/health").status_code == 200
    assert demo_basket(env["c"])["id"]


# ---------------------------------------------------------------- isolation
def _fill(c, uid):
    h = bearer(tok(uid))
    assert c.put("/api/me/profile", headers=h, json={"display_name": uid[:4], "finish_goal": "matte",
                                                     "budget": "any", "beginner": False}).status_code == 200
    assert c.put("/api/me/chips", headers=h, json={"chips": [{"chip": "vitamin_c", "reaction": "itched"}]}).status_code == 200, \
        c.put("/api/me/chips", headers=h, json={"chips": [{"chip": "vitamin_c", "reaction": "itched"}]}).text
    rec = c.post("/api/me/history", headers=h, json={"type": "avoid", "ingredient": "fragrance", "note": ""}).json()
    pid = next(iter(c.get("/api/catalog").json()))["id"]
    assert c.put("/api/me/shelf", headers=h, json={"product_ids": [pid]}).status_code == 200
    b = c.post("/api/me/baskets", headers=h, json={"basket_id": demo_basket(c)["id"]}).json()
    return {"record": rec["id"], "basket": b["id"]}


def test_user_b_cannot_read_change_or_delete_user_a(env):
    c = env["c"]
    a = _fill(c, A)
    hb = bearer(tok(B))
    assert c.get("/api/me/history", headers=hb).json()["chips"] == []
    assert c.get("/api/me/history", headers=hb).json()["records"] == []
    assert c.get("/api/me/shelf", headers=hb).json()["product_ids"] == []
    assert c.get("/api/me/baskets", headers=hb).json() == []
    assert c.get("/api/me/scans", headers=hb).json()["scans"] == []
    assert c.get(f"/api/me/baskets/{a['basket']}", headers=hb).status_code == 404
    assert c.delete(f"/api/me/baskets/{a['basket']}", headers=hb).status_code == 404
    assert c.delete(f"/api/me/history/{a['record']}", headers=hb).status_code == 404
    assert c.get("/api/me", headers=hb).json()["profile"]["display_name"] == ""
    exp = c.get("/api/me/export", headers=hb).json()
    assert A not in json.dumps(exp)
    # B's writes and B's account deletion leave A untouched.
    c.put("/api/me/chips", headers=hb, json={"chips": []})
    c.put("/api/me/shelf", headers=hb, json={"product_ids": []})
    assert c.delete("/api/me", headers=hb).status_code == 200
    ha = bearer(tok(A))
    assert len(c.get("/api/me/history", headers=ha).json()["chips"]) == 1
    assert len(c.get("/api/me/history", headers=ha).json()["records"]) == 1
    assert len(c.get("/api/me/shelf", headers=ha).json()["product_ids"]) == 1
    assert len(c.get("/api/me/baskets", headers=ha).json()) == 1
    assert c.get("/api/me", headers=ha).json()["profile"]["display_name"] == A[:4]


def test_user_id_in_the_body_or_query_is_ignored(env):
    c = env["c"]
    r = c.put(f"/api/me/profile?user_id={B}", headers=bearer(tok(A)),
              json={"display_name": "x", "user_id": B})
    assert r.status_code == 200 and r.json()["user_id"] == A
    assert c.get("/api/me", headers=bearer(tok(B))).json()["profile"]["display_name"] == ""


# ---------------------------------------------------------------- demo separation
def test_demo_writes_nothing_to_user_tables(env):
    c = env["c"]
    demo_basket(c)
    c.post("/api/basket", json={"answers": {"history": "new"}, "persona": "meera"})
    c.put("/api/chips", json={"chips": [{"chip": "vitamin_c", "reaction": "itched"}]})
    c.post("/api/history", json={"type": "avoid", "ingredient": "fragrance", "note": ""})
    for scene in c.get("/api/demo/scenes").json()["scenes"]:
        c.post(f"/api/demo/scene/{scene}")
    c.post("/api/demo/reset")
    assert sum(user_rows(env["db"]).values()) == 0


def test_demo_reset_leaves_accounts_alone(env):
    c = env["c"]
    _fill(c, A)
    before = user_rows(env["db"])
    assert c.post("/api/demo/reset").status_code == 200
    assert user_rows(env["db"]) == before


def test_saved_demo_basket_is_labelled_and_adds_no_scan(env):
    c = env["c"]
    b = c.post("/api/me/baskets", headers=bearer(tok()), json={"basket_id": demo_basket(c)["id"]}).json()
    assert b["demo"] is True and b["start_plan"] and b["engine_versions"]["basket"]
    assert c.get("/api/me/scans", headers=bearer(tok())).json()["scans"] == []


def test_a_real_basket_saves_results_only_scan(env):
    c, m = env["c"], env["m"]
    built = demo_basket(c)
    row = m.get("baskets", built["id"])
    m.put("baskets", {**row, "demo": False, "source": "live"}, id=row["id"])  # stand-in for a live scan
    c.post("/api/me/baskets", headers=bearer(tok()), json={"basket_id": built["id"]})
    scans = c.get("/api/me/scans", headers=bearer(tok())).json()["scans"]
    assert len(scans) == 1
    s = scans[0]
    assert set(s["zone_types"]) and s["undertone"] and s["undertone_method"] and s["engine_versions"]
    assert not BANNED.search(json.dumps(s))


# ---------------------------------------------------------------- no photos, anywhere
def test_no_column_can_hold_image_bytes_or_an_image_url():
    sql = MIGRATION.read_text(encoding="utf-8")
    code = "\n".join(line.split("--")[0] for line in sql.splitlines())
    assert not re.search(r"\b(bytea|blob|oid|lo)\b", code, re.I)
    cols = re.findall(r"^\s{4}([a-z_]+)\s+(?:uuid|text|jsonb|boolean|timestamptz|real)\b", code, re.M)
    assert len(cols) >= 20
    for name in cols:
        assert not BANNED.search(name), name
    import app.db as DBL
    con = sqlite3.connect(":memory:")
    for ddl in DBL.SQLITE_DDL:
        con.execute(ddl)
    for t in (*DBL.USER_TABLES, "spend"):
        for _, name, typ, *_ in con.execute(f"PRAGMA table_info({t})"):
            assert not BANNED.search(name), (t, name)
            assert typ.upper() != "BLOB", (t, name)
    # The migration and the SQLite file have the same account tables and columns.
    for t in DBL.USER_TABLES:
        sqlite_cols = {r[1] for r in con.execute(f"PRAGMA table_info({t})")}
        block = re.search(rf"CREATE TABLE IF NOT EXISTS {t} \((.*?)\n\);", code, re.S).group(1)
        pg_cols = set(re.findall(r"^\s{4}([a-z_]+)\s", block, re.M))
        assert sqlite_cols == pg_cols, t


def test_rls_on_for_every_table_with_no_policies():
    sql = MIGRATION.read_text(encoding="utf-8")
    tables = set(re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", sql))
    rls = set(re.findall(r"ALTER TABLE (\w+)\s+ENABLE ROW LEVEL SECURITY", sql))
    assert tables and tables == rls
    assert "CREATE POLICY" not in sql.upper()


def test_saved_basket_drops_try_on_images_and_links(env):
    c = env["c"]
    built = demo_basket(c)
    b = c.post("/api/me/baskets", headers=bearer(tok()), json={"basket_id": built["id"]}).json()
    text = json.dumps(b)
    assert '"image"' not in text and "data:" not in text and "http" not in text and "/media/" not in text
    from app.accounts import results_only
    assert results_only({"a": "https://x/y.png", "photo": 1, "k": ["data:abc", "ok"], "maskUrl": "z"}) == \
        {"a": None, "k": ["ok"]}


# ---------------------------------------------------------------- export + delete account
def test_export_has_every_kind(env):
    c = env["c"]
    _fill(c, A)
    e = c.get("/api/me/export", headers=bearer(tok())).json()
    assert e["profile"]["display_name"] and e["history"] and e["shelf"] and e["baskets"]
    assert "never stored" in e["note"]


def test_delete_account_removes_every_row_then_the_auth_user(env):
    c = env["c"]
    _fill(c, A)
    c.post("/api/me/history", headers=bearer(tok()), json={"type": "avoid", "ingredient": "menthol", "note": ""})
    assert sum(user_rows(env["db"]).values()) > 0
    r = c.delete("/api/me", headers=bearer(tok()))
    assert r.status_code == 200, r.text
    assert sum(user_rows(env["db"]).values()) == 0
    assert env["calls"]["deleted"] == [A]


def test_delete_account_still_clears_rows_when_auth_removal_fails(env, monkeypatch):
    c, AU = env["c"], env["AU"]
    _fill(c, A)

    def boom(uid):
        raise AU.AuthError("down.")
    monkeypatch.setattr(AU, "delete_auth_user", boom)
    r = c.delete("/api/me", headers=bearer(tok()))
    assert r.status_code == 502
    assert sum(user_rows(env["db"]).values()) == 0


# ---------------------------------------------------------------- device import
def test_import_adds_device_history_and_skips_duplicate_chips(env):
    c = env["c"]
    h = bearer(tok())
    pid = c.get("/api/catalog").json()[0]["id"]
    body = {"chips": [{"chip": "vitamin_c", "reaction": "itched"}],
            "records": [{"type": "confirmed_allergy", "ingredient": "fragrance", "note": ""}],
            "shelf": [pid]}
    assert c.post("/api/me/import", headers=h, json=body).status_code == 200
    c.post("/api/me/import", headers=h, json={**body, "records": []})
    hist = c.get("/api/me/history", headers=h).json()
    assert len(hist["chips"]) == 1
    assert hist["records"][0]["clinician_confirmed"] is True
    assert c.get("/api/me/shelf", headers=h).json()["product_ids"] == [pid]


def test_nothing_is_imported_without_the_call(env):
    c = env["c"]
    c.put("/api/chips", json={"chips": [{"chip": "vitamin_c", "reaction": "itched"}]})
    c.get("/api/me", headers=bearer(tok()))  # first login
    assert c.get("/api/me/history", headers=bearer(tok())).json()["chips"] == []
