import ast
import importlib
import pkgutil
from pathlib import Path

import pytest

import ghostdesk

SCRIPTS = sorted((Path(__file__).resolve().parents[1] / "scripts").rglob("*.py"))


def test_all_modules_import():
    for mod in pkgutil.walk_packages(ghostdesk.__path__, prefix="ghostdesk."):
        importlib.import_module(mod.name)


@pytest.mark.parametrize("path", SCRIPTS, ids=lambda p: p.name)
def test_every_ghostdesk_import_in_a_script_exists(path):
    """Scripts are not imported by the other tests, so a renamed module would break them unseen."""
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("ghostdesk"):
            mod = importlib.import_module(node.module)
            for a in node.names:
                assert hasattr(mod, a.name) or importlib.util.find_spec(f"{node.module}.{a.name}"), \
                    f"{path.name}: {node.module}.{a.name} does not exist"
