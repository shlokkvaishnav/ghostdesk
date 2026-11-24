# Status and next work

Updated 2026-11-24. The project is being turned into a quant research platform (decision D26) on the branch
`pivot/research-platform`. The live monthly book on `main` is unchanged until the owner switches over.

## Done
| Step | Result | Evidence |
|---|---|---|
| Universe | 96.8% of 2010-2025 member-days mapped to a CIK | `universe_coverage.json` |
| Seed prices | 98.0% of 2016-2025 member-days with a bar; 8 vendor-error days | `prices_coverage.json` |
| 1. Deletions | lazy prices, execution study, monthly models, launchd trigger removed | D26 |
| 1. Price store | seeded from the 2016-2025 load; extended to 2026-11-23 (117,247 raw rows, 35 symbols refetched) | `data/store/ingest_log.json` |
| 1. Sectors | 709 companies, 25 SIC groups | `sectors.parquet` |

## Next
2. Expression-language feature engine with a cache, tests and a speed benchmark against plain pandas.
3. Model zoo, walk-forward backtester, optimizer, experiment registry.
4. Pre-registration of the locked test (draft first; the owner approves before it is final and stamped).
5. Nightly live loop, prediction ledger, fault-injection harness.
6. Cloudflare Worker trigger and the new site.

## Known open items
- The index intervals were built on 2026-11-16 from Wikipedia; changes to the index after that date reach the
  research data only when `build_universe.py` runs again. The live loop reads today's members each night.
- `data/raw/` (SEC cache) and the old study files in `data/` are no longer needed except the submissions JSON for
  sectors; the owner decides when to delete them.
