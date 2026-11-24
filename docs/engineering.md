# Engineering

Ghostdesk runs with no person at the desk. This page shows how it is built and which test proves each guarantee.
Details of every module: [modules](dev/modules.md). Every design choice and why: [decisions](dev/decisions.md).

## Guarantees and the tests that prove them
| Guarantee | How | Test |
|---|---|---|
| No survivorship bias | The stock list on each date is the S&P 500 on that date, mapped to SEC CIKs with evidence | `test_sp500_universe.py` |
| Point-in-time prices | Immutable batches; a read at a past date sees the adjusted prices as they were known then | `test_store.py::test_as_of_read_sees_the_old_adjusted_history` |
| A dividend or split is caught | The nightly load compares overlap sessions and refetches the whole adjusted history of that symbol | `test_store.py::test_daily_ingestion_appends_and_refetches_after_a_dividend` |
| The test stays locked | Test sessions open only after the final, committed, stamped pre-registration | `test_holdout_lock.py` |
| Paper money only | The broker refuses any host but the paper API | `test_live.py::test_broker_refuses_a_live_endpoint` |
| Orders never cross zero | A flip is a close, then an open | `test_live.py::test_orders_reach_target_and_never_cross_zero` |
| Rate limits respected | At most 170 requests a minute (limit 200); 429 retried | `test_live.py::test_broker_paces_requests_and_keeps_retrying_rate_limits` |
| No failure emails | Every step of the scheduled workflows continues on error | `test_workflows.py` |
| Docs match the code | Every module, public name and script is documented | `test_docs.py` |
