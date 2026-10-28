# Deploying derm//os

Two pieces:

- **API** on Render, as a Docker image built from `backend/Dockerfile` (blueprint: `render.yaml`).
- **App** on Vercel, the Vite PWA in `frontend/` (config: `frontend/vercel.json`).

The deployed demo replays prepared scans (`DEMO_MODE=1`, also the default when the variable is
missing). No YouCam units are spent and no visitor photo is sent to YouCam. Every screen shows a
"Prepared demo data" label while that's true.

This file lists variable **names** only. Never put secret values in this file, the README or any
committed file: set them in the Render and Vercel dashboards.

## Before you deploy

1. Tests, from `backend/`: `python -m pytest -q`, `python -m benchmark`, `python scripts/claim_lint.py`.
   From `frontend/`: `npm run build`. CI (`.github/workflows/ci.yml`) runs the same on every push.
2. Optional, if Docker Desktop is running: `docker build -t dermos-api backend` then
   `docker run --rm -p 127.0.0.1:8010:8000 dermos-api` and open `http://127.0.0.1:8010/health`.
3. Push to GitHub. Render and Vercel deploy from the repo.

## 1. API on Render

1. Render dashboard → **New** → **Blueprint** → pick the repo. Render reads `render.yaml` and creates
   `dermos-api` (Docker, free plan, health check `/health`).
2. Render asks for the `sync: false` variables. Leave them empty for now:
   `CORS_ORIGINS` (filled in after step 2 below), and `YOUCAM_API_KEY`, `LIVE_SCAN_PASSCODE` and
   `LIVE_SCAN_MIN_BALANCE` (only for a live judge session; without the first two live scans are impossible).
3. **Apply**. The first build takes a few minutes (it downloads the face model into the image).
4. Open `https://<your-service>.onrender.com/health`: expect `{"ok": true}`. Then
   `/api/health`: expect `"server_demo_mode": true` and `"live_scans": "off"`.

| Variable | Where | Purpose |
| --- | --- | --- |
| `DEMO_MODE` | render.yaml | `1` = replay prepared scans (the default) |
| `DERMOS_SEED` | render.yaml | Empty database on start: seed the demo routine |
| `DERMOS_DB` | render.yaml | SQLite file path |
| `DERMOS_MEDIA` | render.yaml | Saved mask images |
| `TRUST_PROXY` | render.yaml | Read the client IP from Render's last `X-Forwarded-For` hop |
| `SCAN_RATE_LIMIT` | render.yaml | Scans per IP per window, `count/seconds` |
| `YOUCAM_UNIT_RESERVE` | render.yaml | Units always kept back from live scans |
| `JUDGE_UNIT_CAP_TOTAL` | render.yaml | Live units this server may spend in total |
| `JUDGE_UNIT_CAP_DAILY` | render.yaml | Live units per UTC day |
| `LIVE_SCAN_MIN_BALANCE` | dashboard | The real cap: no live scan may leave the YouCam balance below this |
| `LLM_PROVIDER` | render.yaml | `none`: the optional language layer stays off (it needs a local Ollama server) |
| `CORS_ORIGINS` | dashboard | Your Vercel URL |
| `YOUCAM_API_KEY` | dashboard | Live judge session only |
| `LIVE_SCAN_PASSCODE` | dashboard | Live judge session only |

Free plan notes:

- **Sleep.** The free instance sleeps when idle. The first request after a pause takes about 30
  seconds or more; the app shows "Waking the server, about 30 seconds" and retries on its own.
- **Resets.** The instance disk is temporary. The database (trials, scans, history) resets on every
  restart and redeploy, and the seed runs again. **That includes the judge unit counter**, so
  `JUDGE_UNIT_CAP_TOTAL` is "per server start", not lifetime. `LIVE_SCAN_MIN_BALANCE` is the cap
  that survives restarts: before every live scan the server reads the real YouCam balance (a free
  call) and sends nothing that would leave it below the floor. If the balance can't be read, the
  scan isn't sent either.
- **Memory.** One 12 MP photo crop peaks at about 290 MB on Windows (`python scripts/measure_memory.py`);
  the free instance has 512 MB.

## 2. App on Vercel

1. Vercel dashboard → **Add New** → **Project** → import the repo.
2. **Root Directory**: `frontend`. Vercel reads `frontend/vercel.json` (Vite, `npm run build`, output `dist`).
3. **Environment variable**: `VITE_API_BASE` = the Render URL, e.g. `https://<your-service>.onrender.com`
   (no trailing slash). It's read at build time, so redeploy after changing it.
4. Deploy. Copy the Vercel URL into Render's `CORS_ORIGINS` and let Render redeploy.

| Variable | Where | Purpose |
| --- | --- | --- |
| `VITE_API_BASE` | Vercel (build time) | API origin. Empty in local dev, where Vite proxies to the local API |

## 3. Check it

- Open the Vercel URL on a phone. The landing page says "Same face, same light, one change, honest verdict."
- **Try the 90-second demo**: 8 steps, each labelled "Prepared demo data". Render's logs show no YouCam calls.
- Learn → **Delete my saved scans** reports how many were deleted.

## Live scans for a judge session (optional)

Live scans need **all** of: `DEMO_MODE=0` on the server, the passcode on the device, a readable
YouCam balance that stays at or above `LIVE_SCAN_MIN_BALANCE` after the scan, units left under both
judge caps, and a balance above the reserve after the scan. Whenever the floor or a cap stops a
scan, it replays prepared data and the app says so; nothing is sent to YouCam.

1. On Render set `YOUCAM_API_KEY` and `LIVE_SCAN_PASSCODE`, and change `DEMO_MODE` to `0`.
   Set LIVE_SCAN_MIN_BALANCE = your balance at deploy time minus the units you'll allow judges (e.g. 300).
   Read the balance first with the free credit call (`GET /s2s/v1.0/client/credit`).
2. On the phone: Learn → **Live scans** → enter the passcode. Only that device scans live; everyone
   else keeps getting prepared data. A wrong passcode is refused, not replayed.
3. Each live scan with the default 4 concerns costs 9 units (SD). With the defaults that's at most
   11 live scans a day and 33 per server start. When a cap is reached, the scan replays prepared data
   and the app says so in plain words; nothing is sent to YouCam.
4. After each live scan the server saves the masks, then asks YouCam to delete the task (photo and outputs).
5. Afterwards set `DEMO_MODE` back to `1`. The guided demo only runs in demo mode.

## Local run (Windows / PowerShell, no keys needed)

```powershell
cd backend
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
# second terminal
cd frontend
npm install
npm run dev -- --host 127.0.0.1 --port 5180
```

`DEMO_MODE` defaults to `1`, so this runs with prepared data and no YouCam key. For local live scans
put `DEMO_MODE=0`, `YOUCAM_API_KEY` and `LIVE_SCAN_PASSCODE` in `backend/.env`, then enter the passcode
on the Learn page.
