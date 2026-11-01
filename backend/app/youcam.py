"""YouCam client: Skin Analysis, plus Skin Tone (AI Facial Color Tones Analyzer) and Makeup VTO.

Skin Tone and Makeup VTO use the same pattern on the v2.0 task endpoints:
POST /s2s/v2.0/task/{skin-tone-analysis|makeup-vto}, then GET .../{task_id}; see run_feature().
The skin analysis flow below is unchanged:

Flow (from docs.perfectcorp.com/reference/ai_skin_analysis):
  1. POST /s2s/v2.0/file            -> file_id + presigned PUT url/headers
  2. PUT bytes to the presigned url
  3. POST /s2s/{ver}/task/skin-analysis  {src_file_id, dst_actions, format}
  4. GET  /s2s/{ver}/task/skin-analysis/{task_id} until task_status == success|error

Important facts baked in here:
  * SD and HD actions cannot be mixed in one request (400 InvalidParameters).
  * Units are only consumed on success; failed tasks cost nothing.
  * ui_score is deliberately adjusted upward by Perfect Corp ("psychological
    motivator"), so every evidence decision in derm//os uses raw_score.
  * Result/mask URLs are temporary, so callers should download masks promptly.
"""
from __future__ import annotations

import json
import logging
import mimetypes
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from . import photometa

log = logging.getLogger("dermos.youcam")

BASE_URL = os.environ.get("YOUCAM_BASE_URL", "https://yce-api-01.makeupar.com")

SD_ACTIONS = {
    "wrinkle", "droopy_upper_eyelid", "droopy_lower_eyelid", "firmness", "acne",
    "moisture", "eye_bag", "dark_circle_v2", "age_spot", "radiance", "redness",
    "oiliness", "pore", "texture", "tear_trough", "skin_type",
}
HD_ACTIONS = {
    "hd_wrinkle", "hd_droopy_upper_eyelid", "hd_droopy_lower_eyelid", "hd_firmness",
    "hd_acne", "hd_moisture", "hd_eye_bag", "hd_dark_circle", "hd_age_spot",
    "hd_radiance", "hd_redness", "hd_oiliness", "hd_pore", "hd_texture",
    "hd_tear_trough", "hd_skin_type",
}

# Friendly messages for documented image errors (docs: File Specs & Errors, and the AI Facial
# Color Tones Analyzer's face-angle errors). One plain sentence each; no raw code reaches the user.
IMAGE_ERRORS = {
    "error_below_min_image_size": "Photo resolution is too low, so use the phone camera (HD needs 1080 px on the short side).",
    "error_exceed_max_image_size": "Photo is too large, so try again with a smaller image.",
    "error_src_face_too_small": "Hold the phone a little closer.",
    "error_src_face_out_of_bound": "Centre your face so it is fully inside the frame.",
    "error_lighting_dark": "Face a window or a bright, even light and try again.",
    "error_no_face": "Look straight at the camera with your whole face in view.",
    "error_face_angle_leftward": "Turn a little more toward the camera and try again.",
    "error_face_angle_rightward": "Turn a little more toward the camera and try again.",
    "error_face_angle_upward": "Lower your chin a little and try again.",
    "error_face_angle_downward": "Raise your chin a little and try again.",
    "error_face_angle_left_tilt": "Hold your head upright, not tilted, and try again.",
    "error_face_angle_right_tilt": "Hold your head upright, not tilted, and try again.",
}
# Any other photo error YouCam may add later, and any request YouCam refused: still one plain line.
PHOTO_ERROR_FALLBACK = "Face the camera in even light and try again."
SERVICE_ERROR_FALLBACK = "The skin service couldn't finish this request, so try again in a minute."
# Photo errors that mean the photo can't be used for anything (as opposed to a face angle the
# tone check is pickier about than skin analysis is).
UNUSABLE_PHOTO_ERRORS = {"error_below_min_image_size", "error_exceed_max_image_size", "error_src_face_too_small",
                         "error_src_face_out_of_bound", "error_lighting_dark", "error_no_face"}


