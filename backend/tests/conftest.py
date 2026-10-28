"""Test isolation: never read backend/.env and never reach the real YouCam API."""
import os

os.environ["DERMOS_NO_DOTENV"] = "1"
os.environ.pop("YOUCAM_API_KEY", None)
os.environ.pop("DEMO_MODE", None)
# Live scans need DEMO_MODE=0 plus this passcode in the X-Live-Passcode header (app/guard.py).
os.environ["LIVE_SCAN_PASSCODE"] = "test-passcode"
os.environ.pop("SCAN_RATE_LIMIT", None)
os.environ.pop("TRUST_PROXY", None)
os.environ.pop("DERMOS_SEED", None)
# The optional LLM layer is off in tests unless a test sets it up with a fake provider.
for _k in ("LLM_PROVIDER", "LLM_BASE_URL", "LLM_MODEL", "LLM_API_KEY", "ANTHROPIC_API_KEY"):
    os.environ.pop(_k, None)
