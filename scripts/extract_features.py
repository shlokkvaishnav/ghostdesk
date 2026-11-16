"""Text-change features and own-period XBRL values for every paired report of the universe. Only the features are
kept (data/features/shard_<i>.parquet), not the report text, and report pages are not added to the disk cache.

Resumable: the shard file is rewritten after every 10 CIKs, and a rerun skips the CIKs already in it. One error on
one report is recorded in the `error` column; the run continues.
Usage: python -u scripts/extract_features.py [--shard 0 --nshards 1] [--ciks 320193,789019] [--per-sec 8]
"""
import argparse
import time
from pathlib import Path

import pandas as pd

from ghostdesk.filings.edgar import DATA_DIR, EdgarClient, Filing, download_filing_html
from ghostdesk.filings.xbrl import get_instance, own_period_values, parse_instance
from ghostdesk.signal.features import pair_features, parts

ap = argparse.ArgumentParser()
ap.add_argument("--shard", type=int, default=0)
ap.add_argument("--nshards", type=int, default=1)
ap.add_argument("--ciks", default="")
ap.add_argument("--since", default="2009-06-01")
ap.add_argument("--until", default="2025-12-31")
ap.add_argument("--per-sec", type=float, default=8.0)
ap.add_argument("--out", default=str(DATA_DIR / "features"))
args = ap.parse_args()

idx = pd.read_parquet(DATA_DIR / "filings_index.parquet")
uni = pd.read_parquet(DATA_DIR / "universe.parquet").dropna(subset=["cik"])


def in_index(r) -> bool:
    """The report was filed while its CIK was in the index (on a mapped part of an interval)."""
    seg = uni[uni["cik"] == r.cik]
    d = r.filing_date
    return bool(((seg["valid_from"].fillna(seg["start"]) <= d) & (seg["end"].isna() | (d < seg["end"]))).any())


t = idx[~idx["amendment"] & idx["prev_accession"].notna() & idx["filing_date"].between(args.since, args.until)]
t = t[[in_index(r) for r in t.itertuples()]]
ciks = sorted(int(c) for c in t["cik"].unique())
ciks = [int(c) for c in args.ciks.split(",")] if args.ciks else [c for c in ciks if c % args.nshards == args.shard]
out = Path(args.out)
out.mkdir(parents=True, exist_ok=True)
path = out / f"shard_{args.shard}.parquet"
rows = pd.read_parquet(path).to_dict("records") if path.exists() else []
done = {r["cik"] for r in rows}
sec = EdgarClient(max_per_sec=args.per_sec)
by_acc = idx.drop_duplicates(["cik", "accession"]).set_index(["cik", "accession"])
print(f"shard {args.shard}/{args.nshards}: {len(ciks)} CIKs, {len(done)} done, "
      f"{int(t['cik'].isin(ciks).sum())} reports", flush=True)


def filing(cik, acc) -> Filing:
    r = by_acc.loc[(cik, acc)]
    return Filing(cik, acc, r["form"], f"{r['filing_date']:%Y-%m-%d}", f"{r['report_date']:%Y-%m-%d}",
                  r["primary_doc"], str(r["accepted_utc"]))


start, n = time.time(), 0
for j, cik in enumerate(c for c in ciks if c not in done):
    memo: dict[str, dict] = {}

    def text(acc, cik=cik, memo=memo):
        if acc not in memo:
            f = filing(cik, acc)
            memo[acc] = parts(download_filing_html(sec, f, store=False), f.form)
        return memo[acc]

    for r in t[t["cik"] == cik].sort_values("filing_date").itertuples():
        row = {"cik": cik, "accession": r.accession, "prev_accession": r.prev_accession, "form": r.form,
               "filing_date": r.filing_date, "report_date": r.report_date, "accepted_utc": r.accepted_utc,
               "error": ""}
        try:
            row |= pair_features(text(r.accession), text(r.prev_accession))
            xml = get_instance(sec, filing(cik, r.accession))
            if xml:
                row |= {f"xbrl_{k}": v for k, v in
                        own_period_values(parse_instance(xml), r.report_date, r.form).items()}
        except Exception as e:  # noqa: BLE001 - record and go on; the error rate is reported
            row["error"] = f"{type(e).__name__}: {e}"[:200]
        rows.append(row)
        n += 1
        memo.pop(r.prev_accession, None)  # each report is the earlier report of at most one later pair
    if (j + 1) % 10 == 0:
        pd.DataFrame(rows).to_parquet(path, index=False)
        print(f"{j + 1} CIKs, {n} reports, {n / (time.time() - start):.2f} reports/s", flush=True)
df = pd.DataFrame(rows)
df.to_parquet(path, index=False)
print(f"done: {len(df)} reports, errors {int((df['error'] != '').sum())}, {time.time() - start:.0f} s", flush=True)
