import importlib
import pkgutil

import ghostdesk


def test_all_modules_import():
    for mod in pkgutil.walk_packages(ghostdesk.__path__, prefix="ghostdesk."):
        importlib.import_module(mod.name)
