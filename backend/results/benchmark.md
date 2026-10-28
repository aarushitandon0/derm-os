# derm//os evidence benchmark

**91 of 91 cases pass.**

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
| Different conditions: not comparable, re-guide | 12 / 12 |
| Symptoms outrank improved scores | 6 / 6 |
| Unresolved stop symptom persists | 4 / 4 |
| Missing baseline: no trend claim | 4 / 4 |
| Wording never claims cause | 2 / 2 |
| LLM down or draft rejected: templates shown, core flow unaffected | 7 / 7 |
| LLM draft overclaims ("caused by" etc.): validator rejects it | 6 / 6 |
| LLM intake proposes; the user confirms | 5 / 5 |

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

### Wording never claims cause

| Case | Checks | Result |
| --- | --- | --- |
| wd-01 | No verdict text says 'caused' or 'because of' | pass |
| wd-02 | Strongest result says 'during the trial' and 'does not prove' | pass |

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

