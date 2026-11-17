"""How much did a report's text change since the earlier report? The measures of Cohen, Malloy and Nguyen (2020).

All measures are similarities in [0, 1]: 1 = the same text, lower = more change. "Lazy prices": firms whose reports
change a lot tend to do worse later.

- `cosine`: cosine of the two word-count vectors.
- `jaccard`: shared distinct words / all distinct words.
- `edit`: share of words that are the same in both reports, in order (`difflib`). The paper uses a word-level
  minimum edit distance. A word-level diff of two 50,000-word reports is very slow, so sentences are aligned first
  and words are aligned only inside the blocks of changed sentences. The result is close to a word-level diff; it
  differs when text moves between distant places.
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


MAX_BLOCK_WORDS = 5000  # a replaced block longer than this is counted as fully changed (bounds the run time)


def edit(a: str, b: str) -> float:
    """2 * same words / all words. Sentences are aligned first; inside each replaced block of sentences the words
    are aligned, so a sentence that changes by one number counts as one changed word, not a changed sentence."""
    sa, sb = sentences(a), sentences(b)
    total = sum(len(s.split()) for s in sa) + sum(len(s.split()) for s in sb)
    if not total:
        return float("nan")
    same = 0
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, sa, sb, autojunk=False).get_opcodes():
        if op == "equal":
            same += sum(len(s.split()) for s in sa[i1:i2])
        elif op == "replace":
            wa, wb = " ".join(sa[i1:i2]).split(), " ".join(sb[j1:j2]).split()
            if len(wa) <= MAX_BLOCK_WORDS and len(wb) <= MAX_BLOCK_WORDS:
                same += sum(m.size for m in difflib.SequenceMatcher(None, wa, wb, autojunk=False).get_matching_blocks())
    return 2 * same / total


MEASURES = {"cosine": cosine, "jaccard": jaccard, "edit": edit}


def all_measures(a: str, b: str) -> dict[str, float]:
    return {k: f(a, b) for k, f in MEASURES.items()}
