"""YouCam client tests against a mocked transport (no units spent).

Response shapes are copied from docs.perfectcorp.com/reference/ai_skin_analysis.
"""
import json

import httpx
import pytest
from PIL import Image

from app.youcam import YouCamClient, YouCamError, normalize, validate_actions

TASK_OK = {
    "status": 200,
    "data": {
        "results": {"output": [
            {"type": "texture", "ui_score": 68, "raw_score": 57.33, "mask_urls": ["https://x/texture.jpg"]},
            {"type": "pore", "ui_score": 92, "raw_score": 95.34, "mask_urls": ["https://x/pore.jpg"]},
        ]},
        "task_status": "success",
    },
}

SCORE_INFO_HD = {
    "hd_redness": {"raw_score": 72.01, "ui_score": 77, "output_mask_name": "hd_redness_output.png"},
    "hd_pore": {"whole": {"raw_score": 49.24, "ui_score": 67}, "nose": {"raw_score": 29.14, "ui_score": 58}},
    "all": {"score": 75.76},
    "skin_age": 37,
}


def test_validate_rejects_mixed_sd_hd_before_spending_units():
    with pytest.raises(ValueError):
        validate_actions(["redness", "hd_pore"])
    assert validate_actions(["redness", "pore"]) == "sd"
    assert validate_actions(["hd_redness"]) == "hd"


def test_normalize_task_json_uses_raw_score():
    r = normalize(TASK_OK, "sd", ["texture", "pore"], "t1")
    assert r.raw_scores() == {"texture": 57.33, "pore": 95.34}
    assert r.scores["texture"].mask_urls == ["https://x/texture.jpg"]


def test_normalize_score_info_hd_regions():
    r = normalize(SCORE_INFO_HD, "hd", ["hd_redness", "hd_pore"])
    assert r.raw_scores()["redness"] == 72.01
    assert r.scores["pore"].raw_score == 49.24
    assert r.scores["pore"].regions["nose"] == 29.14
    assert r.overall == 75.76 and r.skin_age == 37


def _photo(tmp_path):
    p = tmp_path / "face.jpg"
    Image.new("RGB", (600, 800), (200, 160, 140)).save(p)
    return p


def test_full_flow_with_mock_transport(tmp_path, monkeypatch):
    calls = []
    polls = iter([{"status": 200, "data": {"task_status": "running"}}, TASK_OK])

    def handler(req: httpx.Request):
        calls.append((req.method, str(req.url), dict(req.headers)))
        if req.url.path == "/s2s/v2.0/file":
            return httpx.Response(200, json={"status": 200, "data": {"files": [{
                "file_id": "F1", "requests": [{"method": "PUT", "url": "https://s3.example/up",
                                               "headers": {"Content-Type": "image/jpeg"}}]}]}})
        if req.url.host == "s3.example":
            return httpx.Response(200)
        if req.method == "POST" and req.url.path == "/s2s/v2.1/task/skin-analysis":
            body = json.loads(req.content)
            assert body["src_file_id"] == "F1" and body["format"] == "json"
            return httpx.Response(200, json={"status": 200, "data": {"task_id": "T1"}})
        if req.url.path == "/s2s/v2.1/task/skin-analysis/T1":
            return httpx.Response(200, json=next(polls))
        return httpx.Response(404)

    c = YouCamClient(api_key="k", transport=httpx.MockTransport(handler))
    c.poll_sleep = lambda s: None
    res = c.analyze(_photo(tmp_path), ["texture", "pore"])
    assert res.task_id == "T1" and res.raw_scores()["pore"] == 95.34
    s3 = [h for m, u, h in calls if "s3.example" in u][0]
    assert "authorization" not in {k.lower() for k in s3}, "API key must not be sent to the presigned URL"


def test_task_error_maps_to_friendly_message(tmp_path):
    def handler(req):
        if req.url.path == "/s2s/v2.0/file":
            return httpx.Response(200, json={"data": {"files": [{"file_id": "F", "requests": [{"url": "https://s3.example/u"}]}]}})
        if req.url.host == "s3.example":
            return httpx.Response(200)
        if req.method == "POST":
            return httpx.Response(200, json={"data": {"task_id": "T"}})
        return httpx.Response(200, json={"data": {"task_status": "error", "error": "error_src_face_too_small"}})

    c = YouCamClient(api_key="k", transport=httpx.MockTransport(handler))
    c.poll_sleep = lambda s: None
    with pytest.raises(YouCamError) as e:
        c.analyze(_photo(tmp_path), ["redness"])
    assert "60%" in e.value.friendly
