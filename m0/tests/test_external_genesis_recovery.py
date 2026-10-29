"""v32 real SIGKILL recovery for genesis before its first checkpoint."""
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from core.budget.ledger import BudgetLedger
from core.loop import Framework, LoopConfig
from core.x1.checkpoint import certified_snapshot_ref
from core.x1.store import AppendOnlyStore
from examples.toy_gepa import MockLLM
from test_external_evaluator import TASK, evaluator, workspace
from test_external_recovery import COMPARE, ForbiddenLLM

PROJECT = Path(__file__).resolve().parents[1]
CRASH_POINTS = ("settle", "absorb", "gate", "admission_mutation", "admission_receipt")


def config(resume=False):
    return LoopConfig(max_generations=0, baseline_every=5, checkpoint_enabled=True,
                      resume_from_checkpoint=resume)


def genesis_id(run_dir):
    probe = Framework(MockLLM(), None, config(), str(run_dir))
    return probe._proposal_id(TASK, "genesis")


def owner_main(run_dir, root, script, crash_point):
    candidate_id = genesis_id(run_dir / "ids")
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
                and data.get("target") == candidate_id:
            armed = True
            mutation_count = 1
        elif armed and kind == "state_mutation":
            mutation_count += 1
        if crash_point == "settle":
            crash = kind == "ledger" and data.get("entry_kind") == "settle" \
                and data.get("account") == "explore"
        elif crash_point == "absorb":
            crash = kind == "state_mutation" and armed and mutation_count == 4
        elif crash_point == "gate":
            if kind == "gate_evidence" and data.get("candidate_id") == candidate_id:
                gate_seen = True
            crash = gate_seen and kind == "receipt"
        elif crash_point == "admission_mutation":
            crash = kind == "state_mutation" and data.get("target") == candidate_id \
                and data.get("op") in {"merge", "prune"}
        elif crash_point == "admission_receipt":
            crash = kind == "admission_receipt" and data.get("candidate_id") == candidate_id
        if crash:
            os.kill(os.getpid(), signal.SIGKILL)

    AppendOnlyStore.append = append_with_crash
    store = AppendOnlyStore(run_dir / "x1.jsonl")
    external = evaluator(root, script, store)
    Framework(MockLLM(), external, config(), str(run_dir)).evolve(TASK)


def start_owner(run_dir, root, script, crash_point="pre_settlement"):
    env = dict(os.environ)
    env.update(PYTHONPATH=str(PROJECT), PYTHONDONTWRITEBYTECODE="1")
    return subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "--owner", str(run_dir),
         str(root), str(script), crash_point], cwd=PROJECT, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def crash_owner(run_dir, root, script, crash_point):
    owner = start_owner(run_dir, root, script, crash_point)
    stdout, stderr = owner.communicate(timeout=20)
    assert owner.returncode == -signal.SIGKILL, (stdout, stderr)


def kill_after_genesis_started(owner, store):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        started = [row["payload"] for row in store.read("executor_process_started")
                   if (row["payload"].get("evaluation_context") or {}).get(
                       "operator") == "draft"]
        if started:
            owner.kill()
            owner.wait(timeout=5)
            return started[0]
        if owner.poll() is not None:
            stdout, stderr = owner.communicate()
            raise AssertionError(f"owner exited early: {stdout}\n{stderr}")
        time.sleep(0.02)
    owner.kill()
    owner.wait(timeout=5)
    raise AssertionError("owner did not start external genesis")


def recovered_framework(run_dir, root, script):
    store = AppendOnlyStore(run_dir / "x1.jsonl")
    external = evaluator(root, script, store)
    return Framework(ForbiddenLLM(), external, config(resume=True), str(run_dir))


def reference_run(tmp_path, name):
    root, script = workspace(tmp_path, f"{name}-workspace")
    run_dir = tmp_path / name
    store = AppendOnlyStore(run_dir / "x1.jsonl")
    framework = Framework(MockLLM(), evaluator(root, script, store), config(), str(run_dir))
    return framework.evolve(TASK), run_dir


