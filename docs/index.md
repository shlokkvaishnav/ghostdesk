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
  2016-2025. How each problem in the data was found and fixed: [data quality](dev/data-quality.md).
- **Signal study: done.** In the pre-registered test (2022-2025), the effect was **not detected**: +0.09% per month
  after costs, 95% interval −0.36% to +0.54%. Over 2016-2025 the upper limit is about 0.5% per month. Details:
  [results](results.md).
- **Backtest mistakes, measured:** for this signal, timing look-ahead changes little; the stock list and mixing
  annual with quarterly reports change the most.
- **Next:** the execution study (does an RL agent learn real intraday patterns, and how much money can the strategy
  trade), then the live job and the web page.

## Run it
```bash
make install && make check
```
The plan: [plan](plan.md). The data method: [data](data.md). Raw market data is not published; only charts and
statistics are. Developers start at the
[status page](dev/status.md).
