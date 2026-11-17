# Module reference

One section per module in `src/ghostdesk/`. Each public function or class is listed with its contract. Status:
**core** = used by the current pipeline; **ready** = tested, used in a later step. `tests/test_docs.py` fails if a module or a public name is missing here.

---

## ghostdesk/filings/edgar_client.py — SEC access (core)
Fair-access client: declared User-Agent (from `SEC_USER_AGENT` or `.env`), at most `max_per_sec` requests per
second, retries on 429/5xx, disk cache in `data/raw/` keyed by URL hash.

| Name | Contract |
|---|---|
| `user_agent()` | Returns the User-Agent; raises if none is set or it has no contact address. |
| `Filing` | Frozen dataclass: `cik, accession, form, filing_date, report_date, primary_doc, accepted` (UTC string); `.url`. |
| `EdgarClient(ua, cache_dir, max_per_sec=8, session, sleep, clock)` | `.get(url, store=True) -> bytes`: cache first; `store=False` does not write the cache (large pages). `.get_json(url)`. `.network_calls` counter. |
| `tickers_to_ciks(client) -> dict[str, int]` | Today's SEC ticker → CIK map. |
| `list_filings(client, cik, forms, since) -> list[Filing]` | All filings of `forms` since `since`, across all submission pages, newest first, with acceptance time. |
| `download_filing_html(client, filing, store=True) -> str` | Primary document HTML. |

## ghostdesk/filings/filing_index.py — report index (core)
| Name | Contract |
|---|---|
| `index_for(client, cik, since) -> DataFrame` | 10-K, 10-Q and amendments of one CIK (columns of `filings_index.parquet` without `prev_accession`). |
| `frame(rows) -> DataFrame` | Rows → typed index frame (`accepted_utc` UTC). |
| `pair_previous(index, tol_days=20) -> DataFrame` | Adds `prev_accession`: same CIK and base form, period end one year earlier ± `tol_days`, accepted earlier; amendments never paired. |
| `no_future_pairs(index) -> bool` | True if every pair points to an earlier report; keyed by `(cik, accession)` because joint reports share an accession. |

## ghostdesk/filings/xbrl.py — own-period numbers (core)
`ITEMS` maps the four items (`Revenues`, `NetIncomeLoss`, `Assets`, `StockholdersEquity`) to their XBRL concept names.

| Name | Contract |
|---|---|
| `get_instance(client, filing) -> bytes or None` | The instance; inline-XBRL name tried first (filed ≥ 2019-06-15), then the folder index. Never cached. |
| `find_instance(client, filing) -> str or None` | Instance URL from the folder index: `<doc>_htm.xml`, else `<schema>.xml`, else the only non-support `.xml` (rendered `R*.xml` excluded). |
| `parse_instance(xml) -> DataFrame` | Numeric facts: `concept, value, unit, start, end, dims`. |
| `own_period_values(facts, report_date, form) -> dict` | Own-period values only: no dimensions, end = report date ± 3 days, duration ≈ 3 months (10-Q) or 12 (10-K). |
| `first_reported(values) -> DataFrame` | One row per `(cik, item, period_end)`: the earliest accepted report. |
| `as_of(values, t) -> DataFrame` | Latest first-reported value per `(cik, item)` accepted strictly before `t`. |

## ghostdesk/filings/report_sections.py — numbered items (core)
| Name | Contract |
|---|---|
| `ITEM_RE` | Pattern for an item heading at the start of a line (`Item 1A.`, `ITEM 7 -`); `Item 10`-`15` are not read as `Item 1`. |
| `split_sections(text, max_heading=None) -> dict` | `item_1a`, `item_7`, … → section text. Repeated marks of one item (page headers) join into one section; the longest span wins (skips the table of contents). With `max_heading`, a line longer than that is a cross-reference, not a heading. |

