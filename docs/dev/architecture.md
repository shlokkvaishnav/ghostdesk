# Architecture

## Pipeline
Each box is a script in `scripts/`; each arrow is a data file in `data/` (gitignored). Columns are in
[data-contracts.md](data-contracts.md).

```
 public sources                     scripts/                              data/
 ──────────────                     ────────                              ─────
 fja05680 S&P 500 intervals ─┐
 Wikipedia current + changes ├──▶ data/build_universe.py ───────────▶ universe.parquet
 SEC lookup, tickers, JSON ──┘                                         price_symbols.parquet (load_prices.py)
 SEC submissions JSON ──────────▶ data/build_sectors.py ────────────▶ sectors.parquet
 Alpaca daily bars (2016-) ─────▶ data/load_prices.py (seed, once) ─▶ prices_daily{,_raw}.parquet
                                 data/update_prices.py (each night) ▶ store/bars/{adj,raw}/<batch>.parquet
```

## Layers (`src/ghostdesk/`)
| Package | Role | Depends on |
|---|---|---|
| `paths.py` | repository and data paths | — |
| `data/` | SEC client, S&P 500 universe, Alpaca bars, the point-in-time store, spread estimate, sectors | DuckDB |
| `research/` | the test lock | `data/` |
| `live/` | Alpaca paper broker, today's members, whole-share orders, page pieces, book risk | `data/` |

Rules: library code in `src/` does no network I/O at import time, takes clients as arguments (so tests inject
fakes), and never reads `.env` except through `data.edgar_client.user_agent` and `data.alpaca_client.keys`. Scripts
in `scripts/` hold the orchestration and file I/O.

## Point-in-time model
| Event | Time used | Code |
|---|---|---|
| Stock is in the list | membership interval `[start, end)` by price symbol | `data/store.py:membership` |
| A price is known | the batch's `ingested_at`; a read at `asof` sees the newest version known then | `data/store.py:PriceStore.read` |
| Test data may be read | only after the final, stamped pre-registration | `research/holdout_lock.py` |
