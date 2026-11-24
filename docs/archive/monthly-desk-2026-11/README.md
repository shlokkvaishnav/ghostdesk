# Archive: the monthly paper desk (2026-11-17 to 2026-11-24)

The first version of Ghostdesk traded a monthly long-short book on an Alpaca **paper** account (no real money).
It was stopped and closed on 2026-11-24 when the project became the research platform (decisions D26, D38).
The code is in git history before the merge of `pivot/research-platform`; these files are the account record.

Written by `scripts/ops/archive_account.py` (read-only GET requests). The account number, account ids and keys are
left out.

| File | Content |
|---|---|
| `account.json` | Account values at 2026-11-24 17:04 UTC, before the close: equity $100,664.11, 198 positions |
| `positions.json` | The 198 positions at that time |
| `open_orders.json` | Open orders at that time: none (the market-on-open test order `f06e52f6`, 1 SPY, was cancelled at 13:52 UTC before the open, so it never filled) |
| `orders_all.json` | Every order of the account: 1,367 (1,366 filled; the cancelled test order) |
| `fills.json` | Every fill: 1,855 (an order can fill in parts) |
| `portfolio_history.json` | Daily equity from Alpaca (7 points, 2026-11-14 to 2026-11-24 UTC stamps) |
| `site_live.json` | The last page data of the monthly desk (2026-11-17) |
| `liquidation_orders.json` | The 198 market orders that closed the book on 2026-11-24 (all filled) |
| `final_state.json` | The account after the close: 0 positions, 0 open orders, equity $100,582.38 |
| `com.ghostdesk.trade-dispatch.plist` | The Mac launchd trigger of D23 (unloaded on 2026-11-24) |

Result of the monthly desk: one rebalance (2026-11-17, 1,366 filled orders), held until 2026-11-24, closed at
equity $100,582.38 from $100,000 at the start. One week of data is far too short to say anything about the strategy.
