"""S3 local opened-source and explicit knowledge feedback contracts."""
import hashlib
from dataclasses import asdict

import pytest

from core.composition.context import ContextPackBuilder
from core.composition.knowledge import KnowledgePack, LocalKnowledge
from core.executor.types import CostVec
from core.frontier import ResearchFrontier
from core.memory.types import ScopeContext
from core.x1.store import AppendOnlyStore
from test_composition_context import CTX, EVAL_CONTEXT, lesson, memory, receipt


def knowledge(tmp_path, *, ground="opened grounded fact", audit="independent audit source"):
    tmp_path.mkdir(parents=True, exist_ok=True)
    ground_path, audit_path = tmp_path / "ground.txt", tmp_path / "audit.txt"
    ground_path.write_text(ground, encoding="utf-8")
    audit_path.write_text(audit, encoding="utf-8")
    options = {"ground_files": [{"path": str(ground_path)}],
               "audit_files": [{"path": str(audit_path)}]}
    store = AppendOnlyStore(tmp_path / "x1.jsonl")
    return LocalKnowledge(options, store, mode="research"), options


def test_research_constructor_reads_hash_bound_files_without_search_or_journal(tmp_path):
    knowledge_service, options = knowledge(tmp_path)
    assert knowledge_service.ground_backend is not knowledge_service.audit_backend
    assert knowledge_service.ground_backend.calls == knowledge_service.audit_backend.calls == []
    assert not knowledge_service.store.path.exists()
    source = knowledge_service.manifest_binding["ground"][0]
    assert source["sha256"] == "sha256:" + hashlib.sha256(b"opened grounded fact").hexdigest()
    assert source["uri"] == (tmp_path / "ground.txt").as_uri()
    ground_uris = {item["uri"] for item in knowledge_service.manifest_binding["ground"]}
    audit_uris = {item["uri"] for item in knowledge_service.manifest_binding["audit"]}
    assert ground_uris < audit_uris
    wrong = {**options, "ground_files": [{"path": str(tmp_path / "ground.txt"), "sha256": "sha256:" + "0" * 64}]}
    with pytest.raises(ValueError, match="hash"):
        LocalKnowledge(wrong, knowledge_service.store, mode="research")
    assert not knowledge_service.store.path.exists()


def test_benchmark_rejection_precedes_even_source_reads(tmp_path):
    options = {"ground_files": [{"path": str(tmp_path / "missing-ground")}],
               "audit_files": [{"path": str(tmp_path / "missing-audit")}]}
    store = AppendOnlyStore(tmp_path / "x1.jsonl")
    with pytest.raises(ValueError, match="benchmark"):
        LocalKnowledge(options, store, mode="benchmark")
    assert not store.path.exists()


def test_ground_context_and_audit_use_independent_queries_and_fields(tmp_path):
    service, _ = knowledge(tmp_path / "knowledge")
    ground = service.ground("q1", "grounded fact")
    audit = service.audit("candidate", "independent candidate artifact")
    assert ground.cost == audit.cost == CostVec()
    assert ground.context_items()[0]["findings"] == ["opened grounded fact"]
    assert ground.context_items()[0]["provenance"]["source_pages"] == [(tmp_path / "knowledge" / "ground.txt").as_uri()]
    assert service.ground_backend.calls == [{"query": "grounded fact", "lane": "ground"}]
    assert service.audit_backend.calls == [{"query": "independent candidate artifact", "lane": "audit"}]
    assert audit.to_dict()["advisory_only"] is True and not hasattr(audit, "context_items")
    mem = memory(tmp_path / "memory")
    pack = ContextPackBuilder(mem).retrieve(ResearchFrontier(), [], "fact", 0, grounding=ground)
    assert pack.to_dict()["memory"] == []
    assert "opened grounded fact" in pack.render()
    assert "independent audit source" not in pack.render()
    assert mem.entries == {}


