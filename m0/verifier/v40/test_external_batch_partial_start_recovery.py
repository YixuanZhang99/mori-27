"""v37 real SIGKILL recovery for fully proposed, partially started external cohorts."""
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
from core.x1.checkpoint import certified_snapshot_ref
from core.x1.store import AppendOnlyStore
from examples.toy_gepa import MockLLM
from test_external_batch_recovery import (config, kill_at_process_count,
                                         recovered_framework, start_owner)
from test_external_evaluator import TASK, evaluator, workspace
from test_external_recovery import COMPARE, ForbiddenLLM

PROJECT = Path(__file__).resolve().parents[1]


def reference_run(tmp_path, name):
    root, script = workspace(tmp_path, f"{name}-workspace")
    run_dir = tmp_path / name
    store = AppendOnlyStore(run_dir / "x1.jsonl")
    framework = Framework(MockLLM(), evaluator(root, script, store), config(), str(run_dir))
    return framework.evolve(TASK), run_dir


def assert_original_cohort_history(store, adopted, continued):
    assert len(list(store.read("m0_evaluation_started"))) == 3
    assert len(list(store.read("executor_process_started"))) == 3
    assert len(list(store.read("external_evaluator_outcome"))) == 3
    assert len(list(store.read("batch_execution_settled"))) == 2
    assert len(list(store.read("state_mutation"))) == 15
    adoptions = list(store.read("m0_batch_recovery_adopted"))
    assert len(adoptions) == 1
    payload = adoptions[0]["payload"]
    assert payload["process_count"] == 2
    assert payload["adopted_process_count"] == adopted
    assert payload["continued_process_count"] == continued
    assert len(payload["continued_candidate_ids"]) == continued
    assert payload["reexecuted"] is False


def test_real_partially_started_cohort_continues_only_missing_original_evaluation(tmp_path):
    expected, reference_dir = reference_run(tmp_path, "reference-partial")
    root, script = workspace(tmp_path, "partial-workspace")
    run_dir = tmp_path / "recovered-partial"
    store = AppendOnlyStore(run_dir / "x1.jsonl")
    owner = start_owner(run_dir, root, script)
    kill_at_process_count(owner, store, 2)  # genesis plus one of two prepared candidates
    assert len(list(store.read("m0_evaluation_started"))) == 3
    assert not list(store.read("batch_execution_settled"))

    resumed = recovered_framework(run_dir, root, script)
    actual = resumed.evolve(TASK)
    for key in COMPARE:
        assert actual[key] == expected[key], key
    assert actual["resumed"] is True and actual["completed"] is True
    assert_original_cohort_history(store, adopted=1, continued=1)
    assert resumed.inspect()["governance_pass"] is True
    assert certified_snapshot_ref(reference_dir / "checkpoint.json") == \
        certified_snapshot_ref(run_dir / "checkpoint.json")
    resumed.llm = MockLLM()
    replayed = resumed.replay()
    assert resumed.inspect()["replay_certified"] is True
    for key in COMPARE:
        assert replayed[key] == expected[key], key


def proposal_crash_owner(run_dir, root, script, proposal_count):
    env = dict(os.environ)
    env.update(PYTHONPATH=str(PROJECT), PYTHONDONTWRITEBYTECODE="1",
               AR_TEST_PROPOSAL_CRASH=str(proposal_count))
    return subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "--proposal-owner", str(run_dir),
         str(root), str(script)], cwd=PROJECT, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def proposal_owner_main(run_dir, root, script):
    original_append = AppendOnlyStore.append
    proposal_count = int(os.environ["AR_TEST_PROPOSAL_CRASH"])
    seen = 0

    def append_with_crash(self, kind, payload):
        nonlocal seen
        original_append(self, kind, payload)
        data = payload if isinstance(payload, dict) else {}
        if kind == "m0_evaluation_started" and data.get("generation") == 1 \
                and data.get("operator") == "improve":
            seen += 1
            if seen == proposal_count:
                os.kill(os.getpid(), signal.SIGKILL)

    AppendOnlyStore.append = append_with_crash
    store = AppendOnlyStore(run_dir / "x1.jsonl")
    Framework(MockLLM(), evaluator(root, script, store), config(), str(run_dir)).evolve(TASK)


def crash_after_proposals(run_dir, root, script, count):
    owner = proposal_crash_owner(run_dir, root, script, count)
    stdout, stderr = owner.communicate(timeout=25)
    assert owner.returncode == -signal.SIGKILL, (stdout, stderr)


def test_real_fully_proposed_zero_started_cohort_continues_original_evaluations(tmp_path):
    expected, reference_dir = reference_run(tmp_path, "reference-zero")
    root, script = workspace(tmp_path, "zero-workspace")
    run_dir = tmp_path / "recovered-zero"
    store = AppendOnlyStore(run_dir / "x1.jsonl")
    crash_after_proposals(run_dir, root, script, 2)
    assert len(list(store.read("m0_evaluation_started"))) == 3
    assert len(list(store.read("executor_process_started"))) == 1  # genesis only
    assert not list(store.read("batch_execution_settled"))

    resumed = recovered_framework(run_dir, root, script)
    actual = resumed.evolve(TASK)
    for key in COMPARE:
        assert actual[key] == expected[key], key
    assert_original_cohort_history(store, adopted=0, continued=2)
    assert resumed.inspect()["governance_pass"] is True
    assert certified_snapshot_ref(reference_dir / "checkpoint.json") == \
        certified_snapshot_ref(run_dir / "checkpoint.json")


