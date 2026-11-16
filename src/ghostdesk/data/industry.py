"""Industry of each company from its SEC SIC code (in the submissions JSON; the current code of the CIK).

GICS sectors exist only for current members, so they would treat removed companies differently. The SIC code exists
for every CIK. Groups: the 2-digit SIC major group when it has at least `min_size` stocks in the month, else the SIC
division (the standard SIC divisions A-J). The SIC code is today's code of the CIK, a stated limit.
"""
from __future__ import annotations

import pandas as pd

DIVISIONS = [(1, 9, "A agriculture"), (10, 14, "B mining"), (15, 17, "C construction"), (20, 39, "D manufacturing"),
             (40, 49, "E transport and utilities"), (50, 51, "F wholesale"), (52, 59, "G retail"),
             (60, 67, "H finance"), (70, 89, "I services"), (91, 99, "J public administration")]


def major_group(sic) -> str:
    """4-digit SIC (leading zeros may be missing: 100 = 0100) -> its 2-digit major group, or "unknown"."""
    s = str(sic).strip()
    return s.zfill(4)[:2] if s.isdigit() and 1 <= len(s) <= 4 else "unknown"


def sic_division(sic) -> str:
    """4-digit SIC -> its division ("unknown" when missing or out of range)."""
    g = major_group(sic)
    if g == "unknown":
        return g
    return next((name for lo, hi, name in DIVISIONS if lo <= int(g) <= hi), "unknown")


def industry_groups(sic: pd.Series, min_size: int = 10) -> pd.Series:
    """For the stocks of one month: the 2-digit major group if it has >= min_size stocks, else the division."""
    major = sic.map(major_group)
    size = major.map(major.value_counts())
    return major.where(size >= min_size, sic.map(sic_division))
