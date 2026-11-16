# Pre-registration: the signal study

Written 2026-11-16, after the build-period analysis (2016-2019) and **before** any return of the check period
(2020-2021) or the test period (2022-2025) was computed. The commit that adds this file, and its push time on
GitHub, are the record. Any later change is listed in the deviation log at the end, with its reason and date, and
the test-period script refuses to run on an uncommitted or changed version of this file.

## 1. Question
Do US large-cap companies whose 10-K or 10-Q text changed little since the comparable earlier report earn higher
returns in the next month than companies whose text changed a lot ("lazy prices", Cohen, Malloy and Nguyen 2020),
after the paper's publication, with no look-ahead and no survivorship bias?

## 2. Data (fixed; see docs/data.md and docs/dev/data-contracts.md)
- Universe: S&P 500 members at each month-end, with a confirmed SEC CIK and a price symbol (`signal.panel`).
- Reports: original 10-K and 10-Q filings, each paired with the same form for the same period one year earlier.
- Timing: a report is usable from the first NYSE open after its SEC acceptance time; formation is at the close of
  the last session of each month; a signal is used for at most 120 days.
- Returns: Alpaca daily bars (all exchanges), adjusted; vendor corporate-action errors removed; a day without a bar
  counts as 0.
- Factors: Kenneth French library, monthly FF5 (2x3) and momentum, file version of 2026-10 (CRSP 202609).

## 3. Signal (fixed)
- For each report pair: cosine, Jaccard and edit similarity of the full text, tables removed
  (`signal.features`, `signal.similarity`).
- Each measure is ranked within (month, form). **Primary signal `composite`** = mean of the three ranks, re-ranked
  within (month, form). High = little change.
- Industry-neutral signal `composite_ind` = `composite` ranked within (month, form, SIC division).

## 4. Portfolio (fixed)
Monthly. Quintiles of the signal among stocks with a signal and a next-month return. Long Q5 (least change), short
Q1 (most change), equal weights in each leg, rebalanced at each month-end, held one month. A stock that leaves the
index during the month is held to the month-end.

## 5. Hypotheses and tests (fixed)
Test period: formation months 2022-01 to 2025-11 (returns 2022-02 to 2025-12), 47 months. All t-statistics use
Newey-West standard errors with 3 lags. Significance level 5%, two-sided.

| ID | Hypothesis | Statistic |
|---|---|---|
| **H1 (primary)** | The long-short return of `composite`, after a cost of 5 bps per unit of weight traded, has a mean above 0. | mean, NW t, 95% CI |
| H2 | The same for `composite_ind` (industry-neutral). | mean, NW t, 95% CI |
| H3 | In monthly Fama-MacBeth regressions of next-month return on the `composite` rank, standardised log dollar volume, log total assets, 12-1 momentum and industry dummies, the mean signal coefficient is above 0. | mean, NW t |

H1 is the only confirmatory test. H2 and H3 are reported with their p-values, adjusted by Holm over {H1, H2, H3}.

**Reported without a confirmatory claim:** the IC and IC by year; net returns at 2 and 10 bps and with
Corwin-Schultz half-spreads; break-even cost; dollar-volume-weighted long-short; FF5 + momentum alpha (gross and
net of 5 bps); each single measure (cosine, Jaccard, edit; full, risk factors, MD&A), with Holm-adjusted p-values
over the nine; the check period 2020-2021; the pooled period 2016-2025 (119 months).

## 6. Power (computed on build data, before the test)
In 2016-2019, the `composite` long-short had a mean of 0.46% per month and a standard deviation of 1.45% per month
(gross; annual Sharpe 1.10).

| Sample | Months | Standard error | Minimum detectable effect (80% power) | Power if the build effect holds | Power if it halved |
|---|---|---|---|---|---|
| Test 2022-2025 | 47 | 0.21% | 0.59% per month | 0.58 | 0.19 |
| Pooled 2016-2025 | 119 | 0.13% | 0.37% per month | 0.93 | 0.41 |

A non-significant test result is therefore likely even if the effect exists. It will be reported as an upper bound
(the 95% CI), not as "no effect".

## 7. How results will be read (fixed)
- H1 significant and positive: "the effect is present in S&P 500 stocks after publication, after 5 bps costs".
- H1 not significant: "not detected; the 95% CI for the monthly long-short return is [a, b]"; with the build
  estimate inside the CI, "consistent with the pre-publication size"; with it above the CI, "smaller than in
  2016-2019".
- H1 significant and negative: reported as a reversal.
- In all cases, H2 tells whether the result survives industry neutrality; the build period already showed that
  about half of the raw effect is industry-related (H2 build t = 1.36 vs H1 t = 2.22).

## 8. Known facts from the build period (seen before this file was written)
- `composite` gross 0.46%/month (t 2.22), net of 5 bps 0.43% (t 2.06), IC 0.020 (t 1.93), break-even 78 bps.
- `composite_ind` gross 0.25% (t 1.36). Fama-MacBeth signal t 0.16 with controls.
- Raw similarity (not ranked within form) mixed 10-Ks and 10-Qs (Q1 had 11% 10-Ks, Q5 37%); this is why the
  signal is ranked within form. The composite was chosen so that no single measure is picked on the data.
- The signal window was changed from 92 to 120 days after an outside review (92 days misses the Q3-to-10-K gap).

## 9. Command
```bash
make check
PYTHONPATH=src .venv/bin/python -u scripts/signal_study.py --period check
PYTHONPATH=src .venv/bin/python -u scripts/signal_study.py --period test --prereg <commit of this file>
```
The test command runs once. Its output (`data/results_test.json`) is published as it is.

## Deviation log
| Date | Change | Reason |
|---|---|---|
| — | — | — |
