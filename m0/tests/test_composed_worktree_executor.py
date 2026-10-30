"""Offline real-process worktree execution, durable adoption and producer costs."""
from __future__ import annotations

import asyncio
from dataclasses import replace
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

from core.composition.command_domain import CommandDomain
from core.composition.contracts import Proposal
from core.composition.worktree import MeasuredCommandError, WorktreeCommandExecutor
from core.executor.process_identity import process_alive, start_ticks
from core.executor.types import Candidate, EvalRequest
from core.llm import UsageError
from core.x1.store import AppendOnlyStore


PROGRAM = '''import hashlib,json,os,pathlib,runpy,sys,time
mode,delay=sys.argv[1],float(sys.argv[2])
request_path,response_path=map(pathlib.Path,sys.argv[-2:])
raw=request_path.read_bytes(); request=json.loads(raw)
root=pathlib.Path.cwd()
with (root/'invocations.txt').open('a') as f: f.write('called\\n')
time.sleep(delay)
value=runpy.run_path(str(root/request['artifact_path']))['VALUE']
if mode=='sandbox':
    import ctypes,errno,socket
    libc=ctypes.CDLL(None,use_errno=True)
    if libc.syscall(101,0,0,0,0)!=-1 or ctypes.get_errno()!=errno.EPERM: raise RuntimeError('seccomp not enforced')
    if os.environ.get('AR_TEST_SECRET') is not None: raise RuntimeError('host environment leaked')
    for path in (root/'evaluate.py', pathlib.Path(request['split_path'])):
        try: path.write_text('tamper')
        except OSError: pass
        else: raise RuntimeError('protected data is writable')
    try: (pathlib.Path(request['data_dir']).parent/'host-secret.txt').read_text()
    except OSError: pass
    else: raise RuntimeError('host file is visible')
    for split in ('dev','admission','final_audit'):
        if split==request['request']['split_id']: continue
        try: (pathlib.Path(request['data_dir'])/(split+'.json')).read_text()
        except OSError: pass
        else: raise RuntimeError('another evaluation split is visible')
if mode=='unknown':
    response_path.write_text('{}'); sys.exit(0)
binding=request['binding']
if mode=='identity': binding['candidate_id']='forged'
cost={'wall_seconds':0.0,'tokens_in':7,'tokens_out':0,'gpu_hours':0.0,'usd':0.0,'eval_count':1,'node_count':0}
if mode=='partial_cost': cost.pop('tokens_in')
contract={'binding':binding,'measured_cost_units':['token','node','eval_count'],'token_accounting':'split',
    'public':{'data':{'observed_request':request['request']},'metadata':{}},'private':{'metrics':{},'data':{}},
    'items':None,'binding_source':'producer','visibility':'full'}
result={'status':'ok','metrics':{'quality':value},'cost':cost,'fidelity':request['request']['fidelity'],
    'uncertainty':None,'text_feedback':'local command','partial_curves_ref':None,'trajectory_ref':None,
    'artifacts_ref':None,'contract':contract}
evidence={'candidate_id':request['candidate']['id'],'eval_result':result,'branch_ref':None,'executor_status':'scored',
    'attempt':1,'insight':None,'result_text':'local command'}
envelope={'schema_version':1,'operation_key':request['operation_key'],'execution_token':request['execution_token'],
    'request_sha256':'sha256:'+hashlib.sha256(raw).hexdigest(),'evidence':{'schema_version':1,'evidence':evidence}}
if mode=='token': envelope['execution_token']='wrong-token'
if mode=='edit_protected': (root/'evaluate.py').write_text('changed')
if mode=='edit_artifact': (root/request['artifact_path']).write_text('VALUE=999')
temporary=response_path.with_suffix('.tmp'); temporary.write_text(json.dumps(envelope)); os.replace(temporary,response_path)
'''


def git(repo, *args):
    return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()


