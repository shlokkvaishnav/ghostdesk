# Plan

## The three jobs
```
1. SIGNAL      new 10-K / 10-Q reports -> how much did the text change? -> one score per stock
2. PORTFOLIO   scores -> stocks to hold, with a maximum weight per stock and a maximum total exposure
3. EXECUTION   an RL agent splits each trade into small orders over 30-60 minutes after the market opens
LIVE           each US trading day, with fake money (Alpaca paper trading)
SITE           a static page, rebuilt each day: new reports and scores, positions, profit and loss against SPY
```

## Steps
1. **Data, with no hindsight.**
   - Stocks: the S&P 500 as it was on each date since 2010, including companies that later left it.
   - Reports: 10-K and 10-Q text from SEC EDGAR, with the exact time the SEC accepted each report. A report accepted
     after 16:00 New York time counts on the next trading day.
   - Numbers: from each report's own XBRL file, never from later corrected values.
   - Prices: daily and minute bars from Alpaca.
   - Split by time: build 2010-2019, check 2020-2021, final test 2022-2025 (used once). Live trading is the
     forward test.
2. **The signal study.** Text-change measures from the original paper first (word-count cosine, Jaccard, edit
   distance); a neural-embedding measure as a variant. Controls for momentum, size and sector. Results: information
   coefficient by year, quintile returns, long-short return after costs, turnover, and a Fama-French alpha with its
   t-statistic. A result of "no effect" is reported as one.
3. **The execution study.** A simulator with the square-root market-impact law, calibrated for each stock. The PPO
   agent against TWAP, VWAP and Almgren-Chriss, for orders of 0.1%, 1% and 5% of a stock's daily volume. The main
   chart: how much the agent saves at each order size. Theory says almost nothing for small orders.
4. **Optional: a learned market simulator.** Only if it passes three tests written down before the try: realistic
   on held-out days, better results on real days, and cheap enough to run.
5. **Live.** One GitHub Actions job per trading day. Paper fills are simulated by Alpaca, and the site says so.
6. **Write-up.** A short research note, a one-page summary, and a page of the pitfalls that the project avoids.

## Pitfalls this project avoids
- **Survivorship bias:** the stock list on a date contains only the companies in the index on that date.
- **Look-ahead:** a report is used only after the time the SEC accepted it.
- **Restated numbers:** values come from the report that first gave them.
- **Simulated fills:** live paper results show that the system works; they do not prove a real trading cost.
