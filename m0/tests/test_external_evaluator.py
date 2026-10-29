"""v29 explicit external M0 evaluator process/protocol integration."""
import json
import os
import socket
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.executor import (BubblewrapSandbox, ExternalCommandEvaluator,
                           ExternalEvaluatorError)
from core.executor.types import EvalStatus
from core.loop import Framework, LoopConfig
from core.x1.store import AppendOnlyStore
from examples.toy_gepa import MockLLM

TASK = "external M0 evaluator protocol"


SCRIPT = r'''
import json, os, signal, socket, sys, time
from pathlib import Path
mode = sys.argv[1]
request_path, response_path = Path(sys.argv[-2]), Path(sys.argv[-1])
request = json.loads(request_path.read_text())
if mode == "timeout":
    time.sleep(10)
if mode == "delayed":
    time.sleep(2)
if mode == "delayed_non_genesis" and request["candidate_id"] != sys.argv[2]:
    time.sleep(2)
if mode == "fail_non_genesis" and request["candidate_id"] != sys.argv[2]:
    response_path.write_text(json.dumps({"schema_version": 1,
        "token_usage": {"total_tokens": 0}}))
    print("injected external failure", file=sys.stderr)
    raise SystemExit(3)
if mode == "fail_control" and request["candidate_id"] == sys.argv[2]:
    response_path.write_text(json.dumps({"schema_version": 1,
        "token_usage": {"total_tokens": 0}}))
    print("injected external control failure", file=sys.stderr)
    raise SystemExit(3)
public = {}
if mode in {"seccomp", "seccomp_delayed"}:
    if mode == "seccomp_delayed":
        time.sleep(2)
    import ctypes, errno
    libc = ctypes.CDLL(None, use_errno=True)
    returncode = libc.syscall(101, 0, 0, 0, 0)  # x86_64 ptrace(PTRACE_TRACEME)
    error_number = ctypes.get_errno()
    public = {"syscall": "ptrace", "returncode": returncode,
              "errno": error_number,
              "blocked": returncode == -1 and error_number == errno.EPERM}
if mode == "sandbox":
    secret_path, escape_path, port = sys.argv[2], Path(sys.argv[3]), int(sys.argv[4])
    env_ok = os.environ.get("AR_TEST_SECRET") is None
    file_ok = network_ok = True
    escape_attempted = False
    try:
        Path(secret_path).read_text()
        file_ok = False
    except OSError:
        pass
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.2):
            network_ok = False
    except OSError:
        pass
    try:
        escape_path.write_text("escaped")
        escape_attempted = True
    except OSError:
        pass
    public = {"sandbox_ok": all((env_ok, file_ok, network_ok)),
              "env_ok": env_ok, "file_ok": file_ok,
              "network_ok": network_ok, "escape_attempted": escape_attempted}
if mode == "resource":
    probe = sys.argv[2]
    limited = False
    detail = "probe completed without a limit"
    try:
        if probe == "memory":
            block = bytearray(256 * 1024 * 1024)
        elif probe == "file":
            signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
            (response_path.parent / "limit.bin").write_bytes(b"x" * 4096)
        elif probe == "process":
            children = []
            for _ in range(64):
                child = os.fork()
                if child == 0:
                    os._exit(0)
                children.append(child)
            for child in children:
                os.waitpid(child, 0)
        else:
            raise ValueError("unknown resource probe")
    except (MemoryError, OSError) as error:
        limited = True
        detail = type(error).__name__
    public = {"probe": probe, "limited": limited, "detail": detail}
if mode == "malformed":
    response_path.write_text(json.dumps({"unexpected": True}))
    raise SystemExit(0)
prompt = request["prompt"]
items = []
unsolved = []
for index in range(12):
    solved = index < 4 or f"hint_{index}" in prompt
    items.append({"item_id": f"item_{index}", "verdict": 1 if solved else 0})
    if not solved:
        unsolved.append(index)
feedback = "all solved" if not unsolved else (
    f"item_{unsolved[0]} failed; missing hint: hint_{unsolved[0]}")
result = {"candidate_id": request["candidate_id"], "head_sha": request["head_sha"],
          "items": items, "combined_score": sum(i["verdict"] for i in items) / 12,
          "public": public, "private": {}, "text_feedback": feedback,
          "reliability": {"n_trials": 1, "ci95": None, "noise_floor": 0.0},
          "evaluator_version": "external-toy-v1"}
envelope = {"schema_version": 1, "result": result, "token_usage": {"total_tokens": 7}}
temporary = response_path.with_suffix(".tmp")
temporary.write_text(json.dumps(envelope))
os.replace(temporary, response_path)
'''


