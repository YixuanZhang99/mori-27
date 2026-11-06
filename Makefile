UV ?= uv
PYTHON ?= 3.12
export PYTHONDONTWRITEBYTECODE := 1

.PHONY: accept-linux-v73 accept-linux-v74 accept-linux-v75 help setup test test-linux axioms examples tooling check accept-linux build verify-import

help:
	@echo 'make setup        Install the locked Python 3.12 development environment'
	@echo 'make check        Run axioms, portable tests, examples and workflow tests'
	@echo 'make test         Run portable tests (Linux cases explicitly deselected)'
	@echo 'make test-linux   Run every test; any skip fails (Linux x86_64 required)'
	@echo 'make accept-linux Run the full v76 acceptance in a disposable copy'
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
	cd m0 && $(UV) run --locked python examples/configured_execution_offline.py
	cd m0 && $(UV) run --locked python -c "from examples.governed_controls import main; import tempfile; d=tempfile.TemporaryDirectory(prefix='mori-governed-example-'); main(['--workdir',d.name,'--pause-after','0']); main(['--workdir',d.name,'--resume']); main(['--workdir',d.name,'--replay']); d.cleanup()"
	cd m0 && $(UV) run --locked python -c "from examples.governed_cny_offline import main; import tempfile; d=tempfile.TemporaryDirectory(prefix='mori-cny-example-'); main(['--workdir',d.name]); d.cleanup()"

	cd m0 && $(UV) run --locked python -c "from examples.governed_cny_offline import main; import tempfile; d=tempfile.TemporaryDirectory(prefix='mori-cny-construction-example-'); main(['--workdir',d.name,'--construction']); d.cleanup()"

tooling:
	$(UV) run --project m0 --locked python -m unittest discover -s scripts/tests -v

check: axioms test examples tooling

accept-linux:
	$(UV) run --project m0 --locked python scripts/check_linux.py
	$(UV) run --project m0 --locked python scripts/run_acceptance_v76.py --timeout 3000

accept-linux-v75:
	$(UV) run --project m0 --locked python scripts/check_linux.py
	$(UV) run --project m0 --locked python scripts/run_acceptance_v75.py --timeout 2100

accept-linux-v74:
	$(UV) run --project m0 --locked python scripts/check_linux.py
	$(UV) run --project m0 --locked python scripts/run_acceptance_v74.py

accept-linux-v73:
	$(UV) run --project m0 --locked python scripts/check_linux.py
	$(UV) run --project m0 --locked python scripts/run_acceptance.py

build:
	$(UV) build m0 --out-dir artifacts/dist

verify-import:
	$(UV) run --project m0 --locked python scripts/verify_import.py --ref 9301cebe15c3abd772330beba5bd1898f4d4eb72
