# Engineering

Ghostdesk runs with no person at the desk. This page shows how it is built and which test proves each guarantee.
Details of every module: [modules](dev/modules.md). Every design choice and why: [decisions](dev/decisions.md).

## The nightly loop
```
 Cloudflare Worker cron 01:30 + 11:00 UTC ──▶ GitHub workflow_dispatch (live.yml; GitHub schedule = backup)
   night: members (Wikipedia) ─▶ new bars into the point-in-time store ─▶ 158 features ─▶ every model predicts
          every member ─▶ ledger file + hash-chain line (append-only) ─▶ ensemble ─▶ optimizer ─▶ whole shares
          ─▶ market-on-open orders (one per stock and night) ─▶ record ─▶ score older predictions
   site:  account vs SPY, tonight's predictions, model leaderboard from the ledger, health ─▶ GitHub Pages
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
| No failure emails | Every step of the scheduled workflows continues on error | `test_workflows.py` |
| Features never read a later session | `Ref` refuses negative lags; changing all later data changes no earlier value | `test_features.py::test_no_feature_reads_a_later_session` |
| Engine = plain pandas | All 158 factors agree with a pandas implementation | `test_features.py::test_all_158_factors_match_plain_pandas` |
| Results can be made again | Run key = data + code + config; a rerun of LightGBM gives the same bytes | `test_research.py::test_lightgbm_is_bit_identical_on_rerun`, `data/results/validation.json` |
| Optimizer constraints hold | Dollar, beta and sector neutral, 2% cap, gross 2, non-members 0 | `test_research.py::test_optimizer_respects_every_constraint` |
| Predictions before orders | No order for a session without its ledger file; the ledger is never rewritten | `test_nightly.py`, invariant I5 |
| Orders only in Alpaca's OPG window | 19:00-09:28 New York time, both seasons | `test_nightly.py::test_window_follows_new_york_time_in_winter_and_summer` |
| Crashes, storms, partial fills, missed nights | 500 random scenarios (10,152 runs, 1,545 crashes, 1,039 runs stopped by 429 storms): 0 violations of six invariants; two deliberate bugs are caught | `test_nightly.py::test_fault_injection_*`, `data/results/fault_injection.json` |
| Docs match the code | Every module, public name and script is documented | `test_docs.py` |
