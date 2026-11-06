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

An independent offline host plumbing check uses the pinned upstream controller,
its process worker and the same stage sandbox with a synthetic client:

```bash
PYTHONHASHSEED=0 PYTHONPATH=m0 python -m zoo.circle_packing.host_reference \
  --output /tmp/mori-circle-host-fixture --seed 0 --iterations 1
```

This command passes only an allowlisted environment to the host worker; it does
not load credentials. It records fixture stage and message evidence for local
debugging. It is not the governed reference runner, does not enforce a paired
physical budget, and cannot be used to make a benchmark claim.

`governed_setup` is an internal composition factory for the existing CNY
bridge and a fresh circle control. Its loopback tests cover role-bound requests,
settlement, unknown usage and recorded replay. It does not freeze a fair paired
plan or start a real run; the named runner continues to reject live mode until
the complete comparison and audit are ready.

`pilot_plan.build_draft_plan` computes a six-cell draft (three seeds times two
arms) from a verified campaign policy and explicit source/dependency hashes.
It records the proposed common numeric caps, but labels the result
`draft_not_executable`: reference-side enforcement and final source freezing
must be completed before it can authorize any call.
