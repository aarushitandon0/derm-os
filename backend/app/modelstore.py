"""Where the two MediaPipe model files live, and how they get there.

  DERMOS_MODEL_DIR set   -> only that folder is used (the Docker image sets /app/models).
  not set (local dev)    -> app/models/, then scripts/models/.

The server never downloads a model while it runs: a missing or unreadable file is an error that
names the path. Models are fetched ahead of time, at image build or once in a dev checkout:

    python -m app.modelstore           # download any missing model into the model folder
    python -m app.modelstore --check   # also load both models (what the server will do)

MediaPipe can abort the whole process from native code (e.g. tcmalloc can't read the CPU count in
some containers), and an abort can't be caught in Python. So the server first loads both models in
a child process (probe()); only if that exits 0 does it load them in-process.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ENV = "DERMOS_MODEL_DIR"
PROBE_TIMEOUT_ENV = "DERMOS_MODEL_PROBE_TIMEOUT"
DEFAULT_PROBE_TIMEOUT = 60.0
# What the child process runs: load the face detector and the pose model, exactly as the server does.
PROBE_CODE = "from app import facecrop, pose; facecrop.BlazeFace().close(); pose.Landmarker()"
_APP = Path(__file__).resolve().parent
DEFAULT_DIRS = (_APP / "models", _APP.parent / "scripts" / "models")


class ModelMissing(FileNotFoundError):
    pass


def model_dirs() -> tuple[Path, ...]:
    env = os.environ.get(ENV, "").strip()
    return (Path(env),) if env else DEFAULT_DIRS


def resolve(name: str) -> Path:
    """The model file to load. Raises ModelMissing (never downloads)."""
    dirs = model_dirs()
    for d in dirs:
        p = d / name
        if p.is_file():
            if not os.access(p, os.R_OK):
                raise PermissionError(f"model file {p} exists but this user can't read it")
            return p
    raise ModelMissing(f"model {name} not found in {', '.join(str(d) for d in dirs)} "
                       f"(run: python -m app.modelstore)")


def fetch(name: str, url: str) -> Path:
    """Download one model into the first model folder if it isn't there. Build time / dev only."""
    try:
        return resolve(name)
    except ModelMissing:
        pass
    import urllib.request
    dest = model_dirs()[0] / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part")
    urllib.request.urlretrieve(url, tmp)  # model weights only; nothing is uploaded
    tmp.replace(dest)
    return dest


def probe_timeout() -> float:
    try:
        return max(1.0, float(os.environ.get(PROBE_TIMEOUT_ENV, DEFAULT_PROBE_TIMEOUT)))
    except ValueError:
        return DEFAULT_PROBE_TIMEOUT


def probe(timeout: float | None = None) -> tuple[bool, str]:
    """Load both models in a child process. (True, "exit 0") when they load; otherwise False and
    what happened ("exit -6", "timeout after 60s", ...). Never raises, never aborts this process."""
    timeout = probe_timeout() if timeout is None else timeout
    try:
        r = subprocess.run([sys.executable, "-c", PROBE_CODE], cwd=str(_APP.parent),
                           capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, f"timeout after {timeout:g}s"
    except Exception as e:  # noqa: BLE001 - couldn't start the child at all
        return False, f"could not start ({type(e).__name__}: {e})"
    if r.returncode == 0:
        return True, "exit 0"
    tail = (r.stderr or "").strip().splitlines()[-1:]   # library output only; no image data exists here
    return False, f"exit {r.returncode}" + (f" ({tail[0][:300]})" if tail else "")


def main(argv: list[str]) -> int:
    from . import facecrop, pose
    print("face model:", fetch(facecrop.MODEL_NAME, facecrop.MODEL_URL))
    print("pose model:", fetch(pose.MODEL_NAME, pose.MODEL_URL))
    if "--check" in argv:
        facecrop.BlazeFace().close()
        print("face model OK")
        pose.Landmarker()
        print("pose model OK")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
