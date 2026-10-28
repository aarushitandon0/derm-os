# derm//os

**Same face, same light, one change, honest verdict.**

derm//os is a skincare decision and follow-up app built on the YouCam AI Skin Analysis API. It turns each skincare purchase into a small, well-run personal experiment:

- **Personal noise floor**: a baseline is several scans, so every concern has a range, not a single number. A later change only counts if it leaves your own range.
- **Comparability gate**: every photo carries a fingerprint (light level, light colour, face size, head angle, camera, time of day). Photos taken under different conditions are not compared.
- **Honest verdicts**: one new product per trial; several changes at once means "can't tell which"; reported symptoms always outrank better-looking scores.
- **History that keeps its meaning**: "this product bothered me", "I avoid fragrance" and "clinician-confirmed allergy" are different records with different effects. Missing ingredient data is never a pass.

Not a diagnostic tool. derm//os supports skincare decisions; it does not diagnose or treat.

## YouCam API used

| Step | Endpoint |
| --- | --- |
| Register file | `POST /s2s/v2.0/file` → `file_id` + presigned URL |
| Upload bytes | `PUT <presigned url>` (no bearer header) |
| Analyse | `POST /s2s/v2.1/task/skin-analysis` with `src_file_id`, `dst_actions`, `format: json` |
| Poll | `GET /s2s/v2.1/task/skin-analysis/{task_id}` until `success` / `error` |
| Delete | `POST /s2s/v2.0/task/delete` with `task_id`, right after the masks are saved (removes the photo and outputs at YouCam) |

All evidence decisions use `raw_score`. YouCam's docs describe `ui_score` as adjusted upward as a "psychological motivator", so it is shown to users but never used to judge change.

## Setup

```bash
cd backend
pip install -r requirements.txt
cp .env.example .env          # add YOUCAM_API_KEY
python -m pytest -q           # 163 tests, no API units spent
python -m benchmark           # evidence benchmark: pass counts, writes results/benchmark.md
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload   # http://127.0.0.1:8000/docs
```

Deploying: see [docs/DEPLOY.md](docs/DEPLOY.md).

## Frontend (PWA)

```powershell
cd frontend
npm install
npm run dev -- --port 5180   # proxies /api and /media to 127.0.0.1:8000
npm run dev:https    # same, over https so a phone on your Wi-Fi can use the camera
```

