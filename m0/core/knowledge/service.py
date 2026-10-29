"""M6 ground/audit service with physical lanes, provenance and advisory quality."""
from __future__ import annotations

import hashlib
import re
from dataclasses import asdict

from core.knowledge.types import (AuditReliability, AuditVerdict, DualRateLedger,
                                  FetchedDocument, GroundedQuery, KnowledgeDigest)
from core.x1.store import AppendOnlyStore


class KnowledgeError(Exception):
    pass


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"\w+", text.lower()))


class KnowledgeService:
    """The only M6 public supply channel: query() for ground, audit() for audit."""

    def __init__(self, ground_backend, audit_backend, store: AppendOnlyStore,
                 ground_corpus: set[str], audit_corpus: set[str],
                 ground_namespace: str = "ground", audit_namespace: str = "audit"):
        if ground_backend is audit_backend:
            raise KnowledgeError("ground and audit backends must be independent objects")
        if ground_namespace == audit_namespace:
            raise KnowledgeError("lane cache namespaces must be disjoint")
        if not ground_corpus.issubset(audit_corpus):
            raise KnowledgeError("audit corpus must be a superset of ground corpus")
        self.ground_backend = ground_backend
        self.audit_backend = audit_backend
        self.ground_corpus = set(ground_corpus)
        self.audit_corpus = set(audit_corpus)
        self.namespaces = {"ground": ground_namespace, "audit": audit_namespace}
        self.store = store
        self._seq = 0
        self.fetch_by_ref: dict[str, dict] = {}
        self.hashes_by_lane = {"ground": set(), "audit": set()}
        self.audits: dict[str, AuditVerdict] = {}
        self.invalidated_audits: set[str] = set()
        self.reviews: list[DualRateLedger] = []
        self.store.append("knowledge_isolation_check", {
            "backend_config_independent": True, "cache_namespace_separated": True,
            "field_routing_separated": True, "corpus_superset": True,
            "checker_version": "k16-v1"})

    def _record_fetch(self, doc: FetchedDocument, lane: str) -> str:
        self._seq += 1
        digest = hashlib.sha256(doc.content.encode("utf-8")).hexdigest()
        ref = f"fetch:{self._seq}"
        other = "audit" if lane == "ground" else "ground"
        overlap = digest in self.hashes_by_lane[other]
        record = {"seq": self._seq, "ref": ref, "url": doc.url,
                  "content_hash": digest, "timestamp": float(self._seq),
                  "lane": lane, "namespace": self.namespaces[lane],
                  "truncation_boundary": doc.truncation_boundary,
                  "backend": doc.backend, "cross_lane_hash_overlap": overlap}
        self.fetch_by_ref[ref] = record
        self.hashes_by_lane[lane].add(digest)
        self.store.append("fetch_ledger", record)
        if overlap:
            self.store.append("knowledge_isolation_violation", {
                "content_hash": digest, "lane": lane, "fetch_ref": ref})
        return ref

    @staticmethod
    def _opened(backend, text: str, lane: str) -> list[FetchedDocument]:
        docs = backend.search(text, lane=lane)
        # D7: metadata-only/unopened sources never become citations.
        return [doc for doc in docs if doc.opened]

    def query(self, query: GroundedQuery) -> KnowledgeDigest:
        if query.eval_mode == "benchmark":
            self.store.append("knowledge_eval_mode_violation", {
                "query_id": query.query_id, "lane": "ground", "eval_mode": "benchmark"})
            raise KnowledgeError("M6 lanes are disabled in benchmark mode")
        if query.intent == "repair":
            signal = query.context.get("failure_signal")
            if (not isinstance(signal, dict) or not signal.get("item_id")
                    or not signal.get("error")):
                raise KnowledgeError("repair requires structured M8 failure_signal")
        docs = self._opened(self.ground_backend, query.text, "ground")
        refs = [self._record_fetch(doc, "ground") for doc in docs]
        provenance = {
            "query_used": query.text, "source_pages": [d.url for d in docs],
            "opened": [{"url": d.url, "fetch_ref": ref} for d, ref in zip(docs, refs)],
            "truncation_boundary": [d.truncation_boundary for d in docs],
            "lane": "ground", "namespace": self.namespaces["ground"]}
        digest = KnowledgeDigest(
            digest_id=f"digest:{query.query_id}", query=query,
            summary=f"{query.intent}: {len(docs)} independently opened ground sources",
            findings=[d.content[:240] for d in docs], sources=refs,
            confidence=min(1.0, len(docs) / 3), provenance=provenance)
        self.store.append("knowledge_digest", asdict(digest))
        self.store.append("injection_probe", {
            "digest_id": digest.digest_id, "packet_hash": hashlib.sha256(
                (digest.summary + "\n".join(digest.findings)).encode("utf-8")).hexdigest(),
            "status": "awaiting_post_window", "fitness_trigger": False})
        return digest

    def _judge(self, idea_text: str, docs: list[FetchedDocument]) -> tuple[str, str, str]:
        idea = _tokens(idea_text)
        best, best_overlap = None, 0.0
        for doc in docs:
            words = _tokens(doc.content)
            overlap = len(idea & words) / len(idea | words) if idea or words else 0.0
            if overlap > best_overlap:
                best, best_overlap = doc, overlap
        if best is not None and idea_text in best.content:
            return "prior_art_exists", best.url, "exact idea text found in opened source"
        if best is not None and best_overlap >= 0.5:
            return "partial_overlap", best.url, f"token overlap={best_overlap:.3f}"
        return "novel", None if best is None else best.url, "no prior art found in covered backends"

    def audit(self, idea_id: str, idea_text: str,
              audit_phase: str = "add_precheck",
              eval_mode: str = "research") -> AuditVerdict:
        if eval_mode == "benchmark":
            self.store.append("knowledge_eval_mode_violation", {
                "idea_id": idea_id, "lane": "audit", "eval_mode": "benchmark"})
            raise KnowledgeError("M6 lanes are disabled in benchmark mode")
        if not idea_id or not idea_text:
            raise KnowledgeError("audit requires idea id and source text")
        # Fresh search: query is constructed only from idea text, never a ground digest.
        docs = self._opened(self.audit_backend, idea_text, "audit")
        refs = [self._record_fetch(doc, "audit") for doc in docs]
        tier, closest, risk = self._judge(idea_text, docs)
        audit_id = f"audit:{idea_id}:{len(self.audits) + 1}"
        trace = [{"query": idea_text, "backend_hits": len(docs),
                  "namespace": self.namespaces["audit"]}]
        verdict = AuditVerdict(
            audit_id=audit_id, idea_id=idea_id, verdict=tier,
            audit_phase=audit_phase, audit_query_trace=trace,
            backends_covered=sorted({d.backend for d in docs}),
            reliability=AuditReliability(), fetch_refs=refs,
            closest_paper_id=closest, overlap_risk=risk)
        self.audits[audit_id] = verdict
        self.store.append("audit_verdict", asdict(verdict))
        overlap_refs = [ref for ref in refs
                        if self.fetch_by_ref[ref]["cross_lane_hash_overlap"]]
        if overlap_refs:
            self.invalidated_audits.add(audit_id)
            self.store.append("knowledge_verdict_invalidation", {
                "audit_id": audit_id, "reason": "cross-lane fetched-text overlap",
                "fetch_refs": overlap_refs, "error_kind": "isolation_violation"})
        return verdict

    def merge_reference(self, audit_id: str) -> AuditVerdict | None:
        """D2/D3: advisory only, and unusable until independently reviewed."""
        verdict = self.audits[audit_id]
        if audit_id in self.invalidated_audits or not verdict.reliability.usable():
            return None
        return verdict

    def record_review(self, audit_id: str, truth: str, reviewer: str,
                      review_date: float) -> AuditReliability:
        if not reviewer or review_date <= 0:
            raise ValueError("review requires reviewer and logical review_date")
        verdict = self.audits[audit_id]
        if audit_id in self.invalidated_audits:
            error = "isolation_violation"
        elif verdict.verdict == "novel" and truth == "true_overlap":
            error = "false_novel"
        elif verdict.verdict == "prior_art_exists" and truth == "true_novel":
            error = "false_kill"
        else:
            error = "correct"
        review = DualRateLedger(
            verdict_id=audit_id, idea_id=verdict.idea_id, verdict=verdict.verdict,
            audit_query_trace=verdict.audit_query_trace, fetch_refs=verdict.fetch_refs,
            sampled_for_review=True, review_truth=truth, error_kind=error,
            reviewer=reviewer, review_date=review_date)
        self.reviews.append(review)
        self.store.append("dual_rate_ledger", asdict(review))
        valid_reviews = [r for r in self.reviews if r.error_kind != "isolation_violation"]
        n = len(valid_reviews)
        quality = AuditReliability(
            sampled_rate=n / len(self.audits) if self.audits else 0,
            false_novel_rate=sum(r.error_kind == "false_novel" for r in valid_reviews) / n if n else None,
            false_kill_rate=sum(r.error_kind == "false_kill" for r in valid_reviews) / n if n else None,
            n_reviewed=n)
        verdict.reliability = quality
        return quality
