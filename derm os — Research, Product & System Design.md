# **derm//os — Research, Product & System Design** 

Oct 27, 2026 · @aarushi 

## **TL;DR** 

Build derm//os as **the skincare app that knows when it can't tell you yet.** Every purchase becomes a small, well-run personal experiment: one change, a calibrated baseline, matched captures, and a verdict that is only as strong as the evidence. Keep the full Interval scope (start, compare, review, visit brief), but make the evidence engine the hero. 

The research changes the plan in one important way: a team in this same hackathon (Shelf Check) already ships a polished "buy less" agent with shelf audits, rescans, and product-by-product verdicts. "Compare routines and track progress" is no longer enough to stand out. What nobody in the field does yet is **measure how much the score moves on its own before believing it moved because of a product.** 

**The one-line pitch:** _Same face, same light, one change, honest verdict._ 

**Three genuine standout points (each one demoable, none of them claimed by the competitors I found):** 

1. **Your personal noise floor.** At baseline, derm//os takes a quick burst of 3 scans and measures how much _your_ scores wobble per concern. A later change only counts if it beats your own measured noise. Shelf Check uses one fixed ±4 band for everyone. 

2. **A comparability gate.** Every capture gets a fingerprint (light level, face size, head pose, time of day, device). If the before and after photos aren't comparable, derm//os says so and re-guides the capture instead of reporting a trend. 

3. **Attribution you can trust.** derm//os plans changes so results are interpretable (one new product at a time, as dermatologists advise), and it refuses to blame a product when several things changed. Shelf Check pauses a product because redness rose after its start date; derm//os would ask whether anything else changed first. 

**ML answer:** do not train a model. Use YouCam Skin Analysis for perception, MediaPipe in the browser for capture checks, plain statistics for the noise floor, deterministic rules for exclusions and comparisons, and an LLM only for intake extraction and plain-language explanations, behind a validator. 

**Proof we will publish:** a repeat-scan experiment on a real face (how much scores move with no change, and how much a lighting change alone moves them), plus a scripted evidence benchmark with pass rates. Round-one winners all led with a concrete number like this. 

## **What the research says** 

The evidence points one way: skin scores are useful, but small changes between two casual selfies are easy to over-read, and LLMs are unreliable when they freelance on skincare facts. 

### **YouCam Skin Analysis: what we can actually use** 

|Fact|Detail|Source|
|---|---|---|
|Endpoints|Upload file(<br>POST /s2s/v2.0/file/skin-analysis+<br>presigned PUT), create task (<br>POST<br>/s2s/v2.x/task/skin-analysis), poll<br>GET …/{task_id};<br>bearer API key|skinmirror<br>, conventions|
|Version|v2.1 (June 2026) has updated engines and up to 2560<br>px skincare output|changelog|
|Concerns|14 SD actions (acne, wrinkle, pore, texture, redness,<br>oiliness, moisture, radiance, age_spot,<br>dark_circle_v2, eye_bag, firmness, droopy eyelids);<br>HD = same names with<br>hd_prefix, plus skin type and<br>tear trough|zenn-youcam<br>, Playground|
|Hard rule|SD and HD can't be mixed in one request|Playground|
|Output|Per concern:<br>ui_score,<br>raw_score,<br>mask_urls; HD<br>adds per-region scores; JSON or ZIP|skinmirror<br>, Shelf Check|
|Photo rules|JPEG/PNG ≤10 MB; SD short side ≥480 px; HD short<br>side ≥1080 px|Playground|
|Cost|Reported: 16 HD actions = 22 units per task;<br>GET<br>/s2s/v2.0/credit/feature-costreturns exact costs|Shelf Check<br>, changelog|
|Gotchas|Result URLs reportedly expire after ~2 hours<br>(download masks); finished tasks can be deleted with<br>inputs via<br>POST /s2s/v2.0/task/delete|Shelf Check<br>, changelog|



Implication: HD needs a 1080p photo, and many laptop webcams are 720p. Capture on a phone, or fall back to SD. 

### **How reliable are skin scores?** 

