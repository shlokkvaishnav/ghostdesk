"""Experiment registry (decision D34): every result is keyed by what made it, and can be made again.

run key = SHA-256 of (data hash, code commit, config hash), first 16 hex digits. The data hash is the price store's
content hash plus the panel window; the code commit is `git rev-parse HEAD` (a run from a tree with uncommitted
changes gets the suffix `-dirty` and is refused unless `allow_dirty`); the config hash is SHA-256 of the canonical
JSON of the model and backtest settings. Runs are rows of the DuckDB table `runs` in `data/registry/registry.duckdb`;
the scores of a run are a `.npy` file next to it, with its SHA-256 in the row. `verify` reruns a function and
compares the SHA-256 of the new scores with the stored one: equal means bit-identical.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from ghostdesk.paths import DATA_DIR, REPO_ROOT

SCHEMA = """CREATE TABLE IF NOT EXISTS runs (
    run_key VARCHAR PRIMARY KEY, name VARCHAR, data_hash VARCHAR, code_commit VARCHAR, config_hash VARCHAR,
    config VARCHAR, metrics VARCHAR, scores_path VARCHAR, scores_sha256 VARCHAR, seconds DOUBLE,
    created_at TIMESTAMP)"""


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def array_sha256(a: np.ndarray) -> str:
    a = np.ascontiguousarray(a)
    return sha256_bytes(str(a.dtype).encode() + str(a.shape).encode() + a.tobytes())


def config_hash(config: dict) -> str:
    return sha256_bytes(json.dumps(config, sort_keys=True, default=str).encode())


def code_commit(root: Path = REPO_ROOT) -> str:
    def git(*a):
        return subprocess.run(["git", *a], cwd=root, capture_output=True, text=True, check=False).stdout.strip()

    sha = git("rev-parse", "HEAD") or "nogit"
    dirty = git("status", "--porcelain", "--", "src", "scripts")
    return sha + ("-dirty" if dirty else "")


def run_key(data_hash: str, commit: str, cfg_hash: str) -> str:
    return sha256_bytes(f"{data_hash}|{commit}|{cfg_hash}".encode())[:16]


class Registry:
    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root else DATA_DIR / "registry"
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = self.root / "registry.duckdb"
        with duckdb.connect(str(self.db)) as con:
            con.execute(SCHEMA)

    def record(self, name: str, data_hash: str, config: dict, scores: np.ndarray, metrics: dict, seconds: float,
               commit: str | None = None, allow_dirty: bool = False) -> str:
        commit = commit or code_commit()
        if commit.endswith("-dirty") and not allow_dirty:
            raise RuntimeError("uncommitted changes in src/ or scripts/: commit first so the run can be regenerated")
        ch = config_hash(config)
        key = run_key(data_hash, commit, ch)
        path = self.root / f"{key}.npy"
        np.save(path, scores)
        with duckdb.connect(str(self.db)) as con:
            con.execute("DELETE FROM runs WHERE run_key = ?", [key])
            con.execute("INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        [key, name, data_hash, commit, ch, json.dumps(config, sort_keys=True, default=str),
                         json.dumps(metrics, default=str), path.name, array_sha256(scores), seconds,
                         pd.Timestamp.now(tz="UTC").tz_localize(None).to_pydatetime()])
        return key

    def get(self, key: str) -> dict | None:
        with duckdb.connect(str(self.db)) as con:
            df = con.execute("SELECT * FROM runs WHERE run_key = ?", [key]).df()
        if df.empty:
            return None
        row = df.iloc[0].to_dict()
        row["config"], row["metrics"] = json.loads(row["config"]), json.loads(row["metrics"])
        return row

    def runs(self) -> pd.DataFrame:
        with duckdb.connect(str(self.db)) as con:
            return con.execute("SELECT * FROM runs ORDER BY created_at").df()

    def scores(self, key: str) -> np.ndarray:
        return np.load(self.root / self.get(key)["scores_path"])

    def verify(self, key: str, regenerate) -> bool:
        """Run `regenerate(config) -> scores` again; True if its SHA-256 equals the stored one."""
        row = self.get(key)
        return array_sha256(regenerate(row["config"])) == row["scores_sha256"]