def friendly_error(code) -> str:
    """One plain sentence for a YouCam error code. Never the code itself."""
    c = str(code or "")
    if c in IMAGE_ERRORS:
        return IMAGE_ERRORS[c]
    if c.startswith("error_face_angle"):
        return "Turn a little more toward the camera and try again."
    if c.startswith("error_"):
        return PHOTO_ERROR_FALLBACK
    return SERVICE_ERROR_FALLBACK


def is_face_angle_error(code) -> bool:
    return str(code or "").startswith("error_face_angle")


def is_invalid_parameter(e) -> bool:
    """YouCam refused the request's parameters (HTTP 4xx before a task runs: never charged)."""
    c = str(getattr(e, "code", "") or "").lower().replace("_", "")
    return "invalidparam" in c


# face_angle_strictness_level for Skin Tone, most lenient first (docs: "strict, high, medium, low
# to flexible"; YouCam's own default is high). derm//os sends the most lenient by default: a
# slightly turned selfie is normal and the undertone must still be read from it.
TONE_STRICTNESS_LEVELS = ("flexible", "low", "medium", "high", "strict")
DEFAULT_TONE_STRICTNESS = "flexible"
# On an invalid-parameter error the client steps to the next stricter level, but never past this.
MAX_AUTO_STRICTNESS = "medium"


def tone_strictness() -> str:
    """YOUCAM_FACE_ANGLE_STRICTNESS if it is a documented level, else the most lenient."""
    v = os.environ.get("YOUCAM_FACE_ANGLE_STRICTNESS", "").strip().lower()
    return v if v in TONE_STRICTNESS_LEVELS else DEFAULT_TONE_STRICTNESS


class YouCamError(RuntimeError):
    def __init__(self, message: str, code: str | None = None, friendly: str | None = None):
        super().__init__(message)
        self.code = code
        self.friendly = friendly or message


def actions_for_mode(actions: list[str], mode: str) -> list[str]:
    """The same concerns named for SD or HD (hd_ prefix; SD dark_circle_v2 is HD hd_dark_circle)."""
    out = []
    for a in actions:
        base = a[3:] if a.startswith("hd_") else a
        if mode == "hd":
            out.append("hd_dark_circle" if base in ("dark_circle_v2", "dark_circle") else f"hd_{base}")
        else:
            out.append("dark_circle_v2" if base == "dark_circle" else base)
    return out


def validate_actions(actions: list[str]) -> str:
    """Return 'sd' or 'hd'. Raises before a unit is spent if the set is invalid."""
    if not actions:
        raise ValueError("dst_actions is empty")
    unknown = [a for a in actions if a not in SD_ACTIONS | HD_ACTIONS]
    if unknown:
        raise ValueError(f"Unknown actions: {unknown}")
    hd = [a for a in actions if a in HD_ACTIONS]
    if hd and len(hd) != len(actions):
        raise ValueError("SD and HD actions cannot be mixed in one request")
    return "hd" if hd else "sd"


@dataclass
class ConcernScore:
    concern: str                 # normalised name without hd_ prefix, e.g. "redness"
    raw_score: float | None
    ui_score: float | None
    mask_urls: list[str] = field(default_factory=list)
    regions: dict[str, float] = field(default_factory=dict)  # HD sub-regions (raw)


@dataclass
class SkinResult:
    task_id: str | None
    mode: str                    # "sd" | "hd"
    actions: list[str]
    scores: dict[str, ConcernScore]
    overall: float | None = None
    skin_age: float | None = None
    raw: dict[str, Any] | None = None

    def raw_scores(self) -> dict[str, float]:
        return {k: v.raw_score for k, v in self.scores.items() if v.raw_score is not None}

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "mode": self.mode,
            "actions": self.actions,
            "overall": self.overall,
            "skin_age": self.skin_age,
            "scores": {
                k: {"raw_score": v.raw_score, "ui_score": v.ui_score,
                    "mask_urls": v.mask_urls, "regions": v.regions}
                for k, v in self.scores.items()
            },
        }


def _strip(name: str) -> str:
    return name[3:] if name.startswith("hd_") else name


