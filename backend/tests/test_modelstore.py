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
