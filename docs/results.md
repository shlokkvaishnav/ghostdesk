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
