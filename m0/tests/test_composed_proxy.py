"""Heterogeneous calibration, bounded feedback and accounting via Framework."""
from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import asdict, replace

import pytest

from core.composition.defaults import GreedyPolicy, composed_profile, default_registry
from core.composition.evaluation import EvaluationContract, PrivateEvaluationData, binding_for
from core.executor.types import CostVec, EvalResult, EvalStatus
from core.llm import UsageError
from core.loop import Framework, LoopConfig
from core.x1.checkpoint import RunCheckpoint

TASK = "optimize the public proxy while checking independent calibration quality"
MANAGED = ("token", "node", "eval_count")
PRIVATE = "PRIVATE_CALIBRATION_CANARY"
RAW_ANCHOR = "RAW_CALIBRATION_FEEDBACK_CANARY"
HELD_OUT = "HELD_OUT_GATE_FINAL_CANARY"


class Provider:
    model = "proxy-offline-fixture-v1"
    supplier = "offline-simulation"

    def __init__(self):
        self.prompts, self.calls, self.index = [], 0, 0

    def __call__(self, prompt):
        self.prompts.append(prompt)
        self.calls += 1
        self.index += 1
        self.last_usage = {"total_tokens": 5}
        # The marker must come from M5 retrieval, not the monitor state injected
        # separately as budget information.
        memory_text = prompt.split('"memory":', 1)[-1] if '"memory":' in prompt else ""
        applied = '"kind": "structured"' in memory_text and "proxy_improved_true_regressed" in memory_text
        return f"candidate-{self.index}" + (" APPLIED_CALIBRATION_LESSON" if applied else "")

    def checkpoint_state(self):
        return {"index": self.index}

    def restore_state(self, state):
        self.index = state["index"]


class Domain:
    evaluator_version = "heterogeneous-offline-v1"
    measured_cost_units = MANAGED
    datasets = {"dev": "cheap development proxy fixture", "calibration": "independent true-quality anchor fixture",
                "admission": "held-out admission fixture", "final_audit": "sealed final audit fixture"}

    def __init__(self, *, proxies=(1, 2, 3, 4, 5), truths=(10, 9, 8, 11, 12),
                 anchor_fault=None, context_collision=None):
        self.proxies, self.truths = tuple(proxies), tuple(truths)
        self.anchor_fault, self.calls = anchor_fault, []
        self.contexts = {split: "sha256:" + hashlib.sha256(content.encode()).hexdigest()
                         for split, content in self.datasets.items()}
        if context_collision == "empty":
            self.contexts["calibration"] = ""
        elif context_collision is not None:
            self.contexts["calibration"] = self.contexts[context_collision]
        self.evaluation_context = self.contexts["dev"]

    def validate_request(self, request):
        request.validate()
        if request.split_id not in self.contexts or request.fidelity != {
                "dev": "proxy", "calibration": "full", "admission": "admission",
                "final_audit": "final_audit"}[request.split_id]:
            raise ValueError("unsupported fixture evaluation request")

    def evaluation_context_for(self, request):
        return self.contexts[request.split_id]

    async def evaluate(self, proposal, request):
        self.validate_request(request)
        cycle, split = proposal.candidate.created_cycle, request.split_id
        self.calls.append({"candidate_id": proposal.candidate.id, "cycle": cycle,
                           "request": copy.deepcopy(asdict(request)), "artifact": proposal.artifact})
        binding = binding_for(proposal, request, evaluator_version=self.evaluator_version,
                              evaluation_context=self.evaluation_context_for(request))
        status, coverage = EvalStatus.OK, MANAGED
        if split == "calibration" and self.anchor_fault == "unknown":
            coverage = ("eval_count", "node")
        if split == "calibration" and self.anchor_fault == "binding":
            binding = replace(binding, candidate_id="foreign-candidate")
        if split == "calibration" and self.anchor_fault == "failed":
            status = EvalStatus.FAILED_TO_RUN
        metric = "calibration/quality" if split == "calibration" else "dev/score"
        score = self.truths[cycle] if split == "calibration" else self.proxies[cycle]
        feedback = RAW_ANCHOR if split == "calibration" else HELD_OUT if split in {
            "admission", "final_audit"} else f"public dev feedback {cycle}"
        return EvalResult(status, {metric: score} if status is EvalStatus.OK else {},
            CostVec(tokens_in=7, eval_count=1), fidelity=request.fidelity, text_feedback=feedback,
            contract=EvaluationContract(binding, coverage,
                private=PrivateEvaluationData(data={"secret": PRIVATE if split == "calibration" else HELD_OUT})))


