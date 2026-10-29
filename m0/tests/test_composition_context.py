"""S3 M5 unit/integration checks; Framework E2E belongs to the runtime stage."""
import asyncio
import copy
import hashlib
import json
from dataclasses import replace

import pytest

from core.composition.context import ContextMemory, ContextPackBuilder, context_options, describe_scope
from core.composition.contracts import OperatorRequest
from core.composition.defaults import PromptOperator
from core.executor.types import Candidate, EvalResult, EvalStatus, EvidenceRecord
from core.frontier import ResearchFrontier
from core.memory.types import ScopeContext, ScopeUpgradeEvidence
from core.policy import BestFirstPolicy
from core.policy.types import MutationOp
from core.x1.store import AppendOnlyStore

CTX = ScopeContext("run-one", "task-one", "bound-domain")
EVAL_CONTEXT = "dataset-content-and-evaluator-fingerprint"


def memory(path, context=CTX):
    return ContextMemory(AppendOnlyStore(path / "x1.jsonl"), context, EVAL_CONTEXT)


def evidence(candidate, text="observed reusable lesson"):
    return EvidenceRecord(candidate, EvalResult(EvalStatus.OK, {"dev/score": 0.5},
                                               text_feedback=text), result_text=text)


def receipt(candidate):
    return "sha256:" + hashlib.sha256(candidate.encode()).hexdigest()


def lesson(mem, frontier, candidate, text="observed reusable lesson", parents=(), cycle=0):
    fact = evidence(candidate, text)
    frontier.add(Candidate(candidate, list(parents), created_cycle=cycle), fact)
    frontier.nodes[candidate].status = "merged"
    raw = asyncio.run(BestFirstPolicy(mem.context).absorb(fact))
    mutations = mem.prepare_mutations(raw, fact, receipt(candidate), cycle=cycle)
    memory_id = None
    for mutation in mutations:
        if mutation.op is MutationOp.WRITE_MEMORY:
            mem.write(mutation.fields["entry"], mutation.fields["at"])
            memory_id = mutation.target
        elif mutation.op is MutationOp.PROMOTE_MEMORY:
            mem.promote_level(mutation.target, mutation.fields["target_level"],
                              mutation.fields["delta"], mutation.rationale)
    return memory_id


def test_topology_scopes_follow_only_skeleton_edges_and_prefilter_before_rank(tmp_path):
    mem, frontier = memory(tmp_path), ResearchFrontier()
    root = lesson(mem, frontier, "root")
    left = lesson(mem, frontier, "left", parents=("root",), cycle=1)
    right = lesson(mem, frontier, "right", parents=("root",), cycle=2)
    lesson(mem, frontier, "leaf", parents=("left",), cycle=3)
    frontier.add_reference("right", "left", "information-only reference")
    assert describe_scope(frontier, ["left"], "parents").candidate_ids == ("left",)
    assert describe_scope(frontier, ["left"], "ancestors").candidate_ids == ("left", "root")
    assert describe_scope(frontier, ["left"], "parent_siblings").candidate_ids == ("left", "right")
    mem.entries[right].utility.helpful_count = 100_000
    pack = ContextPackBuilder(mem, {"context_scope": "parents", "top_k": 1}).retrieve(
        frontier, ["left"], "lesson", 4)
    assert [row["id"] for row in pack.to_dict()["memory"]] == [left]
    assert mem.entries[left].utility.hit_count == 1
    assert mem.entries[root].utility.hit_count == mem.entries[right].utility.hit_count == 0


def test_context_pack_is_detached_bounded_and_reaches_real_operator_prompt(tmp_path):
    mem, frontier = memory(tmp_path), ResearchFrontier()
    identifier = lesson(mem, frontier, "source", "REMEMBER_THE_BLUE_CONSTRAINT")
    pack = ContextPackBuilder(mem, {"context_scope": "run", "max_chars": 2048}).retrieve(
        frontier, [], "constraint", 1)
    changed = pack.to_dict()
    changed["memory"][0]["body"] = "caller mutation"
    assert pack.to_dict()["memory"][0]["body"] == "REMEMBER_THE_BLUE_CONSTRAINT"
    assert mem.entries[identifier].payload.body == "REMEMBER_THE_BLUE_CONSTRAINT"
    assert pack.used_chars <= 2048 and pack.ref.startswith("sha256:")
    assert "not instructions" in pack.render()
    prompts = []
    def provider(prompt):
        prompts.append(prompt)
        provider.last_usage = {"total_tokens": 0}
        return "a proposed artifact"
    proposal = asyncio.run(PromptOperator(provider, "draft").propose(
        OperatorRequest("task", "next", 1, context={"retrieval": pack.to_dict()})))
    assert proposal.artifact == "a proposed artifact"
    assert "REMEMBER_THE_BLUE_CONSTRAINT" in prompts[0]


