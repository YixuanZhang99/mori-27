"""v42 real owner-SIGKILL adoption of an active detached proposal call."""
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from core.executor.proposal import ExternalCommandLLM
from core.loop import Framework
from core.x1.checkpoint import certified_snapshot_ref
from core.x1.store import AppendOnlyStore
from examples.toy_gepa import MockLLM
from test_external_batch_recovery import config
from test_external_batch_partial_start_recovery import crash_after_proposals
from test_external_evaluator import TASK, evaluator, workspace
from test_external_recovery import COMPARE, ForbiddenLLM

PROJECT = Path(__file__).resolve().parents[1]

PROPOSER_SCRIPT = r'''
import json, os, re, sys, time
from pathlib import Path
mode, count_path, request_path, response_path = sys.argv[1:]
with open(count_path, "a") as stream:
    stream.write("call\n")
if mode == "delayed":
    time.sleep(2)
if mode == "timeout":
    time.sleep(3)
if mode in ("seccomp", "seccomp_delayed"):
    import ctypes, errno
    if mode == "seccomp_delayed":
        time.sleep(2)
    libc = ctypes.CDLL(None, use_errno=True)
    returncode = libc.syscall(101, 0, 0, 0, 0)  # x86_64 ptrace(PTRACE_TRACEME)
    status = {}
    for line in Path("/proc/self/status").read_text().splitlines():
        if line.startswith(("NoNewPrivs:", "Seccomp:", "Seccomp_filters:")):
            key, value = line.split(":", 1)
            status[key] = int(value.strip())
    content = json.dumps({"returncode": returncode, "errno": ctypes.get_errno(),
                          "status": status}, sort_keys=True)
    envelope = {"schema_version": 1, "content": content,
                "token_usage": {"total_tokens": 11}}
    Path(response_path).write_text(json.dumps(envelope))
    raise SystemExit(0)
call_number = len(Path(count_path).read_text().splitlines())
if mode == "invalid_once" and call_number > 1:
    mode = "ok"
if mode in ("malformed", "invalid_once"):
    Path(response_path).write_text(json.dumps({"unexpected": True}))
    raise SystemExit(0)
request = json.loads(Path(request_path).read_text())
prompt = request["prompt"]
match = re.search(r"missing hint: (\w+)", prompt)
current = prompt.split("CURRENT PROMPT:\n", 1)[1].split("\n\nSCORE:", 1)[0]
content = current + "\n" + match.group(1) if match else current
envelope = {"schema_version": 1, "content": content,
            "token_usage": {"total_tokens": 11}}
temporary = Path(response_path).with_suffix(".tmp")
temporary.write_text(json.dumps(envelope))
os.replace(temporary, response_path)
'''


def proposer_workspace(tmp_path, name):
    root = tmp_path / name
    root.mkdir(parents=True)
    script = root / "proposer.py"
    script.write_text(PROPOSER_SCRIPT)
    count = root / "calls.txt"
    count.write_text("")
    return root, script, count


def proposer(root, script, count, store, fallback, mode="ok", time_limit=120, **kwargs):
    execution_root = root / "run"
    execution_root.mkdir(parents=True, exist_ok=True)
    execution_script = execution_root / "proposer.py"
    execution_script.write_text(script.read_text())
    return ExternalCommandLLM(
        [sys.executable, str(execution_script), mode, str(count)],
        execution_root, store, fallback_llm=fallback, time_limit=time_limit, **kwargs)


def reference_run(tmp_path):
    eval_root, eval_script = workspace(tmp_path, "reference-evaluator")
    prop_root, prop_script, count = proposer_workspace(tmp_path, "reference-proposer")
    run_dir = tmp_path / "reference-active-proposal"
    store = AppendOnlyStore(run_dir / "x1.jsonl")
    llm = proposer(prop_root, prop_script, count, store, MockLLM())
    result = Framework(llm, evaluator(eval_root, eval_script, store),
                       config(), str(run_dir)).evolve(TASK)
    return result, run_dir, count


