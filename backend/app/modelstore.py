"""Where the two MediaPipe model files live, and how they get there.

  DERMOS_MODEL_DIR set   -> only that folder is used (the Docker image sets /app/models).
  not set (local dev)    -> app/models/, then scripts/models/.

The server never downloads a model while it runs: a missing or unreadable file is an error that
names the path. Models are fetched ahead of time, at image build or once in a dev checkout:

    python -m app.modelstore           # download any missing model into the model folder
    python -m app.modelstore --check   # also load both models (what the server will do)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ENV = "DERMOS_MODEL_DIR"
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