def assert_single_genesis_history(store, candidate_id, settled_reused):
    assert len(list(store.read("executor_process_started"))) == 1
    assert len(list(store.read("external_evaluator_outcome"))) == 1
    adopted = list(store.read("m0_recovery_adopted"))
    assert len(adopted) == 1
    assert adopted[0]["payload"]["candidate_id"] == candidate_id
    assert adopted[0]["payload"]["settlement_reused"] is settled_reused
    assert adopted[0]["payload"]["reexecuted"] is False
    assert len([row for row in store.read("ledger")
                if row["payload"].get("account") == "explore"
                and row["payload"].get("entry_kind") == "settle"]) == 1
    assert len([row for row in store.read("gate_evidence")
                if row["payload"].get("candidate_id") == candidate_id]) == 1
    assert len([row for row in store.read("admission_receipt")
                if row["payload"].get("candidate_id") == candidate_id]) == 1
    assert len(list(store.read("state_mutation"))) == 5
    assert not list(store.read("state_mutation_rejected"))


def test_real_genesis_pre_settlement_crash_adopts_native_outcome_exactly_once(tmp_path):
    expected, reference_dir = reference_run(tmp_path, "reference-pre-settlement")
    root, script = workspace(tmp_path, "pre-settlement-workspace")
    run_dir = tmp_path / "recovered-pre-settlement"
    store = AppendOnlyStore(run_dir / "x1.jsonl")
    owner = start_owner(run_dir, root, script)
    started = kill_after_genesis_started(owner, store)
    candidate_id = started["evaluation_context"]["proposal"]["proposal_id"]
    assert not (run_dir / "checkpoint.json").exists()

    resumed = recovered_framework(run_dir, root, script)
    actual = resumed.evolve(TASK)
    for key in COMPARE:
        assert actual[key] == expected[key], key
    assert actual["resumed"] is True and actual["completed"] is True
    assert_single_genesis_history(store, candidate_id, settled_reused=False)
    assert resumed.inspect()["governance_pass"] is True
    assert certified_snapshot_ref(reference_dir / "checkpoint.json") == \
        certified_snapshot_ref(run_dir / "checkpoint.json")
    resumed.llm = MockLLM()
    replayed = resumed.replay()
    assert resumed.inspect()["replay_certified"] is True
    for key in COMPARE:
        assert replayed[key] == expected[key], key


@pytest.mark.parametrize("crash_point", CRASH_POINTS)
def test_real_genesis_post_settlement_crashes_resume_only_missing_suffix(
        tmp_path, crash_point):
    expected, reference_dir = reference_run(tmp_path, f"reference-{crash_point}")
    root, script = workspace(tmp_path, f"crash-{crash_point}-workspace")
    run_dir = tmp_path / f"recovered-{crash_point}"
    crash_owner(run_dir, root, script, crash_point)
    assert not (run_dir / "checkpoint.json").exists()
    resumed = recovered_framework(run_dir, root, script)
    actual = resumed.evolve(TASK)
    for key in COMPARE:
        assert actual[key] == expected[key], key
    candidate_id = genesis_id(run_dir / "expected-id")
    assert_single_genesis_history(resumed.store, candidate_id, settled_reused=True)
    assert resumed.inspect()["governance_pass"] is True
    assert certified_snapshot_ref(reference_dir / "checkpoint.json") == \
        certified_snapshot_ref(run_dir / "checkpoint.json")
    if crash_point == "admission_receipt":
        resumed.llm = MockLLM()
        replayed = resumed.replay()
        assert resumed.inspect()["replay_certified"] is True
        for key in COMPARE:
            assert replayed[key] == expected[key], key


