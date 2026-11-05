"""Public external-governed routing with an offline independent authority fixture."""
from __future__ import annotations

import copy
import json
from pathlib import Path

from core.composition.defaults import composed_profile, default_registry
from core.composition.external_provider import (ExternalCallOutcome, ExternalPlanBinding,
    GovernedCallContext, external_call_id, external_session_id)
from core.loop import Framework, LoopConfig
from core.x1.checkpoint import payload_digest
from test_composed_budget import Domain, Provider, TASK, options

CAPABILITY = {"schema_version": 2, "fresh_session": True, "state_independent": True,
    "sampling": {"method": "deterministic_fixture", "parameters": {}, "applied": True},
    "call_bound": {"kind": "hard", "units": {"token": 5}},
    "external_currency": {"schema_version": 1, "bridge": "fixture_bridge"},
    "phase_call_limits": {"operator": 1, "evaluation": 0}}


class ExternalFixtureProvider(Provider):
    def governance_binding(self):
        return copy.deepcopy(CAPABILITY)


class FixtureBridge:
    """An offline durable authority with explicit context; no CNY or HTTP code."""

    def __init__(self):
        self.calls = []
        self.recovered = []
        self.context = None
        self.outcomes = {}

    def bind_run(self, context):
        self.context = context
        self.path = Path(context.workdir) / "fixture-external-outcomes.json"
        if context.mode == "recorded":
            self.outcomes = copy.deepcopy(context.recorded_bundle["outcomes"])
        elif self.path.exists():
            self.outcomes = json.loads(self.path.read_text())
        bindings = {"main": context.main_provider_binding, **context.control_provider_bindings}
        authority = {"currency_run_id": "b" * 64, "campaign_id": "c" * 32,
            "policy_sha256": "d" * 64, "phase_call_limits": CAPABILITY["phase_call_limits"],
            "session_ids": {key: external_session_id(context.logical_run_id,
                "main" if key == "main" else "control", None if key == "main" else key,
                payload_digest(binding)) for key, binding in bindings.items()},
            "obligations_sha256": "e" * 64, "main_currency_cap_micro_cny": 1000,
            "initial_currency_head": {"seq": 0, "sha256": "0" * 64}}
        return ExternalPlanBinding(schema_version=1, runtime_id=context.runtime_id,
            logical_run_id=context.logical_run_id, physical_plan_ref=context.physical_plan["plan_ref"],
            bridge_plan_ref="sha256:" + payload_digest(authority), authority_binding=authority)

    def invoke(self, context, args, kwargs):
        assert self.context.mode == "live", "recorded replay must never invoke a provider"
        assert isinstance(context, GovernedCallContext)
        self.calls.append(context.to_dict())
        raw = self.context.provider_sessions["main" if context.lane == "main" else context.slot_id]
        result = raw(*args, **kwargs)
        wire = payload_digest({"args": list(args), "kwargs": kwargs})
        call_id = external_call_id(context, wire)
        outcome = ExternalCallOutcome(call_id=call_id, context_sha256=payload_digest(context.to_dict()),
            wire_request_sha256=wire, response_sha256=payload_digest(result),
            usage={"total_tokens": raw.last_usage["total_tokens"]}, result=result,
            outcome="returned", currency_state="settled", integrity_reason=None,
            provider_state=raw.checkpoint_state() if callable(getattr(raw,"checkpoint_state",None)) else None,
            outcome_ref="sha256:" + payload_digest({"call_id": call_id, "result": result}))
        self.outcomes[payload_digest(context.to_dict())] = outcome.to_dict()
        self.path.write_text(json.dumps(self.outcomes, sort_keys=True))
        return result

    def recover(self, context, argument_sha256):
        assert argument_sha256 == context.argument_sha256
        self.recovered.append(context.to_dict())
        return ExternalCallOutcome.from_dict(self.outcomes[payload_digest(context.to_dict())])

    def finish_control(self, slot_id, terminal_ref):
        assert slot_id and terminal_ref

    def audit(self):
        return {"schema_version": 1, "protection_valid": True, "complete": True,
                "settled_calls": len(self.outcomes), "pending_calls": []}

    def replay_bundle(self):
        return {"schema_version": 1, "outcomes": copy.deepcopy(self.outcomes)}


