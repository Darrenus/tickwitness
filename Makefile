.PHONY: sync lint format type test docs check build

UV ?= uv

sync:
	$(UV) sync --locked

lint:
	$(UV) run --locked ruff check src tests scripts

format:
	$(UV) run --locked ruff format --check src tests scripts

type:
	$(UV) run --locked mypy

test:
	$(UV) run --locked pytest

docs:
	$(UV) run --locked python scripts/check_docs.py

check: lint format type test docs

build: sync
	$(UV) build --no-build-isolation
