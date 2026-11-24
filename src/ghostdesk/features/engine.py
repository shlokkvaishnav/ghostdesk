"""The feature engine: expressions -> (session x symbol) matrices, with common-subexpression reuse and a cache.

- **Compile:** each expression is parsed (`features.expr.parse`); all trees of a request share one table keyed by
  `canonical`, so a subexpression used by many factors (`Ref($close, 1)`, `Mean($close, 20)`) is computed once.
- **Evaluate:** each node is one vectorized numpy call (`features.ops`) on the whole matrix of all sessions and
  symbols. Infinities (division by zero) become NaN in the results.
- **Cache:** a result is stored as `.npy` under `cache_dir`, keyed by SHA-256 of (data hash, canonical expression,
  ENGINE_VERSION). The data hash comes from the inputs (`data_hash`), so new data or a new engine version never
  reads a stale result. A warm rerun reads every factor from the cache and computes nothing.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np

from ghostdesk.features import ops
from ghostdesk.features.expr import Node, canonical, parse, subexpressions

ENGINE_VERSION = "1"


def data_hash(fields: dict[str, np.ndarray], extra: str = "") -> str:
    """SHA-256 of the input matrices (shape and bytes) and an extra label (for example the symbol list)."""
    h = hashlib.sha256(extra.encode())
    for k in sorted(fields):
        a = np.ascontiguousarray(fields[k], dtype=np.float64)
        h.update(k.encode())
        h.update(str(a.shape).encode())
        h.update(a.tobytes())
    return h.hexdigest()


def _cmp(f, a, b):
    with np.errstate(invalid="ignore"):
        return np.where(np.isnan(a) | np.isnan(b), np.nan, f(a, b).astype(float))


def _eval(node: Node, args: list[np.ndarray], fields: dict[str, np.ndarray]) -> np.ndarray:
    op, p = node.op, node.params
    if op == "Field":
        return fields[p[0]]
    if op == "Const":
        return np.float64(p[0])
    a = args[0] if args else None
    with np.errstate(invalid="ignore", divide="ignore"):
        match op:
            case "Add":
                return a + args[1]
            case "Sub":
                return a - args[1]
            case "Mul":
                return a * args[1]
            case "Div":
                return a / args[1]
            case "Neg":
                return -a
            case "Gt" | "Lt" | "Ge" | "Le" | "Eq" | "Ne":
                f = {"Gt": np.greater, "Lt": np.less, "Ge": np.greater_equal, "Le": np.less_equal,
                     "Eq": np.equal, "Ne": np.not_equal}[op]
                return _cmp(f, np.broadcast_to(a, _shape(args)), np.broadcast_to(args[1], _shape(args)))
            case "Abs":
                return np.abs(a)
            case "Log":
                return np.where(a > 0, np.log(np.where(a > 0, a, 1.0)), np.nan)
            case "Sign":
                return np.sign(a)
            case "Greater":
                return np.where(np.isnan(a) | np.isnan(args[1]), np.nan, np.maximum(a, args[1]))
            case "Less":
                return np.where(np.isnan(a) | np.isnan(args[1]), np.nan, np.minimum(a, args[1]))
            case "If":
                return np.where(np.isnan(a), np.nan, np.where(a != 0, args[1], args[2]))
            case "CSRank":
                return ops.cs_rank(_mat(a, fields))
            case "CSZScore":
                return ops.cs_zscore(_mat(a, fields))
            case "Quantile":
                return ops.quantile(_mat(a, fields), p[0], p[1])
            case "Corr" | "Cov":
                f = ops.corr if op == "Corr" else ops.cov
                return f(_mat(a, fields), _mat(args[1], fields), p[0])
        f = {"Ref": ops.ref, "Delta": ops.delta, "Mean": ops.mean, "Sum": ops.tsum, "Std": ops.std, "Var": ops.var,
             "Max": ops.tmax, "Min": ops.tmin, "Rank": ops.trank, "IdxMax": ops.idxmax, "IdxMin": ops.idxmin,
             "Slope": ops.slope, "Rsquare": ops.rsquare, "Resi": ops.resi, "EMA": ops.ema}[op]
        return f(_mat(a, fields), p[0])


def _shape(args):
    return np.broadcast_shapes(*(np.shape(x) for x in args))


def _mat(a, fields):
    """A constant used where a matrix is needed becomes a full matrix."""
    if np.ndim(a) == 0:
        shape = next(iter(fields.values())).shape
        return np.full(shape, float(a))
    return a


class FeatureEngine:
    """`fields`: name ("open", "high", "low", "close", "volume", "vwap") -> (T, N) float64 matrix."""

    def __init__(self, fields: dict[str, np.ndarray], cache_dir: Path | None = None, data_key: str | None = None):
        self.fields = {k: np.asarray(v, dtype=np.float64) for k, v in fields.items()}
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.data_key = data_key or data_hash(self.fields)
        self.stats: dict[str, int] = {}

    def key(self, canon: str) -> str:
        return hashlib.sha256(f"{self.data_key}|{canon}|{ENGINE_VERSION}".encode()).hexdigest()

    def _path(self, canon: str) -> Path:
        k = self.key(canon)
        return self.cache_dir / k[:2] / f"{k}.npy"

    def compute(self, exprs: dict[str, str]) -> dict[str, np.ndarray]:
        """name -> expression string; returns name -> matrix. `stats`: nodes (all trees), unique (after reuse),
        computed (numpy calls this run), cache_hits (factors read from the cache)."""
        trees = {name: parse(e) for name, e in exprs.items()}
        canon = {name: canonical(t) for name, t in trees.items()}
        out: dict[str, np.ndarray] = {}
        todo = {}
        hits = 0
        for name, t in trees.items():
            p = self._path(canon[name]) if self.cache_dir else None
            if p is not None and p.exists():
                out[name] = np.load(p)
                hits += 1
            else:
                todo[name] = t
        order, uses = self._plan(todo.values())
        memo: dict[str, np.ndarray] = {}
        want: dict[str, list[str]] = {}
        for name, t in todo.items():
            want.setdefault(canonical(t), []).append(name)
        nodes = sum(len(subexpressions(t)) for t in trees.values())
        peak = 0
        for c, node in order:  # children first; a result is freed as soon as its last parent is computed
            memo[c] = _eval(node, [memo[canonical(a)] for a in node.args], self.fields)
            for a in node.args:
                ca = canonical(a)
                uses[ca] -= 1
                if uses[ca] == 0:
                    del memo[ca]
            for name in want.get(c, []):
                res = memo[c]
                res = np.where(np.isfinite(res), res, np.nan) if np.ndim(res) else np.full(
                    next(iter(self.fields.values())).shape, float(res))
                out[name] = res
                if self.cache_dir:
                    self._save(canon[name], res)
            if uses[c] == 0:
                del memo[c]
            peak = max(peak, len(memo))
        unique = len({canonical(n) for t in trees.values() for n in subexpressions(t)})
        self.stats = {"factors": len(trees), "nodes": nodes, "unique": unique, "computed": len(order),
                      "cache_hits": hits, "peak_live": peak}
        return {name: out[name] for name in exprs}

    @staticmethod
    def _plan(trees):
        """Unique nodes in an order where children come first, and how many parents use each."""
        order, seen, uses = [], set(), {}

        def visit(n):
            c = canonical(n)
            if c in seen:
                return
            seen.add(c)
            for a in n.args:
                visit(a)
                uses[canonical(a)] = uses.get(canonical(a), 0) + 1
            uses.setdefault(c, 0)
            order.append((c, n))

        for t in trees:
            visit(t)
        return order, uses

    def _save(self, canon: str, res: np.ndarray) -> None:
        p = self._path(canon)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.stem + ".tmp.npy")
        np.save(tmp, res)
        tmp.replace(p)  # atomic: a crash never leaves half a file under the real name