## ghostdesk/data/sp500_universe.py — point-in-time S&P 500 with CIKs (core)
| Name | Contract |
|---|---|
| `load_intervals(csv)` | fja05680 CSV → `ticker, start, end` (end NaT = member now). |
| `members_on(intervals, date) -> set` | Tickers with `start <= date < end`. |
| `normalise(name) -> str` | Lower case, SEC state tags and legal suffixes removed, `&` → `and`. |
| `parse_cik_lookup(text)` | SEC `cik-lookup-data.txt` → `name, cik, key`. |
| `changes_table(html_tables)` | Wikipedia changes table → `date, add_ticker, add_name, rem_ticker, rem_name`. |
| `candidates(intervals, current, changes, lookup, sec_tickers)` | Adds `cands` (list of `(cik, source)`) and `keys` (matched names). Sources: `current`, `name`, `prefix`, `sec_ticker`. |
| `names_over_time(submissions) -> list` | `(name, from, to)` from SEC `formerNames` plus the current name. |
| `resolve(cands, has_filings, changes, …, names_at, added)` | One CIK per interval or none: filing check ± 400 days, tie-breaks, then renames with evidence. Adds `cik`, `source`. |
| `add_predecessors(mapped, first_filing, has_filings, names_at, lookup, …)` | Splits an interval at a holding-company change and maps the earlier part to the old CIK (`source = "predecessor"`). |
| `add_valid_from(mapped, first_filing, lead_days=120)` | `valid_from` = max(start, first 10-K/10-Q − 120 days). |
| `coverage(mapped, start, end) -> dict` | Share of member-days with a CIK, counts by source. |
| `price_symbols(mapped, current_tickers) -> Series` | Price symbol per interval: own ticker if still the company's; else a current ticker it used in the index; else a plain current ticker; else its last index ticker; None without a CIK. |

## ghostdesk/data/market_calendar.py — tradeable time (core)
| Name | Contract |
|---|---|
| `opens(sessions) -> DatetimeIndex` | Session dates → 09:30 New York open in UTC (DST handled). |
| `first_open_after(accepted_utc, sessions)` | First open strictly after the time, or None. |

## ghostdesk/data/alpaca_client.py — prices (core)
| Name | Contract |
|---|---|
| `keys() -> dict` | Request headers from env or `.env`; error names missing keys, never values. |
| `AlpacaClient(headers, per_minute=180, session, sleep, clock)` | `.bars(symbols, start, end, timeframe="1Day", adjustment="all", feed="sip") -> DataFrame` (`symbol, t, o, h, l, c, v, n, vw`), all pages; a symbol dropped from a multi-symbol answer is asked for alone. |
| `alpaca_symbol(ticker) -> str` | `BRK-B` → `BRK.B`. |
| `coverage(daily, members, start, end) -> dict` | Share of member-days with a bar; uses `price_symbol` if present. |

## ghostdesk/data/daily_returns.py — clean daily returns (core)
| Name | Contract |
|---|---|
| `daily_returns(adjusted, raw, big=0.3, excess=0.2) -> DataFrame` | Log returns; a day with `abs(adj) > big` and `abs(adj) - abs(raw) > excess` is flagged and its return is NaN. |

## ghostdesk/data/spread_estimate.py — spread from high/low (ready)
| Name | Contract |
|---|---|
| `corwin_schultz(high, low, close=None, floor=True) -> Series` | Two-day estimates; overnight gap removed when `close` is given; `floor=False` keeps negatives. |
| `monthly_spread(high, low, close, dates) -> Series` | Monthly mean of unfloored estimates, then floored at 0 (unbiased within ±0.1 pp in tests). |

## ghostdesk/data/fama_french.py — factor returns (core)
| Name | Contract |
|---|---|
| `MONTH_ROW` | Pattern of a monthly row (`YYYYMM,`) in a French-library CSV. |
| `read_french(path) -> DataFrame` | One CSV zip → monthly table (month-end index), decimals; the annual table is skipped. |
| `load_factors(folder) -> DataFrame` | `Mkt-RF, SMB, HML, RMW, CMA, RF, Mom` from `data/sources/ff/`. |

## ghostdesk/data/industry.py — industry from SIC (core)
| Name | Contract |
|---|---|
| `DIVISIONS` | The standard SIC divisions A-J by 2-digit range. |
| `major_group(sic) -> str` | 2-digit SIC major group (`100` → `01`), or `unknown`. |
| `sic_division(sic) -> str` | The division name, or `unknown`. |
| `industry_groups(sic, min_size=10) -> Series` | Per month: the major group if it has ≥ `min_size` stocks, else the division (Fama-MacBeth dummies). |

