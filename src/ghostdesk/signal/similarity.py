"""How much did a report's text change since the earlier report? The measures of Cohen, Malloy and Nguyen (2020).

All measures are similarities in [0, 1]: 1 = the same text, lower = more change. "Lazy prices": firms whose reports
change a lot tend to do worse later.

- `cosine`: cosine of the two word-count vectors.
- `jaccard`: shared distinct words / all distinct words.
- `edit`: share of words in sentences that are the same in both reports, found with a sentence-level diff
  (`difflib`). The paper uses a word-level minimum edit distance; on 50,000-word reports a word-level diff is very
  slow, so sentences are the unit here. This is a stated change, and the other two measures are as in the paper.
"""
from __future__ import annotations

import difflib
import math
import re
from collections import Counter

WORD = re.compile(r"[a-z]+")
SENT = re.compile(r"(?<=[.!?;])\s+|\n+")


def words(text: str) -> list[str]:
    return WORD.findall(text.lower())


def cosine(a: str, b: str) -> float:
    ca, cb = Counter(words(a)), Counter(words(b))
    if not ca or not cb:
        return float("nan")
    dot = sum(v * cb[w] for w, v in ca.items())
    return dot / (math.sqrt(sum(v * v for v in ca.values())) * math.sqrt(sum(v * v for v in cb.values())))


def jaccard(a: str, b: str) -> float:
    sa, sb = set(words(a)), set(words(b))
    if not sa or not sb:
        return float("nan")
    return len(sa & sb) / len(sa | sb)


def sentences(text: str) -> list[str]:
    """Sentences as normalised word strings (case, punctuation and spacing do not count as change)."""
    out = (" ".join(words(s)) for s in SENT.split(text))
    return [s for s in out if s]


def edit(a: str, b: str) -> float:
    sa, sb = sentences(a), sentences(b)
    total = sum(len(s.split()) for s in sa) + sum(len(s.split()) for s in sb)
    if not total:
        return float("nan")
    m = difflib.SequenceMatcher(None, sa, sb, autojunk=False)
    same = sum(len(s.split()) for blk in m.get_matching_blocks() for s in sa[blk.a:blk.a + blk.size])
    return 2 * same / total


MEASURES = {"cosine": cosine, "jaccard": jaccard, "edit": edit}


def all_measures(a: str, b: str) -> dict[str, float]:
    return {k: f(a, b) for k, f in MEASURES.items()}
