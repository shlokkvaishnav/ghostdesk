"""SEC client: cache, rate limit, retries, User-Agent, submission pages."""
import json

import pytest

from ghostdesk.filings import edgar_client
from ghostdesk.filings.edgar_client import EdgarClient, list_filings


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
    monkeypatch.setattr(edgar_client, "REPO_ROOT", tmp_path)
    with pytest.raises(RuntimeError, match="SEC_USER_AGENT"):
        edgar_client.user_agent()


def test_user_agent_is_read_from_env_file(monkeypatch, tmp_path):
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    (tmp_path / ".env").write_text('SEC_USER_AGENT="proj contact@example.org"\n')
    monkeypatch.setattr(edgar_client, "REPO_ROOT", tmp_path)
    assert edgar_client.user_agent() == "proj contact@example.org"


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