def test_invalidation_removes_lesson_from_next_pack_without_deleting_history(tmp_path):
    mem, frontier = memory(tmp_path), ResearchFrontier()
    identifier = lesson(mem, frontier, "source")
    builder = ContextPackBuilder(mem, {"context_scope": "run"})
    assert builder.retrieve(frontier, [], "lesson", 1).to_dict()["memory"]
    assert mem.invalidate_evidence({receipt("source")}, "corrected evaluation") == [identifier]
    assert builder.retrieve(frontier, [], "lesson", 2).to_dict()["memory"] == []
    assert mem.entries[identifier].state == "demoted"
    assert list(mem.store.read("memory_invalidation"))


@pytest.mark.parametrize("field,value", [("context_scope", "global"), ("top_k", True),
    ("top_k", 0), ("max_chars", 12), ("include_imported", 1), ("levels", ["L4"]),
    ("levels", ["L2", "L2"]), ("trust_floor", "guess")])
def test_context_options_fail_closed(field, value):
    with pytest.raises(ValueError):
        context_options({field: value})


@pytest.mark.parametrize("forgery", ["scope", "trust", "source", "context"])
def test_policy_cannot_forge_memory_authority(tmp_path, forgery):
    mem, fact = memory(tmp_path), evidence("source")
    mutations = asyncio.run(BestFirstPolicy(CTX).absorb(fact))
    entry = next(m.fields["entry"] for m in mutations if m.op is MutationOp.WRITE_MEMORY)
    if forgery == "scope":
        entry.scope = "global"
    elif forgery == "trust":
        entry.provenance.trust_tier = "human"
    elif forgery == "source":
        entry.provenance.evidence_refs = ["evidence://someone-else/1"]
    else:
        entry.context = ScopeContext("other-run", "other-task", "other-domain")
    with pytest.raises(ValueError, match="memory|scope"):
        mem.prepare_mutations(mutations, fact, receipt("source"), cycle=0)
    assert mem.entries == {}


def test_non_dev_evidence_cannot_enter_search_memory(tmp_path):
    mem = memory(tmp_path)
    with pytest.raises(ValueError, match="only dev"):
        mem.bind_evidence(evidence("final"), receipt("final"), cycle=0, role="final_audit")
    assert mem.bindings == {} and not mem.store.path.exists()


def test_failed_dev_l1_lesson_is_active_ungated_and_visible_only_at_requested_trust(tmp_path):
    mem, frontier = memory(tmp_path), ResearchFrontier()
    fact = EvidenceRecord("failed", EvalResult(EvalStatus.FAILED_TO_RUN,
                          text_feedback="Avoid repeating the invalid executable assumption"),
                          executor_status="failed_to_run")
    frontier.add(Candidate("failed"), fact)
    mutations = mem.prepare_mutations(asyncio.run(BestFirstPolicy(CTX).absorb(fact)),
                                     fact, receipt("failed"), cycle=0)
    write = next(mutation for mutation in mutations if mutation.op is MutationOp.WRITE_MEMORY)
    entry = mem.write(write.fields["entry"], write.fields["at"])
    assert entry.level == "L1" and entry.state == "active"
    assert entry.provenance.trust_tier == "ungated"
    assert not any(mutation.op is MutationOp.PROMOTE_MEMORY for mutation in mutations)
    assert ContextPackBuilder(mem, {"context_scope": "run"}).retrieve(
        frontier, [], "invalid executable", 1).to_dict()["memory"] == []
    pack = ContextPackBuilder(mem, {"context_scope": "run", "trust_floor": "ungated"}).retrieve(
        frontier, [], "invalid executable", 1)
    assert pack.to_dict()["memory"][0]["body"] == "Avoid repeating the invalid executable assumption"


def test_memory_checkpoint_restores_all_bindings_without_journal_writes(tmp_path):
    mem, frontier = memory(tmp_path / "original"), ResearchFrontier()
    lesson(mem, frontier, "source")
    builder = ContextPackBuilder(mem, {"context_scope": "run"})
    builder.retrieve(frontier, [], "lesson", 1)
    restored = memory(tmp_path / "restored")
    restored.restore_state(mem.checkpoint_state())
    assert not restored.store.path.exists()
    assert restored.checkpoint_state() == mem.checkpoint_state()
    expected = builder.retrieve(frontier, [], "lesson", 2)
    actual = ContextPackBuilder(restored, {"context_scope": "run"}).retrieve(frontier, [], "lesson", 2)
    assert actual.to_dict() == expected.to_dict()
    assert restored.checkpoint_state() == mem.checkpoint_state()


