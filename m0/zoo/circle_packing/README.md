# OpenEvolve circle-packing fixture

The named runner exercises Mori's public Framework, the pinned OpenEvolve host
and the sandboxed 26-circle evaluator with deterministic synthetic patches.
It makes no model requests and its scores are **not benchmark results**.

From the repository root on Linux with the project's sandbox dependencies:

```bash
PYTHONHASHSEED=0 PYTHONPATH=m0 python -m zoo.circle_packing.runner \
  --output /tmp/mori-circle-fixture --seed 0 --iterations 1
```

The command emits JSON, writes a frozen configuration and terminal record, and
verifies recorded replay with zero external calls. Running the same command
again verifies and resumes the terminal without running the provider or
candidate evaluator. Changed configuration or incomplete output is rejected.
`PYTHONHASHSEED` must be set before Python starts for repeatable host behavior.

Live mode is deliberately unavailable here until the common currency and
physical budgets, independent upstream controller, comparison plan and evidence
export have been integrated and verified. Fixture metrics do not populate the
planned paired pilot results.