def workspace(tmp_path, name="workspace"):
    root = tmp_path / name
    root.mkdir(parents=True)
    script = root / "evaluator.py"
    script.write_text(SCRIPT)
    return root, script


def evaluator(root, script, store, mode="ok", *args, **kwargs):
    execution_root = root / "run"
    execution_root.mkdir(parents=True, exist_ok=True)
    execution_script = execution_root / "evaluator.py"
    execution_script.write_text(script.read_text())
    return ExternalCommandEvaluator(
        [sys.executable, str(execution_script), mode, *map(str, args)],
        execution_root, store, **kwargs)


def test_real_subprocess_result_usage_and_persistent_native_outcome(tmp_path):
    root, script = workspace(tmp_path)
    store = AppendOnlyStore(tmp_path / "run/x1.jsonl")
    external = evaluator(root, script, store)
    result = external("candidate", "head1234", "hint_4")
    assert result.combined_score == pytest.approx(5 / 12)
    assert [item.verdict for item in result.items[:6]] == [1, 1, 1, 1, 1, 0]
    assert result.text_feedback == "item_5 failed; missing hint: hint_5"
    assert external.last_usage == {"total_tokens": 7}
    outcomes = list(store.read("external_evaluator_outcome"))
    assert len(outcomes) == 1
    outcome = outcomes[0]["payload"]
    assert outcome["status"] == "ok" and outcome["candidate_id"] == "candidate"
    assert outcome["request_sha256"].startswith("sha256:")
    assert outcome["response_sha256"].startswith("sha256:")
    persisted = json.loads(Path(outcome["outcome_path"]).read_text())
    assert persisted["result"]["head_sha"] == "head1234"
    assert len(list(store.read("executor_process_started"))) == 1


@pytest.mark.parametrize("mode,status", [("malformed", EvalStatus.INVALID),
                                         ("timeout", EvalStatus.TIMEOUT)])
def test_invalid_and_timeout_are_structured_failures(tmp_path, mode, status):
    root, script = workspace(tmp_path, mode)
    store = AppendOnlyStore(tmp_path / f"{mode}/x1.jsonl")
    external = evaluator(root, script, store, mode, time_limit=1)
    with pytest.raises(ExternalEvaluatorError) as caught:
        external("candidate", "head1234", "prompt")
    assert caught.value.status is status
    outcome = list(store.read("external_evaluator_outcome"))[-1]["payload"]
    assert outcome["status"] == status.value
    assert outcome["result"] is None


def test_real_sandbox_clears_environment_and_blocks_host_file_network_and_escape(tmp_path):
    root, script = workspace(tmp_path, "sandbox")
    secret = tmp_path / "secret.txt"
    escape = tmp_path / "escape.txt"
    secret.write_text("host-canary")
    server = socket.socket()
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    os.environ["AR_TEST_SECRET"] = "environment-canary"
    store = AppendOnlyStore(tmp_path / "sandbox-run/x1.jsonl")
    try:
        external = evaluator(root, script, store, "sandbox", secret, escape,
                             server.getsockname()[1], sandbox=BubblewrapSandbox(),
                             time_limit=10)
        result = external("candidate", "head1234", "prompt")
    finally:
        server.close()
        os.environ.pop("AR_TEST_SECRET", None)
    assert {key: result.public[key] for key in
            ("env_ok", "file_ok", "network_ok", "escape_attempted")} == {
                "env_ok": True, "file_ok": True, "network_ok": True,
                "escape_attempted": True}
    assert result.public["sandbox_ok"] is True
    assert not escape.exists() and secret.read_text() == "host-canary"
    persisted = store.path.read_text()
    for record in store.read("executor_process_started"):
        persisted += Path(record["payload"]["spec_path"]).read_text()
    assert "environment-canary" not in persisted and "AR_TEST_SECRET" not in persisted