- **Vendor-reported repeatability is high.** Perfect Corp reports test-retest reliability of ICC > 0.90 and high correlation with a clinical imaging system, from a study by Dr. Steven Feldman <u>(Business Wire, 2022). Haut.AI reports ICC 0.97–0.98 across clinical camera, smartphone, and</u> selfie, but with standardized capture (Haut.AI). 

- **Independent numbers are lower and inconsistent.** One review notes there is no universal accuracy benchmark, and cites a study finding 67.7% agreement between a tablet system and the VISIA clinical device (theacare). 

- **Lighting matters.** Dr. Zoe Draelos found people looked about three years younger under incandescent light than LED in phone apps (Dermatology Times). Philips tells users of its own skin-selfie analyzer to match light, distance, and angle because results vary otherwise (Philips). 

One small study found no significant score difference across three lighting setups (preprint), so the effect is real but variable. 

Conclusion: a population ICC of 0.9 does not tell an individual whether a 5-point drop is real. That gap is our product. 

### **LLMs on skincare facts** 

- A 2026 benchmark of 14 LLMs on cosmetic chemistry found poor overall performance, and warned that confident wrong answers draw less skepticism than hedged ones (arXiv <u>2608.14631).</u> 

- Lovi reports that even the best LLM it tried could not reproduce its suitability methodology, so it splits evaluation into narrow sub-questions (Dmitrii Avdeenko). 

Implication: rules decide; the LLM explains and extracts. 

### **The closest research architecture: SkinAgent AI (Sept 2026)** 

<u>SkinAgent AI is a non-diagnostic skincare agent with a Plan → Execute → Verify loop, typed tools,</u> database-grounded products, deterministic safety checks, approval before state changes, an image quality gate (PASS/WARNING/FAIL), and replayable traces. 

Its own numbers are the lesson. On a 240-case benchmark: intent accuracy 80.00%, exact tool-set match 62.92%, strict task completion 47.08%, and 8 forbidden-tool calls. Ingredient fidelity in recommendations was only 53.85%, and the heavily guarded configuration produced one generic answer in 39 of 60 cases. 

What we take: the quality gate, typed tools, grounding, approval gates, traces. What we avoid: an openended agent choosing tools for core decisions. derm//os runs a fixed pipeline for decisions and uses the LLM at two narrow points. 

### **Personal experiments: N-of-1 trials** 

N-of-1 trials are self-experiments that test what works for one person rather than the average person. StudyMe showed non-experts could set up their own trials and rated the app highly (Trials, 2022). Two standard designs exist: withdrawal (on/off phases) and alternating treatments. 

Dermatology practice already asks for this discipline. The AAD advises testing a new product on a small spot twice daily for 7–10 days (AAD via HealthDay). Dermatologists also advise adding one new product every one to two weeks, because several at once makes a reaction untraceable (K24). 

## **Competitive landscape** 

The direct threat is inside this hackathon. Shelf Check covers routine audits, purchase advice, and rescans with real engineering depth, so derm//os has to win on evidence quality, not feature count. 

### **What round one rewarded** 

Round one drew 238 submissions. All four named winners solved a specific person's problem and were honest about the AI's limits (Perfect Corp, Oct 13 2026): 

|Project|Place|What stood out|
|---|---|---|
|Aloud|1st|Voice skincare for blind and low-vision shoppers;**checks lighting**<br>**before answering**; 10 of 10 scans under 30 s|
|ShadeSpan|2nd|Garments on six skin tones; only 14.3% passed on all six|
|KeepMe|Winner|Flags and repairs try-on changes the user didn't approve|
|ConfidFit|Winner|Labels each try-on as a preview, not a fit guarantee; live on Shopify|



Pattern to copy: one clear audience, one hard number, and visible honesty about what the image can and can't show. 

### **Entries in this round (public repos found)** 

