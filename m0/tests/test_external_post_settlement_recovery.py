"""v31 real SIGKILL recovery after sequential external improve settlement."""
import os
from pathlib import Path
import signal
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from core.loop import Framework
from core.x1.checkpoint import certified_snapshot_ref
from core.x1.store import AppendOnlyStore
from examples.toy_gepa import MockLLM
from test_external_evaluator import TASK, evaluator, workspace
from test_external_recovery import COMPARE, ForbiddenLLM, config

PROJECT = Path(__file__).resolve().parents[1]
CRASH_POINTS = ("settle", "absorb", "gate", "admission_mutation", "admission_receipt")


def owner_main(run_dir, root, script, crash_point):
    improve_id = Framework(MockLLM(), None, config(), str(run_dir / "ids"))
    improve_id = improve_id._proposal_id(TASK, "improve:1")
    original_append = AppendOnlyStore.append
    armed = False
    mutation_count = 0
    gate_seen = False

    def append_with_crash(self, kind, payload):
        nonlocal armed, mutation_count, gate_seen
        original_append(self, kind, payload)
        data = payload if isinstance(payload, dict) else {}
        crash = False
        if kind == "state_mutation" and data.get("op") == "add_node" \
                and data.get("target") == improve_id:
            armed = True
            mutation_count = 1
        elif armed and kind == "state_mutation":
            mutation_count += 1
        if crash_point == "settle":
            crash = kind == "ledger" and data.get("entry_kind") == "settle" \
                and data.get("account") == "exploit"
        elif crash_point == "absorb":
            crash = kind == "state_mutation" and armed and mutation_count == 4
        elif crash_point == "gate":
            if kind == "gate_evidence" and data.get("candidate_id") == improve_id:
                gate_seen = True
            crash = gate_seen and kind == "receipt"
        elif crash_point == "admission_mutation":
            crash = kind == "state_mutation" and data.get("target") == improve_id \
                and data.get("op") in {"merge", "prune"}
        elif crash_point == "admission_receipt":
            crash = kind == "admission_receipt" and data.get("candidate_id") == improve_id
        elif crash_point == "failure_evidence":
            crash = kind == "executor_evidence" \
                and (data.get("evidence") or {}).get("candidate_id") == improve_id
        if crash:
            os.kill(os.getpid(), signal.SIGKILL)

    AppendOnlyStore.append = append_with_crash
    store = AppendOnlyStore(run_dir / "x1.jsonl")
    genesis = Framework(MockLLM(), None, config(), str(run_dir / "genesis-id"))
    genesis = genesis._proposal_id(TASK, "genesis")
    mode = "fail_non_genesis" if crash_point == "failure_evidence" else "ok"
    external = evaluator(root, script, store, mode, genesis)
    Framework(MockLLM(), external, config(), str(run_dir)).evolve(TASK)


def crash_owner(run_dir, root, script, crash_point):
    env = dict(os.environ)
    env.update(PYTHONPATH=str(PROJECT), PYTHONDONTWRITEBYTECODE="1")
    owner = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "--owner", str(run_dir),
         str(root), str(script), crash_point], cwd=PROJECT, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    stdout, stderr = owner.communicate(timeout=20)
    assert owner.returncode == -signal.SIGKILL, (stdout, stderr)


def recovered_framework(run_dir, root, script):
    store = AppendOnlyStore(run_dir / "x1.jsonl")
    external = evaluator(root, script, store)
    return Framework(ForbiddenLLM(), external, config(resume=True), str(run_dir))


