"""v35 real SIGKILL recovery through external M0 batch finalization."""
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
from test_external_batch_recovery import config, recovered_framework, start_owner
from test_external_evaluator import TASK, evaluator, workspace
from test_external_recovery import COMPARE, ForbiddenLLM

CRASH_POINTS = (
    "settle", "settled_evidence", "absorb", "gate", "decision",
    "admission_mutation", "admission", "second_absorb", "completed",
    "admission_receipt",
)


def owner_main(run_dir, root, script, crash_point):
    ids = Framework(MockLLM(), None, config(), str(run_dir / "ids"))
    first = ids._proposal_id(TASK, "improve:1:0")
    second = ids._proposal_id(TASK, "improve:1:1")
    original_append = AppendOnlyStore.append
    mutation_target = None
    mutation_count = 0
    gate_seen = False

    def append_with_crash(self, kind, payload):
        nonlocal mutation_target, mutation_count, gate_seen
        original_append(self, kind, payload)
        data = payload if isinstance(payload, dict) else {}
        crash = False
        if kind == "state_mutation" and data.get("op") == "add_node" \
                and data.get("target") in {first, second}:
            mutation_target = data["target"]
            mutation_count = 1
        elif mutation_target is not None and kind == "state_mutation" \
                and data.get("op") in {"merge", "prune"} \
                and data.get("target") == mutation_target:
            mutation_count += 1
        elif mutation_target is not None and kind == "state_mutation" \
                and mutation_target == data.get("fields", {}).get("candidate_id"):
            mutation_count += 1
        elif mutation_target is not None and kind == "state_mutation" \
                and mutation_count < 4:
            mutation_count += 1

        if crash_point == "settle":
            crash = kind == "ledger" and data.get("entry_kind") == "settle" \
                and data.get("account") == "exploit"
        elif crash_point == "settled_evidence":
            crash = kind == "batch_execution_settled" and data.get("candidate_id") == first
        elif crash_point == "absorb":
            crash = kind == "state_mutation" and mutation_target == first \
                and mutation_count == 4
        elif crash_point == "second_absorb":
            crash = kind == "state_mutation" and mutation_target == second \
                and mutation_count == 4
        elif crash_point == "gate":
            if kind == "gate_evidence" and data.get("candidate_id") == first:
                gate_seen = True
            crash = gate_seen and kind == "receipt"
        elif crash_point == "decision":
            crash = kind == "batch_decision" and data.get("candidate_id") == first
        elif crash_point == "admission_mutation":
            crash = kind == "state_mutation" and data.get("target") == first \
                and data.get("op") in {"merge", "prune"}
        elif crash_point == "admission":
            crash = kind == "batch_admission" and data.get("candidate_id") == first
        elif crash_point == "completed":
            crash = kind == "batch_cycle_completed"
        elif crash_point == "admission_receipt":
            crash = kind == "admission_receipt" and data.get("candidate_id") == first
        if crash:
            os.kill(os.getpid(), signal.SIGKILL)

    AppendOnlyStore.append = append_with_crash
    store = AppendOnlyStore(run_dir / "x1.jsonl")
    Framework(MockLLM(), evaluator(root, script, store), config(), str(run_dir)).evolve(TASK)


def crash_owner(run_dir, root, script, crash_point):
    env = dict(os.environ)
    env.update(PYTHONPATH=str(Path(__file__).resolve().parents[1]),
               PYTHONDONTWRITEBYTECODE="1")
    owner = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "--owner", str(run_dir),
         str(root), str(script), crash_point], cwd=Path(__file__).resolve().parents[1],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    stdout, stderr = owner.communicate(timeout=25)
    assert owner.returncode == -signal.SIGKILL, (stdout, stderr)


@pytest.mark.parametrize("crash_point", CRASH_POINTS)
def test_real_batch_post_settlement_crashes_resume_exact_suffix(tmp_path, crash_point):
    reference_root, reference_script = workspace(tmp_path, f"reference-{crash_point}")
    reference_dir = tmp_path / f"reference-{crash_point}"
    reference_store = AppendOnlyStore(reference_dir / "x1.jsonl")
    reference = Framework(MockLLM(), evaluator(reference_root, reference_script,
                                               reference_store), config(), str(reference_dir))
    expected = reference.evolve(TASK)

    root, script = workspace(tmp_path, f"crash-{crash_point}")
    run_dir = tmp_path / f"recovered-{crash_point}"
    store = AppendOnlyStore(run_dir / "x1.jsonl")
    crash_owner(run_dir, root, script, crash_point)
    resumed = recovered_framework(run_dir, root, script)
    actual = resumed.evolve(TASK)
    for key in COMPARE:
        assert actual[key] == expected[key], key
    assert actual["resumed"] is True and actual["completed"] is True
    assert len(list(store.read("executor_process_started"))) == 3
    assert len(list(store.read("external_evaluator_outcome"))) == 3
    settled = list(store.read("batch_execution_settled"))
    assert len(settled) == 2
    assert len(list(store.read("batch_absorbed"))) == 2
    assert len(list(store.read("batch_decision"))) == 2
    assert len(list(store.read("batch_admission"))) == 2
    assert len(list(store.read("batch_cycle_completed"))) == 1
    assert len(list(store.read("state_mutation"))) == 15
    assert len(list(store.read("gate_evidence"))) == 3
    assert len(list(store.read("admission_receipt"))) == 3
    adopted = list(store.read("m0_batch_recovery_adopted"))
    assert len(adopted) == 1 and adopted[0]["payload"]["reexecuted"] is False
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


def test_batch_mutation_fork_fails_closed_without_adoption(tmp_path):
    root, script = workspace(tmp_path, "fork-workspace")
    run_dir = tmp_path / "fork"
    store = AppendOnlyStore(run_dir / "x1.jsonl")
    crash_owner(run_dir, root, script, "settle")
    store.append("state_mutation", {
        "op": "prune", "target": "forged-batch-candidate", "fields": {},
        "rationale": "forged post-checkpoint batch suffix", "result": {}})
    resumed = recovered_framework(run_dir, root, script)
    with pytest.raises(RuntimeError, match="mutation history differs"):
        resumed.evolve(TASK)
    assert not list(store.read("m0_batch_recovery_adopted"))
    assert len(list(store.read("batch_decision"))) == 0


def test_batch_admission_marker_before_mutation_fails_closed(tmp_path):
    root, script = workspace(tmp_path, "marker-workspace")
    run_dir = tmp_path / "marker"
    store = AppendOnlyStore(run_dir / "x1.jsonl")
    crash_owner(run_dir, root, script, "decision")
    cohort_id = next(store.read("batch_cycle_started"))["payload"]["cohort_id"]
    candidate_id = next(store.read("batch_decision"))["payload"]["candidate_id"]
    store.append("batch_admission", {
        "cohort_id": cohort_id, "candidate_id": candidate_id, "admit": False,
        "reason": "forged", "decision": {"mutations": []}})
    resumed = recovered_framework(run_dir, root, script)
    with pytest.raises(RuntimeError, match="admission marker precedes"):
        resumed.evolve(TASK)
    assert not list(store.read("m0_batch_recovery_adopted"))
    assert not list(store.read("batch_cycle_completed"))


if __name__ == "__main__" and len(sys.argv) == 6 and sys.argv[1] == "--owner":
    owner_main(Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4]), sys.argv[5])
