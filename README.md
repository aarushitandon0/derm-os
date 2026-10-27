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

All evidence decisions use `raw_score`. YouCam's docs describe `ui_score` as adjusted upward as a "psychological motivator", so it is shown to users but never used to judge change.

## Setup

```bash
cd backend
pip install -r requirements.txt
cp .env.example .env          # add YOUCAM_API_KEY
python -m pytest -q           # 37 tests, no API units spent
uvicorn app.main:app --reload # http://localhost:8000/docs
```

## Demo safety

- `DEMO_MODE=1` in `backend/.env`: `/api/scan` replays recorded YouCam responses from `backend/fixtures/<persona>/<set>/` (set = `baseline`, `checkin`, or an explicit `fixture_set` such as `lamp`). The uploaded photo is still fingerprinted from its real pixels, so the comparability gate still reacts to real light. Replayed captures are tagged `source: "replay"`; hand-made placeholders are also tagged `synthetic: true`.
- `python scripts/make_fixtures.py` copies your real `results/*.json` (and saved masks) into `fixtures/riya/` (window 1-3 = baseline, window 4-5 = checkin, lamp = lamp), replacing the synthetic placeholders.
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

## API

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/health` | Key present, rule versions |
| GET | `/api/catalog` | 25 fictional products with INCI lists |
| PUT/GET | `/api/shelf` | Current routine |
| POST/GET/DELETE | `/api/history` | Reaction / avoid / confirmed-allergy records |
| POST | `/api/compare` | Change nothing vs up to 3 options, with exclusion checks and the next question that matters |
| POST | `/api/scan` | Photo → fingerprint → YouCam → stored capture; check-ins get an instant comparability check |
| POST | `/api/trials` | Start a one-change trial (blocked products refused) |
| POST | `/api/trials/{id}/checkin` | Log symptoms and any other new products |
| GET | `/api/trials/{id}/evidence` | Verdict, ranges, comparability reasons and fixes |

## Layout

```
backend/
  app/youcam.py        YouCam client: upload, task, poll, retries, normalisation, record/replay
  app/fingerprint.py   capture conditions from pixels + EXIF (+ face metrics from the browser)
  app/evidence.py      noise ranges, comparability gate, verdict table
  app/inci.py          ingredient-name normalisation and synonym groups
  app/decision.py      exclusions, routine builder, comparison, next question
  app/catalog.json     25 fictional products
  app/main.py          FastAPI
  scripts/run_experiments.py
  tests/               benchmark, YouCam client (mocked), API flow
```

## License

MIT
