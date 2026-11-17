# Decision log

One entry per choice between real alternatives. Format: context, decision, consequences. Newest last; never edit
the decision of an old entry — add a new entry that replaces it.

### D1 — One project, three parts (2026-11-15)
- **Context:** three separate repos (filings Q&A, execution RL, Bitcoin options) did not form a whole; an outside
  quant review found that a slow filing signal and minute-level RL do not combine into P&L at a small order size.
- **Decision:** one US-stocks project. The filing signal is the research result; RL execution is a separate study
  of cost against order size; live paper trading is the engineering result. Static GitHub Pages only, no servers.
- **Consequences:** the old repos were deleted; the tested parts were copied in. The Q&A code (claim verifier,
  retrieval chunks) was removed on 2026-11-16 because the plan does not use it.

### D2 — Learned world model only behind gates (2026-11-15)
- **Decision:** a learned market simulator is tried only after Step 4, and kept only if it passes three gates
  written before the try: realistic (stylised-fact ratios in [2/3, 3/2], discriminator AUC < 0.80 on held-out
  days), useful (PPO trained with it beats PPO without it on real held-out days, 95% interval below 0), and cheap.
- **Consequences:** `execution/realism_checks.py` is kept for the gate; the old Bitcoin world model was removed (in git
  history).

### D3 — Study period 2016-2025 (2026-11-16, owner's choice)
- **Context:** Alpaca's free history starts in 2016; reports start in 2009.
- **Alternatives:** (a) build on 2016-2019 with one price source; (b) add a second free daily source for 2010-2015
  (needs delisted companies, and a join at 2016).
- **Decision:** (a). Build 2016-2019, check 2020-2021, test 2022-2025 once.
- **Consequences:** 4 build years, not 10, so build-period estimates are less certain. Reports of 2010-2015 are
  kept as the earlier report of the first pairs.

### D4 — Point-in-time anchor is the SEC acceptance time (2026-11-15)
- **Decision:** a report is tradeable at the first NYSE open strictly after `acceptanceDateTime` (verified to be
  UTC against the EDGAR index header). Numbers come from each report's own XBRL, first reported value only.
- **Rejected:** filing date (one day too coarse; after-hours reports), companyfacts API (holds restated values).

### D5 — Universe identity by CIK with evidence, never guessed (2026-11-16)
- **Decision:** each membership interval is mapped to a CIK only with evidence (filing check, names with dates,
  "Date added", SEC name changes). Ambiguous intervals stay unmapped and are counted.
- **Consequences:** 96.8% of 2010-2025 member-days mapped; the 3.2% lost is concentrated in 2010-2015 and is
  not random (bought or failed companies). Results are reported by year.

### D6 — Long SEC jobs on GitHub Actions, not the owner's Mac (2026-11-16)
- **Alternatives:** local run (about 4 h, not allowed), Kaggle CPU (secret set in its UI), GitHub Actions.
- **Decision:** GitHub Actions, 6 shards sharing 7.8 requests/s, manual start, inputs from a private release,
  outputs as private artifacts, no failing steps.
- **Consequences:** about 1,300 of the 2,000 free private minutes per month per full run.

### D7 — Text measures: CMN baselines first; sentence-then-word edit similarity (2026-11-16)
- **Decision:** cosine, Jaccard and edit similarity on the full text (primary) and on risk factors and MD&A
  (secondary). The edit measure aligns sentences, then words inside changed blocks, because a word-level diff of
  two 50,000-word reports is too slow. Embedding similarity is a later variant only.

### D8 — Prices follow the company; vendor errors are removed, not repaired (2026-11-16)
- **Decision:** prices by the company's current symbol (Alpaca stores history under it); intervals without a
  confirmed CIK get no prices. Spin-off days that the vendor adjusts as splits get a NaN return.
- **Rejected:** repairing those days from corporate-action data (more sources, few days: 8 in 10 years).

### D9 — Signal ranked within form; composite of three measures (2026-11-16)
- **Context:** in 2016-2019, raw similarity ranks mixed forms (the most-changed quintile was 11% 10-Ks, the least
  changed 37%), because a 10-Q changes more from year to year than a 10-K. An outside review found the same risk.
- **Decision:** each measure is ranked within (month, form); the primary signal is the mean of the three full-text
  ranks. No single measure is chosen on the data (cosine was the strongest in the build period).
- **Consequences:** fixed in `docs/preregistration.md`.

