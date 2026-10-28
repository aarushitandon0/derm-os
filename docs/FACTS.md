# FACTS: every README claim, where it lives, and what tests it

One row per claim in [README.md](../README.md). Paths are from the repo root. "bench `id`" is a case
in `backend/benchmark/cases.py`, run by `python -m benchmark` and by
`backend/tests/test_evidence_benchmark.py` (so CI fails if it fails). Rows marked **not
automated** say so plainly.

## The number

| Claim | Implemented in | Tested by |
| --- | --- | --- |
| The derm//os false-change rate comes from the app's own verdict function on every 3 + 2 split of the no-change photos | `backend/scripts/analyze_experiment.py` `splits()`, `dermos_false_change()` (calls `app.evidence.evaluate`) | `backend/tests/test_analyze_experiment.py` `test_dermos_rate_hand_checked`, `test_dermos_rate_calls_the_real_verdict_function` |
| Constants are unchanged for it | same, `constants()`; `evaluate(..., band=E.MIN_BAND)` | `test_dermos_rate_hand_checked` (checks the recorded TOLERANCES and MIN_BAND) |
| A fixed ±5 / ±4 rule is measured over every pair | `fixed_threshold()` | `test_fixed_threshold_rates_hand_checked` |
| The first result is frozen and never replaced; later tuning is labelled "after tuning on these same photos" | `preregistration()`, `markdown()` | `test_preregistered_number_is_never_replaced`, `test_preregistration_for_other_photos_is_refused_not_overwritten` |
| The gate's share of window-vs-lamp pairs marked not comparable | `lighting()` | `test_noise_and_lighting` |
| The report states n and that splits share photos (not independent) | `markdown()`, `headline()` | `test_report_section_states_n_and_non_independence_and_is_replaced_in_place` |
| No report with fewer than 3 window or 2 lamp scans | `split()` | `test_no_report_with_too_few_photos` |

## What it does

| Claim | Implemented in | Tested by |
| --- | --- | --- |
| `DEMO_MODE` defaults to `1` | `backend/app/guard.py` `demo_mode()` | `backend/tests/test_judge_mode.py` `test_demo_mode_is_on_unless_explicitly_zero` |
| A baseline is 3 scans and a check-in is 2 | `frontend/src/screens/Capture.tsx` (shot counts); `backend/app/evidence.py` `evaluate()` needs at least 2 + 2 | bench `mb-01`…`mb-04` (fewer gives no trend) |
| A change counts only when the ranges don't overlap | `evidence.py` `_findings()` | bench `ov-01`…`ov-05`; `backend/tests/test_benchmark.py` `test_overlapping_ranges_mean_no_detectable_change` |
| The gate checks brightness, light colour, face size, head angle, camera and time of day | `evidence.py` `compare_conditions()`; `backend/app/fingerprint.py` `measure()` | bench `nc-01`…`nc-12` |
| A mismatch gives "can't tell", with how to retake | `evaluate()` (NOT_COMPARABLE), `Comparability.fixes` | bench `nc-08`, `nc-09` |
| Every photo is cropped by a local detector and scaled to the same face width, with no colour, brightness or rotation edits | `backend/app/facecrop.py` `normalise()`, `plan()`, `BlazeFace` | `backend/tests/test_facecrop.py` `test_normalised_face_width_is_the_target_in_pixels`, `test_no_colour_or_brightness_change`, `test_never_upscales_a_small_face` |
| More than one new leave-on product: "can't tell which" | `evaluate()` (SEVERAL_CHANGES) | bench `sc-01`…`sc-04` |
| A reported reaction gives Stop, whatever the scores | `evaluate()` (STOP first); `backend/app/main.py` `_reactions()` | bench `sy-01`…`sy-06`, `sp-01`…`sp-04` |
| A rebuy line on every verdict, mapped strictly from it; "supports rebuying" only for a comparable better move | `evidence.py` `rebuy_line()`, `REBUY`; shown by `frontend/src/components/Verdict.tsx` `RebuyLine` | bench `rb-01`…`rb-08` |
| Three record types; a product reaction never becomes an ingredient allergy | `backend/app/decision.py` `HistoryRecord`, `check_product()` | bench `pr-01`…`pr-04` |
| An incomplete label is "unknown", never a pass | `decision.py` `check_product()` | bench `inc-01`…`inc-05`, `nt-01`…`nt-07` |
| "Change nothing" is always a column; exclusions show the label line; add vs replace recalculates | `decision.py` `compare()`, `build()` | bench `ex-02`, `ar-01`…`ar-08` |
| The strongest wording is "changed during this trial" | `evidence.py` `VERDICT_TEXT`, `moved_sentence()`, `MOVED_CAVEAT` | bench `wd-01`, `wd-02`, `pos-03`; claim linter |
| "Decision support, not diagnosis" on Home, Results and the Visit brief | `frontend/src/copy.ts` `NOT_DIAGNOSIS`; `screens/Home.tsx`, `Results.tsx`, `Brief.tsx` | `backend/tests/test_claim_linter.py` `test_not_diagnosis_line_on_home_evidence_and_brief` |