|Project|What it does|Copy this|Where it stops|
|---|---|---|---|
|Shelf Check|Claude tool-loop agent:<br>keep / pause /<br>alternate / buy verdicts,<br>rescans, Skin Simulation,<br>Makeup VTO|Typed YouCam client<br>with retries;<br>deterministic rules as<br>tools; plan validator<br>that rejects bad plans;<br>recorded replays so the<br>demo never breaks; unit<br>+ e2e tests|One fixed ±4 noise<br>band for everyone;<br>attributes a change to<br>a product from start<br>date alone; no<br>capture comparability<br>check; browser-only<br>history|
|GlowPath|Skin report, routine,<br>cart, weekly "is it<br>working?"|Simple weekly check-in<br>loop|Score deltas only|
|SkinMirror|Selfie → AM/PM routine<br>→ makeup VTO|Server-side key handling|No follow-up<br>evidence|
|Skinova<br>(round one)|Five YouCam APIs, RAG<br>coach, progress with<br>simulation|Breadth of API use, live<br>deployment|Trend deltas, no<br>comparability check|



### **Products outside the hackathon** 

|Product|Relevant strength|Gap we fill|
|---|---|---|
|SkinSort|Routine creator, ingredient checker,|No skin measurement tied|
||product comparison, disliked-ingredient|to a change|



|Product|Relevant strength|Gap we fill|
|---|---|---|
||lists||
|Lovi|Product suitability via narrow LLM sub-<br>questions|Suitability before purchase,<br>not evidence after|
|Haut.AI|Standardized remote capture for brand<br>clinical studies|Built for brands running<br>studies, not for one<br>consumer's decision|
|Droplet, Skintrig, Vessa|Reaction memory, shopping alerts, scan-<br>based routines (from our earlier<br>research; not re-checked today)|Same gap: memory without<br>an evidence standard|



**Positioning:** Haut.AI brings clinical-study discipline to brands. derm//os brings a pocket version of that discipline to one person deciding whether a ₹1,200 serum is worth it. 

## **Conclusions: seven design principles** 

Each principle comes from a finding above; together they define what derm//os does that the field does not. 

1. **Measure noise before measuring change.** Population reliability doesn't tell one person whether a 5-point move is real. A 3-scan baseline burst gives each concern its own noise band. 

2. **Gate comparisons, not just captures.** Aloud and SkinAgent check one photo's quality. derm//os also checks whether two photos are comparable to each other (light, face size, pose, time of day, device). 

3. **Design the change so the result is readable.** One new product per trial, a fixed check-in schedule, and the rest of the routine held steady. This is the N-of-1 withdrawal design in plain words. 

4. **Verdicts have evidence levels.** "Improved beyond your noise", "No detectable change yet", "Can't tell (conditions differed / several changes)", "Stopped: you reported a reaction". Never a bare percentage. 

5. **Symptoms outrank scores.** A better-looking scan never cancels reported itching or burning. 6. **Rules decide, the LLM talks.** Exclusions, comparisons, and verdicts are deterministic and tested. The LLM turns free text into structured fields (user confirms) and turns structured results into plain language (a validator checks every claim). 

7. **History keeps its meaning.** "Reacted to product X", "avoid ingredient Y by choice", and "clinician-confirmed allergy to Z" are different records with different effects. Missing ingredient data is never a pass. 

## **Product design** 

derm//os is organised around one object, the **Trial** : a single skincare change with its reason, its baseline, its schedule, and its verdict. Everything else (shelf, history, captures, visit brief) feeds or reads trials. 

**Name and voice.** Wordmark derm//os, spoken "DermOS", tagline _Your skin, with context._ Because "derm" sounds clinical, every screen says decision support, never diagnosis. 

### **Three entrances, one engine** 

|Entrance|User says|First useful result|
|---|---|---|
|Start|"Where do I begin?"|A minimal 3-step routine (cleanse, moisturise,<br>sunscreen) checked against their exclusions, plus a<br>calibrated baseline|
|Compare|"Should I buy this?"|Current routine vs Option A vs Option B vs "change<br>nothing", with what each adds, replaces, costs, and<br>leaves unknown|
|Review|"Is it working? / My skin reacted."|An evidence view with a verdict level, or a stop card<br>and a visit brief|



