# FACTS: every README claim, where it lives, and what tests it

One row per claim in [README.md](../README.md). Code paths are under `backend/app/` unless shown otherwise, and tests are under `backend/tests/`. "bench `id`" is a case in `backend/benchmark/cases.py`, run by `python -m benchmark` and by `tests/test_evidence_benchmark.py`, so CI fails if it fails. Rows marked **not automated** say so.

Counts measured on 1 Nov 2026.

## The flow

| Claim | Code | Test |
| --- | --- | --- |
| A free precheck (one face, not a side profile, not too dark) runs before any unit is spent | `pose.py`; `main.py` `basket_precheck()`, `_photo_check()`, `basket_scan()` | `test_tone_tolerance.py` `test_precheck_blocks_a_side_profile_before_any_youcam_call`, `test_precheck_blocks_a_dark_photo`, `test_an_unusable_photo_stops_before_the_analysis_is_paid_for`, `test_free_precheck_endpoint_reports_angles_and_the_rule` |
| Face map: skin type per zone (T-zone vs cheeks), read from the live SD shape | `needs.py` `parse_zones()`, `_region_items()`, `read_zones()` | `test_needs_undertone.py` `test_parse_zones_live_sd_shape_one_item_per_region`, `test_parse_zones_documented_shapes`, `test_parse_zones_live_shape_whole_only_is_split` |
| Needs are shown in words, never scores | `needs.py` `build_needs()`; `basket.py` `face_map()` | `test_needs_undertone.py` `test_needs_lines_are_words_only`; `test_basket.py` `test_no_scores_and_no_cant_tell_in_any_user_sentence` |
| One need per zone | `needs.py` | `test_needs_one_per_zone.py` (both tests) |
| Oily T-zone + other cheeks gives two moisturisers; same type in both zones gives one | `basket.py` `jobs_for()` | `test_basket.py` `test_oily_tzone_dry_cheeks_gets_two_moisturisers`, `test_same_type_in_both_zones_gets_one_moisturiser` |
| History by ingredient ("Vitamin C itched", "Azelaic acid broke me out") skips with the exact reason; product-level history ranks above it | `chips.py`, `chips.json`; `basket.py` `_consider()` | `test_chips.py` `test_itched_skips_with_reason_exact_and_family`, `test_broke_out_skips_only_a_key_active_with_formula_caveat`, `test_product_level_history_ranks_above_chips` |
| Each card has three labelled reasons (face, history, finish) and how to use it | `basket.py` `build()` (`why`, `HOW_TO_USE`) | `test_basket.py` `test_riya_full_basket`; bench basket cases |
| Every skipped product shows its exact reason, e.g. the Alcohol Denat. line | `basket.py` `SKIP_ORDER`, `SKIP_LABEL`; `patterns.py`; `cartcheck.py` | `test_basket.py` `test_the_history_suspect_is_skipped_with_its_exact_reason`, `test_an_avoided_ingredient_is_skipped_with_the_label_line` |
| An incomplete ingredient list is "unknown", never a pass, never picked; its label is printed once | `basket.py` `_consider()`; `cartcheck.py` `UNKNOWN_LABEL` | `test_basket.py` `test_incomplete_inci_is_never_picked`, `test_incomplete_inci_is_not_picked_even_when_it_is_the_only_candidate`; `test_cartcheck.py`; bench `inc-01`…`inc-05` |
| Wrong zone type, wrong finish, no shade and over budget are skip reasons | `basket.py` `_consider()` | `test_basket.py` `test_finish_changes_the_texture_and_finish_picks`, `test_a_range_with_no_shade_for_you_is_skipped_as_such`, `test_budget_skips_over_budget_products_while_something_under_fits` |
| Products you already own are marked "skip buying" | `basket.py` `build()` (`already_own`) | `test_basket.py` `test_an_owned_cleanser_is_not_bought_again`, `test_an_owned_store_product_moves_to_already_own_and_out_of_the_total` |
| Start plan: patch test, then one new product every 2 weeks, gentlest first | `startplan.py` `plan()` | `test_startplan.py` `test_patch_week_then_one_new_product_every_14_days`, `test_order_is_gentle_then_base_then_actives`, `test_exactly_one_plan_per_basket_with_sources_and_stop_line` |
| Calendar reminders | `frontend/src/ics.ts`; `components/BasketExtras.tsx` `StartPlanCard` | **not automated** (TypeScript check only) |
| Try-on: the base product, matte and dewy, in your shade | `basket.py` `TRYON_LOOKS`, `tryon_plan()`; `youcam.py` `makeup_vto()` | `test_youcam_tone_vto.py` `test_makeup_vto_sends_the_foundation_effect_and_reads_the_url`; `test_api_basket.py` `test_live_run_chains_analysis_tone_and_two_renders_then_deletes`; `test_tone_tolerance.py` `test_a_failed_try_on_keeps_the_basket` |
| Paste any label: checked the same way; nothing saved; brand text dropped | `pastecheck.py`; `main.py` `paste_check()` | `test_pastecheck.py` `test_suspect_repeats_a_pattern`, `test_truncated_list_is_unknown_never_clean`, `test_nothing_is_stored`, `test_brand_and_trademark_text_dropped_and_nickname_used` |
| Beginner: no history step; every pick and every "Also fits" alternative leans gentle (no fragrance, essential oils or Alcohol Denat.) | `basket.py` `harsh_for_beginner()`, `gentle_rank()`, `GENTLE_LABEL` | `test_basket.py` `test_beginner_also_fits_has_no_fragrance_or_alcohol_denat` (12 cases), `test_the_beginner_filter_is_what_removes_them`; `test_beginner_demo.py` `test_beginner_after_riya_has_no_leftover_history`; bench `ha-10` |
| Breakout helper: what changed 2–8 weeks ago, purging or not, one product to pause | `triage.py` `WINDOW_WEEKS` | `test_triage.py` (all); bench "Breakout triage" (18 cases) |
| Check-in: one new photo against your first scan, in plain words | `evidence.py`; `main.py` trials endpoints | bench "Different conditions", "Overlap" and "Positive persona" categories |
| Store page with "Check against my skin" | `frontend/src/screens/Store.tsx`; `main.py` `store()`, `cart_check()` | `test_api_moments.py`; screenshots **not automated** in CI |