def _num(x: Any) -> float | None:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def normalize(payload: dict[str, Any], mode: str, actions: list[str], task_id: str | None = None) -> SkinResult:
    """Accepts either the JSON task response (data.results.output[]) or a
    score_info.json dict (ZIP format), so recorded fixtures of either shape work."""
    data = payload.get("data", payload)
    results = data.get("results", data)
    scores: dict[str, ConcernScore] = {}
    overall = skin_age = None

    output = results.get("output") if isinstance(results, dict) else None
    if isinstance(output, list):
        for item in output:
            t = item.get("type")
            if not t:
                continue
            name = _strip(t)
            # Some HD types report sub-regions; keep 'whole' as the headline score.
            regions = {}
            raw = _num(item.get("raw_score"))
            ui = _num(item.get("ui_score"))
            for reg in ("whole", "forehead", "nose", "cheek", "glabellar", "crowfeet",
                        "periocular", "nasolabial", "marionette", "t_zone", "u_zone"):
                sub = item.get(reg)
                if isinstance(sub, dict) and _num(sub.get("raw_score")) is not None:
                    regions[reg] = _num(sub.get("raw_score"))
            if raw is None and "whole" in regions:
                raw = regions["whole"]
            scores[name] = ConcernScore(name, raw, ui, list(item.get("mask_urls") or []), regions)
        overall = _num((results.get("all") or {}).get("score")) if isinstance(results.get("all"), dict) else None
        skin_age = _num(results.get("skin_age"))
    else:
        # score_info.json shape
        for key, val in results.items():
            if key == "all" and isinstance(val, dict):
                overall = _num(val.get("score"))
                continue
            if key == "skin_age":
                skin_age = _num(val)
                continue
            if not isinstance(val, dict):
                continue
            name = _strip(key)
            if "raw_score" in val:
                scores[name] = ConcernScore(name, _num(val.get("raw_score")), _num(val.get("ui_score")))
            else:
                regions = {r: _num(s.get("raw_score")) for r, s in val.items()
                           if isinstance(s, dict) and _num(s.get("raw_score")) is not None}
                whole = val.get("whole") if isinstance(val.get("whole"), dict) else {}
                scores[name] = ConcernScore(name, regions.get("whole"), _num(whole.get("ui_score")), [], regions)
    return SkinResult(task_id, mode, actions, scores, overall, skin_age, raw=payload)