## ghostdesk/text_signal/text_similarity.py — change measures (core)
| Name | Contract |
|---|---|
| `words(text)`, `sentences(text)` | Lower-case word list; sentences as normalised word strings. |
| `cosine(a, b)`, `jaccard(a, b)` | As in Cohen, Malloy and Nguyen (2020); NaN for empty text. |
| `edit(a, b)` | 2 × same words / all words; sentence alignment, then word alignment inside changed blocks (≤ 5,000 words). |
| `all_measures(a, b) -> dict` | `{"cosine", "jaccard", "edit"}`. |

## ghostdesk/text_signal/report_features.py — features per report pair (core)
| Name | Contract |
|---|---|
| `prose(html) -> str` | lxml text; number tables removed, layout tables kept; new lines only at block elements; source wraps removed. |
| `parts(html, form) -> dict` | `full`, plus `risk` (Item 1A) and `mdna` (10-K Item 7, 10-Q Item 2) if ≥ 200 words; headings ≤ 160 characters. |
| `pair_features(cur, prev) -> dict` | `sim_<part>_<measure>`, `words_<part>`, `words_<part>_prev`; NaN when a part is missing in either report. |

## ghostdesk/text_signal/stock_month_panel.py — stock-month panel (core)
| Name | Contract |
|---|---|
| `MEASURES` | The nine `sim_<part>_<measure>` columns. |
| `month_ends(sessions)` | Last session of each month. |
| `tradeable_times(accepted_utc, sessions)` | First open strictly after each acceptance time (vectorised `first_open_after`). |
| `close_utc(days)` | 16:00 New York of each day, in UTC. |
| `build_panel(features, members, returns, raw, sic, start, end, window_days=120)` | One row per (month-end, CIK): the signal tradeable at the close (≤ 120 days old), next-month return (missing or flagged days = 0), momentum only over the current interval, log dollar volume, log assets as of formation, SIC, Corwin-Schultz spread, `signal_age`. |

## ghostdesk/evaluation/portfolio_stats.py — statistics (core)
| Name | Contract |
|---|---|
| `FACTORS`, `FULL`, `PRIMARY`, `NEUTRAL` | FF5 + Mom names; the three full-text measures; `composite`; `composite_ind`. |
| `add_signals(panel)` | `<measure>_r` ranks within (month, form); `composite` and `composite_ind` (see the pre-registration). |
| `newey_west(y, x, lags)` | OLS coefficients and Bartlett HAC standard errors (pseudo-inverse). |
| `mean_t(series, lags) -> dict` | `mean`, NW `t`, `n`, `ci95`. |
| `quintiles(panel, measure, n=5)` | Rows with a signal and a return, with `q` (n = most similar) per month. |
| `COST_BPS` | The fixed cost grid (2, 5, 10 bps per unit of weight traded). |
| `portfolio(panel, measure, weighting="equal", n=5) -> dict` | Quintile returns, long-short, weight `traded` per month, nets on the grid, Corwin-Schultz net; `weighting="dv"` for dollar-volume weights. |
| `ic(panel, measure)` | Monthly Spearman IC. |
| `fama_macbeth(panel, measure, lags=3)` | Signal rank + standardised controls + industry dummies; mean coefficients with NW t. |
| `alpha(ls, factors, lags=3)` | FF5 + Mom alpha of a zero-cost return (formation month m earns in m + 1). |
| `summary(panel, measure, factors, lags=3) -> dict` | All of the above, plus Sharpe, minimum detectable effect, break-even bps, signal age. |

## ghostdesk/execution/schedules.py — schedules (ready)
`ACParams` (Almgren-Chriss parameters; `.tau`, `.eta_tilde`), `twap(X, N)`, `vwap(X, volume_profile)`,
`kappa(p, lam)`, `almgren_chriss(X, p, lam)` (holdings; `lam=0` gives TWAP), `expected_cost(x, p)`,
`cost_variance(x, p)`, `mean_variance(x, p, lam)`.

## ghostdesk/execution/impact_simulator.py — simulator (ready)
`ImpactSimulator`: arithmetic Brownian price, linear permanent and power-law temporary impact; `.reset(seed)`,
`.step(n)`. Matches the closed-form Almgren-Chriss cost by Monte Carlo (tests). To be calibrated per stock in Step 4.

## ghostdesk/execution/trading_env.py — Gymnasium environment (ready)
`ExecutionEnv` (sell X shares over N steps, reward = minus implementation shortfall; `.reset`, `.step`),
`run_schedule(env, holdings, seed)`.

