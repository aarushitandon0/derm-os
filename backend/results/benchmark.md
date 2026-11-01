# derm//os evidence benchmark

**235 of 235 cases pass.**

Written and run by the derm//os team, so this is **not an independent evaluation**. Each case has an expected output written from the design doc before the engine was run. It shows the decision and evidence rules behave as designed; it says nothing about how accurate YouCam's skin scores are. No YouCam calls, no units spent. The LLM cases use a scripted stand-in provider (no network): they test the fallback and the claim validator, not any real model.

Run: `cd backend; python -m benchmark` (also runs under `python -m pytest`).

| Category | Passed |
| --- | --- |
| Avoided ingredient is blocked, with the label line | 6 / 6 |
| Synonyms are still blocked | 6 / 6 |
| Incomplete INCI is unknown, never pass | 5 / 5 |
| No exclusions recorded: nothing to check, never a pass | 7 / 7 |
| Product-level reaction blocks that product only | 4 / 4 |
| Add switched to replace recalculates | 8 / 8 |
| Several changes: can't tell | 4 / 4 |
| Overlap: no detectable change | 5 / 5 |
| Different conditions: not comparable, re-guide | 14 / 14 |
| Symptoms outrank improved scores | 6 / 6 |
| Unresolved stop symptom persists | 4 / 4 |
| Missing baseline: no trend claim | 4 / 4 |
| Wording stays at "during this trial" | 2 / 2 |
| Positive persona: a comparable move beyond noise, judged by the real engine | 8 / 8 |
| Rebuy line follows the verdict | 8 / 8 |
| Uploaded photos: same checks as the camera, honest baselines, no GPS | 8 / 8 |
| LLM down or draft rejected: templates shown, core flow unaffected | 7 / 7 |
| LLM draft overclaims ("caused by" etc.): validator rejects it | 6 / 6 |
| LLM intake proposes; the user confirms | 5 / 5 |
| Irritation and breakout never share a suspect list | 5 / 5 |
| Contrast decides: suited products clear, one failed product can't narrow | 10 / 10 |
| Synonyms and families match, exact first | 7 / 7 |
| Cart check: the verdict ladder, in order | 10 / 10 |
| Cart check: three labelled sources, change nothing, one next step | 14 / 14 |
| Breakout triage: the window, purging, usual spots, one next step | 18 / 18 |
| The verdict is written back, and never upgrades a can't-tell | 12 / 12 |
| The demo personas produce the expected outcomes, from the real engines | 17 / 17 |
| Basket: zone split, finish, history skips, unknown labels, owned, shade, wording | 15 / 15 |
| History by ingredient, start plan, what to look for, paste check | 10 / 10 |

## All cases

### Avoided ingredient is blocked, with the label line

| Case | Checks | Result |
| --- | --- | --- |
| ex-01 | Avoid fragrance; Velvet Rose lists Parfum | pass |
| ex-02 | The block shows the exact label line | pass |
| ex-03 | Avoid fragrance also catches declared components (Linalool, Citronellol, Geraniol) | pass |
| ex-04 | Confirmed salicylic acid allergy blocks the BHA gel, label line and record type shown | pass |
| ex-05 | Same allergy: a moisturiser without it passes | pass |
| ex-06 | API refuses to start a trial with a blocked product | pass |

### Synonyms are still blocked

| Case | Checks | Result |
| --- | --- | --- |
| syn-01 | Avoid 'Parfum'; toner lists 'Fragrance' | pass |
| syn-02 | Avoid 'FRAGRANCE' (case) still matches 'Parfum' | pass |
| syn-03 | Avoid fragrance catches tea tree oil by its INCI name | pass |
| syn-04 | Avoid fragrance: SPF lists orange peel oil, Fragrance and Limonene; all three shown | pass |
| syn-05 | Avoid 'nicotinamide'; serum lists 'Niacinamide 10%' (percentage stripped) | pass |
| syn-06 | Avoid 'alcohol' does not catch the fatty alcohol 'Cetearyl Alcohol' | pass |