class YouCamClient:
    def __init__(self, api_key: str | None = None, version: str = "v2.1",
                 timeout: float = 30.0, transport: httpx.BaseTransport | None = None):
        self.api_key = api_key or os.environ.get("YOUCAM_API_KEY")
        if not self.api_key:
            raise YouCamError("YOUCAM_API_KEY is not set", code="no_key")
        self.version = version
        self.http = httpx.Client(base_url=BASE_URL, timeout=timeout, transport=transport,
                                 headers={"Authorization": f"Bearer {self.api_key}"})
        # Separate client for the presigned upload: it must NOT send the bearer header.
        self.upload_http = httpx.Client(timeout=60, transport=transport)
        self.poll_sleep = time.sleep

    # -- low level -----------------------------------------------------------
    def _request(self, method: str, path: str, **kw) -> dict[str, Any]:
        delay = 1.0
        for attempt in range(5):
            r = self.http.request(method, path, **kw)
            if r.status_code == 429 or r.status_code >= 500:
                wait = float(r.headers.get("Retry-After", delay))
                self.poll_sleep(min(wait, 20))
                delay *= 2
                continue
            try:
                body = r.json()
            except ValueError:
                body = {"raw": r.text}
            if r.status_code >= 400:
                code = body.get("error_code") or body.get("error")
                raise YouCamError(f"{method} {path} -> {r.status_code}: {body}", code=code,
                                  friendly=friendly_error(code))
            return body
        raise YouCamError(f"{method} {path} kept failing after retries", code="retry_exhausted")

    def credit(self) -> dict[str, Any]:
        """Unit balance (free, read-only). The response shape isn't documented, so parse_balance() is tolerant."""
        return self._request("GET", "/s2s/v1.0/client/credit")

    def unit_balance(self) -> float | None:
        return parse_balance(self.credit())

    def feature_costs(self, max_pages: int = 20) -> list[dict[str, Any]]:
        """Every SKU from GET /s2s/v2.0/credit/feature-cost (free, read-only), following
        `starting_token` pages."""
        skus: list[dict[str, Any]] = []
        token = None
        for _ in range(max_pages):
            body = self._request("GET", "/s2s/v2.0/credit/feature-cost",
                                 params={"starting_token": token} if token else None)
            res = body.get("result") or body.get("data") or {}
            page = res.get("skus") or []
            skus += page
            token = res.get("next_token")
            if not token or not page:
                break
        return skus

    def scan_cost(self, actions: list[str]) -> tuple[float, str]:
        """Exact units one skin-analysis task with these actions costs, and where the price came
        from ("price list" = read live from YouCam now, "built-in" = PRICE_FALLBACK)."""
        if getattr(self, "_prices", None) is None:
            try:
                self._prices = parse_skin_prices(self.feature_costs())
            except Exception as e:  # noqa: BLE001 - fall back to the built-in table
                log.warning("Feature-cost list unavailable (%s); using the built-in price table.", type(e).__name__)
                self._prices = {}
        return scan_cost_from(self._prices, self.version, actions)

    # -- workflow ------------------------------------------------------------
    def upload(self, image_path: str | Path) -> str:
        p = Path(image_path)
        data = p.read_bytes()
        ctype = mimetypes.guess_type(p.name)[0] or "image/jpeg"
        if ctype not in ("image/jpeg", "image/png"):
            raise YouCamError(f"Unsupported file type {ctype}; use JPEG or PNG")
        if len(data) >= 10 * 1024 * 1024:
            raise YouCamError("File must be under 10 MB")
        body = self._request("POST", "/s2s/v2.0/file", json={
            "files": [{"content_type": ctype, "file_name": p.name, "file_size": len(data)}]})
        f = body["data"]["files"][0]
        req = f["requests"][0]
        put = self.upload_http.request(req.get("method", "PUT"), req["url"], content=data,
                                       headers=req.get("headers") or {"Content-Type": ctype})
        if put.status_code >= 300:
            raise YouCamError(f"Presigned upload failed: {put.status_code} {put.text[:200]}")
        return f["file_id"]

    def create_task(self, file_id: str, actions: list[str], mask_overlay: bool = False) -> str:
        validate_actions(actions)
        body = self._request("POST", f"/s2s/{self.version}/task/skin-analysis", json={
            "src_file_id": file_id,
            "dst_actions": actions,
            "miniserver_args": {"enable_mask_overlay": mask_overlay},
            "format": "json",
        })
        return body["data"]["task_id"]

    def poll(self, task_id: str, max_wait: float = 120.0) -> dict[str, Any]:
        start, delay = time.time(), 1.5
        while time.time() - start < max_wait:
            body = self._request("GET", f"/s2s/{self.version}/task/skin-analysis/{task_id}")
            status = (body.get("data") or {}).get("task_status")
            if status == "success":
                return body
            if status == "error":
                err = (body.get("data") or {}).get("error") or body.get("error")
                raise YouCamError(f"Task failed: {err}", code=str(err), friendly=friendly_error(err))
            self.poll_sleep(delay)
            delay = min(delay * 1.4, 6)
        raise YouCamError(f"Task {task_id} did not finish in {max_wait}s", code="timeout")

    def delete_task(self, task_id: str) -> dict[str, Any]:
        """Delete a finished task at YouCam, with its uploaded photo and generated outputs.

        Docs (Task Management > delete-with-resources): POST /s2s/v2.0/task/delete,
        bearer auth, JSON body {"task_id": "<id from the task's run endpoint>"}.
        Only finished tasks can be deleted (OperationInvalid otherwise).
        """
        if not task_id:
            raise YouCamError("No task id to delete", code="no_task_id")
        return self._request("POST", "/s2s/v2.0/task/delete", json={"task_id": task_id})

    def analyze(self, image_path: str | Path, actions: list[str]) -> SkinResult:
        mode = validate_actions(actions)
        file_id = self.upload(image_path)
        task_id = self.create_task(file_id, actions)
        body = self.poll(task_id)
        return normalize(body, mode, actions, task_id)

    # -- skin tone and makeup try-on (v2.0 task endpoints) ---------------------
    def feature_cost(self, feature: str) -> tuple[float, str]:
        """Units one task of `feature` costs ("skin-tone-analysis", "makeup-vto"), read from the
        free price list by its run_task_url, or the built-in table when the list can't be read."""
        if getattr(self, "_skus", None) is None:
            try:
                self._skus = self.feature_costs()
            except Exception as e:  # noqa: BLE001 - fall back to the built-in price table
                log.warning("Feature-cost list unavailable (%s); using the built-in price table.", type(e).__name__)
                self._skus = []
        return feature_cost_from(self._skus, feature)

    def run_feature(self, feature: str, body: dict[str, Any], max_wait: float = 120.0) -> tuple[str, dict[str, Any]]:
        """POST /s2s/v2.0/task/{feature}, then poll GET .../{task_id} until success or error."""
        if feature not in FEATURES:
            raise ValueError(f"Unknown feature {feature!r}")
        path = f"/s2s/{FEATURE_VERSION}/task/{feature}"
        created = self._request("POST", path, json=body)
        task_id = (created.get("data") or {}).get("task_id")
        if not task_id:
            raise YouCamError(f"{feature}: no task_id in the response", code="no_task_id")
        return task_id, self._poll_path(f"{path}/{task_id}", max_wait)

    def _poll_path(self, path: str, max_wait: float) -> dict[str, Any]:
        start, delay = time.time(), 1.5
        while time.time() - start < max_wait:
            body = self._request("GET", path)
            data = body.get("data") or {}
            status = data.get("task_status")
            if status == "success":
                return body
            if status == "error":
                err = data.get("error") or data.get("error_code") or body.get("error")
                raise YouCamError(f"Task failed: {err}", code=str(err), friendly=friendly_error(err))
            self.poll_sleep(delay)
            delay = min(delay * 1.4, 6)
        raise YouCamError(f"Task at {path} did not finish in {max_wait}s", code="timeout")

    def skin_tone(self, image_path: str | Path | None = None, file_id: str | None = None,
                  strictness: str | None = None) -> "ToneResult":
        """AI Facial Color Tones Analyzer. Returns the measured colours; the API returns no
        undertone (app/undertone.py derives one from skin_color).

        Sent at `strictness` (default: tone_strictness(), the most lenient documented level). If
        YouCam refuses that value as an invalid parameter (a request error: no task runs, nothing
        is charged), the next stricter level is tried, up to MAX_AUTO_STRICTNESS and no further.
        The photo is uploaded once. The level that worked is on the result."""
        start = strictness if strictness in TONE_STRICTNESS_LEVELS else tone_strictness()
        i0 = TONE_STRICTNESS_LEVELS.index(start)
        last = max(i0, TONE_STRICTNESS_LEVELS.index(MAX_AUTO_STRICTNESS))
        fid = file_id or self.upload(image_path)
        self.tone_attempts = []
        for level in TONE_STRICTNESS_LEVELS[i0:last + 1]:
            self.tone_attempts.append(level)
            try:
                task_id, body = self.run_feature(SKIN_TONE, {"src_file_id": fid, "face_angle_strictness_level": level})
            except YouCamError as e:
                if is_invalid_parameter(e) and level != TONE_STRICTNESS_LEVELS[last]:
                    log.warning("Skin Tone refused strictness %r as an invalid parameter; trying the next level.", level)
                    continue
                raise
            res = normalize_tone(body, task_id)
            res.strictness = level
            return res
        raise AssertionError("unreachable")  # pragma: no cover - the last level always returns or raises

    def makeup_vto(self, effects: list[dict[str, Any]], image_path: str | Path | None = None,
                   file_id: str | None = None) -> "VtoResult":
        """AI Makeup Virtual Try-On with the given effects (e.g. one foundation palette)."""
        fid = file_id or self.upload(image_path)
        task_id, body = self.run_feature(MAKEUP_VTO, {"src_file_id": fid, "version": "1.0", "effects": effects})
        return VtoResult(task_id, extract_image_url(body), body)