def start_owner(run_dir, eval_root, eval_script, prop_root, prop_script, count):
    env = dict(os.environ)
    env.update(PYTHONPATH=str(PROJECT), PYTHONDONTWRITEBYTECODE="1",
               AR_TEST_SECRET="proposal-secret-canary")
    return subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "--owner", str(run_dir),
         str(eval_root), str(eval_script), str(prop_root), str(prop_script), str(count)],
        cwd=PROJECT, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def owner_main(run_dir, eval_root, eval_script, prop_root, prop_script, count):
    original_append = AppendOnlyStore.append

    def append_with_crash(self, kind, payload):
        original_append(self, kind, payload)
        if kind == "executor_process_started" \
                and payload.get("process_kind") == "m0_external_proposer":
            os.kill(os.getpid(), signal.SIGKILL)

    AppendOnlyStore.append = append_with_crash
    store = AppendOnlyStore(run_dir / "x1.jsonl")
    llm = proposer(prop_root, prop_script, count, store, MockLLM(), "delayed")
    Framework(llm, evaluator(eval_root, eval_script, store),
              config(), str(run_dir)).evolve(TASK)


def test_real_active_proposal_call_is_adopted_without_provider_retry(tmp_path):
    expected, reference_dir, reference_count = reference_run(tmp_path)
    assert len(reference_count.read_text().splitlines()) == 2

    eval_root, eval_script = workspace(tmp_path, "crash-evaluator")
    prop_root, prop_script, count = proposer_workspace(tmp_path, "crash-proposer")
    run_dir = tmp_path / "recovered-active-proposal"
    store = AppendOnlyStore(run_dir / "x1.jsonl")
    owner = start_owner(run_dir, eval_root, eval_script,
                        prop_root, prop_script, count)
    stdout, stderr = owner.communicate(timeout=25)
    assert owner.returncode == -signal.SIGKILL, (stdout, stderr)
    cohort = list(store.read("batch_cycle_started"))[0]["payload"]
    assert len(list(store.read("m0_proposal_started"))) == 1
    assert len([row for row in store.read("m0_evaluation_started")
                if row["payload"].get("cohort_id") == cohort["cohort_id"]]) == 0
    assert len([row for row in store.read("executor_process_started")
                if row["payload"].get("process_kind") == "m0_external_proposer"]) == 1
    assert not list(store.read("external_proposer_outcome"))
    assert count.read_text().splitlines() == ["call"]

    llm = proposer(prop_root, prop_script, count, store, ForbiddenLLM())
    resumed = Framework(llm, evaluator(eval_root, eval_script, store),
                        config(resume=True), str(run_dir))
    actual = resumed.evolve(TASK)
    for key in COMPARE:
        assert actual[key] == expected[key], key
    assert actual["resumed"] is True and actual["completed"] is True
    proposer_processes = [row["payload"] for row in store.read("executor_process_started")
                          if row["payload"].get("process_kind") == "m0_external_proposer"]
    evaluator_processes = [row["payload"] for row in store.read("executor_process_started")
                           if row["payload"].get("process_kind", "m0_external_evaluator")
                           == "m0_external_evaluator"]
    assert len(proposer_processes) == 2
    assert len(evaluator_processes) == 3
    assert len(list(store.read("external_proposer_outcome"))) == 2
    assert count.read_text().splitlines() == ["call", "call"]
    assert all(row["payload"]["token_usage"] == {"total_tokens": 11}
               for row in store.read("external_proposer_outcome"))
    report = list(store.read("m0_batch_recovery_adopted"))[0]["payload"]
    assert report["continued_proposal_count"] == 2
    assert report["adopted_proposal_count"] == 1
    assert report["adopted_proposal_ids"] == cohort["candidate_ids"][:1]
    assert report["new_proposal_count"] == 1
    assert report["continued_process_count"] == 2
    assert report["reexecuted"] is False
    assert resumed.inspect()["governance_pass"] is True
    assert certified_snapshot_ref(reference_dir / "checkpoint.json") == \
        certified_snapshot_ref(run_dir / "checkpoint.json")
    evidence_text = (run_dir / "x1.jsonl").read_text() + "".join(
        path.read_text() for path in (run_dir / "executor-processes").glob("*/spec.json"))
    assert "proposal-secret-canary" not in evidence_text

    counted = ("executor_process_started", "external_proposer_outcome",
               "m0_proposal_started", "m0_evaluation_started",
               "batch_execution_settled", "m0_batch_recovery_adopted")
    before = [(kind, len(list(store.read(kind)))) for kind in counted]
    completed_llm = proposer(prop_root, prop_script, count, store, ForbiddenLLM())
    completed = Framework(completed_llm, evaluator(eval_root, eval_script, store),
                          config(resume=True), str(run_dir))
    repeated = completed.evolve(TASK)
    after = [(kind, len(list(store.read(kind)))) for kind, _ in before]
    assert repeated["completed"] is True and after == before
    assert count.read_text().splitlines() == ["call", "call"]

    resumed.llm.fallback_llm = MockLLM()
    replayed = resumed.replay()
    assert resumed.inspect()["replay_certified"] is True
    for key in COMPARE:
        assert replayed[key] == expected[key], key
    assert len([row for row in store.read("executor_process_started")
                if row["payload"].get("process_kind") == "m0_external_proposer"]) == 2


