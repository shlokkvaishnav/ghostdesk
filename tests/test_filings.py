import json

import pytest

from ghostdesk.filings import edgar
from ghostdesk.filings.chunking import chunk_filing, chunk_section, html_to_text, split_sections
from ghostdesk.filings.edgar import EdgarClient, list_filings


class Resp:
    def __init__(self, content=b"{}", status=200):
        self.content, self.status_code = content, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class StubSession:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []

    def get(self, url, headers=None, timeout=None):
        self.calls.append((url, headers))
        return self.responses.pop(0)


def make_client(tmp_path, responses, clock=None):
    t = {"now": 0.0}
    sleeps = []
    client = EdgarClient(ua="test-agent a@b.c", cache_dir=tmp_path, max_per_sec=8.0, session=StubSession(responses),
                         sleep=lambda s: (sleeps.append(s), t.__setitem__("now", t["now"] + s)),
                         clock=lambda: t["now"])
    return client, sleeps



HTML = """<html><body>
<p>TABLE OF CONTENTS</p><p>Item 1A. Risk Factors</p><p>Item 7. Management Discussion</p>
<div>Item 1A. Risk Factors</div>
<p>We face competition. Our results depend on demand for our products and on supply chain stability.</p>
<div>Item 7. Management Discussion and Analysis</div>
<p>Revenue grew in 2023.</p>
<table><tr><td>Net sales</td><td>$</td><td>383,285</td><td>394,328</td></tr><tr><td>Net income</td><td>96,995</td><td>99,803</td></tr></table>
<p>Operating margin improved.</p>
</body></html>"""

def test_cache_means_each_url_is_fetched_once(tmp_path):
    client, _ = make_client(tmp_path, [Resp(b"hello")])
    assert client.get("https://x/a") == b"hello"
    assert client.get("https://x/a") == b"hello"
    assert client.network_calls == 1


def test_requests_are_rate_limited_and_carry_a_user_agent(tmp_path):
    client, sleeps = make_client(tmp_path, [Resp(b"1"), Resp(b"2"), Resp(b"3")])
    for u in ("a", "b", "c"):
        client.get(f"https://x/{u}")
    assert len(sleeps) >= 2 and all(s >= 1 / 8.0 - 1e-9 for s in sleeps[:2])
    assert all(h["User-Agent"] == "test-agent a@b.c" for _, h in client.session.calls)


def test_retries_on_429_then_succeeds(tmp_path):
    client, sleeps = make_client(tmp_path, [Resp(status=429), Resp(b"ok")])
    assert client.get("https://x/r") == b"ok" and client.network_calls == 2 and max(sleeps) >= 2.0


def test_refuses_to_run_without_a_user_agent(monkeypatch, tmp_path):
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    monkeypatch.setattr(edgar, "REPO_ROOT", tmp_path)
    with pytest.raises(RuntimeError, match="SEC_USER_AGENT"):
        edgar.user_agent()


def test_user_agent_is_read_from_env_file(monkeypatch, tmp_path):
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    (tmp_path / ".env").write_text('SEC_USER_AGENT="proj contact@example.org"\n')
    monkeypatch.setattr(edgar, "REPO_ROOT", tmp_path)
    assert edgar.user_agent() == "proj contact@example.org"


SUBMISSIONS = {"filings": {"recent": {
    "form": ["10-K", "10-Q", "10-K", "10-K"], "filingDate": ["2023-11-03", "2023-08-04", "2022-10-28", "2017-11-03"],
    "accessionNumber": ["0000320193-23-000106", "x", "0000320193-22-000108", "old"],
    "reportDate": ["2023-09-30", "", "2022-09-24", "2017-09-30"], "primaryDocument": ["a.htm", "q.htm", "b.htm", "o.htm"]},
    "files": []}}


def test_list_filings_filters_form_and_date(tmp_path):
    client, _ = make_client(tmp_path, [Resp(json.dumps(SUBMISSIONS).encode())])
    fl = list_filings(client, 320193, since="2019-01-01")
    assert [f.accession for f in fl] == ["0000320193-23-000106", "0000320193-22-000108"]
    assert fl[0].url.endswith("/320193/000032019323000106/a.htm")


def _fact(end, val, filed, fp="FY", form="10-K", start=None):
    d = {"end": end, "val": val, "accn": "acc-" + filed, "fy": 2023, "fp": fp, "form": form, "filed": filed}
    if start:
        d["start"] = start
    return d


