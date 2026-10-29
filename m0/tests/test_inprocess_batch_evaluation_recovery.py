"""v48 real owner-SIGKILL recovery for durable in-process batch evaluations."""
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
from core.x1.checkpoint import certified_snapshot_ref
from core.x1.store import AppendOnlyStore
from examples.toy_gepa import MockLLM, toy_evaluator
from test_external_recovery import COMPARE

PROJECT = Path(__file__).resolve().parents[1]
TASK = "durable in-process batch evaluator recovery"
BATCH_POINTS = ("zero", "partial", "outcome", "settle", "settled_evidence",
                "absorb", "gate", "decision", "admission_mutation",
                "admission", "admission_receipt", "completed")
FAILURE_POINTS = ("failure_outcome", "failure_settled")
CONTROL_POINTS = ("control_outcome", "control_settle", "control_baseline")


def config(resume=False, control=False):
    return LoopConfig(max_generations=1, baseline_every=1 if control else 5,
                      batch_size=2, max_inflight=2, checkpoint_enabled=True,
                      resume_from_checkpoint=resume)


def proposal_id(run_dir, slot):
    probe = Framework(MockLLM(), None, config(), str(run_dir))
    return probe._proposal_id(TASK, slot)


class CountingLLM:
    def __init__(self, path):
        self.path = Path(path)
        self.base = MockLLM()

    def __call__(self, prompt):
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write("call\n")
        return self.base(prompt)


class CountingEvaluator:
    def __init__(self, path, fail_id=None):
        self.path = Path(path)
        self.fail_id = fail_id

    def __call__(self, candidate_id, head_sha, prompt):
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(candidate_id + "\n")
        if candidate_id == self.fail_id:
            raise RuntimeError("injected in-process batch evaluation failure")
        return toy_evaluator(candidate_id, head_sha, prompt)


class ForbiddenEvaluator:
    def __call__(self, _candidate_id, _head_sha, _prompt):
        raise AssertionError("recovery must not reexecute a durable evaluation")


class ForbiddenLLM:
    def __call__(self, _prompt):
        raise AssertionError("recovery must not propose again")


def owner_main(run_dir, crash_point):
    first = proposal_id(run_dir / "ids-first", "improve:1:0")
    second = proposal_id(run_dir / "ids-second", "improve:1:1")
    control_id = proposal_id(run_dir / "ids-control", "control:1")
    original_append = AppendOnlyStore.append
    batch_outcomes = 0
    mutation_target = None
    mutation_count = 0
    gate_seen = False

    def append_with_crash(self, kind, payload):
        nonlocal batch_outcomes, mutation_target, mutation_count, gate_seen
        original_append(self, kind, payload)
        data = payload if isinstance(payload, dict) else {}
        crash = False
        if kind == "m0_evaluation_outcome" and data.get("execution_ref"):
            batch_outcomes += 1
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

        if crash_point == "active":
            crash = kind == "m0_batch_evaluation_started" \
                and data.get("candidate_id") == first
        elif crash_point == "zero":
            crash = kind == "m0_evaluation_started" \
                and (data.get("proposal") or {}).get("proposal_id") == second
        elif crash_point == "partial":
            crash = kind == "m0_evaluation_outcome" and batch_outcomes == 1
        elif crash_point in {"outcome", "failure_outcome"}:
            crash = kind == "m0_evaluation_outcome" and batch_outcomes == 2
        elif crash_point == "settle":
            crash = kind == "ledger" and data.get("entry_kind") == "settle" \
                and data.get("account") == "exploit"
        elif crash_point in {"settled_evidence", "failure_settled"}:
            target = first if crash_point == "failure_settled" else second
            crash = kind == "batch_execution_settled" \
                and data.get("candidate_id") == target
        elif crash_point == "absorb":
            crash = kind == "state_mutation" and mutation_target == first \
                and mutation_count == 3
        elif crash_point == "gate":
            if kind == "gate_evidence" and data.get("candidate_id") == second:
                gate_seen = True
            crash = gate_seen and kind == "receipt"
        elif crash_point == "decision":
            crash = kind == "batch_decision" and data.get("candidate_id") == first
        elif crash_point == "admission_mutation":
            crash = kind == "state_mutation" and data.get("target") == first \
                and data.get("op") in {"merge", "prune"}
        elif crash_point == "admission":
            crash = kind == "batch_admission" and data.get("candidate_id") == second
        elif crash_point == "admission_receipt":
            crash = kind == "admission_receipt" and data.get("candidate_id") == second
        elif crash_point == "completed":
            crash = kind == "batch_cycle_completed"
        elif crash_point == "control_active":
            crash = kind == "m0_evaluation_started" and data.get("operator") == "iid_rs"
        elif crash_point == "control_outcome":
            crash = kind == "m0_evaluation_outcome" and data.get("operator") == "iid_rs"
        elif crash_point == "control_settle":
            crash = kind == "ledger" and data.get("entry_kind") == "settle" \
                and data.get("account") == "control"
        elif crash_point == "control_baseline":
            crash = kind == "baseline" and data.get("candidate_id") == control_id
        if crash:
            os.kill(os.getpid(), signal.SIGKILL)

    AppendOnlyStore.append = append_with_crash
    fail_id = first if crash_point in FAILURE_POINTS else None
    Framework(CountingLLM(run_dir / "llm-calls.txt"),
              CountingEvaluator(run_dir / "eval-calls.txt", fail_id),
              config(control=crash_point.startswith("control_")), str(run_dir)).evolve(TASK)


