"""Filing HTML -> clean text -> sections -> chunks. Tables are kept whole as their own chunks."""
from __future__ import annotations

import re
from dataclasses import dataclass

from bs4 import BeautifulSoup

TABLE_MARK = "[TABLE]"
ITEM_RE = re.compile(r"(?im)^\s*item\s+(\d{1,2}[abc]?)(?![\da-z])\s*[.:\-–—]?\s*(.*)$")


def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for t in soup(["script", "style"]):
        t.decompose()
    for t in soup.find_all(["ix:header"]):
        t.decompose()
    for table in soup.find_all("table"):
        rows = []
        for tr in table.find_all("tr"):
            cells = [re.sub(r"\s+", " ", c.get_text(" ", strip=True)) for c in tr.find_all(["td", "th"])]
            cells = [c for c in cells if c and c not in {"$", ")", "%"}]
            if cells:
                rows.append(" | ".join(cells))
        table.replace_with(soup.new_string("\n\n" + TABLE_MARK + "\n" + "\n".join(rows) + "\n\n"))
    text = soup.get_text("\n")
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


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


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    text: str
    section: str
    kind: str  # "text" or "table"
    cik: int
    accession: str


def chunk_section(body: str, section: str, cik: int, accession: str, max_words: int = 220, overlap: int = 30) -> list[Chunk]:
    chunks: list[Chunk] = []
    blocks = [b.strip() for b in re.split(r"\n\s*\n", body) if b.strip()]

    def emit(text: str, kind: str):
        chunks.append(Chunk(f"{accession}:{section}:{len(chunks)}", text, section, kind, cik, accession))

    buf: list[str] = []
    for block in blocks:
        if block.startswith(TABLE_MARK):
            if buf:
                emit(" ".join(buf), "text")
                buf = []
            rows = block[len(TABLE_MARK):].strip().split("\n")
            cur: list[str] = []
            for row in rows:  # a very long table is split by rows, never mid-row
                cur.append(row)
                if sum(len(r.split()) for r in cur) >= 4 * max_words:
                    emit("\n".join(cur), "table")
                    cur = []
            if cur:
                emit("\n".join(cur), "table")
            continue
        words = block.split()
        if len(buf) + len(words) <= max_words:
            buf.extend(words)
            continue
        if buf:
            emit(" ".join(buf), "text")
            buf = buf[-overlap:] if overlap else []
        words = buf + words  # carry the overlap into the next chunk
        step = max_words - overlap
        i = 0
        while len(words) - i > max_words:  # a block longer than one chunk is cut into overlapping windows
            emit(" ".join(words[i: i + max_words]), "text")
            i += step
        buf = words[i:]
    if buf:
        emit(" ".join(buf), "text")
    return chunks


FINANCIAL_ITEMS = ("item_7", "item_8", "item_15")
MIN_FINANCIAL_CHARS = 30_000


def chunk_filing(html: str, cik: int, accession: str, sections=("item_1a", "item_7", "item_8", "item_15")) -> list[Chunk]:
    """Chunk the risk-factor and financial sections. Some filings (e.g. Exxon) keep their financial statements in a
    separate section that carries no Item 7/8/15 heading; if the financial items are tiny, the whole document is
    chunked instead (section "full") so that nothing is silently missing."""
    text = html_to_text(html)
    secs = split_sections(text)
    if sum(len(secs.get(k, "")) for k in FINANCIAL_ITEMS) < MIN_FINANCIAL_CHARS:
        return chunk_section(text, "full", cik, accession)
    out: list[Chunk] = []
    for name in sections:
        if name in secs:
            out.extend(chunk_section(secs[name], name, cik, accession))
    return out
