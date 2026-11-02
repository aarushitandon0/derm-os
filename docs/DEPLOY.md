# Deploying derm//os

Two pieces, in this order:

1. **API on Render**: a Docker image from `backend/Dockerfile` (blueprint: `render.yaml`).
2. **App on Vercel**: the Vite PWA in `frontend/` (config: `frontend/vercel.json`).

The public demo runs with `DEMO_MODE=1`: prepared demo faces, no YouCam calls, no units spent. This file lists variable **names** only. Put secret values in the Render and Vercel dashboards, never in a committed file.

## Before you start

1. Push the branch to GitHub (Render and Vercel deploy from the repo).
2. Have a Render account and a Vercel account, both signed in with GitHub.

## Part 1: API on Render

1. Open **dashboard.render.com** → **New +** (top right) → **Blueprint**.
2. Pick the `derm-os` repository and the branch you pushed. Render reads `render.yaml` and shows one service, **dermos-api** (Docker, Free plan). Click **Apply** / **Deploy Blueprint**.
3. Render asks for the variables marked `sync: false`. For the public demo, **leave all four empty** for now:
   - `CORS_ORIGINS` (you fill it in during Part 2);
   - `YOUCAM_API_KEY`, `LIVE_SCAN_PASSCODE` and `LIVE_SCAN_MIN_BALANCE` (only for a live session, see the end).
4. Wait for the first build (several minutes: it installs mediapipe and downloads the two face models into the image). The log ends with `face model: …`, then `pose model: …`, then Uvicorn starting.
5. Copy the service URL from the top of the service page, e.g. `https://dermos-api.onrender.com`. If that name was taken, Render adds a suffix: use whatever it shows.
6. Open `<Render URL>/health` in a browser. Expect `{"ok":true}`.

Variables already set by `render.yaml`:

| Name | Value in render.yaml | Purpose |
| --- | --- | --- |
| `DEMO_MODE` | `1` | Prepared demo faces, no YouCam calls |
| `DERMOS_SEED` | `1` | A fresh database starts with the demo personas |
| `DERMOS_DB` | `/tmp/dermos.db` | SQLite path (resets on every restart) |
| `DERMOS_MEDIA` | `/tmp/dermos-media` | Saved images (reset on every restart) |
| `TRUST_PROXY` | `1` | Read the client IP behind Render's proxy, for the rate limit |
| `SCAN_RATE_LIMIT` | `30/600` | Scans per IP per 10 minutes |
| `YOUCAM_UNIT_RESERVE` | `200` | Units always kept back |
| `JUDGE_UNIT_CAP_TOTAL` | `300` | Live units per server start |
| `JUDGE_UNIT_CAP_DAILY` | `100` | Live units per UTC day |
| `YOUCAM_FACE_ANGLE_STRICTNESS` | `flexible` | Skin Tone's face-angle check at its most lenient level |
| `LLM_PROVIDER` | `none` | The optional language layer stays off |

Set in the dashboard:

| Name | When |
| --- | --- |
| `CORS_ORIGINS` | Always: your Vercel URL (Part 2, step 7) |
| `YOUCAM_API_KEY` | Live session only |
| `LIVE_SCAN_PASSCODE` | Live session only |
| `LIVE_SCAN_MIN_BALANCE` | Live session only |

## Part 2: App on Vercel

1. Open **vercel.com/new** → **Import** next to the `derm-os` repository.
2. **Root Directory** → **Edit** → choose `frontend` → **Continue**. Vercel detects Vite from `frontend/vercel.json` (`npm ci`, `npm run build`, output `dist`).
3. Open **Environment Variables** and add:
   - Name `VITE_API_BASE`, value your Render URL from Part 1 step 5, **with no trailing slash**.
   The build stops with a clear error if this is missing, so a deploy can never point at the wrong place.
4. Click **Deploy** and wait for "Congratulations".
5. Copy the production URL, e.g. `https://derm-os.vercel.app` (Project → **Domains**).
6. Back in Render: **dermos-api** → **Environment** → `CORS_ORIGINS` → **Edit**, paste the Vercel URL (no trailing slash; separate several with commas) → **Save Changes**.
7. Render redeploys by itself. Wait until it shows **Live**.

`VITE_API_BASE` is read at build time. If you ever change it, redeploy on Vercel (**Deployments** → ⋯ → **Redeploy**).