class FreshDrafts(GreedyPolicy):
    async def select(self, frontier, budget):
        return []


def profile(*, every=1, minimum=3, window=4, threshold=0.5, true_direction="maximize",
            memory=None, cap=100, layered=True):
    assembly = composed_profile()
    assembly["domain"] = {"name": "native"}
    assembly["memory"] = {"name": "scoped", "options": memory or {
        "context_scope": "ancestors", "trust_floor": "ungated", "max_chars": 12000}}
    if layered:
        assembly["admission"] = {"name": "layered", "options": {"call_budget": 50}}
    limits = {"token": 10000, "node": 20, "eval_count": cap}
    assembly["budget"] = {"name": "hierarchical", "options": {
        "limits": {level: dict(limits) for level in ("global", "direction", "candidate")},
        "reservation": {"token": 10, "node": 0, "eval_count": 1},
        "operation_reservations": {"planning": {"token": 0, "node": 0, "eval_count": 0},
                                   "operator": {"token": 10, "node": 1, "eval_count": 0}},
        "fidelity_rungs": [{"fidelity": "proxy", "split_id": "dev", "seed_set": [1]}],
        "proxy_validity": {"every_n_cycles": every,
            "anchor_request": {"fidelity": "full", "split_id": "calibration", "seed_set": [7, 19]},
            "proxy_metric": "dev/score", "true_metric": "calibration/quality",
            "proxy_direction": "maximize", "true_direction": true_direction,
            "min_pairs": minimum, "window": window, "min_rank_correlation": threshold}}}
    return assembly


def build(path, *, assembly=None, llm=None, domain=None, generations=3, stop=None, resume=False, fresh=False):
    registry = default_registry()
    assembly = copy.deepcopy(assembly or profile())
    if fresh:
        registry.register("policy", "fresh", lambda context, options: FreshDrafts(context.scope_context))
        assembly["policy"] = {"name": "fresh"}
    return Framework.from_profile(assembly, llm or Provider(), domain or Domain(),
        LoopConfig(max_generations=generations, stop_after_generation=stop, resume_from_checkpoint=resume,
                   total_budget=100000, intent_cost=2000, reeval_floor=0), str(path), component_registry=registry)


def rows(framework, kind):
    return [row["payload"] for row in framework.store.read(kind)]


def calibration_calls(domain):
    return [call for call in domain.calls if call["request"]["split_id"] == "calibration"]


def proxy_begins(framework):
    return [event["data"]["intent"] for event in rows(framework, "proxy_validity") if event["event"] == "begin"]


def assert_costs(framework, provider, domain):
    state = framework._composed.budget.state()
    assert state["global"]["used"] == {
        "token": provider.calls * 5 + len(domain.calls) * 7,
        "node": provider.calls, "eval_count": len(domain.calls)}
    assert not state["open_intents"] and all(value == 0 for value in state["global"]["reserved"].values())
    assert sum(scope["used"]["token"] for scope in state["candidates"].values()) == state["global"]["used"]["token"]


def test_periodic_anchor_becomes_every_candidate_after_real_regression_and_does_not_spend_gate_queries(tmp_path):
    provider, domain = Provider(), Domain(truths=(10, 11, 8, 12, 13))
    fw = build(tmp_path, assembly=profile(every=2), llm=provider, domain=domain, generations=3)
    result = fw.evolve(TASK)
    begins = proxy_begins(fw)
    assert [item["cycle"] for item in begins if item["role"] == "candidate"] == [0, 2, 3]
    assert [(item["cycle"], item["candidate"]["created_cycle"]) for item in begins if item["role"] == "baseline"] == [(2, 1)]
    assert result["proxy_validity"]["mode"] == "degraded"
    decisions = rows(fw, "composed_decision")
    assert [decision["decision"]["admit"] for decision in decisions] == [True, True, False, True]
    assert all(call["cycle"] != 2 for call in domain.calls if call["request"]["split_id"] == "admission")
    assert len(calibration_calls(domain)) == 4
    assert_costs(fw, provider, domain)
    assert fw.replay()["replay_certificate"]["passed"]


