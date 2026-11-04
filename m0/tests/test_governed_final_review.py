"""Focused adversarial reproductions from the final uncommitted-state review."""
import json
from dataclasses import replace

import pytest

from core.composition.recovery import ContinuationStore
from core.composition.contracts import AssemblyConfig
from core.llm import UsageError
from test_composed_budget import Domain, TASK
from test_governed_runtime import FreshProvider, governed


def test_call_bound_breach_invalidates_protection_even_with_operation_slack(tmp_path):
    framework, _, _, main, _ = governed(tmp_path)
    main.tokens = 6  # The hard per-call bound is 5; the operation permits 10.
    with pytest.raises(UsageError, match="bound"):
        framework.evolve(TASK)
    report = framework.inspect()["governance"]
    assert report["budget"]["accounts"]["explore"]["token"] == 6
    assert report["budget"]["protection_valid"] is False


def test_completed_resume_rejects_missing_provider_authority(tmp_path):
    framework, _, _, _, _ = governed(tmp_path)
    framework.evolve(TASK)
    path = tmp_path / "x1.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    rows = [row for row in rows if row["kind"] not in {
        "composed_provider_started", "composed_provider_completed"}]
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    resumed, _, _, _, _ = governed(tmp_path, resume=True)
    with pytest.raises((ValueError, UsageError)):
        resumed.evolve(TASK)
        resumed.inspect()


def test_post_call_binding_drift_survives_completion_crash(tmp_path, monkeypatch):
    class Drifting(FreshProvider):
        def governance_binding(self):
            binding = super().governance_binding()
            if self.calls:
                binding["sampling"]["parameters"] = {"changed": True}
            return binding

    class Crash(BaseException):
        pass

    original = ContinuationStore._write
    crashed = False

    def write_then_crash(store, record):
        nonlocal crashed
        original(store, record)
        if not crashed and record["kind"] == "composed_provider_completed":
            crashed = True
            raise Crash()

    monkeypatch.setattr(ContinuationStore, "_write", write_then_crash)
    framework, providers, _, _, _ = governed(tmp_path, provider_factory=Drifting)
    with pytest.raises(Crash):
        framework.evolve(TASK)
    assert [provider.calls for provider in providers] == [1, 0, 0]
    monkeypatch.setattr(ContinuationStore, "_write", original)
    resumed, fresh, domains, main, _ = governed(tmp_path, resume=True, provider_factory=Drifting)
    with pytest.raises((ValueError, UsageError)):
        resumed.evolve(TASK)
    assert main.calls == 0
    assert all(provider.calls == 0 for provider in fresh)
    assert all(not domain.calls for domain in domains)


def test_completed_native_evaluation_with_provider_calls_replays_without_dispatch(tmp_path, monkeypatch):
    class PaidDomain(Domain):
        def __init__(self, provider):
            super().__init__()
            self.provider = provider

        async def evaluate(self, proposal, request):
            self.provider("evaluation")
            return await super().evaluate(proposal, request)

    framework, providers, _, _, _ = governed(tmp_path)
    registry = framework._composed.registry
    key = ("domain", "independent-fixture")
    registry._entries[key] = replace(registry._entries[key],
        factory=lambda context, options: PaidDomain(context.llm))
    framework.evolve(TASK)
    assert [provider.calls for provider in providers] == [2, 2, 2]

    async def forbidden(*args, **kwargs):
        raise AssertionError("recorded replay invoked evaluator")

    monkeypatch.setattr(PaidDomain, "evaluate", forbidden)
    assert framework.replay()["replay_certificate"]["passed"] is True


@pytest.mark.parametrize("phase,unit", [("operator", "node"), ("evaluation", "eval_count")])
def test_preflight_rejects_reservations_below_mandatory_phase_cost(tmp_path, phase, unit):
    framework, _, _, _, _ = governed(tmp_path)
    profile = framework._composed.assembly.to_dict()
    profile["governance"]["controls"]["reservations"][phase][unit] = 0
    with pytest.raises(ValueError):
        AssemblyConfig.from_dict(profile)