# ---------------------------------------------------------------- tone + try-on results
SKIN_TONE = "skin-tone-analysis"
MAKEUP_VTO = "makeup-vto"
FEATURES = (SKIN_TONE, MAKEUP_VTO)
FEATURE_VERSION = "v2.0"
# From GET /s2s/v2.0/credit/feature-cost (read 2026-11-01): "AI Facial Color Tones Analyzer V1.0"
# 20 units and "AI Makeup Virtual Try-On V1.0" 1 unit, per result image. Fallback only.
FEATURE_PRICE_FALLBACK = {SKIN_TONE: 20.0, MAKEUP_VTO: 1.0}


def feature_cost_from(skus: list[dict[str, Any]], feature: str) -> tuple[float, str]:
    for sku in skus or []:
        url = str(sku.get("run_task_url") or "")
        amt = _num(sku.get("amount"))
        if amt is not None and url.rstrip("/").endswith(f"/task/{feature}"):
            return amt, "price list"
    if feature in FEATURE_PRICE_FALLBACK:
        return FEATURE_PRICE_FALLBACK[feature], "built-in"
    raise ValueError(f"No price for feature {feature!r}")


@dataclass
class ToneResult:
    task_id: str | None
    skin_color: str | None
    colors: dict[str, Any]
    face_quality: dict[str, Any]
    raw: dict[str, Any] | None = None
    strictness: str | None = None    # the face_angle_strictness_level YouCam accepted

    def to_dict(self) -> dict[str, Any]:
        return {"task_id": self.task_id, "skin_color": self.skin_color, "colors": dict(self.colors),
                "face_quality": dict(self.face_quality), "strictness": self.strictness}


