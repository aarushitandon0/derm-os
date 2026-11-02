# derm//os

[![CI](https://github.com/aarushitandon0/derm-os/actions/workflows/ci.yml/badge.svg)](https://github.com/aarushitandon0/derm-os/actions/workflows/ci.yml)

**Shop by your face, not by the hype.**

One selfie becomes a skincare basket from the store's own stock: measured zone by zone with YouCam, matched to the finish you want, in your undertone, minus everything that has bothered you before. Then you see the finish on your own face before you pay.

![derm//os home on a laptop](docs/devpost-gallery/1-home.png)

---

## Contents

- [Judge quick access](#judge-quick-access)
- [The problem](#the-problem)
- [The flow, step by step](#the-flow-step-by-step)
- [Also included](#also-included)
- [How a product gets picked or skipped](#how-a-product-gets-picked-or-skipped)
- [The 3 YouCam APIs](#the-3-youcam-apis)
- [Run it in 5 minutes](#run-it-in-5-minutes)
- [How it's built](#how-its-built)
- [Project layout](#project-layout)
- [Configuration](#configuration)
- [Testing and checks](#testing-and-checks)
- [Counts](#counts-measured-2-nov-2026)
- [Units are guarded](#units-are-guarded)
- [Privacy](#privacy)
- [Notes and limits](#notes-and-limits)
- [Challenges we ran into](#challenges-we-ran-into)
- [Next](#next)

---

## Judge quick access

| What | Where |
| --- | --- |
| Live app (phone, tablet or laptop) | _link added after deploy_ · tap **Use Riya's demo face** on the home screen → **Build my basket** |
| Video (under 3 minutes) | _link added after upload_ · shot list in [docs/VIDEO.md](docs/VIDEO.md) |
| Devpost write-up | [docs/DEVPOST.md](docs/DEVPOST.md) · gallery images (3:2) in [docs/devpost-gallery/](docs/devpost-gallery/) |
| Every claim in this README, with its code and test | [docs/FACTS.md](docs/FACTS.md) |
| Claim linter (fails the build on overclaiming wording) | [backend/scripts/claim_lint.py](backend/scripts/claim_lint.py), run in [CI](.github/workflows/ci.yml) |
| Benchmark of the rules | [backend/results/benchmark.md](backend/results/benchmark.md) · `python -m benchmark` |
| Screenshots (phone + desktop) and a layout check at 10 screen sizes | [docs/screenshots/](docs/screenshots/) · [layout-check.json](docs/screenshots/layout-check.json) |
| Design notes | [docs/DESIGN.md](docs/DESIGN.md) · [docs/strategy.md](docs/strategy.md) |
| Deploy steps (Render, Vercel, Supabase) | [docs/DEPLOY.md](docs/DEPLOY.md) |

The demo needs no account and spends no YouCam units. Every prepared screen shows a "Demo data" tag.

---

## The problem

On sale day, people buy what's trending, not what suits their face. And opened skincare usually can't be returned.

- **37%** of women in a Skin Rocks survey said they buy skincare because of buzzwords they don't understand. ([source](https://britbrief.co.uk/tech/apps/37-of-women-buy-skincare-buzzwords-without-understanding.html))
- **65%** of women in an Ipsos survey for Boots reported frustration finding the right foundation shade. ([source](https://www.ipsos.com/sites/default/files/news_and_polls/2016-06/Cosmetics%20Factum%20Analysis%207274.pdf))
- Opened skincare is often not returnable; see, for example, Nykaa's return policy. ([source](https://www.nykaaman.com/cancellation-policy/lp))

A wrong buy is money lost, and often a few itchy days as well. A chatbot can suggest a serum, but it can't measure your face, and it doesn't know that the last two products with Alcohol Denat. made you itch. derm//os does both, and shows its reasons for every pick.

---

## The flow, step by step

| | Step | What you see |
| --- | --- | --- |
| 1 | **Selfie** | One photo, with a live face guide in the browser and a free precheck on the server (one face, not a side profile, not too dark) before any YouCam unit is spent. |
| 2 | **Face map** | Each zone in plain words ("T-zone: oily", "Cheeks: normal"), your top needs ("oil control on T-zone, hydration on cheeks"), your undertone, and **What your scan found**: one plain line per measured concern ("Pores: somewhat visible", "Moisture: on the low side"). No scores or numbers. |
| 3 | **Three quick questions** | The finish you want (glowy / dewy, natural, matte), your budget, and your history. |
| 4 | **Your history** | Tap the ingredients you remember ("Vitamin C itched", "Azelaic acid broke me out"), plus any product-level history you've saved. Skippable. |
| 5 | **Basket** | One card per job (cleanser, T-zone moisturiser, cheek moisturiser, sunscreen / skin tint). Each card says why in three labelled lines (**From your face** · **From your history** · **Matches your finish**), how to use it (which zone, morning or night), and **what to look for in any shop**. Below the cards: every skipped product with its exact reason, and what you already own. |
| 6 | **Start plan** | Patch-test first, then one new product every 2 weeks, gentlest first, with calendar reminders (.ics). |
| 7 | **Try-on** | YouCam renders your base product on your own photo, matte and dewy side by side, in your shade. |
| + | **Paste any label** | Found something in another shop? Paste its ingredient list and it's checked against your history the same way as the store's stock. Nothing you paste is saved. |

### Example skip lines from the prepared demo

- *Dewdrop Skin Tint SPF 30 · From your history:* "Contains Alcohol Denat., in 2 of 2 products that made you itch, sting or burn, 0 of 2 that suited you."
- *Bright Dew C Gel · From what you've tried:* "Lists Ascorbyl Glucoside 2%, from the same group as vitamin C. Vitamin C itched, stung or burned on you before."
- *Dew Veil Barrier Cream · Ingredient list incomplete → unknown:* "Anything not printed on the label can't be checked against your history, so it isn't picked."
- *Satin Veil Tint SPF 30 · No shade for you:* "No shade for tan warm-neutral skin in this range."
- *Shea Night Balm · Wrong zone type:* "Made for dry skin; your T-zone reads oily."

### Screens

| Face map | Basket | Skipped | Try-on |
| --- | --- | --- | --- |
| ![Face map](docs/screenshots/05-riya-face-map.png) | ![Basket cards](docs/screenshots/06-riya-basket-cards.png) | ![Skipped with reasons](docs/screenshots/07-riya-skipped-with-reasons.png) | ![Try-on](docs/screenshots/10-try-on-matte-vs-dewy.png) |

On a laptop (1440 × 900), the face map stays on the left while the basket fills the right:

![Face map and basket on a 1440 px laptop](docs/screenshots/17-desktop-face-map-basket-1440.png)

| Questions + skipped | Start plan + paste a label |
| --- | --- |
| ![Questions and skipped products](docs/devpost-gallery/3-history-and-skipped.png) | ![Start plan and paste a label](docs/devpost-gallery/4-start-plan-and-paste-label.png) |

### Nothing tried yet?

Pick **Use a beginner demo face** (or answer "nothing tried yet"). The history step is skipped, and every pick and every "Also fits" alternative leans gentle: no fragrance, essential oils or Alcohol Denat., and few actives. Cards are tagged "Gentle start for new routines".

---

## Also included

- **Breakout helper** ("My skin just broke out"): a reaction you can feel (itching, burning, swelling…) is asked first and outranks everything else. Then it ranks what changed 2–8 weeks ago, says whether it could be purging, and names one product to pause. For painful, cystic or persistent breakouts it says to see a dermatologist.
- **Check-in** ("Is my product working?"): one new photo compared with your first scan, in plain words.
- **Store page** with "Check against my skin" on every product.
- **Profile** (optional account):
  - save a basket with its start plan;
  - edit your history (by ingredient or by product, with a "confirmed by a doctor" flag) and what you already own;
  - see past scan results, including What your scan found;
  - **logged-in baskets start from your saved profile**: your finish, budget and beginner answers are pre-filled, and your own history and shelf are used. You can untick any saved item for one basket. Doctor-confirmed items always stay on;
  - "Update my profile too" copies a basket's answers back to the profile, only if you tick it;
  - download your data or delete your account.

  Accounts are hidden when they aren't set up, and the demo never needs one.

![Profile with a saved basket](docs/devpost-gallery/6-profile.png)

---

## How a product gets picked or skipped

Everything after the scan is plain, versioned rules with tests. No language model chooses products.

**1. Face → needs.** YouCam's zone types and concern values become plain needs (for example "oil control on T-zone"). A concern adds a need when its value is in the low band (below 60 of 100). Each need maps to ingredients and textures from a curated data file with sources ([app/needs.json](backend/app/needs.json)).

**2. Skin colour → undertone.** YouCam returns a skin colour, not an undertone. Our rule ([app/undertone.py](backend/app/undertone.py), undertone-1.0) converts it to CIELAB and maps the hue angle to warm / warm-neutral / neutral / cool-neutral / cool / olive, and the lightness to a depth. With no colour, one quiz question is used instead, labelled "from your answers".

**3. History check.** Every product's ingredient list goes through the same check ladder ([app/cartcheck.py](backend/app/cartcheck.py)). The first match wins:

| Result | When |
| --- | --- |
| **Blocked** | It lists something you avoid, or something a doctor confirmed. |
| **Repeats a pattern** | It lists, by exact name, an ingredient shared by the products that bothered you ([app/patterns.py](backend/app/patterns.py)). |
| **Patch-test first** | It lists a weaker lead, or an ingredient from the same family as one you reacted to (vitamin C family, for example). |
| **No conflicts** | Nothing from your history matched. Never called "safe". |
| **Unknown** (tag) | The ingredient list is incomplete. An unknown product is never picked. |

**4. Basket.** For each job, [app/basket.py](backend/app/basket.py) keeps products that fit your zone type, your finish, your shade and your budget, and pass the history check. Products you already own fill their job ("skip buying"). Every pick and every skip carries its reason.

**5. Start plan.** [app/startplan.py](backend/app/startplan.py) orders the new products gentlest first, with a 7-day patch test and 14 days between products.

---

## The 3 YouCam APIs

| API | Its job in derm//os | Units per call |
| --- | --- | --- |
| **AI Skin Analysis** (v2.1, SD): `skin_type` + oiliness, moisture, pore, acne, redness, radiance, texture | Skin type per zone (T-zone vs cheeks), the needs that pick ingredients and textures, and the What your scan found lines | **12** (8 concerns) |
| **AI Facial Color Tones Analyzer** (Skin Tone, `skin-tone-analysis`) | Skin colour → undertone and shade family for tinted products | **20** |
| **AI Makeup Virtual Try-On** (`makeup-vto`, foundation) | Your base product on your photo, matte and dewy | **1** per render (2 per basket) |

One full live basket costs 20 + 12 + 2 × 1 = **34 units**. Prices come from YouCam's free `GET /s2s/v2.0/credit/feature-cost` list, read before every live run; the free `GET /s2s/v1.0/client/credit` balance check runs first. Skin Tone runs first because it's the most likely to refuse a photo, so a refused photo costs as little as possible.

Every endpoint used: `POST /s2s/v2.0/file` (register the photo, presigned upload), `POST /s2s/v2.1/task/skin-analysis` + poll, `POST /s2s/v2.0/task/skin-tone-analysis` + poll, `POST /s2s/v2.0/task/makeup-vto` + poll, `POST /s2s/v2.0/task/delete`, and the two free calls above.

---

## Run it in 5 minutes

No keys needed: `DEMO_MODE` defaults to `1`, so it uses prepared demo faces and never calls YouCam.

**Needs:** Python 3.12 and Node 22.

```powershell
# terminal 1: API
cd backend; python -m pip install -r requirements.txt; python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
# terminal 2: app
cd frontend; npm install; npm run dev -- --host 127.0.0.1 --port 5180
start http://127.0.0.1:5180
```

Tap **Use Riya's demo face** → **Build my basket** (or **Build my basket from my face** → **Use Riya's demo face** → **Build my basket**).

To try the live face guide with a phone camera on your network, use `npm run dev:https` (the camera needs HTTPS).

---

## How it's built

![Architecture](docs/architecture.svg)

| Part | What we used |
| --- | --- |
| **Frontend** | React 18 + TypeScript + Vite, a phone-first PWA that adapts to tablets and desktops with one fluid layout (CSS grid, `clamp()` and container queries). MediaPipe Face Landmarker runs in the browser for the live face guide. Product packs are SVG illustrations drawn in code (shape by product type, colour by fictional brand). Hosted on Vercel. |
| **Backend** | FastAPI on Python 3.12. SQLite locally, or Supabase Postgres (session pooler) when `DATABASE_URL` is set. MediaPipe on the server for the face crop and the free head-pose precheck (run in a child process, so a crash in the native library can't take the server down). Docker image on Render. |
| **Accounts** | Supabase Auth (email + password). The server checks sign-in tokens against the project's public keys. |
| **Rules ("engines")** | Plain Python, versioned, each with tests. See the table below. |
| **CI** | GitHub Actions: pytest, the benchmark, the claim linter, the TypeScript check and the production build on every push. |

### The engines

| Engine | Version tag | What it does |
| --- | --- | --- |
| `needs` | in [needs.json](backend/app/needs.json) | zone types + concerns → needs → ingredient targets and textures |
| `findings` | findings-1.0 | each measured concern → one plain line (high / mid / low band); raw values never leave the file |
| `undertone` | undertone-1.0 | skin colour → CIELAB → undertone and depth |
| `basket` | | one product per job from the store's stock, with reasons for every pick and skip |
| `chips` | | history by ingredient, with synonyms across 6 ingredient families |
| `cartcheck` | | the history check ladder above |
| `patterns` | | which ingredients the products that bothered you share, and how often they also appear in ones that suited you |
| `pastecheck` | | any pasted ingredient list through the same check |
| `lookfor` | | what to look for on any label, with no brand names |
| `startplan` | | patch test, order and 14-day spacing |
| `triage` | | the breakout helper |

An optional language layer (off by default, local Ollama only, no API key) can suggest history entries from free text and rephrase explanations. Its output is checked before it's shown, and the app works fully without it.

---

## Project layout

```text
backend/
  app/            FastAPI app (main.py), engines, data files (needs, findings, chips, families, store)
  benchmark/      rule benchmark cases  → results/benchmark.md
  scripts/        claim_lint.py and helpers
  tests/          pytest (no network, no YouCam units)
  fixtures/       recorded scan values only, never photos
  Dockerfile
frontend/
  src/screens/    Home, Basket, Profile, Store, Checkin, Trial, …
  src/components/ FaceMap and shared UI
  src/capture/    live face guide (MediaPipe)
  scripts/        layout check and walk-through scripts
docs/             DESIGN, FACTS, DEPLOY, DEVPOST, VIDEO, screenshots, devpost-gallery
render.yaml       Render blueprint for the API
```

---

## Configuration

Copy [backend/.env.example](backend/.env.example) to `backend/.env`. Every setting is optional for the demo.

| Variable | What it does |
| --- | --- |
| `DEMO_MODE` | `1` (default): replay prepared faces, never call YouCam. `0`: live scans allowed with the passcode. |
| `YOUCAM_API_KEY` | YouCam key (server only, never logged). |
| `LIVE_SCAN_PASSCODE` | Needed on the device for a live scan. Empty = live scans impossible. |
| `LIVE_SCAN_MIN_BALANCE` | Never send a scan that would leave the balance below this. |
| `YOUCAM_UNIT_RESERVE` | Units always kept back. |
| `JUDGE_UNIT_CAP_TOTAL` / `JUDGE_UNIT_CAP_DAILY` | Total and daily unit caps, counted in the database. |
| `YOUCAM_FACE_ANGLE_STRICTNESS` | Skin Tone's face-angle setting (most lenient by default). |
| `SCAN_RATE_LIMIT`, `TRUST_PROXY` | Scans per client IP; set `TRUST_PROXY=1` behind Render. |
| `CORS_ORIGINS` | The frontend URL(s) allowed to call the API. |
| `DATABASE_URL` | Supabase Postgres. Unset = local SQLite (`backend/dermos.db`). |
| `SUPABASE_URL` and keys | Turn on accounts (see [docs/DEPLOY.md](docs/DEPLOY.md)). |
| `LLM_PROVIDER` | `none` (default) or `ollama` for the optional language layer. |

Frontend (Vercel): `VITE_API_BASE` (the Render API URL), and `VITE_SUPABASE_URL` + `VITE_SUPABASE_ANON_KEY` for accounts.

---

## Testing and checks

From `backend/`:

```powershell
python -m pytest -q            # 1,182 tests, no network, no units
python -m benchmark            # 238 rule cases → results/benchmark.md
python scripts/claim_lint.py   # fails on words like "cures", "proven", "safe"
```

From `frontend/`:

```powershell
npx tsc -b                               # TypeScript check
npx vite build                           # production build
node scripts/layout-check.mjs            # 10 screen sizes, needs the app running
```

The **claim linter** reads every string a user can see (frontend text and backend messages) and fails the build on overclaiming words: cause, cure, treat, diagnose, prove, guarantee, clinically, allergy (outside a doctor-confirmed record), "safe", and claims that a product works on you. Each allowed exception has a written reason. It also keeps real brand and retailer names out of the catalogue, fixtures and UI.

---

## Counts (measured 2 Nov 2026)

| | |
| --- | --- |
| Backend tests (no network, no units) | **1,182 passing** (1 skipped) |
| Rule benchmark | **238 / 238** cases ([results](backend/results/benchmark.md)). We wrote it ourselves, so it isn't an independent evaluation: it shows the rules behave as designed, not how accurate YouCam's measurements are. |
| Claim linter | **0 findings** (16 allowed uses, each with a written reason), 0 real brand names |
| Store stock | **19** fictional products, tagged by job, zone type, texture, finish and shade |
| Ingredient chips (history by ingredient) | **13**, over **6** ingredient families with synonyms |
| What your scan found | **7** concerns × 3 bands, in words |
| Screenshots | **19** at phone width + **5** at 1440 px desktop, plus **6** Devpost gallery images (3:2) |
| Layout check (10 screen sizes, 360 × 740 to 2560 × 1440, incl. 844 × 390 landscape and 1280 × 720) | **0** console errors, **0** sideways scroll, **0** tap targets under 44 px, **0** overflowing elements, main home button visible without scrolling on all 10 ([results](docs/screenshots/layout-check.json)) |

---

## Units are guarded

The public demo spends nothing (`DEMO_MODE=1`). A live run needs the server set to live **and** a passcode on the device.

Before every live run, the server:

1. reads the real balance (free) and the exact price;
2. sends nothing if the balance minus the run would fall below `LIVE_SCAN_MIN_BALANCE`, or if the balance can't be read;
3. checks the judge caps (300 units total, 100 a day, counted in the database) and a 200-unit reserve;
4. runs the free face precheck, so a bad photo never reaches YouCam.

When a limit stops a run, the app replays prepared data and says so.

---

## Privacy

- **Your face photo is never stored**, by anyone. The selfie is cropped and checked on the server, sent to YouCam only for a live run, and deleted from the server straight after. The server then asks YouCam to delete the task, its photo and its outputs. No database table has a column that could hold a photo or an image link (a test checks every column).
- **Accounts are optional.** The demo needs none. With an account (Supabase email + password), derm//os keeps:
  - your name, finish goal, budget and beginner flag;
  - your history (ingredient chips and product notes, with a "confirmed by a doctor" flag);
  - what you own;
  - saved baskets with their start plans;
  - scan **results** only (zone types, concern values, undertone and how it was worked out, engine versions).

  Try-on images, masks and links are removed before anything is saved.
- **Only the server reads the database.** Row Level Security is on for every table with no policies, so the browser's key can't read or write any row. The server reads your user id only from a verified sign-in token, and every query is limited to that id.
- **Export and delete.** The profile page has "Download my data" (one JSON file) and "Delete my account" (every row, then the sign-in account itself).
- History typed on this device before logging in is added to your profile only if you answer yes when asked.
- Photo metadata is stripped: what's sent to YouCam is re-encoded from pixels alone. GPS is never read, stored or logged.
- Pasted ingredient lists are never saved.
- Committed fixtures hold scores only. A pre-commit hook blocks photo files.
- Keys live in server environment variables only and are never logged. The service worker never caches a signed-in request or account data.

---

## Notes and limits

- **The undertone is worked out by our rule**, not measured by YouCam. The thresholds are a documented house rule, and the app says "worked out from your skin colour".
- **Demo data is labelled.** The deployed demo replays prepared faces. Riya's face values come from one recorded live scan (values only: no photo, mask or render kept), while her history and shelf are fictional. The beginner's values are hand-made. Every screen in that mode shows a demo-data tag.
- **The try-on needs a live scan.** In demo mode the try-on card shows a placeholder ("Preview appears on a live scan").
- **No scores are shown.** YouCam's numbers decide the needs; the user sees words.
- **Patch-test, then one product every 2 weeks.** Every basket ends with that step, so if something bothers you there is only one thing it could be.
- **An incomplete ingredient list is "unknown", never a pass,** and is never picked.
- **Decision support, not a diagnosis.** derm//os doesn't name skin conditions. For painful, cystic or persistent breakouts it says to see a dermatologist.
- **All products and brands in the app are fictional.**

---

## Challenges we ran into

- **The live `skin_type` came back in a different shape.** We had coded for one item holding `whole` / `t_zone` / `u_zone`. The live SD response sends one item per region. The parser now reads both shapes, with tests for each.
- **Skin Tone refused normal selfies for face angle.** We now send the most lenient angle setting, run Skin Tone first, add a free head-pose precheck, and fall back to one quiz question if it still refuses, so the user always gets a basket.
- **MediaPipe on the server.** The native library could crash the process on the host. The models are now checked in a child process, and the version is pinned.

---

## Next

- **A retailer catalogue plug-in:** any shop's stock (with full ingredient lists) feeds the basket, as an embeddable "Build my basket" button.
- Check-ins over a longer time, so you can see how your skin changes with each new product.
- More ingredient families and chips in the history step.

## License

MIT
