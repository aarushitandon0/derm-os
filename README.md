# derm//os

[![CI](https://github.com/aarushitandon0/derm-os/actions/workflows/ci.yml/badge.svg)](https://github.com/aarushitandon0/derm-os/actions/workflows/ci.yml)

**Same face, same light, one change, honest verdict.** A skincare app on the YouCam AI Skin Analysis API that tells you whether your skin changed more than it does on its own before you rebuy a product, and says "can't tell" when the photos can't support an answer.

## Judge quick access

| What | Where |
| --- | --- |
| Live app (phone first) | _link added after deploy_ · tap **Try the 90-second demo** |
| 3-minute video | _link added after upload_ |
| Every README claim, with its code and test | [docs/FACTS.md](docs/FACTS.md) |
| Claim linter (fails the build on overclaiming wording) | [backend/scripts/claim_lint.py](backend/scripts/claim_lint.py), run in [CI](.github/workflows/ci.yml) |
| Evidence benchmark | [backend/results/benchmark.md](backend/results/benchmark.md) · `python -m benchmark` |
| Screenshots (390 px) | [docs/screenshots/](docs/screenshots/) |

Run it locally with no keys (prepared data; `DEMO_MODE` defaults to `1`):

```powershell
cd backend; python -m pip install -r requirements.txt; python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
cd frontend; npm install; npm run dev -- --host 127.0.0.1 --port 5180
start http://127.0.0.1:5180
```

## The number

_Placeholder: filled in from `backend/results/report.md` after the repeat-scan shoot._

With nothing changed (N photos of the same face, same window light), a fixed ±5-point rule called a change in X% of comparisons; derm//os's pre-registered verdict said "moved beyond your noise" in Y% of baseline/check-in splits. Under a warm lamp, the comparability gate marked Z% of photo pairs not comparable.

How it's measured (`backend/scripts/analyze_experiment.py`): every split of the no-change photos into a 3-scan baseline and a 2-scan check-in is judged by the app's own verdict function with its constants unchanged. That first result is frozen in `results/preregistered.json`; any later tuning is reported beside it, labelled "after tuning on these same photos". The splits share photos, so they aren't independent.

## What it does

- **Your own noise range.** A baseline is 3 scans, so each concern gets a range, not one number. A check-in is 2 scans. A change counts only when the two ranges don't overlap.
- **Comparability gate.** Every photo carries a fingerprint: brightness, light colour, face size, head angle, camera and time of day. When a check-in doesn't match the baseline, the answer is "can't tell", with how to retake.
- **Take photos or upload them.** "Upload photos instead" opens the gallery: 3 photos for the first set, 2 for a check-in (JPEG, PNG or HEIC, up to 15 MB). A free check on the server (no YouCam call) runs first: one face, the same crop, the light reading and the comparability gate, with one plain fix if anything fails. Uploaded and camera photos go through the same crop, fingerprint and gate; an "Uploaded photo" badge is for display only.
- **Honest first photos.** Uploaded first photos are refused if two are the same picture, or if their capture times are more than 15 minutes apart. If a photo has no capture time, the app asks whether they were taken in one sitting and notes the answer.
- **Same crop for every photo.** Each photo is cropped around the face (on the server, by a local detector) and scaled so the face is the same width every time. No colour, brightness or rotation edits.
- **One change per trial.** More than one new leave-on product means "can't tell which".
- **Symptoms outrank scores.** A reported reaction such as itching gives a Stop card and a visit brief, whatever the scores say.
- **A rebuy line on every verdict,** mapped strictly from the verdict: "The evidence supports rebuying, if you like using it." only for a comparable move beyond noise in the better direction.
- **History that keeps its meaning.** "This product bothered me", "I avoid fragrance" and "clinician-confirmed allergy" are different records. A reaction to a product never becomes an ingredient allergy. An incomplete label is "unknown", never a pass.
- **Compare before you buy.** "Change nothing" is always a column. Exclusions show the exact label line; add vs replace recalculates steps, spend and duplicates.

The strongest wording is "changed during this trial". derm//os is decision support, not diagnosis.

## Evidence benchmark

**115 of 115 cases pass** (`cd backend; python -m benchmark`). We wrote this benchmark ourselves, so it is **not an independent evaluation**: it shows the rules behave as designed, not how accurate YouCam's scores are.

| Category | Cases |
| --- | --- |
| Avoided ingredient is blocked, with the label line | 6 / 6 |
| Synonyms are still blocked | 6 / 6 |
| Incomplete INCI is unknown, never pass | 5 / 5 |
| No exclusions recorded: nothing to check, never a pass | 7 / 7 |
| Product-level reaction blocks that product only | 4 / 4 |
| Add switched to replace recalculates | 8 / 8 |
| Several changes: can't tell | 4 / 4 |
| Overlap: no detectable change | 5 / 5 |
| Different conditions: not comparable, re-guide | 12 / 12 |
| Symptoms outrank improved scores | 6 / 6 |
| Unresolved stop symptom persists | 4 / 4 |
| Missing baseline: no trend claim | 4 / 4 |
| Wording stays at "during this trial" | 2 / 2 |
| Positive persona: a comparable move beyond noise, judged by the real engine | 8 / 8 |
| Rebuy line follows the verdict | 8 / 8 |
| Uploaded photos: same checks as the camera, honest baselines, no GPS | 8 / 8 |
| Optional language layer (scripted stand-in, off in the deployed app) | 18 / 18 |

Also in CI: 405 backend tests (no network, no units), the claim linter, TypeScript typecheck and the production build.

## YouCam API used

Skin Analysis v2.1, SD, 4 concerns by default (redness, acne, texture, pore: 9 units per scan).

| Endpoint | What derm//os uses it for |
| --- | --- |
| `POST /s2s/v2.0/file` | Register the cropped photo; returns a file id and a presigned upload URL |
| `PUT <presigned URL>` | Upload the photo bytes (no bearer header) |
| `POST /s2s/v2.1/task/skin-analysis` | Create the analysis task for the chosen concerns |
| `GET /s2s/v2.1/task/skin-analysis/{task_id}` | Poll until success or error; read `raw_score` per concern |
| `GET <mask URL>` | Download the marked-area masks right away (the URLs expire) |
| `POST /s2s/v2.0/task/delete` | Delete the task, the uploaded photo and its outputs at YouCam once masks are saved |
| `GET /s2s/v1.0/client/credit` | Read the unit balance before every live scan (free) |
| `GET /s2s/v2.0/credit/feature-cost` | Read the exact price of a scan (free) |

Every evidence decision uses `raw_score`. YouCam describes `ui_score` as adjusted upward for display, so it is never used to judge change.

**Units are guarded.** The public demo replays prepared scores (`DEMO_MODE=1`). A live scan needs the server set to live and a passcode on the device. Before every live scan the server reads the real YouCam balance (a free call) and works out the scan's exact price; if the balance minus that price would drop below `LIVE_SCAN_MIN_BALANCE`, or the balance can't be read, nothing is sent. Because it reads the real balance, this cap survives server restarts. The judge caps counted in the database (300 units total, 100 a day) and a 200-unit reserve are second limits. Whenever the floor or a cap stops a scan, it replays prepared data and the app says so.

## What derm//os will not tell you

- **What caused a change.** Seasons, sleep, cycles and stress move skin too. The strongest result is "changed during this trial".
- **A diagnosis.** It doesn't name skin conditions. The visit brief is for a clinician to read.
- **That a product is safe.** "No conflict found" only means none of *your* recorded exclusions are on the label. An incomplete label is "unknown".
- **A trend from mismatched photos.** Different light, framing or time of day gives "can't tell", not a number.
- **How accurate YouCam's scores are.** The benchmark tests derm//os's rules, not the measurement.

## Privacy

- The uploaded photo is cropped and measured on the server, sent to YouCam only for a live scan, and deleted from the server straight after.
- Photo metadata is stripped. The crop sent to YouCam and every saved mask are re-encoded from pixels alone (no EXIF, GPS or other tags). From a photo's EXIF the app keeps only the capture hour and a camera label such as "Acme Phone 7", or "not recorded". GPS is never read, stored or logged.
- After a live scan's masks are saved, the server asks YouCam to delete the task, which removes the photo and outputs there.
- Stored scans keep scores, capture conditions and local mask images, never mask URLs. **Delete my saved scans** (Learn page) removes them and asks YouCam again for any task not confirmed deleted.
- Committed fixtures hold scores and capture-condition numbers only. A pre-commit hook blocks photo files; `photos/`, `backend/media/` and raw results are git-ignored.
- Keys live in server environment variables only and are never logged.

## How it's built

![Architecture](docs/architecture.svg)

- **Frontend:** React + TypeScript + Vite, a phone-first PWA. MediaPipe Face Landmarker runs in the browser for the live capture guide.
- **Backend:** FastAPI on Python 3.12, SQLite, MediaPipe BlazeFace for the server-side crop. Docker image for Render (`backend/Dockerfile`); see [docs/DEPLOY.md](docs/DEPLOY.md).
- **Rules:** `app/evidence.py` (noise ranges, gate, verdicts, rebuy line), `app/decision.py` and `app/inci.py` (exclusions, compare). The guided demo's scenes (`app/scenes.py`) only write rows; the same engine computes every verdict.
- **Experiments:** `scripts/run_experiments.py` (repeat scans, with a `--only` pilot and a whole-run balance check) and `scripts/analyze_experiment.py` (the false-change analysis).

## Next

- **Language layer** (code in `backend/app/llm/`; off on the deployed app, which sets `LLM_PROVIDER=none`): free-text history intake that the user confirms record by record, and plain-language explanations behind a claim validator that falls back to the fixed wording. It runs only against a local Ollama server (`LLM_PROVIDER=ollama`, no API key), so today it works on a developer's own machine, not for judges. On a laptop CPU one call took about 50 seconds.
- **Postgres and object storage** in place of SQLite, so trials survive restarts.
- Real repeat-scan fixtures for the demo personas in place of the prepared ones.

## License

MIT
