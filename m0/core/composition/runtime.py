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
from dataclasses import asdict, replace
from pathlib import Path
from types import FunctionType

from core.composition.contracts import AssemblyConfig, BuildContext, Decision, OperatorRequest, Proposal
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
    return Proposal(Candidate(**data["candidate"]), data["artifact"], CostVec(**data["cost"]))


def _copy_sources(sources):
    copied = copy.deepcopy(sources)
    for key, value in sources.items():
        if value is not None and copied[key] is value and not isinstance(value, FunctionType):
            raise ValueError("replay cannot share live adapters")
    return copied


class ComposedRuntime:
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

    def _build(self, task):
        scope = ScopeContext(_id("composed", self.assembly.name, task), _id("task", task),
                             self.assembly.domain.name)
        context = BuildContext(self.llm, self.evaluator, self.store, scope,
                               self.cfg, str(self.workdir), self.stamp)
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
                    "admission": ("judge",), "budget": ("quote_reserve", "settle", "account_summary")}
        for kind, methods in required.items():
            if any(not callable(getattr(self.parts[kind], name, None)) for name in methods):
                raise ValueError(f"component {kind} does not implement its runtime contract")
        for operator in self.parts["operators"]:
            if not callable(getattr(operator, "propose", None)):
                raise ValueError("operator does not implement propose")
        self.frontier, self.memory = self.parts["frontier"], self.parts["memory"]
        from core.composition.defaults import LegacyPromptDomain, MetricAdmission, PromptOperator
        if isinstance(self.parts["domain"], LegacyPromptDomain):
            expected_metric = self.parts["domain"].metric
            if self.frontier.metric != expected_metric or any(
                    isinstance(operator, PromptOperator) and operator.metric != expected_metric
                    for operator in self.parts["operators"]):
                raise ValueError("configured objective differs across domain/frontier/operators")
            admission = self.parts["admission"]
            if isinstance(admission, MetricAdmission) and (
                    admission.metric != expected_metric or admission.direction != self.frontier.direction):
                raise ValueError("configured admission objective differs from exploration")
        self.applier = StateApplier(self.frontier, self.memory, self.store)
        self.budget = self.parts["budget"]
        preflight = getattr(self.parts["domain"], "validate_context", None)
        if callable(preflight):
            preflight()
        self.manifest = {"assembly": self.assembly.to_dict(),
                         "provider_model": getattr(self.parts["provider"], "model", None),
                         "domain_version": getattr(self.parts["domain"], "evaluator_version", None),
                         "evaluation_context": getattr(self.parts["domain"], "evaluation_context", "")}
        self._validate_domain(EvalRequest("dev"))

    def _validate_domain(self, request):
        validate_request(request)
        domain = self.parts["domain"]
        check = getattr(domain, "validate_context", None)
        if callable(check):
            check()
        check = getattr(domain, "validate_request", None)
        if not callable(check):
            raise ValueError("domain must explicitly validate supported evaluation requests")
        check(request)
        if (getattr(domain, "evaluator_version", None) != self.manifest["domain_version"]
                or getattr(domain, "evaluation_context", "") != self.manifest["evaluation_context"]):
            raise ValueError("domain identity changed during configured execution")
        self._binding(Proposal(Candidate("preflight"), ""), request)

    def _binding(self, proposal, request):
        return binding_for(proposal, request,
                           evaluator_version=self.manifest["domain_version"],
                           evaluation_context=self.manifest["evaluation_context"])

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
        return {"runtime": "composed-v2", "manifest": self.manifest, "config": config,
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
            if self.budget.reserves:
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
        expected = {"runtime": "composed-v2", "manifest": self.manifest,
                    "task_desc": self.task, "config": config}
        for field in ("runtime", "manifest", "task_desc", "config"):
            if payload.get(field) != expected[field]:
                raise ValueError(f"composed checkpoint {field} is incompatible")
        if any(row["payload"]["cycle"] >= payload["next_cycle"]
               for row in self.store.read("composed_cycle_started")):
            raise RuntimeError("unfinished composed cycle requires durable adoption; refusing reexecution")
        proposals = {key: _proposal(value) for key, value in payload["proposals"].items()}
        evidence_by_id = {key: _evidence(value) for key, value in payload["evidence"].items()}
        if set(proposals) != set(evidence_by_id):
            raise ValueError("checkpoint proposal and evidence identities differ")
        for key, evidence in evidence_by_id.items():
            if proposals[key].candidate.id != key or evidence.candidate_id != key:
                raise ValueError("checkpoint candidate key differs from evidence identity")
            validate_evidence(evidence, expected_binding=self._binding(proposals[key], EvalRequest("dev")))
        self.budget.restore_from_journal()
        if self.budget.reserves or self.budget.account_summary() != payload["ledger"]:
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
        self.incumbent, self.next_cycle = payload["incumbent"], payload["next_cycle"]
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
        return {}

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

    async def _cycle(self, task, cycle):
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
        state = {"task": task, "cycle": cycle, "frontier": json.loads(self.frontier.view("json")),
                 "operators": [spec.name for spec in self.assembly.operators]}
        strategy = await self._policy("observe", state, self.budget.account_summary())
        if not isinstance(strategy, dict):
            raise ValueError("policy observe must return a strategy object")
        selection_view = ResearchFrontier.restore(self.frontier.checkpoint())
        parents = await self._policy("select", selection_view, self.budget.account_summary())
        eligible_parents = {node.id for node in self.frontier.nodes.values()
                            if node.status in {"done", "merged"}
                            and node.eval_status == EvalStatus.OK.value
                            and node.score is not None}
        if not isinstance(parents, list) or len(parents) > 2 \
                or any(type(parent) is not str for parent in parents) \
                or len(set(parents)) != len(parents) \
                or any(parent not in self.proposals or parent not in eligible_parents
                       for parent in parents):
            raise ValueError("policy selected invalid parents")
        hypotheses = await self._policy("ideate", copy.deepcopy(strategy),
                                        copy.deepcopy(self.proposals[parents[0]]) if parents else None, 1)
        strategy = {**strategy, "hypotheses": hypotheses}
        context = self._context(task, cycle, parents)
        request = OperatorRequest(task, candidate_id, cycle,
                                  tuple(copy.deepcopy(self.proposals[p]) for p in parents),
                                  tuple(public_projection(self.evidence[p]) for p in parents), context, strategy)
        for skill in self.parts["skills"]:
            before = self.parts["provider"].usage_total
            try:
                request = skill.apply(request)
            finally:
                self._policy_tokens += self.parts["provider"].usage_total - before
            if not isinstance(request, OperatorRequest) or request.candidate_id != candidate_id:
                raise ValueError("skill changed candidate identity")
        names = [spec.name for spec in self.assembly.operators]
        selected = strategy.get("operator", names[min(1 if parents else 0, len(names)-1)])
        if selected not in names:
            raise ValueError("policy selected an unregistered operator")
        operator = self.parts["operators"][names.index(selected)]
        self._call_cost_known = False
        try:
            proposal = await operator.propose(request)
        except OperatorFailure as failure:
            self._known_cost += _tokens(failure.cost)
            self._call_cost_known = True
            proposal = Proposal(Candidate(candidate_id, parents, operator=selected, created_cycle=cycle),
                                "", failure.cost)
            evidence = EvidenceRecord(candidate_id, EvalResult(
                EvalStatus.FAILED_TO_RUN, cost=CostVec(), text_feedback=str(failure),
                contract=EvaluationContract(self._binding(proposal, evaluation_request),
                    ("token", "eval_count"), binding_source="invocation")),
                executor_status="failed_to_run", result_text=str(failure))
        else:
            if isinstance(proposal, Proposal):
                self._known_cost += _tokens(proposal.cost)
                self._call_cost_known = True
            if not isinstance(proposal, Proposal) or proposal.candidate.id != candidate_id \
                    or proposal.candidate.parents != parents or not isinstance(proposal.artifact, str):
                raise ValueError("operator proposal changed identity or lineage")
            proposal.candidate.validate()
            _tokens(proposal.cost)
            self._call_cost_known = False
            evidence = await self.parts["executor"].execute(
                proposal, evaluation_request, self.parts["domain"])
            if isinstance(evidence, EvidenceRecord):
                self._known_cost += measured_costs(evidence.eval_result)["token"]
                self._call_cost_known = True
        if not isinstance(evidence, EvidenceRecord) or evidence.candidate_id != candidate_id:
            raise ValueError("executor evidence identity mismatch")
        validate_evidence(evidence, expected_binding=self._binding(proposal, evaluation_request))
        public = public_projection(evidence)
        mutations = await self._policy("absorb", public_projection(evidence))
        self._validate_mutations(mutations, evidence)
        # A detached copy prevents admission from mutating execution evidence.
        decision = self.parts["admission"].judge(comparison_projection(evidence),
                   comparison_projection(self.evidence[self.incumbent]) if self.incumbent else None)
        if not isinstance(decision, Decision):
            raise ValueError("admission must return a Decision")
        if decision.admit and evidence.eval_result.status is not EvalStatus.OK:
            raise ValueError("failed execution cannot be admitted")
        total = _tokens(proposal.cost) + _tokens(evidence.eval_result.cost) + self._policy_tokens
        self.budget.settle(intent, total, admission_outcome=decision.admit)
        self._current_intent = None
        self.store.append("composed_evidence", {"cycle": cycle, "proposal": _jsonable(proposal),
                                                "evidence": encode_evidence(evidence)["evidence"]})
        receipt = {"candidate_id": candidate_id, "incumbent": self.incumbent,
                   "evidence": _jsonable(evidence), "decision": asdict(decision)}
        # Full cost is durable evidence; decision plugins must not interpret it.
        self.store.append("composed_decision", {**receipt, "receipt_id": "sha256:"+payload_digest(receipt)})
        self.applier.apply(StateMutation(MutationOp.ADD_NODE, candidate_id,
                           {"candidate": proposal.candidate, "evidence": public}, "evaluated candidate"))
        self.applier.apply_all(mutations)
        self.applier.apply(StateMutation(MutationOp.MERGE if decision.admit else MutationOp.PRUNE,
                           candidate_id, {} if decision.admit else {"reason": decision.reason}, decision.reason))
        self.proposals[candidate_id], self.evidence[candidate_id] = proposal, evidence
        if decision.admit:
            self.incumbent = candidate_id
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
        try:
            self._seed = _copy_sources({"llm": self.llm, "evaluator": self.evaluator})
        except Exception:
            self._seed = None
        self._build(task)
        if self.cfg.resume_from_checkpoint:
            self._restore()
        else:
            self.store.append("run_start", {"runtime": "composed-v2", "task_desc": task,
                                           "manifest": self.manifest, "accounting_stamp": asdict(self.stamp)})
            self._save()
        for cycle in range(self.next_cycle, self.cfg.max_generations + 1):
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
        self.result = {"runtime": "composed-v2", "profile": self.assembly.name,
                       "best_candidate_id": self.incumbent,
                       "best_prompt": self.proposals[self.incumbent].artifact if self.incumbent else None,
                       "best_score": self.frontier.nodes[self.incumbent].score if self.incumbent else None,
                       "cycles": self.next_cycle, "ledger": self.budget.account_summary(),
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
        root = self.workdir / "replays"
        root.mkdir(exist_ok=True)
        path = Path(tempfile.mkdtemp(prefix="replay-", dir=root))
        store = AppendOnlyStore(path / "x1.jsonl")
        certificate = {"passed": False, "runtime": "composed-v2", "mode": "independent_rerun",
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