def external_framework(path, *, stop=None, resume=False, bridge_type=FixtureBridge):
    registry = default_registry()
    bridges, controls = [], []
    def bridge_factory():
        bridge = bridge_type()
        bridges.append(bridge)
        return bridge
    def provider_factory(ctx, opts):
        provider = ExternalFixtureProvider()
        controls.append(provider)
        return provider
    registry.install_external_bridge("fixture_bridge", bridge_factory)
    registry.register("provider", "external_fixture", provider_factory, governance=CAPABILITY)
    registry.register("domain", "fresh_fixture", lambda *_: Domain(),
        governance={"schema_version": 1, "fresh_session": True, "state_independent": True})
    profile = composed_profile()
    profile["domain"] = {"name": "native"}
    profile["budget"] = {"name": "hierarchical", "options": options()}
    profile["governance"] = {"schema_version": 1, "controls": {
        "after_main_cycles": [0, 2], "seed": 1, "provider": {"name": "external_fixture"},
        "domain": {"name": "fresh_fixture"}, "operator": {"name": "draft"},
        "request": {"fidelity": "dev", "split_id": "dev", "seed_set": None},
        "reservations": {"operator": {"token": 5, "node": 1, "eval_count": 0},
                         "evaluation": {"token": 7, "node": 0, "eval_count": 1}}}}
    config = LoopConfig(max_generations=1, total_budget=100000, reeval_floor=0,
                        stop_after_generation=stop, resume_from_checkpoint=resume)
    main = ExternalFixtureProvider()
    framework = Framework.from_profile(profile, main, Domain(), config, str(path), component_registry=registry)
    return framework, bridges, controls, main


def test_public_framework_routes_all_external_calls_through_fresh_bridge(tmp_path):
    framework, bridges, controls, main = external_framework(tmp_path)
    result = framework.evolve(TASK)
    assert result["runtime"] == "composed-v8-governed-external"
    assert len(bridges) == 1
    bridge = bridges[0]
    assert len(bridge.calls) == 4
    assert [call["lane"] for call in bridge.calls] == ["control", "main", "main", "control"]
    assert all(call["phase"] == "operator" and call["ordinal"] == 0 for call in bridge.calls)
    assert [call["account"] for call in bridge.calls] == ["control", "explore", "exploit", "control"]
    assert main.calls == 2 and [provider.calls for provider in controls] == [1, 1]


def test_public_external_resume_and_replay_create_new_bridges_without_dispatch_repetition(tmp_path):
    first, bridges, controls, main = external_framework(tmp_path, stop=0)
    first.evolve(TASK)
    assert main.calls == 1 and [provider.calls for provider in controls] == [1, 0]
    resumed, fresh_bridges, fresh_controls, fresh_main = external_framework(tmp_path, resume=True)
    resumed.evolve(TASK)
    assert fresh_main.calls == 1 and [provider.calls for provider in fresh_controls] == [0, 1]
    replay = resumed.replay(TASK)
    assert replay["replay_certificate"]["passed"] is True
    assert replay["replay_certificate"]["external_calls"] == 0
    assert len(fresh_bridges) == 2 and fresh_bridges[1] is not fresh_bridges[0]
    assert fresh_bridges[1].calls == []
    assert fresh_bridges[1].context.mode == "recorded"


def test_durable_external_outcome_recovers_after_sigkill_before_framework_completion(tmp_path):
    import os
    import signal
    import subprocess
    import sys
    script = '''import os, signal, sys
from test_governed_external_runtime import FixtureBridge, external_framework, TASK
class KillAfterOutcome(FixtureBridge):
    def invoke(self, context, args, kwargs):
        super().invoke(context, args, kwargs)
        os.kill(os.getpid(), signal.SIGKILL)
framework, *_ = external_framework(sys.argv[1], bridge_type=KillAfterOutcome)
framework.evolve(TASK)
'''
    env = os.environ.copy()
    source = Path(__file__).resolve().parents[1]
    env["PYTHONPATH"] = os.pathsep.join((str(source), str(source / "tests")))
    child = subprocess.run([sys.executable, "-c", script, str(tmp_path)], env=env,
                           capture_output=True, text=True, timeout=15)
    assert child.returncode == -signal.SIGKILL, child.stderr
    from core.x1.store import AppendOnlyStore
    source_rows = list(AppendOnlyStore(tmp_path / "x1.jsonl").read())
    assert any(row["kind"] == "composed_provider_started" for row in source_rows)
    assert not any(row["kind"] == "composed_provider_completed" for row in source_rows)
    resumed, bridges, controls, main = external_framework(tmp_path, resume=True)
    resumed.evolve(TASK)
    assert controls[0].calls == 0, "durable settled response must be adopted without reissuing it"
    assert controls[1].calls == 1 and main.calls == 2
    assert any(context["slot_id"] == "control-0000" for context in bridges[0].recovered)
    assert resumed.inspect()["governance"]["completed"] == 2
