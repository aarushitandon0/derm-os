"""YouCam Skin Analysis client.

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
import mimetypes
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

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

# Friendly messages for documented image errors (docs: File Specs & Errors).
IMAGE_ERRORS = {
    "error_below_min_image_size": "Photo resolution is too low. Use the phone camera (HD needs 1080 px on the short side).",
    "error_exceed_max_image_size": "Photo is too large. Try again with a smaller image.",
    "error_src_face_too_small": "Move closer: your face should fill at least 60% of the frame width.",
    "error_src_face_out_of_bound": "Centre your face so it is fully inside the frame.",
    "error_lighting_dark": "It's too dark. Face a window or a bright, even light.",
    "error_no_face": "No face found. Look straight at the camera.",
}


class YouCamError(RuntimeError):
    def __init__(self, message: str, code: str | None = None, friendly: str | None = None):
        super().__init__(message)
        self.code = code
        self.friendly = friendly or message


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
                                  friendly=IMAGE_ERRORS.get(str(code)))
            return body
        raise YouCamError(f"{method} {path} kept failing after retries", code="retry_exhausted")

    def credit(self) -> dict[str, Any]:
        """Unit balance. Endpoint used by other hackathon entries; tolerate shape changes."""
        return self._request("GET", "/s2s/v1.0/client/credit")

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
                raise YouCamError(f"Task failed: {err}", code=str(err), friendly=IMAGE_ERRORS.get(str(err)))
            self.poll_sleep(delay)
            delay = min(delay * 1.4, 6)
        raise YouCamError(f"Task {task_id} did not finish in {max_wait}s", code="timeout")

    def analyze(self, image_path: str | Path, actions: list[str]) -> SkinResult:
        mode = validate_actions(actions)
        file_id = self.upload(image_path)
        task_id = self.create_task(file_id, actions)
        body = self.poll(task_id)
        return normalize(body, mode, actions, task_id)


def save_result(result: SkinResult, out_path: str | Path) -> None:
    """Persist the raw response so demos and tests can replay real data with no units spent."""
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(json.dumps({"meta": {"mode": result.mode, "actions": result.actions,
                                                   "task_id": result.task_id},
                                          "response": result.raw}, indent=2))


def load_result(path: str | Path) -> SkinResult:
    blob = json.loads(Path(path).read_text())
    m = blob["meta"]
    return normalize(blob["response"], m["mode"], m["actions"], m.get("task_id"))