### Incomplete INCI is unknown, never pass

| Case | Checks | Result |
| --- | --- | --- |
| inc-01 | Incomplete list, avoid fragrance: unknown | pass |
| inc-02 | The reason says it is not a pass | pass |
| inc-03 | Incomplete list with a confirmed allergy: unknown | pass |
| inc-04 | Incomplete list that does list the avoided ingredient: blocked | pass |
| inc-05 | Compare column lists it under unknowns and doesn't call it blocked | pass |

### No exclusions recorded: nothing to check, never a pass

| Case | Checks | Result |
| --- | --- | --- |
| nt-01 | No records at all: a complete product is 'nothing to check' | pass |
| nt-02 | Every catalog product with no records: none says 'pass' | pass |
| nt-03 | The reason says it is not a pass | pass |
| nt-04 | Incomplete list, no exclusions: nothing to check AND tagged incomplete | pass |
| nt-05 | Incomplete list, avoid fragrance: unknown AND tagged incomplete | pass |
| nt-06 | Incomplete list that lists the avoided ingredient: blocked AND tagged incomplete | pass |
| nt-07 | A complete list is never tagged incomplete | pass |

### Product-level reaction blocks that product only

| Case | Checks | Result |
| --- | --- | --- |
| pr-01 | Reaction to Velvet Rose blocks Velvet Rose | pass |
| pr-02 | Rose toner sharing Linalool is not blocked (no ingredient allergy invented); with no ingredient exclusions it is 'nothing to check' | pass |
| pr-03 | A reaction record must name a product | pass |
| pr-04 | API stores one product-level record, no ingredient | pass |

### Add switched to replace recalculates

| Case | Checks | Result |
| --- | --- | --- |
| ar-01 | Add: old moisturiser kept, duplicate role flagged | pass |
| ar-02 | Replace: routine swaps the moisturiser, no duplicate | pass |
| ar-03 | New spend counts only the new product (Rs 650) either way | pass |
| ar-04 | Unanswered: asks 'replace or add', naming both products | pass |
| ar-05 | Answered 'replace': the question goes away | pass |
| ar-06 | Add: 5 steps after, stop using nothing | pass |
| ar-07 | Replace: 4 steps after, stop using the Daily Barrier Cream | pass |
| ar-08 | 'Replace' with nothing in that role adds a step and stops nothing | pass |

### Several changes: can't tell