## Part 3: Free checks (no units)

Do these in order. None of them calls YouCam.

1. **Health.** Open `<Render URL>/api/health`. Expect `"ok":true`, `"server_demo_mode":true`, `"live_scans":"off"` and `"youcam_key":false`.
2. **CORS.** In PowerShell (replace both URLs):

   ```powershell
   curl.exe -s -i -X OPTIONS "<Render URL>/api/basket" -H "Origin: <Vercel URL>" -H "Access-Control-Request-Method: POST" | Select-String "HTTP/|access-control-allow-origin"
   ```

   Expect `200` and `access-control-allow-origin: <Vercel URL>`. If the header is missing, check that `CORS_ORIGINS` matches the Vercel URL exactly.
3. **Demo walk on your phone.** Open the Vercel URL:
   - first visit after a pause: "Waking the server" for about 30 seconds, then the home screen;
   - **Build my basket from my face** → **Use Riya's demo face** → **Build my basket**;
   - the face map, four cards, the **Skipped** list with reasons, "You already own", and the start plan, with the demo-data tag on screen;
   - **See the finish on you**: says "Preview appears on a live scan" in demo mode;
   - paste an ingredient list into **Check any product**;
   - Home → **Build my basket from my face** → **Use a beginner demo face** → **Build my basket**: every card says "Gentle start for new routines".
4. **No YouCam calls.** In Render → **Logs**, there should be no "YouCam basket run" lines.

## Part 4: Accounts with Supabase (optional, free, no units)

Accounts add sign up / log in, saved baskets and a profile page. Without these variables the app is exactly the demo above: no login controls, nothing stored per person. The demo (Riya, beginner) never needs an account and never writes to the account tables.

What is stored per account: name, finish goal, budget, the beginner flag, history (ingredient chips and product notes, with a "confirmed by a doctor" flag), what you own, saved baskets with their start plans, and scan **results** (zone types, concern values, undertone and how it was worked out, engine versions). **Face photos are never stored**, by anyone: no table has a column for one.

### 4.1 Variable names

Order: apply the migration (4.2) **before** you set `DATABASE_URL` on Render, so the server starts against tables that exist.

Render (**dermos-api** → **Environment**):

| Name | Where to find the value in Supabase | Notes |
| --- | --- | --- |
| `DATABASE_URL` | **Connect** (top bar) → **Session pooler** | Must be the **session pooler**, port **5432**, user `postgres.<project-ref>`, host `aws-…pooler.supabase.com`. Not the direct connection (IPv6 only; Render Free has no IPv6), not the transaction pooler (port 6543). Percent-encode special characters in the password. |
| `SUPABASE_URL` | **Project Settings** → **Data API** → Project URL | `https://<project-ref>.supabase.co`, no trailing slash. Used to check sign-in tokens against the project's public keys. |
| `SUPABASE_SERVICE_ROLE_KEY` | **Project Settings** → **API Keys** → `service_role` / secret key | Server only. Used for one thing: deleting the sign-in account when someone deletes their account. Never put it in Vercel. |
| `SUPABASE_JWT_SECRET` | **Project Settings** → **JWT Keys** → Legacy JWT secret | Optional. Only for a project still signing tokens with the legacy shared secret (HS256). New projects use signing keys and don't need it. |

