# Pre-registration: the ML study

Written 2026-11-18, after the development runs on formation months up to 2021 and **before** any ML prediction or
return for the test period (2022-2025) was computed. The code refuses to give the model any month after 2021 until
this file is committed with no local change (`ml/split.py`). The commit that adds this file, its GitHub push time
and an OpenTimestamps proof are the record. Any later change goes in the deviation log at the end.

## 1. Question
Does a gradient-boosted tree model of standard point-in-time stock characteristics, retrained each year on all
earlier months, rank the next month's returns of S&P 500 stocks out of sample in 2022-2025, after costs, and better
than a linear model of the same inputs?

## 2. Data (fixed)
The same as the signal study ([pre-registration](preregistration.md), section 2): point-in-time S&P 500 members
with a CIK and a price symbol, one row per company and month-end (`data/panel_pooled.parquet`), formation at the
close of the last session of the month, next-month returns from clean daily bars.

## 3. Inputs (fixed): 18 characteristics (`ml/characteristics.py`)
- Price (10): `mom_12_1, mom_6_1, rev_1, vol_21, vol_63, beta_252, maxret_21, amihud_63, high_52w, log_price`.
- Size (1): `logdv`. Accounting (6): `log_assets, roa, turnover, equity_assets, sales_growth, asset_growth`.
  Text (1): `composite`.
- Every input uses only data known at the formation close; each is ranked within the month to [-0.5, 0.5], with a
  missing value at 0.

## 4. Models (fixed)
- Target: the rank of the next-month return within the month, in [-0.5, 0.5].
- **GBM (tested):** LightGBM regression, `learning_rate` 0.02, `n_estimators` 500, `num_leaves` 31,
  `min_child_samples` 200, `subsample` 0.8 (every iteration), `colsample_bytree` 0.8, `reg_lambda` 1.0; the mean of
  seeds 0, 1 and 2. This is `GBM_BASE` with `GBM_GRID["large"]`, chosen from three settings by the highest mean IC
  in the check period 2020-2021 (development predictions: IC -0.004 for `large`, -0.006 `base`, -0.013 `small`).
- **Linear (baseline):** ridge regression, alpha 10, with a constant.
- Walk-forward: refit each January (2022, 2023, 2024, 2025) on all months before it, from 2016; each model predicts
  the 12 months from its fit. No model sees a month that it predicts.

## 5. Portfolio (fixed)
As in the signal study: quintiles of the prediction each month, long Q5 (highest prediction), short Q1, equal
weights, held one month; costs 5 bps per unit of weight traded.

## 6. Hypotheses and tests (fixed)
Test period: formation months 2022-01 to 2025-11 (47 months). Newey-West t-statistics with 3 lags; 5%, two-sided.

| ID | Hypothesis | Statistic |
|---|---|---|
| **M1 (primary)** | The GBM long-short return after 5 bps has a mean above 0. | mean, NW t, 95% CI |
| M2 | The mean monthly IC (Spearman) of the GBM prediction is above 0. | mean, NW t |
| M3 | The GBM IC minus the linear IC (paired by month) has a mean above 0. | mean, NW t |

M1 is the only confirmatory test; M2 and M3 are reported with Holm-adjusted p-values over {M1, M2, M3}.
**Reported without a claim:** the linear model's results, gross and 2/10 bps returns, turnover, break-even cost,
dollar-volume-weighted long-short, FF5 + momentum alpha, IC by year, and the single characteristics in the same
harness.

## 7. Development results and power (formation months 2019-2021, before the test)
| Model | Long-short after 5 bps, %/month | IC | Turnover per month |
|---|---|---|---|
| Linear | +0.24 (t 0.39) | +0.010 | 2.10 |
| GBM (`large`) | +0.29 (t 0.49) | +0.023 | 2.27 |

2019 was positive for every model (GBM IC +0.076), 2020-2021 near zero. The GBM long-short had a standard
deviation of 3.28% per month, so with 47 test months the **minimum detectable effect (80% power) is about 1.3% per
month**, and for the IC about 0.06. Published ML results in large stocks are smaller than this, so a
non-significant result is likely even if a real effect exists; it will be reported as an upper bound.

## 8. What the author knew before the test
The author had seen the signal study's test result (`composite`, 2022-2025, not detected) and knows the market
history of 2022-2025. The 18 characteristics are standard published ones (Gu, Kelly and Xiu 2020), fixed before
any ML number for 2022-2025; none was added or removed after the development runs.

## Deviation log
(none)
