# derm//os

**Same face, same light, one change, honest verdict.**

derm//os is a skincare decision and follow-up app built on the YouCam AI Skin Analysis API. It turns each skincare purchase into a small, well-run personal experiment:

- **Personal noise floor**: a baseline is several scans, so every concern has a range, not a single number. A later change only counts if it leaves your own range.
- **Comparability gate**: every photo carries a fingerprint (light level, light colour, face size, head angle, camera, time of day). Photos taken under different conditions are not compared.
- **Same crop for every photo**: each photo is cropped and scaled the same way, so your distance from the camera doesn't change the comparison.
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

### Unit costs

From `GET /s2s/v2.0/credit/feature-cost` (free, read 28 Oct 2026; paged with `starting_token`). The price is per task and goes up in steps with the number of concerns, not per concern:

| Concerns per scan | SD (v2.1) | HD (v2.1) |
| --- | --- | --- |
| 1-4 | 9 | 12 |
| 5-8 | 12 | 16 |
| 9-12 | 14 | 20 |
| 13-16 | 16 | 22 |

Before every live scan the server works out that scan's exact price from this list (built-in copy if the list can't be read) and refuses unless the balance covers it plus `YOUCAM_UNIT_RESERVE`. `run_experiments.py` prints the exact cost of the whole run and refuses unless the balance covers all of it.

All evidence decisions use `raw_score`. YouCam's docs describe `ui_score` as adjusted upward as a "psychological motivator", so it is shown to users but never used to judge change.

## Setup

```bash
cd backend
pip install -r requirements.txt
cp .env.example .env          # add YOUCAM_API_KEY
python -m pytest -q           # 293 tests, no API units spent, no LLM calls
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

Screens: Welcome and "What brings you here?" (first launch), Home (Start / Compare / Review), Progress (score vs your noise floor; non-comparable scans hollow), Routine (current experiment, today's checklist, schedule), Learn ("How derm//os decides", delete saved scans, live-scan passcode), Shelf, History, Compare (`#/compare?a=mo-02&b=mo-04` preselects options), Trial (with a calendar `.ics` reminder for check-in dates), Check-in, Capture (MediaPipe Face Landmarker guide: one face, close enough, roughly straight, light OK; at check-ins the light is also compared with the baseline using the gate's own tolerances. When the checks hold for about a second the photo takes itself after a short countdown ring; the baseline takes its 3 photos on its own, asking you to look away and back between them; a manual shutter stays as a fallback) → Analysing (steps follow the real request) → Check capture quality (per-field result from the comparability gate), Results (Overview / Concerns / Notes), Visit brief (Summary / Photos, print to PDF).

The welcome hero is one replaceable file: `frontend/public/welcome-hero.svg` (path set in `src/screens/Welcome.tsx`).

## Capture normalisation

Each photo is cropped and scaled the same way, so your distance from the camera doesn't change the comparison.

Every upload goes through `app/facecrop.py` on the server before it is measured or sent to YouCam (the experiment script uses the same code):

