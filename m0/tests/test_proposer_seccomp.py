"""v57 direct-prctl seccomp for durable ExternalCommandLLM proposal workers."""
import base64
import copy
import hashlib
import json
import platform
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from core.executor.process import ProcessJournal
from core.executor.proposal import ExternalCommandLLM
from core.executor.seccomp import (SECCOMP_DIRECT_PRCTL, SECCOMP_FD_PLACEHOLDER,
                                   build_seccomp_policy)
from core.x1.store import AppendOnlyStore
from examples.toy_gepa import MockLLM
from test_external_proposal_recovery import proposer, proposer_workspace
from test_external_proposer import PROMPT, context

PROJECT = Path(__file__).resolve().parents[1]
REAL_DIRECT = pytest.mark.skipif(
    platform.system() != "Linux" or platform.machine() != "x86_64",
    reason="v57 direct-prctl verification requires Linux x86_64")


def started_record(store):
    records = list(store.read("executor_process_started"))
    assert len(records) == 1
    return records[0]["payload"]


@REAL_DIRECT
def test_default_proposer_eperm_status_audit_and_fork(tmp_path, monkeypatch):
    root, script, count = proposer_workspace(tmp_path, "direct-proposer")
    monkeypatch.setenv("AR_TEST_SECRET", "direct-proposer-secret")
    store = AppendOnlyStore(tmp_path / "original/x1.jsonl")
    llm = proposer(root, script, count, store, MockLLM(), "seccomp", time_limit=10)
    llm.set_operation_context(context())
    probe = json.loads(llm(PROMPT))
    assert probe["returncode"] == -1 and probe["errno"] == 1
    assert probe["status"]["NoNewPrivs"] == 1
    assert probe["status"]["Seccomp"] == 2
    assert probe["status"]["Seccomp_filters"] >= 1
    record = started_record(store)
    assert record["process_kind"] == "m0_external_proposer"
    assert record["seccomp_delivery"] == "direct_prctl"
    assert record["seccomp_policy"]["policy"] == "dangerous-syscall-denylist"
    assert "filter_base64" not in record["seccomp_policy"]
    spec = json.loads(Path(record["spec_path"]).read_text())
    assert spec["seccomp_delivery"] == "direct_prctl"
    assert spec["seccomp_policy"]["filter_base64"]
    assert Path(spec["args"][0]).name != "bwrap"
    assert SECCOMP_FD_PLACEHOLDER not in spec["args"]
    persisted = store.path.read_text() + Path(record["spec_path"]).read_text()
    assert "direct-proposer-secret" not in persisted and "AR_TEST_SECRET" not in persisted

    replay_store = AppendOnlyStore(tmp_path / "replay/x1.jsonl")
    clone = llm.fork(tmp_path / "replay-work", replay_store)
    clone.set_operation_context(context())
    assert json.loads(clone(PROMPT))["errno"] == 1
    replay_record = started_record(replay_store)
    assert replay_record["seccomp_delivery"] == "direct_prctl"
    assert replay_record["seccomp_policy"] == record["seccomp_policy"]
    assert replay_record["execution_id"] != record["execution_id"]
    assert count.read_text().splitlines() == ["call", "call"]


@REAL_DIRECT
def test_only_explicit_proposer_seccomp_disable_omits_policy(tmp_path):
    root, script, count = proposer_workspace(tmp_path, "direct-disabled")
    store = AppendOnlyStore(tmp_path / "run/x1.jsonl")
    llm = proposer(root, script, count, store, MockLLM(), seccomp=False)
    llm.set_operation_context(context())
    assert llm(PROMPT) == "base\nhint_4"
    record = started_record(store)
    assert record["seccomp_policy"] is None and record["seccomp_delivery"] is None
    spec = json.loads(Path(record["spec_path"]).read_text())
    assert spec["seccomp_policy"] is None and spec["seccomp_delivery"] is None

    with pytest.raises(TypeError, match="explicitly boolean"):
        ExternalCommandLLM([sys.executable, "-c", "pass"], tmp_path / "invalid",
                           AppendOnlyStore(tmp_path / "invalid/x1.jsonl"), seccomp="yes")
    assert list(AppendOnlyStore(tmp_path / "invalid/x1.jsonl").read(
        "executor_process_started")) == []


