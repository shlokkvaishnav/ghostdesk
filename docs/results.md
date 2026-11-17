# Results: the signal study

**Short answer.** In S&P 500 stocks after the paper's publication, a portfolio that buys companies whose reports
changed little and sells companies whose reports changed a lot did **not** earn a significant return in the
pre-registered test (2022-2025). The 95% confidence interval for its monthly return after costs is
[-0.36%, +0.54%].
The test had low power, so this result sets an upper limit; it does not prove that there is no effect.

## The test (pre-registered)
The rules were fixed in [the pre-registration](preregistration.md) (commit `e4d66bb`, timestamped with
OpenTimestamps) before any return of 2020-2025 was computed. The test ran once, with code commit
`cce3d21`.

| Hypothesis | Monthly return after 5 bps (t) | 95% CI | p | Holm p |
|---|---|---|---|---|
| H1: composite signal, long-short | +0.09% (0.40) | [-0.36%, +0.54%] | 0.69 | 1.00 |
| H2: the same, industry-neutral | +0.06% (0.53) | [-0.17%, +0.29%] | 0.60 | 1.00 |
| H3: Fama-MacBeth signal with controls | t = -0.65 | | 0.52 | 1.00 |

By the pre-registered reading rules: **not detected.** The build-period estimate (+0.43% per month after costs) is
inside the confidence interval, so the test cannot say that the effect became smaller either.

## All periods (composite signal; not confirmatory except the test row)
| Period | Months | Long-short gross, % (t) | After 5 bps, % (t) | 95% CI after 5 bps | IC (t) | Fama-MacBeth t |
|---|---|---|---|---|---|---|
| Build 2016-2019 | 48 | +0.46 (2.22) | +0.43 (2.06) | [+0.02, +0.83] | 0.020 (1.93) | 0.16 |
| Check 2020-2021 | 24 | -0.35 (-0.65) | -0.38 (-0.71) | [-1.43, +0.67] | 0.012 (0.66) | 1.41 |
| **Test 2022-2025** | 47 | +0.13 (0.55) | +0.09 (0.40) | [-0.36, +0.54] | 0.010 (1.26) | -0.65 |
| Pooled 2016-2025 | 119 | +0.16 (0.94) | +0.13 (0.77) | [-0.21, +0.48] | 0.014 (2.17) | 0.45 |

IC by year: 2016 +0.038, 2017 +0.029, 2018 +0.018, 2019 -0.008, 2020 -0.012, 2021 +0.036, 2022 -0.011, 2023 +0.014, 2024 +0.043, 2025 -0.007.

## What this means
- The effect, if it exists in these stocks after publication, is small: over the full ten years, the upper limit of
  the 95% interval is about 0.5% per month after costs.
- The pooled information coefficient is positive (0.014, t 2.17), but small, and it is not a pre-registered test.
- About half of the 2016-2019 effect was an industry effect, and control regressions found no effect in any period.
- Single measures (cosine, Jaccard, edit; risk factors; MD&A) show the same picture; none is significant in the
  test period after a correction for nine tests.

