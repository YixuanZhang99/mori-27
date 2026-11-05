"""Original construction outcomes survive restart without replacement calls."""
import asyncio
import copy
import json
from dataclasses import replace

import pytest

from core.composition.artifacts import NativeArtifactBackend
from core.composition.construction import PromptMaterializer, _ref
from core.composition.contracts import OperatorFailure
from core.composition.evaluation import binding_for
from core.composition.execution import CandidateExecution, Materialization
from core.composition.provider import MeteredProvider
from core.composition.recovery import ContinuationStore, RecordedOutcomeStore
from core.executor.evaluation_contract import EvaluationContract
from core.executor.types import CostVec, EvalRequest, EvalResult, EvalStatus
from core.llm import UsageError
from core.x1.checkpoint import RunCheckpoint
from test_construction import ROLES, plan, response


OP = {"run_id": "run-1", "cycle": 0, "phase": "operator", "intent_id": "construct-1",
      "fingerprint": "sha256:" + "a" * 64, "manifest_sha256": "sha256:" + "b" * 64,
      "lane": "main", "slot_id": None}


class Crash(BaseException):
    pass


class CrashStore(ContinuationStore):
    cut = None

    def _write(self, row):
        super()._write(row)
        if row["kind"] == self.cut:
            self.cut = None
            raise Crash(row["kind"])


class Provider:
    def __init__(self, *, forbidden=False, output=None):
        self.calls, self.index = 0, 0
        self.forbidden, self.output = forbidden, output

    def __call__(self, prompt):
        assert not self.forbidden, "provider was called during adoption"
        self.calls += 1
        self.index += 1
        self.last_usage = {"total_tokens": 7}
        return self.output if self.output is not None else response("frozen artifact")

    def checkpoint_state(self):
        return {"index": self.index}

    def restore_state(self, state):
        self.index = state["index"]


class Domain:
    evaluator_version = "domain-1"
    evaluation_context = "sha256:" + "d" * 64

    def __init__(self, *, forbidden=False):
        self.calls, self.artifacts = 0, []
        self.forbidden = forbidden

    def validate_request(self, request):
        request.validate()

    async def evaluate(self, proposal, request):
        assert not self.forbidden, "evaluator was called during adoption"
        self.calls += 1
        self.artifacts.append(proposal.artifact)
        binding = binding_for(proposal, request, evaluator_version=self.evaluator_version,
                              evaluation_context=self.evaluation_context)
        return EvalResult(EvalStatus.OK, {"dev/score": len(proposal.artifact)},
            cost=CostVec(eval_count=1), fidelity=request.fidelity,
            contract=EvaluationContract(binding, ("token", "node", "eval_count")))


class ForbiddenMaterializer:
    def __init__(self, original):
        self.manifest_binding = original.manifest_binding

    async def construct(self, *args):
        raise AssertionError("materializer was invoked during terminal adoption")


def start(path):
    store = CrashStore(path / "events.jsonl")
    checkpoint = RunCheckpoint.create({"git_state": {}, "inflight_executor": [], "messages": []})
    store.append("composed_checkpoint", {"sha256": checkpoint.payload_sha256})
    return store, checkpoint


def resume(store, checkpoint):
    restored = ContinuationStore(store.path, checkpoint)
    restored.resume()
    return restored


def executor(path, store, *, provider=None, domain=None, materializer=None, backend=None):
    provider = provider or Provider()
    metered = MeteredProvider(provider)
    owner = CandidateExecution(materializer or PromptMaterializer(ROLES),
        backend or NativeArtifactBackend(path / "artifacts"), store, metered, domain or Domain())
    return owner, metered, provider


def run(owner, operation=None):
    return asyncio.run(owner.materialize(plan(), operation=operation or OP))


def evaluate(owner, materialized, split="dev", *, operation=None):
    request = EvalRequest(split, split_id=split)
    operation = operation or {**OP, "phase": split, "intent_id": "evaluate-" + split}
    return asyncio.run(owner.evaluate(materialized, request, operation=operation))


def test_completed_artifact_is_adopted_without_constructor_or_provider(tmp_path):
    store, checkpoint = start(tmp_path)
    owner, meter, raw = executor(tmp_path, store)
    first = run(owner)
    assert first.proposal.artifact == "frozen artifact"
    assert meter.usage_total == 7 and raw.calls == 1
    restored = resume(store, checkpoint)
    second, restored_meter, restored_raw = executor(tmp_path, restored, provider=Provider(forbidden=True),
        materializer=ForbiddenMaterializer(PromptMaterializer(ROLES)))
    before = store.path.read_bytes()
    adopted = run(second)
    assert adopted.to_dict() == first.to_dict()
    assert restored_meter.usage_total == 7 and restored_raw.index == 1 and restored_raw.calls == 0
    assert store.path.read_bytes() == before
    assert run(second).ref == adopted.ref and restored_meter.usage_total == 7


