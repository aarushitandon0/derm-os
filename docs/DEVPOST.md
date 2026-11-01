# Devpost submission

Fill in the two `[placeholder]` links after the deploy and the upload. Keep it to what the build does today.

---

## derm//os

**Shop by your face, not by the hype.**

### The problem

On sale day, people buy what's trending, not what suits their face, and opened skincare usually can't be sent back.

- **37%** of women in a Skin Rocks survey said they buy skincare because of buzzwords they don't understand. ([source](https://britbrief.co.uk/tech/apps/37-of-women-buy-skincare-buzzwords-without-understanding.html))
- **65%** of women in an Ipsos survey for Boots reported frustration finding the right foundation shade. ([source](https://www.ipsos.com/sites/default/files/news_and_polls/2016-06/Cosmetics%20Factum%20Analysis%207274.pdf))
- Opened skincare is often not returnable; see, for example, Nykaa's return policy. ([source](https://www.nykaaman.com/cancellation-policy/lp))

So a wrong buy is money lost, and often a few itchy days as well. A chatbot can suggest a serum, but it can't measure your face, and it doesn't know that the last two products with Alcohol Denat. made you itch.

### What it does

derm//os turns one selfie into a skincare basket from the store's own stock:

1. **Face map.** YouCam Skin Analysis measures skin type per zone. "T-zone: oily, cheeks: normal" leads to two moisturisers, not one. Top needs are shown in words, never as scores.
2. **Your history.** Tap the ingredients you remember ("Vitamin C itched", "Azelaic acid broke me out"). Saved product history counts too.
3. **The basket.** One card per job (cleanser, T-zone moisturiser, cheek moisturiser, sunscreen / skin tint). Each card gives three labelled reasons (From your face · From your history · Matches your finish) and says how to use the product. Every skipped product shows its exact reason, for example: "Contains Alcohol Denat., in 2 of 2 products that made you itch, sting or burn, 0 of 2 that suited you." Products you already own are marked "skip buying".
4. **Start plan.** Patch-test first, then one new product every 2 weeks, gentlest first, with calendar reminders.
5. **Try-on.** YouCam Makeup Try-On shows the base product on your own photo, matte and dewy, in your shade.
6. **Paste any label.** An ingredient list from any shop is checked against your history the same way. Nothing pasted is saved.

Also included: a **breakout helper** (what changed 2–8 weeks ago, purging or not, pause one product) and a **check-in** (one new photo compared with your first scan, in plain words). A beginner path skips the history step, and its picks and alternatives lean gentle (no fragrance, no Alcohol Denat., few actives).

Decision support, not a diagnosis.

### How we built it

**Three YouCam APIs, each with one job:**

| API | Job | Units |
| --- | --- | --- |
| AI Skin Analysis v2.1 SD (`skin_type` + oiliness, moisture, pore, acne, redness, radiance, texture) | Zone types and needs | 12 |
| AI Facial Color Tones Analyzer (Skin Tone) | Skin colour, from which our rule works out the undertone and shade family | 20 |
| AI Makeup Virtual Try-On (foundation) | Matte and dewy renders on your photo | 1 each |

**Deterministic engines** (versioned, with stored inputs and tests) take over from there:

- `needs`: zone types and concern scores → plain needs → ingredient targets and textures, from a curated data file with sources.
- `undertone`: skin colour → CIELAB hue angle → warm / neutral / cool / olive, by a documented house rule, labelled as derived.
- `basket`: picks one product per job from the store's stock by needs, finish, zone type and shade. Every pick and every skip carries its reasons.
- `chips`: history by ingredient, with synonyms and families.
- `startplan`: patch test, order, and 14-day spacing.
- `lookfor`: what to look for on any label, with no brand names.
- `pastecheck`: any pasted ingredient list goes through the same check.
- `cartcheck`: the history check ladder (blocked, repeats a pattern, patch-test first, no conflicts, and unknown for an incomplete list).
- `patterns`: which ingredients the products that bothered you share, and how often they also appear in products that suited you.

**Stack:** FastAPI + SQLite on Python 3.12 in Docker (Render), React + TypeScript PWA (Vercel), and MediaPipe for the live face guide, the server crop and a free head-pose precheck.

**Guard rails:** 1,100 backend tests with no network and no units; a 235-case rule benchmark (235 / 235, written by us, so not an independent evaluation); a claim linter in CI that fails the build on words like "cures", "treats", "proven" or "safe"; and docs/FACTS.md linking each claim to its code and test. Live runs need a passcode, read the real balance first, and stop at a balance floor, judge caps and a reserve.

### Challenges we ran into

Both came from our first live run on a real face:

- **`skin_type` came back in a different shape.** We had coded for one `skin_type` item holding `whole` / `t_zone` / `u_zone`. The live SD response sends **one output item per region** (`{"type": "skin_type", "region": "t_zone", "skin_type": "Oily"}`). The parser now reads that shape, still accepts the documented one, and has tests for both.
- **Skin Tone rejected a normal selfie for its face angle.** YouCam's default angle check is strict, and a slightly turned phone selfie failed. We fixed it in four steps:
  - send the most lenient `face_angle_strictness_level` (configurable with `YOUCAM_FACE_ANGLE_STRICTNESS`), stepping stricter only on an invalid-parameter error, and never past medium;
  - run Skin Tone **before** Skin Analysis, so a refused photo costs as little as possible;
  - add a **free head-pose precheck** on the server, so a side profile is caught before any unit is spent;
  - if Skin Tone still refuses, the basket is built anyway, with the undertone from one quiz question, labelled "from your answers". The shopping flow always gives an answer.

### What's next

- **A retailer catalogue plug-in:** any shop's stock with full ingredient lists feeds the basket, as an embeddable "Build my basket" button.
- Postgres and object storage, so history survives restarts.

### Try it

- App: [Vercel URL] → **Build my basket from my face** → **Use Riya's demo face** (demo data, no account, no units)
- Code: https://github.com/aarushitandon0/derm-os
- Video: [YouTube URL]

All products and brands in the app are fictional.