def test_genesis_mutation_fork_is_refused_before_adoption(tmp_path):
    root, script = workspace(tmp_path, "fork-workspace")
    run_dir = tmp_path / "fork"
    crash_owner(run_dir, root, script, "settle")
    store = AppendOnlyStore(run_dir / "x1.jsonl")
    store.append("state_mutation", {
        "op": "prune", "target": "forged-candidate", "fields": {},
        "rationale": "forged genesis suffix", "result": {}})
    resumed = recovered_framework(run_dir, root, script)
    with pytest.raises(RuntimeError, match="mutation history differs"):
        resumed.evolve(TASK)
    assert not list(store.read("m0_recovery_adopted"))
    assert not list(store.read("admission_receipt"))


def test_genesis_recovery_refuses_existing_checkpoint_evidence(tmp_path):
    _, run_dir = reference_run(tmp_path, "complete")
    (run_dir / "checkpoint.json").unlink()
    root, script = workspace(tmp_path, "checkpoint-evidence-workspace")
    resumed = recovered_framework(run_dir, root, script)
    with pytest.raises(RuntimeError, match="absence of checkpoints"):
        resumed.evolve(TASK)


def test_genesis_recovery_refuses_unrelated_budget_activity(tmp_path):
    root, script = workspace(tmp_path, "budget-workspace")
    run_dir = tmp_path / "budget"
    crash_owner(run_dir, root, script, "settle")
    store = AppendOnlyStore(run_dir / "x1.jsonl")
    probe = Framework(MockLLM(), None, config(), str(run_dir / "ledger-probe"))
    ledger = BudgetLedger(60_000, 0.05, 1_000, probe.stamp, store)
    ledger.restore_from_journal()
    from core.policy.types import AllocationIntent
    unrelated = AllocationIntent(intent_id="other", policy_id="unrelated",
                                 candidate_ref="other-candidate", requested=7,
                                 snapshot_ref="snap", account="exploit")
    assert ledger.quote_reserve(unrelated).verdict == "granted"
    resumed = recovered_framework(run_dir, root, script)
    with pytest.raises(RuntimeError, match="unrelated budget activity"):
        resumed.evolve(TASK)
    assert not list(store.read("m0_recovery_adopted"))


def test_genesis_recovery_refuses_multiple_run_starts(tmp_path):
    root, script = workspace(tmp_path, "multiple-starts-workspace")
    run_dir = tmp_path / "multiple-starts"
    crash_owner(run_dir, root, script, "settle")
    store = AppendOnlyStore(run_dir / "x1.jsonl")
    start = next(store.read("run_start"))
    store.append("run_start", start["payload"])
    resumed = recovered_framework(run_dir, root, script)
    with pytest.raises(RuntimeError, match="one run and one evaluation start"):
        resumed.evolve(TASK)


def test_genesis_recovery_refuses_wrong_candidate_lineage(tmp_path):
    root, script = workspace(tmp_path, "wrong-candidate-workspace")
    run_dir = tmp_path / "wrong-candidate"
    crash_owner(run_dir, root, script, "settle")
    candidate_id = genesis_id(run_dir / "wrong-candidate-id")
    evidence = run_dir / "x1.jsonl"
    evidence.write_text(evidence.read_text().replace(candidate_id, "forged-genesis"))
    resumed = recovered_framework(run_dir, root, script)
    with pytest.raises(RuntimeError, match="candidate differs from run lineage"):
        resumed.evolve(TASK)


def test_genesis_recovery_requires_run_start_anchor(tmp_path):
    root, script = workspace(tmp_path, "missing-anchor-workspace")
    run_dir = tmp_path / "missing-anchor"
    crash_owner(run_dir, root, script, "settle")
    stripped = tmp_path / "missing-anchor-stripped"
    stripped.mkdir()
    source = AppendOnlyStore(run_dir / "x1.jsonl")
    target = AppendOnlyStore(stripped / "x1.jsonl")
    for record in source.read():
        if record["kind"] != "run_start":
            target.append(record["kind"], record["payload"])
    resumed = recovered_framework(stripped, root, script)
    with pytest.raises(RuntimeError, match="one run and one evaluation start"):
        resumed.evolve(TASK)


if __name__ == "__main__" and len(sys.argv) == 6 and sys.argv[1] == "--owner":
    owner_main(Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4]), sys.argv[5])
