# Engineering

Ghostdesk runs with no person at the desk. This page shows how it is built and which test proves each guarantee.
Details of every module: [modules](dev/modules.md). Every design choice and why: [decisions](dev/decisions.md).

## The nightly loop
```
 Cloudflare Worker cron 01:30 + 11:00 UTC ──▶ GitHub workflow_dispatch (nightly.yml; GitHub schedule = backup)
   night: pinned models (models-v1, checked against MODEL_MANIFEST.json) ─▶ members (Wikipedia) ─▶ new bars into
          the point-in-time store ─▶ 158 features ─▶ every model predicts every member, before the next open
          ─▶ ledger file + hash-chain line (append-only) ─▶ ensemble ─▶ optimizer ─▶ target book (no orders:
          execution is disabled) ─▶ record ─▶ score older predictions ─▶ forward_eval.json
   site:  forward-scored ledger, tonight's predictions, model leaderboard, health ─▶ GitHub Pages
```

## Guarantees and the tests that prove them
| Guarantee | How | Test |
|---|---|---|
| No survivorship bias | The stock list on each date is the S&P 500 on that date, mapped to SEC CIKs with evidence | `test_sp500_universe.py` |
| Point-in-time prices | Immutable batches; a read at a past date sees the adjusted prices as they were known then | `test_store.py::test_as_of_read_sees_the_old_adjusted_history` |
| A dividend or split is caught | The nightly load compares overlap sessions and refetches the whole adjusted history of that symbol | `test_store.py::test_daily_ingestion_appends_and_refetches_after_a_dividend` |
| The test stays locked | Test sessions open only after the final, committed, stamped pre-registration | `test_holdout_lock.py` |
| Paper money only | The broker refuses any host but the paper API | `test_live.py::test_broker_refuses_a_live_endpoint` |
| Orders never cross zero | A flip is a close, then an open | `test_live.py::test_orders_reach_target_and_never_cross_zero` |
| Rate limits respected | At most 170 requests a minute (limit 200); 429 retried | `test_live.py::test_broker_paces_requests_and_keeps_retrying_rate_limits` |
| Order execution is off | `nightly.yml` fixes `TRADING` to `off` and has no order or flatten mode; only `ci.yml` and `nightly.yml` exist | `test_workflows.py::test_execution_is_disabled_in_the_nightly_workflow`, `test_workflows.py::test_only_ci_and_nightly_exist` |
| Kill switch is on only for exactly `on` | Unset, empty or any other value means no orders; `Deps.trading` defaults to off | `test_nightly.py::test_trading_is_on_only_for_the_exact_value_on` |
| The models are the published ones | The pinned release `models-v1` is checked against the SHA-256 in `MODEL_MANIFEST.json`; a missing, corrupt or incompatible file stops the night | `test_model_release.py`, `test_workflows.py::test_models_are_pinned_cached_and_verified_before_use` |
| Predictions are made before the outcome | A session is written only before its next open, or recorded as `missed`; scoring refuses a prediction made at or after the open it is scored on | `test_nightly.py::test_night_writes_the_ledger_before_the_next_open_and_never_after`, `test_nightly.py::test_score_refuses_a_prediction_made_at_or_after_the_first_realized_open` |
| A broken night is reported | Model, pipeline, ledger, evaluation or state-upload errors fail the run (GitHub's failure notice, D38); site steps never do | `test_workflows.py::test_failures_of_the_pipeline_fail_the_run_and_the_site_steps_do_not` |
| Features never read a later session | `Ref` refuses negative lags; changing all later data changes no earlier value | `test_features.py::test_no_feature_reads_a_later_session` |
| Engine = plain pandas | All 158 factors agree with a pandas implementation (rtol 1e-6, atol 1e-9); on the real panel 151 of 158 agree to 1e-6, the other 7 differ by rounding (D28) | `test_features.py::test_all_158_factors_match_plain_pandas`, `docs/results/bench_features.json` |
| Results can be made again | Run key = data + code + config; a rerun of LightGBM gives the same bytes | `test_research.py::test_lightgbm_is_bit_identical_on_rerun`, `docs/results/validation.json` |
| Optimizer constraints hold | Dollar, beta and sector neutral, 2% cap, gross 2, non-members 0 | `test_research.py::test_optimizer_respects_every_constraint` |
| Predictions before orders | No order for a session without its ledger file; the ledger is never rewritten | `test_nightly.py`, invariant I5 |
| Orders only in Alpaca's OPG window | 19:00-09:28 New York time, both seasons | `test_nightly.py::test_window_follows_new_york_time_in_winter_and_summer` |
| Crashes, storms, partial fills, missed nights | 500 random scenarios (10,152 runs, 1,545 crashes, 1,039 runs stopped by 429 storms): 0 violations of six invariants; two deliberate bugs are caught | `test_nightly.py::test_fault_injection_*`, `data/results/fault_injection.json` |
| Forward results are scored only when matured | A prediction counts after its open(t+1) and open(t+2) exist; an empty ledger reports 0 days; a changed ledger file breaks the chain | `test_evaluate.py` |
| Docs match the code | Every module, public name and script is documented | `test_docs.py` |
