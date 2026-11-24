# Pre-registration: next-day prediction on the S&P 500, test 2023-01 to 2026-10

Status: draft

This file fixes the rules of the one test run before any test-period label is computed. The code keeps the test
locked until this file says `Status: final` (on its own line), is committed with no local change, and its
OpenTimestamps proof (`preregistration-platform.md.ots`) is committed (`research/holdout_lock.py`). This draft
does not open the lock. The owner approves the final version.

## 1. Data
- Stocks: the S&P 500 as it was on each session (`data/universe.parquet`, `data/price_symbols.parquet`), with the
  companies that later left it.
- Prices: the point-in-time store (`data/store/`), adjusted daily bars from Alpaca (SIP feed), read as known on
  the run date. Sectors: SIC groups (`data/sectors.parquet`).
- Splits: train 2016-01-01 to 2020-12-31, validation 2021-01-01 to 2022-12-31, **test 2023-01-01 to
  2026-10-31**. Sessions after 2026-10-31 belong to the forward window (the live ledger), not to this test.

## 2. Target
For a prediction made after the close of session t: the log return from the open of t+1 to the open of t+2, minus
beta x SPY's return over the same window (beta from the 252 sessions through t), minus the mean of these residuals
over the stock's sector on that session (`research.dataset.residual_label`). A label that touches a vendor
corporate-action error is missing.

## 3. Models (fixed; nothing is tuned on the test)
| Model | Definition |
|---|---|
| reversal_1d | minus the 1-day log return through the close of t |
| reversal_5d | minus the 5-day log return |
| ridge | ridge regression (alpha 100) on the 158 Alpha158 factors, ranked across stocks each session |
| lightgbm | LightGBM, 300 rounds, settings in `research/models.py:LightGBM` (deterministic) |
| transformer | 2-layer Transformer from scratch, `kaggle/transformer/kernel.py`, mean of 3 seeds |
| chronos2, timesfm25, kronos_small | zero-shot, `kaggle/foundation/kernel.py`, no fine-tuning |

Walk-forward: yearly folds; the model for year Y is fitted on all sessions before Y minus a 2-session purge (ridge,
LightGBM). The Transformer is trained once on sessions to 2022-12 (early stopping on the last 6 months of its
training data) for the test years. Foundation models are not trained.

## 4. Ensemble (traded live)
The rank average of the models that run every night, with weights proportional to each model's positive
validation IC (2021-2022, `data/results/validation.json`). With the four local models (validated 2026-11-24):

| Model | Validation IC | Weight |
|---|---|---|
| reversal_1d | 0.00887 | 0.262 |
| reversal_5d | 0.00718 | 0.212 |
| ridge | 0.00702 | 0.207 |
| lightgbm | 0.01084 | 0.320 |

If the Transformer or a foundation model has validation scores and can run every night before this file is final,
it joins by the same rule and the table is recomputed. **Open for the owner:** whether to wait for the Kaggle
results (GPU on hold) before finalizing.

## 5. Portfolios and costs
- Decile book: equal weights, long the top 10% and short the bottom 10% of members by score, traded at the next
  open, held to the open after.
- Optimized book (ensemble and the best single model by validation IC): `research/optimizer.py` with `OptConfig()`
  as committed (12 PCA factors, 2% cap, sectors within ±5%, beta within ±1%, gross 2, IC 0.02, 2 bps).
- Costs: half the Corwin-Schultz spread per unit traded (primary), and 0, 1, 2, 5, 10 bps (grid).

## 6. Reported numbers (every model, all of them reported, none dropped)
Mean daily rank IC with its t-statistic (Newey-West, 5 lags), hit rate, turnover, gross and net daily return and
Sharpe for the decile book; the same for the optimized books. For each foundation model, the test is split into the
sessions before and after its pretraining-data cutoff:

| Model | Cutoff used | Source |
|---|---|---|
| kronos_small | 2024-06-30 | Kronos paper (arXiv:2508.02739): pretraining data to June 2024, test from July 2024 (to be checked against the paper's text before final) |
| chronos2 | 2025-10-31 (end of its release month; arXiv:2510.15821, October 2025; exact day to be checked) | no data cutoff stated; the model card lists Chronos and GIFT-Eval datasets and synthetic data |
| timesfm25 | 2025-09-15 (release) | no overall cutoff stated; listed sources end Nov 2023 (Wikimedia) and 2022 (Trends) |

Where no cutoff is stated, the release date is used: nothing after it can be in the training data.

## 7. Hypotheses and decision rule
- H1: the ensemble's mean daily rank IC on the test is above 0 (one-sided, 5%).
- H2: the optimized ensemble book's mean daily return net of the spread estimate is above 0 (one-sided, 5%).
- H3: each foundation model's IC after its cutoff is above 0; its pre- and post-cutoff ICs are both reported.
- Expected from earlier work: daily IC 0.01-0.03, net Sharpe about 0-1 (Rahimikia et al. arXiv:2511.18578 found
  time-series foundation models weak on daily stock returns before costs; arXiv:2611.12141 found them null on
  index futures). A null result is reported in the same way as a positive one.

## 8. Procedure
1. The owner approves this file; it is set to `Status: final`, committed, stamped (`ots stamp`), and the `.ots`
   proof is committed.
2. `scripts/research/run_test.py` (to be written; it calls `research_end(include_test=True)`) runs once and writes
   `data/results/test.json`; its run keys go to the registry.
3. Any later change of code or rules is a new, separately labelled analysis; it does not replace this test.
