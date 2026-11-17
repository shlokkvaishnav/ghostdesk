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
- Power: the test could detect, with 80% power, an effect of about 0.56% per month or more.
- No pre-2016 period with the same data (see decision D11), so decay is not measured directly.
- Delisting returns are not known; a day without a price counts as 0.

## How much common backtest mistakes change the result (2016-2021)
See the pitfall table in [status](dev/status.md): for this slow
signal, look-ahead in timing changes little; the stock list (survivorship) and mixing 10-K with 10-Q ranks change
the most.

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
