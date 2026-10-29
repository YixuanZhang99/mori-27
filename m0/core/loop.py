"""M0 loop: K1-K6 with metering, deterministic replay and cycle recovery."""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from core.archive import ArchiveEntry, IslandArchive
from core.budget.ledger import BudgetError, BudgetLedger
from core.budget.probe import M3HealthProbe
from core.budget.types import COST_ACCOUNTS, AccountingStamp
from core.eval.decision import AdmissionDecision
from core.eval.gate import AdmissionGate, stop_action
from core.eval.types import EvalResult, ItemResult, ReliabilityMeta, validate_eval_result
from core.executor.external import ExternalCommandEvaluator, ExternalEvaluatorError
from core.executor.m0 import (M0PromptExecutor, inprocess_evaluation_operation_state,
                              proposal_operation_state)
from core.executor.pool import ExecutorPool
from core.executor.proposal import ExternalCommandLLM
from core.executor.types import (Candidate, EvalRequest, EvalResult as ExecutorEvalResult,
                                 EvalStatus, EvidenceRecord, ExecutorSpec)
from core.extensions import ExtensionRegistry
from core.frontier import ResearchFrontier
from core.llm import UsageError, reset_usage, take_usage, validate_usage
from core.memory import ScopeContext, ScopedMemory
from core.map_elites import MapElitesArchive
from core.operator.ops import draft, evolve_block_improve, reflective_improve
from core.operator.types import FunnelRecord, OperatorSpec, VariationProposal
from core.orchestration import BatchScheduler
from core.policy import BestFirstPolicy, MutationOp, StateMutation
from core.policy.scheduler import make_intent, reissue
from core.policy.types import AllocationIntent
from core.state import StateApplier, _jsonable
from core.x1.audit import audit_governance, receipt_chain_sha256
from core.x1.checkpoint import RunCheckpoint, certified_snapshot_ref
from core.x1.store import AppendOnlyStore


@dataclass
class LoopConfig:
    total_budget: int = 60_000
    control_share: float = 0.05
    reeval_floor: int = 1_000
    intent_cost: int = 1_000             # reserve estimate; actual metered cost settles
    baseline_every: int = 5
    noise_floor: float = 0.0
    max_generations: int = 50
    checkpoint_enabled: bool = True
    resume_from_checkpoint: bool = False
    stop_after_generation: int | None = None  # clean cycle-boundary stop; None = run to budget/end
    batch_size: int = 1                     # >1 opts into canonical frozen-cohort M7 scheduling
    max_inflight: int = 1                   # shared global token meters remain serialized


def _stable_id(*parts) -> str:
    return hashlib.sha256("\0".join(str(part) for part in parts).encode()).hexdigest()[:12]