## The 3 YouCam APIs

| Claim | Code | Test |
| --- | --- | --- |
| Skin Analysis v2.1 SD with `skin_type` + 7 concerns | `demo_faces.py` `BASKET_ACTIONS`; `youcam.py` `analyze()` | `test_api_basket.py` `test_live_run_chains_analysis_tone_and_two_renders_then_deletes` |
| Skin Analysis SD with 5–8 concerns costs 12 units | `youcam.py` `PRICE_FALLBACK`, `scan_cost()` | `test_facecrop.py` `test_cost_is_tiered_by_number_of_concerns` |
| Skin Tone costs 20 units and Makeup VTO costs 1, read from the free price list | `youcam.py` `FEATURE_PRICE_FALLBACK`, `feature_cost_from()`, `feature_cost()` | `test_youcam_tone_vto.py` `test_feature_cost_from_the_live_price_list_and_fallback`, `test_client_feature_cost_reads_the_free_list_once` |
| Skin Tone runs before Skin Analysis | `main.py` `_live_basket()` | `test_tone_tolerance.py` `test_tone_runs_before_the_analysis` |
| Endpoints: file register + presigned upload, task create + poll, delete | `youcam.py` `upload()`, `create_task()`, `poll()`, `run_feature()`, `delete_task()` | `test_youcam.py` `test_full_flow_with_mock_transport`; `test_youcam_tone_vto.py` `test_skin_tone_upload_task_poll`, `test_tone_and_vto_tasks_delete_through_the_shared_endpoint` |

## Run it in 5 minutes

| Claim | Code | Test |
| --- | --- | --- |
| `DEMO_MODE` defaults to `1`; no key needed | `guard.py` `demo_mode()` | `test_judge_mode.py` `test_demo_mode_is_on_unless_explicitly_zero` |
| Demo mode never calls YouCam | `main.py` `basket_scan()` → `_replay_basket()` | `test_api_basket.py` `test_scan_without_passcode_replays_and_never_calls_youcam` |

## Notes

| Claim | Code | Test |
| --- | --- | --- |
| The undertone is derived from YouCam's skin colour by a documented rule, and says so | `undertone.py` (module docstring, `classify()`, `DERIVED_NOTE`) | `test_needs_undertone.py` `test_classify`, `test_from_documented_payload_is_derived_and_says_so` |
| With no colour, one quiz question gives the undertone, labelled "from your answers" | `undertone.py` | `test_needs_undertone.py` `test_fallbacks_are_labelled`; `test_tone_tolerance.py` `test_veins_answer_gives_a_labelled_undertone`, `test_angle_refusal_still_returns_the_full_basket_from_the_answer` |
| Demo data is labelled; Riya's face values are from one recorded live scan, with values only | `demo_faces.py` `load_face()`; `backend/fixtures/riya/basket_face.json` | `test_basket.py` `test_demo_face_is_labelled_recorded_values_with_a_synthetic_fallback`; `test_tone_tolerance.py` `test_demo_persona_uses_the_recorded_face_and_keeps_the_demo_label` |
| No scores shown | `basket.py`, `needs.py` | `test_basket.py` `test_no_scores_and_no_cant_tell_in_any_user_sentence`; `test_claim_linter.py` `test_shopping_flow_rules` |
| Every basket ends with one next step (patch-test, one at a time) | `basket.py` `NEXT_STEP` | `test_basket.py` `test_every_basket_has_exactly_one_next_step`, `test_nothing_new_to_buy_still_has_one_next_step` |
| "Decision support, not diagnosis." on screen; see a dermatologist for painful or persistent spots | `frontend/src/copy.ts` `NOT_DIAGNOSIS`; `needs.json` (`see_doctor`) | `test_claim_linter.py` `test_not_diagnosis_line_on_home_evidence_and_brief`; `test_needs_undertone.py` `test_acne_need_carries_the_see_a_dermatologist_line` |
| All products and brands are fictional | `store.json`, `catalog.json`; `scripts/claim_lint.py` `BRANDS` | `test_claim_linter.py` `test_no_real_brand_or_retailer_names`; `test_basket.py` `test_store_has_16_to_20_tagged_fictional_products` |

