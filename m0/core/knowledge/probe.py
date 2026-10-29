"""K15 injection-gravity time series; fitness is intentionally not an input."""
from __future__ import annotations

import re

from core.x1.store import AppendOnlyStore


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"\w+", text.lower()))


def jaccard(left: str, right: str) -> float:
    a, b = _tokens(left), _tokens(right)
    return len(a & b) / len(a | b) if a or b else 0.0


class InjectionGravityProbe:
    def __init__(self, store: AppendOnlyStore, alarm_above: float = 0.25):
        self.store = store
        self.alarm_above = alarm_above
        self.series: list[dict] = []

    @staticmethod
    def _mean(values: list[float]) -> float:
        return sum(values) / len(values) if values else 0.0

    def record(self, injection_id: str, packet_text: str,
               historical_packets: list[str], after_ideas: list[str]) -> dict:
        if not after_ideas:
            raise ValueError("injection probe requires a post-injection idea window")
        attraction = self._mean([jaccard(idea, packet_text) for idea in after_ideas])
        baseline = self._mean([jaccard(idea, old)
                               for idea in after_ideas for old in historical_packets])
        gravity = attraction - baseline
        point = {"injection_id": injection_id, "window": len(after_ideas),
                 "attraction": attraction, "historical_baseline": baseline,
                 "gravity": gravity, "alarm": gravity > self.alarm_above,
                 "trigger": "diversity_only"}
        self.series.append(point)
        self.store.append("injection_gravity", point)
        return point