1. Read upright (the photo's own EXIF orientation) as full-colour RGB.
2. Find faces with a local detector (MediaPipe BlazeFace, on the server). Exactly one is required.
3. Crop 3:4 around the face with the face at 75% of the crop width, shifted (never resized) to stay inside the photo.
4. Scale down, never up, so the face is a fixed width: **360 px for SD** (output 480 x 640, SD's 480 px minimum) or **810 px for HD** (1080 x 1440). HD only when the photo is big enough to reach it; a trial keeps the mode of its first photo, so SD and HD never mix.

No colour, brightness or rotation edits. The fingerprint keeps the original face size (pixels and % of the original frame) next to the normalised one; the gate's face-size check reads the normalised one, every other gate rule and tolerance is unchanged. A photo is refused only when it has to be, with one fix: no face, more than one face, face too small to reach the target without enlarging it ("Hold the phone a little closer"), face cut off by the edge, or so close the crop can't fit. YouCam never receives an image it would reject for size.

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
- Unit guard: before every live scan the server works out that scan's exact cost (see Unit costs), reads the credit balance and refuses unless the balance covers the cost plus `YOUCAM_UNIT_RESERVE` (default 100). If the balance can't be read, it logs that and continues.
- Masks are downloaded right after each successful task (the URLs expire) into `backend/media/` and served at `/media/...`.

## Run the experiments (do this first)

These produce the two numbers the demo leads with. Use your **phone camera** and keep the phone's original JPEGs (not screenshots or converted PNGs). Framing is handled for you: every photo is cropped and scaled by the app's own code, so you don't have to fill the frame. Hold the phone at a normal selfie distance.

**Experiment 1, noise with no change.** Sit facing a window. Take 5 selfies within 5 minutes, putting the phone down and re-framing between shots. Same phone, no makeup, hair off the forehead. Save as `window_1.jpg` ... `window_5.jpg`.

**Experiment 2, lighting alone.** Same session, same spot, turn on a warm lamp (or move away from the window) and take 3 more: `lamp_1.jpg` ... `lamp_3.jpg`.

```bash
cd backend
python scripts/run_experiments.py ../photos --dry-run   # crop/scale per photo + exact unit cost, spends nothing
python scripts/run_experiments.py ../photos             # refuses unless the balance covers the whole run
python scripts/run_experiments.py ../photos --replay    # recompute anytime from saved results
```

Results go to `backend/results/` (`report.md` for the README and video, raw responses for replaying the demo without spending units). `--actions redness,texture,...` picks the concerns (the cost is per scan, in steps of 4 concerns); `--hd` uses HD only if every photo can reach HD's size. A palette or other reduced-colour image is converted to RGB with a clear warning. `scripts/crop_faces.py ../photos` writes a preview of exactly what YouCam would receive into `photos/normalised/`. Earlier results made from palette PNGs are listed in `results/legacy_palette.json`: never reused or reported, moved to `results/legacy_palette/` when a re-shoot replaces them.

What to report: Experiment 1's range per concern ("with nothing changed, redness moved across N points") and Experiment 2's shift beside that range. Then set `TOLERANCES` and `MIN_BAND` in `app/evidence.py` from what you measured.

## Optional LLM layer

Off by default (`LLM_PROVIDER=none`), and the app works fully without it. The AI only extracts and words things; rules decide. Verdicts and exclusion checks never go through it.

- **Intake** (`app/llm/intake.py`): free text → proposed records using the three record types. Strict JSON schema; every record must quote the user's words; products match the catalog only (unknown names stay as typed, unmatched); a product reaction never becomes an ingredient record; "confirmed allergy" only when the text says a clinician confirmed it. Unclear fields are marked "needs confirmation" and nothing saves until the user confirms each record.
- **Explanations** (`app/llm/explain.py`): the LLM sees only the stored structured result. The claim validator rejects causal wording, diagnosis words, products or ingredients not in the record, a verdict stronger than the stored one, and numbers not in the record. On rejection the template sentence shows and only the reason code is logged.
- **Providers** (`app/llm/providers.py`): 12 s timeout (`LLM_TIMEOUT`) plus one retry; any failure falls back silently to templates. Keys come from the environment only and are never logged.

| Env var | Value |
| --- | --- |
| `LLM_PROVIDER` | `none` (default) · `anthropic` · `openai_compatible` |
| `ANTHROPIC_API_KEY` | for `anthropic` (`LLM_MODEL` optional, default `claude-haiku-5-5`) |
| `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY` | for `openai_compatible`: Groq, Gemini's OpenAI endpoint, or local Ollama (`http://127.0.0.1:11434/v1`, no key) |

## Results

### Evidence benchmark

**91 of 91 cases pass** across 16 categories. Run it with `cd backend; python -m benchmark`; the full table is in [backend/results/benchmark.md](backend/results/benchmark.md).

We wrote this benchmark ourselves, so it is **not an independent evaluation**. Each case's expected output comes from the design doc, written before running the engine. It shows the exclusion, comparison and verdict rules behave as designed. It says nothing about how accurate YouCam's scores are. The LLM cases use a scripted stand-in provider with good and bad outputs (no network), so they test the fallback and the claim validator, not any real model.

| Category | Cases |
| --- | --- |
| Avoided ingredient is blocked, with the label line | 6 / 6 pass |
| Synonyms are still blocked | 6 / 6 pass |
| Incomplete INCI is unknown, never pass | 5 / 5 pass |
| No exclusions recorded: nothing to check, never a pass | 7 / 7 pass |
| Product-level reaction blocks that product only | 4 / 4 pass |
| Add switched to replace recalculates | 8 / 8 pass |
| Several changes: can't tell | 4 / 4 pass |
| Overlap: no detectable change | 5 / 5 pass |
| Different conditions: not comparable, re-guide | 12 / 12 pass |
| Symptoms outrank improved scores | 6 / 6 pass |
| Unresolved stop symptom persists | 4 / 4 pass |
| Missing baseline: no trend claim | 4 / 4 pass |
| Wording never claims cause | 2 / 2 pass |
| LLM down or draft rejected: templates shown, core flow unaffected | 7 / 7 pass |
| LLM draft overclaims ("caused by" etc.): validator rejects it | 6 / 6 pass |
| LLM intake proposes; the user confirms | 5 / 5 pass |

### Experiments 1 and 2

Not run yet. Numbers will go here from `backend/results/report.md`.

## API

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/health` | Key present, rule versions |
| GET | `/api/catalog` | 25 fictional products with INCI lists |
| PUT/GET | `/api/shelf` | Current routine |
| POST/GET/DELETE | `/api/history` | Reaction / avoid / confirmed-allergy records |
| POST | `/api/history/intake` | Free text → PROPOSED records (optional LLM). Saves nothing; each is confirmed through `POST /api/history` |
| POST | `/api/compare` | Change nothing vs up to 3 options, with exclusion checks and the next question that matters |
| POST | `/api/scan` | Photo → fingerprint → YouCam (or replay) → stored capture; check-ins get an instant comparability check. Optional `client_hour` (0-23) and `client_device` form fields are used when the photo has no EXIF |
| POST | `/api/trials` | Start a one-change trial (blocked products refused) |
| POST | `/api/trials/{id}/checkin` | Log symptoms and any other new products |
| GET | `/api/trials/{id}/explanation` | 1-3 plain sentences about the stored result, checked by the claim validator; the verdict template when the LLM is off, fails or is rejected |
| GET | `/api/trials/{id}/evidence` | Verdict, ranges, comparability (per field: checked / failed with reason and fix), every scan with its own gate result, reactions |
| POST | `/api/trials/{id}/reactions/{rid}/resolve` | Mark a reported reaction resolved (`resolved_on` date, optional `note`). A stop symptom keeps the verdict at Stop until this is done |
| DELETE | `/api/captures` | Delete every saved scan on this server (scores, capture conditions, saved masks) and re-request YouCam task delete for live scans not yet confirmed deleted. The photo itself is never kept |

## Layout

```
backend/
  app/youcam.py        YouCam client: upload, task, poll, retries, normalisation, record/replay
  app/facecrop.py      server-side face crop + scale (one rule for every capture and the experiments)
  app/fingerprint.py   capture conditions from pixels + EXIF (+ head pose from the browser)
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