### D10 — Costs on a fixed grid; window 120 days (2026-11-16)
- **Context:** the outside review: Corwin-Schultz is too noisy at large-cap spreads; a 92-day signal window misses
  the gap between a Q3 10-Q and the next 10-K.
- **Decision:** net returns at 2, 5 (primary) and 10 bps per unit of weight traded; Corwin-Schultz as a secondary
  estimate. Signal window 120 days, with `signal_age` recorded. Dollar-volume-weighted returns as a check.
- **Rejected for now:** the review's other changes (pre-2016 comparison, LLM measures, demoting the RL study,
  external timestamp) need the owner's decision; they are listed in status.md.

### D11 — No pre-2016 comparison with free data (2026-11-16)
- **Context:** the outside review's first suggestion was a pre-publication period (2010-2015) to measure decay.
- **Check:** the only large free source (Kaggle "Huge Stock Market Dataset") is a 2017 snapshot. It has no company
  that stopped trading before late 2017: 10.0% of 2010-2015 member-days, exactly the bought and failed companies.
- **Decision:** not used; a biased pre-period would carry the bias that this project exists to remove. Decay is
  addressed by the trend inside 2016-2025 and a comparison with the published estimates; a clean pre-2016 test
  needs CRSP (future work).

### D12 — The RL execution study is a test of what PPO learns, not a claim that it wins (2026-11-16)
- **Context:** in a square-root-impact simulator whose prices are a martingale, Almgren-Chriss is near-optimal, so
  PPO can at best match it (outside review).
- **Decision:** keep the study (an agent that learns to trade is a goal of the project), but give the simulator real
  intraday volume and spread profiles from minute bars and ask: does PPO learn them, and match the best fixed
  schedules (VWAP, Almgren-Chriss) at each order size? Add a capacity analysis: the assets under management at which
  the impact cost of the signal's turnover equals its gross return.
- **Rejected:** a headline of "RL beats Almgren-Chriss" (not true in this model).

### D13 — Pre-registration timestamped outside git (2026-11-16)
- **Decision:** OpenTimestamps proof `docs/preregistration.md.ots` (only the SHA-256 hash leaves the machine; no
  account), in addition to the GitHub push time of commit `e4d66bb`. Verify with `ots verify
  docs/preregistration.md.ots` after the Bitcoin confirmation (`ots upgrade` completes the proof).
- The proof is for the file as committed in `e4d66bb` (SHA-256 `b32c95a4…9a17`). The deviation log was added after
  the test, so verify that version: `git show e4d66bb:docs/preregistration.md > /tmp/p.md && ots verify -f /tmp/p.md
  docs/preregistration.md.ots`.

### D14 — Execution study design; a validation split after an early look at 2024 (2026-11-16)
- **Design (fixed before results):** replay of real first-hour minute bars (12 x 5 minutes), Almgren et al. (2005)
  impact, sizes 0.1/1/5% of ADV, 10 large and 10 smaller stocks, train 2023, test 2024, paired differences
  against the best fixed schedule with day-clustered intervals.
- **Process error and fix:** the first PPO version was evaluated directly on 2024 (PPO worse than VWAP at all
  sizes; kept in `data/execution_results_test_v1.json` and reported). Later design changes were chosen on a
  validation split inside 2023 only; 2024 was then used once more for the final run (3 seeds).
- **Changes from validation:** training reward = the order's own cost (`reward="impact"`; the market move is
  noise of about 50 bps per hour against impact differences of about 1 bp), reward scaled by order size, and a
  smaller initial exploration noise (log std -1). The action is a log multiplier of the TWAP pace.

