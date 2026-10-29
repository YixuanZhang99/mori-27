"""Replay is a fresh rerun with isolated state and append-only attempt history."""
import copy
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.extensions import H2MonitorExtension
from core.loop import Framework, LoopConfig
from examples.toy_gepa import MockLLM, toy_evaluator


class StatefulLLM(MockLLM):
    def __init__(self, calls=0):
        self.calls = calls

    def __call__(self, prompt):
        self.calls += 1
        return super().__call__(prompt) + f"\ncall {self.calls}"


class StatefulEvaluator:
    def __init__(self, llm=None, calls=0):
        self.llm = llm
        self.calls = calls

    def __call__(self, candidate_id, head_sha, prompt):
        self.calls += 1
        self.last_usage = {"total_tokens": 0}
        if self.llm is not None:
            assert self.llm.calls == self.calls, "shared adapter alias lost"
        result = toy_evaluator(candidate_id, head_sha, prompt)
        result.private["evaluation_number"] = self.calls
        return result


class ResourceLLM(StatefulLLM):
    def __init__(self):
        super().__init__()
        self.lock = threading.RLock()


class BrokenLLM(StatefulLLM):
    def __call__(self, prompt):
        self.last_usage = {"total_tokens": 7}
        raise RuntimeError("offline simulated provider failure")


class AliasingLLM(StatefulLLM):
    def __deepcopy__(self, memo):
        return self


class AliasingMonitor(H2MonitorExtension):
    def __deepcopy__(self, memo):
        return self


def framework(tmp_path, *, resource=False, calls=0, extension=None):
    llm = ResourceLLM() if resource else StatefulLLM(calls)
    evaluator = StatefulEvaluator(llm, calls)
    fw = Framework(llm, evaluator,
                   LoopConfig(max_generations=3, baseline_every=2),
                   str(tmp_path / "run"), extensions=[extension] if extension else [])
    return fw


def tree_bytes(path):
    return {str(p.relative_to(path)): p.read_bytes() for p in path.rglob("*") if p.is_file()}


@pytest.mark.parametrize("initial_calls", [0, 3])
def test_repeated_replay_preserves_initial_state_aliases_and_every_attempt(tmp_path, initial_calls):
    fw = framework(tmp_path, calls=initial_calls)
    fw.evolve("isolated deterministic run")
    original_calls = (fw.llm.calls, fw.evaluator.calls)
    original_evidence = [r for r in fw.store.read() if r["kind"] != "replay_certificate"]
    first = fw.replay()["replay_certificate"]
    first_dir = Path(first["replay_workdir"])
    preserved = tree_bytes(first_dir)
    second = fw.replay()["replay_certificate"]
    assert first["passed"] and second["passed"]
    assert first["mode"] == second["mode"] == "independent_rerun"
    assert first["replay_id"] != second["replay_id"]
    assert first_dir != Path(second["replay_workdir"])
    assert tree_bytes(first_dir) == preserved
    assert (fw.llm.calls, fw.evaluator.calls) == original_calls
    assert [r for r in fw.store.read() if r["kind"] != "replay_certificate"] == original_evidence
    assert [r["payload"] for r in fw.store.read("replay_certificate")] == [first, second]
    assert (first_dir / "checkpoint.json").is_file()
    assert (Path(second["replay_workdir"]) / "checkpoint.json").is_file()


def test_replay_resets_extension_to_initial_state_without_mutating_live_extension(tmp_path):
    monitor = H2MonitorExtension(window=2)
    fw = framework(tmp_path, extension=monitor)
    fw.evolve("stateful extension")
    original = copy.deepcopy(monitor.checkpoint_state())
    assert original["parents"]
    assert fw.replay()["replay_certificate"]["passed"]
    assert fw.replay()["replay_certificate"]["passed"]
    assert monitor.checkpoint_state() == original


def test_uncopyable_adapters_require_factory_before_any_replay_calls(tmp_path):
    fw = framework(tmp_path, resource=True)
    fw.evolve("resource adapter")
    calls = fw.llm.calls
    with pytest.raises(RuntimeError, match="requires adapter_factory"):
        fw.replay()
    assert fw.llm.calls == calls
    assert not (Path(fw.workdir) / "replays").exists()

    def fresh(workdir, store):
        assert store.path == Path(workdir) / "x1.jsonl"
        llm = ResourceLLM()
        return llm, StatefulEvaluator(llm)

    assert fw.replay(adapter_factory=fresh)["replay_certificate"]["passed"]
    assert fw.llm.calls == calls


