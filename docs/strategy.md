# derm//os — Strategy v2 (Nov 1, 2026): "Shop by your face, not by the hype"

Replaces v1. Deadline **Nov 2, 22:15 IST**; submit by **15:00 IST Nov 2**. Track: **Skin AI**. Units: **992**.

> **UNIT RULE: NO PAID YOUCAM CALL UNLESS THE SESSION PROMPT APPROVES AN EXACT NUMBER. FREE CALLS ONLY (BALANCE, FEATURE COST). TESTS, BUILDS AND DEMOS RUN WITH THE YOUCAM KEY EMPTY.**

## 1. Why we changed direction

v1 made "is my product working?" (repeat photos, noise floors, "can't tell yet") the headline. That's wrong for users, for three reasons:
- People can see their own redness; scores and points mean nothing to a shopper.
- Nobody retakes photos in matching light.
- "Can't tell" doesn't help anyone.

The real pain is **"what should I buy for MY face?"**, especially on sale day, when people buy what's trending and opened skincare can't be returned.

## 2. The product

**derm//os turns one selfie into a skincare basket made for your face:**
- measured **zone by zone**;
- matched to the **finish you want** (glowy/dewy · natural · matte);
- in **your undertone**;
- **minus everything that has burned you before**;
- and you **see the finish on your own face before you pay**.

**USP line:** "Shop by your face, not by the hype."

**Three pillars a chatbot can't do:**
1. **Your face, zone by zone.** YouCam Skin Analysis measures skin type per zone (T-zone vs cheeks) and concerns with overlays. It's a clinically validated measurement, not a guess from a photo. "Oily T-zone, dry cheeks → two moisturisers, not one."
2. **Never the same mistake twice.** Your saved history plus the store's exact INCI lists, with synonyms and families (built: patterns, cartcheck, families). "Skipped: contains Alcohol Denat., in 2 of 2 products that made you itch."
3. **See it before you buy.** YouCam Makeup Try-On (foundation: shade, coverage, glow level) applied to your real photo. Matte vs dewy, side by side, in your undertone's shade. Pair it with tinted SPF / skin tint products.

## 3. How it matches the hackathon

| Brief / criterion | How we meet it |
|---|---|
| "right before a purchase" | The hero flow: build my basket / Check against my skin on the store page. |
| "right after a bad breakout" | The built breakout helper: what changed 2–8 weeks ago, purge or not, pause ONE product. |
| "in front of a mirror deciding whether a product is working" | An optional check-in: one new photo vs your first scan, in plain words, no points, no retake demands unless the photo is unusable. |
| "understand their skin" | The face map in plain words: zone types, top needs, undertone. |
| "know exactly what to do next" | The basket, plus how to use each product (which zone, AM/PM), plus ONE next step (patch test, start one at a time). |
| "Skin AI alone or combined with other YouCam APIs" | Skin Analysis (core) + Skin Tone + Makeup VTO, each with a real job. |
| "not surface-level wrappers" / "beyond a simple API call" | Three APIs chained into deterministic engines: needs, basket, exclusions, history. |
| "first-time user instantly grasps its value" | Selfie → face map → basket → try-on slider. No jargon, no numbers. |
| Retail value | A basket from the store's own stock, with fewer regret buys. Embeddable as a "Build my basket" button. |

## 4. The flow (phone)

1. **Home:** big button "Build my basket from my face". Smaller: "My skin just broke out" · "Is my product working?".
2. **Selfie:** one photo, with the existing live guide and precheck.
3. **Three questions:**
   - Which finish do you want? (glowy/dewy · natural · matte)
   - Anything that itched or broke you out before? (reuse History; skippable)
   - Budget (optional).
