# Module reference

One section per module in `src/ghostdesk/`. Each public function or class is listed with its contract. Status:
**core** = used by the current pipeline; **ready** = tested, used in a later step. `tests/test_docs.py` fails if a module or a public name is missing here.

---

## ghostdesk/filings/edgar.py — SEC access (core)
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

## ghostdesk/filings/index.py — report index (core)
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

## ghostdesk/filings/sections.py — numbered items (core)
| Name | Contract |
|---|---|
| `ITEM_RE` | Pattern for an item heading at the start of a line (`Item 1A.`, `ITEM 7 -`); `Item 10`-`15` are not read as `Item 1`. |
| `split_sections(text, max_heading=None) -> dict` | `item_1a`, `item_7`, … → section text. Repeated marks of one item (page headers) join into one section; the longest span wins (skips the table of contents). With `max_heading`, a line longer than that is a cross-reference, not a heading. |

## ghostdesk/data/universe.py — point-in-time S&P 500 with CIKs (core)
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

## ghostdesk/data/calendar.py — tradeable time (core)
| Name | Contract |
|---|---|
| `opens(sessions) -> DatetimeIndex` | Session dates → 09:30 New York open in UTC (DST handled). |
| `first_open_after(accepted_utc, sessions)` | First open strictly after the time, or None. |

## ghostdesk/data/alpaca.py — prices (core)
| Name | Contract |
|---|---|
| `keys() -> dict` | Request headers from env or `.env`; error names missing keys, never values. |
| `AlpacaClient(headers, per_minute=180, session, sleep, clock)` | `.bars(symbols, start, end, timeframe="1Day", adjustment="all", feed="sip") -> DataFrame` (`symbol, t, o, h, l, c, v, n, vw`), all pages; a symbol dropped from a multi-symbol answer is asked for alone. |
| `alpaca_symbol(ticker) -> str` | `BRK-B` → `BRK.B`. |
| `coverage(daily, members, start, end) -> dict` | Share of member-days with a bar; uses `price_symbol` if present. |

## ghostdesk/data/returns.py — clean daily returns (core)
| Name | Contract |
|---|---|
| `daily_returns(adjusted, raw, big=0.3, excess=0.2) -> DataFrame` | Log returns; a day with `abs(adj) > big` and `abs(adj) - abs(raw) > excess` is flagged and its return is NaN. |

## ghostdesk/data/spread.py — spread from high/low (ready)
| Name | Contract |
|---|---|
| `corwin_schultz(high, low, close=None, floor=True) -> Series` | Two-day estimates; overnight gap removed when `close` is given; `floor=False` keeps negatives. |
| `monthly_spread(high, low, close, dates) -> Series` | Monthly mean of unfloored estimates, then floored at 0 (unbiased within ±0.1 pp in tests). |

## ghostdesk/signal/similarity.py — change measures (core)
| Name | Contract |
|---|---|
| `words(text)`, `sentences(text)` | Lower-case word list; sentences as normalised word strings. |
| `cosine(a, b)`, `jaccard(a, b)` | As in Cohen, Malloy and Nguyen (2020); NaN for empty text. |
| `edit(a, b)` | 2 × same words / all words; sentence alignment, then word alignment inside changed blocks (≤ 5,000 words). |
| `all_measures(a, b) -> dict` | `{"cosine", "jaccard", "edit"}`. |

## ghostdesk/signal/features.py — features per report pair (core)
| Name | Contract |
|---|---|
| `prose(html) -> str` | lxml text; number tables removed, layout tables kept; new lines only at block elements; source wraps removed. |
| `parts(html, form) -> dict` | `full`, plus `risk` (Item 1A) and `mdna` (10-K Item 7, 10-Q Item 2) if ≥ 200 words; headings ≤ 160 characters. |
| `pair_features(cur, prev) -> dict` | `sim_<part>_<measure>`, `words_<part>`, `words_<part>_prev`; NaN when a part is missing in either report. |

## ghostdesk/execution/benchmarks.py — schedules (ready)
`ACParams` (Almgren-Chriss parameters; `.tau`, `.eta_tilde`), `twap(X, N)`, `vwap(X, volume_profile)`,
`kappa(p, lam)`, `almgren_chriss(X, p, lam)` (holdings; `lam=0` gives TWAP), `expected_cost(x, p)`,
`cost_variance(x, p)`, `mean_variance(x, p, lam)`.

## ghostdesk/execution/impact.py — simulator (ready)
`ImpactSimulator`: arithmetic Brownian price, linear permanent and power-law temporary impact; `.reset(seed)`,
`.step(n)`. Matches the closed-form Almgren-Chriss cost by Monte Carlo (tests). To be calibrated per stock in Step 4.

## ghostdesk/execution/env.py — Gymnasium environment (ready)
`ExecutionEnv` (sell X shares over N steps, reward = minus implementation shortfall; `.reset`, `.step`),
`run_schedule(env, holdings, seed)`.

## ghostdesk/execution/realism.py — realism checks (ready; Step 4b gate)
`acf`, `hill`, `stylised_facts`, `window_stats`, `auc`, `discriminator_score(real, fake, folds, seed)`.

## ghostdesk/rl/ppo.py — PPO (ready)
`PPOConfig`, `mlp`, `ActorCritic` (`.dist`, `.value`, `.act`), `gae(...)`, `PPO` (`.learn(total_steps)`,
`.evaluate(env, episodes, seed)`). Needs the `ml` extra (torch).