def test_failed_execution_records_failed_certificate_then_retry_uses_new_directory(tmp_path):
    fw = framework(tmp_path)
    fw.evolve("failed replay retry")
    original_calls = fw.llm.calls
    with pytest.raises(RuntimeError, match="certified replay execution failed"):
        fw.replay(adapter_factory=lambda workdir, store: (BrokenLLM(), StatefulEvaluator()))
    failed = fw.inspect()["replay_certificate"]
    failed_dir = Path(failed["replay_workdir"])
    failed_files = tree_bytes(failed_dir)
    assert failed["passed"] is False
    assert failed["error_type"] == "RuntimeError"
    passed = fw.replay()["replay_certificate"]
    assert passed["passed"] is True
    assert passed["replay_workdir"] != failed["replay_workdir"]
    assert tree_bytes(failed_dir) == failed_files
    assert fw.llm.calls == original_calls
    assert len(list(fw.store.read("replay_certificate"))) == 2


@pytest.mark.parametrize("role", ["llm", "evaluator"])
def test_factory_cannot_return_live_adapter(tmp_path, role):
    fw = framework(tmp_path)
    fw.evolve("bad factory")
    calls = (fw.llm.calls, fw.evaluator.calls)
    def factory(workdir, store):
        return (fw.llm if role == "llm" else StatefulLLM(),
                fw.evaluator if role == "evaluator" else StatefulEvaluator())
    with pytest.raises(RuntimeError, match="certified replay execution failed"):
        fw.replay(adapter_factory=factory)
    assert (fw.llm.calls, fw.evaluator.calls) == calls
    certificate = fw.inspect()["replay_certificate"]
    assert certificate["passed"] is False
    assert certificate["error_type"] == "ValueError"


def test_explicit_fresh_adapter_replacement_is_copied_without_mutating_replacement(tmp_path):
    fw = framework(tmp_path)
    fw.evolve("replacement adapters")
    fw.llm = StatefulLLM()
    fw.evaluator = StatefulEvaluator(fw.llm)
    assert fw.replay()["replay_certificate"]["passed"]
    assert fw.llm.calls == fw.evaluator.calls == 0


def test_identity_preserving_deepcopy_requires_factory_without_live_adapter_calls(tmp_path):
    llm = AliasingLLM()
    fw = Framework(llm, StatefulEvaluator(llm), LoopConfig(max_generations=3),
                   str(tmp_path / "run"))
    fw.evolve("copy must create an independent adapter")
    calls = (llm.calls, fw.evaluator.calls)
    with pytest.raises(RuntimeError, match="requires adapter_factory"):
        fw.replay()
    assert (llm.calls, fw.evaluator.calls) == calls
    assert not (Path(fw.workdir) / "replays").exists()


def test_factory_setup_failure_replaces_success_status_and_retry_keeps_attempts(tmp_path):
    fw = framework(tmp_path)
    fw.evolve("factory failure after successful replay")
    first = fw.replay()["replay_certificate"]
    first_dir = Path(first["replay_workdir"])
    first_files = tree_bytes(first_dir)
    calls = (fw.llm.calls, fw.evaluator.calls)

    def broken_factory(workdir, store):
        assert store.path == Path(workdir) / "x1.jsonl"
        raise OSError("offline simulated resource allocation failure")

    with pytest.raises(RuntimeError, match="certified replay execution failed"):
        fw.replay(adapter_factory=broken_factory)
    inspection = fw.inspect()
    failed = inspection["replay_certificate"]
    failed_dir = Path(failed["replay_workdir"])
    failed_files = tree_bytes(failed_dir)
    assert inspection["replay_certified"] is False
    assert failed["passed"] is False
    assert failed["error_type"] == "OSError"
    assert failed_dir != first_dir
    assert failed["replay_snapshot_ref"] is None
    assert (failed_dir / "x1.jsonl").is_file()
    assert (fw.llm.calls, fw.evaluator.calls) == calls
    third = fw.replay()["replay_certificate"]
    assert third["passed"] is True
    assert len({first["replay_workdir"], failed["replay_workdir"],
                third["replay_workdir"]}) == 3
    assert tree_bytes(first_dir) == first_files
    assert tree_bytes(failed_dir) == failed_files
    assert [r["payload"] for r in fw.store.read("replay_certificate")] == [first, failed, third]


def test_identity_preserving_extension_copy_refuses_replay_without_mutation(tmp_path):
    monitor = AliasingMonitor(window=2)
    fw = framework(tmp_path, extension=monitor)
    fw.evolve("copy must isolate extension state")
    original = copy.deepcopy(monitor.checkpoint_state())
    calls = (fw.llm.calls, fw.evaluator.calls)
    with pytest.raises(RuntimeError, match="replay requires.*extensions"):
        fw.replay()
    assert monitor.checkpoint_state() == original
    assert (fw.llm.calls, fw.evaluator.calls) == calls
    assert not (Path(fw.workdir) / "replays").exists()
