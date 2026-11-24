"""The 158 price-volume factors of Qlib's Alpha158 set (Yang et al. 2020, "Qlib: An AI-oriented Quantitative
Investment Platform", arXiv:2009.11189; definitions from `qlib/contrib/data/loader.py`), written in our expression
language. 9 candle shapes (KBAR), 4 price ratios (PRICE) and 29 rolling families over 5 windows (145).

Differences from Qlib: a rolling window needs all of its values (Qlib often allows partial windows); a comparison
with a missing side is missing, not 0; `IdxMax` and `IdxMin` count from the oldest day of the window (1..d).
"""
from __future__ import annotations

WINDOWS = (5, 10, 20, 30, 60)
E = "1e-12"

KBAR = {
    "KMID": "($close-$open)/$open",
    "KLEN": "($high-$low)/$open",
    "KMID2": f"($close-$open)/($high-$low+{E})",
    "KUP": "($high-Greater($open,$close))/$open",
    "KUP2": f"($high-Greater($open,$close))/($high-$low+{E})",
    "KLOW": "(Less($open,$close)-$low)/$open",
    "KLOW2": f"(Less($open,$close)-$low)/($high-$low+{E})",
    "KSFT": "(2*$close-$high-$low)/$open",
    "KSFT2": f"(2*$close-$high-$low)/($high-$low+{E})",
}
PRICE = {"OPEN0": "$open/$close", "HIGH0": "$high/$close", "LOW0": "$low/$close", "VWAP0": "$vwap/$close"}

ROLLING = {
    "ROC": "Ref($close,{d})/$close",
    "MA": "Mean($close,{d})/$close",
    "STD": "Std($close,{d})/$close",
    "BETA": "Slope($close,{d})/$close",
    "RSQR": "Rsquare($close,{d})",
    "RESI": "Resi($close,{d})/$close",
    "MAX": "Max($high,{d})/$close",
    "MIN": "Min($low,{d})/$close",
    "QTLU": "Quantile($close,{d},0.8)/$close",
    "QTLD": "Quantile($close,{d},0.2)/$close",
    "RANK": "Rank($close,{d})",
    "RSV": f"($close-Min($low,{{d}}))/(Max($high,{{d}})-Min($low,{{d}})+{E})",
    "IMAX": "IdxMax($high,{d})/{d}",
    "IMIN": "IdxMin($low,{d})/{d}",
    "IMXD": "(IdxMax($high,{d})-IdxMin($low,{d}))/{d}",
    "CORR": "Corr($close,Log($volume+1),{d})",
    "CORD": "Corr($close/Ref($close,1),Log($volume/Ref($volume,1)+1),{d})",
    "CNTP": "Mean($close>Ref($close,1),{d})",
    "CNTN": "Mean($close<Ref($close,1),{d})",
    "CNTD": "Mean($close>Ref($close,1),{d})-Mean($close<Ref($close,1),{d})",
    "SUMP": f"Sum(Greater($close-Ref($close,1),0),{{d}})/(Sum(Abs($close-Ref($close,1)),{{d}})+{E})",
    "SUMN": f"Sum(Greater(Ref($close,1)-$close,0),{{d}})/(Sum(Abs($close-Ref($close,1)),{{d}})+{E})",
    "SUMD": f"(Sum(Greater($close-Ref($close,1),0),{{d}})-Sum(Greater(Ref($close,1)-$close,0),{{d}}))"
            f"/(Sum(Abs($close-Ref($close,1)),{{d}})+{E})",
    "VMA": f"Mean($volume,{{d}})/($volume+{E})",
    "VSTD": f"Std($volume,{{d}})/($volume+{E})",
    "WVMA": f"Std(Abs($close/Ref($close,1)-1)*$volume,{{d}})/(Mean(Abs($close/Ref($close,1)-1)*$volume,{{d}})+{E})",
    "VSUMP": f"Sum(Greater($volume-Ref($volume,1),0),{{d}})/(Sum(Abs($volume-Ref($volume,1)),{{d}})+{E})",
    "VSUMN": f"Sum(Greater(Ref($volume,1)-$volume,0),{{d}})/(Sum(Abs($volume-Ref($volume,1)),{{d}})+{E})",
    "VSUMD": f"(Sum(Greater($volume-Ref($volume,1),0),{{d}})-Sum(Greater(Ref($volume,1)-$volume,0),{{d}}))"
             f"/(Sum(Abs($volume-Ref($volume,1)),{{d}})+{E})",
}


def alpha158() -> dict[str, str]:
    """name -> expression for all 158 factors (rolling names carry the window: ROC5 ... VSUMD60)."""
    out = dict(KBAR) | dict(PRICE)
    for name, tpl in ROLLING.items():
        for d in WINDOWS:
            out[f"{name}{d}"] = tpl.format(d=d)
    return out
