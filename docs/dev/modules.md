# Module reference

One section per module in `src/ghostdesk/`. Each public function or class is listed with its contract.
`tests/test_docs.py` fails if a module or a public name is missing here.

---

## ghostdesk/paths.py — repository paths
| Name | Contract |
|---|---|
| `REPO_ROOT` | The repository root. |
| `DATA_DIR` | `data/` under the root, or the `GHOSTDESK_DATA` environment variable (a worktree reads the main checkout's data). |

## ghostdesk/data/store.py — point-in-time price store (core, D26)
Parquet batches under `data/store/bars/<adj|raw>/`, read with DuckDB. A read keeps the newest version of each
`(symbol, day)` with `ingested_at <= asof`.

| Name | Contract |
|---|---|
| `FIELDS` | `o, h, l, c, v, n, vw`. |
| `NY` | `America/New_York`. |
| `session_day(t)` | Bar timestamps (UTC) → New York session dates (naive). |
| `bars_to_rows(bars, ingested_at)` | Alpaca bars → store rows `symbol, day, FIELDS, ingested_at`. |
| `PriceStore(root)` | `.batches(kind)`, `.write_batch(kind, rows, name)` (refuses to overwrite), `.read(kind, start, end, asof, symbols)` (long rows, newest version known at `asof`), `.last_day(kind)`, `.content_hash(kind)` (SHA-256 of all batches). |
| `matrices(rows, fields, days, symbols)` | Long rows → one session × symbol matrix per field (NaN where no bar). |
| `membership(intervals, days, symbols)` | Session × symbol bool: in the S&P 500 (`start <= day < end`) by `price_symbol`. |
| `add_symbols(store, fetch, symbols, first_day, end, now)` | Whole history of symbols new to the store (an index addition), as one batch. |
| `ingest_daily(store, fetch, symbols, today, now, overlap_days=10, first_day)` | Appends new sessions (raw and adjusted) as one batch; a symbol whose overlap closes changed (new dividend or split) gets its whole adjusted history again. Returns `new_rows, refetched, batch`. |

## ghostdesk/data/edgar_client.py — SEC access (core: stock list and sectors only)
Fair-access client: declared User-Agent (from `SEC_USER_AGENT` or `.env`), at most `max_per_sec` requests per
second, retries on 429/5xx, disk cache in `data/raw/` keyed by URL hash.

| Name | Contract |
|---|---|
| `user_agent()` | Returns the User-Agent; raises if none is set or it has no contact address. |
| `Filing` | Frozen dataclass: `cik, accession, form, filing_date, report_date, primary_doc, accepted` (UTC string); `.url`. |
| `EdgarClient(ua, cache_dir, max_per_sec=8, session, sleep, clock)` | `.get(url, store=True) -> bytes`: cache first; `store=False` does not write the cache (large pages). `.get_json(url)`. `.network_calls` counter. |
| `tickers_to_ciks(client) -> dict[str, int]` | Today's SEC ticker → CIK map. |
| `list_filings(client, cik, forms, since) -> list[Filing]` | All filings of `forms` since `since`, across all submission pages, newest first, with acceptance time. |

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

## ghostdesk/data/industry.py — industry from SIC (core)
| Name | Contract |
|---|---|
| `DIVISIONS` | The standard SIC divisions A-J by 2-digit range. |
| `major_group(sic) -> str` | 2-digit SIC major group (`100` → `01`), or `unknown`. |
| `sic_division(sic) -> str` | The division name, or `unknown`. |
| `industry_groups(sic, min_size=10) -> Series` | Per month: the major group if it has ≥ `min_size` stocks, else the division (Fama-MacBeth dummies). |

## ghostdesk/live/alpaca_broker.py — Alpaca paper trading (core)
Paper endpoint only (`PAPER`; any other base URL raises). Retries 429/5xx; `BrokerError` carries the status and
Alpaca's message. `SNAPSHOTS` is the market-data snapshot URL.

| Name | Contract |
|---|---|
| `Broker(headers, base=PAPER, session, sleep)` | `.clock()`, `.sessions(start, end)` (`date, open_utc, close_utc`), `.account()`, `.positions()` (symbol -> signed shares, float), `.position_rows()`, `.orders(after, status)` (all pages), `.submit(symbol, qty, side, client_order_id, time_in_force="day")` (market order; `opg` = market on open, whole shares), `.order(id)`, `.close_all()` (cancel orders, close all positions), `.asset(symbol)`, `.latest_prices(symbols)` (IEX last trade, for sizing only), `.history()` (`day, equity, profit_loss`, equity > 0). |
| `BrokerError` | `status`, `message`. |

## ghostdesk/live/book_risk.py — risk of the live book (core)
Describes the book each day; it does not change the pre-registered portfolio (decision D22).

| Name | Contract |
|---|---|
| `WINDOW`, `MIN_DAYS`, `YEAR` | 252 daily returns; a stock needs 120 to enter the covariance; 252 days a year. |
| `ledoit_wolf(x)` | Ledoit-Wolf (2004) shrinkage of the sample covariance toward a scaled identity; returns (covariance, intensity). |
| `book_risk(values, equity, returns, spy, sectors)` | `vol_annual, beta_spy, gross, net, largest, sectors` (net and gross per sector), `shrinkage, stocks, stocks_without_history, days`. |

## ghostdesk/live/members.py — today's members (core)
| Name | Contract |
|---|---|
| `WIKI_CURRENT` | The Wikipedia page of current S&P 500 members. |
| `current_members(html)` | The table → `symbol` (Alpaca form), `cik`, `name`, `sector`. |
| `one_class_per_company(members, dollar_volume)` | One symbol per CIK: the one with the highest dollar volume. |

## ghostdesk/live/order_planning.py — whole-share targets and orders (core)
| Name | Contract |
|---|---|
| `target_shares_from_weights(weights, prices, equity)` | Signed weights → whole shares; 0-share and unpriced stocks left out. |
| `orders_for(current, target)` | Signed orders that never cross zero (a flip = close, then open). |
| `trades(target, current, prices, per_name, min_frac=0.2)` | Changes worth trading; closes and flips always. |
| `side_of(qty)` | `buy` or `sell`. |

## ghostdesk/live/dashboard_data.py — page pieces (core)
| Name | Contract |
|---|---|
| `reconcile(target, positions, equity)` | Target vs positions at today's prices: on target (within 20%), missing, extra, value off target in % of equity, gross per side, the 5 worst. |
| `equity_curve(history, spy)` | `day, account, spy` in % from the first day. |

## ghostdesk/research/holdout_lock.py — the test-period lock (core, D27)
| Name | Contract |
|---|---|
| `TRAIN_START`, `TRAIN_END`, `VAL_START`, `VAL_END`, `TEST_START`, `TEST_END` | 2016-2020 train, 2021-2022 validation, 2023-01 to 2026-10 test. |
| `PREREG`, `FINAL` | `docs/preregistration-platform.md`; the line `Status: final`. |
| `TestPeriodLocked` | Raised when test sessions are asked for while the lock is closed. |
| `committed(path)` | The commit that last changed `path`, or None if absent, untracked or changed locally. |
| `final_and_stamped(path, check)` | The commit if the file says `Status: final` and its `.ots` is committed; else None. |
| `unlock(path, check)` | That commit, or `TestPeriodLocked`. |
| `research_end(include_test, path, check)` | `(VAL_END, None)`, or `(TEST_END, commit)` when the lock opens. |
| `guard(days, include_test, path, check)` | Raises if `days` reach past the research end. |

## ghostdesk/features/expr.py — the expression language (core, D28)
| Name | Contract |
|---|---|
| `FIELDS` | `open, high, low, close, volume, vwap`. |
| `SIGNATURES` | Function name → (expression arguments, numeric parameters). |
| `BINARY`, `COMMUTATIVE` | Operator → node name; nodes whose arguments are sorted in the canonical form. |
| `TOKEN` | The token pattern. |
| `ExprError` | Syntax error, unknown name, wrong arguments, or a negative `Ref` lag. |
| `Node` | Frozen `op, args, params`. |
| `tokenize(text)`, `parse(text)` | Text → tokens → AST. `Rank(x)` is cross-sectional; `Rank(x, d)` is in time. |
| `canonical(node)` | Unique string of a tree (commutative arguments sorted); memoized. |
| `subexpressions(node)` | All nodes, children first. |
| `lookback(node)` | Sessions of history needed before the first value. |

## ghostdesk/features/ops.py — numpy kernels (core)
Look-back only; a window needs all `d` values. Running sums for sums, means, variances, regressions and
correlations (each column shifted by a constant first); strided window views for max, min, quantile, rank, arg-max.
A constant window has variance exactly 0.

| Name | Contract |
|---|---|
| `EPS_DDOF` | 1 (sample variance, as pandas). |
| `ref(x, d)`, `delta(x, d)` | Lag (refuses d < 0); difference. |
| `tsum`, `mean`, `var`, `std` | Rolling sum, mean, sample variance, standard deviation. |
| `slope`, `rsquare`, `resi` | Least squares on t = 1..d: slope, R² (NaN for a constant window), last value minus its fit. |
| `cov`, `corr` | Rolling covariance and correlation (NaN when a side is constant). |
| `tmax`, `tmin`, `quantile(x, d, q)` | Rolling max, min, linear-interpolated quantile. |
| `trank` | Percentile rank of the last value in its window (average ties), as pandas `rank(pct=True)`. |
| `idxmax`, `idxmin` | 1-based position of the window max or min from the oldest row. |
| `ema(x, d)` | Exponential mean, alpha = 2/(d+1). |
| `cs_rank`, `cs_zscore` | Cross-sectional percentile rank and z-score per row. |

## ghostdesk/features/engine.py — compile, reuse, cache (core, D28)
| Name | Contract |
|---|---|
| `ENGINE_VERSION` | Part of every cache key. |
| `data_hash(fields, extra)` | SHA-256 of the input matrices. |
| `FeatureEngine(fields, cache_dir, data_key)` | `.compute(exprs) -> dict` (name → matrix): unique subexpressions computed once in dependency order and freed after their last use; results cached as `.npy` by SHA-256 of (data key, canonical form, version), written atomically. `.stats`: `factors, nodes, unique, computed, cache_hits, peak_live`. `.key(canon)`. |

## ghostdesk/features/alpha158.py — the 158 factors (core)
| Name | Contract |
|---|---|
| `WINDOWS`, `E` | 5, 10, 20, 30, 60; the 1e-12 guard. |
| `KBAR`, `PRICE`, `ROLLING` | Qlib Alpha158 definitions (arXiv:2009.11189) in our language. |
| `alpha158()` | Name → expression for all 158. |

## ghostdesk/features/pandas_reference.py — the pandas baseline (ready)
| Name | Contract |
|---|---|
| `E` | 1e-12. |
| `alpha158_pandas(df)` | The 158 factors on long rows with `groupby("symbol").rolling` (benchmark baseline and test oracle). |

## ghostdesk/research/dataset.py — panel and label (core, D29)
| Name | Contract |
|---|---|
| `FIELD_MAP` | Engine field → store column. |
| `Panel` | `days, symbols, fields, member, sector, spy_open, spy_close, raw_open, flag, data_key`. |
| `load_panel(start, end, asof, store, include_test, warmup_days=400)` | Members of the window with history; refuses test sessions while locked. |
| `open_to_open(open_)` | Row t: log open(t+1) → open(t+2). |
| `rolling_beta(ret, mkt, window=252, min_obs=120)` | Beta through row t (1.0 with too little history). |
| `residual_label(panel)` | Open-to-open return minus beta × SPY, minus the sector mean; NaN off-index, on vendor-error days and for the last two rows. |

## ghostdesk/research/models.py — the model zoo (core, D31)
| Name | Contract |
|---|---|
| `Design` | `X` (T, N, F ranked features), `y`, `mask`, `names`, `close`. |
| `rank_features(feats, mask)` | Each feature → cross-sectional rank in [-0.5, 0.5] among masked cells; 0 elsewhere. |
| `cs_rank_label(y, mask)` | The label ranked the same way (the training target). |
| `Model` | `.fit(design, rows)`, `.predict(design, rows) -> (len(rows), N)`, `.config()`, `needs_fit`. |
| `Reversal(days)` | Minus the past `days`-day log return (no fit). |
| `Ridge(alpha=100)` | Closed-form ridge on ranked features. |
| `LightGBM(rounds=300, params)` | Deterministic gradient boosting (fixed seed and threads). |
| `ExternalScores(name, days, scores, panel_days)` | Kaggle scores in the same interface. |
| `zoo()` | The local models: 1-day and 5-day reversal, ridge, LightGBM. |

## ghostdesk/research/backtest.py — walk-forward backtests (core, D32)
| Name | Contract |
|---|---|
| `FIXED_BPS`, `YEAR` | Cost grid 0, 1, 2, 5, 10 bps per unit traded; 252 sessions a year. |
| `folds(days, years, purge=2)` | (train rows, predict rows) per year; train ends `purge` sessions before the year. |
| `walk_forward(model, design, days, years, purge, first_train_row)` | Out-of-sample scores (NaN outside the years). |
| `half_spread(high, low, close, window=21)` | Half the mean Corwin-Schultz spread through t. |
| `decile_weights(scores, mask, q=0.1)` | Equal-weight long top 10%, short bottom 10% (gross 2). |
| `rank_ic(scores, label, mask)` | Spearman IC per session (≥ 30 stocks). |
| `evaluate(weights, scores, label, ret, hspread, mask, rows)` | `series` (gross, spread cost, turnover, IC, hit) and `summary`. |
| `summarize(series)` | IC mean and t, hit rate, turnover, gross and net (spread and fixed bps) mean, annual return, Sharpe. |

## ghostdesk/research/optimizer.py — risk model and optimizer (core, D33)
| Name | Contract |
|---|---|
| `OptConfig` | 12 factors, 252-day window, risk aversion 10, 2% cap, ±5% sectors, ±1% beta, gross 2, IC 0.02, 2 bps. |
| `pca_risk(returns, k)` | PCA factor model: loadings, factor variances, floored specific variances. |
| `Optimizer(n, S, cfg)` | One DPP cvxpy problem (dollar, beta and sector neutral, caps, gross, turnover cost); `.solve(...) -> (weights, {status, solve_s})`. |
| `grinold_alpha(score, spec, member, ic)` | IC × volatility × clipped z-score. |
| `optimize_path(scores, daily_ret, beta, member, S, hspread, rows, cfg, log)` | Weights for each session from the previous ones. |

## ghostdesk/research/registry.py — experiment registry (core, D34)
| Name | Contract |
|---|---|
| `SCHEMA` | The DuckDB `runs` table. |
| `sha256_bytes`, `array_sha256(a)`, `config_hash(config)` | Hashes (an array's dtype, shape and bytes). |
| `code_commit(root)` | `HEAD`, with `-dirty` if `src/` or `scripts/` have uncommitted changes. |
| `run_key(data_hash, commit, cfg_hash)` | First 16 hex digits of their SHA-256. |
| `Registry(root)` | `.record(...)` (refuses a dirty tree), `.get(key)`, `.runs()`, `.scores(key)`, `.verify(key, regenerate)` (bit-identical check). |

## ghostdesk/live/ledger.py — the prediction ledger (core, D30)
| Name | Contract |
|---|---|
| `COLUMNS`, `GENESIS` | Ledger columns; the first chain hash. |
| `LedgerError` | A second write for a session. |
| `sides(scores, q=0.1)` | +1 top decile, -1 bottom decile, 0. |
| `Ledger(root)` | `.append(session, made_at, preds)` (once per session, atomic, plus a hash-chain line), `.has`, `.path`, `.read(session)`, `.lines()`, `.verify()` (files match the chain), `.repair()` (adds the line of a file written just before a crash). |
| `first_open_utc(day)` | 09:30 New York time of that day in UTC: the earliest moment its open can exist (D38). |
| `score(rows, opens, half_spread, sectors, fixed_bps=2)` | Realized open(t+1)→open(t+2) return, residual, cost, pnl, profitable (owner's rule: the pick made money after costs), abs_error. A row whose `made_at` is not before `first_open_utc` of t+1 is left out (D38). |
| `refused(rows, opens)` | The rows `score` leaves out: made at or after the first open they would be scored on. |
| `model_summary(scored)` | Per model: sessions, share of profitable picks, cumulative decile-book P&L, mean rank IC, mean absolute error. |

## ghostdesk/live/evaluate.py — forward scoring of the ledger (core, D37)
| Name | Contract |
|---|---|
| `MIN_NAMES`, `REVERSALS`, `DAILY_COLUMNS` | Floor of 30 stocks for a rank IC; the two reversal baselines; columns of the daily table. |
| `daily_metrics(scored)` | One row per (session, model) from `ledger.score` output: rank IC, directional hit rate of the picks, profitable share after costs, picks, mean abs error, decile-book P&L. Empty in, empty out. |
| `summarize(daily)` | Per model: days, mean IC, t, hit rate, profitable share, abs error, P&L, differences to the reversal baselines and to the zero-signal model (IC 0, P&L 0); `forward_days` (0 on an empty ledger). |

## ghostdesk/live/portfolio.py — the target book, tracked forward (core, D37)
| Name | Contract |
|---|---|
| `YEAR`, `FIXED_BPS` | 252; 2 bps each way (same as `ledger.score`). |
| `book_days(books, opens, half_spread, fixed_bps)` | Per matured session: gross, cost, net, turnover, gross exposure, stocks missing a price. `books`: session → `{"target": shares, "equity"}` as in `night_*.json`; priced at open(t+1) and open(t+2). |
| `book_summary(days)` | Days, cumulative net return, Sharpe (None below 2 days), max drawdown, mean turnover, total cost. |
| `curve(days)` | Cumulative return and drawdown per day for the page. |

## ghostdesk/live/compare.py — validation against forward (core, D37)
| Name | Contract |
|---|---|
| `HISTORICAL`, `FORWARD`, `METRICS` | The two labels ("historical validation", "independent forward test"); compared metrics. |
| `load_validation(path)` | `validation.json` as a dict, `{}` if missing. |
| `compare(validation, forward, book)` | Rows per model and metric with validation value and sessions next to forward value and days; headline "N days of forward data". Forward is None until data exists. |

## ghostdesk/live/forward.py — the forward evaluation as one function (core, D37)
| Name | Contract |
|---|---|
| `read_books(live_dir)` | `night_*.json` → session → `{"target": shares, "equity"}`; unreadable files and nights without a plan are left out. |
| `build_report(ledger_rows, books, raw, sectors, validation)` | JSON-ready dict: `forward` (summary), `daily`, `book` (metrics and curve), `compare`. Pure; with no ledger it reports 0 days. |

## ghostdesk/live/nightly.py — the nightly run (core, D30)
| Name | Contract |
|---|---|
| `NY`, `OPG_OPEN`, `OPG_CLOSE` | Alpaca's OPG window: 19:00 to 09:28 New York time. |
| `trading_enabled(value)` | The kill switch: orders only when `TRADING` is exactly `"on"`; unset, empty or anything else is off (D38). |
| `NightConfig` | `min_frac=0.2`, `margin_min=3`. |
| `Decision` | `session, predict, trade, ok, reason`. |
| `Deps` | `broker, now, predict, target, ledger, store, trading=False, log`. |
| `last_closed(sessions, now)`, `window(sessions, s, cfg)` | The last closed session; its OPG window in UTC. |
| `state_path`, `read_state`, `is_done` | `night_<YYYYMMDD>.json`; done = `complete`. |
| `decide(sessions, now, done, cfg)` | Ledger after the close; orders only inside the window; a missed window is an error. |
| `run_night(deps, sessions, cfg)` | Ledger first (never once the next open has passed: the session is recorded as `missed`, D38), kill switch, plan from positions + this session's open orders, one OPG order per (session, symbol), flips closed tonight and opened next night, record with `complete` and `unreached`. |

## ghostdesk/live/model_release.py — the published frozen models (core, D38)
| Name | Contract |
|---|---|
| `RELEASE_TAG`, `MANIFEST_VERSION`, `FILES` | `models-v1`; manifest version 1; the four release files (`lightgbm.txt`, `ridge.npy`, `sectors.json`, `meta.json`). |
| `ModelReleaseError` | A release file is missing, has another size or SHA-256, or the manifest does not match the code. |
| `sha256(path)` | SHA-256 of a file, read in 1 MB blocks. |
| `verify(root, manifest, live_models)` | Checks every manifest file under `root` and that the manifest's nightly models are the code's; returns file -> SHA-256 or raises with every problem found. |
| `load_manifest(path)` | Reads `docs/results/MODEL_MANIFEST.json`; a read or parse error is a `ModelReleaseError`. |
| `build_manifest(root, meta, versions, extra_models)` | The manifest for a model folder (files, models, training, features, ensemble weights, package versions). |

## ghostdesk/live/predict.py — frozen models and the ensemble (core, D30)
| Name | Contract |
|---|---|
| `LIVE_MODELS` | reversal 1d and 5d, ridge, LightGBM. |
| `ensemble_weights(validation, models)` | Pre-registered rule: max(validation IC, 0), normalized. |
| `Night` | One night's design and the inputs of the optimizer. |
| `save_models`, `load_models(root)` | `data/live/models/`. |
| `night_design(store, symbols, session, sectors, asof, days_back=420)` | Features of the members on the night's session. |
| `predict_night(night, models)` | `model, symbol, score, pred_return`. |
| `ensemble_score(rows, weights)` | Weighted mean of the models' ranks. |
| `optimizer_target(night, score, held, cfg)` | Target weights from the optimizer, starting from the book held now. |

## ghostdesk/sim/fault_injection.py — fault-injection harness (ready, D35)
| Name | Contract |
|---|---|
| `NY` | `America/New_York`. |
| `Crash` | A process kill (BaseException). |
| `Resp` | A fake HTTP answer. |
| `FakeAlpaca` | In-memory Alpaca paper API at the HTTP level (duplicate ids, OPG window, no crossing zero, partial fills at the open, 429 storms, crashes before or after the request is handled). |
| `CrashyLedger` | A ledger that may die between the file and its chain line. |
| `SimClock` | A clock the broker's sleeps advance. |
| `sessions_between(start, n)` | A weekday calendar in UTC. |
| `Scenario` | Fault rates and an optional deliberate bug (`no_window`, `dup_ids`). |
| `check(...)` | Invariants I1-I6 after a run. |
| `run_scenario(sc)`, `run_many(n, start_seed, **kw)` | Random nights with primary and backup triggers; counts and violations. |