def test_negative_calibration_memory_changes_nonancestor_draft_and_keeps_private_gate_and_raw_text_out(tmp_path):
    provider, domain = Provider(), Domain()
    fw = build(tmp_path, llm=provider, domain=domain, generations=2, fresh=True)
    fw.evolve(TASK)
    evaluations = rows(fw, "composed_evidence")
    assert all(row["proposal"]["candidate"]["parents"] == [] for row in evaluations)
    assert "APPLIED_CALIBRATION_LESSON" not in evaluations[0]["proposal"]["artifact"]
    assert "APPLIED_CALIBRATION_LESSON" not in evaluations[1]["proposal"]["artifact"]
    assert "APPLIED_CALIBRATION_LESSON" in evaluations[2]["proposal"]["artifact"]
    retrieved = rows(fw, "composed_context")[2]["context"]["memory"]
    negatives = [item for item in retrieved if item["negative"]]
    assert negatives and "proxy_improved_true_regressed" in json.dumps(negatives)
    assert all(PRIVATE not in prompt and RAW_ANCHOR not in prompt and HELD_OUT not in prompt for prompt in provider.prompts)
    assert all(PRIVATE not in json.dumps(pack) and RAW_ANCHOR not in json.dumps(pack)
               and HELD_OUT not in json.dumps(pack) for pack in rows(fw, "context_pack"))
    assert fw.replay()["replay_certificate"]["passed"]


def test_distinct_metrics_and_minimize_true_direction_use_actual_anchor_result(tmp_path):
    domain = Domain(proxies=(1, 2, 3), truths=(30, 20, 10))
    fw = build(tmp_path, assembly=profile(true_direction="minimize"), domain=domain, generations=2)
    result = fw.evolve(TASK)
    assert result["proxy_validity"]["mode"] == "monitoring"
    assert result["proxy_validity"]["rank_correlation"] == 1
    assert len(result["accepted_candidate_ids"]) == 3
    assert all(call["request"]["seed_set"] == [7, 19] and call["request"]["fidelity"] == "full"
               for call in calibration_calls(domain))
    assert not [entry for entry in fw._composed.memory.entries.values() if entry.utility.harmful_count]


@pytest.mark.parametrize("proxies,truths,expected", [
    ((1, 1, 2), (1, 1, 2), 1),
    ((1, 1, 1), (1, 2, 3), None),
])
def test_rank_ties_low_sample_and_constant_proxy_are_observed_through_real_evaluations(tmp_path, proxies, truths, expected):
    domain = Domain(proxies=proxies, truths=truths)
    fw = build(tmp_path, domain=domain, generations=2, stop=1)
    partial = fw.evolve(TASK)
    assert partial["proxy_validity"]["mode"] == "warmup" and partial["proxy_validity"]["valid_pairs"] == 2
    resumed = build(tmp_path, domain=Domain(proxies=proxies, truths=truths), generations=2, resume=True)
    result = resumed.evolve(TASK)
    assert result["proxy_validity"]["rank_correlation"] == expected
    assert result["proxy_validity"]["mode"] == ("degraded" if expected is None else "monitoring")
    assert result["proxy_validity"]["statistical"] is False


@pytest.mark.parametrize("collision", ["dev", "admission", "final_audit", "empty"])
def test_calibration_context_is_preflighted_against_all_other_splits_before_paid_calls(tmp_path, collision):
    provider, domain = Provider(), Domain(context_collision=collision)
    fw = build(tmp_path, llm=provider, domain=domain, generations=0)
    with pytest.raises(ValueError, match="context|calibration|content|binding"):
        fw.evolve(TASK)
    assert provider.calls == 0 and domain.calls == []
    assert not fw.store.path.exists()


