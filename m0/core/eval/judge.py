"""LLM-judge governance utilities (B4/B5/B8): probes, kappa, isotonic calibration.

LLMs may produce raw judgments; registration probes, calibration and final
thresholds are deterministic code. No judge is required for M0 deterministic loads.
"""
from __future__ import annotations


def position_swap_probe(judge, pairs: list[tuple[str, str]],
                        max_flip_rate: float = 0.2) -> dict:
    """judge(a,b) -> 'a'|'b'. Swapping order should not change the winner."""
    if not pairs:
        raise ValueError("position-swap probe requires pairs")
    flips = 0
    for a, b in pairs:
        forward = judge(a, b)
        backward = judge(b, a)
        expected = "b" if forward == "a" else "a"
        flips += backward != expected
    rate = flips / len(pairs)
    return {"flip_rate": rate, "accepted": rate <= max_flip_rate,
            "n_pairs": len(pairs)}


def cohens_kappa(predicted: list[int], gold: list[int]) -> float:
    if len(predicted) != len(gold) or not gold:
        raise ValueError("kappa inputs must be non-empty and aligned")
    n = len(gold)
    observed = sum(p == g for p, g in zip(predicted, gold)) / n
    p_pred = sum(predicted) / n
    p_gold = sum(gold) / n
    expected = p_pred * p_gold + (1 - p_pred) * (1 - p_gold)
    return (observed - expected) / (1 - expected) if expected != 1 else 1.0


class IsotonicCalibrator:
    """Pool-adjacent-violators fit for monotone raw-score -> oracle calibration."""

    def __init__(self):
        self.thresholds: list[float] = []
        self.values: list[float] = []

    def fit(self, raw_scores: list[float], oracle: list[float]):
        if len(raw_scores) != len(oracle) or not raw_scores:
            raise ValueError("calibration data must be non-empty and aligned")
        points = sorted(zip(raw_scores, oracle), key=lambda p: p[0])
        blocks = []  # each: [sum_x, sum_y, count, rightmost_x]
        for x, y in points:
            blocks.append([x, y, 1, x])
            while len(blocks) >= 2 and blocks[-2][1] / blocks[-2][2] > blocks[-1][1] / blocks[-1][2]:
                b = blocks.pop()
                a = blocks.pop()
                blocks.append([a[0] + b[0], a[1] + b[1], a[2] + b[2], b[3]])
        self.thresholds = [b[3] for b in blocks]
        self.values = [b[1] / b[2] for b in blocks]
        return self

    def predict(self, score: float) -> float:
        if not self.values:
            raise RuntimeError("calibrator is not fitted")
        # Piecewise-constant monotone calibration; deterministic and replayable.
        for right_edge, level in zip(self.thresholds, self.values):
            if score <= right_edge:
                return level
        return self.values[-1]
