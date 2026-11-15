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
New project. It starts from tested parts of earlier work:
- an SEC download client that obeys the SEC access rules, and a section-aware report splitter;
- a check that compares numbers with the official figures;
- a trading simulator, the textbook trading schedules (TWAP, VWAP, Almgren-Chriss), and a PPO agent written from
  scratch and checked against a standard library.

Next: the data (500 US stocks since 2010, with no hindsight in the stock list), then the signal study.

## Run it
```bash
make install-ml && make test
```
The full plan is on the [plan page](docs/plan.md). Raw market data is not published; only charts and statistics are.
