"""Durable continuation must consume evidence, never invent a paid retry."""
import json
import multiprocessing

import pytest

from core.composition.provider import MeteredProvider
from core.composition.recovery import ContinuationStore, coordinator_lock
from core.llm import UsageError
from core.x1.checkpoint import RunCheckpoint


def base(tmp_path):
    store = ContinuationStore(tmp_path / "events.jsonl")
    checkpoint = RunCheckpoint.create({"git_state": {}, "inflight_executor": [], "messages": []})
    store.append("composed_checkpoint", {"sha256": checkpoint.payload_sha256})
    return store, checkpoint


def resumed(store, checkpoint):
    result = ContinuationStore(store.path, checkpoint)
    result.resume()
    return result


def test_prefix_restore_hides_uncommitted_budget_and_admission_events(tmp_path):
    store, checkpoint = base(tmp_path)
    store.append("budget", {"charge": 4})
    store.append("admission", {"selected": "candidate"})
    restored = ContinuationStore(store.path, checkpoint)
    assert list(restored.read("budget")) == []
    assert list(restored.read("admission")) == []
    restored.resume()
    before = store.path.read_bytes()
    restored.append("budget", {"charge": 4})
    restored.append("admission", {"selected": "candidate"})
    assert store.path.read_bytes() == before
    assert len(list(restored.read("budget"))) == 1
    restored.append("next", {})
    assert len(list(restored.read("next"))) == 1


@pytest.mark.parametrize("kind,payload", [("wrong", {"charge": 4}), ("budget", {"charge": 0})])
def test_divergent_recovery_cannot_append_or_erase_prior_charges(tmp_path, kind, payload):
    store, checkpoint = base(tmp_path)
    store.append("budget", {"charge": 4})
    restored = resumed(store, checkpoint)
    before = store.path.read_bytes()
    with pytest.raises(ValueError, match="diverged"):
        restored.append(kind, payload)
    assert store.path.read_bytes() == before


class Provider:
    def __init__(self):
        self.paid_calls, self.index = 0, 0

    def __call__(self, prompt):
        self.paid_calls += 1
        self.index += 1
        self.last_usage = {"total_tokens": 7}
        return prompt + str(self.index)

    def checkpoint_state(self):
        return {"index": self.index}

    def restore_state(self, state):
        self.index = state["index"]


def test_provider_completion_restores_state_and_actual_usage_without_paid_retry(tmp_path):
    store, checkpoint = base(tmp_path)
    original = MeteredProvider(Provider())
    original.durable_store = store
    assert original("draft") == "draft1"
    provider = MeteredProvider(Provider())
    provider.durable_store = resumed(store, checkpoint)
    assert provider("draft") == "draft1"
    assert provider.raw_provider.paid_calls == 0
    assert provider.usage_total == 7
    assert provider("next") == "next2"
    assert provider.raw_provider.paid_calls == 1
    assert provider.usage_total == 14


def test_provider_crash_between_start_and_completion_remains_unknown(tmp_path):
    store, checkpoint = base(tmp_path)
    class Crashed(Provider):
        def __call__(self, prompt):
            raise SystemExit("owner died before receiving usage")
    provider = MeteredProvider(Crashed())
    provider.durable_store = store
    with pytest.raises((SystemExit, UsageError)):
        provider("draft")
    recovered = MeteredProvider(Provider())
    recovered.durable_store = resumed(store, checkpoint)
    before = store.path.read_bytes()
    with pytest.raises(UsageError, match="refusing paid retry"):
        recovered("draft")
    assert recovered.raw_provider.paid_calls == 0
    assert store.path.read_bytes() == before


def test_changed_provider_prompt_is_rejected_before_provider_invocation(tmp_path):
    store, checkpoint = base(tmp_path)
    provider = MeteredProvider(Provider())
    provider.durable_store = store
    provider("first")
    fresh = MeteredProvider(Provider())
    fresh.durable_store = resumed(store, checkpoint)
    with pytest.raises(ValueError, match="diverged"):
        fresh("different")
    assert fresh.raw_provider.paid_calls == 0


def test_measured_walltime_reuses_exact_previous_value(tmp_path):
    store, checkpoint = base(tmp_path)
    assert store.measurement({"intent": "one"}, 2.75) == 2.75
    restored = resumed(store, checkpoint)
    assert restored.measurement({"intent": "one"}, 900) == 2.75


def test_changed_measurement_identity_is_not_treated_as_cached_usage(tmp_path):
    store, checkpoint = base(tmp_path)
    store.measurement({"intent": "one", "tokens": 8}, 2.75)
    restored = resumed(store, checkpoint)
    with pytest.raises(ValueError, match="measurement differs"):
        restored.measurement({"intent": "one", "tokens": 0}, 0)


