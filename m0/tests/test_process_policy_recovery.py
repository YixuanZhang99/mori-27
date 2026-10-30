"""Unfinished detached work cannot retain a superseded seccomp policy on recovery."""
from __future__ import annotations

import base64
import copy
import hashlib
import json
from pathlib import Path
import signal
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.executor import process
from core.executor.process import ProcessJournal, start_ticks
from core.executor.seccomp import build_seccomp_policy, seccomp_policy_summary
from core.x1.store import AppendOnlyStore


@pytest.mark.parametrize("name", ["python", "worker with spaces", "a ) tricky (name)",
                                  "worker\nwith\ttabs )"])
@pytest.mark.parametrize("state", ["S", "Z"])
def test_process_identity_parses_whitespace_and_parentheses_inside_comm(monkeypatch, name, state):
    monkeypatch.setattr(sys, "platform", "linux")
    raw = f"101 ({name}) {state} " + " ".join(["0"] * 18 + ["12345"] + ["0"] * 10)
    monkeypatch.setattr(process.Path, "read_text", lambda *args, **kwargs: raw)
    assert process.start_ticks(101) == 12345
    assert process.process_alive(101, 12345) is (state != "Z")
    assert process.process_alive(101, 12346) is False


@pytest.mark.parametrize("raw", ["101 no parentheses S 0", "101 (worker S 0",
                                 "101 (worker) S 0", "102 (foreign) S 0"])
def test_invalid_process_stat_does_not_establish_identity(monkeypatch, raw):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(process.Path, "read_text", lambda *args, **kwargs: raw)
    assert process.start_ticks(101) is None
    assert process.process_alive(101, 12345) is False


def old_policy():
    policy = copy.deepcopy(build_seccomp_policy("x86_64"))
    current = base64.b64decode(policy["filter_base64"])
    old = current[:4 * 8] + current[9 * 8:]  # original architecture guard + native denylist
    policy.update(policy_version=1, filter_base64=base64.b64encode(old).decode(),
                  filter_sha256=hashlib.sha256(old).hexdigest())
    policy.pop("denied_syscall_bits")
    policy.pop("denied_syscall_ranges")
    return policy


def journal_record(tmp_path, policy, *, result=False):
    store = AppendOnlyStore(tmp_path / "x1.jsonl")
    journal = ProcessJournal(store)
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps({"seccomp_policy": policy,
                                     "seccomp_delivery": "direct_prctl"}))
    target_path = tmp_path / "target.json"
    target_path.write_text(json.dumps({"pid": 202, "start_ticks": 2002}))
    record = {"execution_id": "old-operation", "candidate_id": "candidate", "attempt": 1,
              "wrapper_pid": 101, "wrapper_start_ticks": 1001,
              "spec_path": str(spec_path), "target_path": str(target_path),
              "result_path": str(tmp_path / "result.json"),
              "stdout_path": str(tmp_path / "stdout.txt"),
              "stderr_path": str(tmp_path / "stderr.txt"),
              "seccomp_policy": {key: value for key, value in policy.items()
                                 if key != "filter_base64"},
              "seccomp_delivery": "direct_prctl"}
    if result:
        Path(record["result_path"]).write_text(json.dumps({"returncode": 0, "timeout": False}))
        Path(record["stdout_path"]).write_text("historical output")
        Path(record["stderr_path"]).write_text("")
    store.append("executor_process_started", record)
    return journal, record


def fake_identities(monkeypatch, *, wrapper=True, target=True):
    alive = {(101, 1001): wrapper, (202, 2002): target}
    signals = []
    monkeypatch.setattr(process, "process_alive", lambda pid, ticks: alive.get((pid, ticks), False))
    monkeypatch.setattr(process.os, "kill", lambda pid, sig: signals.append(("pid", pid, sig)))
    monkeypatch.setattr(process.os, "killpg", lambda pid, sig: signals.append(("group", pid, sig)))
    return signals


@pytest.mark.parametrize("has_result", [False, True])
def test_unfinalized_v1_is_stopped_and_blocked_even_with_atomic_raw_result(tmp_path, monkeypatch,
                                                                         has_result):
    journal, record = journal_record(tmp_path, old_policy(), result=has_result)
    original_spec = Path(record["spec_path"]).read_bytes()
    signals = fake_identities(monkeypatch)
    for _ in range(2):
        with pytest.raises(RuntimeError, match="seccomp recovery refused.*reconciliation"):
            journal.recover(record)
    assert signals[:2] == [("pid", 101, signal.SIGKILL), ("group", 202, signal.SIGKILL)]
    assert not journal.finished_ids()
    assert journal.unfinished() == [record]
    assert len(list(journal.store.read("executor_process_recovery_blocked"))) == 1
    assert Path(record["spec_path"]).read_bytes() == original_spec
    assert journal.started()[0]["seccomp_policy"]["policy_version"] == 1