def test_each_split_evaluates_the_same_artifact_without_regeneration(tmp_path):
    store, _ = start(tmp_path)
    domain = Domain()
    owner, _, raw = executor(tmp_path, store, domain=domain)
    materialized = run(owner)
    for split in ("dev", "admission", "final_audit"):
        evidence = evaluate(owner, materialized, split)
        assert evidence.eval_result.cost.eval_count == 1
    assert raw.calls == 1 and domain.artifacts == ["frozen artifact"] * 3
    assert owner.operation_metadata({**OP, "phase": "dev", "intent_id": "evaluate-dev"})["wall_seconds"] >= 0


@pytest.mark.parametrize("cut", ["construction_started", "composed_provider_completed",
                                  "construction_outcome", "materialization_completed"])
def test_interrupted_materialization_uses_original_provider_completion(tmp_path, cut):
    store, checkpoint = start(tmp_path)
    store.cut = cut
    first, _, raw = executor(tmp_path, store)
    with pytest.raises(Crash):
        run(first)
    restored = resume(store, checkpoint)
    recovered, meter, next_raw = executor(tmp_path, restored,
        provider=Provider(forbidden=cut != "construction_started"))
    result = run(recovered)
    assert result.proposal.artifact == "frozen artifact" and meter.usage_total == 7
    assert raw.calls + next_raw.calls == 1
    assert len(list(restored.read("composed_provider_started"))) == 1
    assert len(list(restored.read("composed_provider_completed"))) == 1
    assert len(list(restored.read("materialization_completed"))) == 1


def test_ambiguous_native_provider_start_never_dispatches_a_replacement(tmp_path):
    store, checkpoint = start(tmp_path)
    store.cut = "composed_provider_started"
    owner, _, raw = executor(tmp_path, store)
    with pytest.raises(Crash):
        run(owner)
    restored, before = resume(store, checkpoint), store.path.read_bytes()
    recovered, _, next_raw = executor(tmp_path, restored, provider=Provider(forbidden=True))
    with pytest.raises(UsageError):
        run(recovered)
    assert raw.calls == next_raw.calls == 0 and store.path.read_bytes() == before


def test_terminal_only_constructor_is_not_reentered_after_an_incomplete_start(tmp_path):
    materializer = ForbiddenMaterializer(PromptMaterializer(ROLES))
    materializer.manifest_binding["recovery_model"] = "terminal_only"
    store, checkpoint = start(tmp_path)
    store.cut = "construction_started"
    owner, _, _ = executor(tmp_path, store, materializer=materializer)
    with pytest.raises(Crash):
        run(owner)
    recovered, _, _ = executor(tmp_path, resume(store, checkpoint), materializer=materializer)
    with pytest.raises(UsageError):
        run(recovered)


def test_unknown_custom_validator_cannot_claim_a_durable_binding(tmp_path):
    store, _ = start(tmp_path)
    with pytest.raises(ValueError):
        executor(tmp_path, store, materializer=PromptMaterializer(ROLES, validator=lambda text: ()))


@pytest.mark.parametrize("change", ["operation", "plan", "materializer"])
def test_changed_construction_binding_is_rejected_before_new_work(tmp_path, change):
    store, checkpoint = start(tmp_path)
    first, _, _ = executor(tmp_path, store)
    run(first)
    raw = Provider(forbidden=True)
    second, _, _ = executor(tmp_path, resume(store, checkpoint), provider=raw,
        materializer=PromptMaterializer(ROLES, max_attempts=2 if change == "materializer" else 1))
    op = {**OP, "fingerprint": "sha256:" + "c" * 64} if change == "operation" else OP
    value = plan(role="coder") if change == "plan" else plan()
    with pytest.raises(ValueError):
        asyncio.run(second.materialize(value, operation=op))
    assert raw.calls == 0


def test_artifact_tampering_is_detected_before_evaluation(tmp_path):
    store, _ = start(tmp_path)
    domain = Domain()
    owner, _, _ = executor(tmp_path, store, domain=domain)
    materialized = run(owner)
    blob = next(p for p in (tmp_path / "artifacts").iterdir() if p.is_file())
    blob.write_text("tampered bytes")
    with pytest.raises(ValueError):
        evaluate(owner, materialized)
    assert domain.calls == 0


