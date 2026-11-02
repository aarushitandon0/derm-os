"""Model files: found at DERMOS_MODEL_DIR, never downloaded at runtime, failures say why. No network."""
import logging
import os
import urllib.request

import pytest
from fastapi.testclient import TestClient

from app import facecrop, modelstore, pose


def test_model_path_resolves_from_env_var(tmp_path, monkeypatch):
    monkeypatch.setenv("DERMOS_MODEL_DIR", str(tmp_path))
    (tmp_path / facecrop.MODEL_NAME).write_bytes(b"x")
    (tmp_path / pose.MODEL_NAME).write_bytes(b"x")
    assert facecrop.ensure_model() == tmp_path / facecrop.MODEL_NAME
    assert pose.ensure_model() == tmp_path / pose.MODEL_NAME


def test_env_dir_is_the_only_place_looked(tmp_path, monkeypatch):
    # app/models and scripts/models hold the models in a dev checkout; with the env var set they
    # must not be used as a silent fallback.
    monkeypatch.setenv("DERMOS_MODEL_DIR", str(tmp_path))
    assert modelstore.model_dirs() == (tmp_path,)
    with pytest.raises(modelstore.ModelMissing, match=str(tmp_path).replace("\\", "\\\\")):
        facecrop.ensure_model()


def test_missing_model_is_never_downloaded_at_runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("DERMOS_MODEL_DIR", str(tmp_path))
    monkeypatch.setattr(urllib.request, "urlretrieve", lambda *a, **k: pytest.fail("downloaded at runtime"))
    with pytest.raises(modelstore.ModelMissing):
        pose.ensure_model()
    with pytest.raises(modelstore.ModelMissing):
        facecrop.ensure_model()


@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes")
def test_unreadable_model_says_so(tmp_path, monkeypatch):
    monkeypatch.setenv("DERMOS_MODEL_DIR", str(tmp_path))
    p = tmp_path / facecrop.MODEL_NAME
    p.write_bytes(b"x")
    p.chmod(0)
    if os.access(p, os.R_OK):
        pytest.skip("running as root")
    with pytest.raises(PermissionError, match="can't read"):
        facecrop.ensure_model()


def test_detector_failure_logs_real_cause_once(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("DERMOS_MODEL_DIR", str(tmp_path))
    monkeypatch.setattr(facecrop, "_failure_logged", False)
    monkeypatch.setattr(facecrop, "BlazeFace", lambda: facecrop.ensure_model())   # no mediapipe needed
    facecrop.set_detector(None)
    caplog.set_level(logging.ERROR, logger="dermos")
    for _ in range(3):
        with pytest.raises(facecrop.DetectorUnavailable, match="ModelMissing"):
            facecrop.get_detector()
    lines = [r.getMessage() for r in caplog.records if "Face detector failed" in r.getMessage()]
    assert len(lines) == 1 and "ModelMissing" in lines[0] and facecrop.MODEL_NAME in lines[0]


def test_health_reports_face_check(tmp_path, monkeypatch):
    import app.main as m
    c = TestClient(m.app)
    assert c.get("/api/health").json()["face_check"] is True     # conftest's stand-in detector
    monkeypatch.setenv("DERMOS_MODEL_DIR", str(tmp_path))         # no model here
    facecrop.set_detector(None)
    assert c.get("/api/health").json()["face_check"] is False


# ---------------------------------------------------------------- child-process probe (hotfix 2)
# MediaPipe can abort from native code (tcmalloc NumCPUs on Render); Python can't catch an abort,
# so startup loads the models in a child process first. These tests run real child processes.
REAL_PROBE = modelstore.probe   # conftest replaces modelstore.probe with a pass for every test
ABORT = "import os; os.abort()"


def test_probe_reports_a_native_abort(monkeypatch):
    monkeypatch.setattr(modelstore, "PROBE_CODE", ABORT)
    ok, how = REAL_PROBE(timeout=30)
    assert ok is False and how.startswith("exit ") and how != "exit 0"


def test_probe_reports_a_timeout(monkeypatch):
    monkeypatch.setattr(modelstore, "PROBE_CODE", "import time; time.sleep(30)")
    assert REAL_PROBE(timeout=1) == (False, "timeout after 1s")


def test_probe_passes_when_the_child_exits_0(monkeypatch):
    monkeypatch.setattr(modelstore, "PROBE_CODE", "from app import facecrop, pose")
    assert REAL_PROBE(timeout=30) == (True, "exit 0")


def test_probe_timeout_from_env(monkeypatch):
    monkeypatch.setenv("DERMOS_MODEL_PROBE_TIMEOUT", "12")
    assert modelstore.probe_timeout() == 12
    monkeypatch.setenv("DERMOS_MODEL_PROBE_TIMEOUT", "junk")
    assert modelstore.probe_timeout() == modelstore.DEFAULT_PROBE_TIMEOUT


def test_probe_abort_at_startup_keeps_the_app_up_with_face_check_false(tmp_path, monkeypatch, caplog):
    import importlib
    import io

    from PIL import Image
    monkeypatch.setenv("DERMOS_DB", str(tmp_path / "t.db"))
    monkeypatch.setenv("DERMOS_MEDIA", str(tmp_path / "media"))
    import app.main as m
    importlib.reload(m)
    monkeypatch.setattr(modelstore, "probe", REAL_PROBE)       # the real child process ...
    monkeypatch.setattr(modelstore, "PROBE_CODE", ABORT)       # ... which aborts like mediapipe 1.2.0
    facecrop.set_detector(None)
    pose.set_estimator(None)
    # After a failed probe, MediaPipe must never be loaded in the server process.
    monkeypatch.setattr(facecrop, "BlazeFace", lambda *a, **k: pytest.fail("face model loaded in-process"))
    monkeypatch.setattr(pose, "Landmarker", lambda *a, **k: pytest.fail("pose model loaded in-process"))
    b = io.BytesIO()
    Image.new("RGB", (720, 960), (200, 160, 140)).save(b, "JPEG")
    with caplog.at_level(logging.ERROR, logger="dermos"), TestClient(m.app) as c:
        assert c.get("/health").status_code == 200
        h = c.get("/api/health")
        assert h.status_code == 200 and h.json()["face_check"] is False
        r = c.post("/api/scan", files={"image": ("a.jpg", b.getvalue(), "image/jpeg")},
                   data={"actions": "redness"}, headers={"X-Live-Passcode": "test-passcode"})
        assert r.status_code == 503 and "face check isn't available" in r.text
        assert c.get("/api/catalog").status_code == 200        # the rest of the site keeps serving
        assert pose.estimate(Image.new("RGB", (64, 64))) is None
    assert any("model probe FAILED" in r.getMessage() and "exit " in r.getMessage() for r in caplog.records)
