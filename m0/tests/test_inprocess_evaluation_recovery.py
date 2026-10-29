"""v47 real owner-SIGKILL recovery for durable sequential in-process evaluations."""
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
TASK = "durable in-process evaluator recovery"
IMPROVE_POINTS = ("outcome", "settle", "absorb", "gate", "admission_mutation",
                  "admission_receipt", "failure_evidence")
GENESIS_POINTS = ("outcome", "settle", "absorb", "gate", "admission_mutation",
                  "admission_receipt")
CONTROL_POINTS = ("outcome", "settle", "baseline", "failure_evidence")


def config(mode, resume=False):
    return LoopConfig(max_generations=0 if mode == "genesis" else 1,
                      baseline_every=1 if mode == "control" else 5,
                      checkpoint_enabled=True, resume_from_checkpoint=resume)


def proposal_id(run_dir, mode):
    slot = {"genesis": "genesis", "improve": "improve:1", "control": "control:1"}[mode]
    probe = Framework(MockLLM(), None, config(mode), str(run_dir))
    return probe._proposal_id(TASK, slot)


class CountingEvaluator:
    def __init__(self, count_path, fail_id=None):
        self.count_path = Path(count_path)
        self.fail_id = fail_id

    def __call__(self, candidate_id, head_sha, prompt):
        self.last_usage = {"total_tokens": 0}
        with self.count_path.open("a", encoding="utf-8") as handle:
            handle.write(candidate_id + "\n")
        if candidate_id == self.fail_id:
            raise RuntimeError("injected in-process evaluation failure")
        return toy_evaluator(candidate_id, head_sha, prompt)


class ForbiddenEvaluator:
    def __call__(self, _candidate_id, _head_sha, _prompt):
        raise AssertionError("recovery must not reexecute an in-process evaluation")


class ForbiddenLLM:
    def __call__(self, _prompt):
        raise AssertionError("recovery must not propose again")


def owner_main(run_dir, mode, crash_point):
    candidate_id = proposal_id(run_dir / "ids", mode)
    operator = {"genesis": "draft", "improve": "improve", "control": "iid_rs"}[mode]
    account = {"genesis": "explore", "improve": "exploit", "control": "control"}[mode]
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
        if crash_point == "active":
            crash = kind == "m0_evaluation_started" and data.get("operator") == operator
        elif crash_point == "outcome":
            crash = kind == "m0_evaluation_outcome" and data.get("operator") == operator
        elif crash_point == "settle":
            crash = kind == "ledger" and data.get("entry_kind") == "settle" \
                and data.get("account") == account
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
        elif crash_point == "baseline":
            crash = kind == "baseline" and data.get("candidate_id") == candidate_id
        elif crash_point == "failure_evidence":
            crash = kind == "executor_evidence" \
                and (data.get("evidence") or {}).get("candidate_id") == candidate_id
        if crash:
            os.kill(os.getpid(), signal.SIGKILL)

    AppendOnlyStore.append = append_with_crash
    store = AppendOnlyStore(run_dir / "x1.jsonl")
    fail_id = candidate_id if crash_point == "failure_evidence" else None
    evaluator = CountingEvaluator(run_dir / "calls.txt", fail_id)
    Framework(MockLLM(), evaluator, config(mode), str(run_dir)).evolve(TASK)


def crash_owner(run_dir, mode, crash_point):
    env = dict(os.environ)
    env.update(PYTHONPATH=str(PROJECT), PYTHONDONTWRITEBYTECODE="1")
    owner = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "--owner", str(run_dir),
         mode, crash_point], cwd=PROJECT, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    stdout, stderr = owner.communicate(timeout=20)
    assert owner.returncode == -signal.SIGKILL, (stdout, stderr)