@REAL_DIRECT
def test_direct_delivery_rejects_rehashed_spec_before_target_start(tmp_path):
    root = tmp_path / "wrapper"
    root.mkdir()
    policy = copy.deepcopy(build_seccomp_policy())
    encoded = bytearray(base64.b64decode(policy["filter_base64"]))
    encoded[-1] ^= 1
    policy["filter_base64"] = base64.b64encode(encoded).decode("ascii")
    policy["filter_sha256"] = hashlib.sha256(encoded).hexdigest()
    spec = {
        "args": [sys.executable, "-c", "raise AssertionError('target started')"],
        "cwd": str(root), "time_limit": 10, "resource_limits": {},
        "seccomp_policy": policy, "seccomp_delivery": "direct_prctl",
        "stdout_path": str(root / "stdout.txt"), "stderr_path": str(root / "stderr.txt"),
        "result_path": str(root / "result.json"), "target_path": str(root / "target.json")}
    spec_path = root / "spec.json"
    spec_path.write_text(json.dumps(spec))
    completed = subprocess.run(
        [sys.executable, str(PROJECT / "core/executor/process_wrapper.py"), str(spec_path)],
        cwd=root, capture_output=True, text=True, timeout=10)
    assert completed.returncode == 127
    result = json.loads((root / "result.json").read_text())
    assert result["returncode"] == 127
    assert "canonical versioned denylist" in result["wrapper_error"]
    assert not (root / "target.json").exists()


def test_invalid_delivery_fails_before_process_launch(tmp_path):
    store = AppendOnlyStore(tmp_path / "evidence.jsonl")
    journal = ProcessJournal(store)
    with pytest.raises(ValueError, match="explicit bwrap_memfd or direct_prctl"):
        journal.launch([sys.executable, "-c", "pass"], tmp_path, {}, 10,
                       {"candidate_id": "c", "attempt": 1},
                       seccomp_policy=build_seccomp_policy("x86_64"),
                       seccomp_delivery="attacker-selected")
    with pytest.raises(ValueError, match="delivery requires a policy"):
        journal.launch([sys.executable, "-c", "pass"], tmp_path, {}, 10,
                       {"candidate_id": "c", "attempt": 1},
                       seccomp_delivery=SECCOMP_DIRECT_PRCTL)
    assert list(store.read("executor_process_started")) == []


@REAL_DIRECT
def test_proposer_owner_crash_adopts_original_direct_seccomp_outcome(tmp_path):
    root, script, count = proposer_workspace(tmp_path, "direct-recovery")
    store_path = tmp_path / "recovery/x1.jsonl"
    owner = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "--direct-owner",
         str(root), str(script), str(count), str(store_path)], cwd=PROJECT,
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
    original = started[0]["payload"]
    owner.kill()
    owner.wait(timeout=5)
    assert owner.returncode == -9

    recovered = proposer(root, script, count, store, MockLLM(),
                         "seccomp_delayed", time_limit=10)
    recovered.set_operation_context(context())
    probe = json.loads(recovered(PROMPT))
    assert probe["errno"] == 1 and probe["status"]["Seccomp"] == 2
    assert count.read_text().splitlines() == ["call"]
    assert len(list(store.read("executor_process_started"))) == 1
    assert len(list(store.read("external_proposer_outcome"))) == 1
    assert started_record(store)["seccomp_policy"] == original["seccomp_policy"]
    assert started_record(store)["seccomp_delivery"] == "direct_prctl"


def owner_main(root, script, count, store_path):
    llm = proposer(root, script, count, AppendOnlyStore(store_path), MockLLM(),
                   "seccomp_delayed", time_limit=10)
    llm.set_operation_context(context())
    llm(PROMPT)


if __name__ == "__main__" and len(sys.argv) == 6 and sys.argv[1] == "--direct-owner":
    owner_main(Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4]), Path(sys.argv[5]))