## ghostdesk/execution/replay_simulator.py — replay simulator on real minute bars (core)
| Name | Contract |
|---|---|
| `ETA`, `BETA`, `GAMMA` | Almgren, Thum, Hauptmann and Li (2005): temporary 0.142, exponent 0.6, permanent 0.314. |
| `Day` | One stock-day: arrival (first open), per-step price and volume, ADV and daily sigma from the 63 days before. |
| `make_days(minutes, daily, steps=12, minutes_per_step=5)` | Minute bars → `Day` list; ADV and sigma use only earlier days. |
| `shortfall_bps(day, trades, size, half_spread, eta)` | Implementation shortfall of a schedule (sum of `shortfall_part`). |
| `shortfall_part(...)`, `impact_part(...)` | One step's cost with, and without, the market move since arrival. |
| `schedule_trades(weights, size, day)`, `twap_weights(steps)`, `ac_weights(steps, kappa_T)` | Fixed schedules. |
| `volume_profile(days)` | Expected volume share per step and symbol (from earlier days: VWAP). |
| `ReplayEnv(days, profile, sizes, observe_price, half_spread, eta, seed, reward, scale)` | Gymnasium env; action = log multiplier of the TWAP pace (0 = TWAP); `reward="impact"` trains on the order's own cost; `.set_episode(day, size)`. |

## ghostdesk/execution/capacity.py — capacity of the signal strategy (core)
| Name | Contract |
|---|---|
| `monthly_trades(panel, measure, n=5)` | Weight changes per month and stock of the Q5-Q1 portfolio, with dollar ADV and sigma. |
| `cost_fraction(x_dollar, adv_dollar, sigma, ...)` | One day's even trading cost: half-spread + permanent/2 + temporary. |
| `capacity_curve(trades, aums)` | Mean monthly cost (fraction of the fund) per fund size. |
| `break_even(curve, gross_monthly)` | Fund size where cost = gross return; NaN off the curve. |

## ghostdesk/execution/realism_checks.py — realism checks (ready; Step 4b gate)
`acf`, `hill`, `stylised_facts`, `window_stats`, `auc`, `discriminator_score(real, fake, folds, seed)`.

## ghostdesk/execution/ppo_agent.py — PPO (ready)
`PPOConfig`, `mlp`, `ActorCritic` (`.dist`, `.value`, `.act`), `gae(...)`, `PPO` (`.learn(total_steps)`,
`.evaluate(env, episodes, seed)`). Needs the `ml` extra (torch).

## ghostdesk/live/alpaca_broker.py — Alpaca paper trading (core)
Paper endpoint only (`PAPER`; any other base URL raises). Retries 429/5xx; `BrokerError` carries the status and
Alpaca's message. `SNAPSHOTS` is the market-data snapshot URL.

| Name | Contract |
|---|---|
| `Broker(headers, base=PAPER, session, sleep)` | `.clock()`, `.sessions(start, end)` (`date, open_utc, close_utc`), `.account()`, `.positions()` (symbol -> signed shares, float), `.position_rows()`, `.orders(after, status)` (all pages), `.submit(symbol, qty, side, client_order_id)` (day market order, whole shares), `.order(id)`, `.close_all()` (cancel orders, close all positions), `.asset(symbol)`, `.latest_prices(symbols)` (IEX last trade, for sizing only), `.history()` (`day, equity, profit_loss`, equity > 0). |
| `BrokerError` | `status`, `message`. |

## ghostdesk/live/live_signal.py — the live signal (core)
| Name | Contract |
|---|---|
| `WIKI_CURRENT` | Wikipedia page of today's S&P 500. |
| `current_members(html)` | `symbol` (Alpaca form), `cik`, `name`, `sector`. |
| `one_class_per_company(members, dollar_volume)` | One symbol per CIK: the higher dollar volume. |
| `latest_pairs(index, sessions, formation_close_utc, window_days=120)` | Latest original paired report per CIK, tradeable at or before the close and less than 120 days before it; adds `tradeable`. |
| `composite(scores)` | The primary signal for one date (`evaluation.portfolio_stats.add_signals`, ranks within form). |
| `quintile(signal, n=5)` | 1..n (n = least change); NaN with fewer than n values. |