def crash_owner(run_dir, crash_point):
    env = dict(os.environ)
    env.update(PYTHONPATH=str(PROJECT), PYTHONDONTWRITEBYTECODE="1")
    owner = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "--owner", str(run_dir), crash_point],
        cwd=PROJECT, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    stdout, stderr = owner.communicate(timeout=25)
    assert owner.returncode == -signal.SIGKILL, (stdout, stderr)


def reference_run(tmp_path, name, failed=False, control=False):
    run_dir = tmp_path / name
    fail_id = proposal_id(run_dir / "reference-id", "improve:1:0") if failed else None
    framework = Framework(CountingLLM(run_dir / "llm-calls.txt"),
                          CountingEvaluator(run_dir / "eval-calls.txt", fail_id),
                          config(control=control), str(run_dir))
    return framework.evolve(TASK), run_dir


def recovered_framework(run_dir, control=False, forbidden=False):
    if forbidden:
        llm, evaluator = ForbiddenLLM(), ForbiddenEvaluator()
    else:
        llm = CountingLLM(run_dir / "llm-calls.txt")
        evaluator = CountingEvaluator(run_dir / "eval-calls.txt")
    return Framework(llm, evaluator, config(resume=True, control=control), str(run_dir))


def call_count(run_dir, name):
    path = run_dir / name
    return len(path.read_text().splitlines()) if path.exists() else 0


