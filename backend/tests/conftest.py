"""Test isolation: never read backend/.env and never reach the real YouCam API."""
import os

os.environ["DERMOS_NO_DOTENV"] = "1"
os.environ.pop("YOUCAM_API_KEY", None)
os.environ["DEMO_MODE"] = "0"   # the app defaults to 1; tests opt in to live paths with fakes
# Live scans need DEMO_MODE=0 plus this passcode in the X-Live-Passcode header (app/guard.py).
os.environ["LIVE_SCAN_PASSCODE"] = "test-passcode"
os.environ.pop("SCAN_RATE_LIMIT", None)
os.environ.pop("TRUST_PROXY", None)
os.environ.pop("DERMOS_SEED", None)
# The optional LLM layer is off in tests unless a test sets it up with a fake provider.
for _k in ("LLM_PROVIDER", "LLM_BASE_URL", "LLM_MODEL", "LLM_API_KEY", "ANTHROPIC_API_KEY"):
    os.environ.pop(_k, None)

import pytest  # noqa: E402


def centred_face(img):
    """Stand-in for the face detector in tests: one face, centred, half the photo's width
    (at least the SD target when the photo allows it). Tests that need other faces call
    facecrop.set_detector() themselves."""
    from app.facecrop import Box, TARGET_FACE_PX
    w, h = img.size
    fw = min(max(0.5 * w, TARGET_FACE_PX["sd"]), 0.7 * w, 0.7 * h * 0.75)
    return [Box(w / 2 - fw / 2, h * 0.45 - fw * 0.55, fw, fw * 1.1, 0.99)]


@pytest.fixture(autouse=True)
def _fake_face_detector():
    from app import facecrop
    facecrop.set_detector(centred_face)
    yield
    facecrop.set_detector(None)
