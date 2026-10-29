"""v36 real SIGKILL recovery for completed external batch plus same-cycle control."""
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from core.loop import Framework, LoopConfig
from core.x1.checkpoint import certified_snapshot_ref
from core.x1.store import AppendOnlyStore
from examples.toy_gepa import MockLLM
from test_external_evaluator import TASK, evaluator, workspace
from test_external_recovery import COMPARE, ForbiddenLLM

PROJECT = Path(__file__).resolve().parents[1]
CRASH_POINTS = ("settle", "baseline", "failure_evidence")


def config(resume=False):
    return LoopConfig(max_generations=1, baseline_every=1, batch_size=2, max_inflight=2,
                      checkpoint_enabled=True, resume_from_checkpoint=resume)


def proposal_id(run_dir, slot):
    probe = Framework(MockLLM(), None, config(), str(run_dir))
    return probe._proposal_id(TASK, slot)


def owner_main(run_dir, root, script, crash_point):
    control_id = proposal_id(run_dir / "ids", "control:1")
    original_append = AppendOnlyStore.append

    def append_with_crash(self, kind, payload):
        original_append(self, kind, payload)
        data = payload if isinstance(payload, dict) else {}
        crash = False
        if crash_point == "settle":
            crash = kind == "ledger" and data.get("entry_kind") == "settle" \
                and data.get("account") == "control"
        elif crash_point == "baseline":
            crash = kind == "baseline" and data.get("candidate_id") == control_id
        elif crash_point == "failure_evidence":
            crash = kind == "executor_evidence" \
                and (data.get("evidence") or {}).get("candidate_id") == control_id
        if crash:
            os.kill(os.getpid(), signal.SIGKILL)

    AppendOnlyStore.append = append_with_crash
    store = AppendOnlyStore(run_dir / "x1.jsonl")
    mode = "fail_control" if crash_point == "failure_evidence" else (
        "delayed" if crash_point == "pre_settlement" else "ok")
    external = evaluator(root, script, store, mode, control_id)
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
    stdout, stderr = owner.communicate(timeout=25)
    assert owner.returncode == -signal.SIGKILL, (stdout, stderr)


def kill_after_control_started(owner, store, run_dir):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        started = [row["payload"] for row in store.read("executor_process_started")
                   if (row["payload"].get("evaluation_context") or {}).get(
                       "operator") == "iid_rs"]
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
    raise AssertionError("owner did not start external batch/control evaluation")


def recovered_framework(run_dir, root, script, mode="ok", control_id="unused"):
    store = AppendOnlyStore(run_dir / "x1.jsonl")
    external = evaluator(root, script, store, mode, control_id)
    return Framework(ForbiddenLLM(), external, config(resume=True), str(run_dir))


def reference_run(tmp_path, name, failing=False):
    root, script = workspace(tmp_path, f"{name}-workspace")
    run_dir = tmp_path / name
    store = AppendOnlyStore(run_dir / "x1.jsonl")
    control_id = proposal_id(run_dir / "reference-id", "control:1")
    external = evaluator(root, script, store, "fail_control" if failing else "ok", control_id)
    framework = Framework(MockLLM(), external, config(), str(run_dir))
    return framework.evolve(TASK), run_dir


def assert_combined_history(store, candidate_id, settled_reused, failed=False):
    assert len(list(store.read("executor_process_started"))) == 4
    assert len(list(store.read("external_evaluator_outcome"))) == 4
    batch_adoptions = list(store.read("m0_batch_recovery_adopted"))
    assert len(batch_adoptions) == 1
    assert batch_adoptions[0]["payload"]["process_count"] == 2
    assert batch_adoptions[0]["payload"]["reexecuted"] is False
    control_adoptions = [row["payload"] for row in store.read("m0_recovery_adopted")
                         if row["payload"]["candidate_id"] == candidate_id]
    assert len(control_adoptions) == 1
    assert control_adoptions[0]["settlement_reused"] is settled_reused
    assert control_adoptions[0]["reexecuted"] is False
    assert len([row for row in store.read("ledger")
                if row["payload"].get("account") == "control"
                and row["payload"].get("entry_kind") == "settle"]) == 1
    assert len([row for row in store.read("baseline")
                if row["payload"].get("candidate_id") == candidate_id]) == (0 if failed else 1)
    assert len(list(store.read("state_mutation"))) == 15
    assert len(list(store.read("batch_cycle_completed"))) == 1
    assert not list(store.read("state_mutation_rejected"))


