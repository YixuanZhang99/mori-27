"""v34 real SIGKILL recovery for a fully started, pre-settlement external M0 cohort."""
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


def config(resume=False):
    return LoopConfig(max_generations=1, baseline_every=5, batch_size=2, max_inflight=2,
                      checkpoint_enabled=True, resume_from_checkpoint=resume)


def owner_main(run_dir, root, script, crash_point):
    original_append = AppendOnlyStore.append
    settled = 0

    def append_with_crash(self, kind, payload):
        nonlocal settled
        original_append(self, kind, payload)
        data = payload if isinstance(payload, dict) else {}
        if kind == "ledger" and data.get("entry_kind") == "settle" \
                and data.get("account") == "exploit":
            settled += 1
        if crash_point == "settle" and settled == 1:
            os.kill(os.getpid(), signal.SIGKILL)

    AppendOnlyStore.append = append_with_crash
    store = AppendOnlyStore(run_dir / "x1.jsonl")
    mode = "ok" if crash_point == "settle" else "delayed"
    Framework(MockLLM(), evaluator(root, script, store, mode), config(), str(run_dir)).evolve(TASK)


def start_owner(run_dir, root, script, crash_point="running"):
    env = dict(os.environ)
    env.update(PYTHONPATH=str(PROJECT), PYTHONDONTWRITEBYTECODE="1")
    return subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "--owner", str(run_dir),
         str(root), str(script), crash_point], cwd=PROJECT, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def kill_at_process_count(owner, store, count):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        started = list(store.read("executor_process_started"))
        if len(started) >= count:
            owner.kill()
            owner.wait(timeout=5)
            return started
        if owner.poll() is not None:
            stdout, stderr = owner.communicate()
            raise AssertionError(f"owner exited early: {stdout}\n{stderr}")
        time.sleep(0.02)
    owner.kill()
    owner.wait(timeout=5)
    raise AssertionError(f"owner did not start {count} external processes")


def recovered_framework(run_dir, root, script):
    store = AppendOnlyStore(run_dir / "x1.jsonl")
    return Framework(ForbiddenLLM(), evaluator(root, script, store),
                     config(resume=True), str(run_dir))


def test_real_fully_started_batch_crash_recovers_without_reproposal_or_reexecution(tmp_path):
    reference_root, reference_script = workspace(tmp_path, "reference-workspace")
    reference_dir = tmp_path / "reference"
    reference_store = AppendOnlyStore(reference_dir / "x1.jsonl")
    reference = Framework(MockLLM(), evaluator(reference_root, reference_script,
                                               reference_store), config(), str(reference_dir))
    expected = reference.evolve(TASK)

    root, script = workspace(tmp_path, "crash-workspace")
    run_dir = tmp_path / "recovered"
    store = AppendOnlyStore(run_dir / "x1.jsonl")
    owner = start_owner(run_dir, root, script)
    kill_at_process_count(owner, store, 3)  # genesis plus both frozen cohort candidates
    assert len(list(store.read("batch_execution_settled"))) == 0

    resumed = recovered_framework(run_dir, root, script)
    actual = resumed.evolve(TASK)
    for key in COMPARE:
        assert actual[key] == expected[key], key
    assert actual["resumed"] is True and actual["completed"] is True
    assert len(list(store.read("executor_process_started"))) == 3
    assert len(list(store.read("external_evaluator_outcome"))) == 3
    settled = list(store.read("batch_execution_settled"))
    assert len(settled) == 2 and all(row["payload"]["recovered"] for row in settled)
    assert len(list(store.read("state_mutation"))) == 15
    assert len(list(store.read("gate_evidence"))) == 3
    assert len(list(store.read("admission_receipt"))) == 3
    adopted = list(store.read("m0_batch_recovery_adopted"))
    assert len(adopted) == 1 and adopted[0]["payload"]["process_count"] == 2
    assert adopted[0]["payload"]["reexecuted"] is False
    assert resumed.inspect()["governance_pass"] is True
    assert certified_snapshot_ref(reference_dir / "checkpoint.json") == \
        certified_snapshot_ref(run_dir / "checkpoint.json")
    resumed.llm = MockLLM()
    replayed = resumed.replay()
    assert resumed.inspect()["replay_certified"] is True
    for key in COMPARE:
        assert replayed[key] == expected[key], key


def test_partially_started_cohort_fails_closed_instead_of_reproposing(tmp_path):
    root, script = workspace(tmp_path, "partial-workspace")
    run_dir = tmp_path / "partial"
    store = AppendOnlyStore(run_dir / "x1.jsonl")
    owner = start_owner(run_dir, root, script)
    kill_at_process_count(owner, store, 2)  # genesis plus only the first cohort candidate
    resumed = recovered_framework(run_dir, root, script)
    with pytest.raises((RuntimeError, ValueError),
                       match="settlement requires explicit recovery|process journal"):
        resumed.evolve(TASK)
    assert len(list(store.read("executor_process_started"))) == 2
    assert not list(store.read("m0_batch_recovery_adopted"))
    assert not list(store.read("batch_admission"))


def test_post_settlement_cohort_is_outside_v34_and_fails_closed(tmp_path):
    root, script = workspace(tmp_path, "settled-workspace")
    run_dir = tmp_path / "settled"
    store = AppendOnlyStore(run_dir / "x1.jsonl")
    owner = start_owner(run_dir, root, script, "settle")
    stdout, stderr = owner.communicate(timeout=20)
    assert owner.returncode == -signal.SIGKILL, (stdout, stderr)
    resumed = recovered_framework(run_dir, root, script)
    with pytest.raises(RuntimeError, match="only pre-settlement external M0 cohorts"):
        resumed.evolve(TASK)
    assert len(list(store.read("executor_process_started"))) == 3
    assert not list(store.read("m0_batch_recovery_adopted"))
    assert not list(store.read("batch_admission"))


if __name__ == "__main__" and len(sys.argv) == 6 and sys.argv[1] == "--owner":
    owner_main(Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4]), sys.argv[5])
