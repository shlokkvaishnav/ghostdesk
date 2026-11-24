"""Historical validation against the independent forward test (decision D37).

Two different kinds of evidence, never merged:
- **historical validation:** 2021-2022 walk-forward results (`docs/results/validation.json`); the models were
  chosen while looking at these numbers, so they are in-sample for model choice.
- **independent forward test:** the ledger's predictions made after the freeze, scored on opens that did not exist
  when the models were frozen.

A forward value is None until there is forward data. Sample size (sessions or days) is part of every row.
"""
from __future__ import annotations

import json
from pathlib import Path

HISTORICAL = "historical validation"
FORWARD = "independent forward test"
# (metric label, validation key, forward key)
METRICS = (("rank IC (mean)", "ic_mean", "ic_mean"), ("rank IC t statistic", "ic_t", "ic_t"),
           ("hit rate of picks", "hit_rate", "hit_rate"))


def load_validation(path: Path) -> dict:
    """`validation.json` as a dict, or {} if the file is missing or unreadable."""
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {}


def compare(validation: dict, forward: dict, book: dict | None = None) -> dict:
    """Rows (model, metric, validation value and sessions, forward value and days) plus the labels. Only models in
    the forward ledger are listed; a model with no forward data would show None, so with an empty ledger the
    validation models still list with forward None."""
    vmodels = validation.get("models", {})
    fmodels = forward.get("models", {})
    names = sorted(set(vmodels) | set(fmodels))
    rows = []
    for m in names:
        v = (vmodels.get(m) or {}).get("validation") or {}
        f = fmodels.get(m) or {}
        for label, vk, fk in METRICS:
            rows.append({"model": m, "metric": label, "validation": v.get(vk), "validation_sessions": v.get("sessions"),
                         "forward": f.get(fk), "forward_days": f.get("days", 0)})
    v_opt = (validation.get("optimizer") or {})
    n = int(forward.get("forward_days", 0))
    return {"labels": {"validation": HISTORICAL, "forward": FORWARD},
            "forward_days": n,
            "headline": f"{n} days of forward data" if n != 1 else "1 day of forward data",
            "validation_window": validation.get("validation"), "rows": rows,
            "optimizer_validation": v_opt or None, "book_forward": book}
