PYTHON ?= .venv/bin/python
RUFF ?= .venv/bin/ruff
MYPY ?= .venv/bin/mypy
PYTEST ?= .venv/bin/pytest
PNPM ?= pnpm

.PHONY: test test-python lint miniapp-build up down

test: test-python miniapp-build

test-python:
	$(PYTEST) backend/tests -v

lint:
	$(RUFF) check backend/src backend/tests bot/src
	$(MYPY) backend/src
	cd miniapp && $(PNPM) lint

miniapp-build:
	cd miniapp && $(PNPM) build

up:
	docker compose --env-file .env -f infra/compose.local.yml up --build

down:
	docker compose --env-file .env -f infra/compose.local.yml down