@pytest.mark.parametrize("first", ["ground", "audit"])
def test_overlap_invalidates_audit_in_both_fetch_orders_and_survives_restore(tmp_path, first):
    service, options = knowledge(tmp_path / "knowledge", ground="identical fetched text", audit="identical fetched text")
    if first == "ground":
        service.ground("q1", "text")
        verdict = service.audit("candidate", "idea")
    else:
        verdict = service.audit("candidate", "idea")
        service.ground("q1", "text")
    audit_id = verdict.to_dict()["verdict"]["audit_id"]
    assert audit_id in service._service.invalidated_audits
    restored = LocalKnowledge(options, AppendOnlyStore(tmp_path / "restored.jsonl"), mode="research")
    restored.restore_state(service.checkpoint_state())
    assert not restored.store.path.exists()
    assert restored.checkpoint_state() == service.checkpoint_state()
    assert restored._service.merge_reference(audit_id) is None
    assert restored.ground("q2", "text").to_dict() == service.ground("q2", "text").to_dict()
    assert restored.checkpoint_state() == service.checkpoint_state()


def test_changed_local_file_rejects_checkpoint_before_any_new_search_or_log(tmp_path):
    service, options = knowledge(tmp_path / "knowledge")
    service.ground("q1", "fact")
    (tmp_path / "knowledge" / "ground.txt").write_text("changed source", encoding="utf-8")
    restored = LocalKnowledge(options, AppendOnlyStore(tmp_path / "restored.jsonl"), mode="research")
    with pytest.raises(ValueError, match="configuration"):
        restored.restore_state(service.checkpoint_state())
    assert restored.ground_backend.calls == [] and not restored.store.path.exists()


def test_explicit_memory_feedback_is_separately_stored_scoped_and_invalidatable(tmp_path):
    mem, frontier = memory(tmp_path / "memory"), ResearchFrontier()
    identifier = lesson(mem, frontier, "source", "DISTILLED_KNOWLEDGE_CONSTRAINT")
    snapshot = tmp_path / "memory-export.json"
    digest = mem.export_snapshot(snapshot, entry_ids=[identifier])
    memory_state = mem.checkpoint_state()
    service, options = knowledge(tmp_path / "knowledge")
    manifest = service.validate_memory_import(snapshot, expected_sha256=digest)
    assert manifest["sha256"] == digest and manifest["record_ids"]
    assert not service.store.path.exists() and service.records == {}
    ids = service.ingest_memory_export(snapshot, expected_sha256=digest)
    assert ids and service.ingest_memory_export(snapshot, expected_sha256=digest) == ids
    assert mem.checkpoint_state() == memory_state
    query_context = ScopeContext("next-run", CTX.task_id, CTX.domain_id)
    pack = service.retrieve(query_context, "knowledge", evaluation_context=EVAL_CONTEXT)
    assert pack.context_items()[0]["findings"] == ["DISTILLED_KNOWLEDGE_CONSTRAINT"]
    assert pack.context_items()[0]["provenance"]["evidence_refs"] == [receipt("source")]
    assert service.retrieve(ScopeContext("next-run", "wrong-task", CTX.domain_id), "knowledge",
                            evaluation_context=EVAL_CONTEXT).context_items() == []
    assert service.retrieve(query_context, "knowledge", evaluation_context="wrong-dataset").context_items() == []
    restored = LocalKnowledge(options, AppendOnlyStore(tmp_path / "restored.jsonl"), mode="research")
    restored.restore_state(service.checkpoint_state())
    assert restored.checkpoint_state() == service.checkpoint_state()
    assert service.invalidate_evidence({receipt("source")}, "source result corrected") == ids
    assert service.retrieve(query_context, "knowledge", evaluation_context=EVAL_CONTEXT).context_items() == []
    assert service.records[ids[0]]["invalidated"] == "source result corrected"
    assert mem.checkpoint_state() == memory_state


def test_known_zero_local_cost_is_explicit_and_not_an_absent_usage_fallback(tmp_path):
    service, _ = knowledge(tmp_path / "knowledge")
    assert asdict(service.ground("q", "fact").cost) == asdict(CostVec())
    assert asdict(service.audit("candidate", "artifact").cost) == asdict(CostVec())
    assert "provider" not in service.manifest_binding


def test_audit_pack_cannot_be_cast_to_candidate_grounding():
    forged = KnowledgePack('{"lane":"audit","items":[{"raw_audit":"secret"}]}')
    with pytest.raises(ValueError, match="only ground"):
        forged.context_items()
