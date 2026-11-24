"""The static page: its copy of the validation results equals the committed file, and old addresses still resolve."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"


def test_page_validation_copy_equals_the_results_file():
    page = json.loads((WEB / "assets" / "validation.json").read_text())
    assert page == json.loads((ROOT / "docs" / "results" / "validation.json").read_text()), \
        "run: cp docs/results/validation.json web/assets/validation.json"


def test_page_reads_the_copy_and_shows_all_validation_models():
    app = (WEB / "app.js").read_text()
    assert '"assets/validation.json"' in app
    models = json.loads((WEB / "assets" / "validation.json").read_text())["models"]
    assert all(f"{m}:" in app for m in models), "every validation model needs a kind in app.js MODELS"


def test_old_explorer_addresses_forward_to_the_page():
    for p, target in (("explore/index.html", "../"), ("explore.html", "./")):
        html = (WEB / p).read_text()
        assert f'url={target}"' in html and f'location.replace("{target}"' in html
