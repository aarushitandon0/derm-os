# derm//os API for Render (or any Docker host). Build from backend/:
#   docker build -t dermos-api backend
#   docker run --rm -p 127.0.0.1:8010:8000 dermos-api
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Shared libraries a slim image lacks: libgl1 + libglib2.0-0 for MediaPipe's OpenCV dependency, and
# libegl1 + libgles2 for MediaPipe's own native library (tasks/c/libmediapipe.so links libEGL.so.1
# and libGLESv2.so.2; without them the face detector can't load and every photo gets a 503).
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libegl1 libgles2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app
COPY fixtures ./fixtures
COPY benchmark ./benchmark
COPY scripts ./scripts
# SQL migrations for Supabase Postgres (applied with python scripts/migrate.py; see docs/DEPLOY.md).
COPY migrations ./migrations

# Both MediaPipe models (face ~230 KB, head pose ~3.6 MB) live at one fixed path inside the image,
# downloaded at BUILD time. The server never downloads them; it only loads from DERMOS_MODEL_DIR
# (app/modelstore.py). World-readable, so the non-root runtime user below can load them.
ENV DERMOS_MODEL_DIR=/app/models
RUN python -m app.modelstore \
    && chmod 755 /app/models && chmod 644 /app/models/*

# Public-demo defaults. Render's dashboard values override these.
ENV DEMO_MODE=1 \
    DERMOS_SEED=1 \
    DERMOS_DB=/tmp/dermos.db \
    DERMOS_MEDIA=/tmp/dermos-media \
    TRUST_PROXY=1 \
    SCAN_RATE_LIMIT=30/600 \
    YOUCAM_UNIT_RESERVE=200 \
    JUDGE_UNIT_CAP_TOTAL=300 \
    JUDGE_UNIT_CAP_DAILY=100 \
    LLM_PROVIDER=none \
    YOUCAM_FACE_ANGLE_STRICTNESS=flexible \
    PORT=8000

RUN useradd --create-home dermos
USER dermos
# Load both models AS THE RUNTIME USER, so a model or library the server can't use fails the build,
# not the first photo. The detectors themselves are created again at startup (app/main.py).
RUN python -m app.modelstore --check
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers 1"]
