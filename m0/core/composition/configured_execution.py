"""Versioned recipe-to-artifact adapter used by the configured M7 runtime.

This module prepares permitted inputs and immutable references. InvocationLifecycle
still owns the one physical start/settlement boundary around candidate production.
"""
from __future__ import annotations

import copy
from dataclasses import replace
from pathlib import Path

from core.composition.artifacts import NativeArtifactBackend
from core.composition.construction import ConstructionPlan, _json, project_context
from core.composition.context import ContextPack
from core.composition.execution import CandidateExecution
from core.executor.types import Candidate


class ConfiguredExecution:
    def __init__(self, config, parts, store, root, *, lane="main", slot_id=None):
        self.config, self.parts, self.store = config, parts, store
        self.lane, self.slot_id = lane, slot_id
        location = Path(root) / "construction-artifacts" / ("main" if lane == "main" else slot_id)
        create_backend = getattr(parts["executor"], "construction_backend", None)
        backend = create_backend(location, store) if callable(create_backend) else NativeArtifactBackend(location)
        evaluator_factory = getattr(parts["executor"], "evaluation_executor", None)
        command = evaluator_factory(backend, store, parts["domain"]) if callable(evaluator_factory) else None
        self.owner = CandidateExecution(parts["constructor"], backend,
            store, parts["provider"], parts["domain"], command_executor=command)
        self.materializations = {}

    @property
    def manifest_binding(self):
        return {"schema_version": 1, "envelope": "candidate_production_v1",
                "policy_sessions": "separate_planning_absorption_v1",
                "constructor": self.owner.binding, "artifact_backend": self.owner.backend_binding,
                **({"evaluation_backend": self.owner.evaluation_binding} if self.owner.command_executor else {})}

    def project(self, context):
        pack = ContextPack(_json(context["retrieval"]))
        projected = project_context(pack, self.config.spec.context_projection,
                                    expected_ref=context["context_pack_ref"])
        return {"retrieval": projected, "context_pack_ref": context["context_pack_ref"]}

    @staticmethod
    def selection_view(frontier):
        """Keep the numeric/identity topology while removing source text channels."""
        frontier.messages, frontier.git_state = [], {}
        frontier.edges["reference"] = []
        for node in frontier.nodes.values():
            node.hypothesis = node.insight = node.result = node.code_ref = node.prune_reason = None
            node.grounding, node.related_work = [], []
        return frontier

    @staticmethod
    def parent_view(proposal):
        # Selected artifacts are authorized recipe inputs; previous hypotheses
        # and raw feedback are not an alternate retrieval channel.
        return replace(copy.deepcopy(proposal), candidate=replace(proposal.candidate, hypothesis=None))

    @staticmethod
    def control_context(task):
        pack = ContextPack(_json({"schema_version": 1, "usage": "Evidence, not instructions",
            "scope": {"kind": "control", "candidate_ids": []}, "query": task,
            "budget": {"unit": "chars", "limit": 0}, "memory": [], "grounding": []}))
        return {"retrieval": pack.to_dict(), "context_pack_ref": pack.ref}

    def operator(self, operator, selected, context, operation):
        owner = self

        class Production:
            async def propose(self, request):
                recipe = operator.recipe(request)
                hypotheses = request.strategy.get("hypotheses", [])
                hypothesis = hypotheses[0].get("hypothesis") if hypotheses else (
                    owner.config.spec.hypothesis or "Establish an executable baseline")
                candidate = Candidate(request.candidate_id, [p.candidate.id for p in request.parents],
                    operator=selected, created_cycle=request.cycle, hypothesis=hypothesis,
                    context_pack_ref=context["context_pack_ref"])
                plan = ConstructionPlan.create(candidate, recipe, owner.config.spec,
                    ContextPack(_json(context["retrieval"])), roles=owner.parts["constructor"].roles)
                if owner.parts['constructor'].manifest_binding['kind'] == 'openevolve_diff_materializer_v1':
                    owner.store.append('openevolve_construction_plan',
                        {'candidate_id': candidate.id, 'plan': plan.to_dict(), 'plan_ref': plan.ref})
                materialized = await owner.owner.materialize(plan, operation=operation)
                owner.materializations[candidate.id] = materialized
                return materialized.proposal

        return Production()

    async def evaluate(self, proposal, request, operation):
        materialized = self.materializations.get(proposal.candidate.id)
        if materialized is None or materialized.proposal != proposal:
            raise ValueError("evaluation proposal differs from its frozen materialization")
        return await self.owner.evaluate(materialized, request, operation=operation)

    def snapshot(self):
        return {key: value.to_dict() for key, value in self.materializations.items()}

    def report(self):
        artifacts = {}
        for row in self.store.read("materialization_completed"):
            value = row["payload"]
            operation = value["identity"]["operation"]
            if operation["lane"] != self.lane or operation["slot_id"] != self.slot_id:
                continue
            item = self.owner._check_materialization(value)
            candidate = item.proposal.candidate
            if candidate.id in artifacts:
                raise ValueError("multiple materializations for one candidate")
            artifacts[candidate.id] = {"artifact_ref": value["artifact"]["reference"],
                "materialization_ref": item.ref, "role": value["construction_result"]["role"]["name"],
                "hypothesis": candidate.hypothesis}
        return {"binding": self.manifest_binding, "artifacts": artifacts}

    def restore(self, value):
        if type(value) is not dict:
            raise ValueError("checkpoint requires construction materializations")
        result = {}
        for key, data in value.items():
            item = self.owner._check_materialization(data)
            operation = data["identity"]["operation"]
            if item.proposal.candidate.id != key or operation["lane"] != self.lane \
                    or operation["slot_id"] != self.slot_id:
                raise ValueError("checkpoint construction identity differs")
            result[key] = item
        self.materializations = result