def test_incomplete_proposals_fail_closed_without_reproposal_or_execution(tmp_path):
    root, script = workspace(tmp_path, "incomplete-workspace")
    run_dir = tmp_path / "incomplete"
    store = AppendOnlyStore(run_dir / "x1.jsonl")
    crash_after_proposals(run_dir, root, script, 1)
    before = len(list(store.read("executor_process_started")))
    resumed = recovered_framework(run_dir, root, script)
    with pytest.raises((RuntimeError, ValueError),
                       match="post-checkpoint ledger|durable proposals"):
        resumed.evolve(TASK)
    assert len(list(store.read("executor_process_started"))) == before
    assert not list(store.read("m0_batch_recovery_adopted"))
    assert not list(store.read("batch_admission"))


def test_partial_start_with_settlement_fails_before_continuing(tmp_path):
    root, script = workspace(tmp_path, "settled-partial-workspace")
    run_dir = tmp_path / "settled-partial"
    store = AppendOnlyStore(run_dir / "x1.jsonl")
    owner = start_owner(run_dir, root, script)
    kill_at_process_count(owner, store, 2)
    cohort = list(store.read("batch_cycle_started"))[0]["payload"]
    store.append("batch_execution_settled", {
        "cohort_id": cohort["cohort_id"], "candidate_id": cohort["candidate_ids"][0],
        "intent_id": cohort["intents"][0]["intent_id"], "evidence": {}})
    before = len(list(store.read("executor_process_started")))
    resumed = recovered_framework(run_dir, root, script)
    with pytest.raises(RuntimeError, match="partially started cohort cannot have batch settlement"):
        resumed.evolve(TASK)
    assert len(list(store.read("executor_process_started"))) == before
    assert not list(store.read("m0_batch_recovery_adopted"))


def test_partial_start_context_fork_fails_before_continuing(tmp_path):
    root, script = workspace(tmp_path, "context-fork-workspace")
    run_dir = tmp_path / "context-fork"
    store = AppendOnlyStore(run_dir / "x1.jsonl")
    owner = start_owner(run_dir, root, script)
    kill_at_process_count(owner, store, 2)
    started = [row["payload"] for row in store.read("m0_evaluation_started")
               if row["payload"].get("generation") == 1]
    active_proposals = {row["payload"]["evaluation_context"]["proposal"]["proposal_id"]
                        for row in store.read("executor_process_started")
                        if row["payload"].get("evaluation_context", {}).get("generation") == 1}
    targets = [row for row in started
               if row["proposal"]["proposal_id"] in active_proposals]
    assert len(targets) == 1
    target = targets[0]
    evidence = run_dir / "x1.jsonl"
    records = [json.loads(line) for line in evidence.read_text().splitlines()]
    matches = [index for index, row in enumerate(records)
               if row["kind"] == "m0_evaluation_started"
               and row["payload"].get("generation") == 1
               and row["payload"].get("proposal", {}).get("proposal_id")
               == target["proposal"]["proposal_id"]]
    assert len(matches) == 1
    records[matches[0]]["payload"]["head_sha"] = "forged-head"
    evidence.write_text("".join(json.dumps(row) + "\n" for row in records))
    before = len(list(store.read("executor_process_started")))
    resumed = recovered_framework(run_dir, root, script)
    with pytest.raises(RuntimeError, match="recovery context mismatch"):
        resumed.evolve(TASK)
    assert len(list(store.read("executor_process_started"))) == before
    assert not list(store.read("m0_batch_recovery_adopted"))


def test_completed_partial_start_resume_is_a_noop(tmp_path):
    root, script = workspace(tmp_path, "completed-workspace")
    run_dir = tmp_path / "completed"
    store = AppendOnlyStore(run_dir / "x1.jsonl")
    owner = start_owner(run_dir, root, script)
    kill_at_process_count(owner, store, 2)
    resumed = recovered_framework(run_dir, root, script)
    resumed.evolve(TASK)
    before = [(kind, len(list(store.read(kind)))) for kind in
              ("executor_process_started", "external_evaluator_outcome",
               "batch_execution_settled", "m0_batch_recovery_adopted",
               "state_mutation", "admission_receipt")]
    completed = recovered_framework(run_dir, root, script)
    result = completed.evolve(TASK)
    after = [(kind, len(list(store.read(kind)))) for kind, _ in before]
    assert result["resumed"] is True and result["completed"] is True
    assert after == before


if __name__ == "__main__" and len(sys.argv) == 5 and sys.argv[1] == "--proposal-owner":
    proposal_owner_main(Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4]))
