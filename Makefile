UV ?= uv
PYTHON ?= 3.12
export PYTHONDONTWRITEBYTECODE := 1

.PHONY: help setup test test-linux axioms examples tooling check accept-linux build verify-import

help:
	@echo 'make setup        Install the locked Python 3.12 development environment'
	@echo 'make check        Run axioms, portable tests, examples and workflow tests'
	@echo 'make test         Run portable tests (Linux cases explicitly deselected)'
	@echo 'make test-linux   Run every test; any skip fails (Linux x86_64 required)'
	@echo 'make accept-linux Run the full v67 acceptance in a disposable copy'
	@echo 'make build        Build wheel and sdist into artifacts/dist'
	@echo 'make verify-import Verify the immutable imported Git baseline'

setup:
	$(UV) sync --project m0 --locked --python $(PYTHON)

test:
	cd m0 && $(UV) run --locked python -m pytest -q -p no:cacheprovider --strict-markers --fail-on-skip -m 'not linux'

test-linux:
	$(UV) run --project m0 --locked python scripts/check_linux.py
	cd m0 && $(UV) run --locked python -m pytest -q -p no:cacheprovider --strict-markers --fail-on-skip

axioms:
	cd m0 && $(UV) run --locked python ci/check_axioms.py

examples:
	cd m0 && $(UV) run --locked python examples/toy_gepa.py
	cd m0 && $(UV) run --locked python examples/gsm8k_offline.py
	cd m0 && $(UV) run --locked python examples/funsearch_offline.py
	cd m0 && $(UV) run --locked python examples/composed_research_offline.py

tooling:
	$(UV) run --project m0 --locked python -m unittest discover -s scripts/tests -v

check: axioms test examples tooling

accept-linux:
	$(UV) run --project m0 --locked python scripts/check_linux.py
	$(UV) run --project m0 --locked python scripts/run_acceptance.py

build:
	$(UV) build m0 --out-dir artifacts/dist

verify-import:
	$(UV) run --project m0 --locked python scripts/verify_import.py --ref 9301cebe15c3abd772330beba5bd1898f4d4eb72
