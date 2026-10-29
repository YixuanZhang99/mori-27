"""M6 lane isolation, citation, advisory quality and probe tests."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.knowledge.probe import InjectionGravityProbe
from core.knowledge.service import KnowledgeError, KnowledgeService
from core.knowledge.types import (FetchedDocument, GapSignalCard, GroundedQuery)
from core.x1.store import AppendOnlyStore


class Backend:
    def __init__(self, docs):
        self.docs = docs
        self.calls = []

    def search(self, text, lane):
        self.calls.append((text, lane))
        return self.docs


def service(tmp_path, ground_docs=None, audit_docs=None):
    ground = Backend(ground_docs or [])
    audit = Backend(audit_docs or [])
    svc = KnowledgeService(ground, audit, AppendOnlyStore(tmp_path / "x1.jsonl"),
                           {"arxiv"}, {"arxiv", "web"})
    return svc, ground, audit


def test_ground_query_records_only_opened_sources(tmp_path):
    docs = [FetchedDocument("u1", "opened fact", "arxiv"),
            FetchedDocument("u2", "metadata only", "arxiv", opened=False)]
    svc, ground, _ = service(tmp_path, docs)
    query = GroundedQuery("q1", "lookup", "fact", depth_tier="shallow_2k")
    digest = svc.query(query)
    assert digest.sources == ["fetch:1"] and digest.lane == "ground"
    assert digest.provenance["opened"][0]["url"] == "u1"
    assert ground.calls == [("fact", "ground")]
    assert len(list(svc.store.read("fetch_ledger"))) == 1


def test_static_isolation_and_benchmark_mode_are_hard_gates(tmp_path):
    backend = Backend([])
    store = AppendOnlyStore(tmp_path / "bad.jsonl")
    with pytest.raises(KnowledgeError, match="independent"):
        KnowledgeService(backend, backend, store, {"arxiv"}, {"arxiv"})
    with pytest.raises(KnowledgeError, match="namespaces"):
        KnowledgeService(Backend([]), Backend([]), store, {"arxiv"}, {"arxiv"},
                         "shared", "shared")
    with pytest.raises(KnowledgeError, match="superset"):
        KnowledgeService(Backend([]), Backend([]), store, {"arxiv", "web"}, {"arxiv"})
    svc, ground, audit = service(tmp_path / "service")
    with pytest.raises(KnowledgeError, match="benchmark"):
        svc.query(GroundedQuery("q", "survey", "x", eval_mode="benchmark"))
    with pytest.raises(KnowledgeError, match="benchmark"):
        svc.audit("i", "idea", eval_mode="benchmark")
    assert ground.calls == [] and audit.calls == []
    assert len(list(svc.store.read("knowledge_eval_mode_violation"))) == 2


def test_repair_requires_structured_failure_signal(tmp_path):
    svc, _, _ = service(tmp_path)
    with pytest.raises(KnowledgeError, match="failure_signal"):
        svc.query(GroundedQuery("q", "repair", "fix", depth_tier="mid"))
    query = GroundedQuery("q", "repair", "fix", depth_tier="mid",
                          context={"failure_signal": {"item_id": "i1", "error": "assertion"}})
    assert svc.query(query).query.intent == "repair"


def test_audit_is_advisory_and_unusable_until_gold_review(tmp_path):
    svc, _, audit_backend = service(tmp_path, audit_docs=[
        FetchedDocument("paper-1", "a unique idea verbatim", "arxiv")])
    verdict = svc.audit("idea-1", "a unique idea verbatim", "merge_review")
    assert verdict.verdict == "prior_art_exists"
    assert audit_backend.calls == [("a unique idea verbatim", "audit")]
    assert svc.merge_reference(verdict.audit_id) is None
    quality = svc.record_review(verdict.audit_id, "true_overlap", "gold-v1", 10)
    assert quality.n_reviewed == 1 and quality.false_kill_rate == 0
    assert svc.merge_reference(verdict.audit_id).verdict == "prior_art_exists"


def test_cross_lane_hash_overlap_soft_invalidates_verdict(tmp_path):
    shared = "same fetched content"
    svc, _, _ = service(tmp_path,
                        ground_docs=[FetchedDocument("g", shared, "arxiv")],
                        audit_docs=[FetchedDocument("a", shared, "web")])
    svc.query(GroundedQuery("q", "survey", "anything"))
    verdict = svc.audit("idea", "different idea")
    assert verdict.audit_id in svc.invalidated_audits
    quality = svc.record_review(verdict.audit_id, "true_novel", "gold", 10)
    assert quality.n_reviewed == 0  # isolation violations do not contaminate calibration
    assert svc.merge_reference(verdict.audit_id) is None
    assert list(svc.store.read("knowledge_verdict_invalidation"))


def test_gap_card_schema_and_injection_gravity(tmp_path):
    evidence = [{"trace_id": "t1", "paper_id": "p1", "path_excerpt": "a->b"},
                {"trace_id": "t2", "paper_id": "p2", "path_excerpt": "c->d"}]
    card = GapSignalCard("g", "cross_link", "unresolved constraint", evidence,
                         {"structural_novelty": "new causal bridge"})
    assert card.gap_id == "g"
    with pytest.raises(ValueError, match="independent"):
        GapSignalCard("bad", "convergent", "x", evidence[:1], {})
    store = AppendOnlyStore(tmp_path / "probe.jsonl")
    probe = InjectionGravityProbe(store, alarm_above=0.1)
    point = probe.record("d1", "alpha beta", ["gamma"], ["alpha beta", "alpha"])
    assert point["alarm"] and point["trigger"] == "diversity_only"
    assert "fitness" not in point