def setup(root):
    repo, data = root / "repo", root / "data"
    repo.mkdir(); data.mkdir()
    git(repo, "init", "--quiet")
    git(repo, "config", "user.email", "offline@example.invalid")
    git(repo, "config", "user.name", "Local Worktree Tests")
    (repo / "evaluate.py").write_text(PROGRAM)
    (repo / "candidate.py").write_text("VALUE = 0\n")
    for name in ("dev", "admission", "final_audit"):
        (data / (name + ".json")).write_text(json.dumps({"split": name, "items": [1, 2]}))
    git(repo, "add", "-A"); git(repo, "commit", "--quiet", "-m", "base")


def components(root, mode="ok", delay=0.0, *, executor_class=WorktreeCommandExecutor, sandbox="none"):
    store = AppendOnlyStore(root / "state" / "x1.jsonl")
    domain = CommandDomain([sys.executable, "evaluate.py", mode, str(delay)], evaluator_version="local-command-v1",
        data_dir=root / "data", split_paths={name: name + ".json" for name in ("dev", "admission", "final_audit")},
        fidelities=("dev", "high", "admission", "final_audit"), time_limit=10)
    executor = executor_class(root / "repo", root / "worktrees", store,
        artifact_path="candidate.py", protected_paths=("evaluate.py",), sandbox=sandbox)
    return executor, domain, store


def inputs():
    return (Proposal(Candidate("candidate-1", hypothesis="frozen hypothesis"), "VALUE = 0.75\n"),
        EvalRequest("high", time_limit=8, budget_token=100, seed_set=[3, 5]),
        {"run_id": "run-1", "cycle": 1, "phase": "dev", "intent_id": "evaluation-1",
         "fingerprint": "sha256:" + "1" * 64, "manifest_sha256": "sha256:" + "2" * 64})


def execute(executor, domain, values=None):
    proposal, request, operation = values or inputs()
    return asyncio.run(executor.execute_bound(proposal, request, domain, operation))


def wait_file(path, timeout=10):
    deadline = time.monotonic() + timeout
    while not path.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert path.exists(), f"timed out waiting for {path}"
    return json.loads(path.read_text()) if path.suffix == ".json" else path.read_text()


def owner(root, mode, delay, pause, sandbox="none"):
    return subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--owner", str(root), mode, str(delay), pause, sandbox],
        env=dict(os.environ), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def stop(process):
    if process.poll() is None:
        process.kill()
    process.wait(timeout=5)


def test_real_worktree_executes_full_request_and_repeated_adoption_is_single_call(tmp_path):
    setup(tmp_path)
    executor, domain, store = components(tmp_path)
    evidence = execute(executor, domain)
    assert evidence.eval_result.metrics == {"quality": 0.75}
    assert evidence.eval_result.cost.tokens_in == 7
    assert evidence.eval_result.contract.public.data["observed_request"] == {
        "fidelity": "high", "time_limit": 8, "budget_token": 100, "seed_set": [3, 5],
        "resume_from": None, "split_id": "dev"}
    assert git(tmp_path / "repo", "show", evidence.branch_ref + ":candidate.py") == "VALUE = 0.75"
    assert git(tmp_path / "repo", "show", evidence.branch_ref + ":invocations.txt") == "called"
    assert ".autoresearch-command" not in git(tmp_path / "repo", "ls-tree", "-r", "--name-only", evidence.branch_ref)
    assert (tmp_path / "repo" / "candidate.py").read_text() == "VALUE = 0\n"
    fresh, fresh_domain, _ = components(tmp_path)
    assert execute(fresh, fresh_domain) == evidence
    assert len(list(store.read("worktree_process_started"))) == 1
    assert len(list(store.read("worktree_evidence"))) == 1
    fresh.cleanup(inputs()[2])
    assert not list((tmp_path / "worktrees").iterdir())
    assert execute(fresh, fresh_domain) == evidence  # durable result survives cleanup
    assert (fresh.operation_path(inputs()[2]) / "raw-response.json").is_file()


@pytest.mark.parametrize("pause,delay", [("running", 1.0), ("authorization", 0.0), ("completed", 0.0),
                                       ("committed", 0.0), ("returned", 0.0)])