def reference_run(tmp_path, mode, failed=False):
    run_dir = tmp_path / f"reference-{mode}-{failed}"
    candidate_id = proposal_id(run_dir / "reference-id", mode)
    evaluator = CountingEvaluator(run_dir / "calls.txt", candidate_id if failed else None)
    framework = Framework(MockLLM(), evaluator, config(mode), str(run_dir))
    return framework.evolve(TASK), run_dir


def recovered_framework(run_dir, mode, forbidden=True):
    evaluator = ForbiddenEvaluator() if forbidden else toy_evaluator
    llm = ForbiddenLLM() if forbidden else MockLLM()
    return Framework(llm, evaluator, config(mode, resume=True), str(run_dir))


def assert_recovered(mode, crash_point, tmp_path):
    failed = crash_point == "failure_evidence"
    expected, reference_dir = reference_run(tmp_path, mode, failed)
    run_dir = tmp_path / f"recovered-{mode}-{crash_point}"
    crash_owner(run_dir, mode, crash_point)
    resumed = recovered_framework(run_dir, mode)
    actual = resumed.evolve(TASK)
    for key in COMPARE:
        assert actual[key] == expected[key], key
    assert actual["resumed"] is True and actual["completed"] is True
    store = resumed.store
    candidate_id = proposal_id(run_dir / "expected-id", mode)
    expected_calls = {"genesis": 1, "improve": 2, "control": 3}[mode]
    assert len((run_dir / "calls.txt").read_text().splitlines()) == expected_calls
    assert len(list(store.read("m0_evaluation_outcome"))) == expected_calls
    assert not list(store.read("executor_process_started"))
    adoptions = [row["payload"] for row in store.read("m0_recovery_adopted")]
    target = [row for row in adoptions if row["candidate_id"] == candidate_id]
    assert len(target) == 1
    assert target[0]["settlement_reused"] is (crash_point != "outcome")
    assert target[0]["reexecuted"] is False
    assert target[0]["execution_id"].startswith("m0-inprocess-evaluation-")
    assert len(adoptions) == (2 if mode == "control" else 1)
    assert resumed.inspect()["governance_pass"] is True
    if mode == "control":
        assert resumed.inspect()["formal_governance_pass"] is (not failed)
    assert certified_snapshot_ref(reference_dir / "checkpoint.json") == \
        certified_snapshot_ref(run_dir / "checkpoint.json")
    replay_point = (mode == "control" and crash_point == "baseline") or (
        mode != "control" and crash_point == "admission_receipt")
    if replay_point:
        resumed.llm = MockLLM()
        resumed.evaluator = toy_evaluator
        replayed = resumed.replay()
        assert resumed.inspect()["replay_certified"] is True
        for key in COMPARE:
            assert replayed[key] == expected[key], key
    return run_dir


@pytest.mark.parametrize("crash_point", IMPROVE_POINTS)
def test_improve_terminal_outcome_recovers_exact_suffix(tmp_path, crash_point):
    assert_recovered("improve", crash_point, tmp_path)


@pytest.mark.parametrize("crash_point", GENESIS_POINTS)
def test_genesis_terminal_outcome_recovers_exact_suffix(tmp_path, crash_point):
    assert_recovered("genesis", crash_point, tmp_path)


@pytest.mark.parametrize("crash_point", CONTROL_POINTS)
def test_control_terminal_outcome_recovers_exact_suffix(tmp_path, crash_point):
    assert_recovered("control", crash_point, tmp_path)


def test_start_without_outcome_or_legacy_active_call_fails_closed(tmp_path):
    run_dir = tmp_path / "active-improve"
    crash_owner(run_dir, "improve", "active")
    store = AppendOnlyStore(run_dir / "x1.jsonl")
    assert len(list(store.read("m0_evaluation_outcome"))) == 1  # genesis only
    resumed = recovered_framework(run_dir, "improve")
    with pytest.raises(RuntimeError, match="no unique terminal outcome"):
        resumed.evolve(TASK)
    assert not list(store.read("m0_recovery_adopted"))
    assert len((run_dir / "calls.txt").read_text().splitlines()) == 1


