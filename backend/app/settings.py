"""Load backend/.env once, before anything reads os.environ.

Existing environment variables win over the file, so a shell `$env:DEMO_MODE="1"`
still overrides it. Tests set DERMOS_NO_DOTENV=1 so a developer's real key
never leaks into the test run.
"""
from __future__ import annotations

import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
ENV_PATH = BACKEND_DIR / ".env"


def load_env() -> bool:
    if os.environ.get("DERMOS_NO_DOTENV") == "1":
        return False
    try:
        from dotenv import load_dotenv
    except ImportError:  # optional at runtime; requirements.txt installs it
        return False
    return load_dotenv(ENV_PATH, override=False)


def flag(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


load_env()
