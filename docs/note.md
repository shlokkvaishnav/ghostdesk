# Research note: how much do backtest mistakes matter? A case study with "lazy prices"

**One-line summary.** With data that has no look-ahead and no survivorship bias, the "lazy prices" signal
(Cohen, Malloy and Nguyen 2020) was not found in S&P 500 stocks in a pre-registered test (2022-2025). Of the
common backtest mistakes, the wrong stock list moves the result the most; errors in report timing move it little.

## 1. Question
Many public replications of trading signals use today's stock list, report filing dates instead of the exact
release time, and numbers that companies later restated. How much does each mistake change the answer? We use one
published signal as the test case and measure each mistake by turning one guard off at a time.

## 2. Data (point in time)
- **Stocks:** the S&P 500 as it was on each date, 2016-2025, with the companies that later left it, mapped to SEC
  CIKs with evidence (96.8% of member-days mapped).
- **Reports:** 47,719 10-K and 10-Q reports with the SEC acceptance time. A report counts from the first market open
  strictly after that time.
- **Signal:** text change of each report against the same report a year before (10-K with 10-K, Q2 with Q2):
  cosine, Jaccard and edit similarity of the full text; `composite` = their mean rank within form.
- **Prices:** Alpaca daily bars with vendor errors removed.

## 3. Test
Rules fixed before any 2020-2025 return was computed ([pre-registration](preregistration.md), commit `e4d66bb`,
OpenTimestamps proof). Monthly long-short: buy the 20% least-changed, sell the 20% most-changed, equal weights.

| Period | Long-short after 5 bps, %/month | 95% CI |
|---|---|---|
| Build 2016-2019 | +0.43 | [+0.02, +0.83] |
| **Test 2022-2025 (pre-registered)** | **+0.09** | **[-0.36, +0.54]** |
| Pooled 2016-2025 | +0.13 | [-0.21, +0.48] |

The test could detect an effect of about 0.56% per month with 80% power. The result therefore sets an upper limit
(about 0.5% per month); it does not prove that the effect is zero. A small effect after publication agrees with
the average decay of published signals (McLean and Pontiff 2016).

## 4. The cost of each mistake (2016-2021, before the test period)
| Mistake (guard turned off) | Long-short %/month | Change (pp) |
|---|---|---|
| none (baseline) | 0.19 | 0.00 |
| report used from its filing date | 0.20 | +0.01 |
| report used from its period end (look-ahead) | 0.21 | +0.02 |
| **today's stock list (survivorship)** | **0.06** | **-0.13** |
| vendor price errors kept | 0.21 | +0.02 |
| 10-K and 10-Q ranked together | 0.27 | +0.08 |

For a slow monthly signal, timing errors of days to weeks change little. The stock list changes the estimate by
about two thirds of its size, and mixing report types adds a false +0.08 pp. A replication that uses today's
stock list measures a different portfolio.

## 5. Can the signal be traded?
- **Execution:** on replayed real minute bars, a reinforcement-learning agent (PPO) did not beat a VWAP schedule
  at any order size; at 5% of daily volume it cost about 1 bp more ([results](results.md)).
- **Capacity:** at the pooled gross return, trading costs use up the return at a fund of about $7.2 billion.
- **Live:** the same rules trade a paper account each month since 2026-11-17 ([engineering](engineering.md)).
  This is a test of the system, not evidence for the signal: one rebalance a month gives about 12 results a year.

## 6. Limits
Large companies only (the original paper found a stronger effect in smaller companies); one signal; the pitfall
table covers 2016-2021 only, without a confidence interval for each change; paper fills are simulated by Alpaca.

## References
Cohen, L., Malloy, C. and Nguyen, Q. (2020). Lazy Prices. *Journal of Finance* 75(3).
McLean, R. D. and Pontiff, J. (2016). Does Academic Research Destroy Stock Return Predictability? *Journal of
Finance* 71(1).
Almgren, R., Thum, C., Hauptmann, E. and Li, H. (2005). Direct Estimation of Equity Market Impact. *Risk* 18(7).