def normalize_tone(payload: dict[str, Any], task_id: str | None = None) -> ToneResult:
    """data.results.color.skin_color (documented example), tolerant of a missing envelope."""
    data = payload.get("data", payload) if isinstance(payload, dict) else {}
    results = data.get("results", data) if isinstance(data, dict) else {}
    results = results if isinstance(results, dict) else {}
    color = results.get("color") if isinstance(results.get("color"), dict) else {}
    fq = results.get("face_quality") if isinstance(results.get("face_quality"), dict) else {}
    sc = color.get("skin_color")
    return ToneResult(task_id, sc if isinstance(sc, str) else None, dict(color), dict(fq), raw=payload)


@dataclass
class VtoResult:
    task_id: str | None
    image_url: str | None
    raw: dict[str, Any] | None = None


def extract_image_url(payload: Any) -> str | None:
    """The rendered image's URL. Accepts data.results as a string, a dict with url / download_url /
    image_url / dst_url, a list of such dicts, or one nested under `output`."""
    node = payload.get("data", payload) if isinstance(payload, dict) else payload
    node = node.get("results", node) if isinstance(node, dict) else node

    def find(n: Any) -> str | None:
        if isinstance(n, str) and n.startswith(("https://", "http://")):
            return n
        if isinstance(n, list):
            for item in n:
                hit = find(item)
                if hit:
                    return hit
        if isinstance(n, dict):
            for k in ("url", "download_url", "image_url", "dst_url"):
                if isinstance(n.get(k), str) and n[k].startswith(("https://", "http://")):
                    return n[k]
            for k in ("output", "outputs", "results", "images"):
                if k in n:
                    hit = find(n[k])
                    if hit:
                        return hit
        return None

    return find(node)


def download_render(url: str | None, dest: str | Path, http: httpx.Client | None = None) -> Path | None:
    """Save a try-on render now (result URLs expire), re-encoded from pixels only. Never raises:
    a failed download is logged without its URL and returns None."""
    if not url or not url.startswith(("https://", "http://")):
        return None
    own = http is None
    http = http or httpx.Client(timeout=30)
    try:
        r = http.get(url)
        if r.status_code != 200 or len(r.content) > MAX_MASK_BYTES:
            log.warning("Try-on render not saved (status %s).", r.status_code)
            return None
        clean = photometa.clean_bytes(r.content)
        if clean is None:
            log.warning("Try-on render not saved (not a readable image).")
            return None
        out = Path(dest).with_suffix(clean[1])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(clean[0])
        return out
    except httpx.HTTPError as e:
        log.warning("Try-on render download failed (%s).", type(e).__name__)
        return None
    finally:
        if own:
            http.close()


def delete_task_quietly(client: Any, task_id: str | None) -> bool:
    """Ask YouCam to delete a finished task. Never raises: a failed delete is logged
    (task id and error type only: no image data, no URLs, no keys) and the caller continues."""
    if not task_id:
        return False
    try:
        client.delete_task(task_id)
        return True
    except Exception as e:  # noqa: BLE001 - privacy clean-up must never break a scan
        log.warning("YouCam task delete failed for task %s (%s, code %s).",
                    task_id, type(e).__name__, getattr(e, "code", None))
        return False


