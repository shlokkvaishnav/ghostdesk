# Status and next work

Updated 2026-11-24. The project is being turned into a quant research platform (decision D26) on the branch
`pivot/research-platform`. The live monthly book on `main` is unchanged until the owner switches over.

## Done
| Step | Result | Evidence |
|---|---|---|
| Universe | 96.8% of 2010-2025 member-days mapped to a CIK | `universe_coverage.json` |
| Seed prices | 98.0% of 2016-2025 member-days with a bar; 8 vendor-error days | `prices_coverage.json` |
| 1. Deletions | lazy prices, execution study, monthly models, launchd trigger removed | D26 |
| 1. Price store | seeded from the 2016-2025 load; extended to 2026-11-23 (117,247 raw rows, 35 symbols refetched) | `data/store/ingest_log.json` |
| 1. Sectors | 709 companies, 25 SIC groups | `sectors.parquet` |
| 2. Feature engine | 158 Alpha158 factors equal to plain pandas; 1,354 nodes → 357 unique; 1,762 x 635 panel cold 6.8-7.6 s, warm 0.2-0.4 s; 23.5-29.7x faster than pandas on 50 symbols | `data/results/bench_features.json`, `tests/test_features.py` |

| 3. Walk-forward | panel 2016-2022 (1,762 x 635), yearly folds 2018-2022; all four local models in 83 s (LightGBM 82 s); whole script 225 s with the optimizer and the rerun check | `data/results/validation.json` (`timing_s`) |
| 3. Validation 2021-2022 (501 sessions) | rank IC: reversal 1d 0.0089, reversal 5d 0.0072, ridge 0.0070, LightGBM 0.0108 (t 3.1). Decile books lose money after the spread estimate (net Sharpe -0.3 to -1.2) | `validation.json` (`models`) |
| 3. Optimizer (LightGBM scores) | median solve 62 ms (p95 121 ms), 503/503 optimal; turnover 0.83 vs 2.60 for the decile book; net of spread +3.3 bps/day (Sharpe 1.38) vs -5.1 bps/day (-0.91); at a fixed 5 bps both lose (-0.8 and -7.3 bps/day) | `validation.json` (`optimizer`) |
| 3. Transformer (Kaggle GPU, 8.7 min, 71,297 parameters, 3 seeds) | validation IC 0.0082 (t 1.35), turnover 2.85, gross +8.0 bps/day, net of spread -4.2 bps/day (Sharpe -0.49) | `validation.json`, `data/kaggle/out/transformer/meta.json` |
| 3. Registry | LightGBM walk-forward rerun bit-identical (run key `ad1f7ca4370f4bc2`) | `validation.json` (`verify`) |
| 4. Pre-registration | draft committed (`Status: draft`, not stamped); the lock stays closed | `docs/preregistration-platform.md` |
| 5. Nightly loop | ledger, OPG orders, frozen models, live job; fault injection: 500 scenarios, 0 violations | `data/results/fault_injection.json` |
| 5. Dry night on real data | 2026-11-23: 500 members, 4 models, 1,996 predictions, optimized book of 143 stocks (gross 2.0, net 0); design 2.4 s, optimizer 0.6 s | local dry run, 2026-11-24 |
| 6b. Site | new page: account vs SPY, tonight's calls, model leaderboard from the ledger, health; rebuilt by each live run, no commit | `web/` |
| 6a. Trigger | Cloudflare Worker code and setup guide (owner deploys) | `worker/`, [trigger-setup.md](trigger-setup.md) |

## Next
3. Kaggle: Transformer and foundation-model kernels pushed 2026-11-24, still queued; GPU on hold for another
   project (owner's decision). Their scores enter `run_validation.py` from `data/kaggle/out/`.
4. Owner: approve the pre-registration; then set it final, stamp it, commit the proof, run the test once.
5. Owner: TRADING=off, flatten the monthly book, publish the frozen models, merge, deploy the Worker, TRADING=on.
6. Kaggle scores (when the GPU is free) into `run_validation.py`, then the ensemble rule again.

## Known open items
- The index intervals were built on 2026-11-16 from Wikipedia; changes to the index after that date reach the
  research data only when `build_universe.py` runs again. The live loop reads today's members each night.
- `data/raw/` (SEC cache) and the old study files in `data/` are no longer needed except the submissions JSON for
  sectors; the owner decides when to delete them.
