"""Configured orchestration through the public Framework entry point.

Components own decisions and execution; this driver owns call ordering, budget
reservations, serial state mutation and cycle-boundary recovery. Unfinished paid
cycles fail closed on resume; their adapters must provide durable adoption before
that recovery window can be supported.
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import math
import tempfile
import uuid
from dataclasses import asdict, replace
from pathlib import Path
from types import FunctionType

from core.composition.contracts import AssemblyConfig, BuildContext, Decision, OperatorRequest, Proposal
from core.composition.context import ContextMemory, ContextPackBuilder
from core.composition.knowledge import KnowledgePack
from core.composition.admission import LayeredAdmissionController
from core.composition.budget import HierarchicalBudget
from core.composition.hierarchical_runtime import HierarchicalRuntime
from core.composition.evaluation import (EvaluationContract, binding_for, comparison_projection,
    decode_evidence, encode_evidence, measured_costs, public_projection, validate_evidence,
    validate_request)
from core.executor.types import Candidate, CostVec, EvalRequest, EvalResult, EvalStatus, EvidenceRecord
from core.frontier import ResearchFrontier
from core.llm import UsageError, take_usage
from core.memory.types import ScopeContext
from core.policy.types import AllocationIntent, MutationOp, StateMutation
from core.state import StateApplier, _jsonable
from core.x1.checkpoint import RunCheckpoint, payload_digest
from core.x1.store import AppendOnlyStore


def _id(*values):
    return hashlib.sha256("\0".join(map(str, values)).encode()).hexdigest()


def _tokens(cost):
    if not isinstance(cost, CostVec):
        raise UsageError("components must return explicit CostVec usage")
    for name, value in asdict(cost).items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) \
                or not math.isfinite(value) or value < 0:
            raise UsageError("component cost must be finite and non-negative")
        if name in {"tokens_in", "tokens_out", "eval_count", "node_count"} and type(value) is not int:
            raise UsageError("token and count usage must be integers")
    return cost.tokens_in + cost.tokens_out


def _evidence(data):
    return decode_evidence({"schema_version": 1, "evidence": data})


def _proposal(data):
    return Proposal(Candidate(**data["candidate"]), data["artifact"], CostVec(**data["cost"]),
                    tuple(data["measured_cost_units"]) if data.get("measured_cost_units") is not None else None)


def _copy_sources(sources):
    copied = copy.deepcopy(sources)
    for key, value in sources.items():
        if value is not None and copied[key] is value and not isinstance(value, FunctionType):
            raise ValueError("replay cannot share live adapters")
    return copied


class ComposedRuntime(HierarchicalRuntime):
    def __init__(self, assembly, registry, llm, evaluator, config, workdir, stamp):
        self.registry = registry
        self.assembly = registry.preflight(assembly)
        self.llm, self.evaluator = llm, evaluator
        self.cfg, self.workdir, self.stamp = config, Path(workdir), stamp
        self.store = AppendOnlyStore(self.workdir / "x1.jsonl")
        self.result = None
        self.task = None
        self.parts = None
        self._seed = None
        self.proposals, self.evidence = {}, {}
        self.incumbent = None
        self.next_cycle = 0
        self._policy_tokens = 0
        self._forbidden_parts = None
        self._current_intent = None
        self._known_cost = 0
        self._call_cost_known = True
        self._logical_run_id = None
        self._context_export = None
        self.eval_requests = {}
        self._halted_reason = None

    def _build(self, task):
        scope = ScopeContext(self._logical_run_id, _id("task", task),
                             self.assembly.domain.name)
        context = BuildContext(self.llm, self.evaluator, self.store, scope,
                               self.cfg, str(self.workdir), self.stamp, mode=self.assembly.mode)
        self.parts = self.registry.build(self.assembly, context)
        if self._forbidden_parts is not None:
            live = [item for value in self._forbidden_parts.values()
                    for item in (value if isinstance(value, tuple) else (value,))]
            for value in self.parts.values():
                for item in (value if isinstance(value, tuple) else (value,)):
                    if item is not None and any(item is previous for previous in live):
                        raise ValueError("component factory reused live state during replay")
            current_provider = self.parts["provider"].raw_provider
            previous_provider = self._forbidden_parts["provider"].raw_provider
            if current_provider is previous_provider and not isinstance(current_provider, FunctionType):
                raise ValueError("provider factory reused the live underlying adapter")
        required = {"policy": ("observe", "ideate", "select", "absorb"),
                    "domain": ("evaluate",), "executor": ("execute",),
                    "admission": ("judge",), "budget": ("account_summary",)}
        for kind, methods in required.items():
            if any(not callable(getattr(self.parts[kind], name, None)) for name in methods):
                raise ValueError(f"component {kind} does not implement its runtime contract")
        for operator in self.parts["operators"]:
            if not callable(getattr(operator, "propose", None)):
                raise ValueError("operator does not implement propose")
        self.frontier, self.memory = self.parts["frontier"], self.parts["memory"]
        from core.composition.defaults import MetricAdmission, PromptOperator
        expected_metric = self.frontier.metric
        if getattr(self.parts["domain"], "metric", expected_metric) != expected_metric or any(
                isinstance(operator, PromptOperator) and operator.metric != expected_metric
                for operator in self.parts["operators"]):
            raise ValueError("configured objective differs across domain/frontier/operators")
        admission = self.parts["admission"]
        if isinstance(admission, (MetricAdmission, LayeredAdmissionController)) and (
                admission.metric != expected_metric or admission.direction != self.frontier.direction):
            raise ValueError("configured admission objective differs from exploration")
        self.applier = StateApplier(self.frontier, self.memory, self.store)
        self.budget = self.parts["budget"]
        self.hierarchical = isinstance(self.budget, HierarchicalBudget)
        if not self.hierarchical and any(not callable(getattr(self.budget, method, None))
                for method in ("quote_reserve", "settle")):
            raise ValueError("budget does not implement its runtime contract")
        self.layered = self.parts["admission"] if isinstance(self.parts["admission"], LayeredAdmissionController) else None
        preflight = getattr(self.parts["domain"], "validate_context", None)
        if callable(preflight):
            preflight()
        self.manifest = {"assembly": self.assembly.to_dict(),
                         "provider_model": getattr(self.parts["provider"], "model", None),
                         "domain_version": getattr(self.parts["domain"], "evaluator_version", None),
                         "evaluation_context": getattr(self.parts["domain"], "evaluation_context", ""),
                         "knowledge": getattr(self.parts.get("knowledge"), "manifest_binding", None)}
        self.manifest["evaluation_contexts"] = {"dev": self.manifest["evaluation_context"]}
        if self.layered:
            contexts = self.layered.validate_domain(self.parts["domain"])
            self.manifest["evaluation_contexts"].update(contexts)
            if len(set(self.manifest["evaluation_contexts"].values())) != len(self.manifest["evaluation_contexts"]):
                raise ValueError("dev, admission and final audit require distinct dataset contexts")
            self.layered.check_integrity(Proposal(Candidate("task-preflight"), task))
        if self.hierarchical:
            self._preflight_hierarchical()
        else:
            self._validate_domain(EvalRequest("dev"))
        self.manifest["memory_imports"] = [self.memory.validate_import_snapshot(
            spec["path"], expected_sha256=spec["sha256"])
            for spec in self.assembly.memory.options.get("imports", [])]
        knowledge = self.parts.get("knowledge")
        self.manifest["knowledge_imports"] = [knowledge.validate_memory_import(
            spec["path"], expected_sha256=spec["sha256"])
            for spec in (self.assembly.knowledge.options.get("memory_imports", [])
                         if self.assembly.knowledge else [])]
        if (self.assembly.memory.options.get("export_on_finish") or self.assembly.knowledge
                and self.assembly.knowledge.options.get("ingest_on_finish")) and not self.memory.evaluation_context:
            raise ValueError("opaque evaluation context cannot authorize memory export or knowledge ingest")

    def _validate_domain(self, request):
        validate_request(request)
        original_request = asdict(request)
        domain = self.parts["domain"]
        check = getattr(domain, "validate_context", None)
        if callable(check):
            check()
        check = getattr(domain, "validate_request", None)
        if not callable(check):
            raise ValueError("domain must explicitly validate supported evaluation requests")
        check(request)
        if asdict(request) != original_request:
            raise ValueError("domain validation changed the evaluation request")
        if (getattr(domain, "evaluator_version", None) != self.manifest["domain_version"]
                or getattr(domain, "evaluation_context", "") != self.manifest["evaluation_context"]):
            raise ValueError("domain identity changed during configured execution")
        if self.layered and domain.evaluation_context_for(request) != self.manifest["evaluation_contexts"].get(request.split_id):
            raise ValueError("domain split context changed during configured execution")
        self._binding(Proposal(Candidate("preflight"), ""), request)

    def _binding(self, proposal, request):
        return binding_for(proposal, request,
                           evaluator_version=self.manifest["domain_version"],
                           evaluation_context=self.manifest["evaluation_contexts"].get(
                               request.split_id, self.manifest["evaluation_context"]))

    def _module_states(self):
        values = {}
        for kind, component in self.parts.items():
            items = component if isinstance(component, tuple) else (component,)
            for i, item in enumerate(items):
                save = getattr(item, "checkpoint_state", None)
                if kind not in {"frontier", "memory", "budget"} and callable(save):
                    values[f"{kind}:{i}"] = save()
        return values

    def _payload(self):
        config = asdict(self.cfg)
        config.pop("resume_from_checkpoint")
        config.pop("stop_after_generation")
        return {"runtime": "composed-v5", "manifest": self.manifest, "config": config,
                "logical_run_id": self._logical_run_id,
                "context_export": self._context_export,
                "evaluation_requests": {key: asdict(value) for key, value in self.eval_requests.items()},
                "halted_reason": self._halted_reason,
                "budget_checkpoint": self.budget.checkpoint_state() if self.hierarchical else None,
                "task_desc": self.task, "next_cycle": self.next_cycle,
                "git_state": {"kind": "configured_artifacts"}, "inflight_executor": [],
                "messages": [{"role": "task", "content": self.task}],
                "frontier_checkpoint": self.frontier.checkpoint().decode(),
                "memory": self.memory.checkpoint_state(), "module_states": self._module_states(),
                "proposals": {key: _jsonable(value) for key, value in self.proposals.items()},
                "evidence": {key: encode_evidence(value)["evidence"] for key, value in self.evidence.items()},
                "incumbent": self.incumbent, "ledger": self.budget.account_summary()}

    def _save(self):
        if self.cfg.checkpoint_enabled:
            if (self.budget.state()["open_intents"] if self.hierarchical else self.budget.reserves):
                raise RuntimeError("cycle checkpoint cannot contain unsettled reservations")
            checkpoint = RunCheckpoint.create(self._payload())
            checkpoint.save(self.workdir / "checkpoint.json")
            self.store.append("composed_checkpoint", {"next_cycle": self.next_cycle,
                                                       "sha256": checkpoint.payload_sha256})

    def _restore(self):
        payload = RunCheckpoint.load(self.workdir / "checkpoint.json").payload
        config = asdict(self.cfg)
        config.pop("resume_from_checkpoint")
        config.pop("stop_after_generation")
        expected = {"runtime": "composed-v5", "manifest": self.manifest,
                    "task_desc": self.task, "config": config}
        for field in ("runtime", "manifest", "task_desc", "config"):
            if payload.get(field) != expected[field]:
                raise ValueError(f"composed checkpoint {field} is incompatible")
        aborted = {row["payload"]["cycle"] for row in self.store.read("composed_cycle_aborted")}
        if any(row["payload"]["cycle"] >= payload["next_cycle"] and row["payload"]["cycle"] not in aborted
               for row in self.store.read("composed_cycle_started")):
            raise RuntimeError("unfinished composed cycle requires durable adoption; refusing reexecution")
        proposals = {key: _proposal(value) for key, value in payload["proposals"].items()}
        evidence_by_id = {key: _evidence(value) for key, value in payload["evidence"].items()}
        evaluation_requests = {key: EvalRequest(**value) for key, value in payload["evaluation_requests"].items()}
        if set(proposals) != set(evidence_by_id):
            raise ValueError("checkpoint proposal and evidence identities differ")
        if set(evaluation_requests) != set(evidence_by_id):
            raise ValueError("checkpoint evaluation request identities differ")
        for key, evidence in evidence_by_id.items():
            if proposals[key].candidate.id != key or evidence.candidate_id != key:
                raise ValueError("checkpoint candidate key differs from evidence identity")
            self._validate_domain(evaluation_requests[key])
            validate_evidence(evidence, expected_binding=self._binding(proposals[key], evaluation_requests[key]))
        self._verify_context_export(payload["context_export"])
        if self.hierarchical:
            self.budget.restore_state(payload["budget_checkpoint"])
        else:
            self.budget.restore_from_journal()
        if (self.budget.state()["open_intents"] if self.hierarchical else self.budget.reserves) \
                or self.budget.account_summary() != payload["ledger"]:
            raise ValueError("checkpoint budget differs from durable ledger")
        restored = ResearchFrontier.restore(payload["frontier_checkpoint"].encode(), store=self.store)
        if type(self.frontier) is not ResearchFrontier:
            raise ValueError("configured frontier does not implement portable restore")
        self.frontier.__dict__.update(restored.__dict__)
        self.memory.restore_state(payload["memory"])
        for key, state in payload["module_states"].items():
            kind, index = key.split(":")
            value = self.parts[kind]
            component = value[int(index)] if isinstance(value, tuple) else value
            restore = getattr(component, "restore_state", None)
            if not callable(restore):
                raise ValueError(f"component cannot restore saved state: {key}")
            restore(state)
        self.proposals, self.evidence = proposals, evidence_by_id
        self.eval_requests = evaluation_requests
        self._halted_reason = payload["halted_reason"]
        self.incumbent, self.next_cycle = payload["incumbent"], payload["next_cycle"]
        self._context_export = payload["context_export"]
        self.store.append("composed_resumed", {"next_cycle": self.next_cycle})

    async def _policy(self, name, *args):
        # Provider-backed policy work is inside the same pre-reserved cycle.
        provider = self.parts["provider"]
        before = provider.usage_total
        try:
            return await getattr(self.parts["policy"], name)(*args)
        finally:
            self._policy_tokens += provider.usage_total - before

    def _context(self, task, cycle, parents):
        if not isinstance(self.memory, ContextMemory):
            raise ValueError("configured retrieval requires evidence-bound memory")
        knowledge = self.parts.get("knowledge")
        grounding = None
        if knowledge is not None:
            self._call_cost_known = False
            grounding = knowledge.ground(_id(self._logical_run_id, cycle, "ground"), task)
            self._known_cost += _tokens(grounding.cost)
            recalled = knowledge.retrieve(self.memory.context, task,
                evaluation_context=self.memory.evaluation_context,
                top_k=self.assembly.memory.options.get("top_k", 5))
            self._known_cost += _tokens(recalled.cost)
            grounding = KnowledgePack(json.dumps({"schema_version": 1, "lane": "ground",
                "items": [*recalled.context_items(), *grounding.context_items()]}, sort_keys=True))
            self._call_cost_known = True
        pack = ContextPackBuilder(self.memory, self.assembly.memory.options).retrieve(
            self.frontier, parents, task, cycle, grounding=grounding)
        context = {"retrieval": pack.to_dict(), "context_pack_ref": pack.ref}
        self.store.append("composed_context", {"cycle": cycle, "context_ref": pack.ref,
                                               "context": pack.to_dict()})
        return context

    def _finish_context(self):
        knowledge = self.parts.get("knowledge")
        ingest = bool(knowledge and self.assembly.knowledge.options.get("ingest_on_finish"))
        if self._context_export is not None or not (
                self.assembly.memory.options.get("export_on_finish") or ingest):
            return
        selected = sorted(entry.id for entry in self.memory.entries.values()
            if entry.level in {"L2", "L3"} and entry.state == "active"
            and entry.scope != "run" and entry.time.superseded_by is None
            and entry.provenance.source_run_id == self._logical_run_id)
        if not selected:
            self._context_export = {"status": "no_eligible_lessons"}
        else:
            path = self.workdir / "memory-export.json"
            digest = self.memory.export_snapshot(path, entry_ids=selected)
            self._context_export = {"status": "exported", "relative_path": path.name,
                                    "sha256": digest, "entry_ids": selected}
            if ingest:
                knowledge.ingest_memory_export(path, expected_sha256=digest)
        self.store.append("composed_memory_export", self._context_export)
        self._save()

    def _verify_context_export(self, exported):
        if exported is None or exported == {"status": "no_eligible_lessons"}:
            return
        if not isinstance(exported, dict) or exported.get("status") != "exported" \
                or exported.get("relative_path") != "memory-export.json":
            raise ValueError("invalid memory export checkpoint")
        path = self.workdir / "memory-export.json"
        if not path.is_file() or "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest() != exported.get("sha256"):
            raise ValueError("memory export artifact differs from its bound content")

    @staticmethod
    def _source_refs(context):
        refs = []
        for item in context.get("retrieval", {}).get("grounding", []):
            provenance = item.get("provenance", {})
            refs.extend(provenance.get("source_pages", []))
            refs.extend(item.get("fetch_refs", []))
        return refs

    async def _execute_layered_calls(self, calls):
        if self.hierarchical:
            return await self._execute_hierarchical_calls(calls)
        reserved = []
        for call in calls:
            self._validate_domain(call.request)
            intent = AllocationIntent(_id(self._logical_run_id, "layered", call.key),
                "layered", call.proposal.candidate.id, self.cfg.intent_cost,
                snapshot_ref=call.key, account="reeval")
            receipt = self.budget.quote_reserve(intent)
            if receipt.verdict != "granted":
                for _, previous in reserved:
                    self.budget.release_for(previous)
                self.store.append("layered_budget_rejected", {"phase": call.phase, "reason": receipt.reason})
                return False
            reserved.append((call, intent))
        for index, (call, intent) in enumerate(reserved):
            started = False
            recorded = False
            try:
                self.budget.pre_call_check()
                self.layered.before_call(call)
                started = True
                provider_before = self.parts["provider"].usage_total
                evidence = await self.parts["executor"].execute(
                    copy.deepcopy(call.proposal), copy.deepcopy(call.request), self.parts["domain"])
                self._check_provider_floor(intent, provider_before, evidence.eval_result.cost)
                costs = measured_costs(evidence.eval_result)
                self.budget.settle(intent, costs["token"])
                self.layered.record(call, evidence)
                recorded = True
                self.store.append("layered_evidence", {"key": call.key, "phase": call.phase,
                    "evidence": encode_evidence(evidence)})
            except Exception as error:
                for _, remaining in reserved[index+1:]:
                    self.budget.release_for(remaining)
                if not started:
                    self.budget.release_for(intent)
                elif not recorded:
                    self.layered.mark_failed(call, type(error).__name__)
                raise
        return True

    async def _admit_layered(self, proposal, evidence, context):
        plan = self.layered.prepare(proposal, evidence,
            self.proposals[self.incumbent] if self.incumbent else None,
            self.evidence[self.incumbent] if self.incumbent else None,
            self.parts["domain"], source_refs=self._source_refs(context))
        if not await self._execute_layered_calls(plan.calls):
            return self.layered.decline(plan, "global budget cannot fund the admission plan")
        return self.layered.judge(plan)

    async def _finish_layered(self):
        if self.layered is None:
            return
        plan = self.layered.freeze(self.proposals[self.incumbent] if self.incumbent else None,
                                   self.parts["domain"])
        if not await self._execute_layered_calls(plan.calls):
            self.layered.skip_final("global budget cannot fund final audit")
        self.layered.final_report()
        self._save()

    @staticmethod
    def _validate_mutations(mutations, evidence):
        if not isinstance(mutations, list):
            raise ValueError("policy absorb must return a mutation list")
        protected = {"eval_status": evidence.eval_result.status.value,
                     "attempt": evidence.attempt, "code_ref": evidence.branch_ref}
        for mutation in mutations:
            if not isinstance(mutation, StateMutation) or mutation.op not in {
                    MutationOp.UPDATE_NODE, MutationOp.WRITE_MEMORY, MutationOp.PROMOTE_MEMORY}:
                raise ValueError("policy cannot bypass candidate materialization or admission")
            if mutation.op is MutationOp.UPDATE_NODE:
                if mutation.target != evidence.candidate_id or set(mutation.fields) - {
                        "insight", "result", *protected}:
                    raise ValueError("policy cannot rewrite authoritative execution state")
                if any(mutation.fields[key] != value for key, value in protected.items()
                       if key in mutation.fields):
                    raise ValueError("policy execution metadata differs from evidence")

    async def _prepare_cycle(self, task, cycle, candidate_id):
        state = {"task": task, "cycle": cycle, "frontier": json.loads(self.frontier.view("json")),
                 "operators": [spec.name for spec in self.assembly.operators]}
        strategy = await self._policy("observe", state, self.budget.account_summary())
        if not isinstance(strategy, dict):
            raise ValueError("policy observe must return a strategy object")
        selection_view = ResearchFrontier.restore(self.frontier.checkpoint())
        unavailable = set()
        if self.hierarchical:
            unavailable = {identifier for identifier, proposal in self.proposals.items()
                if not self.budget.should_continue(self._candidate_scope(proposal.candidate)[0])}
            # Keep skeleton ancestry intact while hiding exhausted branches from
            # sampling. The policy may choose another branch or a fresh draft.
            for identifier in unavailable:
                selection_view.nodes[identifier].status = "pruned"
        parents = await self._policy("select", selection_view, self.budget.account_summary())
        eligible_parents = {node.id for node in self.frontier.nodes.values()
                            if node.status in {"done", "merged"}
                            and node.eval_status == EvalStatus.OK.value
                            and node.score is not None and node.id not in unavailable}
        if not isinstance(parents, list) or len(parents) > 2 \
                or any(type(parent) is not str for parent in parents) \
                or len(set(parents)) != len(parents) \
                or any(parent not in self.proposals or parent not in eligible_parents
                       for parent in parents):
            raise ValueError("policy selected invalid parents")
        context = self._context(task, cycle, parents)
        if self.layered:
            self.layered.check_integrity(Proposal(Candidate(candidate_id), json.dumps(context, ensure_ascii=False)),
                                         self._source_refs(context))
        hypotheses = await self._policy("ideate", {**copy.deepcopy(strategy), "context": copy.deepcopy(context)},
                                        copy.deepcopy(self.proposals[parents[0]]) if parents else None, 1)
        strategy = {**strategy, "hypotheses": hypotheses}
        request = OperatorRequest(task, candidate_id, cycle,
                                  tuple(copy.deepcopy(self.proposals[p]) for p in parents),
                                  tuple(public_projection(self.evidence[p]) for p in parents), copy.deepcopy(context), strategy)
        for skill in self.parts["skills"]:
            before = self.parts["provider"].usage_total
            try:
                request = skill.apply(request)
            finally:
                self._policy_tokens += self.parts["provider"].usage_total - before
            if not isinstance(request, OperatorRequest) or request.candidate_id != candidate_id:
                raise ValueError("skill changed candidate identity")
            if request.context.get("retrieval") != context["retrieval"] or \
                    request.context.get("context_pack_ref") != context["context_pack_ref"]:
                raise ValueError("skill changed authoritative retrieval context")
        names = [spec.name for spec in self.assembly.operators]
        selected = strategy.get("operator", names[min(1 if parents else 0, len(names)-1)])
        if selected not in names:
            raise ValueError("policy selected an unregistered operator")
        operator = self.parts["operators"][names.index(selected)]
        return operator, selected, parents, context, request

    async def _cycle(self, task, cycle):
        if self.hierarchical:
            return await self._cycle_hierarchical(task, cycle)
        from core.composition.defaults import OperatorFailure
        evaluation_request = EvalRequest("dev")
        self._validate_domain(evaluation_request)
        candidate_id = _id(self.assembly.name, task, cycle)
        intent = AllocationIntent(_id(candidate_id, "cycle"), "composed", candidate_id,
                                  self.cfg.intent_cost, snapshot_ref=str(cycle),
                                  account="explore" if cycle == 0 else "exploit")
        reserve = self.budget.quote_reserve(intent)
        if reserve.verdict != "granted":
            self.store.append("composed_stopped", {"reason": reserve.reason, "cycle": cycle})
            return False
        self.budget.pre_call_check()
        self.store.append("composed_cycle_started", {"cycle": cycle, "intent": asdict(intent)})
        self._policy_tokens = 0
        self._current_intent = intent
        self._known_cost = 0
        self._call_cost_known = True
        operator, selected, parents, context, request = await self._prepare_cycle(task, cycle, candidate_id)
        self._call_cost_known = False
        provider_before = self.parts["provider"].usage_total
        try:
            proposal = await operator.propose(request)
        except OperatorFailure as failure:
            self._check_provider_floor(intent, provider_before, failure.cost)
            self._known_cost += _tokens(failure.cost)
            self._call_cost_known = True
            proposal = Proposal(Candidate(candidate_id, parents, operator=selected, created_cycle=cycle,
                                          context_pack_ref=context["context_pack_ref"]),
                                "", failure.cost, failure.measured_cost_units)
            evidence = EvidenceRecord(candidate_id, EvalResult(
                EvalStatus.FAILED_TO_RUN, cost=CostVec(), text_feedback=str(failure),
                contract=EvaluationContract(self._binding(proposal, evaluation_request),
                    ("token", "eval_count"), binding_source="invocation")),
                executor_status="failed_to_run", result_text=str(failure))
        else:
            if isinstance(proposal, Proposal):
                self._check_provider_floor(intent, provider_before, proposal.cost)
                self._known_cost += _tokens(proposal.cost)
                self._call_cost_known = True
            if request.context.get("retrieval") != context["retrieval"] or \
                    request.context.get("context_pack_ref") != context["context_pack_ref"]:
                raise ValueError("operator changed authoritative retrieval context")
            if not isinstance(proposal, Proposal) or proposal.candidate.id != candidate_id \
                    or proposal.candidate.parents != parents or not isinstance(proposal.artifact, str):
                raise ValueError("operator proposal changed identity or lineage")
            proposal.candidate.validate()
            if proposal.candidate.context_pack_ref != context["context_pack_ref"]:
                raise ValueError("operator dropped or changed retrieval context identity")
            _tokens(proposal.cost)
            if self.layered:
                self.layered.check_integrity(proposal, self._source_refs(context))
            if self.parts.get("knowledge") is not None:
                self._call_cost_known = False
                audit = self.parts["knowledge"].audit(candidate_id, proposal.artifact)
                self._known_cost += _tokens(audit.cost)
                self._call_cost_known = True
                self.store.append("composed_knowledge_audit", {"candidate_id": candidate_id,
                                                               "audit": audit.to_dict()})
            self._call_cost_known = False
            expected_binding = self._binding(proposal, evaluation_request)
            provider_before = self.parts["provider"].usage_total
            evidence = await self.parts["executor"].execute(
                copy.deepcopy(proposal), copy.deepcopy(evaluation_request), self.parts["domain"])
            if isinstance(evidence, EvidenceRecord):
                self._check_provider_floor(intent, provider_before, evidence.eval_result.cost)
                self._known_cost += measured_costs(evidence.eval_result)["token"]
                self._call_cost_known = True
                self._validate_domain(evaluation_request)
                validate_evidence(evidence, expected_binding=expected_binding)
        if not isinstance(evidence, EvidenceRecord) or evidence.candidate_id != candidate_id:
            raise ValueError("executor evidence identity mismatch")
        validate_evidence(evidence, expected_binding=self._binding(proposal, evaluation_request))
        public = public_projection(evidence)
        mutations = await self._policy("absorb", public_projection(evidence))
        self._validate_mutations(mutations, evidence)
        evidence_ref = "sha256:" + payload_digest({"logical_run_id": self._logical_run_id,
                                                   "evidence": encode_evidence(evidence)})
        mutations = self.memory.prepare_mutations(mutations, public_projection(evidence),
                                                 evidence_ref, cycle=cycle)
        if self.layered:
            self.budget.settle(intent, self._known_cost + self._policy_tokens)
            self._current_intent = None
            decision = await self._admit_layered(proposal, evidence, context)
        else:
            decision = self.parts["admission"].judge(comparison_projection(evidence),
                       comparison_projection(self.evidence[self.incumbent]) if self.incumbent else None)
        if not isinstance(decision, Decision):
            raise ValueError("admission must return a Decision")
        if decision.admit and evidence.eval_result.status is not EvalStatus.OK:
            raise ValueError("failed execution cannot be admitted")
        total = self._known_cost + self._policy_tokens
        if self._current_intent is not None:
            self.budget.settle(intent, total, admission_outcome=decision.admit)
        self._current_intent = None
        return self._commit_cycle(cycle, proposal, evidence, decision, mutations, context, evidence_ref, evaluation_request)

    def _commit_cycle(self, cycle, proposal, evidence, decision, mutations, context, evidence_ref, evaluation_request):
        candidate_id = proposal.candidate.id
        public = public_projection(evidence)
        self.store.append("composed_evidence", {"cycle": cycle, "proposal": _jsonable(proposal),
                                                "evidence_ref": evidence_ref,
                                                "evidence": encode_evidence(evidence)["evidence"]})
        receipt = {"candidate_id": candidate_id, "incumbent": self.incumbent,
                   "evidence": _jsonable(evidence), "decision": asdict(decision)}
        # Full cost is durable evidence; decision plugins must not interpret it.
        event_id = "sha256:" + payload_digest(receipt)
        self.store.append("composed_decision", {**receipt, "event_id": event_id,
            "receipt_id": decision.receipt_id if self.layered else event_id})
        self.applier.apply(StateMutation(MutationOp.ADD_NODE, candidate_id,
                           {"candidate": proposal.candidate, "evidence": public}, "evaluated candidate"))
        self.applier.apply_all(mutations)
        lessons = [entry for entry in self.memory.entries.values()
                   if entry.provenance.source_candidate_id == candidate_id and entry.level in {"L2", "L3"}
                   and entry.state == "active" and entry.time.superseded_by is None]
        node_result = dict(self.frontier.nodes[candidate_id].result or {})
        node_result.update(memory_refs=[entry.id for entry in lessons], evidence_ref=evidence_ref,
                           context_pack_ref=context["context_pack_ref"])
        self.applier.apply(StateMutation(MutationOp.UPDATE_NODE, candidate_id,
            {"result": node_result, "insight": "\n".join(str(entry.payload.body) for entry in lessons)[:2048] or None},
            "materialize insight from evidence-bound memory"))
        self.applier.apply(StateMutation(MutationOp.MERGE if decision.admit else MutationOp.PRUNE,
                           candidate_id, {} if decision.admit else {"reason": decision.reason}, decision.reason))
        self.proposals[candidate_id], self.evidence[candidate_id] = proposal, evidence
        if decision.admit:
            self.incumbent = candidate_id
        self.eval_requests[candidate_id] = evaluation_request
        self.next_cycle = cycle + 1
        self._save()
        return True

    def run(self, task):
        self.cfg.validate()
        if self.cfg.batch_size != 1 or self.cfg.max_inflight != 1:
            raise ValueError("configured runtime currently requires serial cycles")
        if not isinstance(task, str) or not task.strip():
            raise ValueError("task must be a non-empty string")
        if not self.cfg.resume_from_checkpoint and any(self.store.read()):
            raise ValueError("non-resume evolution requires a fresh evidence workdir")
        self.registry.preflight(self.assembly)
        self.task = task
        if self.cfg.resume_from_checkpoint:
            saved = RunCheckpoint.load(self.workdir / "checkpoint.json").payload
            if saved.get("runtime") != "composed-v5" or not isinstance(saved.get("logical_run_id"), str) \
                    or not saved["logical_run_id"]:
                raise ValueError("composed checkpoint runtime has no scoped run identity")
            self._logical_run_id = saved["logical_run_id"]
        elif self._logical_run_id is None:
            self._logical_run_id = uuid.uuid4().hex
        try:
            self._seed = _copy_sources({"llm": self.llm, "evaluator": self.evaluator})
        except Exception:
            self._seed = None
        self._build(task)
        if self.cfg.resume_from_checkpoint:
            self._restore()
        else:
            self.store.append("run_start", {"runtime": "composed-v5", "task_desc": task,
                                           "manifest": self.manifest, "accounting_stamp": asdict(self.stamp)})
            for spec in self.assembly.memory.options.get("imports", []):
                self.memory.import_snapshot(spec["path"], expected_sha256=spec["sha256"])
            if self.assembly.knowledge:
                for spec in self.assembly.knowledge.options.get("memory_imports", []):
                    self.parts["knowledge"].ingest_memory_export(spec["path"], expected_sha256=spec["sha256"])
            self._save()
        continued = True
        for cycle in range(self.next_cycle, self.cfg.max_generations + 1):
            if self._halted_reason is not None:
                continued = False
                break
            try:
                continued = asyncio.run(self._cycle(task, cycle))
            except UsageError:
                # Missing physical usage remains an open reservation, never free.
                raise
            except Exception as error:
                if self._current_intent is not None and self._call_cost_known:
                    self.budget.settle(self._current_intent, self._known_cost + self._policy_tokens)
                    self._current_intent = None
                    self.store.append("composed_cycle_failed", {
                        "cycle": cycle, "error_type": type(error).__name__,
                        "known_tokens": self._known_cost + self._policy_tokens})
                raise
            if not continued:
                break
            if self.cfg.stop_after_generation == cycle:
                break
        if self.next_cycle > self.cfg.max_generations or not continued:
            asyncio.run(self._finish_layered())
            self._finish_context()
        self.result = {"runtime": "composed-v5", "profile": self.assembly.name,
                       "best_candidate_id": self.incumbent,
                       "best_prompt": self.proposals[self.incumbent].artifact if self.incumbent else None,
                       "best_score": self.frontier.nodes[self.incumbent].score if self.incumbent else None,
                       "cycles": self.next_cycle, "ledger": self.budget.account_summary(),
                       "memory_export": self._context_export,
                       "reporting": self.layered.report() if self.layered else None,
                       "stop_reason": self._halted_reason,
                       "accepted_candidate_ids": [row["payload"]["candidate_id"] for row in
                            self.store.read("composed_decision") if row["payload"]["decision"]["admit"]],
                       "checkpoint_ref": payload_digest(self._payload())}
        return self.result

    def inspect(self):
        if self.result is None:
            raise RuntimeError("evolve() must run before inspect()")
        certificates = list(self.store.read("replay_certificate"))
        return {**self.result, "assembly": self.assembly.to_dict(),
                "memory_entries": len(self.memory.entries),
                "replay_certificate": certificates[-1]["payload"] if certificates else None}

    def replay(self, task=None, *, adapter_factory=None):
        if self.result is None or not self.cfg.checkpoint_enabled:
            raise RuntimeError("certified replay requires an evolved checkpointed run")
        if adapter_factory is None and self._seed is None:
            raise RuntimeError("replay requires adapter_factory for uncopyable adapters")
        self._verify_context_export(self._context_export)
        root = self.workdir / "replays"
        root.mkdir(exist_ok=True)
        path = Path(tempfile.mkdtemp(prefix="replay-", dir=root))
        store = AppendOnlyStore(path / "x1.jsonl")
        certificate = {"passed": False, "runtime": "composed-v5", "mode": "independent_rerun",
                       "replay_workdir": str(path.resolve()), "replay_id": path.name}
        try:
            if adapter_factory:
                llm, evaluator = adapter_factory(str(path), store)
                if any(value is old and not isinstance(old, FunctionType)
                       for value, old in ((llm, self.llm), (evaluator, self.evaluator))):
                    raise ValueError("replay cannot share live adapters")
            else:
                sources = _copy_sources(self._seed)
                llm, evaluator = sources["llm"], sources["evaluator"]
            clone = type(self)(self.assembly, self.registry, llm, evaluator,
                              replace(self.cfg, resume_from_checkpoint=False, stop_after_generation=None),
                              path, self.stamp)
            clone._forbidden_parts = self.parts
            clone._logical_run_id = self._logical_run_id
            result = clone.run(task or self.task)
            original = RunCheckpoint.load(self.workdir / "checkpoint.json").payload
            copied = RunCheckpoint.load(path / "checkpoint.json").payload
            certificate["snapshot_match"] = original == copied
            certificate["result_match"] = all(result[key] == self.result[key]
                                               for key in self.result if key != "replay_certificate")
            certificate["passed"] = certificate["snapshot_match"] and certificate["result_match"]
        except Exception as error:
            certificate["error_type"] = type(error).__name__
            store.append("replay_certificate", certificate)
            self.store.append("replay_certificate", certificate)
            raise RuntimeError("configured replay execution failed") from error
        store.append("replay_certificate", certificate)
        self.store.append("replay_certificate", certificate)
        if not certificate["passed"]:
            raise RuntimeError("configured replay mismatch")
        result["replay_certificate"] = certificate
        return result
