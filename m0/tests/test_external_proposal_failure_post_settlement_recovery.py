"""v45 failed-proposal recovery through settlement, finalization and control."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from core.loop import Framework, LoopConfig
from core.budget.ledger import BudgetError
from core.x1.checkpoint import certified_snapshot_ref
from core.x1.store import AppendOnlyStore
from examples.toy_gepa import MockLLM
from test_external_evaluator import TASK, evaluator, workspace
from test_external_proposal_recovery import proposer, proposer_workspace
from test_external_recovery import COMPARE, ForbiddenLLM

PROJECT = Path(__file__).resolve().parents[1]
CRASH_POINTS = (
    "settle", "settled_evidence", "absorb", "gate", "decision",
    "admission_mutation", "admission", "second_absorb", "completed",
    "admission_receipt",
)


def config(resume=False, control=False):
    return LoopConfig(max_generations=1, baseline_every=1 if control else 5,
                      batch_size=2, max_inflight=2, checkpoint_enabled=True,
                      resume_from_checkpoint=resume)


def reference_run(tmp_path, name, control=False):
    eval_root, eval_script = workspace(tmp_path, f"{name}-evaluator")
    prop_root, prop_script, count = proposer_workspace(tmp_path, f"{name}-proposer")
    run_dir = tmp_path / name
    store = AppendOnlyStore(run_dir / "x1.jsonl")
    llm = proposer(prop_root, prop_script, count, store, MockLLM(), "invalid_once")
    result = Framework(llm, evaluator(eval_root, eval_script, store),
                       config(control=control), str(run_dir)).evolve(TASK)
    return result, run_dir


def owner_main(run_dir, eval_root, eval_script, prop_root, prop_script, count,
               crash_point):
    control = crash_point in {"control_settle", "control_baseline"}
    ids = Framework(MockLLM(), None, config(control=control), str(run_dir / "ids"))
    first = ids._proposal_id(TASK, "improve:1:0")
    second = ids._proposal_id(TASK, "improve:1:1")
    control_id = ids._proposal_id(TASK, "control:1")
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
                and mutation_count == 3  # failed evidence has no PROMOTE_MEMORY
        elif crash_point == "second_absorb":
            crash = kind == "state_mutation" and mutation_target == second \
                and mutation_count == 4
        elif crash_point == "gate":
            if kind == "gate_evidence" and data.get("candidate_id") == second:
                gate_seen = True
            crash = gate_seen and kind == "receipt"
        elif crash_point == "decision":
            crash = kind == "batch_decision" and data.get("candidate_id") == first
        elif crash_point == "admission_mutation":
            crash = kind == "state_mutation" and data.get("target") == first \
                and data.get("op") == "prune"
        elif crash_point == "admission":
            crash = kind == "batch_admission" and data.get("candidate_id") == first
        elif crash_point == "completed":
            crash = kind == "batch_cycle_completed"
        elif crash_point == "admission_receipt":
            crash = kind == "admission_receipt" and data.get("candidate_id") == second
        elif crash_point == "control_settle":
            crash = kind == "ledger" and data.get("entry_kind") == "settle" \
                and data.get("account") == "control"
        elif crash_point == "control_baseline":
            crash = kind == "baseline" and data.get("candidate_id") == control_id
        if crash:
            os.kill(os.getpid(), signal.SIGKILL)

    AppendOnlyStore.append = append_with_crash
    store = AppendOnlyStore(run_dir / "x1.jsonl")
    llm = proposer(prop_root, prop_script, count, store, MockLLM(), "invalid_once")
    Framework(llm, evaluator(eval_root, eval_script, store),
              config(control=control), str(run_dir)).evolve(TASK)


def crash_owner(run_dir, eval_root, eval_script, prop_root, prop_script, count,
                crash_point):
    env = dict(os.environ)
    env.update(PYTHONPATH=str(PROJECT), PYTHONDONTWRITEBYTECODE="1")
    owner = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "--owner", str(run_dir),
         str(eval_root), str(eval_script), str(prop_root), str(prop_script), str(count),
         crash_point], cwd=PROJECT, env=env, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True)
    stdout, stderr = owner.communicate(timeout=25)
    assert owner.returncode == -signal.SIGKILL, (stdout, stderr)


def recovered_framework(run_dir, eval_root, eval_script, prop_root, prop_script, count,
                        control=False):
    store = AppendOnlyStore(run_dir / "x1.jsonl")
    llm = proposer(prop_root, prop_script, count, store, ForbiddenLLM(), "invalid_once")
    return Framework(llm, evaluator(eval_root, eval_script, store),
                     config(resume=True, control=control), str(run_dir))


def assert_failure_history(store, reference_dir, control=False):
    cohort = next(store.read("batch_cycle_started"))["payload"]
    failed_id, successful_id = cohort["candidate_ids"]
    outcomes = [row["payload"] for row in store.read("external_proposer_outcome")]
    assert [outcome["status"] for outcome in outcomes] == ["invalid", "ok"]
    proposer_processes = [row["payload"] for row in store.read("executor_process_started")
                          if row["payload"].get("process_kind") == "m0_external_proposer"]
    evaluator_processes = [row["payload"] for row in store.read("executor_process_started")
                           if row["payload"].get("process_kind", "m0_external_evaluator")
                           == "m0_external_evaluator"]
    assert len(proposer_processes) == 2
    assert len(evaluator_processes) == (3 if control else 2)
    failed = [row["payload"] for row in store.read("executor_evidence")
              if row["payload"]["evidence"]["candidate_id"] == failed_id]
    assert len(failed) == 1
    assert failed[0]["execution_id"] == proposer_processes[0]["execution_id"]
    assert failed[0]["evidence"]["eval_result"]["status"] == "invalid"
    assert len(list(store.read("batch_execution_settled"))) == 2
    assert len(list(store.read("batch_absorbed"))) == 2
    assert len(list(store.read("batch_decision"))) == 2
    assert len(list(store.read("batch_admission"))) == 2
    assert len(list(store.read("batch_cycle_completed"))) == 1
    decision = [row["payload"] for row in store.read("batch_decision")
                if row["payload"]["candidate_id"] == failed_id]
    assert len(decision) == 1 and decision[0]["decision"]["admit"] is False
    assert decision[0]["decision"]["reason"] == "execution_not_ok"
    assert not [row for row in store.read("gate_evidence")
                if row["payload"].get("candidate_id") == failed_id]
    assert not [row for row in store.read("admission_receipt")
                if row["payload"].get("candidate_id") == failed_id]
    assert [row["payload"]["candidate_id"] for row in store.read("admission_receipt")
            if row["payload"]["candidate_id"] in {failed_id, successful_id}] == [successful_id]
    adopted = list(store.read("m0_batch_recovery_adopted"))
    assert len(adopted) == 1 and adopted[0]["payload"]["reexecuted"] is False
    assert adopted[0]["payload"]["recovered_proposal_failure_ids"] == [failed_id]
    assert not list(store.read("state_mutation_rejected"))
    reference_store = AppendOnlyStore(reference_dir / "x1.jsonl")
    assert len(list(store.read("state_mutation"))) == \
        len(list(reference_store.read("state_mutation")))


def assert_completed_resume_is_noop(run_dir, eval_root, eval_script, prop_root,
                                    prop_script, count, control=False):
    store = AppendOnlyStore(run_dir / "x1.jsonl")
    counted = ("executor_process_started", "external_proposer_outcome", "executor_evidence",
               "m0_proposal_started", "m0_evaluation_started", "batch_execution_settled",
               "m0_batch_recovery_adopted", "batch_cycle_completed", "baseline")
    before = [(kind, len(list(store.read(kind)))) for kind in counted]
    completed = recovered_framework(run_dir, eval_root, eval_script, prop_root,
                                    prop_script, count, control)
    repeated = completed.evolve(TASK)
    assert repeated["completed"] is True
    assert [(kind, len(list(store.read(kind)))) for kind, _ in before] == before
    assert count.read_text().splitlines() == ["call", "call"]


@pytest.mark.parametrize("crash_point", CRASH_POINTS)
def test_failed_proposal_post_settlement_crashes_resume_exact_suffix(tmp_path, crash_point):
    expected, reference_dir = reference_run(tmp_path, f"reference-{crash_point}")
    eval_root, eval_script = workspace(tmp_path, f"crash-{crash_point}-evaluator")
    prop_root, prop_script, count = proposer_workspace(
        tmp_path, f"crash-{crash_point}-proposer")
    run_dir = tmp_path / f"recovered-{crash_point}"
    store = AppendOnlyStore(run_dir / "x1.jsonl")
    crash_owner(run_dir, eval_root, eval_script, prop_root, prop_script, count, crash_point)
    resumed = recovered_framework(run_dir, eval_root, eval_script,
                                  prop_root, prop_script, count)
    actual = resumed.evolve(TASK)
    for key in COMPARE:
        assert actual[key] == expected[key], key
    assert actual["resumed"] is True and actual["completed"] is True
    assert count.read_text().splitlines() == ["call", "call"]
    assert_failure_history(store, reference_dir)
    assert resumed.inspect()["governance_pass"] is True
    assert certified_snapshot_ref(reference_dir / "checkpoint.json") == \
        certified_snapshot_ref(run_dir / "checkpoint.json")
    assert_completed_resume_is_noop(run_dir, eval_root, eval_script,
                                    prop_root, prop_script, count)
    if crash_point in {"settle", "completed", "admission_receipt"}:
        count.write_text("")
        resumed.llm.fallback_llm = MockLLM()
        replayed = resumed.replay()
        assert resumed.inspect()["replay_certified"] is True
        for key in COMPARE:
            assert replayed[key] == expected[key], key
        assert count.read_text().splitlines() == ["call", "call"]


@pytest.mark.parametrize("crash_point", ["control_settle", "control_baseline"])
def test_failed_proposal_batch_then_control_recovers_exactly_once(tmp_path, crash_point):
    expected, reference_dir = reference_run(tmp_path, f"reference-{crash_point}", control=True)
    eval_root, eval_script = workspace(tmp_path, f"crash-{crash_point}-evaluator")
    prop_root, prop_script, count = proposer_workspace(
        tmp_path, f"crash-{crash_point}-proposer")
    run_dir = tmp_path / f"recovered-{crash_point}"
    crash_owner(run_dir, eval_root, eval_script, prop_root, prop_script, count, crash_point)
    resumed = recovered_framework(run_dir, eval_root, eval_script,
                                  prop_root, prop_script, count, control=True)
    actual = resumed.evolve(TASK)
    for key in COMPARE:
        assert actual[key] == expected[key], key
    assert actual["completed"] is True and actual["resumed"] is True
    assert_failure_history(resumed.store, reference_dir, control=True)
    assert len(list(resumed.store.read("baseline"))) == 1
    assert resumed.inspect()["governance_pass"] is True
    assert resumed.inspect()["formal_governance_pass"] is True
    assert certified_snapshot_ref(reference_dir / "checkpoint.json") == \
        certified_snapshot_ref(run_dir / "checkpoint.json")
    assert_completed_resume_is_noop(run_dir, eval_root, eval_script, prop_root,
                                    prop_script, count, control=True)


def rewrite_one(run_dir, predicate, transform):
    path = run_dir / "x1.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    matches = [index for index, row in enumerate(rows) if predicate(row)]
    assert len(matches) == 1
    rows[matches[0]] = transform(rows[matches[0]])
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows))


def crashed_run(tmp_path, name, crash_point="absorb"):
    eval_root, eval_script = workspace(tmp_path, f"{name}-evaluator")
    prop_root, prop_script, count = proposer_workspace(tmp_path, f"{name}-proposer")
    run_dir = tmp_path / name
    store = AppendOnlyStore(run_dir / "x1.jsonl")
    crash_owner(run_dir, eval_root, eval_script, prop_root, prop_script, count, crash_point)
    cohort = next(store.read("batch_cycle_started"))["payload"]
    return run_dir, store, cohort, (eval_root, eval_script, prop_root, prop_script, count)


def test_failed_settled_evidence_tamper_is_refused(tmp_path):
    run_dir, store, cohort, args = crashed_run(tmp_path, "failed-evidence-fork")
    failed_id = cohort["candidate_ids"][0]

    def predicate(row):
        return row["kind"] == "batch_execution_settled" \
            and row["payload"].get("candidate_id") == failed_id

    def transform(row):
        row["payload"]["evidence"]["result_text"] = "forged failure detail"
        return row

    rewrite_one(run_dir, predicate, transform)
    resumed = recovered_framework(run_dir, *args)
    with pytest.raises(RuntimeError, match="differs from settled evidence"):
        resumed.evolve(TASK)
    assert not list(store.read("m0_batch_recovery_adopted"))


def test_failed_candidate_wrong_ledger_cost_is_refused(tmp_path):
    run_dir, store, cohort, args = crashed_run(
        tmp_path, "failed-ledger-fork", crash_point="settled_evidence")
    intent_id = cohort["intents"][0]["intent_id"]

    def predicate(row):
        return row["kind"] == "ledger" and row["payload"].get("intent_id") == intent_id \
            and row["payload"].get("entry_kind") == "settle"

    def transform(row):
        row["payload"]["settled"] += 1
        return row

    rewrite_one(run_dir, predicate, transform)
    resumed = recovered_framework(run_dir, *args)
    with pytest.raises((BudgetError, RuntimeError, ValueError), match="ledger|settlement|cost"):
        resumed.evolve(TASK)
    assert not list(store.read("m0_batch_recovery_adopted"))


def test_failed_batch_mutation_fork_is_refused(tmp_path):
    run_dir, store, cohort, args = crashed_run(
        tmp_path, "failed-mutation-fork", crash_point="settle")
    store.append("state_mutation", {
        "op": "prune", "target": "forged-failed-candidate", "fields": {},
        "rationale": "forged post-checkpoint suffix", "result": {}})
    resumed = recovered_framework(run_dir, *args)
    with pytest.raises(RuntimeError, match="mutation history differs"):
        resumed.evolve(TASK)
    assert not list(store.read("m0_batch_recovery_adopted"))


def test_failed_candidate_forged_evaluator_process_is_refused(tmp_path):
    run_dir, store, cohort, args = crashed_run(
        tmp_path, "failed-process-fork", crash_point="completed")
    store.append("executor_process_started", {
        "execution_id": "forged-failed-evaluator", "candidate_id": cohort["candidate_ids"][0],
        "attempt": 1, "process_kind": "m0_external_evaluator",
        "execution_ref": cohort["cohort_id"], "evaluation_context": {}})
    resumed = recovered_framework(run_dir, *args)
    with pytest.raises(RuntimeError, match="recovery context mismatch"):
        resumed.evolve(TASK)
    assert not list(store.read("m0_batch_recovery_adopted"))


def test_failed_settlement_without_original_proposer_outcome_is_refused(tmp_path):
    run_dir, store, cohort, args = crashed_run(tmp_path, "missing-failure-outcome")
    path = run_dir / "x1.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    kept = [row for row in rows if not (
        row["kind"] == "external_proposer_outcome"
        and row["payload"].get("operation_id") == cohort["candidate_ids"][0])]
    assert len(kept) == len(rows) - 1
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in kept))
    resumed = recovered_framework(run_dir, *args)
    with pytest.raises(ValueError, match="ledger settlement requires explicit recovery"):
        resumed.evolve(TASK)
    assert not list(store.read("m0_batch_recovery_adopted"))


if __name__ == "__main__" and len(sys.argv) == 9 and sys.argv[1] == "--owner":
    owner_main(Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4]),
               Path(sys.argv[5]), Path(sys.argv[6]), Path(sys.argv[7]), sys.argv[8])