def assert_batch_history(run_dir, crash_point, reference_dir):
    store = AppendOnlyStore(run_dir / "x1.jsonl")
    cohort = next(store.read("batch_cycle_started"))["payload"]
    ids = cohort["candidate_ids"]
    assert len(list(store.read("m0_batch_evaluation_started"))) == 2
    assert len([row for row in store.read("m0_evaluation_outcome")
                if row["payload"].get("execution_ref") == cohort["cohort_id"]]) == 2
    assert not list(store.read("executor_process_started"))
    assert len(list(store.read("batch_execution_settled"))) == 2
    assert len(list(store.read("batch_absorbed"))) == 2
    assert len(list(store.read("batch_decision"))) == 2
    assert len(list(store.read("batch_admission"))) == 2
    assert len(list(store.read("batch_cycle_completed"))) == 1
    adopted = list(store.read("m0_batch_recovery_adopted"))
    assert len(adopted) == 1
    report = adopted[0]["payload"]
    expected_adopted = {"zero": 0, "partial": 1}.get(crash_point, 2)
    assert report["adopted_inprocess_evaluation_count"] == expected_adopted
    assert report["continued_inprocess_evaluation_count"] == 2 - expected_adopted
    assert report["process_count"] == 0 and report["reexecuted"] is False
    assert call_count(run_dir, "llm-calls.txt") == 3
    assert call_count(run_dir, "eval-calls.txt") == 3
    assert not list(store.read("state_mutation_rejected"))
    reference_store = AppendOnlyStore(reference_dir / "x1.jsonl")
    assert len(list(store.read("state_mutation"))) == \
        len(list(reference_store.read("state_mutation")))
    if crash_point in FAILURE_POINTS:
        failed = [row["payload"] for row in store.read("batch_execution_settled")
                  if row["payload"]["candidate_id"] == ids[0]]
        assert len(failed) == 1 and failed[0]["status"] == "failed_to_run"
        assert failed[0]["evidence"]["eval_result"]["cost"]["wall_seconds"] == 0.0


def assert_completed_resume_is_noop(run_dir, control=False):
    store = AppendOnlyStore(run_dir / "x1.jsonl")
    kinds = ("m0_batch_evaluation_started", "m0_evaluation_outcome", "executor_evidence",
             "batch_execution_settled", "m0_batch_recovery_adopted",
             "batch_cycle_completed", "baseline")
    before = [(kind, len(list(store.read(kind)))) for kind in kinds]
    calls = (call_count(run_dir, "llm-calls.txt"), call_count(run_dir, "eval-calls.txt"))
    repeated = recovered_framework(run_dir, control).evolve(TASK)
    assert repeated["completed"] is True
    assert [(kind, len(list(store.read(kind)))) for kind, _ in before] == before
    assert calls == (call_count(run_dir, "llm-calls.txt"),
                     call_count(run_dir, "eval-calls.txt"))


@pytest.mark.parametrize("crash_point", BATCH_POINTS)
def test_batch_terminal_outcomes_recover_exact_suffix(tmp_path, crash_point):
    expected, reference_dir = reference_run(tmp_path, f"reference-{crash_point}")
    run_dir = tmp_path / f"recovered-{crash_point}"
    crash_owner(run_dir, crash_point)
    resumed = recovered_framework(run_dir, forbidden=crash_point not in {"zero", "partial"})
    actual = resumed.evolve(TASK)
    for key in COMPARE:
        assert actual[key] == expected[key], key
    assert actual["resumed"] is True and actual["completed"] is True
    assert_batch_history(run_dir, crash_point, reference_dir)
    assert resumed.inspect()["governance_pass"] is True
    assert certified_snapshot_ref(reference_dir / "checkpoint.json") == \
        certified_snapshot_ref(run_dir / "checkpoint.json")
    assert_completed_resume_is_noop(run_dir)
    if crash_point in {"outcome", "completed", "admission_receipt"}:
        resumed.llm = MockLLM()
        resumed.evaluator = toy_evaluator
        replayed = resumed.replay()
        assert resumed.inspect()["replay_certified"] is True
        for key in COMPARE:
            assert replayed[key] == expected[key], key


@pytest.mark.parametrize("crash_point", FAILURE_POINTS)
def test_batch_failure_outcome_recovers_without_retry(tmp_path, crash_point):
    expected, reference_dir = reference_run(
        tmp_path, f"reference-{crash_point}", failed=True)
    run_dir = tmp_path / f"recovered-{crash_point}"
    crash_owner(run_dir, crash_point)
    resumed = recovered_framework(run_dir, forbidden=True)
    actual = resumed.evolve(TASK)
    for key in COMPARE:
        assert actual[key] == expected[key], key
    assert_batch_history(run_dir, crash_point, reference_dir)
    assert resumed.inspect()["governance_pass"] is True
    assert certified_snapshot_ref(reference_dir / "checkpoint.json") == \
        certified_snapshot_ref(run_dir / "checkpoint.json")


