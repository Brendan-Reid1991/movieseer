# Usage:
#   make install          # deps for dev
#   make lint             # lint + fix files in-place
# 	make lint-check		  # static lint checking only (no fixes)
#   make format           # auto-format files in-place
#   make fmt-check        # verify formatting only
#   make test             # run tests
#   make ci               # lint + fmt-check + test
#   make clean            # remove caches/artifacts
#   make lock             # (re)solve and update lockfile
#   make help             # this help

SHELL := /bin/bash
.ONESHELL:
.IGNORE: clean
.DEFAULT_GOAL := help

PY ?= python
UV ?= uv
RUFF ?= ruff

CODE := movieseer scripts
TESTS := tests

.PHONY: install lint lint-check format fmt-check test ci lock clean help

# -------- Tasks --------

install: ## Sync runtime + dev dependencies
	$(UV) venv --seed
	$(UV) sync --group dev

lint: ## Lint and fix
	$(UV) run $(RUFF) check $(CODE) --fix

lint-check: ## Lint check
	$(UV) run $(RUFF) check $(CODE)

format: ## Auto-format code
	$(UV) run $(RUFF) format $(CODE)
	$(UV) run $(RUFF) format $(TESTS)

fmt-check: ## Check formatting without writing
	$(UV) run $(RUFF) format --check $(CODE)

test: ## Run test suite
	$(UV) run pytest --cov=src --cov-fail-under=95 --cov-report term-missing --disable-warnings

ci: ## Lint + format check + tests (for CI pipelines)
	$(MAKE) lint-check
	$(MAKE) fmt-check
	$(MAKE) test

lock: ## Update lockfile (re-resolve)
	$(UV) lock

clean: ## Remove caches and build artifacts
	rm -rf .pytest_cache .ruff_cache build dist *.egg-info .mypy_cache

help: ## Show this help
	@grep -E '^[[:alnum:]_.-]+:.*## ' $(MAKEFILE_LIST) | \
	  sed -E 's/^([[:alnum:]_.-]+):[^#]*## (.*)/\t- \1 - \2/' | \
	  sort
