"""X2 interaction and decision types. Only auto and review are enabled in phase one."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

InteractionMode = Literal["auto", "review"]


@dataclass(frozen=True)
class ControlDecision:
    request_id: str
    decision_id: str | None
    action: str
    payload_sha256: str
    mode: InteractionMode
    verdict: Literal["approved", "rejected", "pending", "denied"]
    allowed: bool
    reason: str = ""