@pytest.mark.parametrize("crash_point", CONTROL_POINTS)
def test_completed_batch_then_native_control_recovers(tmp_path, crash_point):
    expected, reference_dir = reference_run(
        tmp_path, f"reference-{crash_point}", control=True)
    run_dir = tmp_path / f"recovered-{crash_point}"
    crash_owner(run_dir, crash_point)
    resumed = recovered_framework(run_dir, control=True, forbidden=True)
    actual = resumed.evolve(TASK)
    for key in COMPARE:
        assert actual[key] == expected[key], key
    assert call_count(run_dir, "llm-calls.txt") == 4
    assert call_count(run_dir, "eval-calls.txt") == 4
    assert len(list(resumed.store.read("baseline"))) == 1
    batch = list(resumed.store.read("m0_batch_recovery_adopted"))
    assert len(batch) == 1 and batch[0]["payload"]["adopted_inprocess_evaluation_count"] == 2
    control_id = proposal_id(run_dir / "control-id", "control:1")
    control = [row["payload"] for row in resumed.store.read("m0_recovery_adopted")
               if row["payload"]["candidate_id"] == control_id]
    assert len(control) == 1 and control[0]["reexecuted"] is False
    assert control[0]["settlement_reused"] is (crash_point != "control_outcome")
    assert resumed.inspect()["formal_governance_pass"] is True
    assert certified_snapshot_ref(reference_dir / "checkpoint.json") == \
        certified_snapshot_ref(run_dir / "checkpoint.json")
    assert_completed_resume_is_noop(run_dir, control=True)
    if crash_point == "control_baseline":
        resumed.llm = MockLLM()
        resumed.evaluator = toy_evaluator
        replayed = resumed.replay()
        assert resumed.inspect()["replay_certified"] is True
        for key in COMPARE:
            assert replayed[key] == expected[key], key


def crashed_run(tmp_path, name, crash_point="outcome"):
    run_dir = tmp_path / name
    crash_owner(run_dir, crash_point)
    return run_dir, AppendOnlyStore(run_dir / "x1.jsonl")


def rewrite_one(run_dir, predicate, transform):
    path = run_dir / "x1.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    matches = [row for row in rows if predicate(row)]
    assert matches
    transform(matches[0])
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows))


def test_batch_operation_without_outcome_fails_closed(tmp_path):
    run_dir, store = crashed_run(tmp_path, "active-evaluation", "active")
    assert call_count(run_dir, "eval-calls.txt") == 1  # genesis only
    with pytest.raises(RuntimeError, match="active or lacks its terminal outcome"):
        recovered_framework(run_dir).evolve(TASK)
    assert call_count(run_dir, "eval-calls.txt") == 1
    assert not list(store.read("m0_batch_recovery_adopted"))


def test_batch_control_active_start_fails_closed(tmp_path):
    run_dir, store = crashed_run(tmp_path, "active-control", "control_active")
    with pytest.raises(RuntimeError, match="no unique terminal outcome"):
        recovered_framework(run_dir, control=True, forbidden=True).evolve(TASK)
    assert call_count(run_dir, "eval-calls.txt") == 3  # genesis plus batch
    assert not list(store.read("m0_recovery_adopted"))


def test_duplicate_batch_outcome_is_refused(tmp_path):
    run_dir, store = crashed_run(tmp_path, "duplicate-outcome")
    outcome = next(row["payload"] for row in store.read("m0_evaluation_outcome")
                   if row["payload"].get("execution_ref"))
    store.append("m0_evaluation_outcome", outcome)
    with pytest.raises(RuntimeError, match="unbound or duplicated"):
        recovered_framework(run_dir, forbidden=True).evolve(TASK)


