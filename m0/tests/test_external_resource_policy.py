"""v39 real POSIX resource limits for external M0 evaluator processes."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from core.executor import EvalStatus, ExternalEvaluatorError, ResourcePolicy
from core.x1.store import AppendOnlyStore
from test_external_evaluator import evaluator, workspace

PROJECT = Path(__file__).resolve().parents[1]


def uid_thread_count():
    output = subprocess.check_output(["ps", "-L", "-u", str(os.getuid()), "--no-headers"],
                                     text=True)
    return len(output.splitlines())


@pytest.mark.parametrize("probe,policy", [
    ("memory", ResourcePolicy(memory_bytes=96 * 1024 * 1024)),
    ("file", ResourcePolicy(file_bytes=1024)),
    ("process", None),
])
def test_kernel_enforces_real_limits_and_fork_inherits_policy(tmp_path, probe, policy):
    if probe == "process":
        # RLIMIT_NPROC is UID-wide, not a per-tree count; leave headroom for bwrap.
        policy = ResourcePolicy(process_count=uid_thread_count() + 16)
    root, script = workspace(tmp_path, f"resource-{probe}")
    store = AppendOnlyStore(tmp_path / f"run-{probe}/x1.jsonl")
    external = evaluator(root, script, store, "resource", probe,
                         resource_policy=policy, time_limit=10)
    result = external("candidate", "head1234", "prompt")
    assert result.public["probe"] == probe
    assert result.public["limited"] is True, result.public
    assert external.resource_limits == policy.as_dict()
    started = list(store.read("executor_process_started"))
    assert len(started) == 1
    payload = started[0]["payload"]
    assert payload["sandbox_policy"] == "BubblewrapSandbox"
    assert payload["resource_policy"] == policy.as_dict()
    spec = json.loads(Path(payload["spec_path"]).read_text())
    assert spec["resource_limits"] == policy.as_dict()

    replay_store = AppendOnlyStore(tmp_path / f"replay-{probe}/x1.jsonl")
    clone = external.fork(tmp_path / f"replay-work-{probe}", replay_store)
    replayed = clone("replayed", "head5678", "prompt")
    assert replayed.public["limited"] is True
    assert clone.resource_policy == policy
    replay_payload = list(replay_store.read("executor_process_started"))[0]["payload"]
    assert replay_payload["resource_policy"] == policy.as_dict()
    assert replay_payload["execution_id"] != payload["execution_id"]
    assert len(list(store.read("external_evaluator_outcome"))) == 1
    assert len(list(replay_store.read("external_evaluator_outcome"))) == 1


def test_unstartable_process_limit_is_structured_failure_not_fail_open(tmp_path):
    root, script = workspace(tmp_path, "resource-start-failure")
    store = AppendOnlyStore(tmp_path / "start-failure-run/x1.jsonl")
    policy = ResourcePolicy(process_count=1)
    external = evaluator(root, script, store, resource_policy=policy)
    with pytest.raises(ExternalEvaluatorError) as caught:
        external("candidate", "head1234", "prompt")
    assert caught.value.status is EvalStatus.FAILED_TO_RUN
    outcomes = list(store.read("external_evaluator_outcome"))
    assert len(outcomes) == 1
    assert outcomes[0]["payload"]["status"] == "failed_to_run"
    payload = list(store.read("executor_process_started"))[0]["payload"]
    assert payload["resource_policy"] == {"process_count": 1}


@pytest.mark.parametrize("kwargs", [
    {"memory_bytes": 0}, {"file_bytes": -1}, {"process_count": True},
    {"memory_bytes": 1.5},
])
def test_invalid_resource_limits_fail_before_any_process(tmp_path, kwargs):
    root, script = workspace(tmp_path, "invalid-resource")
    store = AppendOnlyStore(tmp_path / "invalid-run/x1.jsonl")
    with pytest.raises(ValueError, match="positive integer"):
        ResourcePolicy(**kwargs)
    with pytest.raises(TypeError, match="ResourcePolicy"):
        evaluator(root, script, store, resource_policy={})
    assert list(store.read("executor_process_started")) == []
    assert list(store.read("external_evaluator_outcome")) == []


def test_unconfigured_policy_is_explicitly_empty(tmp_path):
    root, script = workspace(tmp_path, "unconfigured-resource")
    store = AppendOnlyStore(tmp_path / "unconfigured-run/x1.jsonl")
    external = evaluator(root, script, store)
    external("candidate", "head1234", "prompt")
    payload = list(store.read("executor_process_started"))[0]["payload"]
    assert payload["resource_policy"] == {}
    spec = json.loads(Path(payload["spec_path"]).read_text())
    assert spec["resource_limits"] == {}


def test_resource_policy_owner_crash_adopts_original_outcome(tmp_path):
    root, script = workspace(tmp_path, "resource-recovery")
    store_path = tmp_path / "recovery-run/x1.jsonl"
    policy = ResourcePolicy(memory_bytes=128 * 1024 * 1024)
    owner = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "--resource-owner",
         str(root), str(script), str(store_path)], cwd=PROJECT,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    store = AppendOnlyStore(store_path)
    deadline = time.monotonic() + 10
    started = []
    while not started and time.monotonic() < deadline:
        started = list(store.read("executor_process_started"))
        if owner.poll() is not None:
            stdout, stderr = owner.communicate()
            raise AssertionError(f"owner exited {owner.returncode}: {stdout}{stderr}")
        time.sleep(0.02)
    assert len(started) == 1
    owner.kill()
    owner.wait(timeout=5)
    assert owner.returncode == -9

    recovered = evaluator(root, script, store, "delayed", resource_policy=policy,
                          time_limit=10)
    outcomes = recovered.recover_inflight(wait=True)
    assert len(outcomes) == 1
    assert outcomes[0]["error"] is None
    assert outcomes[0]["result"].combined_score == pytest.approx(1 / 3)
    assert len(list(store.read("executor_process_started"))) == 1
    assert len(list(store.read("external_evaluator_outcome"))) == 1
    payload = list(store.read("executor_process_started"))[0]["payload"]
    assert payload["resource_policy"] == policy.as_dict()


def owner_main(root, script, store_path):
    store = AppendOnlyStore(store_path)
    external = evaluator(root, script, store, "delayed",
                         resource_policy=ResourcePolicy(memory_bytes=128 * 1024 * 1024),
                         time_limit=10)
    external("resource-recovery", "head1234", "prompt")


if __name__ == "__main__" and len(sys.argv) == 5 and sys.argv[1] == "--resource-owner":
    owner_main(Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4]))
