"""SEC EDGAR access that respects the fair-access policy.

Every request carries a declared User-Agent read from the SEC_USER_AGENT environment variable (or a gitignored
`.env` file in the repo root). Requests are limited to well under 10 per second and cached on disk, so nothing is
downloaded twice. The User-Agent is never written into any committed file.
"""
from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = REPO_ROOT / "data"
SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
TICKERS = "https://www.sec.gov/files/company_tickers.json"
ARCHIVE = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}"


def user_agent() -> str:
    """The declared User-Agent. Raises if none is configured: we never send anonymous requests."""
    ua = os.environ.get("SEC_USER_AGENT")
    env_file = REPO_ROOT / ".env"
    if not ua and env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("SEC_USER_AGENT="):
                ua = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not ua or "@" not in ua:
        raise RuntimeError("Set SEC_USER_AGENT (e.g. in .env) to a string with a contact address before downloading.")
    return ua


@dataclass(frozen=True)
class Filing:
    cik: int
    accession: str
    form: str
    filing_date: str
    report_date: str
    primary_doc: str
    accepted: str = ""  # SEC acceptanceDateTime; true UTC (checked against the EDGAR header, which gives New York time)

    @property
    def url(self) -> str:
        return ARCHIVE.format(cik=self.cik, acc=self.accession.replace("-", ""), doc=self.primary_doc)


class EdgarClient:
    """Cached, rate-limited GET client. `session` is injectable so tests never touch the network."""

    def __init__(self, ua: str | None = None, cache_dir: Path | None = None, max_per_sec: float = 8.0,
                 session: requests.Session | None = None, sleep=time.sleep, clock=time.monotonic):
        self._ua = ua
        self.cache_dir = Path(cache_dir) if cache_dir else DATA_DIR / "raw"
        self.min_gap = 1.0 / max_per_sec
        self.session = session or requests.Session()
        self._sleep, self._clock = sleep, clock
        self._last = -1e9
        self.network_calls = 0

    def _cache_path(self, url: str) -> Path:
        h = hashlib.sha256(url.encode()).hexdigest()
        return self.cache_dir / h[:2] / h

    def get(self, url: str) -> bytes:
        path = self._cache_path(url)
        if path.exists():
            return path.read_bytes()
        wait = self.min_gap - (self._clock() - self._last)
        if wait > 0:
            self._sleep(wait)
        headers = {"User-Agent": self._ua or user_agent(), "Accept-Encoding": "gzip, deflate"}
        for attempt in range(4):
            self._last = self._clock()
            self.network_calls += 1
            resp = self.session.get(url, headers=headers, timeout=60)
            if resp.status_code in (429, 500, 502, 503, 504) and attempt < 3:
                self._sleep(2.0 * (attempt + 1))
                continue
            resp.raise_for_status()
            break
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(resp.content)
        return resp.content

    def get_json(self, url: str):
        import json

        return json.loads(self.get(url))


def tickers_to_ciks(client: EdgarClient) -> dict[str, int]:
    data = client.get_json(TICKERS)
    return {row["ticker"].upper(): int(row["cik_str"]) for row in data.values()}


def _filing_blocks(client: EdgarClient, cik: int, since: str) -> list[dict]:
    """The 'recent' block plus any older submission pages that overlap the period since `since`."""
    sub = client.get_json(SUBMISSIONS.format(cik=cik))
    blocks = [sub["filings"]["recent"]]
    for extra in sub["filings"].get("files", []):
        if extra.get("filingTo", "9999") >= since:
            blocks.append(client.get_json("https://data.sec.gov/submissions/" + extra["name"]))
    return blocks


def list_filings(client: EdgarClient, cik: int, forms: tuple[str, ...] = ("10-K",), since: str = "2019-01-01") -> list[Filing]:
    """Filings of the given forms filed on or after `since`, newest first, across all submission pages."""
    out = {}
    for block in _filing_blocks(client, cik, since):
        report = block.get("reportDate", [""] * len(block["form"]))
        accepted = block.get("acceptanceDateTime", [""] * len(block["form"]))
        for i, form in enumerate(block["form"]):
            if form in forms and block["filingDate"][i] >= since:
                acc = block["accessionNumber"][i]
                out[acc] = Filing(cik, acc, form, block["filingDate"][i], report[i], block["primaryDocument"][i],
                                  accepted[i])
    return sorted(out.values(), key=lambda f: f.filing_date, reverse=True)


def download_filing_html(client: EdgarClient, filing: Filing) -> str:
    return client.get(filing.url).decode("utf-8", errors="replace")