def test_killed_coordinator_adopts_original_running_or_completed_call(tmp_path, pause, delay):
    setup(tmp_path)
    executor, domain, store = components(tmp_path, delay=delay)
    directory = executor.operation_path(inputs()[2])
    process = owner(tmp_path, "ok", delay, pause)
    try:
        if pause == "running":
            before = wait_file(directory / "target-authorized.json")
            assert process_alive(before["pid"], before["start_ticks"])
        else:
            wait_file(tmp_path / "owner-paused")
        supervisor = wait_file(directory / "supervisor.json")
        stop(process)
        evidence = execute(executor, domain)
        assert evidence.eval_result.metrics["quality"] == 0.75
        assert read_json(directory / "supervisor.json") == supervisor
        assert len(list(store.read("worktree_process_started"))) == 1
        assert len(list(store.read("worktree_evidence"))) == 1
        assert git(tmp_path / "repo", "show", evidence.branch_ref + ":invocations.txt") == "called"
        assert execute(*components(tmp_path, delay=delay)[:2]) == evidence
        metadata = executor.operation_metadata(inputs()[2])
        assert metadata["wall_seconds"] >= delay
        assert metadata["security_boundary"] == "trusted_local_no_sandbox"
    finally:
        stop(process)


def read_json(path):
    return json.loads(path.read_text())


@pytest.mark.parametrize("mode", ["identity", "token", "edit_protected", "edit_artifact"])
def test_rejected_real_response_preserves_known_cost_and_original_payload(tmp_path, mode):
    setup(tmp_path)
    executor, domain, store = components(tmp_path, mode)
    with pytest.raises(MeasuredCommandError) as captured:
        execute(executor, domain)
    assert captured.value.cost.tokens_in == 7
    assert set(captured.value.measured_cost_units) == {"token", "node", "eval_count"}
    assert Path(captured.value.raw_response_path).is_file()
    assert captured.value.wall_seconds > 0
    with pytest.raises((MeasuredCommandError, ValueError)):
        execute(*components(tmp_path, mode)[:2])
    assert len(list(store.read("worktree_process_started"))) == 1
    assert not list(store.read("worktree_evidence"))


@pytest.mark.parametrize("mode", ["unknown", "partial_cost"])
def test_unknown_cost_is_not_zero_and_cannot_be_retried(tmp_path, mode):
    setup(tmp_path)
    executor, domain, store = components(tmp_path, mode)
    for _ in range(2):
        with pytest.raises(UsageError, match="cost meter"):
            execute(executor, domain)
    assert len(list(store.read("worktree_process_started"))) == 1
    assert not list(store.read("worktree_evidence"))


@pytest.mark.parametrize("change", ["candidate", "artifact", "request", "manifest", "fingerprint"])
def test_same_budget_operation_refuses_changed_context_before_another_call(tmp_path, change):
    setup(tmp_path)
    executor, domain, store = components(tmp_path)
    execute(executor, domain)
    proposal, request, operation = inputs()
    if change == "candidate": proposal = replace(proposal, candidate=Candidate("another"))
    if change == "artifact": proposal = replace(proposal, artifact="VALUE=0.1")
    if change == "request": request = replace(request, seed_set=[7])
    if change == "manifest": operation["manifest_sha256"] = "sha256:" + "3" * 64
    if change == "fingerprint": operation["fingerprint"] = "sha256:" + "4" * 64
    with pytest.raises(ValueError, match="binding changed"):
        execute(executor, domain, (proposal, request, operation))
    assert len(list(store.read("worktree_process_started"))) == 1


def test_dataset_drift_and_unsupported_request_reject_before_any_process(tmp_path):
    setup(tmp_path)
    executor, domain, store = components(tmp_path)
    proposal, request, operation = inputs()
    with pytest.raises(ValueError, match="unsupported"):
        execute(executor, domain, (proposal, replace(request, fidelity="unavailable"), operation))
    (tmp_path / "data" / "dev.json").write_text("changed")
    with pytest.raises(ValueError, match="dataset content changed"):
        execute(executor, domain)
    assert not list(store.read())


