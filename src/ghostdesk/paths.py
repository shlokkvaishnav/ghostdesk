"""Where the repository and its (gitignored) data directory are. GHOSTDESK_DATA overrides the data directory, so a
git worktree can read the main checkout's data."""
from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("GHOSTDESK_DATA") or REPO_ROOT / "data")
