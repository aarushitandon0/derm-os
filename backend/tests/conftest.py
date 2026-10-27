"""Test isolation: never read backend/.env and never reach the real YouCam API."""
import os

os.environ["DERMOS_NO_DOTENV"] = "1"
os.environ.pop("YOUCAM_API_KEY", None)
os.environ.pop("DEMO_MODE", None)