## Evidence benchmark and checks

| Claim | Implemented in | Tested by |
| --- | --- | --- |
| 107 of 107 cases pass | `backend/benchmark/` | `python -m benchmark` (exit code 1 on any failure), CI |
| The positive persona is judged by the real engine, with no special-casing | `backend/app/scenes.py` writes rows only | bench `pos-01`…`pos-08` (`pos-04`: same scores under lamp light are not comparable; `pos-08`: the scene code names no verdict, gate or engine) |
| 18 cases cover the optional language layer with a scripted stand-in | `backend/benchmark/fakes.py`, `backend/app/llm/` | bench `llm-01`…`llm-18` |
| 370+ backend tests with no network and no units | `backend/tests/conftest.py` (no `.env`, no key, stand-in face detector) | CI `pytest -q` |
| The claim linter fails the build on overclaiming wording | `backend/scripts/claim_lint.py` | `backend/tests/test_claim_linter.py` (all), CI step "Claim linter" |
| TypeScript typecheck and production build in CI | `.github/workflows/ci.yml` | CI job "frontend" |
| No real brand or retailer names in the catalog, fixtures or UI | `claim_lint.py` `brand_hits()` | `test_no_real_brand_or_retailer_names` |

## YouCam API and units

| Claim | Implemented in | Tested by |
| --- | --- | --- |
| File register, presigned upload, task create, poll | `backend/app/youcam.py` `upload()`, `create_task()`, `poll()`, `analyze()` | `backend/tests/test_youcam.py` `test_full_flow_with_mock_transport` |
| Masks downloaded right away, without the bearer header | `youcam.py` `download_masks()` | `backend/tests/test_demo_safety.py` `test_download_masks_saves_files_and_skips_failures`, `test_live_scan_stores_local_mask_paths` |
| Task delete once masks are saved | `youcam.py` `delete_task()`; `main.py` `scan()` | `backend/tests/test_privacy.py` `test_delete_task_request_shape`, `test_delete_called_after_mask_download` |
| Balance read before every live scan; exact price from the feature-cost list | `youcam.py` `credit()`, `unit_balance()`, `feature_costs()`, `scan_cost()` | `test_facecrop.py` `test_client_reads_paged_price_list`, `test_live_scan_refused_when_balance_cannot_pay_exact_cost` |
| Default 4 concerns (redness, acne, texture, pore), 9 units per SD scan | `main.py` `DEFAULT_ACTIONS`; `youcam.py` `PRICE_FALLBACK`; `frontend/src/api.ts` `DEFAULT_ACTIONS` | `test_judge_mode.py` `test_default_concerns_reserve_and_caps`; `test_facecrop.py` `test_cost_is_tiered_by_number_of_concerns` |
| Decisions use `raw_score`, never `ui_score` | `youcam.py` `SkinResult.raw_scores()`; `main.py` `_to_capture()` | `test_youcam.py` `test_normalize_task_json_uses_raw_score` |
| A live scan needs the server set to live and the passcode | `guard.py` `scan_source()` | `backend/tests/test_deploy.py` `test_no_passcode_header_replays_fixtures`, `test_wrong_passcode_is_refused_not_replayed`, `test_demo_mode_replays_even_with_passcode` |
| Judge caps 300 total / 100 a day, counted in the database | `guard.py` `judge_caps()`; `main.py` `hold_units()`, `settle_units()`, `spend` table | `test_judge_mode.py` `test_total_cap_falls_back_and_is_counted_in_the_database`, `test_daily_cap_falls_back_to_prepared_data_with_a_plain_message`, `test_failed_live_scan_does_not_count_against_the_caps` |
| Over a cap the scan replays prepared data and the app says so | `main.py` `scan()` (`notice`); `guard.py` `cap_message()`; `frontend/src/screens/Capture.tsx` | backend: same cap tests. The on-screen notice: **not automated** (TypeScript check only) |
| A 200-unit reserve | `main.py` `unit_reserve()`; `youcam.py` `check_unit_reserve()` | `test_judge_mode.py` `test_reserve_still_applies_under_the_caps`; `test_facecrop.py` `test_guard_needs_cost_plus_reserve` |