def test_path_executable_is_resolved_and_frozen_before_any_run(tmp_path, monkeypatch):
    import shutil
    setup(tmp_path)
    binary_dir = tmp_path / "bin"; binary_dir.mkdir()
    selected = binary_dir / "selected-python"
    selected.symlink_to(sys.executable)
    monkeypatch.setenv("PATH", str(binary_dir) + os.pathsep + os.environ.get("PATH", ""))
    domain = CommandDomain(["selected-python", "evaluate.py", "ok", "0.0"], evaluator_version="path-v1",
        data_dir=tmp_path / "data", split_paths={"dev": "dev.json"}, fidelities=("high",))
    assert domain.command[0] == str(selected)
    assert str(selected) in domain.manifest_binding["command_files"]
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    assert domain.command[0] == str(selected)
    domain.validate_context()
    selected.unlink(); selected.write_text("replacement")
    with pytest.raises(ValueError, match="executable or script content changed"):
        domain.validate_context()


def test_relative_evaluator_script_requires_protection_or_candidate_binding(tmp_path):
    setup(tmp_path)
    executor, domain, store = components(tmp_path)
    unprotected = WorktreeCommandExecutor(tmp_path / "repo", tmp_path / "other-worktrees", store,
        artifact_path="candidate.py", sandbox="none")
    with pytest.raises(ValueError, match="protected base file"):
        unprotected.validate_domain(domain)
    assert not list(store.read())


def test_heldout_data_inside_base_repository_is_rejected_before_worktree_materialization(tmp_path):
    setup(tmp_path)
    repo = tmp_path / "repo"
    (repo / "heldout.json").write_text('{"answers": [1, 2]}')
    git(repo, "add", "heldout.json"); git(repo, "commit", "--quiet", "-m", "unsafe embedded data")
    executor, _, store = components(tmp_path)
    domain = CommandDomain([sys.executable, "evaluate.py", "ok", "0.0"], evaluator_version="embedded-v1",
        data_dir=repo, split_paths={"dev": "heldout.json"}, fidelities=("high",))
    with pytest.raises(ValueError, match="outside the candidate base repository"):
        executor.validate_domain(domain)
    assert not list(store.read()) and not list((tmp_path / "worktrees").iterdir())


def test_artifact_snapshot_never_runs_host_git_clean_filters(tmp_path):
    setup(tmp_path)
    repo = tmp_path / "repo"
    marker = tmp_path / "filter-was-run"
    (repo / ".gitattributes").write_text("candidate.py filter=unexpected\n")
    git(repo, "add", ".gitattributes"); git(repo, "commit", "--quiet", "-m", "attributes")
    git(repo, "config", "filter.unexpected.clean", "touch " + str(marker))
    git(repo, "config", "filter.unexpected.smudge", "touch " + str(marker))
    git(repo, "config", "filter.unexpected.required", "true")
    executor, domain, _ = components(tmp_path)
    result = execute(executor, domain)
    assert result.eval_result.metrics["quality"] == 0.75
    assert not marker.exists()
    assert git(repo, "show", result.branch_ref + ":candidate.py") == "VALUE = 0.75"


def test_native_process_start_identity_and_pid_reuse_guard():
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(5)"], start_new_session=True)
    try:
        ticks = start_ticks(child.pid)
        assert type(ticks) is int
        assert process_alive(child.pid, ticks)
        assert not process_alive(child.pid, ticks + 1)
    finally:
        stop(child)
    assert not process_alive(child.pid, ticks)


