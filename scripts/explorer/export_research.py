"""Write web/data/research.json for the research explorer page from the study results in data/.

Run it again by hand after a study changes; the output is committed (statistics only, no raw data).
"""
import json
from pathlib import Path

from ghostdesk.explorer.research_export import build

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"


def load(name: str) -> dict:
    return json.loads((DATA / name).read_text())


def main() -> None:
    results = {p: load(f"results_{p}.json") for p in ("build", "check", "test", "pooled")}
    seeds = [load(f"execution_results_test_seed{s}.json") for s in (0, 1, 2)]
    out = build(results, load("pitfalls.json"), seeds, load("capacity.json"))
    path = ROOT / "web" / "data" / "research.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, separators=(",", ":"), ensure_ascii=False) + "\n")
    print(f"wrote {path.relative_to(ROOT)} ({path.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
