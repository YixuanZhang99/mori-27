"""Performance/cost Pareto archive. M4 stores views; M9 alone adjudicates.

Every physical cost unit remains a separate minimization axis. No score/cost
scalarization, exchange-rate conversion, or admission decision occurs here.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass

from core.x1.store import AppendOnlyStore


@dataclass(frozen=True)
class PerformanceCostPoint:
    candidate_id: str
    performance: float
    costs: dict[str, float]
    receipt_id: str
    evaluator_version: str

    def validate(self) -> None:
        if not self.candidate_id or not self.receipt_id or not self.evaluator_version:
            raise ValueError("candidate, admission receipt and evaluator version are required")
        if not math.isfinite(self.performance):
            raise ValueError("performance must be finite")
        if not self.costs:
            raise ValueError("at least one physical cost axis is required")
        for unit, amount in self.costs.items():
            if not unit or isinstance(amount, bool) or not isinstance(amount, (int, float)):
                raise ValueError("cost units and numeric amounts are required")
            if not math.isfinite(amount) or amount < 0:
                raise ValueError("costs must be finite and non-negative")

    @staticmethod
    def dominates(left: "PerformanceCostPoint", right: "PerformanceCostPoint") -> bool:
        if set(left.costs) != set(right.costs):
            raise ValueError("Pareto comparison requires identical cost units")
        no_worse = (left.performance >= right.performance and
                    all(left.costs[u] <= right.costs[u] for u in left.costs))
        strictly_better = (left.performance > right.performance or
                           any(left.costs[u] < right.costs[u] for u in left.costs))
        return no_worse and strictly_better


class ParetoArchive:
    """Append-only offers plus a deterministic, recomputable non-dominated view."""

    def __init__(self, store: AppendOnlyStore | None = None):
        self.store = store
        self.entries: dict[str, PerformanceCostPoint] = {}
        self.cost_units: frozenset[str] | None = None

    def offer(self, point: PerformanceCostPoint) -> list[str]:
        point.validate()
        if point.candidate_id in self.entries:
            raise ValueError("duplicate candidate offer; append a new candidate identity")
        units = frozenset(point.costs)
        if self.cost_units is not None and units != self.cost_units:
            raise ValueError("all archive points must use identical physical cost units")
        self.entries[point.candidate_id] = point
        self.cost_units = units
        frontier = [p.candidate_id for p in self.frontier()]
        if self.store is not None:
            self.store.append("pareto_offer", {
                **asdict(point), "frontier_after": frontier})
        return frontier

    def frontier(self) -> list[PerformanceCostPoint]:
        points = list(self.entries.values())
        members = [candidate for candidate in points
                   if not any(other.candidate_id != candidate.candidate_id and
                              PerformanceCostPoint.dominates(other, candidate)
                              for other in points)]
        return sorted(members, key=lambda p: (
            -p.performance, tuple(sorted(p.costs.items())), p.candidate_id))

    def dominated_by(self, candidate_id: str) -> list[str]:
        point = self.entries[candidate_id]
        return sorted(other.candidate_id for other in self.entries.values()
                      if other.candidate_id != candidate_id and
                      PerformanceCostPoint.dominates(other, point))
