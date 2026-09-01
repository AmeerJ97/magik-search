.PHONY: check test lint format build clean

check: lint test

test:
	python3 -m pytest -q

lint:
	ruff check .
	ruff format --check .

format:
	ruff check --fix .
	ruff format .

build:
	python3 -m build

clean:
	rm -rf build dist .pytest_cache htmlcov
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