@pytest.mark.parametrize("fault", ["failed", "binding", "unknown"])
def test_anchor_failures_charge_known_usage_or_keep_unknown_reserve_and_never_recall_on_resume(tmp_path, fault):
    provider, domain = Provider(), Domain(anchor_fault=fault)
    fw = build(tmp_path, llm=provider, domain=domain, generations=0)
    if fault == "failed":
        result = fw.evolve(TASK)
        assert result["proxy_validity"]["mode"] == "degraded"
        assert result["reporting"]["gate_calls"] == 0
        assert result["reporting"]["final_audit"]["state"] == "no_selection"
        assert [row["decision"]["admit"] for row in rows(fw, "composed_decision")] == [False]
    else:
        with pytest.raises((ValueError, UsageError)):
            fw.evolve(TASK)
    assert [call["request"]["split_id"] for call in domain.calls] == ["dev", "calibration"]
    state = fw._composed.budget.state()
    assert state["global"]["used"]["eval_count"] == (1 if fault == "unknown" else 2)
    assert bool(state["open_intents"]) is (fault == "unknown")
    if fault != "failed":
        assert not rows(fw, "composed_decision")
    fresh_provider, fresh_domain = Provider(), Domain(anchor_fault=fault)
    resumed = build(tmp_path, llm=fresh_provider, domain=fresh_domain, generations=0, resume=True)
    before = fw.store.path.read_bytes()
    if fault == "failed":
        resumed_result = resumed.evolve(TASK)
        assert resumed_result["ledger"] == result["ledger"]
        assert resumed_result["accepted_candidate_ids"] == []
    else:
        with pytest.raises((ValueError, RuntimeError), match="unfinished|journal|checkpoint"):
            resumed.evolve(TASK)
        assert fw.store.path.read_bytes() == before
    assert fresh_provider.calls == 0 and fresh_domain.calls == []


def test_unfunded_anchor_never_consumes_calibration_or_gate_query_and_leaves_no_partial_reserve(tmp_path):
    provider, domain = Provider(), Domain()
    fw = build(tmp_path, assembly=profile(cap=1), llm=provider, domain=domain, generations=0)
    result = fw.evolve(TASK)
    assert [call["request"]["split_id"] for call in domain.calls] == ["dev"]
    assert result["reporting"]["gate_calls"] == 0
    assert proxy_begins(fw) == []
    assert_costs(fw, provider, domain)


def test_periodic_candidate_and_uncached_incumbent_anchors_are_reserved_as_one_batch(tmp_path):
    provider, domain = Provider(), Domain(truths=(10, 11, 8, 12, 13))
    fw = build(tmp_path, assembly=profile(every=2, cap=7), llm=provider, domain=domain, generations=2)
    result = fw.evolve(TASK)
    assert [call["cycle"] for call in calibration_calls(domain)] == [0]
    assert [item["cycle"] for item in proxy_begins(fw)] == [0]
    assert result["reporting"]["gate_calls"] == 2
    assert_costs(fw, provider, domain)


def test_negative_feedback_honors_opt_out_and_is_not_transferred_in_memory_export(tmp_path):
    memory = {"context_scope": "ancestors", "trust_floor": "ungated", "include_negative": False,
              "max_chars": 12000, "export_on_finish": True}
    provider = Provider()
    fw = build(tmp_path, assembly=profile(memory=memory), llm=provider, generations=2, fresh=True)
    result = fw.evolve(TASK)
    assert not any(item["negative"] for pack in rows(fw, "composed_context") for item in pack["context"]["memory"])
    assert not any("APPLIED_CALIBRATION_LESSON" in row["proposal"]["artifact"] for row in rows(fw, "composed_evidence"))
    export = (tmp_path / result["memory_export"]["relative_path"]).read_text()
    assert "proxy_improved_true_regressed" not in export and PRIVATE not in export and RAW_ANCHOR not in export