def active_marker_fixture(tmp_path, name):
    """Create one safe durable prefix plus one active second proposal marker."""
    eval_root, eval_script = workspace(tmp_path, f"{name}-evaluator")
    prop_root, prop_script, count = proposer_workspace(tmp_path, f"{name}-proposer")
    run_dir = tmp_path / name
    store = AppendOnlyStore(run_dir / "x1.jsonl")
    crash_after_proposals(run_dir, eval_root, eval_script, 1)
    cohort = list(store.read("batch_cycle_started"))[0]["payload"]
    candidate = cohort["candidates"][1]
    store.append("m0_proposal_started", {
        "cohort_id": cohort["cohort_id"], "generation": candidate["created_cycle"],
        "operator": candidate["operator"], "candidate_id": candidate["id"],
        "intent": cohort["intents"][1]})
    llm = proposer(prop_root, prop_script, count, store, ForbiddenLLM())
    resumed = Framework(llm, evaluator(eval_root, eval_script, store),
                        config(resume=True), str(run_dir))
    return resumed, store, cohort, count


def test_active_proposal_with_evaluator_process_fails_before_adoption(tmp_path):
    resumed, store, cohort, count = active_marker_fixture(tmp_path, "active-with-process")
    start = list(store.read("m0_evaluation_started"))[0]["payload"]
    store.append("executor_process_started", {
        "execution_id": "foreign-active-window", "candidate_id": cohort["candidate_ids"][0],
        "attempt": 1, "process_kind": "m0_external_evaluator",
        "execution_ref": cohort["cohort_id"], "evaluation_context": start})
    with pytest.raises(RuntimeError, match="incomplete M0 proposals cannot have processes"):
        resumed.evolve(TASK)
    assert count.read_text() == ""
    assert not list(store.read("external_proposer_outcome"))
    assert not list(store.read("m0_batch_recovery_adopted"))


def test_active_proposal_with_settlement_fails_before_adoption(tmp_path):
    resumed, store, cohort, count = active_marker_fixture(tmp_path, "active-with-settlement")
    store.append("batch_execution_settled", {
        "cohort_id": cohort["cohort_id"], "candidate_id": cohort["candidate_ids"][0],
        "intent_id": cohort["intents"][0]["intent_id"], "evidence": {}})
    with pytest.raises(RuntimeError, match="partially started cohort cannot have batch settlement"):
        resumed.evolve(TASK)
    assert count.read_text() == ""
    assert not list(store.read("external_proposer_outcome"))
    assert not list(store.read("m0_batch_recovery_adopted"))


if __name__ == "__main__" and len(sys.argv) == 8 and sys.argv[1] == "--owner":
    owner_main(Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4]),
               Path(sys.argv[5]), Path(sys.argv[6]), Path(sys.argv[7]))
