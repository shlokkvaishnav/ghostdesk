# Ghostdesk: a trading desk with no people at it

![CI](https://github.com/shlokkvaishnav/ghostdesk/actions/workflows/ci.yml/badge.svg)

**Can a program read company reports, choose stocks, and trade them, with no person at the desk, and can its
backtests be trusted?**

## What it does
1. **Data with no hindsight.** The S&P 500 as it was on each date (including the companies that later left it),
   47,719 10-K and 10-Q reports with the exact time the SEC accepted each one, numbers as they were first reported,
   and clean daily prices for 2016-2025.
2. **Three ways to choose stocks, each tested once under a pre-registration.** The rules of each test were committed
   and timestamped before the test data was used, and the code locks the test years until then.

   | Model | Test 2022-2025, long-short after costs | Result |
   |---|---|---|
   | Text change of 10-K/10-Q reports ("lazy prices") | +0.09%/month, 95% CI [-0.36, +0.54] | not detected |
   | LightGBM on 18 point-in-time stock features | -0.11%/month, 95% CI [-0.72, +0.49] | not detected |
   | CNN on 20-day price-chart images | -0.30%/month, 95% CI [-0.77, +0.17] | not detected |

   A table of common backtest mistakes shows how much each one changes the answer: the wrong stock list (today's
   S&P 500) changes it the most.
3. **Execution.** A reinforcement-learning agent (PPO) was tested against TWAP, VWAP and Almgren-Chriss on replayed
   real minute bars. It did not beat VWAP, so the live desk uses VWAP.
4. **Live desk.** Each month a GitHub Actions job trades the text-change portfolio with paper money on Alpaca, in
   VWAP child orders over the first hour, checks the book against the plan, and updates a web page.
   GitHub starts timed runs 4-6 hours late, so for now the owner starts each rebalance by hand.

## How it is built
A desk with no person at it must be safe when things go wrong. Each guarantee has a test: no look-ahead (every
feature and chart is checked by changing all later data), no survivorship bias, a test period that the code keeps
locked, paper money only, a rerun does no harm, a crashed run is finished by the next one, a missed day is caught
up, orders never cross zero, and the live code picks the same stocks as the tested study. Every failure shows on
the page; none sends an email. Details: [engineering](docs/engineering.md).

## Results and documents
- [Results](docs/results.md): every test, with its confidence interval and power.
- [Research explorer](https://shlokkvaishnav.github.io/ghostdesk/explore/): try the studies yourself (switch off one backtest guard, compare periods and measures, see trading costs).
- [Research note](docs/note.md): the short write-up.
- Pre-registrations: [signal](docs/preregistration.md), [ML](docs/preregistration-ml.md), [chart CNN](docs/preregistration-cnn.md).
- [Data method](docs/data.md). Raw market data is not published; only statistics are.

## Run it
```bash
make install && make check
```

The live page: https://shlokkvaishnav.github.io/ghostdesk/. Developers and AI agents start at [AGENTS.md](AGENTS.md).