def test_calibration_feedback_obeys_the_actual_context_character_and_entry_limits(tmp_path):
    memory = {"context_scope": "ancestors", "trust_floor": "ungated", "include_negative": True,
              "max_chars": 1024, "top_k": 1}
    fw = build(tmp_path, assembly=profile(memory=memory), generations=2, fresh=True)
    fw.evolve(TASK)
    packs = rows(fw, "context_pack")
    assert all(pack["used_chars"] <= pack["limit_chars"] == 1024 for pack in packs)
    assert all(len(pack["context"]["memory"]) <= 1 for pack in rows(fw, "composed_context"))
    assert not any("APPLIED_CALIBRATION_LESSON" in row["proposal"]["artifact"]
                   for row in rows(fw, "composed_evidence"))


def test_cycle_boundary_resume_and_repeated_replay_match_uninterrupted_business_result(tmp_path):
    assembly = profile(every=2)
    full = build(tmp_path / "full", assembly=assembly)
    expected = full.evolve(TASK)
    partial = build(tmp_path / "resume", assembly=assembly, stop=1)
    partial.evolve(TASK)
    resumed = build(tmp_path / "resume", assembly=assembly, resume=True)
    actual = resumed.evolve(TASK)
    for field in ("best_candidate_id", "best_prompt", "best_score", "cycles", "ledger", "accepted_candidate_ids"):
        assert actual[field] == expected[field]
    assert actual["proxy_validity"]["mode"] == expected["proxy_validity"]["mode"]
    assert actual["proxy_validity"]["rank_correlation"] == expected["proxy_validity"]["rank_correlation"]
    assert resumed.replay()["replay_certificate"]["passed"]
    assert resumed.replay()["replay_certificate"]["passed"]


@pytest.mark.parametrize("target", ["checkpoint", "journal", "calibration_context"])
def test_changed_calibration_authority_rejects_resume_before_any_new_paid_call(tmp_path, target):
    fw = build(tmp_path, stop=1)
    fw.evolve(TASK)
    provider, domain = Provider(), Domain()
    if target == "checkpoint":
        payload = RunCheckpoint.load(tmp_path / "checkpoint.json").payload
        payload["proxy_state"]["state"]["mode"] = "monitoring"
        RunCheckpoint.create(payload).save(tmp_path / "checkpoint.json")
    elif target == "journal":
        records = [json.loads(line) for line in fw.store.path.read_text().splitlines()]
        anchor = next(row for row in records if row["kind"] == "proxy_validity" and row["payload"]["event"] == "record")
        anchor["payload"]["data"]["anchor"]["evidence"]["eval_result"]["metrics"]["calibration/quality"] = -999
        fw.store.path.write_text("\n".join(json.dumps(row) for row in records) + "\n")
    else:
        domain.contexts["calibration"] = "sha256:" + "f" * 64
    before = fw.store.path.read_bytes()
    resumed = build(tmp_path, llm=provider, domain=domain, resume=True)
    with pytest.raises(ValueError, match="checkpoint|manifest|journal|integrity|context"):
        resumed.evolve(TASK)
    assert provider.calls == 0 and domain.calls == [] and fw.store.path.read_bytes() == before


def test_replay_certificate_rejects_a_rehashed_checkpoint_that_changes_calibration_state(tmp_path):
    fw = build(tmp_path, generations=1)
    fw.evolve(TASK)
    payload = RunCheckpoint.load(tmp_path / "checkpoint.json").payload
    payload["proxy_state"]["state"]["mode"] = "monitoring"
    RunCheckpoint.create(payload).save(tmp_path / "checkpoint.json")
    with pytest.raises(RuntimeError, match="replay mismatch"):
        fw.replay()
    certificate = rows(fw, "replay_certificate")[-1]
    assert certificate["passed"] is False


