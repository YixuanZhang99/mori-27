"""M7 control sessions construct from frozen parentless inputs."""
import copy
import json

from core.loop import Framework
from test_configured_construction import ConstructorProvider, ForbiddenDomain, profile, records
from test_governed_runtime import CAPABILITY, governed
from test_composed_budget import Domain, TASK


class FreshConstructor(ConstructorProvider):
    def governance_binding(self):
        return copy.deepcopy(CAPABILITY)


def build(path, *, stop=None, resume=False, main_tokens=10000, forbid=None, constructor=None):
    forbid = forbid if forbid is not None else {"value": False}
    template, sessions, domains, _, _ = governed(path, stop=stop, resume=resume, main_tokens=main_tokens,
        provider_factory=lambda: FreshConstructor(forbidden=forbid["value"]),
        domain_factory=lambda: ForbiddenDomain() if forbid["value"] else Domain())
    assembly = template._composed.assembly.to_dict()
    assembly.update(schema_version=2, execution=profile()["execution"])
    if constructor is not None:
        from dataclasses import asdict
        template._composed.registry.register("constructor", "custom", lambda ctx, opts: constructor,
            execution={"schema_version": 1, "roles": {key: asdict(role) for key, role in constructor.roles.items()}})
        assembly["execution"]["constructor"] = {"name": "custom"}
    main = FreshConstructor()
    fw = Framework.from_profile(assembly, main, Domain(), template._composed.cfg, str(path),
        component_registry=template._composed.registry)
    return fw, sessions, domains, main


def test_controls_construct_in_fresh_sessions_without_main_artifacts_or_memory(tmp_path):
    fw, providers, domains, main = build(tmp_path)
    result = fw.evolve(TASK)
    assert result["runtime"] == "composed-v9-m7-governed"
    assert main.calls == 3 and [p.calls for p in providers] == [1, 1, 1]
    assert [len(d.calls) for d in domains] == [1, 1, 1]
    materialized = records(fw, "materialization_completed")
    assert len(materialized) == 6
    sessions = fw._composed.governed.sessions
    constructors = [fw._composed.parts["constructor"], *(p["constructor"] for p in sessions.values())]
    assert len({id(c) for c in constructors}) == 4
    for provider in providers:
        request = json.loads(provider.prompts[0])
        assert request["recipe"]["parent_artifacts"] == []
        assert request["context"]["content"] == {"memory": [], "grounding": []}
    assert fw.inspect()["governance"]["budget"]["physical_totals"] == {"token": 72, "node": 6, "eval_count": 6}
    control_ids = {m["construction_result"]["candidate"]["id"] for m in materialized
                   if m["identity"]["operation"]["lane"] == "control"}
    assert not control_ids.intersection(fw._composed.frontier.nodes)


def test_main_exhaustion_preserves_control_build_and_evaluation_capacity(tmp_path):
    fw, providers, _, main = build(tmp_path, main_tokens=38)
    fw.evolve(TASK)
    assert main.calls == 0 and [p.calls for p in providers] == [1, 1, 1]
    assert fw.inspect()["governance"]["completed"] == 3


def test_control_replay_has_no_new_build_or_evaluation(tmp_path):
    forbid = {"value": False}
    fw, providers, _, _ = build(tmp_path, forbid=forbid)
    fw.evolve(TASK)
    forbid["value"] = True
    replay = fw.replay(adapter_factory=lambda path, store: (FreshConstructor(forbidden=True), ForbiddenDomain()))
    assert replay["replay_certificate"]["passed"]
    assert [p.calls for p in providers] == [1, 1, 1, 0, 0, 0]


def test_paused_controls_resume_only_the_remaining_frozen_slots(tmp_path):
    first, initial, _, _ = build(tmp_path, stop=0)
    first.evolve(TASK)
    assert [provider.calls for provider in initial] == [1, 0, 0]
    resumed, fresh, _, main = build(tmp_path, resume=True)
    resumed.evolve(TASK)
    assert main.calls == 2 and [provider.calls for provider in fresh] == [0, 1, 1]
    report = resumed.inspect()
    assert report["governance"]["completed"] == 3
    assert [len(slot["artifacts"]) for slot in report["execution"]["controls"].values()] == [1, 1, 1]


def test_shared_control_constructor_is_rejected_before_paid_work(tmp_path):
    import pytest
    from core.composition.construction_recipes import DEFAULT_ROLES
    from core.composition.construction import PromptMaterializer
    fw, providers, _, main = build(tmp_path, constructor=PromptMaterializer(DEFAULT_ROLES))
    with pytest.raises(ValueError, match="constructor reused"):
        fw.evolve(TASK)
    assert main.calls == 0 and all(provider.calls == 0 for provider in providers)
