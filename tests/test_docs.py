"""The developer docs stay true to the code: every module and public name is documented, every script is in the
runbook, documented columns match the data files that are present, and relative links resolve."""
import ast
import re
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
DEV = ROOT / "docs" / "dev"
MODULES = sorted(p for p in (ROOT / "src" / "ghostdesk").rglob("*.py") if p.name != "__init__.py")


def sections(md: str, prefix: str) -> dict[str, str]:
    """Heading text (after `prefix`, up to the first space) -> the body until the next heading of that level."""
    parts = re.split(rf"(?m)^{re.escape(prefix)}", md)
    return {p.split()[0]: p for p in parts[1:]}


def public_names(path: Path) -> list[str]:
    tree = ast.parse(path.read_text())
    names = [n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and not n.name.startswith("_")]
    names += [t.id for n in tree.body if isinstance(n, ast.Assign) for t in n.targets
              if isinstance(t, ast.Name) and t.id.isupper() and t.id in ("ITEMS", "ITEM_RE")]
    return names


@pytest.mark.parametrize("path", MODULES, ids=lambda p: str(p.relative_to(ROOT / "src")))
def test_every_module_and_public_name_is_documented(path):
    docs = sections((DEV / "modules.md").read_text(), "## ")
    key = str(path.relative_to(ROOT / "src"))
    assert key in docs, f"{key} has no section in docs/dev/modules.md"
    missing = [n for n in public_names(path) if f"`{n}" not in docs[key] and f"{n}(" not in docs[key]]
    assert not missing, f"{key}: not documented: {missing}"


def test_every_script_is_in_the_runbook():
    runbook = (DEV / "runbook.md").read_text()
    missing = [p.name for p in (ROOT / "scripts").rglob("*.py") if p.name not in runbook]
    assert not missing, f"scripts not in docs/dev/runbook.md: {missing}"


def documented_columns() -> dict[str, list[str]]:
    out = {}
    for head, body in sections((DEV / "data-contracts.md").read_text(), "### ").items():
        cols = re.findall(r"(?m)^\| `([a-zA-Z_]+)` \|", body)
        for f in re.findall(r"data/[a-z_]+\.parquet", head + " " + body.splitlines()[0]):
            out[f] = cols
    return out


def test_data_contracts_match_present_files():
    cols = documented_columns()
    assert {"data/universe.parquet", "data/price_symbols.parquet", "data/sectors.parquet",
            "data/returns_daily.parquet"} <= set(cols)
    checked = 0
    for f, expected in cols.items():
        p = ROOT / f
        if p.exists():  # data/ is not in git; CI checks only the list, a local run checks the columns
            assert list(pd.read_parquet(p).columns) == expected, f"{f}: columns differ from docs/dev/data-contracts.md"
            checked += 1
    print(f"checked {checked} data files")


def test_relative_links_resolve():
    files = [ROOT / "AGENTS.md", *DEV.glob("*.md"), *(ROOT / "docs").glob("*.md")]
    bad = []
    for f in files:
        for link in re.findall(r"\]\(([^)#\s]+)(?:#[^)]*)?\)", f.read_text()):
            if not link.startswith(("http://", "https://", "mailto:")) and not (f.parent / link).exists():
                bad.append(f"{f.relative_to(ROOT)} -> {link}")
    assert not bad, bad