def test_native_proxy_loss_and_true_gate_quality_have_independent_metrics_directions_and_receipts(tmp_path):
    class LossQualityDomain(Domain):
        async def evaluate(self, proposal, request):
            result = await super().evaluate(proposal, request)
            cycle, split = proposal.candidate.created_cycle, request.split_id
            if split == "dev":
                metrics = {"dev/loss": (0.8, 0.4, 0.2)[cycle]}
            elif split == "admission":
                metrics = {"gate/quality": (0.8, 0.7, 0.9)[cycle]}
            elif split == "final_audit":
                metrics = {"gate/quality": 0.65}
            else:
                metrics = result.metrics
            return replace(result, metrics=metrics)
    assembly = profile()
    assembly["frontier"] = {"name": "tree", "options": {"metric": "dev/loss", "direction": "minimize"}}
    assembly["operators"] = [{"name": name, "options": {"metric": "dev/loss"}} for name in ("draft", "reflective")]
    assembly["admission"]["options"].update(metric="gate/quality", direction="maximize",
                                             dev_metric="dev/loss", dev_direction="minimize")
    assembly["budget"]["options"]["proxy_validity"].update(proxy_metric="dev/loss", proxy_direction="minimize")
    provider, domain = Provider(), LossQualityDomain(truths=(0.9, 0.95, 0.7))
    fw = build(tmp_path, assembly=assembly, llm=provider, domain=domain, generations=2)
    result = fw.evolve(TASK)
    decisions = rows(fw, "composed_decision")
    assert [row["decision"]["admit"] for row in decisions] == [True, False, False]
    assert result["reporting"]["dev_best"]["eval_result"]["metrics"] == {"dev/loss": 0.2}
    assert result["reporting"]["gate_selected"]["eval_result"]["metrics"] == {"gate/quality": 0.8}
    assert result["reporting"]["final_audit"]["evidence"]["eval_result"]["metrics"] == {"gate/quality": 0.65}
    assert result["reporting"]["gate_calls"] == 2
    assert not [call for call in domain.calls if call["cycle"] == 2 and call["request"]["split_id"] == "admission"]
    assert result["proxy_validity"]["mode"] == "degraded"
    assert_costs(fw, provider, domain)
    assert fw.replay()["replay_certificate"]["passed"]


def test_failed_uncached_incumbent_anchor_vetoes_without_running_new_candidate_anchor(tmp_path):
    class FailedBaselineDomain(Domain):
        async def evaluate(self, proposal, request):
            result = await super().evaluate(proposal, request)
            if proposal.candidate.created_cycle == 1 and request.split_id == "calibration":
                return replace(result, status=EvalStatus.FAILED_TO_RUN, metrics={})
            return result
    provider, domain = Provider(), FailedBaselineDomain(truths=(1, 2, 100))
    fw = build(tmp_path, assembly=profile(every=2), llm=provider, domain=domain, generations=2)
    result = fw.evolve(TASK)
    assert [call["cycle"] for call in calibration_calls(domain)] == [0, 1]
    assert [row["decision"]["admit"] for row in rows(fw, "composed_decision")] == [True, True, False]
    assert "incumbent calibration baseline did not succeed" in rows(fw, "composed_decision")[-1]["decision"]["reason"]
    assert not [call for call in domain.calls if call["cycle"] == 2 and call["request"]["split_id"] == "admission"]
    assert result["proxy_validity"]["mode"] == "degraded"
    assert result["reporting"]["gate_calls"] == 2
    assert_costs(fw, provider, domain)
    assert fw.replay()["replay_certificate"]["passed"]


def test_rehashed_negative_memory_cannot_replace_the_actual_calibration_receipts(tmp_path):
    from core.composition.context import _hash
    original = build(tmp_path, generations=1)
    original.evolve(TASK)
    payload = RunCheckpoint.load(tmp_path / "checkpoint.json").payload
    memory = payload["memory"]
    entry = next(item for item in memory["entries"] if item["id"].startswith("proxy-feedback:"))
    old_ref = entry["provenance"]["evidence_refs"][0]
    binding = memory["bindings"].pop(old_ref)
    binding["feedback"]["current"]["true_score"] = 999
    new_ref = _hash(binding)
    memory["bindings"][new_ref] = binding
    entry["provenance"]["evidence_refs"] = [new_ref]
    entry["payload"]["body"] = {"observation": copy.deepcopy(binding["feedback"])}
    RunCheckpoint.create(payload).save(tmp_path / "checkpoint.json")
    provider, domain = Provider(), Domain()
    resumed = build(tmp_path, generations=1, resume=True, llm=provider, domain=domain)
    before = original.store.path.read_bytes()
    with pytest.raises(ValueError, match="feedback differs"):
        resumed.evolve(TASK)
    assert provider.calls == 0 and domain.calls == []
    assert original.store.path.read_bytes() == before
