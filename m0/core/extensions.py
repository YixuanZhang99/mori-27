"""Protocol extensions (ADR-0 v2): opt-in behavior behind hooks, never core edits.

M0 ships the hook points only. NoveltyGateExtension and H2MonitorExtension are the
first reference plugins used to test RUBRIC A3 (extensions add no core changes).
"""
from __future__ import annotations

from collections import deque
from difflib import SequenceMatcher
from typing import Protocol


class AdmissionExtension(Protocol):
    def admission_veto(self, proposal, result, pool: list[dict]) -> str | None: ...


class ParentMonitorExtension(Protocol):
    def after_parent_selection(self, parent: dict, generation: int) -> dict | None: ...


class ExtensionRegistry:
    def __init__(self):
        self.admission: list[AdmissionExtension] = []
        self.parent_monitors: list[ParentMonitorExtension] = []

    def register(self, extension) -> None:
        if hasattr(extension, "admission_veto"):
            self.admission.append(extension)
        if hasattr(extension, "after_parent_selection"):
            self.parent_monitors.append(extension)

    def veto(self, proposal, result, pool: list[dict]) -> str | None:
        for ext in self.admission:
            reason = ext.admission_veto(proposal, result, pool)
            if reason:
                return reason
        return None

    def parent_selected(self, parent: dict, generation: int) -> list[dict]:
        alarms = []
        for ext in self.parent_monitors:
            alarm = ext.after_parent_selection(parent, generation)
            if alarm:
                alarms.append(alarm)
        return alarms


class NoveltyGateExtension:
    """M2-O8 reference implementation. Exact sequence similarity, not embeddings."""

    def __init__(self, threshold: float = 0.95):
        if not 0 < threshold <= 1:
            raise ValueError("threshold must be in (0,1]")
        self.threshold = threshold

    def admission_veto(self, proposal, result, pool: list[dict]) -> str | None:
        for cand in pool:
            similarity = SequenceMatcher(None, proposal.patch_text,
                                         cand["prompt"]).ratio()
            if similarity >= self.threshold:
                return (f"novelty_gate: similarity={similarity:.3f} "
                        f">= {self.threshold} vs {cand['candidate_id']}")
        return None


class H2MonitorExtension:
    """Greedy-parent structural alarm: distinct parents over a sliding window."""

    def __init__(self, window: int = 5, min_effective_parents: int = 2):
        self.window = window
        self.min_effective_parents = min_effective_parents
        self.parents = deque(maxlen=window)

    def after_parent_selection(self, parent: dict, generation: int) -> dict | None:
        self.parents.append(parent["candidate_id"])
        if len(self.parents) < self.window:
            return None
        effective = len(set(self.parents))
        if effective < self.min_effective_parents:
            return {"kind": "h2_collapse_alarm", "generation": generation,
                    "effective_parent_count": effective,
                    "action": "install diversity carrier / review greedy default"}
        return None

    def checkpoint_state(self) -> dict:
        return {"parents": list(self.parents)}

    def restore_state(self, state: dict) -> None:
        parents = state.get("parents")
        if not isinstance(parents, list) or len(parents) > self.window:
            raise ValueError("invalid H2 checkpoint state")
        self.parents = deque(parents, maxlen=self.window)
