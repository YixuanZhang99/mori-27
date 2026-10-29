"""v30 real owner-SIGKILL recovery for sequential external M0 improvement."""
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from core.budget.ledger import BudgetLedger
from core.loop import Framework, LoopConfig
from core.policy.types import AllocationIntent
from core.x1.checkpoint import certified_snapshot_ref
from core.x1.store import AppendOnlyStore
from examples.toy_gepa import MockLLM
from test_external_evaluator import TASK, evaluator, workspace

PROJECT = Path(__file__).resolve().parents[1]
COMPARE = ("best_prompt", "best_score", "self_attestation", "governance_audit",
           "main_scores", "baseline_scores", "accepted_candidate_ids", "generations",
           "ledger", "health", "governed_state")


class ForbiddenLLM:
    def __call__(self, _prompt):
        raise AssertionError("recovery must not propose or execute the candidate again")


def config(resume=False):
    return LoopConfig(max_generations=1, baseline_every=5, checkpoint_enabled=True,
                      resume_from_checkpoint=resume)


def start_owner(run_dir, root, script):
    env = dict(os.environ)
    env.update(PYTHONPATH=str(PROJECT), PYTHONDONTWRITEBYTECODE="1")
    return subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "--owner", str(run_dir),
         str(root), str(script)], cwd=PROJECT, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def kill_after_improve_started(owner, store, run_dir):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        started = [row["payload"] for row in store.read("executor_process_started")
                   if (row["payload"].get("evaluation_context") or {}).get(
                       "operator") == "improve"]
        if started and (run_dir / "checkpoint.json").exists():
            owner.kill()
            owner.wait(timeout=5)
            return started[0]
        if owner.poll() is not None:
            stdout, stderr = owner.communicate()
            raise AssertionError(f"owner exited early: {stdout}\n{stderr}")
        time.sleep(0.02)
    owner.kill()
    owner.wait(timeout=5)
    raise AssertionError("owner did not start external improvement")


def test_real_owner_crash_adopts_without_reproposal_reexecution_or_duplicate_receipt(tmp_path):
    reference_root, reference_script = workspace(tmp_path, "reference-external")
    reference_dir = tmp_path / "reference"
    reference_store = AppendOnlyStore(reference_dir / "x1.jsonl")
    reference = Framework(MockLLM(), evaluator(reference_root, reference_script,
                                               reference_store),
                          config(), str(reference_dir))
    expected = reference.evolve(TASK)

    root, script = workspace(tmp_path, "crash-external")
    run_dir = tmp_path / "recovered"
    store = AppendOnlyStore(run_dir / "x1.jsonl")
    owner = start_owner(run_dir, root, script)
    started = kill_after_improve_started(owner, store, run_dir)
    candidate_id = started["evaluation_context"]["proposal"]["proposal_id"]

    recovery_store = AppendOnlyStore(run_dir / "x1.jsonl")
    external = evaluator(root, script, recovery_store, "delayed_non_genesis",
                         Framework(MockLLM(), None, LoopConfig(), str(tmp_path / "ids"))
                         ._proposal_id(TASK, "genesis"))
    resumed = Framework(ForbiddenLLM(), external, config(resume=True), str(run_dir))
    actual = resumed.evolve(TASK)
    for key in COMPARE:
        assert actual[key] == expected[key], key
    assert actual["resumed"] is True and actual["completed"] is True
    assert len(list(store.read("executor_process_started"))) == 2
    assert len(list(store.read("external_evaluator_outcome"))) == 2
    adopted = list(store.read("m0_recovery_adopted"))
    assert len(adopted) == 1
    assert adopted[0]["payload"]["candidate_id"] == candidate_id
    assert adopted[0]["payload"]["reexecuted"] is False
    improve_gates = [row for row in store.read("gate_evidence")
                     if row["payload"]["candidate_id"] == candidate_id]
    assert len(improve_gates) == 1
    assert len(list(store.read("admission_receipt"))) == 2
    assert resumed.inspect()["governance_pass"] is True
    assert certified_snapshot_ref(reference_dir / "checkpoint.json") == \
        certified_snapshot_ref(run_dir / "checkpoint.json")

    resumed.llm = MockLLM()  # Fresh certified replay is execution, not crash adoption.
    replayed = resumed.replay()
    assert resumed.inspect()["replay_certified"] is True
    for key in COMPARE:
        assert replayed[key] == expected[key], key


def test_post_checkpoint_settlement_is_refused_instead_of_settling_twice(tmp_path):
    root, script = workspace(tmp_path, "ambiguous-external")
    run_dir = tmp_path / "ambiguous"
    store = AppendOnlyStore(run_dir / "x1.jsonl")
    owner = start_owner(run_dir, root, script)
    started = kill_after_improve_started(owner, store, run_dir)
    context = started["evaluation_context"]
    probe = Framework(MockLLM(), None, LoopConfig(), str(tmp_path / "ledger-probe"))
    ledger = BudgetLedger(60_000, 0.05, 1_000, probe.stamp, store)
    ledger.restore_from_journal()
    ledger.settle(AllocationIntent(**context["intent"]), actual_cost=7)

    external = evaluator(root, script, store)
    resumed = Framework(ForbiddenLLM(), external, config(resume=True), str(run_dir))
    with pytest.raises(ValueError, match="post-checkpoint ledger settlement"):
        resumed.evolve(TASK)
    assert not list(store.read("m0_recovery_adopted"))
    assert len(list(store.read("executor_process_started"))) == 2


def owner_main(run_dir, root, script):
    store = AppendOnlyStore(run_dir / "x1.jsonl")
    probe = Framework(MockLLM(), None, LoopConfig(), str(run_dir / "ids"))
    genesis = probe._proposal_id(TASK, "genesis")
    external = evaluator(root, script, store, "delayed_non_genesis", genesis)
    Framework(MockLLM(), external, config(), str(run_dir)).evolve(TASK)


if __name__ == "__main__" and len(sys.argv) == 5 and sys.argv[1] == "--owner":
    owner_main(Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4]))
