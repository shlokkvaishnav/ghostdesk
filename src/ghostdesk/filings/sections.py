"""Split report text into its numbered items ("Item 1A", "Item 7", ...).

The text must have one heading per line (see `signal.features.prose`). A table of contents and running page headers
repeat the headings, so for each item the longest span wins.
"""
from __future__ import annotations

import re

ITEM_RE = re.compile(r"(?im)^\s*item\s+(\d{1,2}[abc]?)(?![\da-z])\s*[.:\-–—]?\s*(.*)$")


def split_sections(text: str, max_heading: int | None = None) -> dict[str, str]:
    """Map 'item_1a' etc. to the section text.

    Consecutive marks of the same item (a running page header such as "Item 7" repeated on every page) belong to one
    section, which runs to the next *different* item. A table of contents repeats every heading, so for each item the
    section with the longest span wins. With `max_heading`, a mark counts only if its line is at most that many
    characters: a cross-reference that starts a line ("Item 7, Management's Discussion ... of this report") is a
    long sentence, not a heading.
    """
    def line_len(i):
        j = text.find("\n", i)
        return (len(text) if j < 0 else j) - i

    marks = [(m.start(), f"item_{m.group(1).lower()}") for m in ITEM_RE.finditer(text)
             if max_heading is None or line_len(m.start()) <= max_heading]
    best: dict[str, tuple[int, str]] = {}
    i = 0
    while i < len(marks):
        j = i
        while j + 1 < len(marks) and marks[j + 1][1] == marks[i][1]:
            j += 1
        end = marks[j + 1][0] if j + 1 < len(marks) else len(text)
        body = text[marks[i][0]:end]
        if marks[i][1] not in best or len(body) > best[marks[i][1]][0]:
            best[marks[i][1]] = (len(body), body)
        i = j + 1
    return {k: v[1] for k, v in best.items()}