def _evaluation_start_sha256(context: dict) -> str:
    canonical = json.dumps(context, sort_keys=True, ensure_ascii=False,
                           separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _inprocess_evaluation_execution_id(context: dict) -> str:
    digest = _evaluation_start_sha256(context).split(":", 1)[1]
    return "m0-inprocess-evaluation-" + hashlib.sha256(
        f"{context['proposal']['proposal_id']}\0{digest}".encode("utf-8")).hexdigest()


def _self_attestation(best_score: float, baseline_scores: list[float],
                      noise_floor: float) -> dict:
    """Report B1 honestly; this terminal display never participates in admission."""
    values = [best_score, *baseline_scores]
    if any(isinstance(value, bool) or not isinstance(value, (int, float))
           or not math.isfinite(value) for value in values):
        raise ValueError("self-attestation scores must be finite numbers")
    evidence = {
        "comparison": "best_score_minus_iid_rs_mean",
        "best_score": float(best_score),
        "baseline_count": len(baseline_scores),
        "baseline_mean": None,
        "increment": None,
        "noise_floor": float(noise_floor),
        "noise_floor_source": "LoopConfig.noise_floor",
        "verdict": "INSUFFICIENT_EVIDENCE",
    }
    if not baseline_scores:
        return evidence
    baseline_mean = sum(baseline_scores) / len(baseline_scores)
    increment = float(best_score - baseline_mean)
    if increment > noise_floor:
        verdict = "PASS"
    elif increment < -noise_floor:
        verdict = "FAIL"
    else:
        verdict = "INADJUDICABLE"
    evidence.update(baseline_mean=baseline_mean, increment=increment, verdict=verdict)
    return evidence


def _result_data(result: EvalResult) -> dict:
    return asdict(result)


def _restore_result(data: dict, **bindings) -> EvalResult:
    reliability = dict(data.get("reliability") or {})
    if reliability.get("ci95") is not None:
        reliability["ci95"] = tuple(reliability["ci95"])
    return validate_eval_result(EvalResult(
        candidate_id=data["candidate_id"], head_sha=data["head_sha"],
        items=[ItemResult(**item) for item in data["items"]],
        combined_score=data.get("combined_score", 0.0),
        public=data.get("public", {}), private=data.get("private", {}),
        text_feedback=data.get("text_feedback", ""),
        reliability=ReliabilityMeta(**reliability),
        evaluator_version=data["evaluator_version"]), **bindings)


def _evidence_from_result(candidate_id: str, result: EvalResult) -> EvidenceRecord:
    """Adapt M0 display evaluation to the canonical M7 evidence boundary."""
    executed = ExecutorEvalResult(
        EvalStatus.OK, {"dev/score": float(result.combined_score)},
        text_feedback=result.text_feedback)
    return EvidenceRecord(candidate_id, executed, executor_status="scored",
                          attempt=1, result_text=result.text_feedback)


def _extension_name(extension) -> str:
    cls = type(extension)
    return f"{cls.__module__}.{cls.__qualname__}"


class Framework:
    """Public surface: evolve / inspect / replay (RUBRIC A1)."""

    def __init__(self, llm, evaluator, config: LoopConfig, workdir: str,
                 extensions: list | None = None, profile_name: str = "m0_default",
                 archive: IslandArchive | MapElitesArchive | None = None,
                 improve_impl: str = "llm_reflective",
                 accounting_stamp: AccountingStamp | None = None):
        self.llm = llm
        self.evaluator = evaluator  # callable(candidate_id, head_sha, prompt) -> EvalResult
        self.cfg = config
        self.workdir = workdir
        self.profile_name = profile_name
        self.archive = archive
        self.improve_impl = improve_impl
        self.registry = ExtensionRegistry()
        for extension in extensions or []:
            self.registry.register(extension)
        self.store = AppendOnlyStore(f"{workdir}/x1.jsonl")
        def metadata(name):
            value = getattr(llm, name, None)
            return value if isinstance(value, str) and value.strip() else "unavailable"

        self.stamp = accounting_stamp or AccountingStamp(
            supplier=metadata("supplier"), model_version=metadata("model"),
            tokenizer_version="unavailable", price_table_version="unavailable",
            date="unavailable")
        if not isinstance(self.stamp, AccountingStamp) or any(
                not isinstance(value, str) or not value.strip()
                for value in asdict(self.stamp).values()):
            raise ValueError("accounting_stamp requires non-empty string metadata")
        if config.resume_from_checkpoint:
            starts = list(self.store.read("run_start"))
            if starts and starts[0]["payload"].get("accounting_stamp") is not None:
                persisted = AccountingStamp(**starts[0]["payload"]["accounting_stamp"])
                if any(not isinstance(value, str) or not value.strip()
                       for value in asdict(persisted).values()):
                    raise ValueError("original accounting stamp is invalid")
                if accounting_stamp is not None and accounting_stamp != persisted:
                    raise ValueError("accounting_stamp differs from the original run")
                if accounting_stamp is None and any(
                        metadata(name) != "unavailable"
                        and getattr(persisted, field) != "unavailable"
                        and metadata(name) != getattr(persisted, field)
                        for name, field in (("supplier", "supplier"), ("model", "model_version"))):
                    raise ValueError("provider metadata differs from the original accounting stamp")
                self.stamp = persisted
        self._last_result: dict | None = None
        self._last_task_desc: str | None = None

    @classmethod
    def from_profile(cls, name: str, llm, evaluator, config: LoopConfig, workdir: str,
                     *, accounting_stamp: AccountingStamp | None = None):
        from core.profiles import extensions_for, load_profile
        profile = load_profile(name)
        pool_cfg = profile["parent_pool"]
        archive = None
        if pool_cfg["structure"] == "islands":
            archive = IslandArchive(num_islands=pool_cfg.get("num_islands", 2),
                                    migration_interval=pool_cfg.get("migration_interval", 3))
        elif pool_cfg["structure"] == "map_elites":
            archive = MapElitesArchive.from_config(pool_cfg)
        return cls(llm, evaluator, config, workdir,
                   extensions=extensions_for(profile), profile_name=name,
                   archive=archive,
                   improve_impl=profile["operators"]["improve"],
                   accounting_stamp=accounting_stamp)

    def _proposal_id(self, task_desc: str, slot: str) -> str:
        return _stable_id(self.profile_name, task_desc, slot)

    def evolve(self, task_desc: str) -> dict:
        cfg = self.cfg
        if cfg.resume_from_checkpoint and not cfg.checkpoint_enabled:
            raise ValueError("resume requires checkpoint_enabled=True")
        if cfg.stop_after_generation is not None and cfg.stop_after_generation < 0:
            raise ValueError("stop_after_generation cannot be negative")
        if isinstance(cfg.noise_floor, bool) \
                or not isinstance(cfg.noise_floor, (int, float)) \
                or not math.isfinite(cfg.noise_floor) or cfg.noise_floor < 0:
            raise ValueError("noise_floor must be a finite non-negative number")
        for name in ("batch_size", "max_inflight"):
            value = getattr(cfg, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if not cfg.resume_from_checkpoint and any(self.store.read()):
            raise ValueError("non-resume evolution requires a fresh evidence workdir")
        checkpoint_path = Path(self.workdir) / "checkpoint.json"
        ledger = BudgetLedger(cfg.total_budget, cfg.control_share,
                              cfg.reeval_floor, self.stamp, self.store)
        gate = AdmissionGate(self.store, noise_floor=cfg.noise_floor)
        context = ScopeContext(_stable_id("run", self.profile_name, task_desc),
                               _stable_id("task", task_desc), "m0")
        frontier = ResearchFrontier(
            store=self.store,
            git_state={"kind": "non_git_m0_workdir", "head": None, "branch": None},
            messages=[{"role": "run", "content": task_desc}])
        memory = ScopedMemory(self.store)
        policy = BestFirstPolicy(context)
        applier = StateApplier(frontier, memory, self.store)
        spec_draft = OperatorSpec("draft-0", "draft", prompt_version="1")
        spec_improve = OperatorSpec("improve-0", "improve", prompt_version="1")
        pool: list[dict] = []
        funnels: list[FunnelRecord] = []
        baseline_scores: list[float] = []
        main_scores: list[float] = []
        accepted_candidate_ids: list[str] = []
        incumbent: dict | None = None
        next_generation = 1
        checkpoint_hash = ""
        checkpoint_mutation_count = 0
        resumed = False
        stopped_early = False
        recovered_external: dict[int, dict] = {}
        recovered_control: dict[int, dict] = {}
        recovered_batch: dict[int, str] = {}
        recovery_adoptions: dict[int, dict] = {}
        extensions = self.registry.admission + self.registry.parent_monitors

        def extension_states():
            return [{"type": _extension_name(extension),
                     "state": extension.checkpoint_state()
                     if hasattr(extension, "checkpoint_state") else None}
                    for extension in extensions]

        def archive_state():
            if self.archive is None:
                return None
            if isinstance(self.archive, MapElitesArchive):
                return self.archive.checkpoint_state()
            return {"num_islands": self.archive.num_islands,
                    "migration_interval": self.archive.migration_interval,
                    "migration_count": self.archive.migration_count,
                    "entries": [{**asdict(entry), "island_ids": sorted(entry.island_ids)}
                                for entry in self.archive.entries.values()]}

        def save_checkpoint(after_generation: int) -> None:
            nonlocal checkpoint_hash, next_generation
            next_generation = after_generation
            if not cfg.checkpoint_enabled:
                return
            if ledger.reserves:
                raise RuntimeError("cycle checkpoint cannot contain open budget reserves")
            if any(node.status == "running" for node in frontier.nodes.values()):
                raise RuntimeError("cycle checkpoint cannot contain inflight frontier nodes")
            payload = {
                "git_state": {"kind": "non_git_m0_workdir", "head": None, "branch": None},
                "inflight_executor": [], "messages": [{"role": "run", "content": task_desc}],
                "config": asdict(cfg), "task_desc": task_desc,
                "profile": self.profile_name, "improve_impl": self.improve_impl,
                "next_generation": after_generation,
                "pool": [{"candidate_id": cand["candidate_id"], "prompt": cand["prompt"],
                          "score": cand["score"], "result": _result_data(cand["result"])}
                         for cand in pool],
                "incumbent_id": incumbent["candidate_id"] if incumbent else None,
                "frontier_checkpoint": frontier.checkpoint().decode("utf-8"),
                "memory": memory.checkpoint_state(),
                "funnels": [asdict(funnel) for funnel in funnels],
                "baseline_scores": baseline_scores, "main_scores": main_scores,
                "accepted_candidate_ids": accepted_candidate_ids,
                "state_mutation_count": len(list(self.store.read("state_mutation"))),
                "ledger": {"spent": ledger.spent,
                           "settled_intents": sorted(ledger.settled_intents),
                           "locked_control": ledger.locked_control},
                "archive": archive_state(), "extensions": extension_states()}
            checkpoint = RunCheckpoint.create(payload)
            checkpoint.save(checkpoint_path)
            checkpoint_hash = checkpoint.payload_sha256
            self.store.append("run_checkpoint", {
                "next_generation": after_generation,
                "payload_sha256": checkpoint_hash, "inflight_executor": []})

        def restore_checkpoint() -> None:
            nonlocal pool, funnels, baseline_scores, main_scores, accepted_candidate_ids
            nonlocal incumbent, next_generation, checkpoint_hash, checkpoint_mutation_count
            nonlocal resumed, frontier, memory, applier
            checkpoint = RunCheckpoint.load(checkpoint_path)
            payload = checkpoint.payload
            ignored = {"resume_from_checkpoint", "stop_after_generation"}
            expected = {key: value for key, value in asdict(cfg).items() if key not in ignored}
            actual = {key: value for key, value in payload["config"].items() if key not in ignored}
            if actual != expected:
                raise ValueError("checkpoint LoopConfig is incompatible with resume")
            if (payload["task_desc"] != task_desc or payload["profile"] != self.profile_name
                    or payload["improve_impl"] != self.improve_impl):
                raise ValueError("checkpoint task/profile is incompatible with resume")
            if not isinstance(payload.get("frontier_checkpoint"), str) or not isinstance(
                    payload.get("memory"), dict):
                raise ValueError("checkpoint governed frontier/memory state is incomplete")
            frontier = ResearchFrontier.restore(
                payload["frontier_checkpoint"].encode("utf-8"), store=self.store)
            memory = ScopedMemory(self.store)
            memory.restore_state(payload["memory"])
            applier = StateApplier(frontier, memory, self.store)
            pool = [{"candidate_id": cand["candidate_id"], "prompt": cand["prompt"],
                     "score": cand["score"], "result": _restore_result(
                         cand["result"], candidate_id=cand["candidate_id"],
                         head_sha=_stable_id(cand["candidate_id"], cand["prompt"])[:8],
                         evaluator_version=getattr(self.evaluator, "evaluator_version", None))}
                    for cand in payload["pool"]]
            incumbent = next(cand for cand in pool
                             if cand["candidate_id"] == payload["incumbent_id"])
            funnels = [FunnelRecord(**funnel) for funnel in payload["funnels"]]
            baseline_scores = list(payload["baseline_scores"])
            main_scores = list(payload["main_scores"])
            accepted_candidate_ids = list(payload["accepted_candidate_ids"])
            spent = payload["ledger"]["spent"]
            if set(spent) != set(COST_ACCOUNTS):
                raise ValueError("checkpoint ledger accounts are incomplete")
            next_generation = payload["next_generation"]
            if not isinstance(next_generation, int) or next_generation < 1:
                raise ValueError("invalid checkpoint generation")
            saved_settled = set(payload["ledger"]["settled_intents"])
            ledger.restore_from_journal()
            open_by_account = {account: 0.0 for account in COST_ACCOUNTS}
            for reserve in ledger.reserves.values():
                # The interrupted intent's account is recovered from its journal entry.
                for record in self.store.read("ledger"):
                    entry = record["payload"]
                    if entry["intent_id"] == reserve.intent_id \
                            and entry["entry_kind"] == "reserve":
                        open_by_account[entry["account"]] += reserve.amount
                        break
            extra_settled = ledger.settled_intents - saved_settled
            native_intents = set()
            process_intents = set()
            if isinstance(self.evaluator, ExternalCommandEvaluator):
                outcomes = {row["payload"].get("execution_id")
                            for row in self.store.read("external_evaluator_outcome")}
                for process in self.evaluator.processes.started():
                    if process.get("process_kind", "m0_external_evaluator") \
                            != "m0_external_evaluator":
                        continue
                    context = process.get("evaluation_context") or {}
                    generation = context.get("generation")
                    operator = context.get("operator")
                    recoverable_window = generation == next_generation \
                        and operator in {"improve", "iid_rs"}
                    if recoverable_window:
                        intent_id = (context.get("intent") or {}).get("intent_id")
                        process_intents.add(intent_id)
                        if process["execution_id"] in outcomes:
                            native_intents.add(intent_id)
            if isinstance(self.evaluator, ExternalCommandEvaluator):
                for row in self.store.read("m0_evaluation_started"):
                    context = row["payload"]
                    if context.get("generation") == next_generation \
                            and context.get("operator") in {"improve", "iid_rs"}:
                        process_intents.add((context.get("intent") or {}).get("intent_id"))
                proposal_markers = [row["payload"] for row in self.store.read(
                    "m0_proposal_started")]
                for context in proposal_markers:
                    if context.get("generation") == next_generation \
                            and context.get("operator") in {"improve", "iid_rs"}:
                        process_intents.add((context.get("intent") or {}).get("intent_id"))
                for event_kind in ("external_proposer_outcome", "m0_proposal_outcome"):
                    for row in self.store.read(event_kind):
                        outcome = row["payload"]
                        if outcome.get("status") == "ok":
                            continue
                        for context in proposal_markers:
                            if context.get("generation") == next_generation \
                                    and context.get("operator") == "improve" \
                                    and context.get("candidate_id") == outcome.get("operation_id"):
                                native_intents.add((context.get("intent") or {}).get("intent_id"))
                for row in self.store.read("batch_cycle_started"):
                    cohort = row["payload"]
                    if any(candidate.get("created_cycle") == next_generation
                           for candidate in cohort.get("candidates", [])):
                        process_intents.update(
                            intent.get("intent_id") for intent in cohort.get("intents", []))
            else:
                starts = [row["payload"] for row in self.store.read(
                    "m0_evaluation_started")
                    if row["payload"].get("generation") == next_generation
                    and row["payload"].get("operator") in {"improve", "iid_rs"}]
                process_intents.update((context.get("intent") or {}).get("intent_id")
                                       for context in starts)
                outcomes = [row["payload"] for row in self.store.read(
                    "m0_evaluation_outcome")
                    if row["payload"].get("generation") == next_generation
                    and row["payload"].get("operator") in {"improve", "iid_rs"}]
                for outcome in outcomes:
                    matching = [context for context in starts
                                if _evaluation_start_sha256(context)
                                == outcome.get("start_sha256")
                                and _inprocess_evaluation_execution_id(context)
                                == outcome.get("execution_id")]
                    if len(matching) == 1:
                        native_intents.add(
                            (matching[0].get("intent") or {}).get("intent_id"))
                proposal_markers = [row["payload"] for row in self.store.read(
                    "m0_proposal_started") if row["payload"].get("generation")
                    == next_generation and row["payload"].get("operator")
                    in {"improve", "iid_rs"}]
                process_intents.update((context.get("intent") or {}).get("intent_id")
                                       for context in proposal_markers)
                for event_kind in ("external_proposer_outcome", "m0_proposal_outcome"):
                    for row in self.store.read(event_kind):
                        outcome = row["payload"]
                        if outcome.get("status") == "ok":
                            continue
                        for context in proposal_markers:
                            if context.get("operator") == "improve" \
                                    and context.get("candidate_id") == outcome.get("operation_id"):
                                native_intents.add(
                                    (context.get("intent") or {}).get("intent_id"))
                for row in self.store.read("batch_cycle_started"):
                    cohort = row["payload"]
                    if not any(candidate.get("created_cycle") == next_generation
                               for candidate in cohort.get("candidates", [])):
                        continue
                    intents_by_candidate = {
                        intent.get("candidate_ref"): intent.get("intent_id")
                        for intent in cohort.get("intents", [])}
                    process_intents.update(intents_by_candidate.values())
                    for outcome_row in self.store.read("m0_evaluation_outcome"):
                        outcome = outcome_row["payload"]
                        if outcome.get("execution_ref") == cohort.get("cohort_id") \
                                and outcome.get("candidate_id") in intents_by_candidate:
                            native_intents.add(
                                intents_by_candidate[outcome["candidate_id"]])
            if saved_settled - ledger.settled_intents:
                raise ValueError("post-checkpoint settled intents require explicit recovery")
            open_intents = set(ledger.reserves)
            if len(extra_settled) + len(open_intents) > cfg.batch_size + 1 \
                    or not extra_settled.issubset(native_intents) \
                    or not open_intents.issubset(process_intents) \
                    or extra_settled & open_intents:
                raise ValueError("post-checkpoint ledger settlement requires explicit recovery")
            expected_spent = {account: float(spent[account]) for account in COST_ACCOUNTS}
            for record in self.store.read("ledger"):
                entry = record["payload"]
                if entry["intent_id"] in extra_settled and entry["entry_kind"] == "settle":
                    expected_spent[entry["account"]] += entry["settled"]
            completed_spent = {account: ledger.spent[account] - open_by_account[account]
                               for account in COST_ACCOUNTS}
            if any(not math.isclose(completed_spent[account], expected_spent[account],
                                    rel_tol=0.0, abs_tol=1e-9) for account in COST_ACCOUNTS):
                raise ValueError("post-checkpoint ledger settlement requires explicit recovery")
            mutations = list(self.store.read("state_mutation"))
            checkpoint_mutation_count = payload.get("state_mutation_count", -1)
            if isinstance(checkpoint_mutation_count, bool) \
                    or not isinstance(checkpoint_mutation_count, int) \
                    or not -1 <= checkpoint_mutation_count <= len(mutations):
                raise ValueError("checkpoint mutation cursor is invalid")
            if ledger.locked_control != payload["ledger"]["locked_control"]:
                raise ValueError("checkpoint control lock mismatch")
            saved_archive = payload["archive"]
            if (self.archive is None) != (saved_archive is None):
                raise ValueError("checkpoint archive configuration mismatch")
            if self.archive is not None:
                if isinstance(self.archive, MapElitesArchive):
                    self.archive.restore_state(saved_archive)
                else:
                    if (self.archive.num_islands != saved_archive["num_islands"]
                            or self.archive.migration_interval
                            != saved_archive["migration_interval"]):
                        raise ValueError("checkpoint archive topology mismatch")
                    self.archive.entries = {}
                    for data in saved_archive["entries"]:
                        values = dict(data)
                        values["island_ids"] = set(values["island_ids"])
                        entry = ArchiveEntry(**values)
                        self.archive.entries[entry.candidate_id] = entry
                    self.archive.migration_count = saved_archive["migration_count"]
            states = payload["extensions"]
            if len(states) != len(extensions):
                raise ValueError("checkpoint extension set mismatch")
            for extension, state in zip(extensions, states):
                if state["type"] != _extension_name(extension):
                    raise ValueError("checkpoint extension type mismatch")
                if state["state"] is not None:
                    if not hasattr(extension, "restore_state"):
                        raise ValueError("checkpoint extension cannot restore state")
                    extension.restore_state(state["state"])
            checkpoint_hash = checkpoint.payload_sha256
            resumed = True
            self.store.append("run_resume", {
                "next_generation": next_generation,
                "payload_sha256": checkpoint_hash})

        def restore_genesis_recovery() -> None:
            """Reconstruct the empty pre-genesis state from its unique evidence anchor."""
            nonlocal next_generation, checkpoint_mutation_count, resumed
            if checkpoint_path.exists() or list(self.store.read("run_checkpoint")):
                raise RuntimeError("genesis evidence recovery requires the absence of checkpoints")
            starts = list(self.store.read("run_start"))
            evaluations = list(self.store.read("m0_evaluation_started"))
            if len(starts) != 1 or len(evaluations) != 1:
                raise RuntimeError("genesis recovery requires one run and one evaluation start")
            start = starts[0]["payload"]
            ignored = {"resume_from_checkpoint", "stop_after_generation"}
            expected = {key: value for key, value in asdict(cfg).items() if key not in ignored}
            actual = {key: value for key, value in start.get("config", {}).items()
                      if key not in ignored}
            if actual != expected or start.get("task_desc") != task_desc \
                    or start.get("profile") != self.profile_name:
                raise RuntimeError("genesis run_start is incompatible with recovery")
            context = evaluations[0]["payload"]
            if context.get("generation") != 0 or context.get("operator") != "draft" \
                    or context.get("task_desc") != task_desc:
                raise RuntimeError("genesis recovery requires its draft evaluation anchor")
            candidate_id = (context.get("proposal") or {}).get("proposal_id")
            if candidate_id != self._proposal_id(task_desc, "genesis"):
                raise RuntimeError("genesis recovery candidate differs from run lineage")
            intent = AllocationIntent(**context["intent"])
            ledger.restore_from_journal()
            if ledger.settled_intents - {intent.intent_id} \
                    or set(ledger.reserves) - {intent.intent_id}:
                raise RuntimeError("genesis recovery contains unrelated budget activity")
            if intent.intent_id not in ledger.settled_intents \
                    and intent.intent_id not in ledger.reserves:
                raise RuntimeError("genesis recovery lacks its reserve or settlement")
            next_generation = 0
            checkpoint_mutation_count = 0
            resumed = True
            self.store.append("run_resume", {
                "next_generation": 0, "payload_sha256": None,
                "recovery_anchor": "genesis_evidence"})

        def absorb_candidate(proposal, result: EvalResult, parents: list[str],
                             operator: str, generation: int,
                             recovery_start: int | None = None) -> int:
            """Apply exactly the missing canonical evidence/mutation suffix."""
            evidence = _evidence_from_result(proposal.proposal_id, result)
            candidate = Candidate(proposal.proposal_id, parents,
                                  operator=operator, created_cycle=generation)
            mutations = [StateMutation(
                MutationOp.ADD_NODE, candidate.id,
                {"candidate": candidate, "evidence": evidence},
                "materialize evaluated main-search candidate"),
                *asyncio.run(policy.absorb(evidence))]
            if recovery_start is None:
                applier.apply_all(mutations)
                return len(mutations)
            if recovery_start < 0:
                raise RuntimeError("recovery requires a checkpoint mutation cursor")
            if list(self.store.read("state_mutation_rejected")):
                raise RuntimeError("post-checkpoint rejected mutation makes recovery ambiguous")
            rows = list(self.store.read("state_mutation"))
            if len(rows) < recovery_start:
                raise RuntimeError("checkpoint mutation cursor exceeds durable history")
            suffix = [{key: value for key, value in row["payload"].items() if key != "result"}
                      for row in rows[recovery_start:]]
            expected = [_jsonable(mutation) for mutation in mutations]
            completed = min(len(suffix), len(expected))
            if suffix[:completed] != expected[:completed]:
                raise RuntimeError("post-checkpoint mutation history differs from recovery plan")
            for mutation in mutations[:completed]:
                applier.replay(mutation)
            applier.apply_all(mutations[completed:])
            return len(mutations)

        def judge_candidate(result: EvalResult, incumbent_result: EvalResult | None,
                            forced_reject: str | None, recovered: bool):
            if not recovered:
                return gate.judge(result, incumbent_result, forced_reject=forced_reject)
            receipt, evidence = gate.evaluate(result, incumbent_result, forced_reject)
            gates = [row["payload"] for row in self.store.read("gate_evidence")
                     if row["payload"].get("candidate_id") == result.candidate_id
                     and row["payload"].get("transition") == "verdict"]
            receipts = [row["payload"] for row in self.store.read("receipt")
                        if row["payload"].get("receipt_id") == receipt.receipt_id]
            if not gates and not receipts:
                self.store.append("gate_evidence", asdict(evidence))
                self.store.append("receipt", asdict(receipt))
            elif len(gates) != 1 or len(receipts) != 1 \
                    or gates[0] != asdict(evidence) or receipts[0] != asdict(receipt):
                raise RuntimeError("post-checkpoint gate history differs from recovery plan")
            return receipt

        def apply_admission(candidate_id: str, accepted: bool, receipt_id: str,
                            recovery_start: int | None = None) -> None:
            mutation = StateMutation(
                MutationOp.MERGE if accepted else MutationOp.PRUNE, candidate_id, {},
                f"M9 {receipt_id}: {'admit' if accepted else 'reject'}")
            if recovery_start is None:
                applier.apply(mutation)
            else:
                rows = list(self.store.read("state_mutation"))
                expected = _jsonable(mutation)
                if len(rows) == recovery_start:
                    applier.apply(mutation)
                elif len(rows) == recovery_start + 1:
                    actual = {key: value for key, value in rows[-1]["payload"].items()
                              if key != "result"}
                    if actual != expected:
                        raise RuntimeError("post-checkpoint admission mutation mismatch")
                    applier.replay(mutation)
                else:
                    raise RuntimeError("post-checkpoint admission mutation suffix is ambiguous")
            payload = {"candidate_id": candidate_id, "receipt_id": receipt_id,
                       "admit": accepted}
            existing = [row["payload"] for row in self.store.read("admission_receipt")
                        if row["payload"].get("candidate_id") == candidate_id]
            if not existing:
                self.store.append("admission_receipt", payload)
            elif recovery_start is None or len(existing) != 1 or existing[0] != payload:
                raise RuntimeError("duplicate or mismatched admission receipt")

        def append_execution_failure(candidate_id: str, status: EvalStatus, detail: str,
                                     execution_id: str | None) -> None:
            executor_status = {EvalStatus.INVALID: "invalid",
                               EvalStatus.TIMEOUT: "timeout"}.get(status, "failed_to_run")
            failed_result = ExecutorEvalResult(status, fidelity="dev", text_feedback=detail)
            evidence = EvidenceRecord(candidate_id, failed_result,
                                      executor_status=executor_status, result_text=detail)
            self.store.append("executor_evidence", {
                "evidence": {**asdict(evidence),
                             "eval_result": {**asdict(failed_result), "status": status.value}},
                "outcome": status.value, "detail": detail, "execution_id": execution_id})

        def execute(intent, op_fn, funnel: FunnelRecord):
            """Shared K2/K3/K4 path: reserve -> R4 low-tier reissue -> meter -> settle."""
            while True:
                receipt = ledger.quote_reserve(intent)
                if receipt.verdict == "granted":
                    break
                if receipt.verdict == "rejected_budget":
                    ledger.release_for(intent)       # R4(1): synchronous release
                    intent = reissue(intent)         # R4(2): lower tier + ttl restart
                    continue
                return None, receipt                 # conflict / invalid
            reset_usage(self.llm)
            reset_usage(self.evaluator)
            ledger.pre_call_check()                  # J4: terminate-before-call
            try:
                proposal = op_fn()
            except UsageError:
                raise
            except Exception as error:
                # A failed content/transport operation can still have a known
                # provider charge. Unknown usage raises before any settlement.
                proposer_cost = take_usage(self.llm)
                self.store.append("m0_sequential_proposal_failure", {
                    "intent": asdict(intent), "operator": funnel.operator,
                    "generation": funnel.generation,
                    "token_usage": {"total_tokens": proposer_cost},
                    "detail": f"{type(error).__name__}: {error}"[-4000:]})
                ledger.settle(intent, actual_cost=proposer_cost)
                raise
            funnel.proposed += 1
            proposer_cost = take_usage(self.llm)
            if proposal.apply_result not in ("ok", "retry_ok"):
                ledger.settle(intent, actual_cost=proposer_cost)
                return (proposal, None), receipt
            funnel.applicable += 1
            head_sha = _stable_id(proposal.proposal_id, proposal.patch_text)[:8]
            external = isinstance(self.evaluator, ExternalCommandEvaluator)
            context = {"task_desc": task_desc, "intent": asdict(intent),
                       "proposal": asdict(proposal), "head_sha": head_sha,
                       "operator": funnel.operator, "generation": funnel.generation,
                       "proposer_token_cost": proposer_cost}
            self.store.append("m0_evaluation_started", context)
            if external:
                self.evaluator.set_evaluation_context(context)
            failure = None
            expected_evaluator_version = getattr(self.evaluator, "evaluator_version", None)
            try:
                result = validate_eval_result(
                    self.evaluator(proposal.proposal_id, head_sha, proposal.patch_text),
                    candidate_id=proposal.proposal_id, head_sha=head_sha,
                    evaluator_version=expected_evaluator_version)
            except UsageError:
                raise
            except ExternalEvaluatorError as error:
                result = None
                failure = (error.status, str(error), error.execution_id)
            except Exception as error:
                result = None
                failure = (EvalStatus.FAILED_TO_RUN,
                           f"{type(error).__name__}: {error}"[-4000:], None)
            finally:
                if external:
                    self.evaluator.clear_evaluation_context()
            metered = proposer_cost + take_usage(self.llm) + take_usage(self.evaluator)
            if not external:
                execution_id = _inprocess_evaluation_execution_id(context)
                status = EvalStatus.OK if failure is None else failure[0]
                self.store.append("m0_evaluation_outcome", {
                    "schema_version": 1, "adapter": "in_process",
                    "execution_id": execution_id, "candidate_id": proposal.proposal_id,
                    "generation": funnel.generation, "operator": funnel.operator,
                    "start_sha256": _evaluation_start_sha256(context),
                    "status": status.value,
                    "detail": "in-process evaluation completed" if failure is None
                    else failure[1],
                    "result": _result_data(result) if failure is None else None,
                    "token_usage": {"total_tokens": metered - proposer_cost}})
                if failure is not None:
                    failure = (failure[0], failure[1], execution_id)
            ledger.settle(intent, actual_cost=metered)
            if failure is not None:
                status, detail, execution_id = failure
                append_execution_failure(proposal.proposal_id, status, detail, execution_id)
                return (proposal, None), receipt
            funnel.runnable += 1
            return (proposal, result), receipt

        def prepare_external_recovery() -> None:
            """Adopt native sequential or prepared batch/control evidence before checkpoint."""
            if not resumed:
                return
            external = isinstance(self.evaluator, ExternalCommandEvaluator)
            processes = ([record for record in self.evaluator.processes.started()
                          if record.get("process_kind", "m0_external_evaluator")
                          == "m0_external_evaluator"] if external else [])

            def native_adoption(record, start, expected_operator, expected_id):
                context = record.get("evaluation_context") or {}
                if context != start or context.get("operator") != expected_operator \
                        or context.get("task_desc") != task_desc:
                    raise RuntimeError("external recovery context does not match its M0 start")
                candidate_id = (context.get("proposal") or {}).get("proposal_id")
                if candidate_id != expected_id:
                    raise RuntimeError("external recovery candidate differs from checkpoint lineage")
                intent = AllocationIntent(**context["intent"])
                settled = intent.intent_id in ledger.settled_intents
                reserve = ledger.reserves.get(intent.intent_id)
                if not settled and (reserve is None or reserve.amount != intent.requested):
                    raise RuntimeError("recovered external intent lacks its exact open reserve")
                if settled and checkpoint_mutation_count < 0:
                    raise RuntimeError("post-settlement recovery requires a checkpoint mutation cursor")
                if not settled:
                    for kind in ("gate_evidence", "admission_receipt", "executor_evidence",
                                 "baseline", "m0_recovery_adopted"):
                        for event in self.store.read(kind):
                            payload = event["payload"]
                            event_candidate = (payload.get("candidate_id")
                                               or (payload.get("evidence") or {}).get("candidate_id"))
                            if event_candidate == candidate_id:
                                raise RuntimeError("post-evaluation evidence precedes settlement")
                self.evaluator.recover_inflight(wait=True)
                adopted = self.evaluator.outcome(record)
                if adopted["result"] is not None:
                    validate_eval_result(
                        adopted["result"], candidate_id=candidate_id,
                        head_sha=context["head_sha"],
                        evaluator_version=getattr(self.evaluator, "evaluator_version", None))
                token_usage = validate_usage(adopted["token_usage"])["total_tokens"]
                actual = validate_usage({"total_tokens": context["proposer_token_cost"]})[
                    "total_tokens"] + token_usage
                if settled:
                    settlements = [row["payload"] for row in self.store.read("ledger")
                                   if row["payload"].get("intent_id") == intent.intent_id
                                   and row["payload"].get("entry_kind") == "settle"]
                    if len(settlements) != 1 or settlements[0]["settled"] != actual \
                            or settlements[0]["account"] != intent.account:
                        raise RuntimeError("recovered settlement differs from native outcome cost")
                return {**adopted, "settled": settled, "actual_token_cost": actual}

            def native_inprocess_adoption(start, expected_operator, expected_id):
                """Bind one exact sequential start to its durable in-process terminal result."""
                if external:
                    raise RuntimeError("in-process outcome conflicts with external evaluator")
                context = start
                if context.get("operator") != expected_operator \
                        or context.get("task_desc") != task_desc:
                    raise RuntimeError("in-process recovery context does not match its M0 start")
                candidate_id = (context.get("proposal") or {}).get("proposal_id")
                if candidate_id != expected_id:
                    raise RuntimeError("external recovery candidate differs from checkpoint lineage")
                execution_id = _inprocess_evaluation_execution_id(context)
                outcomes = [row["payload"] for row in self.store.read(
                    "m0_evaluation_outcome")
                    if row["payload"].get("execution_id") == execution_id]
                if len(outcomes) != 1:
                    raise RuntimeError("in-process evaluation has no unique terminal outcome")
                outcome = outcomes[0]
                if (outcome.get("schema_version") != 1
                        or outcome.get("adapter") != "in_process"
                        or outcome.get("candidate_id") != candidate_id
                        or outcome.get("generation") != context.get("generation")
                        or outcome.get("operator") != expected_operator
                        or outcome.get("start_sha256")
                        != _evaluation_start_sha256(context)):
                    raise RuntimeError("in-process evaluation outcome binding is invalid")
                usage = outcome.get("token_usage")
                tokens = validate_usage(usage)["total_tokens"]
                if set(usage) != {"total_tokens"}:
                    raise RuntimeError("in-process evaluation outcome has invalid token usage")
                status = outcome.get("status")
                if status not in {"ok", "failed_to_run", "timeout", "invalid"}:
                    raise RuntimeError("in-process evaluation outcome status is invalid")
                detail = outcome.get("detail")
                if not isinstance(detail, str):
                    raise RuntimeError("in-process evaluation outcome detail is invalid")
                if status == "ok":
                    try:
                        result = _restore_result(
                            outcome["result"], candidate_id=candidate_id,
                            head_sha=context["head_sha"],
                            evaluator_version=getattr(self.evaluator, "evaluator_version", None))
                    except (KeyError, TypeError, ValueError) as error:
                        if "binding mismatch" in str(error):
                            raise RuntimeError(
                                "in-process evaluation result differs from its start") from error
                        raise RuntimeError(
                            "in-process evaluation outcome result is invalid") from error
                    if result.candidate_id != candidate_id \
                            or result.head_sha != context.get("head_sha"):
                        raise RuntimeError(
                            "in-process evaluation result differs from its start")
                    error = None
                else:
                    if outcome.get("result") is not None:
                        raise RuntimeError("failed in-process outcome cannot contain a result")
                    result = None
                    status_enum = {"timeout": EvalStatus.TIMEOUT,
                                   "invalid": EvalStatus.INVALID}.get(
                                       status, EvalStatus.FAILED_TO_RUN)
                    error = ExternalEvaluatorError(status_enum, detail, execution_id)
                intent = AllocationIntent(**context["intent"])
                settled = intent.intent_id in ledger.settled_intents
                reserve = ledger.reserves.get(intent.intent_id)
                if not settled and (reserve is None or reserve.amount != intent.requested):
                    raise RuntimeError("recovered external intent lacks its exact open reserve")
                if settled and checkpoint_mutation_count < 0:
                    raise RuntimeError("post-settlement recovery requires a checkpoint mutation cursor")
                if not settled:
                    for kind in ("gate_evidence", "admission_receipt", "executor_evidence",
                                 "baseline", "m0_recovery_adopted"):
                        for event in self.store.read(kind):
                            payload = event["payload"]
                            event_candidate = (payload.get("candidate_id")
                                               or (payload.get("evidence") or {}).get("candidate_id"))
                            if event_candidate == candidate_id:
                                raise RuntimeError("post-evaluation evidence precedes settlement")
                actual = validate_usage({"total_tokens": context["proposer_token_cost"]})[
                    "total_tokens"] + tokens
                if settled:
                    settlements = [row["payload"] for row in self.store.read("ledger")
                                   if row["payload"].get("intent_id") == intent.intent_id
                                   and row["payload"].get("entry_kind") == "settle"]
                    if len(settlements) != 1 or settlements[0]["settled"] != actual \
                            or settlements[0]["account"] != intent.account:
                        raise RuntimeError("recovered settlement differs from native outcome cost")
                record = {"execution_id": execution_id, "evaluation_context": context,
                          "process_kind": "m0_inprocess_evaluator_terminal"}
                return {"record": record, "result": result, "error": error,
                        "token_usage": usage, "settled": settled,
                        "actual_token_cost": actual}

            if cfg.batch_size > 1:
                cohorts = [row["payload"] for row in self.store.read("batch_cycle_started")
                           if any(candidate.get("created_cycle") == next_generation
                                  for candidate in row["payload"].get("candidates", []))]
                if not cohorts:
                    if ledger.reserves:
                        raise RuntimeError("checkpoint resume has an unrecoverable batch gap")
                    return
                if len(cohorts) != 1:
                    raise RuntimeError("only one M0 cohort can be recovered")
                cohort = cohorts[0]
                cohort_id = cohort["cohort_id"]
                ids = cohort["candidate_ids"]
                candidates = [Candidate(**payload) for payload in cohort["candidates"]]
                expected_ids = [self._proposal_id(
                    task_desc, f"improve:{next_generation}:{slot}")
                    for slot in range(len(ids))]
                if ids != expected_ids or [candidate.id for candidate in candidates] != ids \
                        or any(candidate.created_cycle != next_generation
                               or candidate.operator != "improve" for candidate in candidates):
                    raise RuntimeError("recovered batch differs from checkpoint lineage")
                intents = [AllocationIntent(**payload) for payload in cohort["intents"]]
                if len(intents) != len(ids) \
                        or [intent.candidate_ref for intent in intents] != ids:
                    raise RuntimeError("recovered batch intents differ from its cohort")
                for intent in intents:
                    reserve = ledger.reserves.get(intent.intent_id)
                    settled = intent.intent_id in ledger.settled_intents
                    if (settled and reserve is not None) or (
                            not settled and (reserve is None
                                             or reserve.amount != intent.requested)):
                        raise RuntimeError("recovered batch reserve/settlement lifecycle is invalid")
                current = [record for record in processes
                           if record.get("execution_ref") == cohort_id]
                proposal_state = proposal_operation_state(self.store, cohort_id, ids)
                starts = proposal_state["starts"]
                markers = proposal_state["markers"]
                completed_proposals = proposal_state["completed_ids"]
                active_call = proposal_state["active_call"]
                if active_call and not isinstance(self.llm, ExternalCommandLLM):
                    raise RuntimeError("incomplete M0 proposal operation is ambiguous")
                if len(completed_proposals) < len(ids):
                    if len(markers) != len(completed_proposals) and not active_call:
                        raise RuntimeError("external M0 cohort durable proposals are incomplete")
                    if current:
                        raise RuntimeError(
                            "incomplete M0 proposals cannot have processes or settlement")
                if len({record["candidate_id"] for record in current}) != len(current) \
                        or not {record["candidate_id"] for record in current}.issubset(ids):
                    raise RuntimeError("external M0 cohort process journal is invalid")
                contexts = {record["candidate_id"]: record.get("evaluation_context")
                            for record in current}
                start_contexts = {context["proposal"]["proposal_id"]: context
                                  for context in starts}
                if external:
                    if any(candidate_id not in start_contexts
                           or contexts[candidate_id] != start_contexts[candidate_id]
                           for candidate_id in contexts):
                        raise RuntimeError("external M0 cohort recovery context mismatch")
                    self.evaluator.recover_inflight(wait=True)
                    by_candidate = {record["candidate_id"]: record for record in current}
                batch_settled = [row["payload"] for row in self.store.read(
                    "batch_execution_settled") if row["payload"].get("cohort_id") == cohort_id]
                failed_proposals = proposal_state["failed"]
                failure_sources = proposal_state["failure_sources"]
                inprocess_state = None
                if not external:
                    inprocess_state = inprocess_evaluation_operation_state(
                        self.store, cohort_id, start_contexts,
                        failed_ids=failed_proposals,
                        evaluator_version=getattr(self.evaluator, "evaluator_version", None))
                    by_candidate = inprocess_state["operations"]
                missing = set(start_contexts) - set(by_candidate)
                if missing and (batch_settled or any(
                        intent.intent_id in ledger.settled_intents for intent in intents)):
                    raise RuntimeError("partially started cohort cannot have batch settlement")
                if len({row["candidate_id"] for row in batch_settled}) != len(batch_settled):
                    raise RuntimeError("duplicate recovered batch settlement evidence")
                if set(failed_proposals) & set(by_candidate):
                    raise RuntimeError("failed proposal cannot have an evaluator execution")
                markers_by_id = {marker["candidate_id"]: marker for marker in markers}
                for candidate_id, outcome in failed_proposals.items():
                    marker = markers_by_id.get(candidate_id)
                    intent = intents[ids.index(candidate_id)]
                    candidate = candidates[ids.index(candidate_id)]
                    expected_marker = {"cohort_id": cohort_id,
                                       "generation": candidate.created_cycle,
                                       "operator": candidate.operator,
                                       "candidate_id": candidate_id,
                                       "intent": asdict(intent)}
                    if marker != expected_marker:
                        raise RuntimeError("recovered proposal failure lacks its original operation")
                    if failure_sources[candidate_id] == "in_process":
                        if isinstance(self.llm, ExternalCommandLLM):
                            raise RuntimeError("in-process outcome conflicts with external proposer")
                        continue
                    if not isinstance(self.llm, ExternalCommandLLM):
                        raise RuntimeError("external outcome requires its external proposer")
                    proposal_processes = [
                        record for record in self.llm.processes.started(cohort_id)
                        if record.get("process_kind") == "m0_external_proposer"
                        and record.get("execution_id") == outcome.get("execution_id")
                        and record.get("operation_id") == candidate_id]
                    if len(proposal_processes) != 1:
                        raise RuntimeError("recovered proposal failure lacks its original operation")
                    request_path = Path(proposal_processes[0]["request_path"])
                    request_sha = "sha256:" + hashlib.sha256(
                        request_path.read_bytes()).hexdigest()
                    if outcome.get("request_sha256") != request_sha:
                        raise RuntimeError("recovered proposal failure differs from its request")
                for candidate, intent in zip(candidates, intents):
                    settled = intent.intent_id in ledger.settled_intents
                    recorded = [row for row in batch_settled
                                if row["candidate_id"] == candidate.id]
                    if recorded and not settled:
                        raise RuntimeError("batch settlement evidence lacks its ledger settlement")
                    if recorded and recorded[0].get("intent_id") != intent.intent_id:
                        raise RuntimeError("batch settlement evidence has the wrong intent")
                    if candidate.id in failed_proposals:
                        outcome = failed_proposals[candidate.id]
                        usage = outcome.get("token_usage")
                        tokens = validate_usage(usage)["total_tokens"]
                        if set(usage) != {"total_tokens"}:
                            raise RuntimeError("recovered proposal failure has invalid token usage")
                        actual = tokens
                        if settled:
                            settlements = [row["payload"] for row in self.store.read("ledger")
                                           if row["payload"].get("intent_id") == intent.intent_id
                                           and row["payload"].get("entry_kind") == "settle"]
                            if len(settlements) != 1 or settlements[0]["settled"] != actual \
                                    or settlements[0]["account"] != intent.account:
                                raise RuntimeError(
                                    "recovered batch settlement differs from native cost")
                            status = {"timeout": EvalStatus.TIMEOUT,
                                      "invalid": EvalStatus.INVALID}.get(
                                          outcome.get("status"), EvalStatus.FAILED_TO_RUN)
                            detail = str(outcome.get("detail") or "proposal failed")[-4000:]
                            expected = M0PromptExecutor._failure(
                                candidate.id, status, detail, actual, 0.0, "dev")
                            if recorded and (
                                    recorded[0].get("evidence") != asdict(expected)
                                    or recorded[0].get("actual_token_cost") != actual
                                    or (recorded[0].get("actual_costs") or {}).get("token")
                                    != actual
                                    or recorded[0].get("status") != status.value):
                                raise RuntimeError(
                                    "recovered proposal failure differs from settled evidence")
                            ledger.reconcile_settled(intent, actual)
                        continue
                    if candidate.id not in start_contexts:
                        if settled or recorded:
                            raise RuntimeError(
                                "recovered batch candidate lacks a terminal proposal")
                        continue
                    proposal = start_contexts[candidate.id]["proposal"]
                    if proposal["parent_ids"] != candidate.parents:
                        raise RuntimeError("recovered batch proposal parent mismatch")
                    if settled:
                        if external:
                            adopted = self.evaluator.outcome(by_candidate[candidate.id])
                            token_usage = validate_usage(adopted["token_usage"])
                        else:
                            outcome = inprocess_state["outcomes"].get(candidate.id)
                            if outcome is None:
                                raise RuntimeError(
                                    "settled in-process batch candidate lacks its outcome")
                            token_usage = outcome["token_usage"]
                        actual = start_contexts[candidate.id]["proposer_token_cost"] + \
                            token_usage["total_tokens"]
                        settlements = [row["payload"] for row in self.store.read("ledger")
                                       if row["payload"].get("intent_id") == intent.intent_id
                                       and row["payload"].get("entry_kind") == "settle"]
                        if len(settlements) != 1 or settlements[0]["settled"] != actual \
                                or settlements[0]["account"] != intent.account:
                            raise RuntimeError("recovered batch settlement differs from native cost")
                        ledger.reconcile_settled(intent, actual)
                recovered_batch[next_generation] = cohort_id
                control_starts = [row["payload"] for row in self.store.read(
                    "m0_evaluation_started")
                    if row["payload"].get("generation") == next_generation
                    and row["payload"].get("operator") == "iid_rs"]
                control_current = [record for record in processes
                                   if (record.get("evaluation_context") or {}).get("generation")
                                   == next_generation
                                   and (record.get("evaluation_context") or {}).get("operator")
                                   == "iid_rs"]
                if control_starts or control_current:
                    completed = [row["payload"] for row in self.store.read(
                        "batch_cycle_completed")
                        if row["payload"].get("cohort_id") == cohort_id]
                    batch_gates = {row["payload"]["candidate_id"]
                                   for row in self.store.read("gate_evidence")
                                   if row["payload"].get("candidate_id") in set(ids)
                                   and row["payload"].get("transition") == "verdict"}
                    batch_receipts = {row["payload"]["candidate_id"]
                                      for row in self.store.read("admission_receipt")
                                      if row["payload"].get("candidate_id") in batch_gates}
                    if (next_generation < 1
                            or next_generation % cfg.baseline_every != 0
                            or len(control_starts) != 1
                            or (external and len(control_current) != 1)
                            or (not external and control_current)
                            or len(completed) != 1 or batch_receipts != batch_gates):
                        raise RuntimeError("batch/control recovery requires completed batch finalization")
                    control_id = self._proposal_id(task_desc, f"control:{next_generation}")
                    if external:
                        recovered_control[next_generation] = native_adoption(
                            control_current[0], control_starts[0], "iid_rs", control_id)
                    else:
                        recovered_control[next_generation] = native_inprocess_adoption(
                            control_starts[0], "iid_rs", control_id)
                return
            expected_operator = "draft" if next_generation == 0 else "improve"
            starts = [record["payload"] for record in self.store.read("m0_evaluation_started")
                      if record["payload"].get("generation") == next_generation
                      and record["payload"].get("operator") == expected_operator]
            current = [record for record in processes
                       if (record.get("evaluation_context") or {}).get("generation")
                       == next_generation
                       and (record.get("evaluation_context") or {}).get("operator")
                       == expected_operator]

            control_starts = [record["payload"] for record in self.store.read("m0_evaluation_started")
                              if record["payload"].get("generation") == next_generation
                              and record["payload"].get("operator") == "iid_rs"]
            control_current = [record for record in processes
                               if (record.get("evaluation_context") or {}).get("generation")
                               == next_generation
                               and (record.get("evaluation_context") or {}).get("operator")
                               == "iid_rs"]
            if control_starts or control_current:
                if cfg.batch_size != 1 or next_generation < 1 \
                        or next_generation % cfg.baseline_every != 0 \
                        or len(control_starts) != 1 or len(starts) != 1 \
                        or (external and (len(control_current) != 1 or len(current) != 1)) \
                        or (not external and (control_current or current)):
                    raise RuntimeError("only one sequential improve/control cycle can be recovered")
                improve_id = self._proposal_id(task_desc, f"improve:{next_generation}")
                control_id = self._proposal_id(task_desc, f"control:{next_generation}")
                if external:
                    recovered_external[next_generation] = native_adoption(
                        current[0], starts[0], "improve", improve_id)
                    recovered_control[next_generation] = native_adoption(
                        control_current[0], control_starts[0], "iid_rs", control_id)
                else:
                    recovered_external[next_generation] = native_inprocess_adoption(
                        starts[0], "improve", improve_id)
                    recovered_control[next_generation] = native_inprocess_adoption(
                        control_starts[0], "iid_rs", control_id)
                return
            if not current:
                if not starts:
                    if ledger.reserves:
                        raise RuntimeError("checkpoint resume has an unrecoverable evaluation gap")
                    return
                if external or cfg.batch_size != 1 or len(starts) != 1:
                    raise RuntimeError("only one sequential external candidate can be recovered")
                expected_operator = "draft" if next_generation == 0 else "improve"
                expected_id = self._proposal_id(
                    task_desc, "genesis" if next_generation == 0 else f"improve:{next_generation}")
                recovered_external[next_generation] = native_inprocess_adoption(
                    starts[0], expected_operator, expected_id)
                return
            if not external or cfg.batch_size != 1 or len(current) != 1 or len(starts) != 1:
                raise RuntimeError("only one sequential external candidate can be recovered")
            expected_operator = "draft" if next_generation == 0 else "improve"
            expected_id = self._proposal_id(
                task_desc, "genesis" if next_generation == 0 else f"improve:{next_generation}")
            recovered_external[next_generation] = native_adoption(
                current[0], starts[0], expected_operator, expected_id)

        def adopt_external_recovery(parent: dict | None, generation: int,
                                    funnel: FunnelRecord):
            adopted = recovered_external.pop(generation, None)
            if adopted is None:
                return None
            record = adopted["record"]
            context = record["evaluation_context"]
            proposal = VariationProposal(**context["proposal"])
            expected_parents = [] if parent is None else [parent["candidate_id"]]
            if proposal.parent_ids != expected_parents:
                raise RuntimeError("recovered candidate parent differs from selected lineage")
            intent = AllocationIntent(**context["intent"])
            actual = adopted["actual_token_cost"]
            if adopted["settled"]:
                if intent.intent_id not in ledger.settled_intents:
                    raise RuntimeError("recovered settlement disappeared from ledger state")
                ledger.reconcile_settled(intent, actual)
            else:
                reserve = ledger.reserves.get(intent.intent_id)
                if reserve is None or reserve.amount != intent.requested:
                    raise RuntimeError("recovered external intent lacks its exact open reserve")
                ledger.settle(intent, actual_cost=actual)
            funnel.proposed = funnel.applicable = 1
            error = adopted["error"]
            failures = [row["payload"] for row in self.store.read("executor_evidence")
                        if (row["payload"].get("evidence") or {}).get("candidate_id")
                        == proposal.proposal_id]
            if error is not None:
                if not failures:
                    append_execution_failure(proposal.proposal_id, error.status, str(error),
                                             error.execution_id)
                elif len(failures) != 1 or failures[0]["outcome"] != error.status.value \
                        or failures[0].get("execution_id") != error.execution_id \
                        or failures[0].get("detail") != str(error):
                    raise RuntimeError("recovered executor failure evidence mismatch")
            elif failures:
                raise RuntimeError("successful native outcome has failure evidence")
            else:
                funnel.runnable = 1
            payload = {
                "candidate_id": proposal.proposal_id, "intent_id": intent.intent_id,
                "execution_id": record["execution_id"], "generation": generation,
                "actual_token_cost": actual,
                "status": error.status.value if error is not None else "ok",
                "settlement_reused": adopted["settled"], "reexecuted": False}
            recovery_adoptions[generation] = payload
            return (proposal, adopted["result"]), None

        def adopt_control_recovery(generation: int, funnel: FunnelRecord) -> None:
            """Restore one IID-RS result without admitting it into research state."""
            adopted = recovered_control.pop(generation)
            record = adopted["record"]
            context = record["evaluation_context"]
            proposal = VariationProposal(**context["proposal"])
            expected_id = self._proposal_id(task_desc, f"control:{generation}")
            if proposal.proposal_id != expected_id or proposal.parent_ids:
                raise RuntimeError("recovered control candidate differs from selected lineage")
            intent = AllocationIntent(**context["intent"])
            if intent.account != "control":
                raise RuntimeError("recovered IID-RS intent must use the control account")
            actual = adopted["actual_token_cost"]
            if adopted["settled"]:
                ledger.reconcile_settled(intent, actual)
            else:
                reserve = ledger.reserves.get(intent.intent_id)
                if reserve is None or reserve.amount != intent.requested:
                    raise RuntimeError("recovered external intent lacks its exact open reserve")
                ledger.settle(intent, actual_cost=actual)
            funnel.proposed = funnel.applicable = 1
            error = adopted["error"]
            failures = [row["payload"] for row in self.store.read("executor_evidence")
                        if (row["payload"].get("evidence") or {}).get("candidate_id")
                        == proposal.proposal_id]
            baselines = [row["payload"] for row in self.store.read("baseline")
                         if row["payload"].get("generation") == generation
                         and row["payload"].get("candidate_id") == proposal.proposal_id]
            if error is not None:
                if baselines:
                    raise RuntimeError("failed control evaluation cannot have baseline evidence")
                if not failures:
                    append_execution_failure(proposal.proposal_id, error.status, str(error),
                                             error.execution_id)
                elif len(failures) != 1 or failures[0]["outcome"] != error.status.value \
                        or failures[0].get("execution_id") != error.execution_id \
                        or failures[0].get("detail") != str(error):
                    raise RuntimeError("recovered executor failure evidence mismatch")
            else:
                if failures:
                    raise RuntimeError("successful native outcome has failure evidence")
                result = adopted["result"]
                if result is None:
                    raise RuntimeError("successful control recovery lacks its native result")
                funnel.runnable = 1
                payload = {"generation": generation, "candidate_id": result.candidate_id,
                           "score": result.combined_score, "main_score": incumbent["score"]}
                if not baselines:
                    baseline_scores.append(result.combined_score)
                    self.store.append("baseline", payload)
                elif len(baselines) != 1 or baselines[0] != payload:
                    raise RuntimeError("recovered baseline evidence mismatch")
                else:
                    baseline_scores.append(result.combined_score)
            recovery_adoptions[generation] = {
                "candidate_id": proposal.proposal_id, "intent_id": intent.intent_id,
                "execution_id": record["execution_id"], "generation": generation,
                "actual_token_cost": actual,
                "status": error.status.value if error is not None else "ok",
                "settlement_reused": adopted["settled"], "reexecuted": False}
            record_external_recovery(proposal.proposal_id, generation)

        def record_external_recovery(candidate_id: str, generation: int) -> None:
            """Mark adoption only after failure evidence or successful admission is durable."""
            payload = recovery_adoptions[generation]
            if payload["candidate_id"] != candidate_id:
                raise RuntimeError("recovery adoption candidate mismatch")
            previous = [row["payload"] for row in self.store.read("m0_recovery_adopted")
                        if row["payload"].get("candidate_id") == candidate_id]
            if not previous:
                self.store.append("m0_recovery_adopted", payload)
            elif len(previous) != 1 or previous[0] != payload:
                raise RuntimeError("duplicate or mismatched external recovery adoption")

        def execute_improvement_batch(parent: dict, generation: int,
                                      funnel: FunnelRecord) -> bool:
            """Run one frozen M0 cohort through canonical reserve/settle/admission."""
            nonlocal incumbent
            recovering = generation in recovered_batch
            if recovering:
                starts = [row["payload"] for row in self.store.read("batch_cycle_started")
                          if row["payload"].get("cohort_id") == recovered_batch[generation]]
                if len(starts) != 1:
                    raise RuntimeError("recovered M0 cohort start is missing or duplicated")
                cohort = starts[0]
                candidates = [Candidate(**payload) for payload in cohort["candidates"]]
                intents = [AllocationIntent(**payload) for payload in cohort["intents"]]
                if any(candidate.parents != [parent["candidate_id"]]
                       for candidate in candidates):
                    raise RuntimeError("recovered batch parent differs from selected lineage")
            else:
                available = int(ledger.account_summary()["available_main"])
                cohort_size = min(cfg.batch_size, available // cfg.intent_cost)
                if cohort_size < 1:
                    return False
                candidates = [Candidate(
                    self._proposal_id(task_desc, f"improve:{generation}:{slot}"),
                    [parent["candidate_id"]], operator="improve", created_cycle=generation)
                    for slot in range(cohort_size)]
                intents = [make_intent("m0", candidate.id, cfg.intent_cost,
                                       f"snap-{generation}", "exploit", generation)
                           for candidate in candidates]
            operations = {}
            for candidate in candidates:
                improve_id = candidate.id
                operations[improve_id] = lambda improve_id=improve_id: improve_fn(
                    self.llm, spec_improve, parent["candidate_id"], parent["prompt"],
                    parent["result"].text_feedback, parent["score"],
                    proposal_id=improve_id)
            backend = M0PromptExecutor(self.llm, self.evaluator, operations,
                                       cfg.intent_cost, evidence_store=self.store)
            executor_pool = ExecutorPool(backend, cfg.max_inflight,
                                         evidence_store=self.store)
            scheduler = BatchScheduler(executor_pool, ledger, policy, applier, self.store)
            frozen_incumbent = incumbent
            receipt_ids: dict[str, str] = {}

            def admission(candidate: Candidate, evidence: EvidenceRecord):
                native = backend.outcome(candidate.id)
                if evidence.eval_result.status is not EvalStatus.OK or native.result is None:
                    return AdmissionDecision(False, [StateMutation(
                        MutationOp.PRUNE, candidate.id, {},
                        "M0 execution did not produce an OK evaluation")],
                        "execution_not_ok")
                veto = self.registry.veto(native.proposal, native.result, pool)
                receipt = judge_candidate(native.result, frozen_incumbent["result"], veto,
                                          recovered=recovering)
                receipt_ids[candidate.id] = receipt.receipt_id
                accepted = receipt.verdict.kind == "ACCEPT"
                mutation = MutationOp.MERGE if accepted else MutationOp.PRUNE
                return AdmissionDecision(accepted, [StateMutation(
                    mutation, candidate.id, {},
                    f"M9 {receipt.receipt_id}: {'admit' if accepted else 'reject'}")],
                    receipt.receipt_id)

            try:
                if recovering:
                    if recovered_batch[generation] != scheduler.recovery_state()["cohort_id"]:
                        raise RuntimeError("recovered M0 cohort identity changed")
                    backend.recover_inflight(
                        None, execution_ref=recovered_batch[generation])
                    asyncio.run(scheduler.resume(
                        admission, mutation_start=checkpoint_mutation_count))
                else:
                    asyncio.run(scheduler.run(
                        [ExecutorSpec(role="m0_prompt") for _ in candidates], candidates, None,
                        [EvalRequest("dev") for _ in candidates], intents, admission))
                for candidate_id, receipt_id in receipt_ids.items():
                    payload = {"candidate_id": candidate_id, "receipt_id": receipt_id,
                               "admit": scheduler.last_admissions[candidate_id]}
                    existing = [row["payload"] for row in self.store.read("admission_receipt")
                                if row["payload"].get("candidate_id") == candidate_id]
                    if not existing:
                        self.store.append("admission_receipt", payload)
                    elif not recovering or len(existing) != 1 or existing[0] != payload:
                        raise RuntimeError("duplicate or mismatched batch admission receipt")
                if recovering:
                    report = backend._recovery_reports.get(recovered_batch[generation], {})
                    payload = {"cohort_id": recovered_batch[generation],
                               "generation": generation,
                               "candidate_ids": [candidate.id for candidate in candidates],
                               "process_count": report.get(
                                   "adopted_process_count", len(candidates)) + report.get(
                                   "continued_process_count", 0),
                               "adopted_process_count": report.get(
                                   "adopted_process_count", len(candidates)),
                               "continued_process_count": report.get(
                                   "continued_process_count", 0),
                               "continued_candidate_ids": report.get(
                                   "continued_candidate_ids", []),
                               "adopted_inprocess_evaluation_count": report.get(
                                   "adopted_inprocess_evaluation_count", 0),
                               "continued_inprocess_evaluation_count": report.get(
                                   "continued_inprocess_evaluation_count", 0),
                               "continued_inprocess_evaluation_ids": report.get(
                                   "continued_inprocess_evaluation_ids", []),
                               "continued_proposal_count": report.get(
                                   "continued_proposal_count", 0),
                               "continued_proposal_ids": report.get(
                                   "continued_proposal_ids", []),
                               "adopted_proposal_count": report.get(
                                   "adopted_proposal_count", 0),
                               "adopted_proposal_ids": report.get(
                                   "adopted_proposal_ids", []),
                               "new_proposal_count": report.get(
                                   "new_proposal_count", report.get(
                                       "continued_proposal_count", 0)),
                               "recovered_proposal_failure_count": report.get(
                                   "recovered_proposal_failure_count", 0),
                               "recovered_proposal_failure_ids": report.get(
                                   "recovered_proposal_failure_ids", []),
                               "reexecuted": False}
                    existing = [row["payload"] for row in self.store.read(
                        "m0_batch_recovery_adopted")
                        if row["payload"].get("cohort_id") == payload["cohort_id"]]
                    if not existing:
                        self.store.append("m0_batch_recovery_adopted", payload)
                    elif len(existing) != 1 or existing[0] != payload:
                        raise RuntimeError("duplicate or mismatched M0 batch recovery adoption")
            finally:
                executor_pool.close()
            for candidate in candidates:
                native = backend.outcome(candidate.id)
                if native.proposal is not None:
                    funnel.proposed += 1
                    if native.proposal.apply_result in ("ok", "retry_ok"):
                        funnel.applicable += 1
                if native.result is not None:
                    funnel.runnable += 1
                if not scheduler.last_admissions.get(candidate.id, False):
                    continue
                funnel.admitted += 1
                accepted_candidate_ids.append(candidate.id)
                cand = {"candidate_id": candidate.id,
                        "prompt": native.proposal.patch_text,
                        "score": native.result.combined_score, "result": native.result}
                pool.append(cand)
                if self.archive is not None:
                    self.archive.register(cand, generation)
                if cand["score"] >= incumbent["score"]:
                    incumbent = cand
            return True

        improve_fn = (evolve_block_improve if self.improve_impl == "llm_evolve_block"
                      else reflective_improve)
        if cfg.resume_from_checkpoint:
            if checkpoint_path.exists():
                restore_checkpoint()
            else:
                restore_genesis_recovery()
            prepare_external_recovery()
            if 0 in recovered_external:
                funnel = FunnelRecord("draft", 0)
                outcome, _ = adopt_external_recovery(None, 0, funnel)
                proposal, result = outcome
                if result is None:
                    record_external_recovery(proposal.proposal_id, 0)
                    raise RuntimeError("recovered genesis evaluation did not produce a result")
                absorbed = absorb_candidate(proposal, result, [], "draft", 0,
                                            recovery_start=0)
                receipt = judge_candidate(result, None, None, recovered=True)
                apply_admission(proposal.proposal_id,
                                receipt.verdict.kind == "ACCEPT", receipt.receipt_id,
                                recovery_start=absorbed)
                record_external_recovery(proposal.proposal_id, 0)
                if receipt.verdict.kind == "ACCEPT":
                    funnel.admitted += 1
                    accepted_candidate_ids.append(proposal.proposal_id)
                    pool.append({"candidate_id": proposal.proposal_id,
                                 "prompt": proposal.patch_text,
                                 "score": result.combined_score, "result": result})
                incumbent = pool[0]
                if self.archive is not None:
                    self.archive.register(incumbent, 0)
                main_scores.append(incumbent["score"])
                funnels.append(funnel)
                save_checkpoint(1)
                stopped_early = cfg.stop_after_generation == 0
        else:
            self.store.append("run_start", {"task_desc": task_desc,
                                            "config": asdict(cfg),
                                            "profile": self.profile_name,
                                            "accounting_stamp": asdict(self.stamp)})
            intent = make_intent("m0", "genesis", cfg.intent_cost, "snap-0", "explore")
            funnel = FunnelRecord("draft", 0)
            genesis_id = self._proposal_id(task_desc, "genesis")
            outcome, _ = execute(
                intent, lambda: draft(self.llm, spec_draft, task_desc,
                                      proposal_id=genesis_id), funnel)
            if outcome is None:
                raise BudgetError("genesis intent rejected; check budget floors")
            proposal, result = outcome
            if result is None:
                raise RuntimeError("genesis proposal failed deterministic apply")
            absorb_candidate(proposal, result, [], "draft", 0)
            receipt = gate.judge(result, None)
            apply_admission(proposal.proposal_id,
                            receipt.verdict.kind == "ACCEPT", receipt.receipt_id)
            if receipt.verdict.kind == "ACCEPT":
                funnel.admitted += 1
                accepted_candidate_ids.append(proposal.proposal_id)
                pool.append({"candidate_id": proposal.proposal_id,
                             "prompt": proposal.patch_text,
                             "score": result.combined_score, "result": result})
            incumbent = pool[0]
            if self.archive is not None:
                self.archive.register(incumbent, 0)
            main_scores.append(incumbent["score"])
            funnels.append(funnel)
            save_checkpoint(1)
            stopped_early = cfg.stop_after_generation == 0

        for gen in range(next_generation, cfg.max_generations + 1):
            if stopped_early:
                break
            if gen not in recovered_external and gen not in recovered_batch \
                    and ledger.account_summary()["available_main"] < cfg.intent_cost:
                action = stop_action("REJECT", "budget_exhausted")
                self.store.append("stop_action", {
                    "verdict_kind": "REJECT", "scope": "budget_exhausted",
                    "action": action, "generation": gen,
                    "available_main": ledger.account_summary()["available_main"],
                    "required": cfg.intent_cost})
                if action != "stop":
                    raise RuntimeError("budget exhaustion must resolve to stop")
                break
            if self.archive is not None:
                for event in self.archive.migrate_if_due(gen):
                    self.store.append("archive_migration", event)
                parent = self.archive.select_parent(pool, gen)
            else:
                selected = asyncio.run(policy.select(frontier, ledger.account_summary()))
                if len(selected) != 1:
                    raise RuntimeError("best-first policy must select one accepted parent")
                parent = next(cand for cand in pool
                              if cand["candidate_id"] == selected[0])
            for alarm in self.registry.parent_selected(parent, gen):
                self.store.append("extension_alarm", alarm)
            funnel = FunnelRecord("improve", gen)
            if cfg.batch_size > 1:
                if not execute_improvement_batch(parent, gen, funnel):
                    break
            else:
                intent = make_intent("m0", parent["candidate_id"], cfg.intent_cost,
                                     f"snap-{gen}", "exploit", gen)
                improve_id = self._proposal_id(task_desc, f"improve:{gen}")
                recovered = adopt_external_recovery(parent, gen, funnel)
                if recovered is not None:
                    outcome, _ = recovered
                else:
                    outcome, _ = execute(
                        intent,
                        lambda: improve_fn(
                            self.llm, spec_improve, parent["candidate_id"],
                            parent["prompt"], parent["result"].text_feedback,
                            parent["score"], proposal_id=improve_id), funnel)
                if outcome is None:
                    break
                proposal, result = outcome
                if result is None:
                    if recovered is not None:
                        record_external_recovery(proposal.proposal_id, gen)
                    main_scores.append(incumbent["score"])
                    funnels.append(funnel)
                    save_checkpoint(gen + 1)
                    stopped_early = cfg.stop_after_generation == gen
                    continue
                recovery_start = checkpoint_mutation_count if recovered is not None else None
                veto = self.registry.veto(proposal, result, pool)
                absorbed = absorb_candidate(
                    proposal, result, [parent["candidate_id"]], "improve", gen,
                    recovery_start=recovery_start)
                receipt = judge_candidate(result, incumbent["result"], veto,
                                          recovered=recovered is not None)
                apply_admission(
                    proposal.proposal_id, receipt.verdict.kind == "ACCEPT", receipt.receipt_id,
                    recovery_start=(recovery_start + absorbed
                                    if recovery_start is not None else None))
                if recovered is not None:
                    record_external_recovery(proposal.proposal_id, gen)
                if receipt.verdict.kind == "ACCEPT":
                    funnel.admitted += 1
                    accepted_candidate_ids.append(proposal.proposal_id)
                    cand = {"candidate_id": proposal.proposal_id,
                            "prompt": proposal.patch_text,
                            "score": result.combined_score, "result": result}
                    pool.append(cand)
                    if self.archive is not None:
                        self.archive.register(cand, gen)
                    if cand["score"] >= incumbent["score"]:
                        incumbent = cand
            main_scores.append(incumbent["score"])
            funnels.append(funnel)

            if gen % cfg.baseline_every == 0:
                b_intent = make_intent("m0", "iid-rs", cfg.intent_cost,
                                       f"snap-{gen}", "control", gen)
                b_funnel = FunnelRecord("iid_rs", gen)
                baseline_id = self._proposal_id(task_desc, f"control:{gen}")
                if gen in recovered_control:
                    adopt_control_recovery(gen, b_funnel)
                else:
                    b_outcome, _ = execute(
                        b_intent, lambda: draft(self.llm, spec_draft, task_desc,
                                                proposal_id=baseline_id), b_funnel)
                    if b_outcome is not None and b_outcome[1] is not None:
                        _, b_result = b_outcome
                        baseline_scores.append(b_result.combined_score)
                        self.store.append("baseline", {"generation": gen,
                                                       "candidate_id": b_result.candidate_id,
                                                       "score": b_result.combined_score,
                                                       "main_score": incumbent["score"]})
                funnels.append(b_funnel)
            save_checkpoint(gen + 1)
            stopped_early = cfg.stop_after_generation == gen

        for f in funnels:
            f.check()
        health = M3HealthProbe.compute(ledger, funnels)
        attestation = _self_attestation(incumbent["score"], baseline_scores,
                                        cfg.noise_floor)
        governance = audit_governance(self.store, ledger.account_summary(),
                                      accepted_candidate_ids)
        self.store.append("health", health)
        self.store.append("self_attestation", attestation)
        self.store.append("governance_audit", governance)
        self._last_task_desc = task_desc
        self._last_result = {
            "best_prompt": incumbent["prompt"], "best_score": incumbent["score"],
            "self_attestation": attestation, "governance_audit": governance,
            "main_scores": main_scores, "baseline_scores": baseline_scores,
            "funnels": funnels, "ledger": ledger.account_summary(),
            "health": health,
            "archive_health": self.archive.health() if self.archive else None,
            "governed_state": {
                "frontier_nodes": len(frontier.nodes),
                "merged_ids": sorted(node.id for node in frontier.nodes.values()
                                     if node.status == "merged"),
                "pruned_ids": sorted(node.id for node in frontier.nodes.values()
                                     if node.status == "pruned"),
                "memory_entries": len(memory.entries),
                "memory_levels": {level: sum(entry.level == level
                                             for entry in memory.entries.values())
                                  for level in ("L1", "L2", "L3")},
                "mutation_receipts": len(list(self.store.read("state_mutation"))),
                "baseline_in_frontier": bool({
                    record["payload"].get("candidate_id")
                    for record in self.store.read("baseline")
                }.intersection(frontier.nodes))},
            "generations": len(funnels),
            "accepted_candidate_ids": accepted_candidate_ids,
            "completed": not stopped_early, "resumed": resumed,
            "next_generation": next_generation,
            "checkpoint_path": str(checkpoint_path) if cfg.checkpoint_enabled else None,
            "checkpoint_sha256": checkpoint_hash or None}
        return self._last_result

    def inspect(self) -> dict:
        """Machine-readable governance view: self-attestation + receipt coverage."""
        if self._last_result is None:
            raise RuntimeError("evolve() must run before inspect()")
        result = self._last_result
        accepted = set(result["accepted_candidate_ids"])
        attestation = result["self_attestation"]
        governance = audit_governance(self.store, result["ledger"],
                                      result["accepted_candidate_ids"])
        replay_records = list(self.store.read("replay_certificate"))
        replay_certificate = replay_records[-1]["payload"] if replay_records else None
        return {"best_score": result["best_score"],
                "baseline_mean": attestation["baseline_mean"],
                "self_attestation": attestation,
                "self_attestation_pass": attestation["verdict"] == "PASS",
                "ledger": result["ledger"],
                "receipt_count": len(list(self.store.read("receipt"))),
                "funnel_count": len(result["funnels"]),
                "health": result["health"],
                "archive_health": result["archive_health"],
                "governed_state": result["governed_state"],
                "governance_audit": governance,
                "governance_pass": governance["passed"],
                "formal_governance_pass": governance["formal_pass"],
                "baseline_resident": governance["baseline_residence"]["passed"],
                "replay_certificate": replay_certificate,
                "replay_certified": bool(replay_certificate
                                         and replay_certificate["passed"]),
                "ledger_reconciliation_pass": governance["ledger_reconciliation"]["passed"],
                "stop_action_replay_pass": governance["stop_action_replay"]["passed"],
                "accepted_receipt_coverage": governance["receipt_coverage"][
                    "accepted_receipt_coverage"],
                "accepted_candidates": len(accepted)}

    def replay(self, task_desc: str | None = None) -> dict:
        """Rerun independently and certify normalized snapshot plus Receipt chain."""
        if self._last_result is None:
            raise RuntimeError("evolve() must run before certified replay()")
        if not self.cfg.checkpoint_enabled:
            raise RuntimeError("certified replay requires an integrity-checked checkpoint")
        task = task_desc or self._last_task_desc
        if task is None:
            raise RuntimeError("replay requires a task description")
        archive = None
        if isinstance(self.archive, MapElitesArchive):
            archive = self.archive.fork()
        elif self.archive is not None:
            archive = IslandArchive(self.archive.num_islands,
                                    self.archive.migration_interval)
        clone_workdir = f"{self.workdir}/replay"
        clone_store = AppendOnlyStore(f"{clone_workdir}/x1.jsonl")
        replay_evaluator = (self.evaluator.fork(clone_workdir, clone_store)
                            if isinstance(self.evaluator, ExternalCommandEvaluator)
                            else self.evaluator)
        replay_llm = (self.llm.fork(clone_workdir, clone_store)
                      if isinstance(self.llm, ExternalCommandLLM) else self.llm)
        clone = Framework(replay_llm, replay_evaluator,
                          replace(self.cfg, resume_from_checkpoint=False,
                                  stop_after_generation=None),
                          clone_workdir, profile_name=self.profile_name,
                          archive=archive, improve_impl=self.improve_impl,
                          accounting_stamp=self.stamp)
        for ext in self.registry.admission + self.registry.parent_monitors:
            clone.registry.register(ext)
        original = self._last_result
        replayed = clone.evolve(task)
        original_snapshot = certified_snapshot_ref(Path(self.workdir) / "checkpoint.json")
        replay_snapshot = certified_snapshot_ref(Path(clone.workdir) / "checkpoint.json")
        original_chain = receipt_chain_sha256(self.store)
        replay_chain = receipt_chain_sha256(clone.store)
        compared = ("best_prompt", "best_score", "self_attestation", "governance_audit",
                    "main_scores", "baseline_scores", "accepted_candidate_ids",
                    "generations", "ledger", "health", "archive_health", "governed_state")
        result_match = all(replayed[key] == original[key] for key in compared)
        current_governance = audit_governance(
            self.store, original["ledger"], original["accepted_candidate_ids"])
        certificate = {
            "passed": False, "snapshot_ref": original_snapshot,
            "replay_snapshot_ref": replay_snapshot,
            "snapshot_match": original_snapshot == replay_snapshot,
            "receipt_chain_sha256": original_chain,
            "replay_receipt_chain_sha256": replay_chain,
            "receipt_chain_match": original_chain == replay_chain,
            "result_match": result_match,
            "original_governance_pass": current_governance["passed"],
            "replay_governance_pass": replayed["governance_audit"]["passed"]}
        certificate["passed"] = all((
            certificate["snapshot_match"], certificate["receipt_chain_match"],
            result_match, current_governance["passed"],
            replayed["governance_audit"]["passed"]))
        clone.store.append("replay_certificate", certificate)
        self.store.append("replay_certificate", certificate)
        original["replay_certificate"] = certificate
        replayed["replay_certificate"] = certificate
        if not certificate["passed"]:
            raise RuntimeError(f"certified replay mismatch: {certificate}")
        return replayed
