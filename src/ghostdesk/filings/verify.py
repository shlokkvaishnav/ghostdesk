"""Extract numeric claims from answers and check them against XBRL values.

A claim is a printed money amount or per-share figure: "$260.2 billion", "260,174 million", "$3.28", "(1,234)".
Bare small integers, years and dates are not claims. A claim matches a value when the difference is within half a unit of
the last printed digit (so "$260.2 billion" matches 260,174,000,000) and the claim has at least 3 significant digits
(so "$260 billion" matches, but "$0.3 trillion" is too vague to count). Signs are ignored: filings print losses in
parentheses or as "net loss of", and the comparison is on magnitude.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

SCALES = {"thousand": 1e3, "k": 1e3, "million": 1e6, "mn": 1e6, "mm": 1e6, "m": 1e6, "billion": 1e9, "bn": 1e9,
          "b": 1e9, "trillion": 1e12, "tn": 1e12, "t": 1e12}
_NUM = re.compile(
    r"(?P<neg>-|\()?\s*(?P<cur>\$|USD\s?)?\s*\(?(?<![\w.,:/])(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"\)?(?:\s*(?P<scale>thousand|million|billion|trillion|mn|mm|bn|tn|[kmbt])\b)?(?P<pct>\s*%|\s*percent)?",
    re.IGNORECASE,
)
_CITE = re.compile(r"\[[^\]]*\]")
REFUSAL = re.compile(r"\b(insufficient evidence|not (?:found|stated|disclosed|provided|available)|cannot (?:find|determine|answer)|"
                     r"do(?:es)? not (?:contain|include|state|provide)|no information)\b", re.IGNORECASE)


@dataclass(frozen=True)
class Claim:
    value: float  # magnitude in units (USD or USD per share)
    half_unit: float  # half of the last printed digit, in units
    sig_digits: int
    text: str


def _sig_digits(digits: str) -> int:
    d = digits.replace(",", "").replace(".", "").lstrip("0")
    return len(d)


def extract_claims(answer: str) -> list[Claim]:
    claims = []
    answer = _CITE.sub(" ", answer)  # citations such as [0000320193-19-000119:item_7:6] are not claims
    for m in _NUM.finditer(answer):
        if m["pct"]:
            continue
        num, cur, scale = m["num"], m["cur"], (m["scale"] or "").lower()
        has_group = "," in num
        if not (cur or scale or has_group) and len(num.split(".")[0]) < 5:
            continue  # "2019", "28", "10-K": not money claims; a bare 260174000000 is one
        if not cur and not has_group and scale in ("m", "b", "t", "k"):
            continue  # "3 b" in prose is too ambiguous without a currency sign
        mult = SCALES.get(scale, 1.0)
        plain = num.replace(",", "")
        decimals = len(plain.split(".")[1]) if "." in plain else 0
        value = abs(float(plain)) * mult
        claims.append(Claim(value, 0.5 * 10 ** (-decimals) * mult, _sig_digits(num), m.group(0).strip()))
    return claims


def matches(claim: Claim, value: float, concept: str = "") -> bool:
    v = abs(value)
    if concept == "eps_diluted":
        return claim.half_unit <= 0.005 + 1e-12 and abs(claim.value - v) <= 0.005 + 1e-9
    if claim.sig_digits < 3:
        return False
    return abs(claim.value - v) <= claim.half_unit * (1 + 1e-9) + 1e-9 * max(1.0, v)


def verify_answer(answer: str, gold_value: float, concept: str = "") -> dict:
    """Status of an answer to a question with one gold value:
    'correct' (some claim matches), 'wrong' (claims, none match), 'refused' (no claim, refusal wording),
    'no_number' (no claim and no refusal)."""
    claims = extract_claims(answer)
    if any(matches(c, gold_value, concept) for c in claims):
        status = "correct"
    elif claims:
        status = "wrong"
    elif REFUSAL.search(answer):
        status = "refused"
    else:
        status = "no_number"
    return {"status": status, "claims": [c.text for c in claims]}


def unsupported_claims(answer: str, facts: list[float], concept: str = "") -> list[str]:
    """Claims that match none of the given XBRL values (for example all facts of the company and period)."""
    return [c.text for c in extract_claims(answer) if not any(matches(c, f, concept) for f in facts)]
