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
| reversal_1d | 0.00887 | 0.269 |
| reversal_5d | 0.00718 | 0.217 |
| ridge | 0.00702 | 0.213 |
| lightgbm | 0.00996 | 0.302 |

The Transformer now has validation scores (Kaggle, 2026-11-24): IC 0.00817 (t 1.35), registry run `107d03dbbd2c2ec4`.
It does not run every night yet, so it is not in the table. Zero-shot validation (2021-2022, before every
cutoff): Chronos-2 IC -0.00081, TimesFM-2.5 IC -0.00154 (weight 0 by the rule); Kronos-small has no validation
scores (it failed with CUDA out of memory on Kaggle); 7 models have validation scores. If the Transformer or a foundation model has validation scores and can run every night before this file is final,
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
| kronos_small | 2024-06-30 | verified in the paper's text (arXiv:2508.02739v1, Appendix D, "Task Implementation Details" > "Forecasting Task Setup"): "The pre-training data for Kronos extends up to June 2024. Consequently, our test period for all tasks begins in July 2024" |
| chronos2 | 2025-10-17 (arXiv:2510.15821 v1, submitted 17 Oct 2025) | no date cutoff in the paper (full text searched: no "cutoff", "stock" or "financ"). Sec. 4.1 uses "select datasets from the Chronos ... and GIFT-Eval ... pretraining corpora"; Table 6 ("Real univariate datasets used for pretraining Chronos-2") lists 23 datasets in energy, nature, transport, web, cloud ops and M4 ("Various"; M4 includes finance series, but no stock-price dataset is named). The GIFT-Eval pretraining part is not itemized: unverified |
| timesfm25 | 2025-09-15 (release; GitHub README "Update - Sept. 15, 2025 TimesFM 2.5 is out!") | model card "Data": GiftEvalPretrain; "Wikimedia Pageviews, cutoff Nov 2023"; "Google Trends top queries, cutoff EoY 2022"; "Synthetic and augmented data". No overall cutoff; the GiftEvalPretrain part is undated: unverified |

Where no cutoff is stated, the release date is used: nothing after it can be in the training data. Checked on
2026-11-24 against the papers' HTML text and the model cards. Moirai-2 is not used.

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
