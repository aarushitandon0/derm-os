# Deploying derm//os

The public demo runs as two pieces:

- **API** on Render (FastAPI + SQLite), from `render.yaml` at the repo root.
- **App** on Vercel (the Vite PWA in `frontend/`), from `frontend/vercel.json`.

The deployed demo replays recorded scans by default (`DEMO_MODE=1`). No YouCam units are spent and no visitor photo is sent to YouCam. Every screen shows a "Demo · scan scores are prepared data" label while that's true.

Never put values of secrets in this file, the README, or any committed file. Set them in the Render and Vercel dashboards.

## Before you deploy

1. Tests: `cd backend; python -m pytest -q` and `python -m benchmark`. In `frontend/`: `npm run build`.
2. Fixtures: if you replaced the synthetic fixtures with your own scans, use `python scripts/make_fixtures.py`. It keeps only scores, actions, engine version and the photo's fingerprint numbers. It never copies mask images and refuses to write anything that looks like a URL or image path. `tests/test_privacy.py` checks the committed fixtures too.
3. Install the pre-commit hook once (it blocks photo files): `powershell -ExecutionPolicy Bypass -File scripts/install-hooks.ps1`.
4. Push to GitHub. Render and Vercel deploy from the repo.

## 1. API on Render

1. Render dashboard → **New → Blueprint** → pick this repo. Render reads `render.yaml` and creates `dermos-api`.
2. When Render asks for the `sync: false` variables:
   - `CORS_ORIGINS`: leave it empty for now and fill it in after step 2 (the Vercel URL).
   - `YOUCAM_API_KEY` and `LIVE_SCAN_PASSCODE`: leave both empty for a replay-only demo. Live scans stay impossible without them.
3. Deploy, then open `https://<render-service>.onrender.com/api/health`. Expect `"server_demo_mode": true` and `"live_scans": "off"`.

| Variable | Set in | Purpose |
| --- | --- | --- |
| `DEMO_MODE` | render.yaml (`1`) | `1` = always replay recorded scans |
| `DERMOS_SEED` | render.yaml (`1`) | Empty database on start → seed the demo persona's routine (Riya's 4 products). Never touches existing data |
| `DERMOS_DB` | render.yaml | SQLite file path |
| `DERMOS_MEDIA` | render.yaml | Where saved mask images go |
| `TRUST_PROXY` | render.yaml (`1`) | Read the client IP from Render's last `X-Forwarded-For` hop (for the rate limit) |
| `SCAN_RATE_LIMIT` | render.yaml (`30/600`) | Scans per IP per window (count/seconds). `0` turns it off |
| `YOUCAM_UNIT_RESERVE` | render.yaml (`100`) | Unit guard: refuse live scans below this balance |
| `CORS_ORIGINS` | dashboard | Comma-separated allowed origins: your Vercel URL |
| `YOUCAM_API_KEY` | dashboard (optional) | Only for live scans |
| `LIVE_SCAN_PASSCODE` | dashboard (optional) | Only for live scans |
| `PYTHON_VERSION` | render.yaml | Python runtime |

On Render's free plan the instance disk is temporary. The database and saved masks reset on every restart or redeploy, and the seed runs again. That suits a public demo. The free instance also sleeps when idle, so the first request after a pause can take about a minute.

## 2. App on Vercel

1. Vercel dashboard → **Add New → Project** → import the repo.
2. **Root Directory**: `frontend`. Vercel picks up `frontend/vercel.json` (Vite, `npm run build`, output `dist`).
3. **Environment variable**: `VITE_API_BASE` = your Render URL, e.g. `https://<render-service>.onrender.com` (no trailing slash). It's read at build time, so redeploy after changing it.
4. Deploy, then copy the Vercel URL into Render's `CORS_ORIGINS` and let Render redeploy.

| Variable | Set in | Purpose |
| --- | --- | --- |
| `VITE_API_BASE` | Vercel (build time) | API origin. Empty in local dev, where Vite proxies `/api` and `/media` to 127.0.0.1:8000 |

## 3. Check it

- Open the Vercel URL on a phone. The grey "Demo" label is at the top of every screen.
- Take a baseline scan: the result says prepared data, and Render's logs show no YouCam calls.
- Learn → "Delete my saved scans" reports how many were deleted.

## Live scans for a judge session (optional)

Live scans need **both** of these: `DEMO_MODE=0` on the server, **and** the right passcode on the device.

1. On Render set `YOUCAM_API_KEY`, `LIVE_SCAN_PASSCODE`, and change `DEMO_MODE` to `0`.
2. On the phone: Learn → **Live scans** → enter the passcode. Only that device scans live. Everyone else keeps getting replays (and the Demo label). A wrong passcode is refused, not replayed.
3. The unit guard still refuses live scans below `YOUCAM_UNIT_RESERVE`. After each live scan the server downloads the masks, then asks YouCam to delete the task (photo and outputs).
4. Afterwards set `DEMO_MODE` back to `1`.

## Local run (Windows / PowerShell)

```powershell
cd backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
# second terminal
cd frontend
npm run dev -- --port 5180
```

Locally, live scans follow the same rule. Put `LIVE_SCAN_PASSCODE` in `backend/.env` with `DEMO_MODE=0`, then enter it on the Learn page.