### **The core objects** 

|Object|Holds|Rule that makes it different|
|---|---|---|
|Shelf item|Product, role (cleanser, treatment…), leave-<br>on or wash-off, INCI list, source,<br>completeness flag|Incomplete INCI is shown as<br>"unknown", never "safe"|
|History record|Type: suspected reaction · avoid by choice ·<br>clinician-confirmed; product or ingredient;<br>dates; note|A suspected reaction to a product<br>never becomes an ingredient<br>allergy on its own|
|Capture|Image ref, YouCam scores + masks, action<br>set, SD/HD, engine version,**fingerprint**<br>(light, face size, pose, white balance, device,<br>time)|Two captures are compared only if<br>fingerprints match within tolerance|
|Baseline|3-scan burst → per-concern**range**|Defines the user's own noise band|
|Trial|Goal concern, the one change, items held<br>fixed, checkpoints, stop signs, verdict, rule<br>version|Only one new leave-on product per<br>trial; a second change opens a new<br>trial or marks the first "confounded"|
|Visit brief|Timeline, products with INCI, reactions,<br>evidence charts, photos|User edits before export; nothing<br>claims clinical review|



### **Screens** 

1. **Home** — three cards: Start, Compare, Review. Shows any active trial and its next checkpoint. 

2. **Shelf** — current routine as steps; add from catalog or by typing; optional label photo (stretch). 

3. **History** — the three record types, each a different colour chip; free-text entry with LLM extraction and a confirm step. 

4. **Capture** — live camera with a checklist that turns green: face size, straight on, even light, no glasses. Baseline mode takes the 3-scan burst automatically. 

5. **Compare** — four columns (Change nothing, Current, A, B). Rows: steps, added / replaced / kept, new spend, overlapping roles, exclusion check (pass / blocked + reason / unknown), information gaps. One highlighted question when its answer would change the table ("Is the new moisturiser replacing yours or added?"). 

6. **Trial card** — "Testing: Serum B for redness. Holding fixed: everything else. Check-ins: day 14, day 28. Stop if: burning, swelling, itching that persists." 

7. **Check-in → Evidence view** — 10-second symptom log, then capture. Per concern: baseline range bar vs follow-up range bar (overlap = no detectable change), mask overlays side by side, comparability badge, and the product timeline under the chart. 

8. **Visit brief** — one printable page. 

### **Verdict levels (the heart of the product)** 

|Verdict|Fires when|
|---|---|
|Stop — reaction reported|Any stop-sign symptom logged; overrides everything<br>below|
|Can't tell — captures not comparable|Fingerprints differ beyond tolerance; app re-guides<br>the capture|
|Can't tell — several changes|More than one new leave-on product since baseline|
|No detectable change yet|Follow-up range overlaps the baseline range|
|Moved beyond your noise|Ranges don't overlap and captures are comparable;<br>direction shown, with symptoms beside it|



Even the strongest verdict says "changed during this trial", not "caused by the product". Seasons, sleep, and cycles still move skin. 

### **The hero flow (what the demo shows)** 

1. Riya, 21, has a 4-step routine and a sale tab open with two options. She once reacted to a fragranced moisturiser. 

2. She logs that history; derm//os files it as a _suspected product reaction_ and asks whether she also wants to avoid fragrance by choice. She says yes. 

3. Baseline: a 3-scan burst. Her redness range shows as a small band. 

4. Compare: Option A is blocked (fragrance in the INCI, exact match shown). Option B's ingredient list is incomplete, so it shows "unknown", not "pass". She switches "add" to "replace" and the table recalculates. 

5. She starts a trial with a third option that passes, holding the rest fixed. 

6. **The striking moment:** she rescans under a warm lamp. derm//os shows her redness score moved with no product change, marks the pair "not comparable", and guides her back to window light. 

7. Day-14 check-in (clearly labelled as prepared data): ranges overlap → "No detectable change yet. Keep going to day 28." She logs mild itching → the verdict flips to the stop card and the visit brief. 