def test_materialization_codec_rejects_changed_outcome_and_cost(tmp_path):
    store, _ = start(tmp_path)
    owner, _, _ = executor(tmp_path, store)
    value = run(owner)
    encoded = value.to_dict()
    encoded["construction_result"]["cost"]["tokens_in"] = 0
    with pytest.raises(ValueError):
        Materialization.from_dict(encoded)
    assert Materialization.from_dict(value.to_dict()).ref == value.ref


def test_known_construction_failure_is_durable_and_stays_charged(tmp_path):
    store, checkpoint = start(tmp_path)
    owner, _, raw = executor(tmp_path, store, provider=Provider(output="invalid json"))
    with pytest.raises(OperatorFailure) as first:
        run(owner)
    restored = resume(store, checkpoint)
    second, meter, _ = executor(tmp_path, restored, provider=Provider(forbidden=True),
        materializer=ForbiddenMaterializer(PromptMaterializer(ROLES)))
    with pytest.raises(OperatorFailure) as adopted:
        run(second)
    assert first.value.cost == adopted.value.cost == CostVec(tokens_in=7, node_count=1)
    assert meter.usage_total == 7 and raw.calls == 1
    assert not list(restored.read("materialization_completed"))


def test_artifact_publication_failure_does_not_discard_known_bill(tmp_path):
    class Unavailable(NativeArtifactBackend):
        def publish(self, *args, **kwargs):
            raise OSError("disk full")
    store, checkpoint = start(tmp_path)
    first, _, raw = executor(tmp_path, store, backend=Unavailable(tmp_path / "artifacts"))
    with pytest.raises(OperatorFailure) as failure:
        run(first)
    assert failure.value.cost.tokens_in == 7 and raw.calls == 1
    second, _, _ = executor(tmp_path, resume(store, checkpoint), provider=Provider(forbidden=True))
    with pytest.raises(OperatorFailure) as adopted:
        run(second)
    assert adopted.value.cost == failure.value.cost


def test_evaluation_completion_is_adopted_without_reconstructing_or_reevaluating(tmp_path):
    store, checkpoint = start(tmp_path)
    owner, _, _ = executor(tmp_path, store)
    materialized = run(owner)
    store.cut = "governed_evaluation_completed"
    with pytest.raises(Crash):
        evaluate(owner, materialized)
    restored = resume(store, checkpoint)
    recovered, _, _ = executor(tmp_path, restored, provider=Provider(forbidden=True),
        domain=Domain(forbidden=True), materializer=ForbiddenMaterializer(PromptMaterializer(ROLES)))
    original = run(recovered)
    evidence = evaluate(recovered, original)
    assert evidence.eval_result.metrics["dev/score"] == len("frozen artifact")
    assert len(list(restored.read("governed_evaluation_completed"))) == 1


def test_recorded_replay_has_no_materializer_provider_evaluator_or_blob_writes(tmp_path):
    store, _ = start(tmp_path)
    owner, _, _ = executor(tmp_path, store)
    materialized = run(owner)
    evidence = evaluate(owner, materialized)
    rows = [row for row in store.rows if row["kind"] != "composed_checkpoint"]
    replay = RecordedOutcomeStore(tmp_path / "replay.jsonl", rows)
    snapshot = {p.name: p.read_bytes() for p in (tmp_path / "artifacts").iterdir()}
    recovered, _, _ = executor(tmp_path, replay, provider=Provider(forbidden=True),
        domain=Domain(forbidden=True), materializer=ForbiddenMaterializer(PromptMaterializer(ROLES)))
    assert evaluate(recovered, run(recovered)) == evidence
    assert snapshot == {p.name: p.read_bytes() for p in (tmp_path / "artifacts").iterdir()}
    assert replay.peek() is None


def test_repeated_known_failure_keeps_its_original_bill(tmp_path):
    store, _ = start(tmp_path)
    owner, meter, raw = executor(tmp_path, store, provider=Provider(output="invalid json"))
    for _ in range(2):
        with pytest.raises(OperatorFailure) as failure:
            run(owner)
        assert failure.value.cost.tokens_in == 7
    assert raw.calls == 1 and meter.usage_total == 7


def test_another_journals_materialization_cannot_authorize_evaluation(tmp_path):
    store, _ = start(tmp_path)
    owner, _, _ = executor(tmp_path, store)
    materialized = run(owner)
    foreign, _ = start(tmp_path / "foreign")
    domain = Domain()
    reader, _, _ = executor(tmp_path, foreign, domain=domain)
    with pytest.raises(ValueError):
        evaluate(reader, materialized)
    assert domain.calls == 0


