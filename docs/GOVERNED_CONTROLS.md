# Run resident controls in five minutes

The [offline example](../m0/examples/governed_controls.py) uses the public `Framework.from_profile`, `evolve`, `inspect` and `replay` interfaces. It runs a small integer-search task with three resident controls and seven-account physical accounting. It requires no credentials, model server or network requests.

The provider is explicitly a **deterministic fixture**. Its five-token usage is synthetic accounting for a local adapter. This demonstration does not establish IID model sampling, superiority, paid-run protection or completion of the framework's broader research requirements.

## Install and run

From the repository root, use Python 3.11 or later:

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install ./m0
python m0/examples/governed_controls.py --workdir /tmp/mori-controls
```

Use a new work directory for a new run. The script imports the installed `core` package and has no test-module imports or repository-path modifications. It also works when copied elsewhere and invoked as `python /path/to/governed_controls.py ...` after installing the package.

The JSON output contains the selected main candidate, its score, and a freshly computed governance report. For this fixture, expect:

| Field | Completed run |
| --- | --- |
| `runtime` | `composed-v7-governed` |
| `best_score` | `0.86` |
| `governance.planned` / `completed` | `3` / `3` |
| `governance.failed` / `unresolved` / `pending` | `0` / `0` / `0` |
| `governance.budget.reconciled` | `true` |
| Control account | `15` synthetic tokens, `3` nodes, `3` evaluations |

The accounts are `explore`, `exploit`, `reeval`, `control`, `repair`, `handoff` and `overhead`. They are projections of the same physical settlements, so their totals reconcile without charging twice. Unsupported repair/handoff operations remain zero. Controls never become main parents, frontier entries or selected incumbents.

## Resume and replay

A completed run can be reopened without repeating its work:

```bash
python m0/examples/governed_controls.py --workdir /tmp/mori-controls --resume
python m0/examples/governed_controls.py --workdir /tmp/mori-controls --replay
```

Successful governed replay reports `replay_certificate.passed: true`, `mode: "recorded_outcomes"` and `external_calls: 0`. It reconstructs execution from recorded provider and evaluator outcomes; missing or mismatched evidence fails instead of falling back to HTTP. This behavior is specific to governed replay. Legacy ungoverned replay retains its existing semantics.

To try an explicit pause, use a separate directory:

```bash
python m0/examples/governed_controls.py --workdir /tmp/mori-controls-paused --pause-after 0
python m0/examples/governed_controls.py --workdir /tmp/mori-controls-paused --resume
python m0/examples/governed_controls.py --workdir /tmp/mori-controls-paused --replay
```

After the pause, one control is completed and two remain pending. An explicit pause retains their capacity and does not drain them. The example's `--replay` requires a completed checkpoint; finish a paused run with `--resume` first. Preserve the work directory, including its checkpoint and journal, for recovery and audit.

## Configuration and factory contract

The example adds this optional root object to a composed profile:

```json
{
  "governance": {
    "schema_version": 1,
    "controls": {
      "after_main_cycles": [0, 2, 4],
      "seed": 7,
      "provider": {"name": "seeded_fixture", "options": {}},
      "domain": {"name": "integer_fixture", "options": {}},
      "operator": {"name": "draft", "options": {}},
      "request": {"fidelity": "dev", "split_id": "dev", "seed_set": [1]},
      "reservations": {
        "operator": {"token": 5, "node": 1, "eval_count": 0},
        "evaluation": {"token": 0, "node": 0, "eval_count": 1}
      }
    }
  }
}
```

`0` runs before any main cycle; `2` and `4` run after those numbers of committed main cycles. `max_generations=3` allows the initial generation plus three further generations, giving four main cycles. The schedule starts at zero, is strictly increasing, and cannot exceed `max_generations + 1`. Each slot gets its frozen seed and one draw, including failed draws.

Registered factories construct fresh providers and domains. A control provider factory receives `ctx.invocation_scope`, including `lane`, `slot_id` and `seed`; it does not receive the live main provider or evaluator. The example uses the seed to initialize its own deterministic sequence. Metadata stays outside prompt text, so the control prompts are identical. Factories receive restricted lane/component store views. These are declared-interface isolation checks, not a sandbox against malicious Python code.

The provider declaration and its runtime `governance_binding()` agree on:

```python
{
    "schema_version": 1,
    "fresh_session": True,
    "state_independent": True,
    "sampling": {
        "method": "deterministic_fixture",
        "parameters": {},
        "applied": True,
    },
    "call_bound": {"kind": "hard", "units": {"token": 5}},
    "external_currency": False,
}
```

Both main and control providers need supported hard-bound capabilities. The bound must cover the adapter's total call consumption; an estimated prompt length or ignored temperature parameter is insufficient. The current provider bound supports exactly the `token` unit, because provider calls are metered in tokens; other physical units remain explicit domain or operation costs. Every controlled physical unit must appear in both reservation baskets. When configured, an operator must reserve at least one node and an evaluation at least one evaluation count; evaluation node reservation must be zero. The domain returns canonical `EvalResult` values with `EvaluationContract` bindings and explicit measured units. See the example's `IntegerDomain` for the complete implementation.

Omitting `governance` preserves the existing composed-v6 configuration serialization and behavior. Existing checkpoints are not silently converted into governed runs.

## Failures and current limits

A failure with authoritative known usage keeps its original charge and account. A failed control remains in the predetermined sample; its unused evaluation obligation can be cancelled, and there is no redraw. Ordinary main exhaustion can drain the remaining controls. Unknown usage, integrity errors or bound violations stop new work in both lanes. Known actual overruns remain fully charged.

The [CNY authority contract](superpowers/specs/2026-11-04-cny-governance-journal.md) implements offline-tested currency obligations and explicit versioned migration. Its provider bridge is not implemented. Providers declaring an external currency authority are therefore rejected by core governance preflight; this example does not enable a formally protected paid campaign. No live ledger migration or new financial authorization follows from running the example.

## Implementation map

The public methods remain `Framework.evolve`, `inspect` and `replay`. Configuration and trusted registered factories supply the new behavior.

| Module under `m0/core/composition/` | Responsibility |
| --- | --- |
| `contracts.py`, `registry.py`, `governance.py` | Strict configuration, frozen plan, fresh sessions and restricted component records |
| `budget_contracts.py`, `budget.py`, `budget_governance.py` | Pure resource values, single settlement authority, accounts and protected future capacity |
| `governed.py`, `runtime.py`, `hierarchical_runtime.py` | Schedule and invocation sequencing shared by main/control and native/worktree adapters |
| `provider.py`, `provider_evidence.py` | Meter every ordinal and seal exact provider receipt coverage into physical settlements |
| `recovery.py` | Adopt recorded provider/evaluator outcomes and declared adapter state; reject unknown completion |
| `governance_audit.py` | Recompute control status from linked starts, outcomes, requests, measurements and settlements |

CNY obligations remain in `zoo/mle_bench_lite/cny_budget.py`; no currency conversion enters the core. The separate [CNY journal contract](superpowers/specs/2026-11-04-cny-governance-journal.md) documents its tested migration and recovery states. Enabling that journal format alone does not connect it to governed model invocations.
