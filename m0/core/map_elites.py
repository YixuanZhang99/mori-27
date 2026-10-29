"""M4/M1 MAP-Elites feature-grid archive extension.

The grid owns parent-pool diversity only. Admission remains the per-item M9 gate;
feature metadata never becomes an admission score or cost input.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Iterable


def _finite_number(value) -> bool:
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(value))


@dataclass(frozen=True)
class FeatureDimension:
    """One inclusive numeric range partitioned into equal-width cells."""

    name: str
    lower: float
    upper: float
    bins: int

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("feature dimension name must be non-empty")
        if not _finite_number(self.lower) or not _finite_number(self.upper) \
                or self.lower >= self.upper:
            raise ValueError("feature dimension bounds must be finite and increasing")
        if isinstance(self.bins, bool) or not isinstance(self.bins, int) or self.bins < 1:
            raise ValueError("feature dimension bins must be a positive integer")

    @classmethod
    def from_dict(cls, payload: dict) -> "FeatureDimension":
        if not isinstance(payload, dict) \
                or set(payload) != {"name", "lower", "upper", "bins"}:
            raise ValueError("feature dimension requires name/lower/upper/bins")
        return cls(payload["name"], payload["lower"], payload["upper"], payload["bins"])

    def index(self, value) -> int:
        if not _finite_number(value):
            raise ValueError(f"feature {self.name} must be a finite number")
        # Boundary values are clipped explicitly; NaN/inf are never silently clipped.
        fraction = (min(self.upper, max(self.lower, float(value))) - self.lower) \
            / (self.upper - self.lower)
        return min(self.bins - 1, int(fraction * self.bins))


@dataclass
class MapElitesEntry:
    candidate_id: str
    score: float
    cell: tuple[int, ...]
    registered_generation: int
    archived: bool = True
    parent_eligible: bool = True
    deliver_eligible: bool = True
    soft_deleted: bool = False
    eviction_reason: str | None = None


class MapElitesArchive:
    """One deterministic elite per feature cell with soft, inspectable history."""

    kind = "map_elites"

    def __init__(self, dimensions: Iterable[FeatureDimension]):
        self.dimensions = tuple(dimensions)
        if not self.dimensions \
                or any(not isinstance(dimension, FeatureDimension)
                       for dimension in self.dimensions):
            raise ValueError("MAP-Elites requires FeatureDimension entries")
        names = [dimension.name for dimension in self.dimensions]
        if len(set(names)) != len(names):
            raise ValueError("MAP-Elites feature names must be unique")
        self.entries: dict[str, MapElitesEntry] = {}
        self.cells: dict[tuple[int, ...], str] = {}
        self.replacement_count = 0

    @classmethod
    def from_config(cls, config: dict) -> "MapElitesArchive":
        if not isinstance(config, dict) or set(config) != {"structure", "dimensions"} \
                or config["structure"] != "map_elites" \
                or not isinstance(config["dimensions"], list):
            raise ValueError("map_elites parent_pool requires only structure and dimensions")
        return cls(FeatureDimension.from_dict(payload)
                   for payload in config["dimensions"])

    def configuration(self) -> dict:
        return {"kind": self.kind,
                "dimensions": [asdict(dimension) for dimension in self.dimensions]}

    def fork(self) -> "MapElitesArchive":
        return type(self)(self.dimensions)

    def _valid_cell(self, cell) -> bool:
        return (isinstance(cell, tuple) and len(cell) == len(self.dimensions)
                and all(not isinstance(index, bool) and isinstance(index, int)
                        and 0 <= index < dimension.bins
                        for index, dimension in zip(cell, self.dimensions)))

    def cell_for(self, features: dict) -> tuple[int, ...]:
        if not isinstance(features, dict):
            raise ValueError("MAP-Elites public features must be an object")
        missing = [dimension.name for dimension in self.dimensions
                   if dimension.name not in features]
        if missing:
            raise ValueError(f"MAP-Elites features are missing: {', '.join(missing)}")
        return tuple(dimension.index(features[dimension.name])
                     for dimension in self.dimensions)

    @staticmethod
    def _candidate_features(candidate: dict) -> dict:
        result = candidate.get("result")
        public = getattr(result, "public", None)
        if not isinstance(public, dict) or "features" not in public:
            raise ValueError("admitted candidate lacks public MAP-Elites features")
        return public["features"]

    def register(self, candidate: dict, generation: int) -> MapElitesEntry:
        candidate_id = candidate.get("candidate_id")
        score = candidate.get("score")
        if not isinstance(candidate_id, str) or not candidate_id \
                or not _finite_number(score):
            raise ValueError("MAP-Elites candidate requires an ID and finite score")
        if isinstance(generation, bool) or not isinstance(generation, int) or generation < 0:
            raise ValueError("MAP-Elites generation must be a non-negative integer")
        if candidate_id in self.entries:
            raise ValueError(f"duplicate MAP-Elites registration: {candidate_id}")
        cell = self.cell_for(self._candidate_features(candidate))
        entry = MapElitesEntry(candidate_id, float(score), cell, generation)
        self.entries[candidate_id] = entry
        incumbent_id = self.cells.get(cell)
        if incumbent_id is None:
            self.cells[cell] = candidate_id
        else:
            incumbent = self.entries[incumbent_id]
            if (entry.score, entry.candidate_id) > (incumbent.score, incumbent.candidate_id):
                self.cells[cell] = candidate_id
                self.replacement_count += 1
        return entry

    def migrate_if_due(self, generation: int) -> list[dict]:
        """MAP-Elites uses cell elites, not island migration."""
        return []

    def select_parent(self, pool: list[dict], generation: int) -> dict:
        if isinstance(generation, bool) or not isinstance(generation, int) or generation < 0:
            raise ValueError("parent-selection generation must be non-negative")
        available = {candidate["candidate_id"]: candidate for candidate in pool}
        occupied = sorted(cell for cell, candidate_id in self.cells.items()
                          if candidate_id in available
                          and self.entries[candidate_id].parent_eligible)
        if not occupied:
            raise RuntimeError("MAP-Elites has no eligible occupied cell")
        cell = occupied[generation % len(occupied)]
        return available[self.cells[cell]]

    def evict(self, candidate_id: str, reason: str) -> MapElitesEntry:
        if not isinstance(reason, str) or not reason:
            raise ValueError("soft eviction requires a reason")
        entry = self.entries[candidate_id]
        entry.archived = False
        entry.parent_eligible = False
        entry.deliver_eligible = False
        entry.soft_deleted = True
        entry.eviction_reason = reason
        if self.cells.get(entry.cell) == candidate_id:
            del self.cells[entry.cell]
        return entry

    def health(self) -> dict:
        active = [entry for entry in self.entries.values() if entry.parent_eligible]
        grid_cells = math.prod(dimension.bins for dimension in self.dimensions)
        return {"kind": self.kind,
                "entries": len(self.entries), "active": len(active),
                "soft_deleted": sum(entry.soft_deleted for entry in self.entries.values()),
                "feature_dimensions": [dimension.name for dimension in self.dimensions],
                "grid_cells": grid_cells, "occupied_cells": len(self.cells),
                "coverage": len(self.cells) / grid_cells,
                "replacement_count": self.replacement_count,
                "cell_elites": {",".join(str(index) for index in cell): candidate_id
                                for cell, candidate_id in sorted(self.cells.items())}}

    def checkpoint_state(self) -> dict:
        return {**self.configuration(),
                "entries": [{**asdict(entry), "cell": list(entry.cell)}
                            for entry in sorted(self.entries.values(),
                                                key=lambda entry: entry.candidate_id)],
                "cells": [{"cell": list(cell), "candidate_id": candidate_id}
                          for cell, candidate_id in sorted(self.cells.items())],
                "replacement_count": self.replacement_count}

    def restore_state(self, state: dict) -> None:
        required = {"kind", "dimensions", "entries", "cells", "replacement_count"}
        if not isinstance(state, dict) or set(state) != required:
            raise ValueError("MAP-Elites checkpoint schema is invalid")
        configuration = {"kind": state["kind"], "dimensions": state["dimensions"]}
        if configuration != self.configuration():
            raise ValueError("MAP-Elites checkpoint topology mismatch")
        replacement_count = state["replacement_count"]
        if isinstance(replacement_count, bool) or not isinstance(replacement_count, int) \
                or replacement_count < 0:
            raise ValueError("MAP-Elites replacement count is invalid")
        if not isinstance(state["entries"], list) or not isinstance(state["cells"], list):
            raise ValueError("MAP-Elites checkpoint collections must be lists")
        entries: dict[str, MapElitesEntry] = {}
        for payload in state["entries"]:
            if not isinstance(payload, dict):
                raise ValueError("MAP-Elites entry must be an object")
            values = dict(payload)
            try:
                values["cell"] = tuple(values.get("cell", ()))
                entry = MapElitesEntry(**values)
            except (TypeError, ValueError) as error:
                raise ValueError("MAP-Elites entry schema is invalid") from error
            if entry.candidate_id in entries or not entry.candidate_id \
                    or not _finite_number(entry.score) or not self._valid_cell(entry.cell):
                raise ValueError("MAP-Elites entry identity, score or cell is invalid")
            if isinstance(entry.registered_generation, bool) \
                    or not isinstance(entry.registered_generation, int) \
                    or entry.registered_generation < 0:
                raise ValueError("MAP-Elites entry generation is invalid")
            if any(not isinstance(getattr(entry, name), bool) for name in
                   ("archived", "parent_eligible", "deliver_eligible", "soft_deleted")):
                raise ValueError("MAP-Elites entry flags must be boolean")
            if entry.eviction_reason is not None and not isinstance(entry.eviction_reason, str):
                raise ValueError("MAP-Elites eviction reason must be text or null")
            entries[entry.candidate_id] = entry
        cells: dict[tuple[int, ...], str] = {}
        for payload in state["cells"]:
            if not isinstance(payload, dict) or set(payload) != {"cell", "candidate_id"}:
                raise ValueError("MAP-Elites cell binding schema is invalid")
            try:
                cell = tuple(payload["cell"])
            except TypeError as error:
                raise ValueError("MAP-Elites cell coordinate must be iterable") from error
            candidate_id = payload["candidate_id"]
            if not self._valid_cell(cell) or cell in cells or candidate_id not in entries:
                raise ValueError("MAP-Elites cell binding is invalid or ambiguous")
            entry = entries[candidate_id]
            if entry.cell != cell or not entry.parent_eligible or not entry.archived \
                    or entry.soft_deleted:
                raise ValueError("MAP-Elites elite must be an active entry in its cell")
            elites = [candidate for candidate in entries.values()
                      if candidate.cell == cell and candidate.parent_eligible
                      and candidate.archived and not candidate.soft_deleted]
            if max(elites, key=lambda candidate: (candidate.score, candidate.candidate_id)) \
                    is not entry:
                raise ValueError("MAP-Elites cell elite is not the deterministic maximum")
            cells[cell] = candidate_id
        active_cells = {entry.cell for entry in entries.values()
                        if entry.parent_eligible and entry.archived
                        and not entry.soft_deleted}
        for cell in active_cells - set(cells):
            occupants = [entry for entry in entries.values() if entry.cell == cell]
            former_elite = max(occupants,
                               key=lambda entry: (entry.score, entry.candidate_id))
            if former_elite.parent_eligible and former_elite.archived \
                    and not former_elite.soft_deleted:
                raise ValueError("MAP-Elites active cell lacks an elite or eviction explanation")
        self.entries = entries
        self.cells = cells
        self.replacement_count = replacement_count
