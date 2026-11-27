# Status and next work

Updated 2026-11-24. The project is a quant research platform (decision D26). The switch-over is done (D38): the
monthly paper desk is archived in `docs/archive/monthly-desk-2026-11/` and closed, the paper account holds nothing,
and order execution is disabled. The nightly job (`nightly.yml`) writes predictions to the ledger before each open and
scores them forward; no order is placed.

## Done
| Step | Result | Evidence |
|---|---|---|
| Universe | 96.8% of 2010-2025 member-days mapped to a CIK | `universe_coverage.json` |
| Seed prices | 98.0% of 2016-2025 member-days with a bar; 8 vendor-error days | `prices_coverage.json` |
| 1. Deletions | lazy prices, execution study, monthly models, launchd trigger removed | D26 |
| 1. Price store | seeded from the 2016-2025 load; extended to 2026-11-23 (117,247 raw rows, 35 symbols refetched) | `data/store/ingest_log.json` |
| 1. Sectors | 709 companies, 25 SIC groups | `sectors.parquet` |
| 2. Feature engine | 151 of 158 Alpha158 factors equal plain pandas to 1e-6 (the other 7 are BETA, RSQR, RESI on 5-20 day windows: rounding of the running sums, at most 1.5e-4 relative to a value near 0; D28); 1,354 nodes → 357 unique; 1,762 x 635 panel cold 6.8-22.8 s, warm 0.2-1.4 s and 24.9-34.2x faster than pandas on 50 symbols (28.3x in the committed run; times vary with machine load) | `docs/results/bench_features.json`, `tests/test_features.py` |

| 3. Walk-forward | panel 2016-2022 (1,762 x 635), yearly folds 2018-2022; all four local models in 222 s (LightGBM 208 s, the Mac was busy; an earlier idle run took 83 s); whole script 510 s with the optimizer and the rerun check | `docs/results/validation.json` (`timing_s`) |
| 3. Validation 2021-2022 (501 sessions) | rank IC: reversal 1d 0.0089, reversal 5d 0.0072, ridge 0.0070, LightGBM 0.0100 (t 2.85; 0.0108 before the constant-window fix of the feature engine). Decile books lose money after the spread estimate (net Sharpe -0.3 to -1.2). 7 models have validation scores | `docs/results/validation.json` (`models`) |
| 3. Optimizer (LightGBM scores) | median solve 62.9 ms (p95 119.0 ms; three runs on this Mac gave medians of 34.0, 47.4 and 62.9 ms, so it depends on load), 503/503 optimal; turnover 0.83 vs 2.61 for the decile book; net of spread +2.5 bps/day (Sharpe 1.04) vs -4.5 bps/day (-0.77); at a fixed 5 bps both lose (-1.5 and -6.6 bps/day) | `validation.json` (`optimizer`) |
| 3. Transformer (Kaggle GPU, 8.7 min, 71,297 parameters, 3 seeds) | validation IC 0.0082 (t 1.35), turnover 2.85, gross +8.0 bps/day, net of spread -4.2 bps/day (Sharpe -0.49) | `validation.json`, `data/kaggle/out/transformer/meta.json` |
| 3. Foundation models, zero-shot (Kaggle GPU, 2021-2022 is before every cutoff) | Chronos-2 IC -0.0008 (t -0.21), TimesFM-2.5 IC -0.0015 (t -0.49), 247,919 forecasts each; both lose after costs. Kronos-small failed with CUDA out of memory (batch of about 500 series x 3 samples); not rerun (GPU on hold) | `validation.json`, `data/kaggle/out/foundation/meta.json` |
| 3. Registry | LightGBM walk-forward rerun bit-identical (`--verify`, run key `595a1d9332fe60c9`) | `docs/results/validation.json` (`verify`) |
| 4. Pre-registration | draft committed (`Status: draft`, not stamped); the lock stays closed | `docs/preregistration-platform.md` |
| 5. Nightly loop | ledger, frozen models, nightly job; the order path is kept in the code but disabled (D38); fault injection: 500 scenarios, 0 violations | `data/results/fault_injection.json` |
| 5. Dry night on real data | 2026-11-23: 500 members, 4 models, 1,996 predictions, optimized book of 143 stocks (gross 2.0, net 0); design 2.4 s, optimizer 0.6 s | local dry run, 2026-11-24 |
| 6b. Site | new page: how it works, the 2021-2022 historical validation (all seven models, optimizer vs decile book, from `web/assets/validation.json`), forward-scored ledger, tonight's calls, model leaderboard, health; every live panel has an empty state when `data/live.json` is missing; `/explore/` forwards to the page; no account curve (nothing is traded); rebuilt by each nightly run, no commit | `web/` |
| 6a. Trigger | Cloudflare Worker code and setup guide (owner deploys) | `worker/`, [trigger-setup.md](trigger-setup.md) |

| 7. Forward evaluation | scoring of the ledger (rank IC, hit rate, error, zero-signal and reversal baselines), book tracking (return, Sharpe, drawdown, turnover, Corwin-Schultz cost), validation-versus-forward table and page section; runs on an empty ledger ("0 days of forward data"); no forward result exists yet | `scripts/live_eval.py`, `tests/test_evaluate.py`, D37 |
| 8. Switch-over (D38) | monthly desk archived (record removed from the tree and site; in git history at 80f8347) and closed (0 positions); `live.yml` replaced by `nightly.yml` with `TRADING` fixed off; models published as the pinned release `models-v1` with `MODEL_MANIFEST.json`; timing guard; model and pipeline errors fail the run | `docs/archive/monthly-desk-2026-11/`, `docs/results/MODEL_MANIFEST.json`, `tests/test_workflows.py` |