@pytest.mark.parametrize("elapsed", [-1, float("nan"), float("inf"), True])
def test_invalid_wall_measurements_remain_unknown(tmp_path, elapsed):
    store, _ = base(tmp_path)
    before = store.path.read_bytes()
    with pytest.raises(UsageError, match="wall-time"):
        store.measurement({"intent": "one"}, elapsed)
    assert store.path.read_bytes() == before


def test_external_operation_rows_visible_to_their_validator_and_not_duplicated(tmp_path):
    store, checkpoint = base(tmp_path)
    store.append("budget_start", {"id": "one"})
    store.append("worktree_launch_intent", {"token": "immutable"})
    restored = resumed(store, checkpoint)
    assert list(restored.read("worktree_launch_intent"))[0]["payload"]["token"] == "immutable"
    restored.append("budget_start", {"id": "one"})
    assert restored.peek() is None
    assert len([row for row in map(json.loads, store.path.read_text().splitlines())
                if row["kind"] == "worktree_launch_intent"]) == 1


def attempt_lock(root, queue):
    try:
        with coordinator_lock(root):
            queue.put("acquired")
    except RuntimeError:
        queue.put("blocked")


def test_second_coordinator_cannot_restore_or_dispatch_concurrently(tmp_path):
    context = multiprocessing.get_context("spawn")
    queue = context.Queue()
    with coordinator_lock(tmp_path):
        process = context.Process(target=attempt_lock, args=(str(tmp_path), queue))
        process.start()
        assert queue.get(timeout=10) == "blocked"
        process.join(10)
        assert process.exitcode == 0
    with coordinator_lock(tmp_path):
        pass


def test_checkpoint_must_have_a_durable_journal_boundary(tmp_path):
    store, checkpoint = base(tmp_path)
    bad = RunCheckpoint.create({**checkpoint.payload, "extra": True})
    with pytest.raises(ValueError, match="no durable journal boundary"):
        ContinuationStore(store.path, bad)


def test_interrupted_local_wall_charge_is_not_replaced_with_recovery_duration(tmp_path, monkeypatch):
    from core.composition.hierarchical_runtime import HierarchicalRuntime
    from test_composed_worktree_framework import prepare, framework, provider_calls, rows, TASK
    prepare(tmp_path)
    original = HierarchicalRuntime._settle_physical
    def crash(self, receipt, cost, coverage, elapsed, **kwargs):
        if kwargs.get("operator"):
            raise SystemExit("lost local duration before persisting measurement")
        return original(self, receipt, cost, coverage, elapsed, **kwargs)
    monkeypatch.setattr(HierarchicalRuntime, "_settle_physical", crash)
    with pytest.raises(SystemExit):
        framework(tmp_path, generations=0, physical_wall=True).evolve(TASK)
    assert len(provider_calls(tmp_path)) == 1
    monkeypatch.setattr(HierarchicalRuntime, "_settle_physical", original)
    with pytest.raises(UsageError, match="no durable wall-time"):
        framework(tmp_path, generations=0, physical_wall=True, resume=True).evolve(TASK)
    assert len(provider_calls(tmp_path)) == 1
    events = rows(tmp_path, "hierarchical_budget")
    assert events[-1]["event"] == "unresolved"
    assert not rows(tmp_path, "worktree_launch_intent")


def test_command_cannot_override_supervisor_walltime_with_a_zero_producer_meter(tmp_path):
    from test_composed_worktree_framework import prepare, profile, framework, rows, used, TASK, git
    prepare(tmp_path)
    script = tmp_path / "repo" / "evaluate.py"
    script.write_text(script.read_text().replace("['token','node','eval_count']",
                                               "['token','node','eval_count','wallclock']"))
    git(tmp_path / "repo", "add", "evaluate.py")
    git(tmp_path / "repo", "commit", "--quiet", "-m", "explicit zero producer wall meter")
    assembly = profile(tmp_path, delay=0.15, layered=False, physical_wall=True)
    assembly["domain"]["options"]["measured_cost_units"].append("wallclock")
    result = framework(tmp_path, generations=0, assembly=assembly).evolve(TASK)
    actual = rows(tmp_path, "worktree_process_completed")[0]["wall_seconds"]
    assert actual >= 0.15
    assert used(result)["wallclock"] >= actual
    assert rows(tmp_path, "composed_evidence")[0]["evidence"]["eval_result"]["cost"]["wall_seconds"] == 0
