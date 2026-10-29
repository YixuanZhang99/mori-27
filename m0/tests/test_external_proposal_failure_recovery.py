"""v43 owner-crash recovery with a durable failed proposal and a successful sibling."""
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
from test_external_batch_recovery import config
from test_external_evaluator import TASK, evaluator, workspace
from test_external_proposal_recovery import proposer, proposer_workspace
from test_external_recovery import COMPARE, ForbiddenLLM

PROJECT = Path(__file__).resolve().parents[1]


def reference_run(tmp_path):
    eval_root, eval_script = workspace(tmp_path, "failure-reference-evaluator")
    prop_root, prop_script, count = proposer_workspace(tmp_path, "failure-reference-proposer")
    run_dir = tmp_path / "failure-reference"
    store = AppendOnlyStore(run_dir / "x1.jsonl")
    llm = proposer(prop_root, prop_script, count, store, MockLLM(), "invalid_once")
    result = Framework(llm, evaluator(eval_root, eval_script, store),
                       config(), str(run_dir)).evolve(TASK)
    return result, run_dir


def start_owner(run_dir, eval_root, eval_script, prop_root, prop_script, count,
                crash_point):
    env = dict(os.environ)
    env.update(PYTHONPATH=str(PROJECT), PYTHONDONTWRITEBYTECODE="1",
               AR_FAILURE_CRASH=crash_point)
    return subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "--owner", str(run_dir),
         str(eval_root), str(eval_script), str(prop_root), str(prop_script), str(count)],
        cwd=PROJECT, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def owner_main(run_dir, eval_root, eval_script, prop_root, prop_script, count):
    original_append = AppendOnlyStore.append
    crash_point = os.environ["AR_FAILURE_CRASH"]

    def append_with_crash(self, kind, payload):
        original_append(self, kind, payload)
        process_crash = crash_point == "process" \
            and kind == "executor_process_started" \
            and payload.get("process_kind") == "m0_external_proposer"
        outcome_crash = crash_point == "outcome" \
            and kind == "external_proposer_outcome" and payload.get("status") != "ok"
        if process_crash or outcome_crash:
            os.kill(os.getpid(), signal.SIGKILL)

    AppendOnlyStore.append = append_with_crash
    store = AppendOnlyStore(run_dir / "x1.jsonl")
    llm = proposer(prop_root, prop_script, count, store, MockLLM(), "invalid_once")
    Framework(llm, evaluator(eval_root, eval_script, store),
              config(), str(run_dir)).evolve(TASK)


