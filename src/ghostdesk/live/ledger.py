"""The prediction ledger (decision D30): every model's prediction for every member, written before any order.

Layout under `root` (data/live/ledger/):
  <YYYYMMDD>.parquet   one file per session: the predictions made after that session's close. Written once
                       (a second write for the same session is refused), never changed.
  chain.jsonl          one line per file: session, file SHA-256, the previous line's hash, and the line's own hash
                       (SHA-256 of the three). Changing or removing any earlier file breaks `verify`.
Rows: session, made_at (UTC), model, symbol, score, rank (percentile among the night's members), side (+1 top
decile, -1 bottom decile, 0), pred_return (the model's own return forecast where it has one, else NaN).

Scoring (`score`) is derived, not part of the ledger: after the opens of t+1 and t+2, each prediction of session t
gets its realized open(t+1) -> open(t+2) return and residual. Owner's definition of a correct prediction: the trade
it caused made money after costs: a pick (side != 0) is profitable when side x return - cost > 0, with cost = half
spread in and out plus 2 bps each way. The error size is |pred_return - realized| where a return forecast exists.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

COLUMNS = ["session", "made_at", "model", "symbol", "score", "rank", "side", "pred_return"]
GENESIS = "0" * 64


class LedgerError(RuntimeError):
    """A second write for a session, a changed file, or a broken chain."""


def first_open_utc(day) -> pd.Timestamp:
    """The earliest moment a session's opening price can exist: 09:30 New York time on that day (NYSE never opens
    earlier; early closes change only the close)."""
    d = pd.Timestamp(day)
    d = d.tz_localize(None) if d.tz is not None else d
    return (d.normalize() + pd.Timedelta(hours=9, minutes=30)).tz_localize("America/New_York").tz_convert("UTC")


def _utc(t) -> pd.Timestamp:
    t = pd.Timestamp(t)
    return t.tz_localize("UTC") if t.tz is None else t.tz_convert("UTC")


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def sides(scores: pd.Series, q: float = 0.1) -> pd.Series:
    """+1 for the top q of finite scores, -1 for the bottom q, 0 else."""
    s = scores.dropna()
    out = pd.Series(0, index=scores.index, dtype=int)
    k = int(len(s) * q)
    if k:
        order = s.sort_values(kind="stable").index
        out[order[-k:]] = 1
        out[order[:k]] = -1
    return out


class Ledger:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.chain = self.root / "chain.jsonl"

    def path(self, session: pd.Timestamp) -> Path:
        return self.root / f"{pd.Timestamp(session):%Y%m%d}.parquet"

    def has(self, session) -> bool:
        return self.path(session).exists()

    def lines(self) -> list[dict]:
        if not self.chain.exists():
            return []
        return [json.loads(x) for x in self.chain.read_text().splitlines() if x.strip()]

    def append(self, session, made_at: pd.Timestamp, preds: pd.DataFrame) -> dict:
        """preds: model, symbol, score, pred_return. Adds rank and side per model; writes the file and the chain line."""
        p = self.path(session)
        if p.exists():
            raise LedgerError(f"ledger for {pd.Timestamp(session):%Y-%m-%d} exists; it is never rewritten")
        df = preds.copy()
        df["rank"] = df.groupby("model")["score"].rank(pct=True)
        df["side"] = df.groupby("model", group_keys=False)["score"].apply(sides).astype(int)
        df["session"] = pd.Timestamp(session)
        df["made_at"] = pd.Timestamp(made_at)
        if "pred_return" not in df:
            df["pred_return"] = np.nan
        df = df[COLUMNS].sort_values(["model", "symbol"]).reset_index(drop=True)
        tmp = p.with_name(p.stem + ".tmp")
        df.to_parquet(tmp, index=False)
        tmp.replace(p)  # atomic: a crash leaves no half-written ledger file
        prev = (self.lines() or [{"hash": GENESIS}])[-1]["hash"]
        rec = {"session": f"{pd.Timestamp(session):%Y-%m-%d}", "file_sha256": _sha(p), "prev": prev,
               "rows": len(df), "written_at": pd.Timestamp(made_at).isoformat()}
        rec["hash"] = hashlib.sha256(f"{rec['session']}|{rec['file_sha256']}|{prev}".encode()).hexdigest()
        with self.chain.open("a") as f:
            f.write(json.dumps(rec) + "\n")
        return rec

    def read(self, session=None) -> pd.DataFrame:
        files = [self.path(session)] if session is not None else sorted(self.root.glob("*.parquet"))
        files = [f for f in files if f.exists()]
        if not files:
            return pd.DataFrame(columns=COLUMNS)
        return pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)

    def verify(self) -> tuple[bool, str]:
        """Every file matches its chain line and the chain links; a file without a line is a crash between the two
        writes, repaired by `repair`."""
        prev = GENESIS
        seen = set()
        for rec in self.lines():
            h = hashlib.sha256(f"{rec['session']}|{rec['file_sha256']}|{prev}".encode()).hexdigest()
            if rec["prev"] != prev or rec["hash"] != h:
                return False, f"chain broken at {rec['session']}"
            p = self.root / f"{rec['session'].replace('-', '')}.parquet"
            if not p.exists() or _sha(p) != rec["file_sha256"]:
                return False, f"ledger file of {rec['session']} changed or missing"
            seen.add(p.name)
            prev = rec["hash"]
        extra = sorted(p.name for p in self.root.glob("*.parquet") if p.name not in seen)
        return (not extra), ("ok" if not extra else f"files without a chain line: {extra}")

    def repair(self) -> list[str]:
        """Add the missing chain line of a file written just before a crash (the file itself is complete: it was
        renamed into place atomically)."""
        seen = {r["session"].replace("-", "") + ".parquet" for r in self.lines()}
        fixed = []
        for p in sorted(self.root.glob("*.parquet")):
            if p.name not in seen:
                df = pd.read_parquet(p)
                prev = (self.lines() or [{"hash": GENESIS}])[-1]["hash"]
                s = f"{pd.Timestamp(df['session'].iloc[0]):%Y-%m-%d}"
                rec = {"session": s, "file_sha256": _sha(p), "prev": prev, "rows": len(df),
                       "written_at": str(df["made_at"].iloc[0]), "repaired": True}
                rec["hash"] = hashlib.sha256(f"{s}|{rec['file_sha256']}|{prev}".encode()).hexdigest()
                with self.chain.open("a") as f:
                    f.write(json.dumps(rec) + "\n")
                fixed.append(s)
        return fixed


def score(ledger_rows: pd.DataFrame, opens: pd.DataFrame, half_spread: pd.DataFrame | None = None,
          sectors: pd.Series | None = None, fixed_bps: float = 2.0) -> pd.DataFrame:
    """Realized outcome of each prediction whose two next opens are known. A row whose `made_at` is not earlier than
    the first realized open (`first_open_utc` of session t+1) is refused (left out); see `refused`. `opens`: session x symbol raw opens.
    Returns the ledger rows with realized (simple return), residual (minus the cross-sectional mean of the night's
    members, by sector when `sectors` is given), cost, pnl (side x realized - cost for picks), profitable, abs_error."""
    if ledger_rows.empty:
        return ledger_rows.assign(realized=[], residual=[], cost=[], pnl=[], profitable=[], abs_error=[])
    days = opens.index
    out = []
    for s, g in ledger_rows.groupby("session"):
        i = days.searchsorted(pd.Timestamp(s), side="right")  # the first session after s
        if i + 1 >= len(days):
            continue
        # Refuse a prediction made at or after the first realized price it would be scored on (D38): the ledger
        # must exist before the outcome does. Such rows are left out of the scores, never scored.
        g = g[g["made_at"].map(_utc) < first_open_utc(days[i])]
        if g.empty:
            continue
        a, b = opens.iloc[i], opens.iloc[i + 1]
        g = g.copy()
        g["realized"] = (b / a - 1).reindex(g["symbol"]).to_numpy()
        base = g.drop_duplicates("symbol").set_index("symbol")["realized"]
        if sectors is not None:
            mu = base.groupby(sectors.reindex(base.index).fillna("unknown")).transform("mean")
        else:
            mu = pd.Series(base.mean(), index=base.index)
        g["residual"] = g["realized"] - mu.reindex(g["symbol"]).to_numpy()
        hs = (half_spread.loc[:s].iloc[-1].reindex(g["symbol"]).to_numpy() if half_spread is not None
              else np.zeros(len(g)))
        g["cost"] = np.where(g["side"] != 0, 2 * (np.nan_to_num(hs) + fixed_bps / 1e4), 0.0)
        g["pnl"] = np.where(g["side"] != 0, g["side"] * g["realized"] - g["cost"], 0.0)
        g["profitable"] = np.where(g["side"] != 0, g["pnl"] > 0, np.nan)
        g["abs_error"] = (g["pred_return"] - g["realized"]).abs()
        out.append(g)
    return pd.concat(out, ignore_index=True) if out else ledger_rows.iloc[:0]


def refused(ledger_rows: pd.DataFrame, opens: pd.DataFrame) -> pd.DataFrame:
    """The rows that `score` refuses: made at or after the first open of the session after theirs."""
    if ledger_rows.empty:
        return ledger_rows
    days = opens.index
    first = ledger_rows["session"].map(
        lambda s: first_open_utc(days[i]) if (i := days.searchsorted(pd.Timestamp(s), side="right")) < len(days)
        else pd.NaT)
    first = pd.to_datetime(first, utc=True)  # naive opens are UTC; NaT stays NaT
    late = first.notna() & (ledger_rows["made_at"].map(_utc) >= first)
    return ledger_rows[late.to_numpy(dtype=bool)]


def model_summary(scored: pd.DataFrame) -> pd.DataFrame:
    """Per model: sessions scored, share of profitable picks, cumulative hypothetical P&L of the equal-weight decile
    book (mean pick pnl per side, long + short), mean rank IC, mean absolute error."""
    rows = []
    for m, g in scored.dropna(subset=["realized"]).groupby("model"):
        picks = g[g["side"] != 0]
        daily = picks.groupby(["session", "side"])["pnl"].mean().groupby("session").sum()
        ics = g.groupby("session").apply(lambda x: x["score"].corr(x["residual"], method="spearman"),
                                         include_groups=False)
        rows.append({"model": m, "sessions": int(g["session"].nunique()),
                     "profitable_share": float(picks["profitable"].mean()) if len(picks) else np.nan,
                     "cum_pnl": float(daily.sum()), "ic_mean": float(ics.mean()),
                     "abs_error": float(g["abs_error"].mean()) if g["abs_error"].notna().any() else np.nan})
    return pd.DataFrame(rows)
