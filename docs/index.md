# Ghostdesk

Ghostdesk is a quant research platform for next-day stock prediction on the S&P 500 as it was on each date, with a
nightly prediction ledger that is scored forward. Order execution is disabled: no order is placed and the paper
account holds nothing. It has its own point-in-time data store, a feature engine driven by a small expression
language, a model zoo with one interface, a walk-forward backtester with trading costs, a portfolio optimizer, and an
experiment registry that can regenerate any result exactly.

- [Engineering](engineering.md): how it is built and which test proves each guarantee.
- [Data method](data.md). Raw market data is not published; only statistics are.
- Developers start at the [status page](dev/status.md).

```bash
make install && make check
```