### D15 — Live paper trading design (2026-11-17)
- **Strategy:** the pre-registered portfolio, unchanged: `composite` of the latest paired report (tradeable at or
  before the formation close, at most 120 days old), quintiles across the current S&P 500 (Wikipedia list, with
  its CIK column), long Q5 and short Q1, equal weights, rebalanced on the first session of each month. Each leg is
  90% of account equity (gross 1.8x, inside the account's 2x margin). Longs use fractional shares (4 decimals);
  shorts use whole shares (Alpaca does not allow fractional short sales), so a short whose target rounds to 0
  shares is left out and listed (`too_expensive` in the rebalance log); hard-to-borrow stocks are left out of the
  short leg and listed (`not_shortable`). Changed on 2026-11-17, before the first trade: the first version used
  50% legs and whole shares for longs too, and a dry run dropped 6 of 198 stocks and gave 1-3-share positions. One exception: the first run, on an empty account,
  enters at once (formation = the last close), so that the forward test starts without a wait of two weeks.
- **Execution:** VWAP, the best schedule in the execution study (Step 4). Child market orders in the 5-minute
  buckets of the first hour, sized by the pooled first-hour volume profile of the Step 4 minute bars
  (`live.order_planning.FIRST_HOUR_PROFILE`). A job that starts late uses the buckets that are left; after the first
  hour it uses 6 buckets of 5 minutes. A long-to-short flip is closed in the first bucket and opened over the rest
  (Alpaca rejects an order that crosses zero).
- **State:** Alpaca is the record of trades (orders, positions, portfolio history). Report scores are kept in an
  Actions cache (`data/live/scores.parquet`); if the cache is lost, the job computes the scores again from SEC
  (about 500 report pairs). A run trades only the difference between target and position (a difference below
  20% of the per-stock target is not traded). A later run on the same day does nothing if the plan is empty and
  never overwrites the first run's record (`rebalance_<date>.json`); if it finishes leftover trades, it writes
  `rebalance_<date>_<HHMM>.json` and uses order IDs with its own start time (amended 2026-11-17 after review).
- **Broker limits:** at most 170 requests a minute from the client (Alpaca allows 200); 429 and 5xx answers are
  retried for about 2 minutes; only a 4xx rejection stops a stock for the rest of the run.
- **Schedule (UTC):** `score+site` at 21:40 and again at 23:40 each weekday (after the close). `trade` every 20
  minutes from 13:05 to 16:45 each weekday (changed on 2026-11-17: on the first trade day GitHub started none of
  the three timed runs at 13:40, 14:40, 15:40, and the trade was dispatched by hand at 14:47; more runs make a
  dropped run harmless, and a rerun trades nothing);
  the script trades only on the first session of a month (or on an empty account), and only between the open and
  150 minutes after it, so the two time zones of New York (EST, EDT) need no change. Other runs stop in seconds.
- **Stop:** repository variable `TRADING=off` stops every new order (the page shows "trading is off"); the mode
  `flatten` closes all positions and cancels open orders, also when trading is off.
- **Silent:** every step has `continue-on-error`; the result and any error go to `live.json`, shown on the site.
- **Site:** one workflow builds the whole Pages site: the product page at the root (from `live.json`) and the
  mkdocs pages under `/docs/`. The old `docs.yml` is removed, so two workflows never overwrite each other.
- **Rejected:** daily rebalancing (not the tested strategy); commits of state to git (rule: no commit from jobs);
  waiting inside a job for the open (Actions minutes of a private repository).

### D16 — The only adaptive part: the VWAP volume profile (2026-11-17)
- **Context:** the owner asked that the desk "learn from its trades". The signal is pre-registered; changing it
  from live results means tuning on about 12 noisy monthly results a year. Paper fills are simulated by Alpaca,
  so learning from the desk's own fills would learn the simulator, not the market.
- **Decision:** the signal and portfolio rules stay fixed. Before each rebalance the desk learns the first-hour
  volume profile (12 buckets of 5 minutes) from the last 20 sessions of real SIP minute bars of its 30 largest
  trades (`live.order_planning.learned_profile`), and uses it for the VWAP child orders. With fewer than 200
  stock-days, or if the bars cannot be read, it uses the Step 4 profile. The profile is kept in the rebalance log
  and shown on the page.
- **Rejected:** re-training PPO on live fills (simulated fills; PPO lost to VWAP in Step 4); changing the signal.

### D17 — The trade run as a tested library; catch-up and reconciliation (2026-11-17)
- **Context:** the engineering review (2026-11-17) found that the trade orchestration in `scripts/live_desk.py` had no
  tests, that a missed window was reported as healthy and skipped a whole month, and that nothing checked the book
  after a run.
- **Decision:** `live.rebalance` holds the run with injected broker, clock, data and store; `scripts/live_desk.py` only
  wires the real ones. A rebalance is due in the first 3 sessions of a month until a run completes; "completes"
  means its record has the final reconciliation, so a run that died half way is finished by the next run. A due
  rebalance outside the window is an error on the page. A run is ok only with 0 rejected orders and at least 90%
  of the stocks within 20% of their target value.
- **Tests:** a month-start day, a rerun the same day (no orders, record unchanged), a missed window and its
  catch-up, a run killed half way and its completion (no order-ID clash), an empty account mid-month, the gate.
- **Parity with the study (`tests/test_parity.py`, local data):** for four month-ends (2017, 2019, 2023, 2025)
  the live code picks the same report and gives the same `composite` and quintile as the study panel. The test
  found one difference: the study breaks quintile ties by dollar-volume order, the live code broke them by symbol
  order (78 tied values in one month). Fixed in `rebalance.select`. The first rebalance (2026-11-17) ran with the old
  tie-break, so a few stocks at a quintile border may differ from the tested rule in that month only.

### D18 — An ML model of the cross-section, built as one harness (2026-11-18)
- **Context:** the lazy-prices signal was not detected in 2022-2025. The owner asked for ML-finance methods that
  learn which stocks to trade. The model must learn from the history of all stocks, not from the desk's own ~12
  trades a year, and it must not use the test period to choose anything.
- **Decision:** one pipeline for every model: point-in-time characteristics (`return_models/stock_features.py`: 10 price, 1
  size, 6 accounting, 1 text), ranked within the month; walk-forward fits on all earlier months, refit each
  January; the same evaluation as the signal study (`evaluation.portfolio_stats.summary`: equal-weighted quintile long-short,
  costs, IC, Fama-MacBeth, alpha). Models: ridge (baseline) and LightGBM (Gu, Kelly and Xiu 2020). The code
  locks months after 2021 until `docs/preregistration-ml.md` is committed (`return_models/holdout_lock.py`).
- **Selection (check period only):** of `GBM_GRID`, the setting with the highest mean IC in 2020-2021 is the one
  tested. Development results (predictions 2019-2021) are in `data/ml_dev.json`.
- **Not used:** market value and book-to-market (no share counts in the data); a neural network (the 2016-2021
  sample, about 30,000 training rows by 2022, is small for one); hyperparameter search on more than three settings.
- **Order of the other methods:** the price-chart CNN (Jiang, Kelly and Xiu 2023), time-safe text embeddings, and
  risk engineering come after this, through the same harness.

### D19 — The chart CNN, in the same harness (2026-11-18)
- **Context:** the owner asked for a model that "reads the charts". Jiang, Kelly and Xiu (2023) trained a CNN on
  price-chart images (1993-2019, all US stocks) and found strong out-of-sample results; later tests in large stocks
  after 2020 are few.
- **Decision:** their I20/R20 design (20-session OHLC + moving average + volume image, up/down label for the next
  20 sessions), smaller: 16-32-64 channels (a quarter of the paper's), about 92,000 training images (every 5th
  session, index members only), at most 5 epochs. One fit, no yearly refit: dev trains on 2016-2019 and predicts
  2020-2021; the test trains on 2016-2021 and predicts 2022-2025. Three seeds, averaged. The prediction (probability
  of an up month) goes through `evaluation.portfolio_stats.summary` like every other model.
- **Compute:** about 1.2 ms per training image on the Apple GPU (M-series, `mps`), 3x faster than the CPU; one seed
  per run was meant to keep each run under 10 minutes (hard rule 7). The development runs took 4-6 min; the test
  runs (142,103 images) took 8, 14 and 8 min, so one broke the rule. A later CNN run goes to Kaggle or Actions.
- **Lock:** `docs/preregistration-cnn.md` must be committed before `--period test` runs (`return_models/holdout_lock.py`).

### D20 — Clear names for packages, modules and scripts (2026-11-18)
- **Context:** the owner asked for a cleaner, more professional layout: short names such as `ml/`, `cnn.py`,
  `split.py`, `runner.py` or `study.py` do not say what the code does.
- **Decision:** packages and modules are named after what they hold (`text_signal/`, `evaluation/`,
  `return_models/`; `holdout_lock.py`, `walk_forward.py`, `rebalance.py`, ...); scripts are grouped into
  `scripts/data/` (build data files) and `scripts/studies/` (run a study), with `scripts/live_desk.py` for the live
  job; test files follow their module. Imports inside the package are absolute. `tests/test_smoke.py` now checks
  every `ghostdesk` import of every script, which the rename showed was untested.
- **Records not changed:** the pre-registrations keep the names they were written with (they are timestamped
  records); every other document uses the new names. Map:

| Before | After (`src/ghostdesk/`) |
|---|---|
| `data/alpaca.py` | `data/alpaca_client.py` |
| `data/calendar.py` | `data/market_calendar.py` |
| `data/universe.py` | `data/sp500_universe.py` |
| `data/returns.py` | `data/daily_returns.py` |
| `data/spread.py` | `data/spread_estimate.py` |
| `data/factors.py` | `data/fama_french.py` |
| `filings/edgar.py` | `filings/edgar_client.py` |
| `filings/index.py` | `filings/filing_index.py` |
| `filings/sections.py` | `filings/report_sections.py` |
| `signal/similarity.py` | `text_signal/text_similarity.py` |
| `signal/features.py` | `text_signal/report_features.py` |
| `signal/panel.py` | `text_signal/stock_month_panel.py` |
| `signal/study.py` | `evaluation/portfolio_stats.py` |
| `execution/benchmarks.py` | `execution/schedules.py` |
| `execution/impact.py` | `execution/impact_simulator.py` |
| `execution/replay.py` | `execution/replay_simulator.py` |
| `execution/env.py` | `execution/trading_env.py` |
| `execution/realism.py` | `execution/realism_checks.py` |
| `rl/ppo.py` | `execution/ppo_agent.py` |
| `live/broker.py` | `live/alpaca_broker.py` |
| `live/signal.py` | `live/live_signal.py` |
| `live/portfolio.py` | `live/order_planning.py` |
| `live/runner.py` | `live/rebalance.py` |
| `live/site.py` | `live/dashboard_data.py` |
| `ml/characteristics.py` | `return_models/stock_features.py` |
| `ml/split.py` | `return_models/holdout_lock.py` |
| `ml/models.py` | `return_models/walk_forward.py` |
| `ml/charts.py` | `return_models/chart_images.py` |
| `ml/cnn.py` | `return_models/chart_cnn.py` |

| Before | After |
|---|---|
| `scripts/build_universe.py` | `scripts/data/build_universe.py` |
| `scripts/build_filings_index.py` | `scripts/data/build_filing_index.py` |
| `scripts/load_prices.py` | `scripts/data/load_prices.py` |
| `scripts/load_minutes.py` | `scripts/data/load_minute_bars.py` |
| `scripts/extract_features.py` | `scripts/data/extract_text_features.py` |
| `scripts/collect_features.py` | `scripts/data/merge_feature_shards.py` |
| `scripts/signal_study.py` | `scripts/studies/run_signal_study.py` |
| `scripts/pitfalls.py` | `scripts/studies/run_pitfall_table.py` |
| `scripts/execution_study.py` | `scripts/studies/run_execution_study.py` |
| `scripts/execution_summary.py` | `scripts/studies/summarize_execution_study.py` |
| `scripts/capacity.py` | `scripts/studies/run_capacity.py` |
| `scripts/ml_study.py` | `scripts/studies/run_ml_study.py` |
| `scripts/cnn_study.py` | `scripts/studies/run_cnn_study.py` |
| `scripts/live.py` | `scripts/live_desk.py` |

### D21 — Remove code that no study or job uses (2026-11-18)
- **Removed:** `execution/impact_simulator.py` and `execution/trading_env.py` (the first parametric simulator and
  its Gymnasium environment; the execution study used the replay simulator on real minute bars instead),
  `execution/realism_checks.py` (the gate for a learned world model, decision D2, which was never built), their
  tests, and `docs/plan.md` (the first plan; the results, note and status pages now describe the project).
  They stay in git history.
- **Kept:** every module that a study, the live job or a test of a used module needs.

### D22 — Risk monitoring of the live book; no text-embedding study (2026-11-18)
- **Risk (done):** each site run measures the book from one year of adjusted daily bars: expected yearly volatility
  with a Ledoit-Wolf shrinkage covariance, beta to SPY, net and gross weight per sector, and the largest position
  (`live/book_risk.py`, on the page). It describes the book and changes no weight: changing the portfolio would
  change the pre-registered strategy. On 2026-11-17 the book had 7.3% expected yearly volatility, beta -0.16, and a
  net long of 27% in Financials (similar reports from banks rank as "little change").
- **Text embeddings (not done):** a fair test needs a language model trained only on text before each date (for
  example ChronoBERT, one model per year) and hours of compute for about 30,000 long report pairs, off the owner's
  Mac. The word-count version of the signal showed no effect in the test period and the test power is low, so one
  more test would add little. It is left as future work.