@pytest.mark.parametrize("case", ["spec", "supervisor", "target", "completion", "commit_ref", "worktree"])
def test_tampered_durable_identity_or_response_is_never_adopted(tmp_path, case):
    from core.composition.command_domain import digest
    setup(tmp_path)
    executor, domain, store = components(tmp_path)
    evidence = execute(executor, domain)
    directory = executor.operation_path(inputs()[2])
    if case == "spec":
        spec = read_json(directory / "spec.json")
        spec["spec"]["args"] = ["/bin/echo", "replacement"]
        spec["spec_sha256"] = digest(spec["spec"])
        (directory / "spec.json").write_text(json.dumps(spec))
        launch = read_json(directory / "launch.json"); launch["spec_sha256"] = spec["spec_sha256"]
        (directory / "launch.json").write_text(json.dumps(launch))
    elif case in {"supervisor", "target"}:
        path = directory / (case + ".json")
        identity = read_json(path); identity["start_ticks"] += 1
        path.write_text(json.dumps(identity))
    elif case == "completion":
        path = directory / "completion.json"
        saved = read_json(path); saved["evidence"]["evidence"]["eval_result"]["metrics"]["quality"] = 999
        path.write_text(json.dumps(saved))
    elif case == "commit_ref":
        path = directory / "completion.json"
        saved = read_json(path); saved["evidence"]["evidence"]["branch_ref"] = git(tmp_path / "repo", "rev-parse", "HEAD")
        path.write_text(json.dumps(saved))
        path = directory / "artifact-commit.json"
        commit = read_json(path); commit["head"] = saved["evidence"]["evidence"]["branch_ref"]
        path.write_text(json.dumps(commit))
    else:
        path = directory / "operation.json"
        saved = read_json(path); saved["worktree_path"] = str(tmp_path / "other")
        path.write_text(json.dumps(saved))
    with pytest.raises((ValueError, UsageError, MeasuredCommandError)):
        execute(*components(tmp_path)[:2])
    assert git(tmp_path / "repo", "show", evidence.branch_ref + ":invocations.txt") == "called"
    assert len(list(store.read("worktree_process_started"))) == 1


def test_concurrent_coordinator_cannot_repeat_or_steal_an_owned_operation(tmp_path):
    setup(tmp_path)
    executor, domain, store = components(tmp_path, delay=0.5)
    directory = executor.operation_path(inputs()[2])
    process = owner(tmp_path, "ok", 0.5, "authorization")
    try:
        wait_file(tmp_path / "owner-paused")
        with pytest.raises(RuntimeError, match="another coordinator"):
            execute(executor, domain)
        assert not (directory / "target.json").exists()
        stop(process)
        assert execute(executor, domain).eval_result.metrics["quality"] == 0.75
        assert len(list(store.read("worktree_process_started"))) == 1
    finally:
        stop(process)


def test_identical_dataset_contents_do_not_become_different_splits_by_renaming(tmp_path):
    setup(tmp_path)
    (tmp_path / "data" / "admission.json").write_bytes((tmp_path / "data" / "dev.json").read_bytes())
    _, domain, _ = components(tmp_path)
    assert domain.evaluation_context_for(EvalRequest("dev")) == domain.evaluation_context_for(
        EvalRequest("admission", split_id="admission"))


def test_durable_launch_marker_without_popen_never_authorizes_a_replacement(tmp_path, monkeypatch):
    import core.composition.worktree as implementation
    setup(tmp_path)
    executor, domain, store = components(tmp_path)
    original = implementation.subprocess.Popen
    def interrupted(args, *positional, **kwargs):
        if len(args) > 2 and args[1] == "-I":
            raise RuntimeError("owner disappeared immediately before Popen")
        return original(args, *positional, **kwargs)
    monkeypatch.setattr(implementation.subprocess, "Popen", interrupted)
    with pytest.raises(RuntimeError, match="immediately before"):
        execute(executor, domain)
    directory = executor.operation_path(inputs()[2])
    assert (directory / "launch.json").exists()
    assert not (directory / "supervisor.json").exists()
    # Shorten only this deterministic wait; never replace the original launch.
    executor._identity_wait_seconds = 0
    with pytest.raises(UsageError, match="refusing replacement"):
        executor._execute(*inputs()[:2], domain, inputs()[2])
    assert len(list(store.read("worktree_launch_intent"))) == 1


def test_frozen_security_spec_rejection_stops_only_bound_supervisor(tmp_path):
    from core.composition.command_domain import digest
    setup(tmp_path)
    executor, domain, store = components(tmp_path)
    directory = executor.operation_path(inputs()[2])
    process = owner(tmp_path, "ok", 0.0, "authorization")
    try:
        wait_file(tmp_path / "owner-paused")
        identity = wait_file(directory / "supervisor.json")
        stop(process)
        spec = read_json(directory / "spec.json")
        spec["spec"]["args"] = ["/bin/echo", "changed"]
        spec["spec_sha256"] = digest(spec["spec"])
        (directory / "spec.json").write_text(json.dumps(spec))
        with pytest.raises(UsageError, match="security specification"):
            execute(executor, domain)
        deadline = time.monotonic() + 5
        while process_alive(identity["pid"], identity["start_ticks"]) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert not process_alive(identity["pid"], identity["start_ticks"])
        assert not (directory / "target.json").exists()
    finally:
        stop(process)


