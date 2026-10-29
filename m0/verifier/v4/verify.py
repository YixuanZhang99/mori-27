#!/usr/bin/env python3
"""Verifier v4: v3 plus scoped memory and two-lane knowledge acceptance."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import traceback
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.knowledge.probe import InjectionGravityProbe
from core.knowledge.service import KnowledgeError, KnowledgeService
from core.knowledge.types import FetchedDocument, GapSignalCard, GroundedQuery
from core.memory.store import MemoryError, ScopedMemory
from core.memory.types import (MemoryEntry, MemoryQuery, Payload, Provenance,
                               ScopeContext, ScopeUpgradeEvidence, TimeMeta,
                               UtilitySignals)
from core.x1.store import AppendOnlyStore

CTX = ScopeContext("run-1", "task-1", "domain-1")


def memory_entry(entry_id, body, evidence=("receipt-1",), helpful=0, harmful=0):
    return MemoryEntry(entry_id, Payload("text", body),
        Provenance("run-1", evidence_refs=list(evidence), trust_tier="verified"),
        TimeMeta(created_at=1, ttl=5), CTX,
        utility=UtilitySignals(helpful_count=helpful, harmful_count=harmful))


def check_memory(root):
    store = AppendOnlyStore(root / "memory.jsonl")
    memory = ScopedMemory(store, utility_weight=1.0)
    memory.write(memory_entry("helpful", "alpha beta", helpful=4), at=1)
    memory.write(memory_entry("harmful", "alpha", harmful=4), at=1)
    assert memory.retrieve(MemoryQuery("alpha", CTX), at=1) == []
    memory.transition("helpful", "active", "verifier")
    memory.transition("harmful", "active", "verifier")
    ranked = [e.id for e in memory.retrieve(MemoryQuery("alpha", CTX), at=2)]
    other = MemoryQuery("alpha", ScopeContext("run-2", "task-2", "domain-1"))
    isolated = memory.retrieve(other, at=2) == []
    memory.promote_scope("helpful", "domain", ScopeUpgradeEvidence(True, True, "snap"))
    domain_visible = [e.id for e in memory.retrieve(other, at=3)] == ["helpful"]
    try:
        memory.promote_scope("helpful", "global", ScopeUpgradeEvidence(True, True, "snap"))
        global_refused = False
    except MemoryError:
        global_refused = True
    memory.promote_scope("helpful", "global",
                         ScopeUpgradeEvidence(True, True, "snap", human_confirmation=True))
    ttl = memory.expire(10)
    invalidated = memory.invalidate_evidence({"receipt-1"}, "evaluator-v2")
    hard_records = len(memory.entries)
    passed = (ranked == ["helpful", "harmful"] and isolated and domain_visible
              and global_refused and set(invalidated) == {"helpful", "harmful"}
              and hard_records == 2 and set(ttl) == {"helpful", "harmful"}
              and bool(list(store.read("memory_invalidation"))))
    return passed, {"ranked": ranked, "task_isolated": isolated,
                    "domain_visible": domain_visible, "global_refused_without_evidence": global_refused,
                    "invalidated": invalidated, "ttl_demoted": ttl,
                    "records_preserved": hard_records}


class Backend:
    def __init__(self, docs):
        self.docs = docs
        self.calls = []

    def search(self, text, lane):
        self.calls.append((text, lane))
        return self.docs


def knowledge_service(path, ground_docs=(), audit_docs=()):
    ground, audit = Backend(list(ground_docs)), Backend(list(audit_docs))
    svc = KnowledgeService(ground, audit, AppendOnlyStore(path / "knowledge.jsonl"),
                           {"arxiv"}, {"arxiv", "web"})
    return svc, ground, audit


def check_ground_and_eval_mode(root):
    svc, ground, audit = knowledge_service(root / "ground", [
        FetchedDocument("u1", "opened fact", "arxiv"),
        FetchedDocument("u2", "unopened", "arxiv", opened=False)])
    digest = svc.query(GroundedQuery("q", "lookup", "fact", depth_tier="shallow_2k"))
    benchmark_refusals = 0
    for fn in (lambda: svc.query(GroundedQuery("qb", "survey", "x", eval_mode="benchmark")),
               lambda: svc.audit("i", "idea", eval_mode="benchmark")):
        try:
            fn()
        except KnowledgeError:
            benchmark_refusals += 1
    calls_before = (len(ground.calls), len(audit.calls))
    passed = (digest.sources == ["fetch:1"] and benchmark_refusals == 2
              and calls_before == (1, 0)
              and len(list(svc.store.read("knowledge_eval_mode_violation"))) == 2)
    return passed, {"opened_sources": digest.sources,
                    "benchmark_refusals": benchmark_refusals,
                    "backend_calls": calls_before}


def check_audit_and_isolation(root):
    svc, _, audit = knowledge_service(root / "audit", audit_docs=[
        FetchedDocument("paper", "unique idea verbatim", "arxiv")])
    verdict = svc.audit("i", "unique idea verbatim", "merge_review")
    before_review = svc.merge_reference(verdict.audit_id)
    quality = svc.record_review(verdict.audit_id, "true_overlap", "gold", 10)
    after_review = svc.merge_reference(verdict.audit_id)
    shared = "shared fetched bytes"
    contaminated, _, _ = knowledge_service(root / "contaminated",
        [FetchedDocument("g", shared, "arxiv")], [FetchedDocument("a", shared, "web")])
    contaminated.query(GroundedQuery("q", "survey", "query"))
    bad = contaminated.audit("idea", "different")
    contaminated.record_review(bad.audit_id, "true_novel", "gold", 10)
    passed = (verdict.verdict == "prior_art_exists" and before_review is None
              and quality.n_reviewed == 1 and after_review is not None
              and audit.calls == [("unique idea verbatim", "audit")]
              and contaminated.merge_reference(bad.audit_id) is None
              and bool(list(contaminated.store.read("knowledge_verdict_invalidation"))))
    return passed, {"tier": verdict.verdict, "usable_before_review": before_review is not None,
                    "reviewed": quality.n_reviewed,
                    "cross_lane_invalidated": bad.audit_id in contaminated.invalidated_audits}


def check_cards_and_probe(root):
    evidence = [{"trace_id": "t1", "paper_id": "p1", "path_excerpt": "a"},
                {"trace_id": "t2", "paper_id": "p2", "path_excerpt": "b"}]
    card = GapSignalCard("gap", "cross_link", "constraint", evidence,
                         {"structural_novelty": "bridge"})
    probe = InjectionGravityProbe(AppendOnlyStore(root / "probe.jsonl"), alarm_above=0.1)
    point = probe.record("d", "alpha beta", ["gamma"], ["alpha beta"])
    passed = card.gap_id == "gap" and point["alarm"] and point["trigger"] == "diversity_only"
    return passed, {"gravity": point["gravity"], "alarm": point["alarm"]}


def main() -> int:
    checks, values = {}, {}
    v3 = subprocess.run([sys.executable, "verifier/v3/verify.py"], cwd=ROOT,
                        text=True, capture_output=True)
    checks["v3_complete"] = v3.returncode == 0
    values["v3_exit"] = v3.returncode
    if v3.returncode:
        values["v3_stderr"] = v3.stderr[-2000:]
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        for name, fn in (("scoped_memory_lifecycle", check_memory),
                         ("ground_provenance_and_benchmark_gate", check_ground_and_eval_mode),
                         ("advisory_quality_and_lane_isolation", check_audit_and_isolation),
                         ("gap_cards_and_diversity_probe", check_cards_and_probe)):
            try:
                checks[name], values[name] = fn(root)
            except Exception as exc:
                checks[name] = False
                values[name] = {"error": str(exc), "traceback": traceback.format_exc()}
    passed = all(checks.values())
    record = {"timestamp": datetime.now(timezone.utc).isoformat(),
              "command": "python3 verifier/v4/verify.py", "version": "v4",
              "exit_code": 0 if passed else 1, "checks": checks, "values": values}
    with (ROOT / "verifier/runs/v4.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    print(json.dumps(record, ensure_ascii=False, indent=2, default=str))
    return record["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
