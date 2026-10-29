"""v38 default Bubblewrap policy and explicit fail-closed/disable behavior."""
import json
import socket
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.executor import ExternalCommandEvaluator
from core.x1.store import AppendOnlyStore
from test_external_evaluator import evaluator, workspace


@pytest.mark.parametrize("explicit", [False, True])
def test_default_bubblewrap_is_real_and_audited(tmp_path, monkeypatch, explicit):
    root, script = workspace(tmp_path, f"default-{explicit}")
    secret = tmp_path / f"secret-{explicit}.txt"
    escape = tmp_path / f"escape-{explicit}.txt"
    secret.write_text("host-canary")
    server = socket.socket()
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    monkeypatch.setenv("AR_TEST_SECRET", "environment-canary")
    store = AppendOnlyStore(tmp_path / f"run-{explicit}/x1.jsonl")
    kwargs = {"sandbox": True} if explicit else {}
    try:
        external = evaluator(root, script, store, "sandbox", secret, escape,
                             server.getsockname()[1], time_limit=10, **kwargs)
        result = external("candidate", "head1234", "prompt")
    finally:
        server.close()
    assert result.public == {"sandbox_ok": True, "env_ok": True, "file_ok": True,
                             "network_ok": True, "escape_attempted": True}
    assert external.sandbox_policy == "BubblewrapSandbox"
    assert not escape.exists() and secret.read_text() == "host-canary"
    started = list(store.read("executor_process_started"))
    assert len(started) == 1
    payload = started[0]["payload"]
    assert payload["sandbox_policy"] == "BubblewrapSandbox"
    spec = json.loads(Path(payload["spec_path"]).read_text())
    assert Path(spec["args"][0]).name == "bwrap"
    assert "--unshare-all" in spec["args"] and "--clearenv" in spec["args"]
    persisted = store.path.read_text() + Path(payload["spec_path"]).read_text()
    assert "environment-canary" not in persisted and "AR_TEST_SECRET" not in persisted


@pytest.mark.parametrize("disabled", [None, False])
def test_only_explicit_disable_runs_without_isolation(tmp_path, monkeypatch, disabled):
    root, script = workspace(tmp_path, f"disabled-{disabled}")
    secret = tmp_path / f"secret-{disabled}.txt"
    escape = tmp_path / f"escape-{disabled}.txt"
    secret.write_text("host-canary")
    server = socket.socket()
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    monkeypatch.setenv("AR_TEST_SECRET", "environment-canary")
    store = AppendOnlyStore(tmp_path / f"disabled-run-{disabled}/x1.jsonl")
    try:
        external = evaluator(root, script, store, "sandbox", secret, escape,
                             server.getsockname()[1], sandbox=disabled, time_limit=10)
        result = external("candidate", "head1234", "prompt")
    finally:
        server.close()
    assert result.public == {"sandbox_ok": False, "env_ok": False, "file_ok": False,
                             "network_ok": False, "escape_attempted": True}
    assert external.sandbox is None and external.sandbox_policy == "disabled"
    assert escape.read_text() == "escaped"
    started = list(store.read("executor_process_started"))
    assert len(started) == 1
    payload = started[0]["payload"]
    assert payload["sandbox_policy"] == "disabled"
    spec = json.loads(Path(payload["spec_path"]).read_text())
    assert Path(spec["args"][0]).name != "bwrap"


def test_missing_default_bwrap_fails_closed_before_process_launch(tmp_path, monkeypatch):
    root, script = workspace(tmp_path, "missing-bwrap")
    store = AppendOnlyStore(tmp_path / "missing-run/x1.jsonl")
    monkeypatch.setattr("core.executor.sandbox.shutil.which", lambda executable: None)
    with pytest.raises(RuntimeError, match="requires an installed bwrap"):
        evaluator(root, script, store)
    assert list(store.read("executor_process_started")) == []
    assert list(store.read("external_evaluator_outcome")) == []
    assert not (root / "run/evaluations").exists()


@pytest.mark.parametrize("disabled", [None, False, "default"])
def test_fork_inherits_policy_and_keeps_independent_process_history(tmp_path, disabled):
    root, script = workspace(tmp_path, f"fork-{disabled}")
    store = AppendOnlyStore(tmp_path / f"original-{disabled}/x1.jsonl")
    kwargs = {} if disabled == "default" else {"sandbox": disabled}
    external = evaluator(root, script, store, **kwargs)
    external("original", "head1234", "prompt")
    replay_store = AppendOnlyStore(tmp_path / f"replay-{disabled}/x1.jsonl")
    clone = external.fork(tmp_path / f"replay-work-{disabled}", replay_store)
    clone("replayed", "head5678", "prompt")
    expected = "disabled" if disabled != "default" else "BubblewrapSandbox"
    assert external.sandbox_policy == clone.sandbox_policy == expected
    assert (external.sandbox is None) == (clone.sandbox is None)
    original = list(store.read("executor_process_started"))
    replayed = list(replay_store.read("executor_process_started"))
    assert len(original) == len(replayed) == 1
    assert original[0]["payload"]["execution_id"] != replayed[0]["payload"]["execution_id"]
    assert original[0]["payload"]["sandbox_policy"] == expected
    assert replayed[0]["payload"]["sandbox_policy"] == expected
    assert len(list(store.read("external_evaluator_outcome"))) == 1
    replay_outcomes = list(replay_store.read("external_evaluator_outcome"))
    assert len(replay_outcomes) == 1
    assert replay_outcomes[0]["payload"]["candidate_id"] == "replayed"