## Counts

| Claim | How measured |
| --- | --- |
| 1,100 backend tests passing | `cd backend; python -m pytest -q` (1 Nov 2026) |
| 235 / 235 benchmark cases | `python -m benchmark`; `backend/results/benchmark.md` |
| Claim linter: 0 findings, 16 allowed with a reason, 0 brand names | `python scripts/claim_lint.py`; `test_claim_linter.py` `test_every_exception_has_a_reason_and_is_still_needed` |
| 19 store products | `store.json` `products`; `test_basket.py` `test_store_has_16_to_20_tagged_fictional_products` |
| 13 ingredient chips over 6 families | `chips.json` `chips`; `families.json` |
| 15 screenshots at 390 px, 0 sideways scroll, 0 targets under 44 px | `frontend/scripts/screenshots.mjs` → `docs/screenshots/layout-check.json`; **not in CI** |
| CI runs pytest, benchmark, linter, tsc, vite build | `.github/workflows/ci.yml` |

## Units are guarded

| Claim | Code | Test |
| --- | --- | --- |
| Live needs the server set to live and the passcode | `guard.py` `scan_source()` | `test_deploy.py` `test_no_passcode_header_replays_fixtures`, `test_wrong_passcode_is_refused_not_replayed`, `test_demo_mode_replays_even_with_passcode` |
| Balance floor read before every live run; an unreadable balance sends nothing | `guard.py` `balance_floor()`; `main.py` `_live_basket()` | `test_api_basket.py` `test_live_run_below_the_floor_replays_and_sends_nothing`; `test_judge_mode.py` `test_balance_floor_blocks_and_survives_a_restart`; `test_demo_safety.py` `test_scan_falls_back_when_credit_call_fails` |
| Judge caps 300 total / 100 a day, and a 200-unit reserve | `guard.py` `judge_caps()`; `main.py` `unit_reserve()` | `test_judge_mode.py` `test_total_cap_falls_back_and_is_counted_in_the_database`, `test_daily_cap_falls_back_to_prepared_data_with_a_plain_message`, `test_reserve_still_applies_under_the_caps` |

## Privacy

| Claim | Code | Test |
| --- | --- | --- |
| The photo is deleted from the server after the run, and the task is deleted at YouCam | `main.py`; `youcam.py` `delete_task()` | `test_judge_mode.py` `test_uploaded_photo_and_its_crop_are_deleted_after_the_scan`; `test_api_basket.py` `test_live_run_chains_analysis_tone_and_two_renders_then_deletes` |
| Metadata stripped; GPS never stored | `photometa.py` `clean_copy()`, `clean_bytes()` | `test_upload.py` `test_gps_is_never_stored_and_stored_files_have_no_exif`, `test_clean_bytes_drops_every_tag` |
| Pasted ingredient lists are never saved | `pastecheck.py` | `test_pastecheck.py` `test_nothing_is_stored` |
| Committed fixtures hold scores only | `scripts/make_fixtures.py` | `test_privacy.py` `test_committed_fixtures_have_no_urls_or_images` |
| A pre-commit hook blocks photo files | `scripts/git-hooks/pre-commit` | **not automated** |
| Keys never logged | `youcam.py` `delete_task_quietly()` | `test_privacy.py` `test_delete_quietly_logs_without_secrets` (that log path only) |

## How it's built

| Claim | Code | Test |
| --- | --- | --- |
| MediaPipe face guide in the browser | `frontend/src/capture/faceGuide.ts` | **not automated** |
| Server-side crop and head-pose precheck | `facecrop.py`, `pose.py` | `test_facecrop.py`; `test_tone_tolerance.py` `test_angles_from_matrix_round_trip` |
| Docker image for Render, with both models downloaded at build time | `backend/Dockerfile`, `render.yaml` | **not automated** (see docs/DEPLOY.md) |
| Engines are versioned and store their inputs | each engine's `RULE_VERSION` | `test_basket.py` `test_inputs_and_rule_versions_are_stored`; `test_api_basket.py` `test_meta_lists_the_new_rule_versions` |