def test_html_to_text_keeps_table_rows_together():
    text = html_to_text(HTML)
    assert "[TABLE]\nNet sales | 383,285 | 394,328\nNet income | 96,995 | 99,803" in text


def test_section_split_skips_the_table_of_contents():
    secs = split_sections(html_to_text(HTML))
    assert "competition" in secs["item_1a"] and "Revenue grew" in secs["item_7"]
    assert len(secs["item_1a"]) > len("Item 1A. Risk Factors") + 20


def test_chunking_tables_stay_whole_and_text_is_bounded():
    ch = chunk_filing(HTML, 1, "acc")
    tables = [c for c in ch if c.kind == "table"]
    assert len(tables) == 1 and "383,285" in tables[0].text and "394,328" in tables[0].text
    assert all(len(c.text.split()) <= 4 * 220 for c in ch)


def test_long_paragraph_is_split_with_overlap_and_loses_no_words():
    words = [f"w{i}" for i in range(1000)]
    ch = chunk_section(" ".join(words), "item_7", 1, "acc", max_words=220, overlap=30)
    assert all(len(c.text.split()) <= 220 for c in ch) and len(ch) >= 5
    assert {w for c in ch for w in c.text.split()} == set(words)
    assert ch[0].text.split()[-30:] == ch[1].text.split()[:30]


def test_list_filings_follows_older_submission_pages(tmp_path):
    main = {"filings": {"recent": {"form": ["10-K"], "filingDate": ["2024-02-01"], "accessionNumber": ["a1"],
                                   "reportDate": ["2023-12-31"], "primaryDocument": ["x.htm"]},
                        "files": [{"name": "CIK0000000001-submissions-001.json", "filingTo": "2021-06-30"},
                                  {"name": "CIK0000000001-submissions-002.json", "filingTo": "2015-01-01"}]}}
    older = {"form": ["10-K", "8-K"], "filingDate": ["2020-02-10", "2020-03-01"], "accessionNumber": ["a0", "z"],
             "reportDate": ["2019-12-31", ""], "primaryDocument": ["y.htm", "z.htm"]}
    client, _ = make_client(tmp_path, [Resp(json.dumps(main).encode()), Resp(json.dumps(older).encode())])
    fl = list_filings(client, 1, since="2019-01-01")
    assert [f.accession for f in fl] == ["a1", "a0"]
    assert client.network_calls == 2  # the page ending in 2015 is never requested


def test_running_page_headers_do_not_cut_a_section_short():
    page = "x " * 300
    text = (f"Item 7. Management's Discussion\n{page}\n\nItem 7\n{page}\n\nItem 7\n{page}\n\n"
            f"Item 8. Financial Statements\nstatements\n")
    secs = split_sections(text)
    assert len(secs["item_7"].split()) > 900 and "Item 8" not in secs["item_7"]


def test_item_15_is_chunked_when_item_8_only_points_to_it():
    big = "Revenue | 130,497 | 60,922\n" * 2000
    html = ("<html><body><p>Item 1A. Risk Factors</p><p>risks</p><p>Item 7. MD&A</p><p>text</p>"
            "<p>Item 8. Financial Statements</p><p>See Item 15.</p><p>Item 15. Exhibits</p>"
            f"<table><tr><td>{big}</td></tr></table></body></html>")
    assert any(c.section == "item_15" for c in chunk_filing(html, 1, "acc"))


def test_whole_document_fallback_when_financial_items_are_tiny():
    html = "<html><body><p>Item 7. MD&A</p><p>see financial section</p><p>Item 8. Statements</p><p>see financial section</p>" \
           "<p>FINANCIAL SECTION</p><p>" + "Net income was 34,457. " * 400 + "</p></body></html>"
    ch = chunk_filing(html, 1, "acc")
    assert {c.section for c in ch} == {"full"} and any("34,457" in c.text for c in ch)


def test_item_numbers_10_to_15_are_not_read_as_item_1():
    text = "Item 1. Business\nb\n\nItem 1A. Risk\nr\n\nItem 10. Directors\nd\n\nItem 15. Exhibits\ne\n\nItem 7A. Market risk\nm\n"
    assert set(split_sections(text)) == {"item_1", "item_1a", "item_10", "item_15", "item_7a"}


