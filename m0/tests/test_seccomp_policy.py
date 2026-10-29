"""v56 real Bubblewrap seccomp denylist, audit and recovery evidence."""
import asyncio
import base64
import copy
import hashlib
import json
import os
import platform
import shutil
import struct
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from core.executor import BubblewrapSandbox, Candidate, EvalRequest, EvalStatus, ExecutorSpec
from core.executor import GitWorktree, GitWorktreeExecutor
from core.executor.process import ProcessJournal
from core.executor.seccomp import (DENIED_SYSCALLS, SECCOMP_FD_PLACEHOLDER,
                                   build_seccomp_policy, seccomp_arguments,
                                   seccomp_policy_summary, validate_seccomp_policy)
from core.x1.store import AppendOnlyStore
from test_external_evaluator import evaluator, workspace
from test_sandbox_executor import builder_for, contract, listener, make_repo

PROJECT = Path(__file__).resolve().parents[1]
REAL_SANDBOX = pytest.mark.skipif(
    platform.machine() != "x86_64" or shutil.which("bwrap") is None,
    reason="v56 real filter verification requires x86_64 and bubblewrap")


def test_canonical_policy_has_arch_guard_errno_and_allow_termination():
    policy = build_seccomp_policy("x86_64")
    encoded = validate_seccomp_policy(policy)
    assert len(encoded) == 8 * (10 + 2 * len(DENIED_SYSCALLS))
    first = struct.unpack("<HBBI", encoded[:8])
    arch_check = struct.unpack("<HBBI", encoded[8:16])
    arch_kill = struct.unpack("<HBBI", encoded[16:24])
    final = struct.unpack("<HBBI", encoded[-8:])
    assert first == (0x20, 0, 0, 4)
    assert arch_check == (0x15, 1, 0, 0xC000003E)
    assert arch_kill[0:3] == (0x06, 0, 0) and arch_kill[3] == 0x80000000
    assert final == (0x06, 0, 0, 0x7FFF0000)
    assert "ptrace" in policy["denied_syscalls"]
    assert "unshare" in policy["denied_syscalls"]
    assert policy["action"] == "errno:EPERM"
    assert policy["policy_version"] == 2
    assert policy["denied_syscall_bits"] == 0x40000000
    assert policy["denied_syscall_ranges"] == [[512, 547]]
    summary = seccomp_policy_summary(policy)
    assert "filter_base64" not in summary
    assert summary["filter_sha256"] == hashlib.sha256(encoded).hexdigest()


@pytest.mark.parametrize("architecture", ["aarch64", "arm64", "ppc64le", ""])
def test_unsupported_architecture_fails_closed(architecture):
    with pytest.raises(RuntimeError, match="requires x86_64"):
        build_seccomp_policy(architecture)


@pytest.mark.parametrize("mutation", [
    "filter_and_rehashed_digest", "denied_syscalls", "action", "version", "extra_field"])
def test_semantic_policy_tamper_is_rejected_even_with_recomputed_hash(mutation):
    policy = copy.deepcopy(build_seccomp_policy("x86_64"))
    if mutation == "filter_and_rehashed_digest":
        encoded = bytearray(base64.b64decode(policy["filter_base64"]))
        encoded[-1] ^= 1
        policy["filter_base64"] = base64.b64encode(encoded).decode("ascii")
        policy["filter_sha256"] = hashlib.sha256(encoded).hexdigest()
    elif mutation == "denied_syscalls":
        policy["denied_syscalls"].remove("ptrace")
    elif mutation == "action":
        policy["action"] = "allow"
    elif mutation == "version":
        policy["policy_version"] = 1
    else:
        policy["attacker_controlled"] = True
    with pytest.raises(ValueError, match="canonical versioned denylist"):
        validate_seccomp_policy(policy)


