"""The detached writer and recovery reader share the same process identity rules."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time

import pytest

from core.executor import process
from core.executor.process import ProcessJournal
from core.executor import process_identity
from core.x1.store import AppendOnlyStore


def load_wrapper():
    path = Path(process.__file__).with_name("process_wrapper.py")
    spec = importlib.util.spec_from_file_location("identity_test_wrapper", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("name", ["python", "worker with spaces", "a ) tricky (name)",
                                  "worker\nwith\ttabs )"])
@pytest.mark.parametrize("state", ["S", "Z"])
def test_writer_persists_the_same_identity_the_reader_observes(tmp_path, monkeypatch, name, state):
    wrapper = load_wrapper()
    raw = f"101 ({name}) {state} " + " ".join(["0"] * 18 + ["12345"] + ["0"] * 10)
    original_read = Path.read_text
    monkeypatch.setattr(Path, "read_text", lambda path, *args, **kwargs:
                        raw if str(path) == "/proc/101/stat" else original_read(path, *args, **kwargs))
    target = type("OwnedChild", (), {"pid": 101})()
    destination = tmp_path / "target.json"
    wrapper._record_target_identity(target, destination)
    record = json.loads(destination.read_text())
    assert record == {"pid": 101, "start_ticks": 12345}
    assert process.start_ticks(101) == wrapper._start_ticks(101) == 12345
    assert process.process_alive(record["pid"], record["start_ticks"]) is (state != "Z")
    assert process.start_ticks is process_identity.start_ticks
    assert Path(wrapper._start_ticks.__code__.co_filename) == Path(process_identity.__file__)


@pytest.mark.parametrize("raw", ["101 no parentheses S 0", "101 (worker S 0",
                                 "101 (worker) S 0", "102 (foreign) S 0",
                                 "101 (name) S " + " ".join(["0"] * 18 + ["-1"])])
def test_invalid_stat_is_rejected_by_both_paths(monkeypatch, raw):
    wrapper = load_wrapper()
    monkeypatch.setattr(Path, "read_text", lambda *args, **kwargs: raw)
    assert process.start_ticks(101) is None
    assert wrapper._start_ticks(101) is None
    assert not process.process_alive(101, 12345)


@pytest.mark.parametrize("failure", ["missing-identity", "publication"])
def test_target_identity_failure_stops_and_reaps_the_owned_child(tmp_path, monkeypatch, failure):
    wrapper = load_wrapper()
    calls = []
    target = type("OwnedChild", (), {
        "pid": 101, "poll": lambda self: None,
        "wait": lambda self: calls.append("reaped")})()
    monkeypatch.setattr(wrapper, "_start_ticks", lambda pid: None if failure == "missing-identity" else 12345)
    monkeypatch.setattr(wrapper.os, "killpg", lambda pid, sig: calls.append((pid, sig)))
    if failure == "publication":
        def failed_write(*args):
            raise OSError("disk write failed")
        monkeypatch.setattr(wrapper, "_atomic_json", failed_write)
    destination = tmp_path / "target.json"
    with pytest.raises(RuntimeError if failure == "missing-identity" else OSError):
        wrapper._record_target_identity(target, destination)
    assert calls == [(101, signal.SIGKILL), "reaped"]
    assert not destination.exists()


def test_missing_identity_of_already_reaped_child_never_signals_reused_pid(tmp_path, monkeypatch):
    wrapper = load_wrapper()
    calls = []
    target = type("CompletedChild", (), {
        "pid": 101, "poll": lambda self: 0,
        "wait": lambda self: calls.append("reaped")})()
    monkeypatch.setattr(wrapper, "_start_ticks", lambda pid: None)
    monkeypatch.setattr(wrapper.os, "killpg", lambda pid, sig: calls.append((pid, sig)))
    with pytest.raises(RuntimeError, match="stable OS start identity"):
        wrapper._record_target_identity(target, tmp_path / "target.json")
    assert calls == ["reaped"]


@pytest.mark.parametrize("identity", [None, True, -1, "12345"])
def test_recovery_requires_a_nonnegative_integer_start_identity(monkeypatch, identity):
    raw = "101 (normal) S " + " ".join(["0"] * 18 + ["12345"])
    monkeypatch.setattr(Path, "read_text", lambda *args, **kwargs: raw)
    assert not process.process_alive(101, identity)


@pytest.mark.linux
def test_real_wrapper_records_named_executable_and_owner_recovery_stops_it(tmp_path):
    source = shutil.which("sleep")
    assert source, "Linux acceptance requires the system sleep utility"
    executable = tmp_path / "sleep ) child"
    shutil.copyfile(source, executable)
    executable.chmod(0o700)
    journal = ProcessJournal(AppendOnlyStore(tmp_path / "x1.jsonl"))
    wrapper, record = journal.launch(
        [str(executable), "30"], tmp_path, dict(os.environ), 30,
        {"candidate_id": "identity-writer", "attempt": 1})
    try:
        target_path = Path(record["target_path"])
        deadline = time.monotonic() + 5
        while not target_path.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert target_path.exists()
        target = json.loads(target_path.read_text())
        stat = Path(f"/proc/{target['pid']}/stat").read_text()
        assert f"({executable.name})" in stat
        assert target["start_ticks"] == process.start_ticks(target["pid"])
        assert process.process_alive(target["pid"], target["start_ticks"])
        wrapper.kill()
        wrapper.wait(timeout=5)
        assert journal.recover(record)["status"] == "lost"
        deadline = time.monotonic() + 5
        while process.process_alive(target["pid"], target["start_ticks"]) and time.monotonic() < deadline:
            time.sleep(0.01)
        assert not process.process_alive(target["pid"], target["start_ticks"])
    finally:
        if wrapper.poll() is None:
            wrapper.kill()
        wrapper.wait(timeout=5)
        journal.terminate_target(record)


@pytest.mark.linux
def test_fast_child_still_has_a_durable_identity_and_successful_result(tmp_path):
    journal = ProcessJournal(AppendOnlyStore(tmp_path / "x1.jsonl"))
    wrapper, record = journal.launch(
        ["/bin/true"], tmp_path, dict(os.environ), 5,
        {"candidate_id": "fast-identity", "attempt": 1})
    completed = journal.wait(wrapper, record)
    assert completed["returncode"] == 0 and completed["wrapper_error"] is None
    target = json.loads(Path(record["target_path"]).read_text())
    assert type(target["start_ticks"]) is int and target["start_ticks"] >= 0
