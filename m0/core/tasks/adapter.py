"""Frozen ZOO adapter types. Benchmark names never enter the evolution kernel."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol

from core.x1.store import AppendOnlyStore


@dataclass(frozen=True)
class Workspace:
    root: Path
    evidence: AppendOnlyStore | None = None


@dataclass(frozen=True)
class ArtifactRef:
    uri: str
    sha256: str = ""


@dataclass(frozen=True)
class FidelityLevel:
    name: str
    cost: dict[str, float]
    seeds: int
    purpose: Literal["exploration", "admission", "audit"]


@dataclass(frozen=True)
class EvalContract:
    metric_direction: Literal["maximize", "minimize"]
    eval_cmd: str
    fidelity_levels: tuple[FidelityLevel, ...]
    required_outputs: tuple[str, ...]
    protected_paths: tuple[str, ...]
    visibility: Literal["dev", "admission", "audit"] = "dev"


@dataclass(frozen=True)
class ProvenanceDoc:
    source_uri: str
    revision: str
    protocol_uri: str
    task_list_sha256: str
    license: str
    notes: dict[str, str] = field(default_factory=dict)


class TaskAdapter(Protocol):
    name: str

    def setup(self, workspace: Workspace) -> None: ...
    def eval_contract(self) -> EvalContract: ...
    def initial_artifact(self) -> ArtifactRef: ...
    def provenance(self) -> ProvenanceDoc: ...
