PY := PYTHONPATH=src .venv/bin/python -u
.PHONY: typecheck install install-ml test lint format docs check universe prices update sectors

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
check: lint typecheck test docs

universe:
	$(PY) scripts/data/build_universe.py
prices:
	$(PY) scripts/data/load_prices.py
update:
	$(PY) scripts/data/update_prices.py
sectors:
	$(PY) scripts/data/build_sectors.py

typecheck:
	.venv/bin/mypy