@pytest.mark.parametrize("wrapper,target", [(False, False), (False, True), (True, False)])
def test_stale_policy_recovery_signals_only_verified_process_identities(tmp_path, monkeypatch,
                                                                      wrapper, target):
    journal, record = journal_record(tmp_path, old_policy())
    signals = fake_identities(monkeypatch, wrapper=wrapper, target=target)
    with pytest.raises(RuntimeError, match="seccomp recovery refused"):
        journal.recover(record)
    assert ("pid", 101, signal.SIGKILL) in signals if wrapper else not any(
        kind == "pid" for kind, *_ in signals)
    assert ("group", 202, signal.SIGKILL) in signals if target else not any(
        kind == "group" for kind, *_ in signals)


@pytest.mark.parametrize("tamper", ["relabelled", "summary", "delivery", "missing-spec"])
def test_recovery_requires_full_canonical_policy_and_matching_summary(tmp_path, monkeypatch, tamper):
    policy = build_seccomp_policy("x86_64")
    if tamper == "relabelled":
        old = old_policy()
        policy.update(filter_base64=old["filter_base64"], filter_sha256=old["filter_sha256"])
    journal, record = journal_record(tmp_path, policy)
    if tamper == "summary":
        record["seccomp_policy"]["filter_sha256"] = "f" * 64
    elif tamper == "delivery":
        record["seccomp_delivery"] = "bwrap_memfd"
    elif tamper == "missing-spec":
        Path(record["spec_path"]).unlink()
    fake_identities(monkeypatch)
    with pytest.raises(RuntimeError, match="seccomp recovery refused"):
        journal.recover(record)
    assert not journal.finished_ids()


@pytest.mark.parametrize("has_result", [False, True])
def test_canonical_v2_recovery_keeps_normal_pending_and_completion_semantics(tmp_path, monkeypatch,
                                                                           has_result):
    journal, record = journal_record(tmp_path, build_seccomp_policy("x86_64"), result=has_result)
    signals = fake_identities(monkeypatch)
    recovered = journal.recover(record)
    assert recovered["status"] == ("finished" if has_result else "pending")
    assert not signals
    assert not list(journal.store.read("executor_process_recovery_blocked"))


def test_finished_v1_outcome_stays_readable_without_relabelling_or_duplicate_completion(tmp_path,
                                                                                      monkeypatch):
    journal, record = journal_record(tmp_path, old_policy(), result=True)
    journal.store.append("executor_process_finished", {
        "execution_id": record["execution_id"], "candidate_id": record["candidate_id"],
        "attempt": 1, "returncode": 0, "timeout": False, "recovered": False})
    signals = fake_identities(monkeypatch)
    assert journal.completed_result(record)["stdout"] == "historical output"
    assert journal.recover(record)["status"] == "finished"
    assert len(list(journal.store.read("executor_process_finished"))) == 1
    assert journal.started()[0]["seccomp_policy"]["policy_version"] == 1
    assert not signals
    assert not list(journal.store.read("executor_process_recovery_blocked"))


@pytest.mark.linux
def test_stale_policy_recovery_terminates_real_verified_wrapper_and_target(tmp_path):
    journal, record = journal_record(tmp_path, old_policy())
    wrapper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                               start_new_session=True)
    target = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                              start_new_session=True)
    try:
        record.update(wrapper_pid=wrapper.pid, wrapper_start_ticks=start_ticks(wrapper.pid))
        assert record["wrapper_start_ticks"] is not None
        target_start = start_ticks(target.pid)
        assert target_start is not None
        Path(record["target_path"]).write_text(json.dumps({
            "pid": target.pid, "start_ticks": target_start}))
        with pytest.raises(RuntimeError, match="seccomp recovery refused"):
            journal.recover(record)
        assert wrapper.wait(timeout=5) == -signal.SIGKILL
        assert target.wait(timeout=5) == -signal.SIGKILL
        assert not journal.finished_ids()
    finally:
        for child in (wrapper, target):
            if child.poll() is None:
                child.kill()
            child.wait(timeout=5)