## Next
3. Kaggle: Transformer and foundation-model kernels pushed 2026-11-24, still queued; GPU on hold for another
   project (owner's decision). Their scores enter `run_validation.py` from `data/kaggle/out/`.
4. Owner: approve the pre-registration; then set it final, stamp it, commit the proof, run the test once.
5. Owner: deploy the Worker ([trigger-setup.md](trigger-setup.md)); until then the GitHub schedule starts the night.
   Execution stays off until the checklist in the runbook ("Before execution is turned on") is done.
6. Kaggle scores (when the GPU is free) into `run_validation.py`, then the ensemble rule again.

## Known open items
- The index intervals were built on 2026-11-16 from Wikipedia; changes to the index after that date reach the
  research data only when `build_universe.py` runs again. The live loop reads today's members each night.
- `data/raw/` (SEC cache) and the old study files in `data/` are no longer needed except the submissions JSON for
  sectors; the owner decides when to delete them.

## Forward evaluation: timing rules and the count

- **Two timestamps per prediction.** `made_at` is the real UTC time of the run that generated the predictions, and
  `written_at` in the ledger is the same time. The intended session (the close the predictions follow) is a separate
  field. A prediction counts only if `made_at` is earlier than the first open after its session (09:30 New York time).
- **No backfill.** The night step writes only the last closed session. A run that starts after the next open does
  not write that session (the session is recorded as missed), so a late or retried run cannot create a prospective-looking
  prediction. A second write for the same session is refused, and a re-run reports the existing entry with its original time.
- **Refused rows.** Any row whose `made_at` is not earlier than that open is left out of scoring (`refused()`), and the
  forward evaluation uses scored rows only. Historical validation (2021–2022) comes from `validation.json` and never
  enters the ledger.
- **Trading calendar.** The next session is taken from the price store, so weekends and exchange holidays are skipped.
  2026-11-26 was Thanksgiving (market closed). Session 2026-11-24 is scored after the 2026-11-27 open, and session
  2026-11-25 after the 2026-11-30 open. The first scored day is therefore expected on the 2026-11-28 scheduled run.
  Zero forward days on 2026-11-27 is expected: the 2026-11-27 open had not yet happened when that run started.

## Temporal integrity of the frozen models (verified 2026-11-27, read-only)

Result: **passes**, with the caveats below. Checked against `docs/results/MODEL_MANIFEST.json`, `scripts/research/fit_live_models.py`,
`src/ghostdesk/research/dataset.py` (`load_panel`, `guard`), `src/ghostdesk/research/models.py` (`rank_features`) and `docs/results/validation.json`.

- **Training data cutoff.** The nightly models (reversal 1-day and 5-day, ridge, LightGBM) were fitted on sessions
  2016-01-04 to 2022-12-28, with the last two labels dropped. The panel's recorded end is 2022-12-30 (data hash `…|20221230|…`).
  `load_panel` refuses any end date in the test period (`guard`), and the fit's end is the validation end (2022-12-31).
- **Feature transformations.** Alpha158 features use windows that end at the session (a test checks that no feature
  reads a later session). `rank_features` ranks each feature across stocks within one session, so no mean, scale or other
  statistic is fitted over time.
- **Hyperparameters and ensemble weights.** Chosen on the 2021–2022 validation runs only (`validation.json` has no 2023-or-later
  data; its only 2026 date is its run timestamp, 2026-11-24). This is in-sample for those choices, and the page says so.
- **Artifacts.** Fitted once on 2026-11-24 (`fitted_at` in the manifest, 17:08 UTC). The release `models-v1` was published
  at 17:28 UTC, before the first ledger write (2026-11-25 00:01 UTC). Each night checks the file hashes against the manifest.
- **Foundation models and the Transformer are not in the nightly ensemble.** Chronos-2 and TimesFM-2.5 are validation-only,
  and the Transformer and Kronos are not published (their pretraining data may overlap the validation years).
- **Membership.** The S&P 500 membership is point-in-time from dated changes, not a current list.

Caveats (not leakage into the predictions):
- Sector labels (SIC groups) are one snapshot and are used only by the optimizer's sector-neutral constraint, never by the
  models. Historical sector labels are not point-in-time.
- The 2023-01 to 2026-10 test period is locked. The pre-registration is still `Status: draft`, so no test-period result exists
  and none is claimed. The forward ledger (from 2026-11-24) lies after that period, so it does not overlap any data the models saw.
- Forward evaluation is the only independent evidence so far. It has 0 scored days (see the timing section above).

## Optimizer cost model: a limitation (2026-11-27)

- Both books in `docs/results/validation.json` (LightGBM scores, 501 sessions, 2021-2022) use the same cost function
  (`research/backtest.py::evaluate`): one-way cost per unit traded, either the Corwin-Schultz half-spread or a fixed grid.
- The 21-day Corwin-Schultz half-spread is clipped at zero (`half_spread`), and is exactly zero for 63.9% of member-days
  in 2021-2022 (median 0, mean 4.19 bps). The optimizer's penalty uses that estimate plus 2 bps, so it trades mostly
  in names with a zero estimate: implied cost 0.1 bps a day against 4.2 bps for the decile book.
- So the spread-model net Sharpe (optimizer 1.04, decile -0.77) is the most favourable comparison. Under one fixed cost:
  1 bps 0.73 vs 0.67, 2 bps 0.39 vs 0.22, 5 bps -0.63 vs -1.14. Gross: 1.07 vs 1.12. Turnover 0.83 vs 2.61 (-68%).
- Public claims use the fixed 2 bps comparison. The page's validation tile still shows the spread-model Sharpe; changing it
  is an owner decision.