@pytest.mark.parametrize("crash_point", CRASH_POINTS)
def test_real_post_settlement_crashes_resume_only_missing_suffix(tmp_path, crash_point):
    reference_root, reference_script = workspace(tmp_path, f"reference-{crash_point}")
    reference_dir = tmp_path / f"reference-{crash_point}"
    reference = Framework(MockLLM(), evaluator(reference_root, reference_script,
                                               AppendOnlyStore(reference_dir / "x1.jsonl")),
                          config(), str(reference_dir))
    expected = reference.evolve(TASK)

    root, script = workspace(tmp_path, f"crash-{crash_point}")
    run_dir = tmp_path / f"recovered-{crash_point}"
    crash_owner(run_dir, root, script, crash_point)
    resumed = recovered_framework(run_dir, root, script)
    actual = resumed.evolve(TASK)
    for key in COMPARE:
        assert actual[key] == expected[key], key
    assert actual["resumed"] is True and actual["completed"] is True
    store = resumed.store
    assert len(list(store.read("executor_process_started"))) == 2
    assert len(list(store.read("external_evaluator_outcome"))) == 2
    adopted = list(store.read("m0_recovery_adopted"))
    assert len(adopted) == 1
    assert adopted[0]["payload"]["settlement_reused"] is True
    assert adopted[0]["payload"]["reexecuted"] is False
    assert len([row for row in store.read("ledger")
                if row["payload"].get("account") == "exploit"
                and row["payload"].get("entry_kind") == "settle"]) == 1
    improve_id = adopted[0]["payload"]["candidate_id"]
    assert len([row for row in store.read("gate_evidence")
                if row["payload"].get("candidate_id") == improve_id]) == 1
    assert len([row for row in store.read("admission_receipt")
                if row["payload"].get("candidate_id") == improve_id]) == 1
    assert len(list(store.read("state_mutation"))) == 10
    assert not list(store.read("state_mutation_rejected"))
    assert resumed.inspect()["governance_pass"] is True
    assert certified_snapshot_ref(reference_dir / "checkpoint.json") == \
        certified_snapshot_ref(run_dir / "checkpoint.json")
    if crash_point == "admission_receipt":
        resumed.llm = MockLLM()
        replayed = resumed.replay()
        assert resumed.inspect()["replay_certified"] is True
        for key in COMPARE:
            assert replayed[key] == expected[key], key


def test_real_post_settlement_failure_evidence_is_adopted_exactly_once(tmp_path):
    def failing_external(root, script, store):
        genesis = Framework(MockLLM(), None, config(), str(root / "genesis-id"))
        genesis = genesis._proposal_id(TASK, "genesis")
        return evaluator(root, script, store, "fail_non_genesis", genesis)

    reference_root, reference_script = workspace(tmp_path, "reference-failure")
    reference_dir = tmp_path / "reference-failure"
    reference_store = AppendOnlyStore(reference_dir / "x1.jsonl")
    reference = Framework(MockLLM(), failing_external(
        reference_root, reference_script, reference_store), config(), str(reference_dir))
    expected = reference.evolve(TASK)

    root, script = workspace(tmp_path, "crash-failure")
    run_dir = tmp_path / "recovered-failure"
    crash_owner(run_dir, root, script, "failure_evidence")
    store = AppendOnlyStore(run_dir / "x1.jsonl")
    resumed = Framework(ForbiddenLLM(), failing_external(root, script, store),
                        config(resume=True), str(run_dir))
    actual = resumed.evolve(TASK)
    for key in COMPARE:
        assert actual[key] == expected[key], key
    assert len(list(store.read("executor_process_started"))) == 2
    assert len(list(store.read("executor_evidence"))) == 1
    adopted = list(store.read("m0_recovery_adopted"))
    assert len(adopted) == 1 and adopted[0]["payload"]["settlement_reused"] is True
    improve_id = adopted[0]["payload"]["candidate_id"]
    assert not [row for row in store.read("gate_evidence")
                if row["payload"].get("candidate_id") == improve_id]
    assert resumed.inspect()["governance_pass"] is True
    assert certified_snapshot_ref(reference_dir / "checkpoint.json") == \
        certified_snapshot_ref(run_dir / "checkpoint.json")


def test_post_checkpoint_mutation_fork_is_refused_without_duplicate_finalization(tmp_path):
    root, script = workspace(tmp_path, "fork-external")
    run_dir = tmp_path / "fork"
    crash_owner(run_dir, root, script, "settle")
    store = AppendOnlyStore(run_dir / "x1.jsonl")
    store.append("state_mutation", {
        "op": "prune", "target": "forged-candidate", "fields": {},
        "rationale": "forged post-checkpoint suffix", "result": {}})
    resumed = recovered_framework(run_dir, root, script)
    with pytest.raises(RuntimeError, match="mutation history differs"):
        resumed.evolve(TASK)
    assert not list(store.read("m0_recovery_adopted"))
    assert not list(store.read("admission_receipt"))[1:]
    assert len([row for row in store.read("ledger")
                if row["payload"].get("account") == "exploit"
                and row["payload"].get("entry_kind") == "settle"]) == 1


if __name__ == "__main__" and len(sys.argv) == 6 and sys.argv[1] == "--owner":
    owner_main(Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4]), sys.argv[5])
