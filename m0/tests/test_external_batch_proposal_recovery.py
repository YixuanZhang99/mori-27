"""v41 real SIGKILL recovery at certified external proposal operation boundaries."""
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from core.loop import Framework
from core.x1.checkpoint import certified_snapshot_ref
from core.x1.store import AppendOnlyStore
from examples.toy_gepa import MockLLM
from test_external_batch_partial_start_recovery import crash_after_proposals, reference_run
from test_external_batch_recovery import config, recovered_framework
from test_external_evaluator import TASK, evaluator, workspace
from test_external_recovery import COMPARE, ForbiddenLLM


class CountingLLM(MockLLM):
    def __init__(self):
        self.prompts = []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        return super().__call__(prompt)


def test_real_safe_proposal_gap_continues_only_missing_llm_operation(tmp_path):
    expected, reference_dir = reference_run(tmp_path, "reference-proposal-gap")
    reference_store = AppendOnlyStore(reference_dir / "x1.jsonl")
    assert len(list(reference_store.read("m0_proposal_started"))) == 2
    assert len(list(reference_store.read("m0_evaluation_started"))) == 3
    assert len(list(reference_store.read("executor_process_started"))) == 3

    root, script = workspace(tmp_path, "proposal-gap-workspace")
    run_dir = tmp_path / "recovered-proposal-gap"
    store = AppendOnlyStore(run_dir / "x1.jsonl")
    crash_after_proposals(run_dir, root, script, 1)
    cohort = list(store.read("batch_cycle_started"))[0]["payload"]
    original_contexts = [row["payload"] for row in store.read("m0_evaluation_started")
                         if row["payload"].get("cohort_id") == cohort["cohort_id"]]
    assert [row["proposal"]["proposal_id"] for row in original_contexts] == \
        cohort["candidate_ids"][:1]
    assert [row["payload"]["candidate_id"] for row in store.read("m0_proposal_started")] == \
        cohort["candidate_ids"][:1]
    assert len(list(store.read("executor_process_started"))) == 1  # genesis only

    llm = CountingLLM()
    resumed = Framework(llm, evaluator(root, script, store), config(resume=True), str(run_dir))
    actual = resumed.evolve(TASK)
    for key in COMPARE:
        assert actual[key] == expected[key], key
    assert actual["resumed"] is True and actual["completed"] is True
    assert len(llm.prompts) == 1  # the persisted first proposal was not regenerated
    assert "CURRENT PROMPT:" in llm.prompts[0]
    contexts = [row["payload"] for row in store.read("m0_evaluation_started")
                if row["payload"].get("cohort_id") == cohort["cohort_id"]]
    assert contexts[:1] == original_contexts
    assert [row["proposal"]["proposal_id"] for row in contexts] == cohort["candidate_ids"]
    assert len(list(store.read("m0_proposal_started"))) == 2
    assert len(list(store.read("executor_process_started"))) == 3
    assert len(list(store.read("external_evaluator_outcome"))) == 3
    adoptions = list(store.read("m0_batch_recovery_adopted"))
    assert len(adoptions) == 1
    report = adoptions[0]["payload"]
    assert report["adopted_process_count"] == 0
    assert report["continued_process_count"] == 2
    assert report["continued_candidate_ids"] == cohort["candidate_ids"]
    assert report["continued_proposal_count"] == 1
    assert report["continued_proposal_ids"] == cohort["candidate_ids"][1:]
    assert report["reexecuted"] is False
    assert resumed.inspect()["governance_pass"] is True
    assert certified_snapshot_ref(reference_dir / "checkpoint.json") == \
        certified_snapshot_ref(run_dir / "checkpoint.json")

    counted_kinds = ("m0_proposal_started", "m0_evaluation_started",
                     "executor_process_started", "external_evaluator_outcome",
                     "batch_execution_settled", "m0_batch_recovery_adopted",
                     "state_mutation", "admission_receipt")
    before = [(kind, len(list(store.read(kind)))) for kind in counted_kinds]
    completed = recovered_framework(run_dir, root, script)
    repeated = completed.evolve(TASK)
    after = [(kind, len(list(store.read(kind)))) for kind, _ in before]
    assert repeated["resumed"] is True and repeated["completed"] is True
    assert after == before

    resumed.llm = MockLLM()
    replayed = resumed.replay()
    assert resumed.inspect()["replay_certified"] is True
    for key in COMPARE:
        assert replayed[key] == expected[key], key


def test_incomplete_proposals_with_settlement_fail_before_llm_or_process(tmp_path):
    root, script = workspace(tmp_path, "proposal-settlement-workspace")
    run_dir = tmp_path / "proposal-settlement"
    store = AppendOnlyStore(run_dir / "x1.jsonl")
    crash_after_proposals(run_dir, root, script, 1)
    cohort = list(store.read("batch_cycle_started"))[0]["payload"]
    store.append("batch_execution_settled", {
        "cohort_id": cohort["cohort_id"], "candidate_id": cohort["candidate_ids"][0],
        "intent_id": cohort["intents"][0]["intent_id"], "evidence": {}})
    before = len(list(store.read("executor_process_started")))
    proposals_before = len(list(store.read("m0_evaluation_started")))
    resumed = recovered_framework(run_dir, root, script)
    with pytest.raises(RuntimeError, match="partially started cohort cannot have batch settlement"):
        resumed.evolve(TASK)
    assert len(list(store.read("executor_process_started"))) == before
    assert len(list(store.read("m0_evaluation_started"))) == proposals_before
    assert not list(store.read("m0_batch_recovery_adopted"))


def test_legacy_incomplete_proposals_without_boundary_fail_closed(tmp_path):
    root, script = workspace(tmp_path, "legacy-proposal-workspace")
    run_dir = tmp_path / "legacy-proposal"
    store = AppendOnlyStore(run_dir / "x1.jsonl")
    crash_after_proposals(run_dir, root, script, 1)
    evidence = run_dir / "x1.jsonl"
    records = [json.loads(line) for line in evidence.read_text().splitlines()]
    records = [row for row in records if row["kind"] != "m0_proposal_started"]
    evidence.write_text("".join(json.dumps(row) + "\n" for row in records))
    before = len(list(store.read("executor_process_started")))
    proposals_before = len(list(store.read("m0_evaluation_started")))
    resumed = Framework(ForbiddenLLM(), evaluator(root, script, store),
                        config(resume=True), str(run_dir))
    with pytest.raises(RuntimeError, match="durable proposals are incomplete"):
        resumed.evolve(TASK)
    assert len(list(store.read("executor_process_started"))) == before
    assert len(list(store.read("m0_evaluation_started"))) == proposals_before
    assert not list(store.read("m0_batch_recovery_adopted"))