def edit_target_outcome(run_dir, operator, edit):
    path = run_dir / "x1.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    matches = [row for row in rows if row["kind"] == "m0_evaluation_outcome"
               and row["payload"].get("operator") == operator]
    assert len(matches) == 1
    edit(matches[0]["payload"])
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


def test_outcome_start_hash_tamper_is_refused(tmp_path):
    run_dir = tmp_path / "hash-fork"
    crash_owner(run_dir, "improve", "settle")
    edit_target_outcome(run_dir, "improve", lambda row: row.update(start_sha256="sha256:forged"))
    with pytest.raises((RuntimeError, ValueError),
                       match="no unique terminal outcome|binding is invalid|post-checkpoint ledger settlement"):
        recovered_framework(run_dir, "improve").evolve(TASK)


def test_outcome_result_binding_tamper_is_refused(tmp_path):
    run_dir = tmp_path / "result-fork"
    crash_owner(run_dir, "improve", "settle")
    edit_target_outcome(run_dir, "improve",
                        lambda row: row["result"].update(candidate_id="forged"))
    with pytest.raises(RuntimeError, match="result differs from its start"):
        recovered_framework(run_dir, "improve").evolve(TASK)


def test_outcome_cost_must_match_settlement(tmp_path):
    run_dir = tmp_path / "cost-fork"
    crash_owner(run_dir, "improve", "settle")
    edit_target_outcome(run_dir, "improve",
                        lambda row: row.update(token_usage={"total_tokens": 999}))
    with pytest.raises(RuntimeError, match="settlement differs from native outcome cost"):
        recovered_framework(run_dir, "improve").evolve(TASK)


def test_duplicate_terminal_outcome_is_refused(tmp_path):
    run_dir = tmp_path / "duplicate-outcome"
    crash_owner(run_dir, "improve", "outcome")
    store = AppendOnlyStore(run_dir / "x1.jsonl")
    outcome = [row["payload"] for row in store.read("m0_evaluation_outcome")
               if row["payload"].get("operator") == "improve"][0]
    store.append("m0_evaluation_outcome", outcome)
    with pytest.raises(RuntimeError, match="no unique terminal outcome"):
        recovered_framework(run_dir, "improve").evolve(TASK)


def test_settled_failure_evidence_detail_must_match_outcome(tmp_path):
    run_dir = tmp_path / "failure-evidence-fork"
    crash_owner(run_dir, "improve", "failure_evidence")
    path = run_dir / "x1.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    matches = [row for row in rows if row["kind"] == "executor_evidence"
               and (row["payload"].get("evidence") or {}).get("candidate_id")
               == proposal_id(run_dir / "failure-id", "improve")]
    assert len(matches) == 1
    matches[0]["payload"]["detail"] = "forged failure detail"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    with pytest.raises(RuntimeError, match="executor failure evidence mismatch"):
        recovered_framework(run_dir, "improve").evolve(TASK)


def test_completed_resume_is_noop_and_fresh_replay_executes_normally(tmp_path):
    expected, run_dir = reference_run(tmp_path, "control")
    store = AppendOnlyStore(run_dir / "x1.jsonl")
    before = (len(list(store.read("m0_evaluation_outcome"))),
              len(list(store.read("m0_recovery_adopted"))),
              len(list(store.read("baseline"))))
    resumed = recovered_framework(run_dir, "control")
    actual = resumed.evolve(TASK)
    after = (len(list(store.read("m0_evaluation_outcome"))),
             len(list(store.read("m0_recovery_adopted"))),
             len(list(store.read("baseline"))))
    assert after == before == (3, 0, 1)
    for key in COMPARE:
        assert actual[key] == expected[key]


if __name__ == "__main__" and len(sys.argv) == 5 and sys.argv[1] == "--owner":
    owner_main(Path(sys.argv[2]), sys.argv[3], sys.argv[4])