def test_sequential_failure_is_settled_evidence_not_a_loop_exception(tmp_path):
    root, script = workspace(tmp_path)
    run_dir = tmp_path / "run"
    store = AppendOnlyStore(run_dir / "x1.jsonl")
    probe = Framework(MockLLM(), None, LoopConfig(), str(tmp_path / "probe"))
    genesis = probe._proposal_id(TASK, "genesis")
    external = evaluator(root, script, store, "fail_non_genesis", genesis)
    fw = Framework(MockLLM(), external,
                   LoopConfig(max_generations=1, baseline_every=5), str(run_dir))
    out = fw.evolve(TASK)
    assert out["best_score"] == pytest.approx(1 / 3)
    assert out["main_scores"] == [pytest.approx(1 / 3), pytest.approx(1 / 3)]
    failures = list(fw.store.read("executor_evidence"))
    assert len(failures) == 1
    evidence = failures[0]["payload"]["evidence"]
    assert evidence["eval_result"]["status"] == "failed_to_run"
    failed_outcome = next(row["payload"] for row in fw.store.read(
        "external_evaluator_outcome") if row["payload"]["status"] == "failed_to_run")
    assert failures[0]["payload"]["execution_id"] == failed_outcome["execution_id"]
    assert fw.inspect()["governance_pass"] is True
    assert out["funnels"][-1].runnable == 0


def test_batch_failure_and_successful_external_replay_use_independent_evidence(tmp_path):
    root, script = workspace(tmp_path)
    failed_dir = tmp_path / "failed"
    failed_store = AppendOnlyStore(failed_dir / "x1.jsonl")
    probe = Framework(MockLLM(), None, LoopConfig(), str(tmp_path / "batch-probe"))
    genesis = probe._proposal_id(TASK, "genesis")
    failed_external = evaluator(root, script, failed_store, "fail_non_genesis", genesis)
    failed_fw = Framework(MockLLM(), failed_external,
                          LoopConfig(max_generations=1, batch_size=2, max_inflight=2,
                                     baseline_every=5), str(failed_dir))
    failed = failed_fw.evolve(TASK)
    assert len(failed["governed_state"]["pruned_ids"]) == 2
    assert failed_fw.inspect()["governance_pass"] is True
    settled = list(failed_fw.store.read("batch_execution_settled"))
    assert {row["payload"]["status"] for row in settled} == {"failed_to_run"}

    run_dir = tmp_path / "success"
    store = AppendOnlyStore(run_dir / "x1.jsonl")
    external = evaluator(root, script, store)
    fw = Framework(MockLLM(), external,
                   LoopConfig(max_generations=4, baseline_every=2), str(run_dir))
    first = fw.evolve(TASK)
    before = len(list(fw.store.read("external_evaluator_outcome")))
    replayed = fw.replay()
    after = len(list(fw.store.read("external_evaluator_outcome")))
    replay_store = AppendOnlyStore(run_dir / "replay/x1.jsonl")
    assert before == after == 7
    assert len(list(replay_store.read("external_evaluator_outcome"))) == 7
    assert fw.inspect()["replay_certified"] is True
    assert fw.inspect()["formal_governance_pass"] is True
    assert replayed["best_score"] == first["best_score"]
    assert first["ledger"]["spent"]["control"] == 2 * (1000 + 7)