@pytest.mark.parametrize("crash_point", ["process", "outcome"])
def test_failed_active_proposal_recovers_without_retry_or_fake_evaluator_process(
        tmp_path, crash_point):
    expected, reference_dir = reference_run(tmp_path)
    eval_root, eval_script = workspace(tmp_path, "failure-crash-evaluator")
    prop_root, prop_script, count = proposer_workspace(tmp_path, "failure-crash-proposer")
    run_dir = tmp_path / "failure-recovered"
    store = AppendOnlyStore(run_dir / "x1.jsonl")
    owner = start_owner(run_dir, eval_root, eval_script,
                        prop_root, prop_script, count, crash_point)
    stdout, stderr = owner.communicate(timeout=25)
    assert owner.returncode == -signal.SIGKILL, (stdout, stderr)
    cohort = list(store.read("batch_cycle_started"))[0]["payload"]
    assert len(list(store.read("m0_proposal_started"))) == 1
    assert not [row for row in store.read("m0_evaluation_started")
                if row["payload"].get("cohort_id") == cohort["cohort_id"]]
    initial_outcomes = list(store.read("external_proposer_outcome"))
    assert len(initial_outcomes) == (1 if crash_point == "outcome" else 0)
    if initial_outcomes:
        assert initial_outcomes[0]["payload"]["status"] == "invalid"

    llm = proposer(prop_root, prop_script, count, store, ForbiddenLLM(), "invalid_once")
    resumed = Framework(llm, evaluator(eval_root, eval_script, store),
                        config(resume=True), str(run_dir))
    actual = resumed.evolve(TASK)
    for key in COMPARE:
        assert actual[key] == expected[key], key
    assert actual["completed"] is True and actual["resumed"] is True
    outcomes = [row["payload"] for row in store.read("external_proposer_outcome")]
    assert [outcome["status"] for outcome in outcomes] == ["invalid", "ok"]
    assert count.read_text().splitlines() == ["call", "call"]
    proposer_processes = [row["payload"] for row in store.read("executor_process_started")
                          if row["payload"].get("process_kind") == "m0_external_proposer"]
    evaluator_processes = [row["payload"] for row in store.read("executor_process_started")
                           if row["payload"].get("process_kind", "m0_external_evaluator")
                           == "m0_external_evaluator"]
    assert len(proposer_processes) == 2
    assert len(evaluator_processes) == 2  # genesis plus only the successful cohort proposal
    cohort_starts = [row["payload"] for row in store.read("m0_evaluation_started")
                     if row["payload"].get("cohort_id") == cohort["cohort_id"]]
    assert [row["proposal"]["proposal_id"] for row in cohort_starts] == \
        cohort["candidate_ids"][1:]
    evidence = [row["payload"] for row in store.read("executor_evidence")]
    failed = [row for row in evidence
              if row["evidence"]["candidate_id"] == cohort["candidate_ids"][0]]
    assert len(failed) == 1
    assert failed[0]["execution_id"] == proposer_processes[0]["execution_id"]
    assert failed[0]["evidence"]["eval_result"]["status"] == "invalid"
    assert failed[0]["evidence"]["eval_result"]["cost"]["tokens_in"] == 7
    assert len(list(store.read("batch_execution_settled"))) == 2
    report = list(store.read("m0_batch_recovery_adopted"))[0]["payload"]
    assert report["continued_proposal_count"] == (2 if crash_point == "process" else 1)
    assert report["adopted_proposal_count"] == (1 if crash_point == "process" else 0)
    assert report["new_proposal_count"] == 1
    assert report["recovered_proposal_failure_count"] == 1
    assert report["recovered_proposal_failure_ids"] == cohort["candidate_ids"][:1]
    assert report["continued_process_count"] == 1
    assert report["continued_candidate_ids"] == cohort["candidate_ids"][1:]
    assert resumed.inspect()["governance_pass"] is True
    assert certified_snapshot_ref(reference_dir / "checkpoint.json") == \
        certified_snapshot_ref(run_dir / "checkpoint.json")

    counted = ("executor_process_started", "external_proposer_outcome", "executor_evidence",
               "m0_proposal_started", "m0_evaluation_started", "batch_execution_settled")
    before = [(kind, len(list(store.read(kind)))) for kind in counted]
    completed_llm = proposer(prop_root, prop_script, count, store,
                             ForbiddenLLM(), "invalid_once")
    completed = Framework(completed_llm, evaluator(eval_root, eval_script, store),
                          config(resume=True), str(run_dir))
    repeated = completed.evolve(TASK)
    assert repeated["completed"] is True
    assert [(kind, len(list(store.read(kind)))) for kind, _ in before] == before
    assert count.read_text().splitlines() == ["call", "call"]

    # Replay is a fresh execution, so reset only the external call counter; its evidence
    # namespace remains independent and the original run journal is unchanged.
    count.write_text("")
    resumed.llm.fallback_llm = MockLLM()
    replayed = resumed.replay()
    assert resumed.inspect()["replay_certified"] is True
    for key in COMPARE:
        assert replayed[key] == expected[key], key
    assert count.read_text().splitlines() == ["call", "call"]
    assert len([row for row in store.read("executor_process_started")
                if row["payload"].get("process_kind") == "m0_external_proposer"]) == 2


if __name__ == "__main__" and len(sys.argv) == 8 and sys.argv[1] == "--owner":
    owner_main(Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4]),
               Path(sys.argv[5]), Path(sys.argv[6]), Path(sys.argv[7]))
