"""Canonical M9 admission output consumed by batch orchestration."""
from __future__ import annotations

from dataclasses import dataclass, field

from core.policy.types import StateMutation


@dataclass(frozen=True)
class AdmissionDecision:
    admit: bool
    mutations: list[StateMutation] = field(default_factory=list)
    reason: str = ""