The demo must use fictional brand names: the rules ban third-party trademarks in the video. 

## **System architecture** 

A fixed pipeline makes every consequential decision; the LLM sits at the edges. This copies the best of SkinAgent (quality gate, typed tools, grounding, traces) and Shelf Check (typed YouCam client, plan validator, replay cache), and drops the part that failed in SkinAgent's benchmark: an open-ended agent picking tools. 



<!-- Start of picture text -->
Rules decide, YouCam measures, the LLM only explains<br>Phone browser (PWA) FastAPI server Services and data<br>Capture guide YouCam gateway YouCam API<br>MediaPipe face size, pose upload > task > poll worker Skin Analysis v2.1<br>light and white balance unit guard -mask download: replay async tasks<br>> capture fingerprint<br>Evidence engine (the hero) Postgres + storage<br>Screens noise floor - comparability gate trials, captures<br>Shelf- History « Compare verdict levels photos, masks<br>Trial -Evidence - Brief<br>Decision engine Catalog + rules<br>exclusions- routine builder 25 products, INCI<br>comparison - next best question versioned rules<br>Language layer LLM API<br>intake extraction > user confirms extraction, wording<br>explanations > claim validator never decides<br>Verdicts and exclusions never pass through the LLM. It only extracts facts the user confirms.<br>and words results that the claim validator checks against the structured record.<br><!-- End of picture text -->

derm//os system architecture · 3 tiers 

The evidence engine is the part no competitor has; everything else is solid, conventional engineering. 

### **Stack** 

- **Frontend:** React + TypeScript + Vite as a mobile-first PWA, so judges and users capture on a phone at 1080p+. MediaPipe Face Landmarker (web) runs in the browser for face size, centring, and head pose. 

- **Backend:** FastAPI + SQLModel, Postgres (Neon or Supabase), object storage for photos and masks. A background worker polls YouCam tasks. 

- **LLM:** one provider behind an adapter, with JSON-schema outputs. Claude or Qwen3-4B-Instruct both work; the adapter means the core app runs if the LLM is down. 

### **YouCam pipeline** 

1. Client checks the live frame (face width, pose, light) and only enables the shutter when all pass. 

2. Server registers the file, uploads bytes to the presigned URL, creates a v2.1 task with **only the goal's concerns** (fewer actions, fewer units), and stores <mark>task_id</mark> . 

3. Worker polls with backoff; on success it downloads masks immediately (URLs expire), normalises scores, and saves engine version + action set with the capture. 

4. A unit guard reads the credit balance and refuses live scans below a reserve, so the demo personas always work. Recorded responses replay when no key is set. 

5. Failed tasks (no face, bad image) map to friendly re-capture prompts. 

### **Evidence engine** 

- **Fingerprint** per capture: face width as % of frame, yaw/pitch/roll, mean luminance and a red/blue ratio on a cheek patch, resolution, device string, local hour. 

- **Comparability:** a pair is comparable when every fingerprint field is within tolerance. Tolerances start as constants and get tuned from our own repeat-scan experiment (section 7). 

- **Noise floor:** baseline = 3 scans in about 2 minutes, user re-framing between shots. Each concern stores min–max. Each check-in takes 2 scans. 

- **Verdict:** the table in Product design, applied top-down; the first matching rule wins. Every verdict stores its inputs and rule version. 

### **Decision engine** 

- **INCI normaliser:** lowercase, strip percentages and brackets, map synonyms (e.g. "parfum" and "fragrance") through a small curated dictionary. 

- **Exclusions:** exact match on normalised INCI against "avoid" and "confirmed" records → blocked with the matching line shown. Product-level reactions block that product only. Incomplete INCI → unknown. 

- **Routine builder:** applies an option to the current routine as add or replace per role, then lists retained / replaced / added, new spend, and duplicate roles. "Change nothing" is always a column. 

- **Next best question:** among unanswered questions, ask the one whose possible answers would change the comparison table; skip the rest. 

### **Language layer** 

- **Intake:** free text → proposed records with every uncertain field set to "needs confirmation"; nothing saves until the user confirms. 