@REAL_SANDBOX
def test_direct_popen_uses_same_memfd_contract(tmp_path):
    sandbox = BubblewrapSandbox()
    probe = ("import ctypes,errno; c=ctypes.CDLL(None,use_errno=True); "
             "r=c.syscall(101,0,0,0,0); e=ctypes.get_errno(); "
             "raise SystemExit(0 if r == -1 and e == errno.EPERM else 9)")
    command = sandbox.wrap([sys.executable, "-c", probe], tmp_path, env={})
    with seccomp_arguments(command, sandbox.seccomp_spec()) as (args, pass_fds):
        assert args[args.index("--seccomp") + 1].isdigit()
        process = subprocess.Popen(args, cwd=tmp_path, pass_fds=pass_fds,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = process.communicate(timeout=10)
    assert process.returncode == 0, stderr.decode(errors="replace")


@REAL_SANDBOX
def test_external_evaluator_real_eperm_fork_and_public_audit(tmp_path, monkeypatch):
    root, script = workspace(tmp_path, "external-seccomp")
    monkeypatch.setenv("AR_TEST_SECRET", "seccomp-environment-canary")
    store = AppendOnlyStore(tmp_path / "original/x1.jsonl")
    external = evaluator(root, script, store, "seccomp", time_limit=10)
    result = external("candidate", "head1234", "prompt")
    assert result.public["blocked"] is True
    assert result.public["returncode"] == -1 and result.public["errno"] == 1
    started = list(store.read("executor_process_started"))
    assert len(started) == 1
    record = started[0]["payload"]
    policy = record["seccomp_policy"]
    assert policy["policy"] == "dangerous-syscall-denylist"
    assert policy["policy_version"] == 2 and "filter_base64" not in policy
    spec = json.loads(Path(record["spec_path"]).read_text())
    assert spec["seccomp_policy"]["filter_base64"]
    assert spec["seccomp_policy"]["filter_sha256"] == policy["filter_sha256"]
    assert SECCOMP_FD_PLACEHOLDER in spec["args"]
    persisted = store.path.read_text() + Path(record["spec_path"]).read_text()
    assert "seccomp-environment-canary" not in persisted
    assert "AR_TEST_SECRET" not in persisted

    replay_store = AppendOnlyStore(tmp_path / "replay/x1.jsonl")
    clone = external.fork(tmp_path / "replay-work", replay_store)
    replayed = clone("replayed", "head5678", "prompt")
    assert replayed.public["blocked"] is True
    replay_record = list(replay_store.read("executor_process_started"))[0]["payload"]
    assert replay_record["seccomp_policy"] == policy
    assert replay_record["execution_id"] != record["execution_id"]


@REAL_SANDBOX
@pytest.mark.parametrize("sandbox", ["seccomp_disabled", "sandbox_disabled"])
def test_only_explicit_disable_omits_seccomp_policy(tmp_path, sandbox):
    root, script = workspace(tmp_path, f"disable-{sandbox}")
    store = AppendOnlyStore(tmp_path / f"run-{sandbox}/x1.jsonl")
    selected = BubblewrapSandbox(seccomp=False) if sandbox == "seccomp_disabled" else None
    external = evaluator(root, script, store, sandbox=selected, time_limit=10)
    result = external("candidate", "head1234", "prompt")
    assert result.combined_score == pytest.approx(1 / 3)
    record = list(store.read("executor_process_started"))[0]["payload"]
    assert record["seccomp_policy"] is None
    spec = json.loads(Path(record["spec_path"]).read_text())
    assert spec["seccomp_policy"] is None
    assert SECCOMP_FD_PLACEHOLDER not in spec["args"]


@REAL_SANDBOX
def test_detached_wrapper_rejects_rehashed_spec_before_target_start(tmp_path):
    root = tmp_path / "wrapper"
    root.mkdir()
    sandbox = BubblewrapSandbox()
    args = sandbox.wrap([sys.executable, "-c", "raise AssertionError('target started')"],
                        root, env={})
    policy = copy.deepcopy(sandbox.seccomp_spec())
    encoded = bytearray(base64.b64decode(policy["filter_base64"]))
    encoded[-1] ^= 1
    policy["filter_base64"] = base64.b64encode(encoded).decode("ascii")
    policy["filter_sha256"] = hashlib.sha256(encoded).hexdigest()
    spec = {
        "args": args, "cwd": str(root), "time_limit": 10, "resource_limits": {},
        "seccomp_policy": policy, "stdout_path": str(root / "stdout.txt"),
        "stderr_path": str(root / "stderr.txt"), "result_path": str(root / "result.json"),
        "target_path": str(root / "target.json")}
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


@REAL_SANDBOX
def test_invalid_policy_fails_before_process_journal_launch(tmp_path):
    store = AppendOnlyStore(tmp_path / "evidence.jsonl")
    journal = ProcessJournal(store)
    policy = build_seccomp_policy()
    policy["denied_syscalls"].remove("ptrace")
    with pytest.raises(ValueError, match="canonical versioned denylist"):
        journal.launch([sys.executable, "-c", "pass"], tmp_path, {}, 10,
                       {"candidate_id": "c", "attempt": 1}, seccomp_policy=policy)
    assert list(store.read("executor_process_started")) == []


@REAL_SANDBOX
def test_git_worktree_executor_enforces_and_audits_same_policy(tmp_path):
    repo = make_repo(tmp_path)
    (tmp_path / "host-secret.txt").write_text("host-canary")
    (tmp_path / "data").mkdir()
    (tmp_path / "data/input.txt").write_text("offline-data")
    server = listener()
    store = AppendOnlyStore(tmp_path / "evidence.jsonl")
    try:
        executor = GitWorktreeExecutor(
            contract(), builder_for(tmp_path, server.getsockname()[1]), store,
            data_dir=tmp_path / "data", sandbox=BubblewrapSandbox())
        evidence = asyncio.run(executor.execute(
            ExecutorSpec(), Candidate("seccomp-worktree"),
            GitWorktree(repo, tmp_path / "worktrees"),
            EvalRequest("dev", time_limit=10, seed_set=[20])))
    finally:
        server.close()
    # make_repo's real eval.py fails unless ptrace returns EPERM.
    assert evidence.executor_status == "scored", evidence.result_text
    assert evidence.eval_result.status is EvalStatus.OK
    record = list(store.read("executor_process_started"))[0]["payload"]
    assert record["seccomp_policy"]["filter_sha256"] == \
        build_seccomp_policy()["filter_sha256"]
    spec = json.loads(Path(record["spec_path"]).read_text())
    assert spec["seccomp_policy"]["denied_syscalls"] == list(DENIED_SYSCALLS)


@REAL_SANDBOX
def test_owner_crash_adopts_original_seccomp_outcome_without_reexecution(tmp_path):
    root, script = workspace(tmp_path, "seccomp-recovery")
    store_path = tmp_path / "recovery/x1.jsonl"
    owner = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "--seccomp-owner",
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
    original = started[0]["payload"]
    owner.kill()
    owner.wait(timeout=5)
    assert owner.returncode == -9

    recovered = evaluator(root, script, store, "seccomp_delayed", time_limit=10)
    outcomes = recovered.recover_inflight(wait=True)
    assert len(outcomes) == 1 and outcomes[0]["error"] is None
    assert outcomes[0]["result"].public["blocked"] is True
    assert len(list(store.read("executor_process_started"))) == 1
    assert len(list(store.read("external_evaluator_outcome"))) == 1
    assert list(store.read("executor_process_started"))[0]["payload"]["seccomp_policy"] == \
        original["seccomp_policy"]


def owner_main(root, script, store_path):
    external = evaluator(root, script, AppendOnlyStore(store_path),
                         "seccomp_delayed", time_limit=10)
    external("seccomp-recovery", "head1234", "prompt")


if __name__ == "__main__" and len(sys.argv) == 5 and sys.argv[1] == "--seccomp-owner":
    owner_main(Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4]))