def strip_urls(result_dict: dict[str, Any]) -> dict[str, Any]:
    """Copy of SkinResult.to_dict() without mask URLs (they are signed links to images of a face)."""
    out = {**result_dict, "scores": {}}
    for k, v in (result_dict.get("scores") or {}).items():
        out["scores"][k] = {**v, "mask_urls": []}
    return out


def save_result(result: SkinResult, out_path: str | Path, api_version: str | None = None) -> None:
    """Persist the raw response so demos and tests can replay real data with no units spent.
    This local copy still holds mask URLs; scripts/make_fixtures.py strips them before anything
    is committed."""
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    meta = {"mode": result.mode, "actions": result.actions, "task_id": result.task_id}
    if api_version:
        meta["api_version"] = api_version
    Path(out_path).write_text(json.dumps({"meta": meta, "response": result.raw}, indent=2))


def load_result(path: str | Path) -> SkinResult:
    blob = json.loads(Path(path).read_text())
    m = blob["meta"]
    return normalize(blob["response"], m["mode"], m["actions"], m.get("task_id"))


# ---------------------------------------------------------------- unit guard
_BALANCE_KEYS = ("amount", "balance", "credit", "credits", "remaining", "units", "unit", "point", "points")


def parse_balance(body: Any) -> float | None:
    """Find the unit balance in a credit response without trusting one exact shape.
    Lists (one entry per credit pack) are summed. Returns None if nothing numeric is found."""
    if isinstance(body, list):
        vals = [parse_balance(x) for x in body]
        vals = [v for v in vals if v is not None]
        return sum(vals) if vals else None
    if not isinstance(body, dict):
        return None
    for k in ("data", "result", "results"):
        if k in body:
            v = parse_balance(body[k])
            if v is not None:
                return v
    for k in _BALANCE_KEYS:
        if k in body and not isinstance(body[k], (dict, list, bool)):
            v = _num(body[k])
            if v is not None:
                return v
    for k in _BALANCE_KEYS:
        if isinstance(body.get(k), (dict, list)):
            v = parse_balance(body[k])
            if v is not None:
                return v
    return None


# ---------------------------------------------------------------- prices
# Tiered by the number of concerns in one task, from GET /s2s/v2.0/credit/feature-cost
# (read 2026-10-28). Only used when the live list can't be read or has no matching entry.
PRICE_FALLBACK: dict[tuple[str, str], list[tuple[int, int, float]]] = {
    ("2.1", "sd"): [(1, 4, 9.0), (5, 8, 12.0), (9, 12, 14.0), (13, 16, 16.0)],
    ("2.1", "hd"): [(1, 4, 12.0), (5, 8, 16.0), (9, 12, 20.0), (13, 16, 22.0)],
    ("2.0", "sd"): [(1, 4, 9.0), (5, 8, 12.0), (9, 12, 14.0), (13, 16, 16.0)],
    ("2.0", "hd"): [(1, 4, 12.0), (5, 8, 16.0), (9, 12, 20.0), (13, 16, 22.0)],
}
_SKU = re.compile(r"AI Skin Analysis V(\d+\.\d+) (SD|HD) \((\d+)\s*-\s*(\d+) concerns?\)", re.I)


def parse_skin_prices(skus: list[dict[str, Any]]) -> dict[tuple[str, str], list[tuple[int, int, float]]]:
    table: dict[tuple[str, str], list[tuple[int, int, float]]] = {}
    for s in skus or []:
        m = _SKU.search(str(s.get("description", "")))
        amt = _num(s.get("amount"))
        if not m or amt is None:
            continue
        key = (m.group(1), m.group(2).lower())
        table.setdefault(key, []).append((int(m.group(3)), int(m.group(4)), amt))
    return {k: sorted(v) for k, v in table.items()}


def scan_cost_from(table: dict, version: str, actions: list[str]) -> tuple[float, str]:
    """Units for one task. Raises ValueError if no tier covers this many concerns."""
    mode = validate_actions(actions)
    n = len(set(actions))
    ver = version.lstrip("vV")
    for src, tiers in (("price list", (table or {}).get((ver, mode))), ("built-in", PRICE_FALLBACK.get((ver, mode)))):
        for lo, hi, amt in tiers or []:
            if lo <= n <= hi:
                return amt, src
    raise ValueError(f"No price for {n} {mode.upper()} concerns on v{ver}")