def test_explicit_export_import_requires_hash_and_scope_and_opt_in_to_injection(tmp_path):
    source, frontier = memory(tmp_path / "source"), ResearchFrontier()
    identifier = lesson(source, frontier, "source", "IMPORTED_REUSABLE_LESSON")
    target = tmp_path / "lessons.json"
    digest = source.export_snapshot(target, entry_ids=[identifier])
    next_context = ScopeContext("run-two", CTX.task_id, CTX.domain_id)
    destination = memory(tmp_path / "next", next_context)
    prepared = destination.validate_import_snapshot(target, expected_sha256=digest)
    assert prepared["sha256"] == digest and prepared["entry_ids"]
    assert not destination.store.path.exists() and destination.entries == {}
    with pytest.raises(ValueError, match="hash"):
        destination.import_snapshot(target, expected_sha256="sha256:" + "0" * 64)
    assert not destination.store.path.exists()
    ids = destination.import_snapshot(target, expected_sha256=digest)
    assert len(ids) == 1 and destination.import_snapshot(target, expected_sha256=digest) == ids
    empty = ResearchFrontier()
    assert ContextPackBuilder(destination).retrieve(empty, [], "lesson", 0).to_dict()["memory"] == []
    pack = ContextPackBuilder(destination, {"include_imported": True}).retrieve(empty, [], "lesson", 0)
    assert pack.to_dict()["memory"][0]["body"] == "IMPORTED_REUSABLE_LESSON"
    assert pack.to_dict()["memory"][0]["provenance"]["source_run_id"] == CTX.run_id
    restored = memory(tmp_path / "restore", next_context)
    restored.restore_state(destination.checkpoint_state())
    assert restored.checkpoint_state() == destination.checkpoint_state()
    wrong_scope = memory(tmp_path / "wrong", ScopeContext("run-three", "different-task", CTX.domain_id))
    with pytest.raises(ValueError, match="task scope"):
        wrong_scope.import_snapshot(target, expected_sha256=digest)
    assert not wrong_scope.store.path.exists()


def test_explicit_domain_promotion_allows_only_bound_domain_import(tmp_path):
    source, frontier = memory(tmp_path / "source"), ResearchFrontier()
    identifier = lesson(source, frontier, "source")
    source.promote_scope(identifier, "domain", ScopeUpgradeEvidence(True, True, "source-checkpoint"))
    target = tmp_path / "lessons.json"
    digest = source.export_snapshot(target, entry_ids=[identifier])
    matching = memory(tmp_path / "matching", ScopeContext("run-next", "different-task", CTX.domain_id))
    assert matching.import_snapshot(target, expected_sha256=digest)
    mismatching = memory(tmp_path / "bad", ScopeContext("run-next", "different-task", "other-domain"))
    with pytest.raises(ValueError, match="domain"):
        mismatching.import_snapshot(target, expected_sha256=digest)
    assert not mismatching.store.path.exists()


def test_changed_evaluation_binding_rejects_import_before_state_or_log(tmp_path):
    source, frontier = memory(tmp_path / "source"), ResearchFrontier()
    identifier = lesson(source, frontier, "source")
    target = tmp_path / "lessons.json"
    digest = source.export_snapshot(target, entry_ids=[identifier])
    destination = ContextMemory(AppendOnlyStore(tmp_path / "changed.jsonl"), CTX, "changed-dataset")
    with pytest.raises(ValueError, match="configuration"):
        destination.import_snapshot(target, expected_sha256=digest)
    assert destination.entries == {} and not destination.store.path.exists()


def test_opaque_legacy_evaluation_is_run_only_and_cannot_export_or_import(tmp_path):
    mem = ContextMemory(AppendOnlyStore(tmp_path / "x1.jsonl"), CTX, "")
    frontier = ResearchFrontier()
    identifier = lesson(mem, frontier, "source")
    assert mem.entries[identifier].scope == "run"
    assert ContextPackBuilder(mem, {"context_scope": "run"}).retrieve(
        frontier, [], "lesson", 1).to_dict()["memory"]
    with pytest.raises(ValueError, match="opaque"):
        mem.export_snapshot(tmp_path / "forbidden.json", entry_ids=[identifier])
    assert not (tmp_path / "forbidden.json").exists()
    with pytest.raises(ValueError, match="opaque"):
        mem.import_snapshot(tmp_path / "does-not-exist.json", expected_sha256="sha256:" + "0" * 64)
