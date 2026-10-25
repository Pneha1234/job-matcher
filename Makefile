SHELL := /bin/bash
VENV := .venv
BIN := $(VENV)/bin
PYTHON_VERSION := $(shell cat .python-version)
API_PORT ?= 8000
UI_PORT ?= 3000

.PHONY: setup dev api ui check check-api check-ui fmt smoke ollama

## One-time setup: Python venv (pyenv 3.12) + UI packages.
setup: $(BIN)/uvicorn ui/node_modules

$(BIN)/uvicorn: pyproject.toml
	test -d $(VENV) || $(HOME)/.pyenv/versions/$(PYTHON_VERSION)/bin/python -m venv $(VENV)
	$(BIN)/pip install -q --upgrade pip
	$(BIN)/pip install -q -e '.[dev]'
	@touch $@

ui/node_modules: ui/package.json
	cd ui && npm install
	@touch $@

## Start API (:8000) and UI (:3000) together; Ctrl-C stops both.
dev: setup ollama
	@trap 'kill 0' EXIT; \
	$(BIN)/uvicorn app.main:app --reload --port $(API_PORT) & \
	(cd ui && API_URL=http://127.0.0.1:$(API_PORT) npm run dev -- --port $(UI_PORT)) & \
	wait

api: setup
	$(BIN)/uvicorn app.main:app --reload --port $(API_PORT)

ui: ui/node_modules
	cd ui && API_URL=http://127.0.0.1:$(API_PORT) npm run dev -- --port $(UI_PORT)

## Ollama runs natively (Homebrew service) so it can use the Metal GPU.
ollama:
	@curl -sf http://127.0.0.1:11434/api/version >/dev/null \
		|| echo "warning: Ollama is not running — start it with: brew services start ollama"

check: check-api check-ui

check-api: setup
	$(BIN)/ruff check app tests
	$(BIN)/black --check app tests
	$(BIN)/pytest -q

check-ui: ui/node_modules
	cd ui && npm run lint && npx tsc --noEmit

fmt: setup
	$(BIN)/ruff check --fix app tests
	$(BIN)/black app tests

## Real round-trip through local Ollama (needs qwen2.5:14b and bge-m3 pulled).
smoke: setup
	$(BIN)/pytest -q -m ollama tests/test_ollama_smoke.py
