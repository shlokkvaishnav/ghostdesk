"""A small expression language for features, in the style of Qlib (decision D28), parsed to an AST.

    Rank(Ref($close, 5) / $close)            cross-sectional rank of the 5-day reversal
    Corr($close, Log($volume + 1), 20)       20-day correlation of price and log volume

Grammar: numbers, fields (`$open $high $low $close $volume $vwap`), `+ - * /`, comparisons `> < >= <= == !=`
(1.0 or 0.0; NaN if a side is NaN), unary minus, parentheses, and the functions in `SIGNATURES`. A function has
expression arguments first, then numeric parameters (window lengths, a quantile). `Rank(x)` with one argument is the
cross-sectional rank; `Rank(x, d)` is the rank of today's value in its own last d days. `Ref(x, d)` needs d >= 0, so
no expression can read a later session.

`canonical(node)` is a unique string for a tree: arguments of `+`, `*`, `Greater` and `Less` are sorted (these are
exactly commutative in floating point), so equal subexpressions are found and computed once by the engine.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cache

FIELDS = ("open", "high", "low", "close", "volume", "vwap")
# name -> (expression arguments, numeric parameters)
SIGNATURES = {
    "Ref": (1, 1), "Delta": (1, 1), "Mean": (1, 1), "Sum": (1, 1), "Std": (1, 1), "Var": (1, 1), "Max": (1, 1),
    "Min": (1, 1), "Rank": (1, 1), "IdxMax": (1, 1), "IdxMin": (1, 1), "Slope": (1, 1), "Rsquare": (1, 1),
    "Resi": (1, 1), "EMA": (1, 1), "Quantile": (1, 2), "Corr": (2, 1), "Cov": (2, 1), "Abs": (1, 0),
    "Log": (1, 0), "Sign": (1, 0), "CSRank": (1, 0), "CSZScore": (1, 0), "Greater": (2, 0), "Less": (2, 0),
    "If": (3, 0),
}
BINARY = {"+": "Add", "-": "Sub", "*": "Mul", "/": "Div", ">": "Gt", "<": "Lt", ">=": "Ge", "<=": "Le",
          "==": "Eq", "!=": "Ne"}
COMMUTATIVE = {"Add", "Mul", "Greater", "Less", "Eq", "Ne"}
TOKEN = re.compile(r"\s*(?:(\d+\.?\d*(?:[eE][-+]?\d+)?|\.\d+(?:[eE][-+]?\d+)?)|(\$[a-z]+)|([A-Za-z_]\w*)"
                   r"|(>=|<=|==|!=|[-+*/(),<>]))")


class ExprError(ValueError):
    """A syntax error, an unknown name, or a wrong number of arguments."""


@dataclass(frozen=True)
class Node:
    op: str                      # "Field", "Const", a function name, or a binary name (Add, Gt, ...)
    args: tuple = ()             # child nodes
    params: tuple = ()           # numbers: the field name for Field, the value for Const, windows for functions


def tokenize(text: str) -> list[str]:
    out, pos = [], 0
    text = text.strip()
    while pos < len(text):
        m = TOKEN.match(text, pos)
        if not m or m.end() == pos:
            raise ExprError(f"cannot read {text[pos:pos + 10]!r} at position {pos}")
        out.append(next(g for g in m.groups() if g is not None))
        pos = m.end()
    return out


class _Parser:
    def __init__(self, tokens):
        self.t, self.i = tokens, 0

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else None

    def take(self, want=None):
        tok = self.peek()
        if tok is None or (want is not None and tok != want):
            raise ExprError(f"expected {want or 'more input'}, found {tok!r}")
        self.i += 1
        return tok

    def expr(self):
        left = self.add()
        if self.peek() in (">", "<", ">=", "<=", "==", "!="):
            op = self.take()
            left = Node(BINARY[op], (left, self.add()))
        return left

    def add(self):
        left = self.mul()
        while self.peek() in ("+", "-"):
            op = self.take()
            left = Node(BINARY[op], (left, self.mul()))
        return left

    def mul(self):
        left = self.unary()
        while self.peek() in ("*", "/"):
            op = self.take()
            left = Node(BINARY[op], (left, self.unary()))
        return left

    def unary(self):
        if self.peek() == "-":
            self.take()
            return Node("Neg", (self.unary(),))
        return self.atom()

    def atom(self):
        tok = self.take()
        if tok == "(":
            node = self.expr()
            self.take(")")
            return node
        if tok.startswith("$"):
            if tok[1:] not in FIELDS:
                raise ExprError(f"unknown field {tok}")
            return Node("Field", params=(tok[1:],))
        if tok[0].isdigit() or tok[0] == ".":
            return Node("Const", params=(float(tok),))
        if tok not in SIGNATURES:
            raise ExprError(f"unknown function {tok}")
        self.take("(")
        items = [self.expr()]
        while self.peek() == ",":
            self.take()
            items.append(self.expr())
        self.take(")")
        return _call(tok, items)


def _call(name: str, items: list[Node]) -> Node:
    if name == "Rank" and len(items) == 1:
        name = "CSRank"
    n_args, n_par = SIGNATURES[name]
    if len(items) != n_args + n_par:
        raise ExprError(f"{name} takes {n_args + n_par} arguments, got {len(items)}")
    params = []
    for p in items[n_args:]:
        if p.op != "Const":
            raise ExprError(f"{name}: parameter must be a number")
        params.append(p.params[0])
    if name == "Quantile":
        params = [int(params[0]), params[1]]
        if not 0 <= params[1] <= 1:
            raise ExprError("Quantile: q must be in [0, 1]")
    else:
        params = [int(v) for v in params]
    if n_par and name != "Ref" and params[0] < 1:
        raise ExprError(f"{name}: window must be >= 1")
    if name in ("Ref", "Delta") and params[0] < 0:
        raise ExprError(f"{name} with a negative lag would read a later session")
    return Node(name, tuple(items[:n_args]), tuple(params))


def parse(text: str) -> Node:
    p = _Parser(tokenize(text))
    node = p.expr()
    if p.peek() is not None:
        raise ExprError(f"unexpected {p.peek()!r}")
    return node


@cache
def canonical(node: Node) -> str:
    if node.op == "Field":
        return "$" + node.params[0]
    if node.op == "Const":
        return repr(float(node.params[0]))
    args = [canonical(a) for a in node.args]
    if node.op in COMMUTATIVE:
        args.sort()
    return f"{node.op}({','.join(args + [repr(p) for p in node.params])})"


def subexpressions(node: Node) -> list[Node]:
    """Every node of the tree, children first."""
    out = []
    for a in node.args:
        out += subexpressions(a)
    return out + [node]


def lookback(node: Node) -> int:
    """Sessions of history the expression needs before its first value (sum of windows along the deepest path)."""
    own = {"Ref": lambda p: p[0], "Delta": lambda p: p[0]}.get(node.op, lambda p: (p[0] - 1) if p else 0)
    extra = own(node.params) if node.op not in ("Field", "Const") else 0
    return extra + max((lookback(a) for a in node.args), default=0)
