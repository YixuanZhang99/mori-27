"""M4 performance/cost frontiers remain separate from M9 adjudication."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.eval.gate import AdmissionGate
from core.eval.types import EvalResult, ItemResult
from core.frontier.pareto import ParetoArchive, PerformanceCostPoint
from core.x1.store import AppendOnlyStore


def point(cid, performance, token, usd):
    return PerformanceCostPoint(cid, performance, {"token": token, "usd": usd},
                                receipt_id=f"receipt-{cid}", evaluator_version="anchor-v1")


def test_multi_currency_non_dominated_view_and_evidence_retention(tmp_path):
    store = AppendOnlyStore(tmp_path / "frontier.jsonl")
    archive = ParetoArchive(store)
    archive.offer(point("balanced", 0.8, 100, 1.0))
    archive.offer(point("cheap", 0.7, 80, 0.8))
    archive.offer(point("dominated", 0.6, 120, 1.2))
    archive.offer(point("fast", 0.9, 150, 0.5))
    assert {p.candidate_id for p in archive.frontier()} == {"balanced", "cheap", "fast"}
    assert archive.dominated_by("dominated") == ["balanced", "cheap"]
    assert set(archive.entries) == {"balanced", "cheap", "dominated", "fast"}
    events = list(store.read("pareto_offer"))
    assert len(events) == 4
    assert events[-1]["payload"]["frontier_after"] == ["fast", "balanced", "cheap"]


def test_cost_units_never_silently_convert_and_invalid_offer_is_atomic():
    archive = ParetoArchive()
    archive.offer(point("a", 0.5, 10, 1))
    with pytest.raises(ValueError, match="identical physical cost units"):
        archive.offer(PerformanceCostPoint("b", 0.9, {"token": 1}, "r-b", "v1"))
    assert set(archive.entries) == {"a"}
    with pytest.raises(ValueError, match="non-negative"):
        archive.offer(point("c", 0.9, -1, 1))
    assert set(archive.entries) == {"a"}


def test_equal_tradeoff_points_and_duplicate_ids_are_not_overwritten():
    archive = ParetoArchive()
    archive.offer(point("a", 0.8, 100, 1))
    archive.offer(point("b", 0.8, 100, 1))
    assert {p.candidate_id for p in archive.frontier()} == {"a", "b"}
    with pytest.raises(ValueError, match="duplicate"):
        archive.offer(point("a", 1.0, 1, 0.1))
    assert archive.entries["a"].performance == 0.8


def test_m9_verdict_is_invariant_to_cost_side_channels(tmp_path):
    gate = AdmissionGate(AppendOnlyStore(tmp_path / "gate.jsonl"))
    incumbent = EvalResult("old", "sha-old", [ItemResult("i1", 0), ItemResult("i2", 1)],
                           combined_score=0.5)
    cheap = EvalResult("cheap", "sha-cheap", [ItemResult("i1", 1), ItemResult("i2", 1)],
                       combined_score=0.1, private={"costs": {"token": 1, "usd": 0.01}})
    expensive = EvalResult("expensive", "sha-expensive",
                           [ItemResult("i1", 1), ItemResult("i2", 1)],
                           combined_score=999.0,
                           private={"costs": {"token": 10**9, "usd": 10**6}})
    cheap_receipt = gate.judge(cheap, incumbent)
    expensive_receipt = gate.judge(expensive, incumbent)
    assert cheap_receipt.verdict.kind == expensive_receipt.verdict.kind == "ACCEPT"
    assert cheap_receipt.verdict.rationale_ref == expensive_receipt.verdict.rationale_ref
    evidence = [r["payload"] for r in gate.store.read("gate_evidence")]
    assert all(set(e["signals_snapshot"]) == {"F", "B", "N", "noise_floor"}
               for e in evidence)