- **Explanations:** the LLM receives only the structured result and writes plain sentences. A claim validator rejects drafts that name a cause, a diagnosis, a product not in the record, or a verdict stronger than the stored one; on rejection the app shows a template sentence instead. 

### **Data model (Postgres)** 

<mark>user</mark> · <mark>product</mark> (catalog, INCI, source, completeness, verified_at) · <mark>shelf_item</mark> · <mark>history_record</mark> (type, target, dates, note) · <mark>capture</mark> (scores JSON, masks, fingerprint, engine, actions) · <mark>baseline</mark> (capture ids, ranges) · <mark>trial</mark> (goal, change, fixed items, checkpoints, status, verdict, rule_version) · <mark>checkin</mark> (symptoms, captures) · <mark>trace</mark> (every engine decision, for replay). 

### **Catalog** 

25 products across five roles, fictional names, ingredient lists modelled on real formulations and checked against Open Beauty Facts (open data, ODbL licence). Each row records its source and whether the list is complete. 

### **Privacy** 

Keys server-side only. Photos stored with consent; a delete button removes them locally and calls YouCam's task delete. Logs never contain images or tokens. 

## **Evaluation: the numbers we will publish** 

Two small experiments on real scans give derm//os its "14.3%" moment, and a scripted benchmark proves the engine behaves. Report whatever the numbers turn out to be; don't predict them. 

### **Experiment 1: how much do scores move on their own?** 

- 5 scans of the same face, same window light, same phone, re-framing between shots, within 5 minutes. 

- Report per concern: min, max, range. This becomes the default noise band and tunes the fingerprint tolerances. 

- Headline format: "With no change at all, redness moved across a range of N points in 5 scans." 

### **Experiment 2: what does lighting alone do?** 

- 3 scans by a window, 3 under a warm lamp, same session. 

- Report the shift per concern beside the Experiment 1 range. If the shift exceeds the range, that's the live proof for the comparability gate. If it doesn't, say so: it means the gate is a safeguard, not a headline. 

Cost: about 11 scans. At the reported 22 units per 16-action HD task that's under 250 units, and less with fewer actions; confirm with the feature-cost endpoint first. 

### **Evidence benchmark (scripted, runs in CI)** 

About 40 fixture cases with expected outputs, reported as pass counts. Like SkinAgent, it is nonindependent and we say so. 

|Case|Expected behaviour|
|---|---|
|Avoided ingredient appears in an option|Blocked, with the matching INCI line|
|Synonym ("parfum" vs "fragrance")|Still blocked|
|INCI list incomplete|"Unknown", never "pass"|
|Product-level reaction recorded|That product blocked; no ingredient allergy created|
|Add switched to replace|Routine, spend, and explanation all update|
|Two leave-on products started together|"Can't tell — several changes"|
|Follow-up range overlaps baseline|"No detectable change yet"|
|Different light or face size|"Not comparable" and re-guide|
|Scores improve, itching reported|Stop card wins|
|Missing baseline|No trend claim|
|LLM down or draft rejected|Templates shown; core flow unaffected|
|LLM draft says "caused by"|Validator rejects it|



### **Usability check (if time allows)** 

5 people, one task: "Decide between these two options, then tell me why." Measure whether they can state the reason and the next action. Report counts, not percentages. 

## **Build plan, demo, and risks** 

Submit by the afternoon of 2 Nov; the deadline is 22:15 IST and the last evening is buffer, not build time. 

### **Day by day** 

1. **Wed 28 Oct — YouCam first.** Redeem units, call the feature-cost endpoint, build the typed client (upload, task, poll, retries, mask download). Run Experiments 1 and 2 on your own face and record every response as fixtures. 

2. **Thu 29 — Data + capture.** Postgres schema, catalog of 25 fictional products, capture screen with MediaPipe checks and the fingerprint, baseline burst. 

3. **Fri 30 — Decision engine.** INCI normaliser, exclusions, routine builder, compare screen, nextbest question. Benchmark cases for this half. 