| Case | Checks | Result |
| --- | --- | --- |
| sc-01 | Two new leave-on products and scores moved | pass |
| sc-02 | Two new leave-on products and scores flat (still can't tell, not 'no change') | pass |
| sc-03 | Compare counts a two-product option as 2 new leave-on | pass |
| sc-04 | API: check-in logs another new product | pass |

### Overlap: no detectable change

| Case | Checks | Result |
| --- | --- | --- |
| ov-01 | Baseline 60-64, check-in 62-65 | pass |
| ov-02 | Ranges touch at one point (60-64 vs 64-66) | pass |
| ov-03 | Check-in inside a wide baseline | pass |
| ov-04 | Overlap gives no direction | pass |
| ov-05 | Control: no overlap moves beyond noise | pass |

### Different conditions: not comparable, re-guide

| Case | Checks | Result |
| --- | --- | --- |
| nc-01 | Much dimmer light | pass |
| nc-02 | Warm lamp: says the light is warmer | pass |
| nc-03 | Face fills less of the frame | pass |
| nc-04 | Head turned 20 degrees | pass |
| nc-05 | Another camera | pass |
| nc-06 | Ten hours later | pass |
| nc-07 | SD baseline vs HD check-in | pass |
| nc-08 | Every mismatch carries a re-guide fix | pass |
| nc-11 | Same label source (both live camera), different camera: fails | pass |
| nc-12 | Photo-file label vs live-camera label: device 'not compared', pair still comparable | pass |
| nc-09 | Not comparable outranks big score gains | pass |
| nc-10 | Small light change within tolerance stays comparable | pass |
| nc-13 | Camera metered 4 stops of difference: not comparable, even though the photos look equally bright | pass |
| nc-14 | No exposure recorded on either side: not a failure, and not counted as a matching field either | pass |

### Symptoms outrank improved scores

| Case | Checks | Result |
| --- | --- | --- |
| sy-01 | Scores improve, itching reported | pass |
| sy-02 | Burning outranks 'not comparable' | pass |
| sy-03 | Swelling outranks 'several changes' | pass |
| sy-04 | Swelling with no baseline yet still stops | pass |
| sy-05 | ' Itching ' with stray case and spaces still stops | pass |
| sy-06 | A non-stop symptom (dryness) is shown beside the result | pass |

### Unresolved stop symptom persists

| Case | Checks | Result |
| --- | --- | --- |
| sp-01 | Itching, then a clean check-in: still Stop | pass |
| sp-02 | The reaction stays open until resolved | pass |
| sp-03 | Marked resolved: Stop lifts, scores speak again | pass |
| sp-04 | Itching logged again after resolving: Stop again | pass |

### Missing baseline: no trend claim

| Case | Checks | Result |
| --- | --- | --- |
| mb-01 | No baseline scans | pass |
| mb-02 | One baseline scan only | pass |
| mb-03 | One check-in scan only | pass |
| mb-04 | No trend wording when the baseline is missing | pass |

### Wording stays at "during this trial"

| Case | Checks | Result |
| --- | --- | --- |
| wd-01 | No verdict text says 'caused' or 'because of' | pass |
| wd-02 | Strongest result says 'during this trial' and that it can't show the product was the reason | pass |

### Positive persona: a comparable move beyond noise, judged by the real engine

| Case | Checks | Result |
| --- | --- | --- |
| pos-01 | Meera: comparable check-ins leave her redness range | pass |
| pos-02 | The pair passed the gate on light, face size, head pose, time and device | pass |
| pos-03 | Wording: 'dropped beyond your usual variation during this trial', plus the caveat | pass |
| pos-04 | Same scores, check-ins under a warm lamp: not comparable (no special-casing) | pass |
| pos-05 | Itching logged at her check-in: Stop outranks the better scores | pass |
| pos-06 | Another new leave-on product logged: can't tell which | pass |
| pos-07 | Every scan in the scene is labelled prepared data | pass |
| pos-08 | The scene builder never names a verdict, the gate or the engine | pass |

### Rebuy line follows the verdict

| Case | Checks | Result |
| --- | --- | --- |
| rb-01 | Moved beyond noise, better | pass |
| rb-02 | No detectable change | pass |
| rb-03 | Not comparable | pass |
| rb-04 | Several changes, even with better scores | pass |
| rb-05 | No baseline | pass |
| rb-06 | Itching with better scores: don't rebuy | pass |
| rb-07 | Moved beyond noise, worse: never 'supports rebuying' | pass |
| rb-08 | API: Meera supports; Riya lamp / day 14 / itching = can't tell / finish / don't rebuy | pass |

### Uploaded photos: same checks as the camera, honest baselines, no GPS

| Case | Checks | Result |
| --- | --- | --- |
| up-01 | Baseline with two pixel-identical photos (their metadata differs) | pass |
| up-02 | Baseline photo times spread over 30 minutes | pass |
| up-03 | A baseline photo has no capture time: ask, don't assume | pass |
| up-04 | ...and the user says yes: stored as user-confirmed | pass |
| up-05 | Same pixels by camera and by upload, warm lamp vs window baseline: same gate result | pass |
| up-06 | Same pixels by camera and by upload, same window light: same gate result | pass |
| up-07 | Uploaded photos carry GPS: none of it is stored | pass |
| up-08 | Upload over 15 MB is refused before decoding | pass |

### LLM down or draft rejected: templates shown, core flow unaffected

| Case | Checks | Result |
| --- | --- | --- |
| llm-01 | LLM off: explanation is the template | pass |
| llm-02 | Provider times out twice (one retry): template | pass |
| llm-03 | Rejected draft: template shown | pass |
| llm-04 | A clean draft passes and is used | pass |
| llm-05 | API, LLM off: evidence and explanation work, template text | pass |
| llm-06 | API, provider failing: same template, core flow unaffected | pass |
| llm-07 | Intake output that isn't JSON is rejected: no proposals | pass |

### LLM draft overclaims ("caused by" etc.): validator rejects it

| Case | Checks | Result |
| --- | --- | --- |
| llm-08 | Draft says 'caused by' | pass |
| llm-09 | Draft says 'thanks to' | pass |
| llm-10 | Draft names a diagnosis | pass |
| llm-11 | Draft names a product not in the record | pass |
| llm-12 | Draft claims improvement when the verdict is 'no detectable change' | pass |
| llm-13 | Draft gives a number not in the record | pass |

### LLM intake proposes; the user confirms

| Case | Checks | Result |
| --- | --- | --- |
| llm-14 | Example text: product reaction + clinician-confirmed lanolin allergy | pass |
| llm-15 | Unmatched product stays as typed text and needs confirmation | pass |
| llm-16 | LLM attaches an ingredient to a product reaction: dropped, stays product-level | pass |
| llm-17 | Allergy with no clinician in the text: proposed as 'avoid', type needs confirmation | pass |
| llm-18 | API intake proposes but saves nothing | pass |

### Irritation and breakout never share a suspect list

| Case | Checks | Result |
| --- | --- | --- |
| sep-01 | Her irritation suspect (a drying alcohol) is not in the breakout run | pass |
| sep-02 | The irritation run's failure set is only the products that itched | pass |
| sep-03 | The breakout run's failure set is only the product that broke her out | pass |
| sep-04 | Azelaic acid is a breakout candidate and never an irritation one | pass |
| sep-05 | A cleanser that stings is NOT down-weighted (only breakouts are) | pass |

### Contrast decides: suited products clear, one failed product can't narrow

| Case | Checks | Result |
| --- | --- | --- |
| con-01 | In 2 of 2 products that itched and 0 that suited: a suspect | pass |
| con-02 | The counts read 'in 2 of 2 ... 0 of 2 that suited you' | pass |
| con-03 | An ingredient that is also in a suited product is cleared, never a suspect | pass |
| con-04 | In 1 failed product of 2 and 0 suited: a lead, not a suspect | pass |
| con-05 | A 2-week 'suited' product clears nothing: the shared alcohol is still a suspect | pass |
| con-06 | The same product at 4 weeks does clear it | pass |
| con-07 | A 2-week 'suited' outcome reads as too early to say | pass |
| con-08 | One failed product: says plainly it can't narrow down which ingredient | pass |
| con-09 | One failed product names no suspects and no leads at all | pass |
| con-10 | One failed product lists only what is in nothing that suited her | pass |

### Synonyms and families match, exact first

| Case | Checks | Result |
| --- | --- | --- |
| mat-01 | 'Parfum (Fragrance)' and 'Fragrance' count as one ingredient: a suspect | pass |
| mat-02 | ...and the synonym match names both products | pass |
| mat-03 | The fragrance FAMILY is matched across differently-named components | pass |
| mat-04 | An exact match ranks above a family match of the same tier | pass |
| mat-05 | A cross-reactor with no exact history is a family match, so patch-test | pass |
| mat-06 | A fatty alcohol is not in the drying-alcohol family | pass |
| mat-07 | Every ingredient family and the purge list are versioned data | pass |

### Cart check: the verdict ladder, in order

| Case | Checks | Result |
| --- | --- | --- |
| cl-01b | The ladder is Blocked, Repeats a pattern, Patch-test first, No conflicts | pass |
| cl-02b | Blocked wins: she avoids fragrance and it lists Parfum | pass |
| cl-03b | Repeats a pattern: it lists her exact irritation suspect | pass |
| cl-04b | Patch-test first: it lists a lead | pass |
| cl-05b | No conflicts with your history: nothing of hers matched | pass |
| cl-06b | The bottom rung is never worded as 'safe' | pass |
| cl-07b | Incomplete INCI can never read as no conflicts: it reads unknown | pass |
| cl-08b | A stronger rung still stands on an incomplete label, and carries the tag | pass |
| cl-09b | A complete label is never tagged incomplete | pass |
| cl-10b | A family-level suspect is one rung softer than an exact one | pass |

### Cart check: three labelled sources, change nothing, one next step

| Case | Checks | Result |
| --- | --- | --- |
| cs-01 | Exactly three sources, labelled from history, skin and shelf | pass |
| cs-02 | With no scan, the skin source says to scan first | pass |
| cs-03 | Through the API with no scan, the same line is shown | pass |
| cs-04 | No scan does not change the verdict rung | pass |
| cs-05 | Aimed at names a measured top concern, and says which | pass |
| cs-06 | Her lowest measured score is named as the lowest | pass |
| cs-07 | Not aimed at a top concern is said plainly | pass |
| cs-08 | The skin source says 'aimed at' and never that it fixes anything | pass |
| cs-09 | The shelf source names the duplicate and the new spend | pass |
| cs-10 | Change nothing is always one of the options | pass |
| cs-11 | Exactly one next step on every cart check and every triage | pass |
| cs-12 | Each rung has its own next step | pass |
| cs-13 | Every result stores its inputs and its rule versions | pass |
| cs-14 | General knowledge is kept under its own key, out of the counts line | pass |

### Breakout triage: the window, purging, usual spots, one next step

| Case | Checks | Result |
| --- | --- | --- |
| tg-01 | The product started inside the 2-8 week window is the top lead | pass |
| tg-02 | A leave-on in the window ranks above a wash-off in the window | pass |
| tg-03 | A product used 12 weeks without trouble ranks lowest, with the reason | pass |
| tg-04 | ...and it is never excluded from the list | pass |
| tg-05 | The long-use reason says it is not a clean bill | pass |
| tg-06 | Something started a week ago ranks below the window | pass |
| tg-07 | No purge without a turnover ingredient, and it says why | pass |
| tg-08 | A turnover ingredient plus her usual spots plus settling: purge-consistent | pass |
| tg-09 | The same turnover ingredient, but spots in a NEW area: not a purge | pass |
| tg-10 | A new area is said to point away from purging | pass |
| tg-11 | Usual spots are said to be where purging shows up | pass |
| tg-12 | Settling later than ~6 weeks is not purge-consistent | pass |
| tg-13 | Symptoms outrank the whole ranking: stop wins | pass |
| tg-14 | The stop next step opens the visit brief, not a trial | pass |
| tg-15 | A mild symptom is not a stop | pass |
| tg-16 | One next step: pause one leave-on product and hold the rest | pass |
| tg-17 | Zone shares come from masks when there are numbers, and say so | pass |
| tg-18 | With no mask numbers it uses the tapped zones and says which it used | pass |

### The verdict is written back, and never upgrades a can't-tell

| Case | Checks | Result |
| --- | --- | --- |
| lp-01 | A comparable move in the good direction after 4 weeks writes 'suited' | pass |
| lp-02 | The same move under 4 weeks stays 'not sure' | pass |
| lp-03 | A move in the wrong direction is not 'suited' | pass |
| lp-04 | No detectable change never writes 'suited' | pass |
| lp-05 | Not comparable never writes 'suited' | pass |
| lp-06 | Several changes never writes 'suited' | pass |
| lp-07 | No baseline never writes 'suited' | pass |
| lp-08 | A stop on an itch writes an irritation outcome | pass |
| lp-09 | A stop on spots writes a breakout outcome | pass |
| lp-10 | A can't-tell verdict can't soften a reaction she already recorded | pass |
| lp-11 | Through the real app: a can't-tell verdict writes 'not sure', never 'suited' | pass |
| lp-12 | Meera's positive trial writes 'suited' into her history | pass |

### The demo personas produce the expected outcomes, from the real engines

| Case | Checks | Result |
| --- | --- | --- |
| ps-01 | Riya's scene: her irritation suspect is the shared drying alcohol | pass |
| ps-02 | Riya's scene: the suspect's counts line | pass |
| ps-03 | Riya's scene: the azelaic breakout offers a purge reclassification | pass |
| ps-04 | Riya's scene: the purge offer changes nothing by itself | pass |
| ps-05 | Store product A repeats a pattern | pass |
| ps-06 | Store product B's label is incomplete, so it reads unknown | pass |
| ps-07 | Store product C has no conflicts and is aimed at her measured pores | pass |
| ps-08 | Riya's breakout: the new sunscreen is the top lead, and it is not a purge | pass |
| ps-09 | Riya's breakout: the snail mucin ranks low with its reason shown | pass |
| ps-10 | Meera's positive verdict is on PORES, not redness | pass |
| ps-11 | Meera's wording stays at 'during this trial', with the caveat | pass |
| ps-12 | Meera's raw move is 6.0 points, which the 'typical app' line is built from | pass |
| ps-13 | Itching at Meera's check-in: stop outranks her better scores | pass |
| ps-14 | The beginner scene starts from nothing at all | pass |
| ps-15 | The beginner's skin type is labelled 'from your answers' | pass |
| ps-16 | The beginner's starter is 3 steps, each run through the cart check | pass |
| ps-17 | A scene writes rows only: no verdict word appears in what it stored | pass |

### Basket: zone split, finish, history skips, unknown labels, owned, shade, wording

| Case | Checks | Result |
| --- | --- | --- |
| bk-01 | Oily T-zone, dry cheeks: two moisturisers, one per zone | pass |
| bk-02 | The two moisturisers are different products, gel on the T-zone, cream on the cheeks | pass |
| bk-03 | Both zones the same type: one moisturiser for the whole face | pass |
| bk-04 | Matte instead of dewy changes the T-zone pick to a matte finish | pass |
| bk-05 | Dewy: the base pick has a dewy finish, and a matte tint is skipped as the wrong finish | pass |
| bk-06 | The history suspect is skipped with its exact reason | pass |
| bk-07 | An incomplete ingredient list is never picked; it is skipped as unknown | pass |
| bk-08 | An owned cleanser is not bought again | pass |
| bk-09 | A store product already on the shelf moves to 'You already own' | pass |
| bk-10 | Warm-neutral skin colour: a warm shade at her depth | pass |
| bk-11 | Cool skin colour: a cool shade | pass |
| bk-12 | No score, number or 'can't tell' in any user sentence, for every finish | pass |
| bk-13 | Every basket has exactly one next step | pass |
| bk-14 | No face measurement: the zones come from the answers, labelled, and every job answers | pass |
| bk-15 | Riya's basket: owned cleanser, gel T-zone, cream cheeks, dewy tint in her shade | pass |

### History by ingredient, start plan, what to look for, paste check

| Case | Checks | Result |
| --- | --- | --- |
| ha-01 | Itched chip skips exact and same-group products | pass |
| ha-02 | Broke-out chip skips only a key active | pass |
| ha-03 | 'Suited me' never excludes anything | pass |
| ha-04 | Purge: offered only after a yes, never applied without the user's choice | pass |
| ha-05 | Product-level history ranks above a chip on the same product | pass |
| ha-06 | Start plan: gentle, then sunscreen, then actives, 14 days apart, owned kept | pass |
| ha-07 | What to look for: no exfoliant in the base, Avoid lists her own reasons | pass |
| ha-08 | Paste check: suspect repeats a pattern, clean has no conflicts, cut-off is unknown | pass |
| ha-09 | One need per zone: normal cheeks with low moisture read hydration once | pass |
| ha-10 | Beginner: gentle label on every card, no history step | pass |