4. **Your face map:** a stylised face with zones coloured, plus one plain line per zone ("T-zone: oily", "Cheeks: dry"), top 2–3 needs in words ("needs: oil control on T-zone, hydration on cheeks"), and undertone ("warm-neutral"). No scores shown.
5. **Your basket** (from the store's stock), one card per job:
   - Cleanser (whole face);
   - T-zone treatment/moisturiser;
   - Cheek moisturiser (or one product if both zones are the same type);
   - Sunscreen / skin tint in your shade, finished to your goal.
   Each card shows:
   - **Why** in three labelled lines: From your face (YouCam) · From your history · Matches your finish;
   - **How to use:** zone, AM/PM.
   Below the cards:
   - **Skipped** products with the exact reason (history match, wrong finish, wrong zone type, incomplete INCI → unknown);
   - **You already own:** skip buying.
6. **See it on you:** two YouCam try-on renders (matte vs dewy) of the base product in your undertone's shade.
7. **One next step:** "Patch-test the new products, then start one at a time. Tap to set day-14 reminders."

Rule: the shopping flow **always gives an answer**. If a measurement is missing, use the quiz answer and label it "from your answers". Never "can't tell".

## 5. Engines and data (deterministic, versioned, inputs stored, tested)

- **needs.py (needs-1.0):** zone skin types + concern raw scores + finish goal → plain-language needs → ingredient targets. Kept as a curated, versioned data file with sources. Examples:
  - oily zone / pores → niacinamide, salicylic acid, gel texture;
  - dry zone / low moisture → glycerin, hyaluronic acid (sodium hyaluronate), ceramides, cream texture;
  - low radiance → niacinamide, vitamin C derivatives (not L-ascorbic acid if it's a history suspect);
  - acne → salicylic acid / benzoyl peroxide (OTC), plus "see a dermatologist if painful, cystic or persistent";
  - redness → centella, panthenol; avoid fragrance.
  The **finish goal** adjusts textures:
  - dewy → humectant-rich, "glow" finish;
  - matte → oil-control, mattifying;
  - natural → satin.
- **undertone.py (undertone-1.0):** map the Skin Tone response to warm / cool / neutral / olive (rules depend on what the API actually returns; verify) → a shade family for tinted products. If the API gives only a colour, derive undertone with a documented rule and label it.
- **basket.py (basket-1.0):**
  - choose from the store stock per job using needs + finish + zone + shade;
  - exclude via existing cartcheck/patterns (history), never with an incomplete INCI shown as pass;
  - "already own" from the shelf;
  - one product per job; total price;
  - every pick and skip carries its reasons.
- **Store stock** (fictional brands, store.json): ~16–20 products tagged with job, zone suitability, texture, finish, aimed_at, shade + undertone family for tinted items, full or incomplete INCI.
- **Kept from v1, reframed:** patterns, cartcheck, families, triage, writeback, history, store page. Evidence engine = the optional check-in only. The 132-unit experiment is **dropped**.

## 6. YouCam use (verify names, costs and shapes with free calls first)

| Call | Job | Units |
|---|---|---|
| Skin Analysis SD: skin_type + oiliness, moisture, pore, acne, redness, radiance, texture | zone types + needs + overlays | 12 for 5–8 actions (verified live) |
| Skin Tone / shade finder | undertone + shade | verify |
| Makeup VTO, foundation × 2 (matte, dewy) | see the finish | verify |

Unknowns to verify:
- does SD skin_type return t_zone/u_zone?
- does Skin Tone return an undertone or only a colour?
- what are the VTO foundation parameters (shade, coverage, glow)?

## 7. Video (≤2:50, on a phone, no trademarks/music)

| Time | Beat |
|---|---|
| 0:00–0:15 | "Vitamin C made me itch. Azelaic acid broke me out. There's a sale on, everyone's buying the trending serum, and opened skincare can't be returned. So I built derm//os: shop by your face, not by the hype." |
| 0:15–0:45 | Selfie → face map: "Oily T-zone, dry cheeks, warm-neutral undertone." |
| 0:45–1:30 | Basket: the two-moisturiser zone split; the skipped product with its exact reason; "you already own a cleanser". |
| 1:30–2:00 | Try-on: her face, matte vs dewy, in her shade. |
| 2:00–2:25 | Breakout helper (10 s) and check-in (10 s), both already built. |
| 2:25–2:50 | "A chatbot guesses. derm//os measures your face, checks real ingredient lists against your history, and shows you the finish on you." Name the YouCam APIs; link. |

## 8. Timeline

- **Sun day (Session I, 0 units):** free checks + build engines, data, UI with fixtures/placeholders.
- **Sun evening (Session J, approved units):** one live run on her own selfie (analysis + tone + 2 renders), record sanitised fixtures, deploy.
- **Mon morning:** video, screenshots, Devpost text, share for bonus units.
- **Mon by 15:00:** submit.

## 9. Words

- Never: causes, cures, treats, safe, proven, works, diagnose, allergy (unless clinician-confirmed), points or scores shown to users.
- Use: aimed at, suits your [zone], matches your finish, skipped because, from your face, from your history, from your answers.
- Every screen: "Decision support, not a diagnosis."

## Sources

- Hackathon page: https://youcam-api-skin-ai-ecommerce.devpost.com/
- YouCam Skin Analysis API reference: https://docs.perfectcorp.com/api_references/skin_analysis/api-reference
- YouCam Makeup VTO docs: https://docs.perfectcorp.com/reference/makeup_vto
- Makeup VTO API product page (foundation shade, coverage, glow): https://yce.perfectcorp.com/ai-api/products/virtual-makeup-try-on-api
- Skin type by T-zone/U-zone: https://www.perfectcorp.com/business/products/ai-skin-diagnostic
- Skin Rocks survey (buzzword buying, 37%): https://britbrief.co.uk/tech/apps/37-of-women-buy-skincare-buzzwords-without-understanding.html
- Ipsos/Boots (foundation shade frustration, 65%): https://www.ipsos.com/sites/default/files/news_and_polls/2016-06/Cosmetics%20Factum%20Analysis%207274.pdf
- Nykaa return policy: https://www.nykaaman.com/cancellation-policy/lp
- Nykaa × OpenAI: https://www.mediainfoline.com/tag/nykaa