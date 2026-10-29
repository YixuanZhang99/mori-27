"""M4 protocol extension: island archive with migration and soft eviction.

The archive owns membership/health; M1 still owns parent selection. No hard-delete
API is exposed (I-可逆/I-谱系): evicted entries remain inspectable forever.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ArchiveEntry:
    candidate_id: str
    score: float
    island_ids: set[int] = field(default_factory=set)
    archived: bool = True
    parent_eligible: bool = True
    deliver_eligible: bool = True
    soft_deleted: bool = False
    eviction_reason: str | None = None


class IslandArchive:
    def __init__(self, num_islands: int = 2, migration_interval: int = 3):
        if num_islands < 1 or migration_interval < 1:
            raise ValueError("invalid island configuration")
        self.num_islands = num_islands
        self.migration_interval = migration_interval
        self.entries: dict[str, ArchiveEntry] = {}
        self.migration_count = 0

    def register(self, candidate: dict, generation: int) -> ArchiveEntry:
        island = generation % self.num_islands
        entry = ArchiveEntry(candidate_id=candidate["candidate_id"],
                             score=candidate["score"], island_ids={island})
        self.entries[entry.candidate_id] = entry
        return entry

    def migrate_if_due(self, generation: int) -> list[dict]:
        """Copy elite membership to the next island; never duplicate the candidate."""
        if generation == 0 or generation % self.migration_interval != 0:
            return []
        events = []
        for source in range(self.num_islands):
            members = [e for e in self.entries.values()
                       if source in e.island_ids and e.parent_eligible]
            if not members:
                continue
            elite = max(members, key=lambda e: (e.score, e.candidate_id))
            target = (source + 1) % self.num_islands
            if target not in elite.island_ids:
                elite.island_ids.add(target)
                self.migration_count += 1
                events.append({"candidate_id": elite.candidate_id,
                               "source": source, "target": target,
                               "generation": generation})
        return events

    def select_parent(self, pool: list[dict], generation: int) -> dict:
        """M1 deterministic island-round-robin + within-island greedy."""
        target = generation % self.num_islands
        eligible = [c for c in pool
                    if c["candidate_id"] in self.entries
                    and self.entries[c["candidate_id"]].parent_eligible
                    and target in self.entries[c["candidate_id"]].island_ids]
        if not eligible:  # cold-start fallback only
            eligible = [c for c in pool
                        if self.entries.get(c["candidate_id"], ArchiveEntry("", 0)).parent_eligible]
        return max(eligible, key=lambda c: (c["score"], c["candidate_id"]))

    def evict(self, candidate_id: str, reason: str) -> ArchiveEntry:
        entry = self.entries[candidate_id]
        entry.archived = False
        entry.parent_eligible = False
        entry.deliver_eligible = False
        entry.soft_deleted = True
        entry.eviction_reason = reason
        return entry

    def health(self) -> dict:
        active = [e for e in self.entries.values() if e.parent_eligible]
        return {"entries": len(self.entries), "active": len(active),
                "soft_deleted": sum(e.soft_deleted for e in self.entries.values()),
                "island_populations": {
                    str(i): sum(i in e.island_ids for e in active)
                    for i in range(self.num_islands)},
                "migration_count": self.migration_count}