def test_materialization_codec_binds_descriptor_to_actual_artifact_bytes(tmp_path):
    store, _ = start(tmp_path)
    owner, _, _ = executor(tmp_path, store)
    value = run(owner).to_dict()
    value["artifact"]["reference"] = "sha256:" + "e" * 64
    with pytest.raises(ValueError):
        Materialization.from_dict(value)


def test_wrong_plan_output_has_a_durable_known_bill_and_integrity_failure(tmp_path):
    class WrongPlan(PromptMaterializer):
        async def construct(self, ignored, provider):
            return await super().construct(plan(role="coder"), provider)
    store, checkpoint = start(tmp_path)
    owner, _, raw = executor(tmp_path, store, materializer=WrongPlan(ROLES))
    with pytest.raises(OperatorFailure) as failure:
        run(owner)
    assert failure.value.cost.tokens_in == 7 and failure.value.integrity_failure
    second, meter, _ = executor(tmp_path, resume(store, checkpoint), provider=Provider(forbidden=True),
        materializer=ForbiddenMaterializer(WrongPlan(ROLES)))
    with pytest.raises(OperatorFailure) as adopted:
        run(second)
    assert adopted.value.cost == failure.value.cost and adopted.value.integrity_failure
    assert raw.calls == 1 and meter.usage_total == 7


def test_invalid_publication_descriptor_preserves_the_construction_bill(tmp_path):
    class WrongDescriptor(NativeArtifactBackend):
        def publish(self, artifact, **kwargs):
            descriptor = super().publish(artifact, **kwargs)
            return {**descriptor, "unexpected": True}

        def load(self, descriptor):
            return super().load({k: v for k, v in descriptor.items() if k != "unexpected"})
    store, checkpoint = start(tmp_path)
    owner, _, _ = executor(tmp_path, store, backend=WrongDescriptor(tmp_path / "artifacts"))
    with pytest.raises(OperatorFailure) as failure:
        run(owner)
    assert failure.value.integrity_failure and failure.value.cost.tokens_in == 7
    recovered, meter, raw = executor(tmp_path, resume(store, checkpoint), provider=Provider(forbidden=True))
    with pytest.raises(OperatorFailure) as adopted:
        run(recovered)
    assert adopted.value.integrity_failure and adopted.value.cost == failure.value.cost
    assert meter.usage_total == 7 and raw.calls == 0


@pytest.mark.parametrize("elapsed", [-1, True, float("inf")])
def test_cached_evaluation_rejects_invalid_original_duration(tmp_path, elapsed):
    store, _ = start(tmp_path)
    owner, _, _ = executor(tmp_path, store)
    materialized = run(owner)
    evaluate(owner, materialized)
    # Simulate invalid decoded durable data before the cached-return path.
    row = next(row for row in store.rows if row["kind"] == "governed_evaluation_completed")
    row["payload"]["elapsed"] = elapsed
    with pytest.raises(ValueError):
        evaluate(owner, materialized)


def test_cached_evaluation_rejects_duplicate_terminal_outcomes(tmp_path):
    store, _ = start(tmp_path)
    owner, _, _ = executor(tmp_path, store)
    materialized = run(owner)
    evaluate(owner, materialized)
    row = next(store.read("governed_evaluation_completed"))
    store.append(row["kind"], row["payload"])
    with pytest.raises(ValueError):
        evaluate(owner, materialized)


def test_published_record_cannot_replace_its_original_construction_outcome(tmp_path):
    store, _ = start(tmp_path)
    owner, _, _ = executor(tmp_path, store)
    original = run(owner)
    forged = original.to_dict()
    forged['construction_result']['artifact'] = 'different measured artifact'
    forged['artifact'] = owner.backend.publish('different measured artifact',
        operation=forged['identity']['operation'])
    forged['outcome_ref'] = _ref({'identity': forged['identity'],
        'outcome': {'kind': 'returned', 'result': forged['construction_result']}})
    materialized = Materialization.from_dict(forged)
    row = next(row for row in store.rows if row['kind'] == 'materialization_completed')
    row['payload'] = copy.deepcopy(forged)
    # The substituted bytes and self-hash agree; the original producer terminal does not.
    with pytest.raises(ValueError):
        evaluate(owner, materialized)
    with pytest.raises(ValueError):
        run(owner)
    assert owner.evaluator.calls == 0
