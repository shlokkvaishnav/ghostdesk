PY := PYTHONPATH=src .venv/bin/python -u
.PHONY: install install-ml test lint format docs check universe index prices features

install:
	python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
install-ml:
	.venv/bin/pip install -e ".[dev,ml]"

test:
	.venv/bin/pytest -q
lint:
	.venv/bin/ruff check src tests scripts
format:
	.venv/bin/ruff format src tests scripts
docs:
	.venv/bin/mkdocs build --strict -q
check: lint test docs

universe:
	$(PY) scripts/data/build_universe.py
index:
	$(PY) scripts/data/build_filing_index.py
prices:
	$(PY) scripts/data/load_prices.py
features:
	@test -n "$(RUN)" || (echo "usage: make features RUN=<features workflow run id>" && exit 1)
	$(PY) scripts/data/merge_feature_shards.py $(RUN)
