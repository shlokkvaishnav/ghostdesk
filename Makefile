.PHONY: install install-ml test lint format
install:
	python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
install-ml:
	.venv/bin/pip install -e ".[dev,ml]"
test:
	.venv/bin/pytest -q
lint:
	.venv/bin/ruff check src tests
format:
	.venv/bin/ruff format src tests