def test_missing_supervisor_result_kills_only_recorded_target_and_remains_unknown(tmp_path):
    setup(tmp_path)
    executor, domain, store = components(tmp_path, delay=5.0)
    directory = executor.operation_path(inputs()[2])
    process = owner(tmp_path, "ok", 5.0, "running")
    try:
        target = wait_file(directory / "target-authorized.json")
        supervisor = wait_file(directory / "supervisor.json")
        stop(process)
        os.kill(supervisor["pid"], signal.SIGKILL)
        deadline = time.monotonic() + 5
        while process_alive(supervisor["pid"], supervisor["start_ticks"]) and time.monotonic() < deadline:
            time.sleep(0.02)
        with pytest.raises(UsageError, match="without a durable result"):
            execute(executor, domain)
        deadline = time.monotonic() + 5
        while process_alive(target["pid"], target["start_ticks"]) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert not process_alive(target["pid"], target["start_ticks"])
        assert len(list(store.read("worktree_process_started"))) == 1
    finally:
        stop(process)


@pytest.mark.linux
def test_linux_real_bubblewrap_seccomp_worktree_execution(tmp_path, monkeypatch):
    setup(tmp_path)
    (tmp_path / "host-secret.txt").write_text("host canary")
    monkeypatch.setenv("AR_TEST_SECRET", "must not be inherited")
    executor, domain, store = components(tmp_path, "sandbox", sandbox="bubblewrap")
    evidence = execute(executor, domain)
    assert evidence.eval_result.metrics["quality"] == 0.75
    assert executor.manifest_binding["security_boundary"] == "linux_bubblewrap_seccomp"
    spec = read_json(executor.operation_path(inputs()[2]) / "spec.json")["spec"]
    assert spec["seccomp_policy"] and spec["seccomp_delivery"] == "bwrap_memfd"


@pytest.mark.linux
def test_linux_sandbox_owner_crash_adopts_original_filtered_process(tmp_path):
    setup(tmp_path)
    executor, domain, store = components(tmp_path, "sandbox", 0.5, sandbox="bubblewrap")
    directory = executor.operation_path(inputs()[2])
    process = owner(tmp_path, "sandbox", 0.5, "running", "bubblewrap")
    try:
        target = wait_file(directory / "target-authorized.json")
        stop(process)
        evidence = execute(executor, domain)
        assert evidence.eval_result.metrics["quality"] == 0.75
        assert read_json(directory / "target.json") == target
        assert len(list(store.read("worktree_process_started"))) == 1
        assert executor.operation_metadata(inputs()[2])["security_boundary"] == "linux_bubblewrap_seccomp"
    finally:
        stop(process)


def owner_main(root, mode, delay, pause, sandbox):
    class Pausing(WorktreeCommandExecutor):
        def _event_once(self, kind, key, payload):
            super()._event_once(kind, key, payload)
            if pause == "authorization" and kind == "worktree_process_started":
                (root / "owner-paused").write_text("before authorization")
                time.sleep(60)
        def _complete(self, *args):
            if pause == "completed":
                (root / "owner-paused").write_text("durable process completion")
                time.sleep(60)
            return super()._complete(*args)
        def _commit(self, *args):
            result = super()._commit(*args)
            if pause == "committed":
                (root / "owner-paused").write_text("artifact committed before evidence")
                time.sleep(60)
            return result
    executor, domain, _ = components(root, mode, delay, executor_class=Pausing, sandbox=sandbox)
    execute(executor, domain)
    if pause == "returned":
        (root / "owner-paused").write_text("durable evidence")
        time.sleep(60)


if __name__ == "__main__" and sys.argv[1] == "--owner":
    owner_main(Path(sys.argv[2]), sys.argv[3], float(sys.argv[4]), sys.argv[5], sys.argv[6])
