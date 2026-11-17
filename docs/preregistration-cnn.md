# Pre-registration: the chart-CNN study

Written 2026-11-18, after the development runs (train 2016-2019, predict 2020-2021) and **before** any CNN
prediction or return for the test period (2022-2025) was computed. `scripts/cnn_study.py --period test` refuses to
run until this file is committed with no local change (`ml/split.py`). The commit, its GitHub push time and an
OpenTimestamps proof are the record. Any later change goes in the deviation log.

## 1. Question
Does a CNN that sees only a picture of a stock's last 20 sessions (prices and volume; Jiang, Kelly and Xiu 2023)
rank the next month's returns of S&P 500 stocks out of sample in 2022-2025, after costs?

## 2. Data and images (fixed; `ml/charts.py`)
- Point-in-time S&P 500 members, as in the signal study. Alpaca daily bars, split- and dividend-adjusted.
- Image: 64 x 60 pixels, 20 sessions, open / high-low / close per session, 20-session moving average, volume bars;
  scaled within the image. No image if the window has a missing bar, a flagged vendor-error day or a day before
  the stock's current index interval.

## 3. Model and training (fixed; `ml/cnn.py`)
- Label: the next 20 sessions' adjusted return > 0.
- Training images: every 5th session from 2016-01 to 2021-12, index members only, with every label window ending
  by 2021-12-31.
- Network: 3 x (5x3 convolution, batch norm, leaky ReLU 0.01, 2x1 max pool) with 16, 32, 64 channels, dropout 0.5,
  linear layer to 2 classes; Xavier initialisation.
- Fit: cross-entropy, Adam (learning rate 1e-4), batch 128, a random 30% of training images for early stopping
  (patience 2, at most 5 epochs). Seeds 0, 1 and 2, one network each; the prediction is the mean probability of an
  up move.
- One fit for the whole test (no refit), the same as the development design.

## 4. Portfolio (fixed)
Each month-end from 2022-01 to 2025-11 (47 months): quintiles of the prediction among panel stocks with an image
and a next-month return; long Q5 (highest probability of an up move), short Q1; equal weights; held one month;
costs 5 bps per unit of weight traded.

## 5. Hypotheses and tests (fixed)
Newey-West t-statistics with 3 lags; 5%, two-sided.

| ID | Hypothesis | Statistic |
|---|---|---|
| **C1 (primary)** | The CNN long-short return after 5 bps has a mean above 0. | mean, NW t, 95% CI |
| C2 | The mean monthly IC (Spearman) of the CNN prediction is above 0. | mean, NW t |

C1 is the only confirmatory test; C2 is reported with a Holm-adjusted p-value over {C1, C2}.
**Reported without a claim:** gross and 2/10 bps returns, turnover, break-even cost, quintile means, FF5 + momentum
alpha, IC by year, and the correlation of the CNN prediction with `rev_1` and `mom_12_1` (does it only rediscover
reversal or momentum?).

## 6. Development results and power (before the test)
Train 2016-2019 (92,019 images, 58.4% up), predict 2020-2021 (24 months), 3 seeds:

| | Value |
|---|---|
| Long-short after 5 bps | +0.09%/month (t 0.29) |
| Long-short gross | +0.25%/month (t 0.81) |
| IC | +0.006 (t 0.43) |
| Turnover | 3.23 per month (of a maximum of 4) |
| Validation loss | 0.672-0.678; the loss of always predicting 58.4% "up" is 0.679 |

The networks learned little beyond the base rate. With a monthly standard deviation of 1.63%, the minimum
detectable effect over 47 months (80% power) is about **0.67% per month**. The high turnover costs about 16 bps a
month at 5 bps per trade.

## 7. What the author knew before the test
The signal-study and ML-study test results for 2022-2025 (both not detected), the single-characteristic results in
the ML harness for 2022-2025 (for example 12-1 momentum +0.73%/month gross), and the market history. The CNN
design follows the published paper with smaller sizes set for compute before any run; no setting was changed after
the development results.

## Deviation log
(none)
