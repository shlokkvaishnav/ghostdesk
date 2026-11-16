# Ghostdesk: a trading desk with no people at it

![CI](https://github.com/shlokkvaishnav/ghostdesk/actions/workflows/ci.yml/badge.svg)

**Can a program read company reports, choose stocks, and trade them at a low cost, with no person at the desk?**

## What it does
A quant trading desk does three jobs. Ghostdesk will do all three by itself:
1. **Signal.** It reads each annual and quarterly report (10-K, 10-Q) that a company sends to the SEC, and measures
   how much the text changed since the comparable earlier report. Research shows that companies that change their
   reports a lot often do worse later ("lazy prices", Cohen, Malloy and Nguyen, 2020). Ghostdesk tests this again,
   with no hindsight.
2. **Execution.** An AI agent, trained with reinforcement learning, splits each trade into small orders. The study
   measures how much it saves against standard methods (TWAP, VWAP, Almgren-Chriss) at each order size.
3. **Live.** Each US trading day, one job trades with fake money (Alpaca paper trading) and updates a web page.

## Status
- **Data: done.** The S&P 500 as it was on each date (with the companies that left it), 47,719 reports with the
  exact time the SEC accepted each one, text-change scores for 30,514 report pairs, and clean daily prices for
  2016-2025. How each problem in the data was found and fixed: [data quality](docs/dev/data-quality.md).
- **Next: the signal study.** Build on 2016-2019, check on 2020-2021, and test once on 2022-2025, after the test
  rules are written down.
- **Later:** the execution study, the live job and the web page.

## Run it
```bash
make install && make check
```
The plan: [plan](docs/plan.md). The data method: [data](docs/data.md). Raw market data is not published; only charts and
statistics are. Developers and AI agents start at [AGENTS.md](AGENTS.md).
