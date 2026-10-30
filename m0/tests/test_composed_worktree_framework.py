"""The real Framework entry point owns worktree calls, budgets and crash adoption."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.composition.defaults import composed_profile
from core.composition.worktree import MeasuredCommandError, WorktreeCommandExecutor
from core.llm import UsageError
from core.loop import Framework, LoopConfig
from core.x1.store import AppendOnlyStore
from test_composed_budget import options as budget_options
from test_composed_worktree_executor import PROGRAM, git, setup, stop


TASK = "Improve the executable candidate while retaining real worktree provenance"


class LocalProvider:
    model = "worktree-local-provider-v1"
    supplier = "offline-simulation"

    def __init__(self, root):
        self.root, self.calls, self.generation_index = Path(root), 0, 0

    def __call__(self, prompt):
        self.calls += 1
        self.generation_index += 1
        self.last_usage = {"total_tokens": 5}
        with (self.root / "provider-calls.jsonl").open("a") as stream:
            stream.write(json.dumps({"generation": self.generation_index,
                "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest()}) + "\n")
            stream.flush(); os.fsync(stream.fileno())
        return "VALUE = " + str(0.4 + self.generation_index * 0.1) + "\n"

    def checkpoint_state(self):
        return {"generation_index": self.generation_index}

    def restore_state(self, value):
        self.generation_index = value["generation_index"]


def prepare(root):
    setup(root)
    program = PROGRAM.replace("'quality'", "('calibration/quality' if request['request']['split_id']=='calibration' else 'dev/score')")
    program = program.replace("'private':{'metrics':{},'data':{}}",
        "'private':{'metrics':{},'data':{'secret':'PRIVATE_'+request['request']['split_id']}}")
    (root / "repo" / "evaluate.py").write_text(program)
    git(root / "repo", "add", "evaluate.py")
    git(root / "repo", "commit", "--quiet", "-m", "canonical framework fixture")
    (root / "data" / "calibration.json").write_text('{"split":"calibration","items":[3,4]}')


def profile(root, *, mode="ok", delay=0.0, layered=True, physical_wall=False, proxy=False):
    result = composed_profile(name="worktree-framework-local")
    result["domain"] = {"name": "command", "options": {
        "command": [sys.executable, "evaluate.py", mode, str(delay)],
        "evaluator_version": "framework-command-v1", "data_dir": str(root / "data"),
        "split_paths": {name: name + ".json" for name in ("dev", "admission", "final_audit")},
        "fidelities": ["dev", "high", "admission", "final_audit"],
        "measured_cost_units": ["token", "node", "eval_count"], "time_limit": 10}}
    result["executor"] = {"name": "git_worktree", "options": {
        "base_repo": str(root / "repo"), "run_root": str(root / "worktrees"),
        "artifact_path": "candidate.py", "protected_paths": ["evaluate.py"], "sandbox": "none"}}
    if layered:
        result["admission"] = {"name": "layered", "options": {"call_budget": 10,
            "admission_seeds": [3, 5], "final_seeds": [11]}}
    units = {"token": 10, "node": 0, "eval_count": 1}
    if physical_wall:
        units["wallclock"] = 10.0
    result["budget"] = {"name": "hierarchical", "options": budget_options(units=units)}
    if proxy:
        result["domain"]["options"]["split_paths"]["calibration"] = "calibration.json"
        result["budget"]["options"]["proxy_validity"] = {"every_n_cycles": 1,
            "anchor_request": {"fidelity": "high", "split_id": "calibration", "seed_set": [7, 19]},
            "proxy_metric": "dev/score", "true_metric": "calibration/quality",
            "proxy_direction": "maximize", "true_direction": "maximize",
            "min_pairs": 3, "window": 4, "min_rank_correlation": 0.5}
    return result


def framework(root, *, provider=None, mode="ok", delay=0.0, generations=1, resume=False, stop_after=None,
              layered=True, physical_wall=False, assembly=None):
    cfg = LoopConfig(max_generations=generations, total_budget=100_000, intent_cost=2_000,
        reeval_floor=0, baseline_every=2, resume_from_checkpoint=resume, stop_after_generation=stop_after)
    return Framework.from_profile(assembly or profile(root, mode=mode, delay=delay,
        layered=layered, physical_wall=physical_wall), provider or LocalProvider(root), None, cfg, str(root / "run"))


def rows(root, kind):
    return [record["payload"] for record in AppendOnlyStore(root / "run" / "x1.jsonl").read(kind)]


def provider_calls(root):
    path = root / "provider-calls.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def used(result):
    return result["ledger"]["global"]["used"]


def assert_closed(result):
    assert not result["ledger"]["open_intents"]
    assert not any(result["ledger"]["global"]["reserved"].values())


def test_configured_framework_executes_real_worktrees_and_settles_dev_gate_final_once(tmp_path):
    prepare(tmp_path)
    provider = LocalProvider(tmp_path)
    fw = framework(tmp_path, provider=provider)
    result = fw.evolve(TASK)
    assert result["cycles"] == provider.calls == 2
    assert used(result) == {"token": 45, "node": 2, "eval_count": 5}
    assert_closed(result)
    assert result["reporting"]["gate_calls"] == 2
    assert result["reporting"]["final_audit"]["calls"] == 1
    assert len(rows(tmp_path, "worktree_process_started")) == len(rows(tmp_path, "worktree_evidence")) == 5
    assert len(rows(tmp_path, "layered_admission_receipt")) == 2
    assert fw._composed.parts["executor"].manifest_binding["security_boundary"] == "trusted_local_no_sandbox"
    for row in rows(tmp_path, "worktree_evidence"):
        evidence = row["evidence"]["evidence"]
        branch = evidence["branch_ref"]
        assert git(tmp_path / "repo", "show", branch + ":candidate.py").startswith("VALUE = 0.")
        assert git(tmp_path / "repo", "show", branch + ":invocations.txt") == "called"
        assert ".autoresearch-command" not in git(tmp_path / "repo", "ls-tree", "-r", "--name-only", branch)
        assert git(tmp_path / "repo", "show", branch + ":evaluate.py") == (tmp_path / "repo" / "evaluate.py").read_text().strip()
    assert (tmp_path / "repo" / "candidate.py").read_text() == "VALUE = 0\n"
    assert len(list((tmp_path / "run" / "worktree-operations").glob("*/raw-response.json"))) == 5


def test_completed_framework_resume_is_a_zero_call_zero_charge_noop(tmp_path):
    prepare(tmp_path)
    result = framework(tmp_path).evolve(TASK)
    before_calls = rows(tmp_path, "worktree_process_started")
    before_provider = provider_calls(tmp_path)
    fresh = LocalProvider(tmp_path)
    resumed = framework(tmp_path, provider=fresh, resume=True)
    assert resumed.evolve(TASK) == result
    assert fresh.calls == 0
    assert rows(tmp_path, "worktree_process_started") == before_calls
    assert provider_calls(tmp_path) == before_provider
    assert used(resumed.inspect()) == used(result)


def test_cycle_boundary_resume_only_runs_new_candidate_and_one_final_audit(tmp_path):
    prepare(tmp_path)
    partial = framework(tmp_path, stop_after=0).evolve(TASK)
    assert used(partial) == {"token": 19, "node": 1, "eval_count": 2}
    assert partial["reporting"]["final_audit"]["state"] == "not_frozen"
    fresh = LocalProvider(tmp_path)
    complete = framework(tmp_path, provider=fresh, resume=True).evolve(TASK)
    assert fresh.calls == 1
    assert used(complete) == {"token": 45, "node": 2, "eval_count": 5}
    assert len(rows(tmp_path, "worktree_process_started")) == 5
    assert_closed(complete)


def wait_operation(root, split, *, result=False, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for path in (root / "run" / "worktree-operations").glob("*/operation.json"):
            record = json.loads(path.read_text())
            if record["binding"]["request"]["split_id"] != split:
                continue
            sidecar = path.parent / ("process-result.json" if result else "target-authorized.json")
            if sidecar.exists():
                return path.parent, record, json.loads(sidecar.read_text())
        time.sleep(0.02)
    raise AssertionError("configured owner never reached the requested physical invocation")


def start_owner(root, split, pause, *, resume=False):
    return subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--owner", str(root), split, pause,
                             "resume" if resume else "fresh"],
        env=dict(os.environ), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


@pytest.mark.parametrize("split", ["dev", "calibration", "admission", "final_audit"])
@pytest.mark.parametrize("pause", ["running", "completed"])
def test_owner_sigkill_adopts_same_framework_operation_without_provider_or_evaluation_repayment(tmp_path, split, pause):
    prepare(tmp_path)
    owner = start_owner(tmp_path, split, pause)
    try:
        directory, operation, original = wait_operation(tmp_path, split, result=pause == "completed")
        if pause == "completed":
            deadline = time.monotonic() + 5
            while not (tmp_path / "owner-paused").exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            assert (tmp_path / "owner-paused").exists()
        target = json.loads((directory / "target.json").read_text())
        stop(owner)
        fresh = LocalProvider(tmp_path)
        assembly = profile(tmp_path, delay=0.5, proxy=split == "calibration")
        result = framework(tmp_path, provider=fresh, generations=0, delay=0.5, resume=True, assembly=assembly).evolve(TASK)
        assert fresh.calls == 0
        assert len(provider_calls(tmp_path)) == 1
        evaluations = 4 if split == "calibration" else 3
        assert used(result) == {"token": 5 + 7 * evaluations, "node": 1, "eval_count": evaluations}
        assert len(rows(tmp_path, "worktree_process_started")) == evaluations
        assert json.loads((directory / "target.json").read_text()) == target
        assert json.loads((directory / "operation.json").read_text()) == operation
        assert result["reporting"]["gate_calls"] == result["reporting"]["final_audit"]["calls"] == 1
        assert_closed(result)
        assert framework(tmp_path, generations=0, delay=0.5, resume=True, assembly=assembly).evolve(TASK) == result
        assert len(rows(tmp_path, "worktree_process_started")) == evaluations
        if split == "calibration":
            assert result["proxy_validity"]["valid_pairs"] == 1
            assert len(rows(tmp_path, "composed_anchor")) == 1
    finally:
        stop(owner)


def test_unknown_external_meter_remains_reserved_and_resume_does_not_launch_replacement(tmp_path):
    prepare(tmp_path)
    fw = framework(tmp_path, mode="unknown", generations=0)
    with pytest.raises(UsageError):
        fw.evolve(TASK)
    ledger = fw._composed.budget.state()
    assert ledger["global"]["used"] == {"token": 5, "node": 1, "eval_count": 0}
    assert ledger["open_intents"] and ledger["global"]["reserved"]["token"] == 10
    fresh = LocalProvider(tmp_path)
    with pytest.raises((UsageError, ValueError, RuntimeError)):
        framework(tmp_path, provider=fresh, mode="unknown", generations=0, resume=True).evolve(TASK)
    assert fresh.calls == 0 and len(provider_calls(tmp_path)) == 1
    assert len(rows(tmp_path, "worktree_process_started")) == 1


@pytest.mark.parametrize("mode", ["identity", "edit_protected"])
def test_known_command_rejection_is_charged_before_validation_stops_admission(tmp_path, mode):
    prepare(tmp_path)
    fw = framework(tmp_path, mode=mode, generations=0)
    with pytest.raises(MeasuredCommandError):
        fw.evolve(TASK)
    ledger = fw._composed.budget.state()
    assert ledger["global"]["used"] == {"token": 12, "node": 1, "eval_count": 1}
    assert not ledger["open_intents"]
    assert not rows(tmp_path, "composed_decision")
    assert not rows(tmp_path, "layered_admission_receipt")
    assert len(rows(tmp_path, "worktree_process_started")) == 1


def test_dataset_drift_on_resume_rejects_before_any_new_paid_call(tmp_path):
    prepare(tmp_path)
    framework(tmp_path, stop_after=0).evolve(TASK)
    count = len(rows(tmp_path, "worktree_process_started"))
    (tmp_path / "data" / "admission.json").write_text('{"different": true}')
    fresh = LocalProvider(tmp_path)
    with pytest.raises(ValueError, match="manifest|context|incompatible"):
        framework(tmp_path, provider=fresh, resume=True).evolve(TASK)
    assert fresh.calls == 0 and len(rows(tmp_path, "worktree_process_started")) == count


def test_command_domain_with_inprocess_executor_is_rejected_before_provider_or_budget_start(tmp_path):
    prepare(tmp_path)
    assembly = profile(tmp_path)
    assembly["executor"] = {"name": "inprocess"}
    provider = LocalProvider(tmp_path)
    with pytest.raises(ValueError, match="executor|worktree|command"):
        framework(tmp_path, provider=provider, assembly=assembly).evolve(TASK)
    assert provider.calls == 0 and not rows(tmp_path, "worktree_process_started")
    assert not rows(tmp_path, "hierarchical_budget")


def wait_pause(root, owner, timeout=15):
    deadline = time.monotonic() + timeout
    while not (root / "owner-paused").exists() and time.monotonic() < deadline:
        if owner.poll() is not None:
            raise AssertionError("owner exited before pause: " + owner.stderr.read()[-3000:])
        time.sleep(0.02)
    assert (root / "owner-paused").exists()


@pytest.mark.parametrize("pause", ["mutation_before_journal", "mutation_after_journal"])
def test_state_mutation_interruption_rebuilds_once_without_repeating_paid_operations(tmp_path, pause):
    prepare(tmp_path)
    owner = start_owner(tmp_path, "dev", pause)
    try:
        wait_pause(tmp_path, owner)
        assert len(rows(tmp_path, "worktree_process_started")) == 2
        stop(owner)
        provider = LocalProvider(tmp_path)
        fw = framework(tmp_path, provider=provider, generations=0, delay=0.5, resume=True)
        result = fw.evolve(TASK)
        assert provider.calls == 0 and len(provider_calls(tmp_path)) == 1
        assert used(result) == {"token": 26, "node": 1, "eval_count": 3}
        assert len(rows(tmp_path, "worktree_process_started")) == 3
        assert len(rows(tmp_path, "composed_decision")) == len(rows(tmp_path, "layered_admission_receipt")) == 1
        assert len(fw._composed.frontier.nodes) == len(fw._composed.memory.entries) == 1
        additions = [row for row in rows(tmp_path, "state_mutation") if row["op"] == "add_node"]
        assert len(additions) == 1
        assert_closed(result)
    finally:
        stop(owner)


def test_second_coordinator_can_also_die_while_adopting_the_same_original_call(tmp_path):
    prepare(tmp_path)
    first = start_owner(tmp_path, "dev", "running")
    second = None
    try:
        directory, operation, target = wait_operation(tmp_path, "dev")
        stop(first)
        second = start_owner(tmp_path, "dev", "completed", resume=True)
        wait_pause(tmp_path, second)
        stop(second)
        provider = LocalProvider(tmp_path)
        result = framework(tmp_path, provider=provider, generations=0, delay=0.5, resume=True).evolve(TASK)
        assert provider.calls == 0 and len(provider_calls(tmp_path)) == 1
        assert used(result) == {"token": 26, "node": 1, "eval_count": 3}
        assert json.loads((directory / "operation.json").read_text()) == operation
        assert json.loads((directory / "target.json").read_text()) == target
        assert len(rows(tmp_path, "worktree_process_started")) == 3
        assert_closed(result)
    finally:
        stop(first)
        if second is not None:
            stop(second)


def test_replay_prefix_mismatch_stops_before_any_new_provider_or_command_call(tmp_path):
    prepare(tmp_path)
    owner = start_owner(tmp_path, "dev", "completed")
    try:
        wait_pause(tmp_path, owner)
        stop(owner)
        path = tmp_path / "run" / "x1.jsonl"
        transcript = [json.loads(line) for line in path.read_text().splitlines()]
        context = next(record for record in transcript if record["kind"] == "composed_context")
        context["payload"]["cycle"] = 999
        path.write_text("".join(json.dumps(record) + "\n" for record in transcript))
        provider = LocalProvider(tmp_path)
        with pytest.raises(ValueError, match="continuation diverged"):
            framework(tmp_path, provider=provider, generations=0, delay=0.5, resume=True).evolve(TASK)
        assert provider.calls == 0 and len(provider_calls(tmp_path)) == 1
        assert len(rows(tmp_path, "worktree_process_started")) == 1
    finally:
        stop(owner)


def test_checkpoint_file_written_before_boundary_event_can_resume_without_repayment(tmp_path):
    prepare(tmp_path)
    owner = start_owner(tmp_path, "dev", "checkpoint_written")
    try:
        wait_pause(tmp_path, owner)
        stop(owner)
        pending = json.loads((tmp_path / "run" / "checkpoint.pending.json").read_text())
        current = json.loads((tmp_path / "run" / "checkpoint.json").read_text())
        assert pending["payload"]["next_cycle"] == 1
        assert current["payload"]["next_cycle"] == 0
        assert rows(tmp_path, "composed_checkpoint")[-1]["sha256"] == current["payload_sha256"]
        provider = LocalProvider(tmp_path)
        result = framework(tmp_path, provider=provider, generations=0, delay=0.5, resume=True).evolve(TASK)
        assert provider.calls == 0 and len(provider_calls(tmp_path)) == 1
        assert used(result) == {"token": 26, "node": 1, "eval_count": 3}
        assert len(rows(tmp_path, "worktree_process_started")) == 3
        assert len(rows(tmp_path, "composed_decision")) == 1
        assert_closed(result)
    finally:
        stop(owner)


def test_checkpoint_boundary_before_pointer_swap_rolls_forward_without_repayment(tmp_path):
    prepare(tmp_path)
    owner = start_owner(tmp_path, "dev", "checkpoint_boundary")
    try:
        wait_pause(tmp_path, owner)
        stop(owner)
        pending = json.loads((tmp_path / "run" / "checkpoint.pending.json").read_text())
        current = json.loads((tmp_path / "run" / "checkpoint.json").read_text())
        assert pending["payload"]["next_cycle"] == 1
        assert current["payload"]["next_cycle"] == 0
        assert rows(tmp_path, "composed_checkpoint")[-1]["sha256"] == pending["payload_sha256"]
        assert len(rows(tmp_path, "worktree_process_started")) == 2
        provider = LocalProvider(tmp_path)
        fw = framework(tmp_path, provider=provider, generations=0, delay=0.5, resume=True)
        result = fw.evolve(TASK)
        assert provider.calls == 0 and len(provider_calls(tmp_path)) == 1
        assert used(result) == {"token": 26, "node": 1, "eval_count": 3}
        assert len(rows(tmp_path, "worktree_process_started")) == 3
        assert len(rows(tmp_path, "composed_decision")) == len(rows(tmp_path, "layered_admission_receipt")) == 1
        assert len(fw._composed.frontier.nodes) == len(fw._composed.memory.entries) == 1
        assert not (tmp_path / "run" / "checkpoint.pending.json").exists()
        assert_closed(result)
    finally:
        stop(owner)


def owner_main(root, split, pause, resume=False):
    if pause == "completed":
        original = WorktreeCommandExecutor._complete
        def completed(self, directory, recorded, *args):
            evidence = original(self, directory, recorded, *args)
            if recorded["binding"]["request"]["split_id"] == split:
                (root / "owner-paused").write_text("completed command, before runtime settlement")
                time.sleep(60)
            return evidence
        WorktreeCommandExecutor._complete = completed
    elif pause in {"mutation_before_journal", "mutation_after_journal"}:
        from core.state import StateApplier
        from core.policy.types import MutationOp
        name = "_apply_validated" if pause == "mutation_before_journal" else "apply"
        original = getattr(StateApplier, name)
        def paused(self, mutation):
            result = original(self, mutation)
            if mutation.op is MutationOp.ADD_NODE:
                (root / "owner-paused").write_text("state mutation " + pause)
                time.sleep(60)
            return result
        setattr(StateApplier, name, paused)
    elif pause == "checkpoint_written":
        from core.x1.checkpoint import RunCheckpoint
        original = RunCheckpoint.save
        def checkpoint_written(self, path):
            result = original(self, path)
            if Path(path).name == "checkpoint.pending.json" and self.payload["next_cycle"] > 0:
                (root / "owner-paused").write_text("checkpoint file written, journal boundary missing")
                time.sleep(60)
            return result
        RunCheckpoint.save = checkpoint_written
    elif pause == "checkpoint_boundary":
        from core.composition import recovery
        original = recovery.os.replace
        def before_pointer(source, destination):
            if (Path(source).name == "checkpoint.pending.json"
                    and Path(destination).name == "checkpoint.json"
                    and json.loads(Path(source).read_text())["payload"]["next_cycle"] > 0):
                (root / "owner-paused").write_text("durable boundary, before checkpoint pointer replacement")
                time.sleep(60)
            return original(source, destination)
        recovery.os.replace = before_pointer
    assembly = profile(root, delay=0.5, proxy=split == "calibration")
    framework(root, generations=0, delay=0.5, assembly=assembly, resume=resume).evolve(TASK)


if __name__ == "__main__" and sys.argv[1] == "--owner":
    owner_main(Path(sys.argv[2]), sys.argv[3], sys.argv[4], sys.argv[5] == "resume")
