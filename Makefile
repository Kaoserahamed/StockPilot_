# StockPilot - single entry point for local install, verification and build.
# Works on Linux/macOS (GNU make + bash) and Windows (Git Bash via
# `choco install make`, or PowerShell - see CONTRIBUTING.md for equivalents).
# Every target below runs the same command CI runs, so "make verify" == "CI is green".

# NOTE: no `SHELL := /bin/bash` on purpose - forcing bash breaks native
# Windows shells. Targets only use POSIX-portable constructs (`cd ... && ...`)
# and detect the virtualenv layout (.venv/bin vs .venv/Scripts) at runtime.
BACKEND := backend
FRONTEND := frontend

# Portable virtualenv python, detected once for the whole Makefile:
#   Windows -> backend/.venv/Scripts/python.exe
#   POSIX   -> backend/.venv/bin/python
#
# Every backend target below invokes tooling through $(VENV_PY) so the targets
# work in a *non-activated* shell (CI, devcontainer, fresh clone). Calling bare
# `python -m ruff/pytest/mypy` only worked when the virtualenv happened to be
# activated, which is exactly the fragile fresh-clone path the README promises.
ifeq ($(OS),Windows_NT)
  VENV_PY := $(BACKEND)/.venv/Scripts/python.exe
  RM_RF := powershell -NoProfile -Command "Remove-Item -Recurse -Force -ErrorAction SilentlyContinue"
else
  VENV_PY := $(BACKEND)/.venv/bin/python
  RM_RF := rm -rf
endif

.DEFAULT_GOAL := help

.PHONY: help
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

.PHONY: doctor
doctor: ## Check required tooling (python 3.11+, node 20+, docker, env templates)
	@python --version
	@node --version
	@npm --version
	@docker --version 2>/dev/null || echo "docker: not installed (only needed for db-up / prod parity)"
	@test -f .env.example && echo "root .env.example: ok"
	@test -f $(BACKEND)/.env.example && echo "backend .env.example: ok"
	@test -f $(FRONTEND)/.env.example && echo "frontend .env.example: ok"
	@test -f $(BACKEND)/requirements.lock && echo "backend lockfile: ok"
	@test -f $(BACKEND)/requirements-dev.lock && echo "backend dev lockfile: ok"
	@test -f $(BACKEND)/uv.lock && echo "backend uv lockfile: ok"

# ---------------------------------------------------------------- install ----
.PHONY: install
install: install-backend install-frontend ## Install both stacks

.PHONY: install-backend
install-backend: ## Create a virtualenv and install backend deps
	cd $(BACKEND) && python -m venv .venv && \
		$(VENV_PY) -m pip install --upgrade pip && \
		$(VENV_PY) -m pip install -r requirements.txt -r requirements-dev.txt

.PHONY: install-frontend
install-frontend: ## Install frontend deps from the lockfile
	cd $(FRONTEND) && npm ci

# ------------------------------------------------------------------ verify ----
.PHONY: lint
lint: lint-backend lint-frontend ## Lint both stacks

.PHONY: lint-backend
lint-backend: ## Ruff lint + format check (backend)
	cd $(BACKEND) && $(VENV_PY) -m ruff check app tests scripts && $(VENV_PY) -m ruff format --check app tests scripts

.PHONY: lint-frontend
lint-frontend: ## ESLint (frontend)
	cd $(FRONTEND) && npm run lint

.PHONY: format
format: ## Auto-fix formatting and import order (backend)
	cd $(BACKEND) && $(VENV_PY) -m ruff check --fix app tests && $(VENV_PY) -m ruff format app tests

.PHONY: typecheck
typecheck: typecheck-backend typecheck-frontend ## Type-check both stacks

.PHONY: typecheck-backend
typecheck-backend: ## mypy (backend)
	cd $(BACKEND) && $(VENV_PY) -m mypy app

.PHONY: typecheck-frontend
typecheck-frontend: ## tsc --noEmit (frontend)
	cd $(FRONTEND) && npm run typecheck

.PHONY: test
test: test-backend test-frontend ## Run both test suites

.PHONY: test-backend
test-backend: ## pytest (backend, in-memory SQLite)
	cd $(BACKEND) && $(VENV_PY) -m pytest

.PHONY: test-frontend
test-frontend: ## vitest run (frontend)
	cd $(FRONTEND) && npm test -- --run
.PHONY: test-cov
test-cov: ## pytest with a terminal coverage report
	cd $(BACKEND) && $(VENV_PY) -m pytest --cov=app --cov-report=term-missing --cov-fail-under=90

.PHONY: audit
audit: ## Dependency vulnerability audit for both stacks
	cd $(BACKEND) && $(VENV_PY) -m pip_audit -r requirements.lock
	cd $(FRONTEND) && npm run audit

.PHONY: secrets
secrets: ## Scan for hardcoded secrets
	cd $(BACKEND) && $(VENV_PY) scripts/scan_secrets.py

.PHONY: lock
lock: ## Regenerate backend lockfiles (pip closure + uv.lock) from the manifests
	cd $(BACKEND) && $(VENV_PY) scripts/generate_lockfile.py && $(VENV_PY) scripts/generate_lockfile.py --dev
	cd $(BACKEND) && $(VENV_PY) -m uv lock

.PHONY: verify
verify: lint typecheck test build audit secrets ## Everything CI enforces, in one command

# ------------------------------------------------------------------- build ----
.PHONY: build
build: build-frontend ## Build production artifacts

.PHONY: build-frontend
build-frontend: ## Next.js production build
	cd $(FRONTEND) && npm run build

# --------------------------------------------------------------------- run ----
.PHONY: run-backend
run-backend: ## Start the API with autoreload
	cd $(BACKEND) && $(VENV_PY) -m uvicorn app.main:app --reload --port 8000

.PHONY: run-frontend
run-frontend: ## Start the Next.js dev server
	cd $(FRONTEND) && npm run dev

.PHONY: db-up
db-up: ## Start the development PostgreSQL container
	docker compose -f docker-compose.dev.yml up -d db

.PHONY: migrate
migrate: ## Apply database migrations
	cd $(BACKEND) && $(VENV_PY) -m alembic upgrade head

# ------------------------------------------------------------------- housekeeping ----
.PHONY: clean
clean: ## Remove caches and build output
	rm -rf $(BACKEND)/.pytest_cache $(BACKEND)/.ruff_cache $(BACKEND)/.mypy_cache
	rm -rf $(BACKEND)/htmlcov $(BACKEND)/.coverage
	find . -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
	rm -rf $(FRONTEND)/.next $(FRONTEND)/coverage