Screens: Welcome and "What brings you here?" (first launch), Home (Start / Compare / Review), Progress (score vs your noise floor; non-comparable scans hollow), Routine (current experiment, today's checklist, schedule), Learn ("How derm//os decides", delete saved scans, live-scan passcode), Shelf, History, Compare (`#/compare?a=mo-02&b=mo-04` preselects options), Trial (with a calendar `.ics` reminder for check-in dates), Check-in, Capture (MediaPipe Face Landmarker guide: face 60-80% of width, straight on, even light; shutter unlocks only when all pass) → Analysing (steps follow the real request) → Check capture quality (per-field result from the comparability gate), Results (Overview / Concerns / Notes), Visit brief (Summary / Photos, print to PDF).

The welcome hero is one replaceable file: `frontend/public/welcome-hero.svg` (path set in `src/screens/Welcome.tsx`).

## Privacy

Face photos never reach a public place:

- The uploaded photo is measured, sent to YouCam (live scans only), and deleted from this server right after the scan.
- After a live scan's masks are downloaded, the server asks YouCam to delete the task (`POST /s2s/v2.0/task/delete`), which removes the photo and outputs there. If that request fails, it's logged (task id and error type only) and the scan still succeeds.
- Stored scans keep scores, capture conditions and local mask images, never mask URLs (they're signed links to images of a face).
- **Delete my saved scans** (Learn page) removes every scan's scores, capture conditions and saved masks from this server, and asks YouCam again to delete any live scan it hasn't confirmed deleted.
- Committed fixtures hold scores, action set, engine version and fingerprint numbers only. `scripts/make_fixtures.py` strips mask URLs and never copies mask images. In demo mode the app shows a placeholder and "Mask images aren't included in the public demo."
- `.gitignore` keeps `photos/`, `backend/media/` and raw `backend/results/*.json` out of git. A pre-commit hook blocks `.jpg/.jpeg/.png/.heic/.heif/.webp` files outside `frontend/public/` and `docs/design-reference.png`. Install it once: `powershell -ExecutionPolicy Bypass -File scripts/install-hooks.ps1`.

## Demo safety

- Live scans need **both** `DEMO_MODE=0` and the `LIVE_SCAN_PASSCODE`, entered on the Learn page (sent as an `X-Live-Passcode` header). Without the passcode, scans replay recorded fixtures. A wrong passcode is refused. With no passcode configured, live scans are off.
- Scan requests are rate limited per IP (`SCAN_RATE_LIMIT`, default 30 per 10 minutes).
- `DEMO_MODE=1` in `backend/.env`: `/api/scan` replays recorded YouCam responses from `backend/fixtures/<persona>/<set>/` (set = `baseline`, `checkin`, or an explicit `fixture_set` such as `lamp`). The uploaded photo is still fingerprinted from its real pixels, so the comparability gate still reacts to real light. Replayed captures are tagged `source: "replay"`; hand-made placeholders are also tagged `synthetic: true`.
- `python scripts/make_fixtures.py` copies your real `results/*.json` into `fixtures/riya/` (window 1-3 = baseline, window 4-5 = checkin, lamp = lamp), replacing the synthetic placeholders. It keeps scores, actions, engine version and the photo's fingerprint only: no URLs, no mask images.
- Unit guard: before every live scan the server reads the credit balance and refuses below `YOUCAM_UNIT_RESERVE` (default 100). If the balance can't be read, it logs that and continues.
- Masks are downloaded right after each successful task (the URLs expire) into `backend/media/` and served at `/media/...`.

## Run the experiments (do this first)

These produce the two numbers the demo leads with. Use your **phone camera** (laptop webcams are often below the 1080 px HD minimum; SD needs 480 px).

**Experiment 1, noise with no change.** Sit facing a window. Take 5 selfies within 5 minutes, putting the phone down and re-framing between shots. Same phone, no makeup, hair off the forehead, face filling 60 to 80% of the frame width. Save as `window_1.jpg` ... `window_5.jpg`.

**Experiment 2, lighting alone.** Same session, same spot, turn on a warm lamp (or move away from the window) and take 3 more: `lamp_1.jpg` ... `lamp_3.jpg`.

```bash
cd backend
python scripts/run_experiments.py ../photos --dry-run   # checks photo sizes and light, spends nothing
python scripts/run_experiments.py ../photos             # 8 SD tasks
python scripts/run_experiments.py ../photos --replay    # recompute anytime from saved results
```

Results go to `backend/results/` (`report.md` for the README and video, raw responses for replaying the demo without spending units). Use `--hd` for HD actions and `--concerns redness,acne,...` to change the concern set.

What to report: Experiment 1's range per concern ("with nothing changed, redness moved across N points") and Experiment 2's shift beside that range. Then set `TOLERANCES` and `MIN_BAND` in `app/evidence.py` from what you measured.

## Results

### Evidence benchmark

**61 of 61 cases pass** across 12 categories. Run it with `cd backend; python -m benchmark`; the full table is in [backend/results/benchmark.md](backend/results/benchmark.md).

We wrote this benchmark ourselves, so it is **not an independent evaluation**. Each case's expected output comes from the design doc, written before running the engine. It shows the exclusion, comparison and verdict rules behave as designed. It says nothing about how accurate YouCam's scores are. Two rows of the design's benchmark table aren't covered yet because there is no LLM layer: LLM fallback, and the claim validator.

| Category | Cases |
| --- | --- |
| Avoided ingredient is blocked, with the label line | 6 / 6 pass |
| Synonyms are still blocked | 6 / 6 pass |
| Incomplete INCI is unknown, never pass | 5 / 5 pass |
| Product-level reaction blocks that product only | 4 / 4 pass |
| Add switched to replace recalculates | 5 / 5 pass |
| Several changes: can't tell | 4 / 4 pass |
| Overlap: no detectable change | 5 / 5 pass |
| Different conditions: not comparable, re-guide | 10 / 10 pass |
| Symptoms outrank improved scores | 6 / 6 pass |
| Unresolved stop symptom persists | 4 / 4 pass |
| Missing baseline: no trend claim | 4 / 4 pass |
| Wording never claims cause | 2 / 2 pass |

### Experiments 1 and 2

Not run yet. Numbers will go here from `backend/results/report.md`.

## API

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/health` | Key present, rule versions |
| GET | `/api/catalog` | 25 fictional products with INCI lists |
| PUT/GET | `/api/shelf` | Current routine |
| POST/GET/DELETE | `/api/history` | Reaction / avoid / confirmed-allergy records |
| POST | `/api/compare` | Change nothing vs up to 3 options, with exclusion checks and the next question that matters |
| POST | `/api/scan` | Photo → fingerprint → YouCam (or replay) → stored capture; check-ins get an instant comparability check. Optional `client_hour` (0-23) and `client_device` form fields are used when the photo has no EXIF |
| POST | `/api/trials` | Start a one-change trial (blocked products refused) |
| POST | `/api/trials/{id}/checkin` | Log symptoms and any other new products |
| GET | `/api/trials/{id}/evidence` | Verdict, ranges, comparability (per field: checked / failed with reason and fix), every scan with its own gate result, reactions |
| POST | `/api/trials/{id}/reactions/{rid}/resolve` | Mark a reported reaction resolved (`resolved_on` date, optional `note`). A stop symptom keeps the verdict at Stop until this is done |
| DELETE | `/api/captures` | Delete every saved scan on this server (scores, capture conditions, saved masks) and re-request YouCam task delete for live scans not yet confirmed deleted. The photo itself is never kept |

## Layout

```
backend/
  app/youcam.py        YouCam client: upload, task, poll, retries, normalisation, record/replay
  app/fingerprint.py   capture conditions from pixels + EXIF (+ face metrics from the browser)
  app/evidence.py      noise ranges, comparability gate, verdict table
  app/inci.py          ingredient-name normalisation and synonym groups
  app/decision.py      exclusions, routine builder, comparison, next question
  app/catalog.json     25 fictional products
  app/guard.py         live-scan passcode gate, per-IP rate limit, CORS origins
  app/main.py          FastAPI
  benchmark/           evidence benchmark cases + `python -m benchmark`
  scripts/run_experiments.py
  scripts/make_fixtures.py   results -> stripped demo fixtures
  tests/               benchmark, YouCam client (mocked), API flow, privacy, deploy
render.yaml            Render blueprint (API)
frontend/vercel.json   Vercel config (app)
docs/DEPLOY.md         deploy steps and env var names
scripts/git-hooks/     pre-commit hook that blocks photo files
```

## License

MIT
