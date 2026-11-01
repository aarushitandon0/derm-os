"""Skin Tone and Makeup VTO client methods over mocked HTTP. No network, no units."""
import json

import httpx
import pytest

from app import youcam as Y
from app.youcam import YouCamClient, YouCamError


def make_client(routes, seen):
    def handler(req: httpx.Request):
        seen.append((req.method, req.url.path, json.loads(req.content) if req.content and
                     req.headers.get("content-type", "").startswith("application/json") else None,
                     req.headers.get("authorization")))
        for (method, path), resp in routes.items():
            if req.method == method and req.url.path == path:
                body = resp(req) if callable(resp) else resp
                return httpx.Response(200, json=body) if isinstance(body, dict) else body
        if req.url.host == "upload.example":
            return httpx.Response(200)
        return httpx.Response(404, json={"error": "not mocked"})

    c = YouCamClient(api_key="k", transport=httpx.MockTransport(handler))
    c.poll_sleep = lambda s: None
    return c


UPLOAD = {("POST", "/s2s/v2.0/file"): {"data": {"files": [{"file_id": "F1", "requests": [
    {"method": "PUT", "url": "https://upload.example/put", "headers": {"Content-Type": "image/jpeg"}}]}]}}}


@pytest.fixture()
def photo(tmp_path):
    p = tmp_path / "selfie.jpg"
    p.write_bytes(b"\xff\xd8\xff" + b"0" * 100)
    return p


def test_skin_tone_upload_task_poll(photo):
    seen = []
    polls = iter([{"data": {"task_status": "running"}},
                  {"data": {"task_status": "success", "results": {
                      "face_quality": {"has_face": True, "lighting": "good"},
                      "color": {"skin_color": "#b9947c", "eye_color": "#62432e"}}}}])
    routes = {**UPLOAD,
              ("POST", "/s2s/v2.0/task/skin-tone-analysis"): {"data": {"task_id": "T9"}},
              ("GET", "/s2s/v2.0/task/skin-tone-analysis/T9"): lambda r: next(polls)}
    c = make_client(routes, seen)
    res = c.skin_tone(photo)
    assert res.task_id == "T9" and res.skin_color == "#b9947c" and res.face_quality["has_face"] is True
    task = next(s for s in seen if s[1] == "/s2s/v2.0/task/skin-tone-analysis")
    assert task[2] == {"src_file_id": "F1", "face_angle_strictness_level": "flexible"}
    assert res.strictness == "flexible"
    assert task[3] == "Bearer k"
    put = next(s for s in seen if s[1] == "/put")
    assert put[3] is None                      # the presigned upload never carries the key


def test_makeup_vto_sends_the_foundation_effect_and_reads_the_url(photo):
    seen = []
    effects = [{"category": "foundation", "palettes": [
        {"color": "#c09170", "colorIntensity": 55, "coverageIntensity": 50, "glowIntensity": 70}]}]
    routes = {**UPLOAD,
              ("POST", "/s2s/v2.0/task/makeup-vto"): {"data": {"task_id": "V1"}},
              ("GET", "/s2s/v2.0/task/makeup-vto/V1"): {"data": {"task_status": "success",
                                                                "results": {"url": "https://cdn.example/r.jpg"}}}}
    c = make_client(routes, seen)
    res = c.makeup_vto(effects, image_path=photo)
    assert res.task_id == "V1" and res.image_url == "https://cdn.example/r.jpg"
    body = next(s for s in seen if s[1] == "/s2s/v2.0/task/makeup-vto")[2]
    assert body == {"src_file_id": "F1", "version": "1.0", "effects": effects}


@pytest.mark.parametrize("results,url", [
    ("https://a.example/x.png", "https://a.example/x.png"),
    ([{"download_url": "https://a.example/y.png"}], "https://a.example/y.png"),
    ({"output": [{"image_url": "https://a.example/z.png"}]}, "https://a.example/z.png"),
    ({"nothing": 1}, None),
])
def test_extract_image_url_shapes(results, url):
    assert Y.extract_image_url({"data": {"results": results}}) == url


def test_task_error_raises_friendly(photo):
    routes = {**UPLOAD,
              ("POST", "/s2s/v2.0/task/skin-tone-analysis"): {"data": {"task_id": "T1"}},
              ("GET", "/s2s/v2.0/task/skin-tone-analysis/T1"): {"data": {"task_status": "error",
                                                                         "error": "error_no_face"}}}
    c = make_client(routes, [])
    with pytest.raises(YouCamError) as e:
        c.skin_tone(photo)
    assert e.value.code == "error_no_face" and "Look straight" in e.value.friendly


def test_missing_task_id_raises(photo):
    routes = {**UPLOAD, ("POST", "/s2s/v2.0/task/makeup-vto"): {"data": {}}}
    with pytest.raises(YouCamError):
        make_client(routes, []).makeup_vto([], image_path=photo)


def test_unknown_feature_is_refused_before_any_call():
    seen = []
    with pytest.raises(ValueError):
        make_client({}, seen).run_feature("skin-analysis-hd-everything", {})
    assert seen == []


def test_feature_cost_from_the_live_price_list_and_fallback():
    skus = [{"description": "AI Facial Color Tones Analyzer V1.0", "amount": 20.0,
             "run_task_url": "https://yce-api-01.makeupar.com/s2s/v2.0/task/skin-tone-analysis"},
            {"description": "AI Makeup Virtual Try-On V1.0", "amount": 1.0,
             "run_task_url": "https://yce-api-01.makeupar.com/s2s/v2.0/task/makeup-vto"}]
    assert Y.feature_cost_from(skus, Y.SKIN_TONE) == (20.0, "price list")
    assert Y.feature_cost_from(skus, Y.MAKEUP_VTO) == (1.0, "price list")
    assert Y.feature_cost_from([], Y.SKIN_TONE) == (20.0, "built-in")
    with pytest.raises(ValueError):
        Y.feature_cost_from([], "nope")


def test_client_feature_cost_reads_the_free_list_once():
    seen = []
    routes = {("GET", "/s2s/v2.0/credit/feature-cost"): {"result": {"skus": [
        {"amount": 1.0, "run_task_url": "https://x/s2s/v2.0/task/makeup-vto"}]}}}
    c = make_client(routes, seen)
    assert c.feature_cost(Y.MAKEUP_VTO) == (1.0, "price list")
    assert c.feature_cost(Y.SKIN_TONE) == (20.0, "built-in")
    assert sum(1 for s in seen if s[1].endswith("feature-cost")) == 1


def test_tone_and_vto_tasks_delete_through_the_shared_endpoint():
    seen = []
    c = make_client({("POST", "/s2s/v2.0/task/delete"): {"status": 200}}, seen)
    assert Y.delete_task_quietly(c, "T9") is True
    assert seen[-1][1:3] == ("/s2s/v2.0/task/delete", {"task_id": "T9"})


def test_download_render_saves_clean_pixels(tmp_path):
    import io
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", (8, 8), (180, 140, 120)).save(b, "PNG")
    http = httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, content=b.getvalue(), headers={"content-type": "image/png"})))
    out = Y.download_render("https://cdn.example/r.png", tmp_path / "tryon_dewy", http)
    assert out is not None and out.exists() and out.stem == "tryon_dewy"
    assert Y.download_render(None, tmp_path / "x") is None
    bad = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(403)))
    assert Y.download_render("https://cdn.example/r.png", tmp_path / "y", bad) is None