## Limits
- Large companies only (S&P 500); the paper's effect was stronger in smaller companies.
- Power: the test could detect, with 80% power, an effect of about 0.56% per month or more (with the test
  period's own volatility). The pre-registration planned 0.59% from the build-period volatility; both say the same.
- No pre-2016 period with the same data (see decision D11), so decay is not measured directly.
- Delisting returns are not known; a day without a price counts as 0.

## How much common backtest mistakes change the result (2016-2021)
Each row turns off one guard of the data pipeline and runs the same study again (`composite`, equal-weighted
long-short, gross, before the test period). Source: `scripts/pitfalls.py`.

| Variant | Long-short %/month | t | IC | Change vs baseline (pp) | Stock-months |
|---|---|---|---|---|---|
| baseline | 0.19 | 0.79 | 0.017 | +0.00 | 34,522 |
| filing_date | 0.20 | 0.85 | 0.017 | +0.01 | 34,541 |
| period_end | 0.21 | 0.91 | 0.018 | +0.02 | 34,730 |
| survivors | 0.06 | 0.25 | 0.012 | -0.13 | 26,482 |
| vendor_errors | 0.21 | 0.86 | 0.017 | +0.02 | 34,522 |
| mixed_forms | 0.27 | 1.27 | 0.017 | +0.08 | 34,522 |

- **survivors:** today's stock list instead of the list on each date. This changes the result the most.
- **mixed_forms:** 10-K and 10-Q ranked together instead of like with like.
- **filing_date / period_end:** a report used from its filing date or its period end instead of the SEC acceptance
  time. For a slow monthly signal this changes little.
- **vendor_errors:** price errors of the data vendor kept.

# Results: the execution study

**Short answer.** The PPO agent did **not** trade more cheaply than the best fixed schedule. In 2024 (the test year),
VWAP was the cheapest strategy for each stock group and order size. PPO cost more than VWAP in all 18 cells
(3 seeds × 2 stock groups × 3 order sizes). At 5% of daily volume, the extra cost was about 1 bp (in all seeds,
95% interval above 0). A PPO that cannot see the price did as well as the full PPO, so the agent did not learn to
use price moves. This agrees with decision D12: in this simulator, a fixed schedule that follows the volume
profile is close to the best possible.

## The test
Design fixed in decision D14: replay of real first-hour minute bars (12 × 5 minutes) for 10 large and 10 smaller
stocks, Almgren et al. (2005) impact, orders of 0.1%, 1% and 5% of average daily volume. Train 2023, test 2024
(252 days). Each number is the paired difference against the best fixed schedule (TWAP, VWAP, Almgren-Chriss), with
a 95% interval clustered by day. 600,000 training steps per seed.

| Stocks | Size (% of daily volume) | VWAP cost (bps) | PPO − VWAP, mean of 3 seeds (bps) | Per seed | Price-blind PPO − VWAP (bps) | Seeds with 95% interval above 0 (PPO / blind) |
|---|---|---|---|---|---|---|
| Large | 0.1 | 1.80 | +0.48 | +0.23, +0.81, +0.40 | +0.45 | 0 / 0 |
| Large | 1 | 6.63 | +0.15 | +0.15, +0.22, +0.08 | +0.11 | 0 / 0 |
| Large | 5 | 17.91 | +0.98 | +0.71, +1.27, +0.97 | +0.93 | 3 / 3 |
| Smaller | 0.1 | 2.33 | +1.03 | +0.28, +1.89, +0.93 | +0.73 | 0 / 0 |
| Smaller | 1 | 7.35 | +0.28 | +0.27, +0.33, +0.25 | +0.16 | 1 / 0 |
| Smaller | 5 | 18.69 | +1.13 | +0.73, +1.18, +1.48 | +1.15 | 3 / 3 |

No seed, group or size has an agent significantly cheaper than VWAP. Source: `scripts/execution_summary.py`.

## A process error, reported
The first PPO version was evaluated on 2024 directly. It was also worse than VWAP (all stocks, 5% of volume:
+1.24 bps, 95% interval [+0.70, +1.78]). After that, design changes were chosen on a validation split inside 2023
only, and 2024 was used once more for the final runs above (decision D14). Both results show the same thing.

## Capacity of the signal strategy
With the impact model above and the signal's trades in 2016-2025, the trading cost equals the pooled gross return
(0.16% per month) at a fund of about **$7.2 billion**. At the upper end of the pooled 95% interval, the break-even
size is about $30 billion. The signal itself was not detected in the test period, so these sizes are limits, not
a claim that the strategy earns money.

## Limits
- One impact model; the cost level changes with its parameters (at half or double the impact coefficient, VWAP is
  still the cheapest fixed schedule at 1% and 5% of volume), but no real fills were measured.
- First hour only, 20 stocks, one test year.
- The simulator does not model the effect of the agent's orders on later prices beyond the impact model.

# Results: the ML study

**Short answer.** A LightGBM model of 18 point-in-time characteristics, retrained each January on all earlier
months, did **not** rank next month's S&P 500 returns in the pre-registered test (2022-2025). Its long-short return
after costs was -0.11% per month (95% CI [-0.72%, +0.49%]) and its mean IC was 0.000. It did better than a ridge
model of the same inputs, but not significantly.

## The test
Rules fixed in [the ML pre-registration](preregistration-ml.md) (commit `e41120d`, OpenTimestamps proof
`preregistration-ml.md.ots`). The code gave the models no month after 2021 until that file was committed
(`ml/split.py`). Run once on 2026-11-18. Formation months 2022-01 to 2025-11 (47), Newey-West t (3 lags).

| ID | Hypothesis | Estimate | t | 95% CI | Holm p |
|---|---|---|---|---|---|
| **M1 (primary)** | GBM long-short after 5 bps > 0 | -0.11%/month | -0.36 | [-0.72%, +0.49%] | 1.00 |
| M2 | GBM mean IC > 0 | +0.000 | 0.03 | [-0.026, +0.027] | 1.00 |
| M3 | GBM IC - linear IC > 0 | +0.012 | 1.33 | [-0.006, +0.029] | 0.55 |

Not confirmatory: ridge long-short -0.34%/month after 5 bps (IC -0.011); GBM turnover 2.05 per month; GBM FF5 +
momentum alpha after 5 bps -0.19%/month (t -1.07); GBM IC by year 2022 -0.009, 2023 +0.020, 2024 -0.002,
2025 -0.007. In the same harness, plain 12-1 momentum had a gross long-short of +0.73%/month (IC +0.025).

## What this means
- The minimum detectable effect was about 1.3% per month (pre-registration, section 7), so the test can exclude only
  large effects. The CI excludes a GBM edge above about 0.5% per month after costs.
- In 2016-2021 (about 30,000 training rows) the model learned patterns that did not hold after 2021. A tree model
  can mix many weak signals, but it cannot make a signal that is not in the data.
- The model trades its whole book about once a month (turnover 2.05 of 2 legs), so even a small edge must pay
  about 10 bps a month in costs.

## Limits
- Large companies only; 18 characteristics (no market value or book-to-market: no share counts in the data); a
  short training history (from 2016).
- One tree setting, chosen on 2020-2021 from three.
