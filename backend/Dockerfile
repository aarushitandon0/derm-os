# derm//os API for Render (or any Docker host). Build from backend/:
#   docker build -t dermos-api backend
#   docker run --rm -p 127.0.0.1:8010:8000 dermos-api
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# MediaPipe's OpenCV dependency needs these two shared libraries on a slim image.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app
COPY fixtures ./fixtures
COPY benchmark ./benchmark
COPY scripts ./scripts

# The face model is downloaded at BUILD time (about 230 KB), so a cold start never fetches it.
# The detector itself is created once, on the first scan (app/facecrop.get_detector).
RUN python -c "from app.facecrop import ensure_model; print('face model:', ensure_model())"
# The head-pose model for the free basket precheck (app/pose.py, about 3.6 MB), also at build time.
RUN python -c "from app.pose import ensure_model; print('pose model:', ensure_model())"

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
    PORT=8000

RUN useradd --create-home dermos
USER dermos
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers 1"]