class UnitReserveError(YouCamError):
    pass


def check_unit_reserve(client: Any, reserve: float, cost: float | None = None,
                       balance: float | None = None) -> float | None:
    """Refuse a live scan when the balance can't pay for it (`cost`, the exact price of this
    scan) or when paying would leave less than `reserve`. If the balance can't be read
    (network error, unknown shape), log it and allow the scan: the guard must never be the
    reason a demo breaks, and YouCam itself refuses a scan the account can't pay for.
    `balance`: a balance already read for this scan (by the floor check), so it isn't read twice.
    In the app the floor check (guard.balance_floor) runs first and never lets an unreadable
    balance through; this allow-on-failure only matters for scripts that call it directly."""
    try:
        bal = balance if balance is not None else client.unit_balance()
    except Exception as e:  # noqa: BLE001 - any failure here is non-fatal by design
        log.warning("Unit balance check failed (%s); continuing without the guard.", type(e).__name__)
        return None
    if bal is None:
        log.warning("Unit balance response had no recognisable balance; continuing without the guard.")
        return None
    c = cost or 0.0
    if bal < c:
        raise UnitReserveError(
            f"Unit balance {bal:g} can't pay for this scan ({c:g})", code="unit_reserve",
            friendly=(f"Live scans are paused: this scan costs {c:g} YouCam units and {bal:g} are left. "
                      "Turn on DEMO_MODE=1 to replay recorded scans, or top up units."))
    if bal - c < reserve:
        raise UnitReserveError(
            f"Unit balance {bal:g} minus this scan ({c:g}) is below reserve {reserve:g}", code="unit_reserve",
            friendly=(f"Live scans are paused: this scan costs {c:g} YouCam units, {bal:g} are left, and "
                      f"{reserve:g} are kept in reserve for the demo. Turn on DEMO_MODE=1 to replay recorded "
                      "scans, or top up units."))
    return bal


# ---------------------------------------------------------------- masks
_MASK_TYPES = {"image/png": ".png", "image/jpeg": ".jpg", "image/jpg": ".jpg", "image/webp": ".webp"}
MAX_MASK_BYTES = 15 * 1024 * 1024


def download_masks(result: SkinResult, dest_dir: str | Path,
                   http: httpx.Client | None = None) -> dict[str, list[Path]]:
    """Download every mask now, because YouCam result URLs expire (~2 h).
    Uses a client WITHOUT the bearer header (these are presigned storage URLs).
    A failed mask is skipped and logged without its URL (URLs carry signatures)."""
    dest = Path(dest_dir)
    own = http is None
    http = http or httpx.Client(timeout=30)
    saved: dict[str, list[Path]] = {}
    try:
        for concern, score in result.scores.items():
            for i, url in enumerate(score.mask_urls):
                if not isinstance(url, str) or not url.startswith(("https://", "http://")):
                    continue
                try:
                    r = http.get(url)
                    ctype = (r.headers.get("content-type") or "").split(";")[0].strip().lower()
                    ext = _MASK_TYPES.get(ctype) or (Path(httpx.URL(url).path).suffix.lower() or "")
                    if r.status_code != 200 or ext not in _MASK_TYPES.values() or len(r.content) > MAX_MASK_BYTES:
                        log.warning("Mask %s #%d not saved (status %s, type %s).", concern, i, r.status_code, ctype)
                        continue
                    # Stored re-encoded from its pixels alone, so no metadata is kept.
                    clean = photometa.clean_bytes(r.content)
                    if clean is None:
                        log.warning("Mask %s #%d not saved (not a readable image).", concern, i)
                        continue
                    dest.mkdir(parents=True, exist_ok=True)
                    out = dest / f"{concern}_{i}{clean[1]}"
                    out.write_bytes(clean[0])
                    saved.setdefault(concern, []).append(out)
                except httpx.HTTPError as e:
                    log.warning("Mask %s #%d download failed (%s).", concern, i, type(e).__name__)
    finally:
        if own:
            http.close()
    return saved