## Privacy

| Claim | Implemented in | Tested by |
| --- | --- | --- |
| The uploaded photo (and its crop) is deleted from the server straight after | `main.py` `scan()` `finally: os.unlink` | `test_judge_mode.py` `test_uploaded_photo_and_its_crop_are_deleted_after_the_scan` |
| Sent to YouCam only for a live scan | `guard.py` `scan_source()`; `main.py` `scan()` | `test_demo_safety.py` `test_demo_mode_replays_fixtures_in_rotation_without_calling_youcam`; `test_privacy.py` `test_demo_mode_never_calls_youcam_delete` |
| Stored scans never keep mask URLs | `youcam.py` `strip_urls()`; `main.py` `scan()` | `test_judge_mode.py` `test_stored_scans_never_keep_mask_urls` |
| "Delete my saved scans" removes them and re-asks YouCam for unconfirmed tasks | `main.py` `delete_captures()` | `test_privacy.py` `test_delete_saved_scans_rerequests_only_unconfirmed_live_tasks`, `test_delete_saved_scans_without_key_still_deletes_locally` |
| Committed fixtures hold scores and capture numbers only | `backend/scripts/make_fixtures.py` `sanitize()`, `leaks()` | `test_privacy.py` `test_fixture_keeps_scores_actions_engine_fingerprint_only`, `test_committed_fixtures_have_no_urls_or_images` |
| A pre-commit hook blocks photo files | `scripts/git-hooks/pre-commit` | **not automated** (installed with `scripts/install-hooks.ps1`) |
| Keys are never logged | `youcam.py` `delete_task_quietly()` logs task id and error type only | `test_privacy.py` `test_delete_quietly_logs_without_secrets` (that log path only; no global test) |

## How it's built

| Claim | Implemented in | Tested by |
| --- | --- | --- |
| The guided demo's scenes only write rows; the same engine computes every verdict | `backend/app/scenes.py`; `main.py` `demo_scene()`, `trial_evidence()` | bench `pos-08`; `test_judge_mode.py` `test_riya_scenes_tell_the_hero_story`, `test_scenes_only_in_demo_mode` |
| Every guided-demo screen shows "Prepared demo data" | `frontend/src/components/Guide.tsx` `GuideBar`; `App.tsx` demo label | Screenshots in `docs/screenshots/` (`frontend/scripts/screenshots.mjs`); **not automated** in CI |
| MediaPipe Face Landmarker in the browser for the live guide | `frontend/src/capture/faceGuide.ts` | **not automated** (TypeScript check only) |
| `/health` makes no YouCam call | `main.py` `liveness()`, `health()` | `test_judge_mode.py` `test_health_never_calls_youcam` |
| Docker image for Render | `backend/Dockerfile`, `render.yaml` | **not automated**; see the build note in `docs/DEPLOY.md` |
| Experiments: `--only` pilot with balance before and after; whole-run balance check | `backend/scripts/run_experiments.py` `main()`, `cost_blocker()` | `test_analyze_experiment.py` `test_pilot_reports_units_charged_and_full_run_reuses_it`; `backend/tests/test_experiment_scripts.py` `test_refuses_when_balance_cannot_cover_the_whole_run` |
| 390 px with no sideways scroll, tap targets at least 44 px | `frontend/src/styles.css` | `frontend/scripts/screenshots.mjs` layout check (12 screens: 0 sideways scroll, 0 small targets on 28 Oct); **not in CI** |
