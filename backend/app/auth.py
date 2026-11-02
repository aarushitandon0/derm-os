"""Supabase Auth: who is calling, from a verified access token only.

The user id comes ONLY from a token whose signature, expiry, audience and issuer all check out,
never from a request body or query. Checked against Supabase's docs (Auth > JWTs, Nov 2026):

- Asymmetric signing keys (ES256 / RS256): public keys at
  SUPABASE_URL + /auth/v1/.well-known/jwks.json. Supabase's edge caches that list for 10 minutes,
  so we cache it no longer than that, and refetch once early when a token names a key we don't have
  (key rotation).
- Legacy projects (HS256 shared secret): SUPABASE_JWT_SECRET, optional. Supabase recommends moving
  to asymmetric keys; this fallback only exists so an older project still works.
- iss = SUPABASE_URL + "/auth/v1", aud = "authenticated", exp required.
"""
from __future__ import annotations

import os
import threading
import time

import httpx
import jwt
from fastapi import Header, HTTPException

AUDIENCE = "authenticated"
JWKS_TTL_S = 600          # Supabase's own edge cache time; don't keep keys longer
JWKS_MIN_REFETCH_S = 30   # an unknown key id refetches at most this often
ASYMMETRIC = ("ES256", "RS256", "EdDSA")


class AuthError(Exception):
    pass


def supabase_url() -> str:
    return (os.environ.get("SUPABASE_URL") or "").strip().rstrip("/")


def jwt_secret() -> str:
    return (os.environ.get("SUPABASE_JWT_SECRET") or "").strip()


def configured() -> bool:
    return bool(supabase_url())


def issuer() -> str:
    return f"{supabase_url()}/auth/v1"


def jwks_url() -> str:
    return f"{issuer()}/.well-known/jwks.json"


# ---------------------------------------------------------------- JWKS cache
_LOCK = threading.Lock()
_CACHE: dict = {"keys": {}, "at": 0.0, "url": ""}


def fetch_jwks(url: str) -> dict:
    """The public keys. Replaced in tests; no network there."""
    r = httpx.get(url, timeout=5.0)
    r.raise_for_status()
    return r.json()


def reset_cache() -> None:
    with _LOCK:
        _CACHE.update(keys={}, at=0.0, url="")


def _key_for(kid: str | None) -> dict | None:
    url = jwks_url()
    with _LOCK:
        now = time.monotonic()
        stale = _CACHE["url"] != url or now - _CACHE["at"] > JWKS_TTL_S
        missing = kid not in _CACHE["keys"] and now - _CACHE["at"] > JWKS_MIN_REFETCH_S
        if stale or missing:
            try:
                body = fetch_jwks(url)
            except Exception as e:  # noqa: BLE001 - any failure means we can't verify
                if stale:
                    raise AuthError("Couldn't load the sign-in keys.") from e
            else:
                _CACHE.update(keys={k.get("kid"): k for k in body.get("keys", [])}, at=now, url=url)
        return _CACHE["keys"].get(kid)


# ---------------------------------------------------------------- verify
def verify(token: str) -> dict:
    """The verified claims, or AuthError. Never trusts the token's own word on how to check it
    beyond choosing between the two allowed paths."""
    if not configured():
        raise AuthError("Accounts aren't set up on this server.")
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as e:
        raise AuthError("Malformed token.") from e
    alg = header.get("alg")
    opts = {"require": ["exp", "sub", "aud", "iss"]}
    try:
        if alg in ASYMMETRIC:
            jwk = _key_for(header.get("kid"))
            if jwk is None:
                raise AuthError("Unknown signing key.")
            if jwk.get("alg") and jwk["alg"] != alg:
                raise AuthError("Key and token algorithms differ.")
            key = jwt.PyJWK(jwk, algorithm=alg).key
            claims = jwt.decode(token, key, algorithms=[alg], audience=AUDIENCE, issuer=issuer(), options=opts)
        elif alg == "HS256":
            secret = jwt_secret()
            if not secret:
                raise AuthError("This server only accepts tokens signed with the project's keys.")
            claims = jwt.decode(token, secret, algorithms=["HS256"], audience=AUDIENCE, issuer=issuer(),
                                options=opts)
        else:
            raise AuthError("Token algorithm not allowed.")
    except jwt.PyJWTError as e:
        raise AuthError(f"Invalid token: {type(e).__name__}.") from e
    sub = claims.get("sub")
    if not isinstance(sub, str) or not sub:
        raise AuthError("Token has no user.")
    return claims


def current_user(authorization: str | None = Header(None)) -> str:
    """FastAPI dependency for every /api/me endpoint: the verified user id, or 401."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Log in to use your profile.", headers={"WWW-Authenticate": "Bearer"})
    try:
        return verify(authorization[7:].strip())["sub"]
    except AuthError as e:
        raise HTTPException(401, f"Log in again. {e}", headers={"WWW-Authenticate": "Bearer"}) from e


# ---------------------------------------------------------------- account deletion
def delete_auth_user(user_id: str) -> None:
    """Delete the Supabase auth user. Server-side only, with SUPABASE_SERVICE_ROLE_KEY (never sent
    to the browser, never logged). Replaced in tests."""
    srk = (os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
    if not configured() or not srk:
        raise AuthError("Account removal isn't set up on this server.")
    r = httpx.delete(f"{issuer()}/admin/users/{user_id}",
                     headers={"apikey": srk, "Authorization": f"Bearer {srk}"}, timeout=10.0)
    if r.status_code not in (200, 204, 404):  # 404: already gone
        raise AuthError(f"The sign-in service answered {r.status_code}.")
