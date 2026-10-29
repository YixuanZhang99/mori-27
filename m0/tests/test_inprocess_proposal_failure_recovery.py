"""v46 durable in-process proposal failure recovery without active-call claims."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from core.loop import Framework
from core.budget.ledger import BudgetError
from core.x1.checkpoint import certified_snapshot_ref
from core.x1.store import AppendOnlyStore
from examples.toy_gepa import MockLLM
from test_external_evaluator import TASK, evaluator, workspace
from test_external_proposal_failure_post_settlement_recovery import config, rewrite_one
from test_external_recovery import COMPARE

PROJECT = Path(__file__).resolve().parents[1]
CRASH_POINTS = (
    "outcome", "settle", "settled_evidence", "absorb", "gate", "decision",
    "admission_mutation", "admission", "second_absorb", "completed",
    "admission_receipt",
)


class FailOnceLLM:
    """Fail only the first improve; the shared file proves retry counts across owners."""

    def __init__(self, count):
        self.count = Path(count)
        self.base = MockLLM()
        self.last_usage = {"total_tokens": 0}

    def __call__(self, prompt):
        with self.count.open("a") as stream:
            stream.write("call\n")
        call_number = len(self.count.read_text().splitlines())
        self.last_usage = {"total_tokens": 0}
        if call_number == 2:
            raise RuntimeError("injected in-process proposal failure")
        content = self.base(prompt)
        self.last_usage = dict(self.base.last_usage)
        return content


def reference_run(tmp_path, name, control=False):
    eval_root, eval_script = workspace(tmp_path, f"{name}-evaluator")
    run_dir = tmp_path / name
    count = tmp_path / f"{name}-calls.txt"
    count.write_text("")
    store = AppendOnlyStore(run_dir / "x1.jsonl")
    result = Framework(FailOnceLLM(count), evaluator(eval_root, eval_script, store),
                       config(control=control), str(run_dir)).evolve(TASK)
    return result, run_dir


def owner_main(run_dir, eval_root, eval_script, count, crash_point):
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

        if crash_point == "marker":
            crash = kind == "m0_proposal_started" and data.get("candidate_id") == first
        elif crash_point == "outcome":
            crash = kind == "m0_proposal_outcome" and data.get("candidate_id") == first
        elif crash_point == "settle":
            crash = kind == "ledger" and data.get("entry_kind") == "settle" \
                and data.get("account") == "exploit"
        elif crash_point == "settled_evidence":
            crash = kind == "batch_execution_settled" and data.get("candidate_id") == first
        elif crash_point == "absorb":
            crash = kind == "state_mutation" and mutation_target == first \
                and mutation_count == 3
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
    Framework(FailOnceLLM(count), evaluator(eval_root, eval_script, store),
              config(control=control), str(run_dir)).evolve(TASK)


def crash_owner(run_dir, eval_root, eval_script, count, crash_point):
    env = dict(os.environ)
    env.update(PYTHONPATH=str(PROJECT), PYTHONDONTWRITEBYTECODE="1")
    owner = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "--owner", str(run_dir),
         str(eval_root), str(eval_script), str(count), crash_point], cwd=PROJECT,
        env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    stdout, stderr = owner.communicate(timeout=25)
    assert owner.returncode == -signal.SIGKILL, (stdout, stderr)


def recovered_framework(run_dir, eval_root, eval_script, count, control=False):
    store = AppendOnlyStore(run_dir / "x1.jsonl")
    return Framework(FailOnceLLM(count), evaluator(eval_root, eval_script, store),
                     config(resume=True, control=control), str(run_dir))


def assert_failure_history(store, reference_dir, control=False):
    cohort = next(store.read("batch_cycle_started"))["payload"]
    failed_id, successful_id = cohort["candidate_ids"]
    outcomes = [row["payload"] for row in store.read("m0_proposal_outcome")]
    assert len(outcomes) == 1
    assert outcomes[0]["status"] == "failed_to_run"
    assert outcomes[0]["adapter"] == "in_process"
    assert outcomes[0]["candidate_id"] == failed_id
    assert not list(store.read("external_proposer_outcome"))
    evaluator_processes = [row["payload"] for row in store.read("executor_process_started")
                           if row["payload"].get("process_kind", "m0_external_evaluator")
                           == "m0_external_evaluator"]
    assert len(evaluator_processes) == (3 if control else 2)
    assert failed_id not in {row["candidate_id"] for row in evaluator_processes}
    failed = [row["payload"] for row in store.read("executor_evidence")
              if row["payload"]["evidence"]["candidate_id"] == failed_id]
    assert len(failed) == 1
    assert failed[0]["execution_id"] == outcomes[0]["execution_id"]
    assert failed[0]["evidence"]["eval_result"]["status"] == "failed_to_run"
    assert failed[0]["evidence"]["eval_result"]["cost"]["wall_seconds"] == 0.0
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
    assert [row["payload"]["candidate_id"] for row in store.read("admission_receipt")
            if row["payload"]["candidate_id"] in {failed_id, successful_id}] == [successful_id]
    adopted = list(store.read("m0_batch_recovery_adopted"))
    assert len(adopted) == 1 and adopted[0]["payload"]["reexecuted"] is False
    assert adopted[0]["payload"]["recovered_proposal_failure_ids"] == [failed_id]
    assert not list(store.read("state_mutation_rejected"))
    reference_store = AppendOnlyStore(reference_dir / "x1.jsonl")
    assert len(list(store.read("state_mutation"))) == \
        len(list(reference_store.read("state_mutation")))


def assert_completed_resume_is_noop(run_dir, eval_root, eval_script, count, control=False):
    store = AppendOnlyStore(run_dir / "x1.jsonl")
    counted = ("executor_process_started", "m0_proposal_outcome", "executor_evidence",
               "m0_proposal_started", "m0_evaluation_started", "batch_execution_settled",
               "m0_batch_recovery_adopted", "batch_cycle_completed", "baseline")
    before = [(kind, len(list(store.read(kind)))) for kind in counted]
    before_calls = count.read_text()
    completed = recovered_framework(run_dir, eval_root, eval_script, count, control)
    repeated = completed.evolve(TASK)
    assert repeated["completed"] is True
    assert [(kind, len(list(store.read(kind)))) for kind, _ in before] == before
    assert count.read_text() == before_calls


@pytest.mark.parametrize("crash_point", CRASH_POINTS)
def test_inprocess_failure_crashes_resume_without_retry(tmp_path, crash_point):
    expected, reference_dir = reference_run(tmp_path, f"reference-{crash_point}")
    eval_root, eval_script = workspace(tmp_path, f"crash-{crash_point}-evaluator")
    run_dir = tmp_path / f"recovered-{crash_point}"
    count = tmp_path / f"crash-{crash_point}-calls.txt"
    count.write_text("")
    crash_owner(run_dir, eval_root, eval_script, count, crash_point)
    if crash_point == "outcome":
        assert count.read_text().splitlines() == ["call", "call"]
        assert len(list(AppendOnlyStore(run_dir / "x1.jsonl").read(
            "m0_proposal_outcome"))) == 1
    resumed = recovered_framework(run_dir, eval_root, eval_script, count)
    actual = resumed.evolve(TASK)
    for key in COMPARE:
        assert actual[key] == expected[key], key
    assert actual["resumed"] is True and actual["completed"] is True
    assert count.read_text().splitlines() == ["call", "call", "call"]
    assert_failure_history(resumed.store, reference_dir)
    assert resumed.inspect()["governance_pass"] is True
    assert certified_snapshot_ref(reference_dir / "checkpoint.json") == \
        certified_snapshot_ref(run_dir / "checkpoint.json")
    assert_completed_resume_is_noop(run_dir, eval_root, eval_script, count)
    if crash_point in {"outcome", "completed", "admission_receipt"}:
        count.write_text("")
        replayed = resumed.replay()
        assert resumed.inspect()["replay_certified"] is True
        for key in COMPARE:
            assert replayed[key] == expected[key], key
        assert count.read_text().splitlines() == ["call", "call", "call"]


@pytest.mark.parametrize("crash_point", ["control_settle", "control_baseline"])
def test_inprocess_failure_batch_then_control_recovers(tmp_path, crash_point):
    expected, reference_dir = reference_run(tmp_path, f"reference-{crash_point}", control=True)
    eval_root, eval_script = workspace(tmp_path, f"crash-{crash_point}-evaluator")
    run_dir = tmp_path / f"recovered-{crash_point}"
    count = tmp_path / f"crash-{crash_point}-calls.txt"
    count.write_text("")
    crash_owner(run_dir, eval_root, eval_script, count, crash_point)
    resumed = recovered_framework(run_dir, eval_root, eval_script, count, control=True)
    actual = resumed.evolve(TASK)
    for key in COMPARE:
        assert actual[key] == expected[key], key
    assert actual["completed"] is True and actual["resumed"] is True
    assert count.read_text().splitlines() == ["call"] * 4
    assert_failure_history(resumed.store, reference_dir, control=True)
    assert len(list(resumed.store.read("baseline"))) == 1
    assert resumed.inspect()["formal_governance_pass"] is True
    assert certified_snapshot_ref(reference_dir / "checkpoint.json") == \
        certified_snapshot_ref(run_dir / "checkpoint.json")
    assert_completed_resume_is_noop(run_dir, eval_root, eval_script, count, control=True)


def crashed_run(tmp_path, name, crash_point="absorb"):
    eval_root, eval_script = workspace(tmp_path, f"{name}-evaluator")
    run_dir = tmp_path / name
    count = tmp_path / f"{name}-calls.txt"
    count.write_text("")
    crash_owner(run_dir, eval_root, eval_script, count, crash_point)
    store = AppendOnlyStore(run_dir / "x1.jsonl")
    cohort = next(store.read("batch_cycle_started"))["payload"]
    return run_dir, store, cohort, (eval_root, eval_script, count)


def test_inprocess_active_marker_remains_fail_closed(tmp_path):
    run_dir, store, cohort, args = crashed_run(
        tmp_path, "inprocess-active-marker", crash_point="marker")
    count = args[-1]
    assert count.read_text().splitlines() == ["call"]  # genesis only
    assert not list(store.read("m0_proposal_outcome"))
    resumed = recovered_framework(run_dir, *args)
    with pytest.raises(RuntimeError, match="proposal operation is ambiguous"):
        resumed.evolve(TASK)
    assert count.read_text().splitlines() == ["call"]
    assert not list(store.read("m0_batch_recovery_adopted"))


def test_inprocess_outcome_marker_tamper_is_refused(tmp_path):
    run_dir, store, cohort, args = crashed_run(
        tmp_path, "inprocess-marker-fork", crash_point="outcome")
    failed_id = cohort["candidate_ids"][0]

    def predicate(row):
        return row["kind"] == "m0_proposal_outcome" \
            and row["payload"].get("candidate_id") == failed_id

    def transform(row):
        row["payload"]["marker_sha256"] = "sha256:" + "0" * 64
        return row

    rewrite_one(run_dir, predicate, transform)
    resumed = recovered_framework(run_dir, *args)
    with pytest.raises(RuntimeError, match="exact marker"):
        resumed.evolve(TASK)
    assert args[-1].read_text().splitlines() == ["call", "call"]
    assert not list(store.read("m0_batch_recovery_adopted"))


def test_inprocess_settled_evidence_tamper_is_refused(tmp_path):
    run_dir, store, cohort, args = crashed_run(tmp_path, "inprocess-evidence-fork")
    failed_id = cohort["candidate_ids"][0]

    def predicate(row):
        return row["kind"] == "batch_execution_settled" \
            and row["payload"].get("candidate_id") == failed_id

    def transform(row):
        row["payload"]["evidence"]["result_text"] = "forged in-process detail"
        return row

    rewrite_one(run_dir, predicate, transform)
    resumed = recovered_framework(run_dir, *args)
    with pytest.raises(RuntimeError, match="differs from settled evidence"):
        resumed.evolve(TASK)
    assert not list(store.read("m0_batch_recovery_adopted"))


def test_inprocess_wrong_ledger_cost_is_refused(tmp_path):
    run_dir, store, cohort, args = crashed_run(
        tmp_path, "inprocess-ledger-fork", crash_point="settled_evidence")
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


def test_inprocess_settlement_without_outcome_is_refused(tmp_path):
    run_dir, store, cohort, args = crashed_run(tmp_path, "inprocess-missing-outcome")
    path = run_dir / "x1.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    kept = [row for row in rows if row["kind"] != "m0_proposal_outcome"]
    assert len(kept) == len(rows) - 1
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in kept))
    resumed = recovered_framework(run_dir, *args)
    with pytest.raises(ValueError, match="ledger settlement requires explicit recovery"):
        resumed.evolve(TASK)
    assert not list(store.read("m0_batch_recovery_adopted"))


if __name__ == "__main__" and len(sys.argv) == 7 and sys.argv[1] == "--owner":
    owner_main(Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4]),
               Path(sys.argv[5]), sys.argv[6])