4. **Sat 31 — Evidence engine.** Comparability gate, noise ranges, verdict table, trial card, evidence view with range bars and masks. Benchmark cases for this half. 

5. **Sun 1 Nov — Language + brief + deploy.** LLM intake and explanations behind the validator, visit brief, deploy (Vercel + Render or Railway), README with setup and results. 

6. **Mon 2 Nov — Video + submit.** Record the 3-minute demo on a phone, screenshots, Devpost text, submit by afternoon. 

### **Cut lines** 

|Must ship|Ship if time|Cut|
|---|---|---|
|Live YouCam scan + baseline burst|LLM intake extraction|Label OCR|
|Comparability gate + verdicts|Visit brief PDF export|Skin Simulation<br>preview|
|Exclusions + compare with "change nothing"|Usability sessions|Reminders and<br>notifications|
|Trial card + evidence view|Makeup VTO tie-in|Web review<br>aggregation|
|Benchmark + both experiments in README|||



### **3-minute demo script** 

|Time|Shows|
|---|---|
|0:00–0:20|Problem: "Did that serum work, or was it the lighting?" Show the Experiment 2<br>result|
|0:20–0:50|History logged; reaction vs avoid kept separate; baseline burst on a phone (live<br>YouCam)|
|0:50–1:30|Compare: option blocked with the exact INCI line, unknown shown honestly, add<br>→ replace recalculates|
|1:30–2:05|Trial starts; warm-lamp rescan → "not comparable", re-guided|
|2:05–2:40|Day-14 check-in (labelled prepared data): "No detectable change yet"; itching<br>logged → stop card → visit brief|
|2:40–3:00|Architecture slide naming the YouCam APIs and endpoints; the benchmark pass<br>count|



### **Risks** 

|Risk|Mitigation|
|---|---|
|Units run out|Request only goal concerns; record fixtures on day 1; unit|
||guard with reserve;share the demo video for bonus units|



|Risk|Mitigation|
|---|---|
||(500 per qualifying share, up to two)|
|Laptop webcam below 1080p|Phone-first PWA; SD fallback|
|Noise ranges look large|That is a finding, not a failure: report it and widen the bands|
|Scope creep|Cut lines above; the evidence engine is never cut|
|Overclaiming in copy|Validator, plus a final read of every on-screen sentence|



**Prizes worth targeting:** as a student team you qualify for the Rising Star Award; the Women in Tech Award also applies if a team member self-identifies as a woman. Both are $1,000 alongside the main placings. 

## **Sources** 

- <u>Perfect Corp: Round two launch and round one winners (Oct 13, 2026)</u> 

- <u>YouCam AI Skin Analysis Playground</u> 

- <u>Perfect Corp API changelog (community mirror)</u> 

- <u>Perfect Corp API conventons (community mirror)i</u> 

- <u>zenn-youcam: SD/HD action list</u> 

- <u>Shelf Check repository</u> 

- <u>GlowPath repository</u> 

- <u>SkinMirror repository</u> 

- <u>Skinova write-up</u> 

- <u>SkinAgent AI (arXiv 2609.29341)</u> 

- <u>LLMs in cosmetic chemistry benchmark (arXiv 2608.14631)</u> 

- <u>Perfect Corp AI skin reliability study (Business Wire, 2022)</u> 

- <u>Haut.AI clinical studies sofwaret</u> 

- <u>How accurate is AI skin analysis? (theacare)</u> 

- <u>Dermatology Times: Do facial appearance apps work?</u> 

- <u>Philips: inconsistent skin-selfie results</u> 

- <u>Efect of lightf</u> ing variability on a facial skin analysis device (preprint) 

- <u>StudyMe: user-centric N-of-1 trials (Trials, 2022)</u> 

- <u>AAD advice on testng new skin care products (HealthDay)i</u> 

- <u>Introduce one product at a time (K24)</u> 

- <u>SkinSort</u> 

- <u>Lovi on LLM suitability limits (LinkedIn)</u> 

- <u>Open Beauty Facts data fields</u> 