## ghostdesk/live/order_planning.py — targets and VWAP orders (core)
| Name | Contract |
|---|---|
| `FIRST_HOUR_PROFILE`, `BUCKET_MIN` | Mean share of first-hour volume per 5-minute bucket (Step 4 minute bars). |
| `UNIT_FRACTIONAL` | 0.0001 share. |
| `target_shares(sides, prices, equity, leg=1.0, fractional)` | Equal value per stock in each leg; longs in `fractional` to 4 decimals, others whole shares; 0 targets dropped. |
| `too_expensive(sides, target, prices)` | Selected stocks whose whole-share target rounded to 0. |
| `unit_of(symbol, current, target, fractional)` | Order unit: 0.0001 for a fractionable long side, else 1. |
| `per_name_value(sides, equity, leg=1.0)` | Value of one stock's target in the larger leg. |
| `trades(target, current, prices, per_name, min_frac=0.2)` | symbol -> (current, target); closes and flips always, other changes only if worth >= 20% of a target. |
| `learned_profile(minutes, min_days=200)` | (profile, stock-days): first-hour 5-minute volume shares from minute bars; `FIRST_HOUR_PROFILE` with too few days (D16). |
| `buckets_left(minutes_since_open, after_hour=6, profile=FIRST_HOUR_PROFILE)` | (start minute, weight) of the buckets not started; weights sum to 1. |
| `split(qty, weights, unit=1.0)` | Parts in multiples of `unit` with an exact sum. |
| `child_orders(current, target, weights, unit=1.0)` | Signed orders per bucket; no order crosses zero (a flip closes in bucket 0; a new short side is whole shares). |
| `side_of(qty)` | `buy` or `sell`. |

## ghostdesk/live/dashboard_data.py — data of the web page (core)
| Name | Contract |
|---|---|
| `equity_curve(history, spy)` | `day, account, spy` in % from the first day. |
| `report_scores(scores, members, at, days=120)` | Latest scored pair per member with `composite` and `q`. |
| `EXPECTED_MONTH` | Backtest mean and SD of the monthly account return (legs 0.9); the band behind the live curve. |
| `reconcile(target, positions, equity)` | Target vs positions at today's prices: on target (within 20%), missing, extra, value off target in % of equity, gross per side, the 5 worst. |
| `rebalance_summary(log)` | Orders, fills, rejects, cost against the arrival price in bps (positive = paid more). |
| `bucket_shares(log)` | Share of traded shares per bucket of a rebalance. |
| `build(account, positions, history, spy, rebalances, scores, members, health, at, next_rebalance)` | The `live.json` dict. |

## ghostdesk/live/rebalance.py — the trade run (core)
All outside dependencies are injected (`Deps`), so whole runs are tested with a fake broker and clock
(`tests/test_rebalance.py`).

| Name | Contract |
|---|---|
| `Config` | Frozen settings: `leg` 0.9, `window_min` 150, `catchup_sessions` 3, `start`, `min_frac` 0.2, `profile_symbols` 30. Logged in each rebalance record. |
| `Decision` | `trade, ok, reason, catch_up`. |
| `decide(sessions, now, is_open, empty_account, month_done, cfg)` | The gate: due on an empty account, or in the first `catchup_sessions` sessions of a month until a run completes; a due rebalance outside the window is `ok=False`. |
| `formation(sessions, today, members, index, scores)` | Members with their latest pair's features at the last close; count of pairs without features; that close. |
| `select(f, dollar_volume)` | One class per company, `composite`, quintile, sides (+1 / -1 / 0). |
| `Deps` | `broker, now, sleep, dollar_volume, minute_bars, store, log`. |
| `month_done(store, today)` | A rebalance record of the month with a final reconciliation exists. |
| `run_trade(deps, sessions, cfg, dry_run)` | One run: gate, plan, VWAP child orders, fills, reconciliation; returns `(ok, message, extra)`. ok needs 0 rejects and >= 90% of stocks on target. |

## ghostdesk/return_models/stock_features.py — point-in-time characteristics (core)
Each value uses only data known at the formation close (`tests/test_return_models.py` changes every later input and checks
that nothing changes).

