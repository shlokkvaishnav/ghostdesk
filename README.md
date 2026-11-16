# Ghostdesk: a trading desk with no people at it

![CI](https://github.com/shlokkvaishnav/ghostdesk/actions/workflows/ci.yml/badge.svg)

**Can a program read company reports, choose stocks, and trade them at a low cost, with no person at the desk?**

## What it does
A quant trading desk does three jobs. Ghostdesk does all three by itself, every US trading day:
1. **Signal.** It reads each new annual and quarterly report (10-K, 10-Q) that a company sends to the SEC. It
   measures how much the text changed since the last report. Research shows that companies that change their reports
   a lot often do worse later ("lazy prices", Cohen, Malloy and Nguyen, 2020).
2. **Portfolio.** It turns these scores into a list of stocks to hold, with limits on risk.
3. **Execution.** An AI agent, trained with reinforcement learning, buys and sells these stocks in small parts, so
   the trades cost less than simple methods.

It trades with fake money (Alpaca paper trading). The results go to a public web page each day.

## Status
- **Done: the stock list.** The S&P 500 as it was on each date since 2010, with the companies that left it. Each
  stock is linked to its SEC company number with checks against its reports: 96.8% of member-days are linked
  ([data](docs/data.md)).
- **Done: the report index.** 47,719 annual and quarterly reports, each with the exact time the SEC accepted it,
  and each paired with the correct earlier report.
- **Done: the tools.** Text-change measures from the paper, a spread estimate from daily prices, a trading
  simulator, the textbook trading schedules (TWAP, VWAP, Almgren-Chriss), and a PPO agent written from scratch.
- **Next:** the report text and numbers, prices (Alpaca), then the signal study.

## Run it
```bash
make install-ml && make test
```
The full plan is on the [plan page](docs/plan.md). Raw market data is not published; only charts and statistics are.
