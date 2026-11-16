# Status and next work

Updated 2026-11-16. Steps follow [docs/plan.md](../plan.md).

## Done
| Step | Result | Evidence |
|---|---|---|
| 1. Repo | Tested parts copied in; CI and docs green | commits `3c13a3c`… |
| 2a. Universe | 96.8% of 2010-2025 member-days mapped to a CIK | `universe_coverage.json`, [data.md](../data.md) |
| 2b. Report index | 47,719 reports, all with acceptance time; 92.6% paired | `filings_index_summary.json` |
| 2c. Text features + XBRL | 30,514 pairs, 765 CIKs, 44 errors | `features_summary.json`, run 43854092158 |
| 2d. Prices and returns | 98.0% of 2016-2025 member-days with a bar; 8 vendor-error days removed | `prices_coverage.json` |
| 2e. Spread estimate | Corwin-Schultz, ±0.1 pp in simulation | `tests/test_spread_similarity.py` |

## Step 3 — the signal study (in progress)
| Item | State |
|---|---|
| Panel builder `signal/panel.py`, statistics `signal/study.py` | done, tested |
| Build period 2016-2019 | done: `composite` long-short 0.46%/month gross (t 2.22), 0.43% net of 5 bps (t 2.06); industry-neutral t 1.36; Fama-MacBeth t 0.16 |
| Outside review of the research value | done (2026-11-16); accepted changes are in decisions D9-D10 |
| Pre-registration `docs/preregistration.md` | written; committed before any 2020-2025 return was computed |
| Check period 2020-2021 | done (after the pre-registration commit `e4d66bb`): `composite` long-short -0.35%/month (t -0.65, 95% CI [-1.40%, 0.70%]); IC 0.012 (t 0.66); Fama-MacBeth t 1.41. Uninformative (high 2020 volatility). Build IC by year falls from 0.038 (2016) to -0.008 (2019). |
| Test period 2022-2025 | **wait**: run once, only after the owner decides on the open questions below |

## Open questions for the owner (they can change the pre-registration)
1. **Pre-publication comparison.** The review's top suggestion: run the same pipeline on 2010-2015 (before the
   paper) to measure decay after publication. Needs a second price source for 2010-2015 (reverses D3).
2. **Role of the RL execution study.** The review: in a square-root-impact simulator with no predictive state,
   Almgren-Chriss is near-optimal, so PPO can at best match it. Proposed: present it as a short sanity check, and
   use the impact model for a capacity analysis (break-even assets under management) instead.
3. **External timestamp of the pre-registration** (OSF or AsPredicted needs an account; OpenTimestamps needs none
   and publishes only a hash).

## Next after the test
- **Step 3b — pitfall-bias table** (review's second suggestion): rerun the study with one guard off at a time
  (filing date instead of acceptance time; ticker instead of CIK; today's constituents; companyfacts-style latest
  values; vendor spin-off days kept) and report how much each moves the IC and the Sharpe ratio.

## Later
- Step 4 — execution study: calibrate `execution/impact.py` per stock (daily volatility and volume from
  `prices_daily.parquet`, spread from `data/spread.py`); PPO vs TWAP/VWAP/Almgren-Chriss at 0.1%, 1%, 5% of daily
  volume; main chart: RL gain by order size. Needs minute bars (Alpaca, a sample of stocks).
- Step 4b — optional world model behind the gates of decision D2.
- Step 5 — live job and site: daily GitHub Actions job, Alpaca paper orders over 30-60 min after the open, site from
  JSON with `deploy-pages`, no commit, no failure emails.
- Step 6 — research note, one-page summary, filing-diff visual, `make figures`.

## Known open items
- data-quality F7 (MD&A in Exhibit 13), F8 (revenue concept names): not blocking.
- 44 feature errors (network): can be retried with `extract_features.py --ciks ...`.