| Name | Contract |
|---|---|
| `PRICE` | Price characteristics and their lookback (sessions): `mom_12_1, mom_6_1, rev_1, vol_21, vol_63, beta_252, maxret_21, amihud_63, high_52w, log_price`. A window must lie inside the stock's current index interval. |
| `ACCOUNTING` | `log_assets, roa, turnover, equity_assets, sales_growth, asset_growth`, from the latest report accepted strictly before the close and at most `MAX_REPORT_AGE` (200) days old; 10-Q flows x4. |
| `TEXT` | `composite` (the signal study's text-change rank). |
| `ALL` | The model inputs: `PRICE`, `logdv` (from the panel), `ACCOUNTING`, `TEXT`. |
| `MAX_REPORT_AGE` | 200 days. |
| `price_matrices(returns, raw)` | Session x symbol matrix of each price characteristic, as known at each close. |
| `report_values(features)` | One row per report: first-reported values and its accounting characteristics; growth against the same kind of report 365 +- 20 days earlier. |
| `add_characteristics(panel, members, returns, raw, features)` | The panel with the raw values of `ALL`. |
| `rank_features(panel, cols)` | Cross-sectional rank per month in [-0.5, 0.5]; missing -> 0. |

## ghostdesk/return_models/holdout_lock.py — the test-period lock (core)
| Name | Contract |
|---|---|
| `DEV_END`, `TEST_START`, `TEST_END` | 2021-12-31; 2022-01-01 to 2025-12-31. |
| `PREREG` | `docs/preregistration-ml.md`. |
| `TestPeriodLocked` | Raised when test rows are asked for before the pre-registration is committed. |
| `dev(panel)` | Rows with month <= `DEV_END`. |
| `committed(path)` | The commit that last changed `path`, or None if absent, untracked or changed locally. |
| `unlock(path, check)` | That commit, or `TestPeriodLocked`. |
| `everything(panel, path, check)` | All rows to `TEST_END` and the pre-registration commit (the walk-forward test trains on earlier months). |

## ghostdesk/return_models/walk_forward.py — walk-forward models (core)
| Name | Contract |
|---|---|
| `target(panel)` | Rank of `fwd_ret` within the month, in [-0.5, 0.5]. |
| `ridge(alpha)` | Ridge regression `Fit` (constant not penalised); `RIDGE_ALPHA` 10. |
| `gbm(params, seeds)` | LightGBM `Fit` (native API), averaged over `SEEDS` (0, 1, 2); settings `GBM_BASE` with one entry of `GBM_GRID` (`small`, `base`, `large`). |
| `Fit`, `Predictor` | `fit(x, y) -> predict(x_new)`. |
| `walk_forward(panel, features, fit, first, min_train_months, refit_every)` | Out-of-sample `pred` for each month from `first`; refit every `refit_every` (12) months on all earlier months only; `fit_month` = the first month the model predicted. |

## ghostdesk/return_models/chart_images.py — price-chart images (core)
| Name | Contract |
|---|---|
| `DAYS`, `HEIGHT`, `WIDTH`, `PRICE_ROWS`, `VOLUME_ROWS` | 20 sessions; 64 x 60 pixels; 51 price rows, 1 gap row, 12 volume rows. |
| `matrices(prices, returns)` | Session x symbol matrices of adjusted o, h, l, c, v, the 20-session moving average and `bad` (flag or missing bar). |
| `windows(mats, symbols, end_pos, start_pos)` | Arrays (n, 20) for each window ending on a session, and the mask of valid windows (no bad day, a full moving average, inside the index interval). |
| `draw(arr)` | Images (n, 64, 60) uint8: open tick, high-low bar, close tick per session; moving average; volume bars. |

## ghostdesk/return_models/chart_cnn.py — the chart CNN (core)
| Name | Contract |
|---|---|
| `STEP`, `SEEDS`, `TRAIN` | Training image every 5 sessions; seeds 0, 1, 2; Adam 1e-4, batch 128, at most 5 epochs, patience 2, 30% early-stopping split, channels (16, 32, 64), dropout 0.5. |
| `training_images(mats, members, first, last, label_end, step)` | Images, 0/1 labels (next 20 sessions up) and keys, for members only; every label window ends by `label_end`. |
| `prediction_images(mats, panel, members)` | Images ending on each panel row's formation session, and the mask of rows with one. |
| `net(channels, dropout)` | The network: 3 x (5x3 conv, batch norm, leaky ReLU, 2x1 max pool), dropout, linear to 2 classes. |
| `device()` | Apple GPU (`mps`), else CUDA, else CPU. |
| `fit(images, labels, seed, cfg, log)` | One network with early stopping; returns (model, validation-loss history). |
| `predict(models, images)` | Mean probability of an up move. |