Vercel (**Project** → **Settings** → **Environment Variables**), then **Redeploy** (they're read at build time):

| Name | Where | Notes |
| --- | --- | --- |
| `VITE_SUPABASE_URL` | same Project URL as above | |
| `VITE_SUPABASE_ANON_KEY` | **Project Settings** → **API Keys** → `anon` / publishable key | Public by design. Row Level Security is on for every table with no policies, so this key can read or write nothing in the database. |

### 4.2 Apply the migration from your PC (once, and after any new file in `backend/migrations`)

```powershell
cd backend
python -m pip install -r requirements.txt
$env:DATABASE_URL = Read-Host "Session pooler connection string"   # pasted, not saved anywhere
python scripts/migrate.py
Remove-Item Env:DATABASE_URL
```

Expect `applied 001_accounts.sql` (a second run says `Up to date (1 applied).`). It creates `profiles`, `scans`, `user_history`, `user_shelf`, `user_baskets`, the unit counter `spend`, the guest / demo tables, and `schema_migrations`, with Row Level Security on for every one. The script refuses a port-6543 string and never prints the connection string.

With `DATABASE_URL` set on Render, everything the server keeps (accounts, guest / demo data and the judge unit counter) lives in Postgres and survives restarts. `DERMOS_DB` is then unused.

### 4.3 Auth settings in Supabase

1. **Authentication** → **Sign In / Providers** → **Email**: enabled. "Confirm email" on is fine: new users get a link first.
2. **Authentication** → **URL Configuration**:
   - **Site URL**: your Vercel URL, e.g. `https://derm-os.vercel.app`.
   - **Redirect URLs**: add the same URL (and `http://127.0.0.1:5180` if you test locally). Confirmation and reset-password links come back here.
3. The free built-in email sender is rate-limited (a few emails an hour). Enough for judging; for more, add your own SMTP under **Authentication** → **Emails**.

### 4.4 Free verification (no units)

1. `<Render URL>/api/health` shows `"accounts":true`.
2. Open the Vercel URL in a **private window**. The home screen has **Log in** at the top right.
3. **Log in** → **Sign up** with an email you can open → confirm from the email → log in.
4. **Build my basket from my face** → **Use Riya's demo face** → **Build my basket** → **Save this basket to your profile** → "Saved to your profile".
5. **Reload** the page → **Profile**: the basket is listed, tagged "Demo data", with its start plan under **Open**. "Past scans" is empty: a demo face adds no scan.
6. **Download my data**: a JSON file with your profile, history, shelf and the basket. No photo, no image link.
7. **Delete my account** → confirm. You land on the home screen, logged out.
8. **Log in** again with the same email and password: it fails ("That email and password don't match an account").

In Supabase → **Table Editor**, the account tables have no rows for that user, and **Authentication** → **Users** no longer lists them.

## Live session (optional, spends units)

A live basket costs **34 units** (Skin Tone 20 + Skin Analysis 12 + 2 try-on renders). Do this only with an approved unit budget.

1. Read the balance with the free credit call (`GET /s2s/v1.0/client/credit`).
2. In Render → **Environment**: set `YOUCAM_API_KEY` and `LIVE_SCAN_PASSCODE`, set `LIVE_SCAN_MIN_BALANCE` to *your balance minus the units you allow*, and change `DEMO_MODE` to `0`. Save.
3. On the phone: Learn → **Live scans** → enter the passcode. Only that device runs live.
4. Afterwards set `DEMO_MODE` back to `1` and clear `YOUCAM_API_KEY`.

A live run stops and replays prepared data, saying so, if the balance can't be read, if the run would leave less than `LIVE_SCAN_MIN_BALANCE` or the reserve, or if a judge cap is reached.

## Free tier risks

- **Memory (main risk).** Render Free has 512 MB. Measured locally with mediapipe 1.2.0: the app idles at about 100 MB; with both face models loaded and two 12 MP photos run through the crop and the pose precheck it peaked at **439 MB**. The demo buttons ("Use Riya's demo face") load no models, but a real selfie does. Two people uploading full-size phone photos at the same moment could go over 512 MB and restart the server. If that happens: downscale photos in the browser before upload, or move to a plan with more memory.
- **Sleep.** The free service sleeps after about 15 minutes idle; the first request then takes about 30 seconds or more. Open the app a minute before a demo or a recording.
- **Resets.** Without `DATABASE_URL`, `/tmp` is wiped on every restart and deploy: saved history and the judge unit counter start again (with it, they live in Postgres; Part 4). `LIVE_SCAN_MIN_BALANCE` is the limit that survives, because it reads the real YouCam balance each time.
- **Image size.** Not measured here (Docker Desktop's engine didn't start on this machine). Expect roughly 0.7–0.9 GB (python:3.12-slim, mediapipe, opencv-contrib, matplotlib, numpy), which mostly means a slower first build.

## Local run (Windows / PowerShell, no keys)

```powershell
cd backend; python -m pip install -r requirements.txt; python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
# second terminal
cd frontend; npm install; npm run dev -- --host 127.0.0.1 --port 5180
```

To test the image locally once Docker runs: `docker build -t dermos-api backend`, then `docker run --rm -p 127.0.0.1:8010:8000 dermos-api` and open `http://127.0.0.1:8010/health`.
