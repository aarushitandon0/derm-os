# derm//os evidence benchmark

**61 of 61 cases pass.**

Written and run by the derm//os team, so this is **not an independent evaluation**. Each case has an expected output written from the design doc before the engine was run. It shows the decision and evidence rules behave as designed; it says nothing about how accurate YouCam's skin scores are. No YouCam calls, no units spent.

Run: `cd backend; python -m benchmark` (also runs under `python -m pytest`).

| Category | Passed |
| --- | --- |
| Avoided ingredient is blocked, with the label line | 6 / 6 |
| Synonyms are still blocked | 6 / 6 |
| Incomplete INCI is unknown, never pass | 5 / 5 |
| Product-level reaction blocks that product only | 4 / 4 |
| Add switched to replace recalculates | 5 / 5 |
| Several changes: can't tell | 4 / 4 |
| Overlap: no detectable change | 5 / 5 |
| Different conditions: not comparable, re-guide | 10 / 10 |
| Symptoms outrank improved scores | 6 / 6 |
| Unresolved stop symptom persists | 4 / 4 |
| Missing baseline: no trend claim | 4 / 4 |
| Wording never claims cause | 2 / 2 |

## Not benchmarked yet

| Design row | Why |
| --- | --- |
| LLM down or draft rejected: templates shown, core flow unaffected | No LLM layer is built yet. All on-screen wording is fixed template text, so the core flow never depends on an LLM. |
| LLM draft says "caused by": validator rejects it | No LLM layer or claim validator is built yet. The 'Wording never claims cause' cases check the fixed templates instead. |

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

### Product-level reaction blocks that product only

| Case | Checks | Result |
| --- | --- | --- |
| pr-01 | Reaction to Velvet Rose blocks Velvet Rose | pass |
| pr-02 | Rose toner sharing Linalool is not blocked (no ingredient allergy invented) | pass |
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

