# Status and next work

Updated 2026-11-17. Steps follow [docs/plan.md](../plan.md).

## Done
| Step | Result | Evidence |
|---|---|---|
| 1. Repo | Tested parts copied in; CI and docs green | commits `3c13a3c`… |
| 2a. Universe | 96.8% of 2010-2025 member-days mapped to a CIK | `universe_coverage.json`, [data.md](../data.md) |
| 2b. Report index | 47,719 reports, all with acceptance time; 92.6% paired | `filings_index_summary.json` |
| 2c. Text features + XBRL | 30,514 pairs, 765 CIKs, 44 errors | `features_summary.json`, run 43854092158 |
| 2d. Prices and returns | 98.0% of 2016-2025 member-days with a bar; 8 vendor-error days removed | `prices_coverage.json` |
| 2e. Spread estimate | Corwin-Schultz, ±0.1 pp in simulation | `tests/test_spread_similarity.py` |

## Step 3 — the signal study (done)
| Item | State |
|---|---|
| Panel builder `signal/panel.py`, statistics `signal/study.py` | done, tested |
| Build period 2016-2019 | done: `composite` long-short 0.46%/month gross (t 2.22), 0.43% net of 5 bps (t 2.06); industry-neutral t 1.36; Fama-MacBeth t 0.16 |
| Outside review of the research value | done (2026-11-16); accepted changes are in decisions D9-D10 |
| Pre-registration `docs/preregistration.md` | written; committed before any 2020-2025 return was computed |
| Check period 2020-2021 | done (after the pre-registration commit `e4d66bb`): `composite` long-short -0.35%/month (t -0.65, 95% CI [-1.40%, 0.70%]); IC 0.012 (t 0.66); Fama-MacBeth t 1.41. Uninformative (high 2020 volatility). Build IC by year falls from 0.038 (2016) to -0.008 (2019). |
| Test period 2022-2025 | **done once** (code `cce3d21`): H1 +0.09%/month after 5 bps (t 0.40, 95% CI [-0.36%, +0.54%]); not detected. See [results](../results.md). |

## Step 4 — the execution study (done)
| Item | State |
|---|---|
| Replay simulator `execution/replay.py`, capacity `execution/capacity.py` | done, tested |
| Validation (2023-10..12) and design changes | done (decision D14) |
| Test 2024, 3 seeds | **done**: PPO is not cheaper than VWAP in any cell; at 5% of volume it costs about 1 bp more (all seeds significant). Price-blind PPO is the same. See [results](../results.md#results-the-execution-study). |
| Capacity | break-even fund about $7.2B at the pooled gross return |

## Decisions on the review (owner: "do what is better")
- Pre-2016 comparison: not with free data (D11). RL study reframed (D12). External timestamp done (D13).

## Pitfall-bias table (2016-2021 only; `scripts/pitfalls.py`, `data/pitfalls.json`)
Primary signal, equal-weighted long-short, gross. Each row turns one guard off.

| Variant | Long-short %/month | t | IC | Change vs baseline (pp) | Stock-months |
|---|---|---|---|---|---|
| baseline | 0.19 | 0.79 | 0.017 | +0.00 | 34,522 |
| filing_date | 0.20 | 0.85 | 0.017 | +0.01 | 34,541 |
| period_end | 0.21 | 0.91 | 0.018 | +0.02 | 34,730 |
| survivors | 0.06 | 0.25 | 0.012 | -0.13 | 26,482 |
| vendor_errors | 0.21 | 0.86 | 0.017 | +0.02 | 34,522 |
| mixed_forms | 0.27 | 1.27 | 0.017 | +0.08 | 34,522 |

Reading: for this slow signal, timing look-ahead changes little (even a report "known" at its period end); the stock
list (survivorship) and mixing 10-K with 10-Q ranks change the most.

## Later

- Step 4b — optional world model behind the gates of decision D2.
- Step 5 — live job and site: daily GitHub Actions job, Alpaca paper orders over 30-60 min after the open, site from
  JSON with `deploy-pages`, no commit, no failure emails.
- Step 6 — research note, one-page summary, filing-diff visual, `make figures`.

## Known open items
- data-quality F7 (MD&A in Exhibit 13), F8 (revenue concept names): not blocking.
- 44 feature errors (network): can be retried with `extract_features.py --ciks ...`.