def test_real_batch_control_pre_settlement_crash_adopts_without_reexecution(tmp_path):
    expected, reference_dir = reference_run(tmp_path, "reference-pre-settlement")
    root, script = workspace(tmp_path, "pre-settlement-workspace")
    run_dir = tmp_path / "recovered-pre-settlement"
    store = AppendOnlyStore(run_dir / "x1.jsonl")
    owner = start_owner(run_dir, root, script)
    started = kill_after_control_started(owner, store, run_dir)
    candidate_id = started["evaluation_context"]["proposal"]["proposal_id"]
    before_checkpoint = (run_dir / "checkpoint.json").read_bytes()

    resumed = recovered_framework(run_dir, root, script)
    actual = resumed.evolve(TASK)
    for key in COMPARE:
        assert actual[key] == expected[key], key
    assert actual["resumed"] is True and actual["completed"] is True
    assert_combined_history(store, candidate_id, settled_reused=False)
    assert resumed.inspect()["governance_pass"] is True
    assert resumed.inspect()["formal_governance_pass"] is True
    assert (run_dir / "checkpoint.json").read_bytes() != before_checkpoint
    assert certified_snapshot_ref(reference_dir / "checkpoint.json") == \
        certified_snapshot_ref(run_dir / "checkpoint.json")
    resumed.llm = MockLLM()
    replayed = resumed.replay()
    assert resumed.inspect()["replay_certified"] is True
    for key in COMPARE:
        assert replayed[key] == expected[key], key


@pytest.mark.parametrize("crash_point", CRASH_POINTS)
def test_real_batch_control_post_settlement_crashes_resume_exactly_once(tmp_path, crash_point):
    failed = crash_point == "failure_evidence"
    expected, reference_dir = reference_run(
        tmp_path, f"reference-{crash_point}", failing=failed)
    root, script = workspace(tmp_path, f"crash-{crash_point}-workspace")
    run_dir = tmp_path / f"recovered-{crash_point}"
    crash_owner(run_dir, root, script, crash_point)
    control_id = proposal_id(run_dir / "expected-id", "control:1")
    resumed = recovered_framework(run_dir, root, script, "fail_control" if failed else "ok",
                                  control_id)
    actual = resumed.evolve(TASK)
    for key in COMPARE:
        assert actual[key] == expected[key], key
    assert_combined_history(resumed.store, control_id, settled_reused=True, failed=failed)
    assert resumed.inspect()["governance_pass"] is True
    assert resumed.inspect()["formal_governance_pass"] is (not failed)
    assert certified_snapshot_ref(reference_dir / "checkpoint.json") == \
        certified_snapshot_ref(run_dir / "checkpoint.json")
    if crash_point == "baseline":
        resumed.llm = MockLLM()
        replayed = resumed.replay()
        assert resumed.inspect()["replay_certified"] is True
        for key in COMPARE:
            assert replayed[key] == expected[key], key


def test_batch_control_baseline_mismatch_fails_before_control_adoption(tmp_path):
    root, script = workspace(tmp_path, "baseline-fork-workspace")
    run_dir = tmp_path / "baseline-fork"
    crash_owner(run_dir, root, script, "baseline")
    evidence = run_dir / "x1.jsonl"
    evidence.write_text(evidence.read_text().replace(
        '"score": 0.3333333333333333', '"score": 0.5'))
    resumed = recovered_framework(run_dir, root, script)
    with pytest.raises(RuntimeError, match="baseline evidence mismatch"):
        resumed.evolve(TASK)
    control_id = proposal_id(run_dir / "baseline-fork-id", "control:1")
    assert not [row for row in resumed.store.read("m0_recovery_adopted")
                if row["payload"].get("candidate_id") == control_id]
    assert len(list(resumed.store.read("m0_batch_recovery_adopted"))) == 1
    assert len(list(resumed.store.read("baseline"))) == 1


def test_batch_control_wrong_candidate_lineage_is_refused(tmp_path):
    root, script = workspace(tmp_path, "wrong-lineage-workspace")
    run_dir = tmp_path / "wrong-lineage"
    crash_owner(run_dir, root, script, "settle")
    control_id = proposal_id(run_dir / "lineage-id", "control:1")
    evidence = run_dir / "x1.jsonl"
    evidence.write_text(evidence.read_text().replace(control_id, "forged-control"))
    resumed = recovered_framework(run_dir, root, script)
    with pytest.raises(RuntimeError, match="candidate differs from checkpoint lineage"):
        resumed.evolve(TASK)
    assert not list(resumed.store.read("m0_recovery_adopted"))
    assert not list(resumed.store.read("m0_batch_recovery_adopted"))


def test_completed_batch_control_resume_does_not_readopt_or_reexecute(tmp_path):
    _, run_dir = reference_run(tmp_path, "completed-control")
    root = tmp_path / "completed-control-workspace"
    script = root / "evaluator.py"
    store = AppendOnlyStore(run_dir / "x1.jsonl")
    before = (len(list(store.read("executor_process_started"))),
              len(list(store.read("m0_recovery_adopted"))),
              len(list(store.read("m0_batch_recovery_adopted"))),
              len(list(store.read("baseline"))))
    resumed = recovered_framework(run_dir, root, script)
    resumed.evolve(TASK)
    after = (len(list(store.read("executor_process_started"))),
             len(list(store.read("m0_recovery_adopted"))),
             len(list(store.read("m0_batch_recovery_adopted"))),
             len(list(store.read("baseline"))))
    assert after == before == (4, 0, 0, 1)


if __name__ == "__main__" and len(sys.argv) == 6 and sys.argv[1] == "--owner":
    owner_main(Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4]), sys.argv[5])