@pytest.mark.parametrize("kind,field", [
    ("m0_batch_evaluation_started", "evaluation_sha256"),
    ("m0_evaluation_outcome", "start_sha256"),
    ("m0_evaluation_outcome", "evaluation_sha256"),
])
def test_batch_operation_and_outcome_hash_forks_are_refused(tmp_path, kind, field):
    run_dir, _store = crashed_run(tmp_path, f"hash-fork-{kind}-{field}")
    rewrite_one(run_dir, lambda row: row["kind"] == kind and row["payload"].get("execution_ref")
                if kind == "m0_evaluation_outcome" else row["kind"] == kind,
                lambda row: row["payload"].update(**{field: "sha256:forged"}))
    with pytest.raises((RuntimeError, ValueError),
                       match="invalid|settlement|recovery"):
        recovered_framework(run_dir, forbidden=True).evolve(TASK)


def test_batch_outcome_result_binding_is_refused(tmp_path):
    run_dir, _store = crashed_run(tmp_path, "result-fork")
    rewrite_one(run_dir, lambda row: row["kind"] == "m0_evaluation_outcome"
                and bool(row["payload"].get("execution_ref")),
                lambda row: row["payload"]["result"].update(candidate_id="forged"))
    with pytest.raises(RuntimeError, match="result differs from its start"):
        recovered_framework(run_dir, forbidden=True).evolve(TASK)


def test_batch_outcome_cost_must_match_settlement(tmp_path):
    run_dir, _store = crashed_run(tmp_path, "cost-fork", "settle")
    rewrite_one(run_dir, lambda row: row["kind"] == "m0_evaluation_outcome"
                and bool(row["payload"].get("execution_ref")),
                lambda row: row["payload"].update(token_usage={"total_tokens": 999}))
    with pytest.raises((RuntimeError, ValueError), match="cost|settlement"):
        recovered_framework(run_dir, forbidden=True).evolve(TASK)


def test_batch_settled_evidence_must_match_outcome(tmp_path):
    run_dir, _store = crashed_run(tmp_path, "evidence-fork", "settled_evidence")
    rewrite_one(run_dir, lambda row: row["kind"] == "batch_execution_settled",
                lambda row: row["payload"]["evidence"].update(result_text="forged"))
    with pytest.raises(RuntimeError, match="differs from settled evidence"):
        recovered_framework(run_dir, forbidden=True).evolve(TASK)


def test_batch_post_checkpoint_mutation_fork_is_refused(tmp_path):
    run_dir, _store = crashed_run(tmp_path, "mutation-fork", "absorb")
    first = proposal_id(run_dir / "mutation-id", "improve:1:0")
    rewrite_one(run_dir,
                lambda row: row["kind"] == "state_mutation"
                and row["payload"].get("target") == first
                and row["payload"].get("op") == "add_node",
                lambda row: row["payload"]["fields"]["evidence"].update(result_text="forged"))
    with pytest.raises(RuntimeError, match="mutation history differs"):
        recovered_framework(run_dir, forbidden=True).evolve(TASK)


def test_completed_native_batch_resume_is_noop(tmp_path):
    _expected, run_dir = reference_run(tmp_path, "completed-reference")
    store = AppendOnlyStore(run_dir / "x1.jsonl")
    before = (len(list(store.read("m0_batch_evaluation_started"))),
              len(list(store.read("m0_evaluation_outcome"))),
              len(list(store.read("m0_batch_recovery_adopted"))))
    actual = recovered_framework(run_dir, forbidden=True).evolve(TASK)
    assert actual["completed"] is True
    after = (len(list(store.read("m0_batch_evaluation_started"))),
             len(list(store.read("m0_evaluation_outcome"))),
             len(list(store.read("m0_batch_recovery_adopted"))))
    assert after == before == (2, 3, 0)  # two batch outcomes plus genesis
    assert call_count(run_dir, "llm-calls.txt") == 3
    assert call_count(run_dir, "eval-calls.txt") == 3


if __name__ == "__main__" and len(sys.argv) == 4 and sys.argv[1] == "--owner":
    owner_main(Path(sys.argv[2]), sys.argv[3])
