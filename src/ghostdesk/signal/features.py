"""Text-change features for one pair of reports (this report and its like-with-like earlier report).

Tables are removed first: they hold numbers, and the measures are about words. The measures are computed on the
full text and on two sections that the paper finds most informative:
- risk factors: Item 1A (10-K Part I, 10-Q Part II);
- management's discussion (MD&A): Item 7 in a 10-K, Item 2 (Part I) in a 10-Q.
A section that is not found in both reports gives NaN, not a guess.
"""
from __future__ import annotations

import re

import lxml.html

from ..filings.sections import split_sections
from .similarity import MEASURES, words

SECTIONS = {"10-K": {"risk": "item_1a", "mdna": "item_7"}, "10-Q": {"risk": "item_1a", "mdna": "item_2"}}
MIN_SECTION_WORDS = 200  # shorter "sections" are usually a table-of-contents line or "not applicable"
MAX_HEADING = 160  # characters; a longer line that starts with "Item 7" is a cross-reference
BLOCK = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6", "table", "ul", "ol", "center", "pre",
         "blockquote", "section", "article"}
WS = re.compile(r"\s+")
NUMBER = re.compile(r"^[\s$€£()%.,\-–—0-9]*$")


def _numeric_table(t) -> bool:
    """A table of numbers (most non-empty cells are numbers), not a layout table that holds text."""
    cells = [c.text_content().strip() for c in t.iter("td", "th")]
    cells = [c for c in cells if c]
    return bool(cells) and sum(bool(NUMBER.match(c)) for c in cells) / len(cells) >= 0.3


def prose(html: str) -> str:
    """Report HTML -> text without number tables. New lines only at block elements, so a heading split over several
    inline elements ("<span>Item</span> <span>1A.</span>") stays on one line."""
    doc = lxml.html.document_fromstring(html.encode("utf-8", errors="replace") if isinstance(html, str) else html)
    for el in list(doc.iter("script", "style", "{*}header", "ix:header")):
        el.drop_tree()
    for t in [t for t in doc.iter("table") if _numeric_table(t)]:
        t.drop_tree()
    for el in doc.iter():  # source line wraps (old reports wrap at ~80 columns) are not line breaks
        if el.text:
            el.text = WS.sub(" ", el.text)
        if el.tail:
            el.tail = WS.sub(" ", el.tail)
    for el in doc.iter():
        if isinstance(el.tag, str) and el.tag.lower() in BLOCK:
            el.tail = "\n" + (el.tail or "")
            if el.tag.lower() in ("td", "th"):
                el.tail = " " + (el.tail or "")
    text = doc.text_content().replace("\xa0", " ")
    lines = (re.sub(r"\s+", " ", ln).strip() for ln in text.split("\n"))
    return "\n".join(ln for ln in lines if ln)


def parts(html: str, form: str) -> dict[str, str]:
    """{"full": text, "risk": ..., "mdna": ...}; a missing or very short section is left out."""
    text = prose(html)
    sec = split_sections(text, max_heading=MAX_HEADING)
    out = {"full": text}
    for name, item in SECTIONS[form.removesuffix("/A")].items():
        body = sec.get(item, "")
        if len(words(body)) >= MIN_SECTION_WORDS:
            out[name] = body
    return out


def pair_features(cur: dict[str, str], prev: dict[str, str]) -> dict[str, float]:
    """sim_<part>_<measure> for each part found in both reports, and the word counts of both."""
    f: dict[str, float] = {}
    for part in ("full", "risk", "mdna"):
        a, b = cur.get(part), prev.get(part)
        for m, fn in MEASURES.items():
            f[f"sim_{part}_{m}"] = fn(a, b) if a and b else float("nan")
        f[f"words_{part}"] = float(len(words(a))) if a else float("nan")
        f[f"words_{part}_prev"] = float(len(words(b))) if b else float("nan")
    return f
