"""Strict, versioned interoperability with the vendored OpenEvolve database.

OpenEvolve metrics and feature grids are host-side sampling/display state.  This
module never converts them into M9 flip evidence or admission decisions.
"""
from __future__ import annotations

import base64
import binascii
import copy
import hashlib
import json
import math
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Callable, Mapping
from urllib.parse import urlsplit

_VENDOR = Path(__file__).resolve().parents[1] / "vendor" / "openevolve"
if str(_VENDOR) not in sys.path:
    sys.path.insert(0, str(_VENDOR))

from openevolve.config import DatabaseConfig  # noqa: E402
from openevolve.database import Program, ProgramDatabase  # noqa: E402

from core.frontier.research import FrontierCheckpoint, ResearchFrontier  # noqa: E402

SCHEMA_VERSION = 1
FRONTIER_GOVERNANCE_SCHEMA = 2
_PROGRAM_FIELDS = frozenset(field.name for field in fields(Program))
_STATE_FIELDS = frozenset({
    "island_feature_maps", "islands", "archive", "best_program_id",
    "island_best_programs", "last_iteration", "current_island",
    "island_generations", "last_migration_generation", "feature_stats",
})
_CONFIG_FIELDS = (
    "log_prompts", "population_size", "archive_size", "num_islands",
    "elite_selection_ratio", "exploration_ratio", "exploitation_ratio",
    "diversity_metric", "feature_dimensions", "feature_bins",
    "diversity_reference_size", "migration_interval", "migration_rate",
    "random_seed", "artifact_size_threshold", "cleanup_old_artifacts",
    "artifact_retention_days", "max_snapshot_artifacts", "similarity_threshold",
    "feature_scaling_method", "embedding_model", "embedding_api_base",
)


def _object_without_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _json_loads(raw: str):
    try:
        return json.loads(raw, object_pairs_hook=_object_without_duplicate_keys)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError("invalid OpenEvolve interoperability JSON") from exc


def _canonical(payload) -> bytes:
    try:
        return json.dumps(payload, sort_keys=True, ensure_ascii=False,
                          separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("OpenEvolve snapshot is not finite canonical JSON") from exc


def _digest(payload) -> str:
    return hashlib.sha256(_canonical(payload)).hexdigest()


def _integer(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _number(value) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value))


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _config_payload(config: DatabaseConfig, num_islands: int,
                    feature_scaling_method: str = "minmax") -> dict:
    _require(config.novelty_llm is None,
             "live novelty LLM objects are not portable database state")
    payload = {name: copy.deepcopy(getattr(config, name)) for name in _CONFIG_FIELDS
               if name != "feature_scaling_method"}
    payload["num_islands"] = num_islands
    payload["feature_scaling_method"] = feature_scaling_method
    return payload


def _database_config(payload: dict) -> DatabaseConfig:
    values = {name: copy.deepcopy(payload[name]) for name in _CONFIG_FIELDS
              if name != "feature_scaling_method"}
    values.update(db_path=None, in_memory=True, artifacts_base_path=None,
                  novelty_llm=None)
    return DatabaseConfig(**values)


def _validate_config(config: dict) -> None:
    _require(isinstance(config, dict), "snapshot config must be an object")
    _require(set(config) == set(_CONFIG_FIELDS), "unsupported OpenEvolve config schema")
    for name in ("population_size", "archive_size", "num_islands",
                 "diversity_reference_size", "migration_interval",
                 "artifact_size_threshold", "artifact_retention_days"):
        _require(_integer(config[name]) and config[name] >= 0,
                 f"invalid OpenEvolve config integer: {name}")
    _require(config["population_size"] > 0 and config["archive_size"] > 0
             and config["num_islands"] > 0, "population, archive and islands must be positive")
    for name in ("elite_selection_ratio", "exploration_ratio", "exploitation_ratio",
                 "migration_rate", "similarity_threshold"):
        _require(_number(config[name]), f"invalid OpenEvolve config number: {name}")
    _require(isinstance(config["log_prompts"], bool)
             and isinstance(config["cleanup_old_artifacts"], bool),
             "invalid OpenEvolve boolean config")
    _require(config["random_seed"] is None or _integer(config["random_seed"]),
             "invalid OpenEvolve random seed")
    _require(config["max_snapshot_artifacts"] is None
             or (_integer(config["max_snapshot_artifacts"])
                 and config["max_snapshot_artifacts"] >= 0),
             "invalid snapshot artifact limit")
    dimensions = config["feature_dimensions"]
    _require(isinstance(dimensions, list) and dimensions
             and all(isinstance(item, str) and item for item in dimensions)
             and len(set(dimensions)) == len(dimensions),
             "feature dimensions must be unique non-empty strings")
    bins = config["feature_bins"]
    if _integer(bins):
        _require(bins > 0, "feature bins must be positive")
    else:
        _require(isinstance(bins, dict) and set(bins) == set(dimensions)
                 and all(_integer(value) and value > 0 for value in bins.values()),
                 "per-dimension bins must exactly cover feature dimensions")
    _require(config["feature_scaling_method"] in {"minmax", "percentile"},
             "unsupported feature scaling method")
    _require(isinstance(config["diversity_metric"], str) and config["diversity_metric"],
             "diversity metric must be non-empty")
    model = config["embedding_model"]
    _require(model is None or (isinstance(model, str) and model.strip() == model and model),
             "embedding model must be null or a non-empty trimmed string")
    api_base = config["embedding_api_base"]
    _require(api_base is None or (isinstance(api_base, str) and api_base.strip() == api_base
                                 and api_base),
             "embedding API base must be null or a non-empty trimmed string")
    _require(api_base is None or model is not None,
             "embedding API base requires an embedding model")
    if api_base is not None:
        parsed = urlsplit(api_base)
        _require(parsed.scheme in {"http", "https"} and parsed.hostname is not None
                 and parsed.username is None and parsed.password is None
                 and not parsed.query and not parsed.fragment,
                 "embedding API base must be an HTTP(S) URL without credentials, query or fragment")


def _validate_program(data: dict) -> None:
    _require(isinstance(data, dict) and set(data) <= _PROGRAM_FIELDS,
             "unsupported OpenEvolve Program schema")
    _require({"id", "code"} <= set(data), "Program requires id and code")
    _require(isinstance(data["id"], str) and data["id"] not in {"", ".", ".."}
             and "/" not in data["id"] and "\\" not in data["id"],
             "Program id must be a safe non-empty filename stem")
    _require(isinstance(data["code"], str), "Program code must be text")
    for name in ("changes_description", "language"):
        _require(isinstance(data.get(name, "" if name == "changes_description" else "python"), str),
                 f"Program {name} must be text")
    for name in ("generation", "iteration_found"):
        _require(_integer(data.get(name, 0)) and data.get(name, 0) >= 0,
                 f"Program {name} must be a non-negative integer")
    _require(_number(data.get("timestamp", 0.0)), "Program timestamp must be finite")
    metrics = data.get("metrics", {})
    _require(isinstance(metrics, dict)
             and all(isinstance(key, str) and key and _number(value)
                     for key, value in metrics.items()),
             "Program metrics must be finite numeric values")
    for name in ("complexity", "diversity"):
        _require(_number(data.get(name, 0.0)), f"Program {name} must be finite")
    _require(isinstance(data.get("metadata", {}), dict), "Program metadata must be an object")
    prompts = data.get("prompts")
    _require(prompts is None or isinstance(prompts, dict), "Program prompts must be an object")
    for name in ("artifacts_json", "artifact_dir"):
        _require(data.get(name) is None or isinstance(data.get(name), str),
                 f"Program {name} must be text or null")
    embedding = data.get("embedding")
    _require(embedding is None or (isinstance(embedding, list)
                                   and all(_number(value) for value in embedding)),
             "Program embedding must contain finite numbers")


def _validate_payload(payload: dict) -> None:
    _require(isinstance(payload, dict) and set(payload) == {"config", "programs", "state"},
             "unsupported OpenEvolve snapshot schema")
    config = payload["config"]
    _validate_config(config)
    programs = payload["programs"]
    _require(isinstance(programs, list), "snapshot programs must be a list")
    by_id = {}
    for data in programs:
        _validate_program(data)
        _require(data["id"] not in by_id, f"duplicate Program id: {data['id']}")
        by_id[data["id"]] = data
    embedding_dimensions = {len(data["embedding"]) for data in programs
                            if data.get("embedding") is not None}
    _require(0 not in embedding_dimensions and len(embedding_dimensions) <= 1,
             "Program embeddings must be non-empty and have one consistent dimension")
    for data in programs:
        parent = data.get("parent_id")
        _require(parent is None or (isinstance(parent, str) and parent in by_id
                                    and parent != data["id"]),
                 f"Program {data['id']} has an unknown or invalid parent")
        if parent is not None:
            _require(data.get("generation", 0) > by_id[parent].get("generation", 0),
                     "child generation must exceed parent generation")
    state = payload["state"]
    _require(isinstance(state, dict) and set(state) == _STATE_FIELDS,
             "unsupported OpenEvolve database state schema")
    count = config["num_islands"]
    for name in ("island_feature_maps", "islands", "island_best_programs",
                 "island_generations"):
        _require(isinstance(state[name], list) and len(state[name]) == count,
                 f"database {name} length does not match configured islands")
    memberships = {}
    for island, program_ids in enumerate(state["islands"]):
        _require(isinstance(program_ids, list) and len(set(program_ids)) == len(program_ids),
                 "island membership must be a unique list")
        for program_id in program_ids:
            _require(isinstance(program_id, str) and program_id in by_id,
                     "island references an unknown Program")
            _require(program_id not in memberships, "Program cannot occupy multiple islands")
            memberships[program_id] = island
    for program_id, data in by_id.items():
        island = data.get("metadata", {}).get("island")
        if island is not None:
            _require(_integer(island) and memberships.get(program_id) == island,
                     "Program island metadata disagrees with database membership")
    archive = state["archive"]
    _require(isinstance(archive, list) and len(set(archive)) == len(archive)
             and all(isinstance(item, str) and item in by_id for item in archive),
             "archive must contain unique existing Program ids")
    best = state["best_program_id"]
    _require(best is None or (isinstance(best, str) and best in by_id),
             "global best references an unknown Program")
    for island, best in enumerate(state["island_best_programs"]):
        _require(best is None or (isinstance(best, str)
                                  and memberships.get(best) == island),
                 "island best must reference a current island member")
    dimensions = config["feature_dimensions"]
    bins = config["feature_bins"]
    if _integer(bins):
        # ProgramDatabase expands a scalar bin count from the archive capacity.
        bins = max(bins, int(pow(config["archive_size"], 1 / len(dimensions)) + 0.99))
    for island, grid in enumerate(state["island_feature_maps"]):
        _require(isinstance(grid, dict), "island feature map must be an object")
        for key, program_id in grid.items():
            _require(isinstance(key, str) and memberships.get(program_id) == island,
                     "feature cell must reference a Program in the same island")
            parts = key.split("-")
            _require(len(parts) == len(dimensions)
                     and all(part.isdigit() for part in parts),
                     "feature cell has the wrong coordinate schema")
            for dimension, part in zip(dimensions, parts):
                limit = bins if _integer(bins) else bins[dimension]
                _require(0 <= int(part) < limit, "feature coordinate exceeds configured bins")
    for name in ("last_iteration", "current_island", "last_migration_generation"):
        _require(_integer(state[name]) and state[name] >= 0,
                 f"database {name} must be a non-negative integer")
    _require(state["current_island"] < count, "current island is out of range")
    _require(all(_integer(value) and value >= 0 for value in state["island_generations"]),
             "island generations must be non-negative integers")
    stats = state["feature_stats"]
    _require(isinstance(stats, dict), "feature stats must be an object")
    for name, values in stats.items():
        _require(isinstance(name, str) and name and isinstance(values, dict)
                 and set(values) == {"min", "max", "values"},
                 "malformed feature statistics")
        _require(_number(values["min"]) and _number(values["max"])
                 and values["min"] <= values["max"]
                 and isinstance(values["values"], list)
                 and all(_number(value) for value in values["values"]),
                 "feature statistics must contain ordered finite numbers")
    _canonical(payload)


@dataclass(frozen=True)
class OpenEvolveInteropEnvelope:
    schema_version: int
    payload: dict
    payload_sha256: str

    def to_bytes(self) -> bytes:
        return _canonical({"schema_version": self.schema_version,
                           "payload": self.payload,
                           "payload_sha256": self.payload_sha256})

    @classmethod
    def from_bytes(cls, raw: bytes) -> "OpenEvolveInteropEnvelope":
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("invalid OpenEvolve envelope encoding") from exc
        envelope = _json_loads(text)
        _require(isinstance(envelope, dict)
                 and set(envelope) == {"schema_version", "payload", "payload_sha256"}
                 and envelope["schema_version"] == SCHEMA_VERSION,
                 "unsupported OpenEvolve interoperability envelope")
        payload = envelope["payload"]
        _require(isinstance(envelope["payload_sha256"], str)
                 and envelope["payload_sha256"] == _digest(payload),
                 "OpenEvolve snapshot integrity check failed")
        _validate_payload(payload)
        return cls(SCHEMA_VERSION, payload, envelope["payload_sha256"])


@dataclass(frozen=True)
class OpenEvolveDatabaseSnapshot:
    """Validated host database state; it carries no governed admission verdict."""

    payload: dict

    def __post_init__(self):
        _validate_payload(self.payload)

    @classmethod
    def from_database(cls, database: ProgramDatabase) -> "OpenEvolveDatabaseSnapshot":
        _require(isinstance(database, ProgramDatabase), "expected a real ProgramDatabase")
        payload = {
            "config": _config_payload(database.config, len(database.islands),
                                      database.feature_scaling_method),
            "programs": [copy.deepcopy(database.programs[key].to_dict())
                         for key in sorted(database.programs)],
            "state": {
                "island_feature_maps": copy.deepcopy(database.island_feature_maps),
                "islands": [sorted(island) for island in database.islands],
                "archive": sorted(database.archive),
                "best_program_id": database.best_program_id,
                "island_best_programs": list(database.island_best_programs),
                "last_iteration": database.last_iteration,
                "current_island": database.current_island,
                "island_generations": list(database.island_generations),
                "last_migration_generation": database.last_migration_generation,
                "feature_stats": database._serialize_feature_stats(),
            },
        }
        return cls(payload)

    def to_database(self) -> ProgramDatabase:
        _validate_payload(self.payload)
        config = _database_config(self.payload["config"])
        database = ProgramDatabase(config)
        database.feature_scaling_method = self.payload["config"]["feature_scaling_method"]
        database.programs = {
            data["id"]: Program.from_dict(copy.deepcopy(data))
            for data in self.payload["programs"]
        }
        state = self.payload["state"]
        database.island_feature_maps = copy.deepcopy(state["island_feature_maps"])
        database.islands = [set(items) for items in state["islands"]]
        database.archive = set(state["archive"])
        database.best_program_id = state["best_program_id"]
        database.island_best_programs = list(state["island_best_programs"])
        database.last_iteration = state["last_iteration"]
        database.current_island = state["current_island"]
        database.island_generations = list(state["island_generations"])
        database.last_migration_generation = state["last_migration_generation"]
        database.feature_stats = database._deserialize_feature_stats(
            copy.deepcopy(state["feature_stats"]))
        return database

    def to_bytes(self) -> bytes:
        _validate_payload(self.payload)
        return OpenEvolveInteropEnvelope(SCHEMA_VERSION, self.payload,
                                         _digest(self.payload)).to_bytes()

    @classmethod
    def from_bytes(cls, raw: bytes) -> "OpenEvolveDatabaseSnapshot":
        return cls(OpenEvolveInteropEnvelope.from_bytes(raw).payload)


def frontier_to_openevolve(
        frontier: ResearchFrontier,
        code_by_id: Mapping[str, str] | Callable[[str], str],
        config: DatabaseConfig | None = None,
        island_by_id: Mapping[str, int] | Callable[[str], int] | None = None,
        language: str = "python") -> ProgramDatabase:
    """Export an eligible Frontier, preserving DAG lineage in governance metadata.

    OpenEvolve's native sampler sees only the first declared parent.  The complete
    checkpoint is carried at one deterministic anchor and hash-bound by every node.
    """
    _require(isinstance(frontier, ResearchFrontier), "expected a ResearchFrontier")
    count = len(frontier.nodes)
    _require(count > 0, "Frontier export requires at least one governance anchor")
    config = copy.deepcopy(config) if config is not None else DatabaseConfig(
        num_islands=1, population_size=max(1000, count),
        archive_size=max(100, count), feature_dimensions=["complexity"], random_seed=0)
    _require(count <= config.population_size,
             "OpenEvolve population cap would evict Frontier nodes")
    code_for = code_by_id if callable(code_by_id) else lambda node: code_by_id[node]
    island_for = island_by_id if callable(island_by_id) else (
        (lambda node: island_by_id.get(node, 0)) if island_by_id is not None
        else (lambda node: 0))
    checkpoint_raw = frontier.checkpoint()
    checkpoint = FrontierCheckpoint.from_bytes(checkpoint_raw)
    checkpoint_envelope = _json_loads(checkpoint_raw.decode("utf-8"))
    checkpoint_anchor = min(frontier.nodes)
    database = ProgramDatabase(config)
    exported_programs = {}
    for node_id in sorted(frontier.nodes,
                          key=lambda key: (frontier.nodes[key].depth, key)):
        node = frontier.nodes[node_id]
        _require(node.status in {"done", "merged"} and node.eval_status == "ok",
                 "only completed OK Frontier nodes can be exported")
        code = code_for(node_id)
        _require(isinstance(code, str), f"missing textual code for Frontier node {node_id}")
        island = island_for(node_id)
        _require(_integer(island) and 0 <= island < config.num_islands,
                 f"invalid target island for Frontier node {node_id}")
        primary_parent = node.parent_ids[0] if node.parent_ids else None
        metadata = {
            "governance_schema": FRONTIER_GOVERNANCE_SCHEMA,
            "frontier_checkpoint_sha256": checkpoint.payload_sha256,
            "frontier_node": asdict(node),
            "frontier_primary_parent_id": primary_parent,
            "frontier_additional_parent_ids": list(node.parent_ids[1:]),
            "frontier_status": node.status,
            "frontier_depth": node.depth,
            "operator": node.operator,
            "created_cycle": node.created_cycle,
            "code_ref": node.code_ref,
            "grounding": copy.deepcopy(node.grounding),
            "related_work": copy.deepcopy(node.related_work),
            "attempt": node.attempt,
            "cost": copy.deepcopy(node.cost),
            "uncertainty": node.uncertainty,
            "prune_reason": node.prune_reason,
            "host_metrics_not_m9_evidence": True,
        }
        if node_id == checkpoint_anchor:
            metadata["frontier_checkpoint"] = checkpoint_envelope
        program = Program(
            id=node.id, code=code, changes_description=node.hypothesis or "",
            language=language, parent_id=primary_parent,
            generation=node.depth, timestamp=float(node.created_cycle),
            iteration_found=node.created_cycle, metrics=copy.deepcopy(node.score_split),
            complexity=float(len(code)), diversity=0.0, metadata=metadata)
        exported_programs[node_id] = Program.from_dict(program.to_dict())
        database.add(program, iteration=node.created_cycle, target_island=island)
    # Native cell replacement and novelty filtering may deactivate a Program.  Keep
    # its governed code/lineage without fabricating island or elite membership.
    for node_id, program in exported_programs.items():
        if node_id not in database.programs:
            database.programs[node_id] = copy.deepcopy(program)
    members = set().union(*database.islands) if database.islands else set()
    for program in database.programs.values():
        if program.id not in members:
            program.metadata.pop("island", None)
    _require(set(database.programs) == set(frontier.nodes),
             "OpenEvolve export did not retain every Frontier node")
    snapshot = OpenEvolveDatabaseSnapshot.from_database(database)
    restored = frontier_from_openevolve(snapshot)
    _require(restored.checkpoint() == checkpoint_raw,
             "OpenEvolve export changed the governed Frontier checkpoint")
    return database


def _validate_restored_frontier_graph(frontier: ResearchFrontier) -> None:
    """Check exact DAG adjacency and canonical information-only references."""
    expected_skeleton = set()
    expected_children = {node_id: [] for node_id in frontier.nodes}
    for node_id, node in frontier.nodes.items():
        _require(node.id == node_id and len(node.parent_ids) == len(set(node.parent_ids))
                 and node_id not in node.parent_ids,
                 "Frontier checkpoint contains duplicate or invalid parents")
        _require(node.status in {"done", "merged"} and node.eval_status == "ok",
                 "governed OpenEvolve recovery accepts only completed OK nodes")
        for parent in node.parent_ids:
            expected_skeleton.add((parent, node_id))
            expected_children[parent].append(node_id)
        expected_depth = 1 + max((frontier.nodes[parent].depth
                                  for parent in node.parent_ids), default=-1)
        _require(node.depth == expected_depth, "Frontier checkpoint depth mismatch")
    for node_id, node in frontier.nodes.items():
        _require(node.children_ids == sorted(expected_children[node_id]),
                 "Frontier checkpoint children are incomplete or non-canonical")
    _require(frontier.edges["skeleton"] == expected_skeleton,
             "Frontier checkpoint skeleton edges do not exactly match node parents")
    references = frontier.edges["reference"]
    _require(isinstance(references, list)
             and all(isinstance(edge, dict)
                     and set(edge) == {"source", "target", "rationale"}
                     and edge["source"] in frontier.nodes
                     and edge["target"] in frontier.nodes
                     and edge["source"] != edge["target"]
                     and isinstance(edge["rationale"], str) and edge["rationale"]
                     for edge in references),
             "Frontier checkpoint contains an invalid reference edge")
    _require(references == sorted(references, key=lambda item: (
                 item["source"], item["target"], item["rationale"]))
             and len(references) == len({_canonical(edge) for edge in references}),
             "Frontier checkpoint reference edges are duplicate or non-canonical")


def frontier_from_openevolve(
        source: ProgramDatabase | OpenEvolveDatabaseSnapshot) -> ResearchFrontier:
    """Restore only a complete v2 governed export; never infer evidence from hosts."""
    if isinstance(source, ProgramDatabase):
        snapshot = OpenEvolveDatabaseSnapshot.from_database(source)
    else:
        _require(isinstance(source, OpenEvolveDatabaseSnapshot),
                 "expected a ProgramDatabase or OpenEvolveDatabaseSnapshot")
        snapshot = source
    _validate_payload(snapshot.payload)
    programs = {program["id"]: program for program in snapshot.payload["programs"]}
    _require(programs, "governed Frontier recovery requires a checkpoint anchor")
    carriers = []
    checkpoint_hashes = set()
    for program_id, program in programs.items():
        metadata = program.get("metadata", {})
        _require(metadata.get("governance_schema") == FRONTIER_GOVERNANCE_SCHEMA
                 and metadata.get("host_metrics_not_m9_evidence") is True,
                 f"Program {program_id} lacks governed Frontier metadata")
        checkpoint_hash = metadata.get("frontier_checkpoint_sha256")
        _require(isinstance(checkpoint_hash, str) and len(checkpoint_hash) == 64,
                 f"Program {program_id} lacks a Frontier checkpoint binding")
        checkpoint_hashes.add(checkpoint_hash)
        if "frontier_checkpoint" in metadata:
            carriers.append(program_id)
    expected_anchor = min(programs)
    _require(carriers == [expected_anchor],
             "Frontier checkpoint must occur only at its deterministic anchor")
    envelope = programs[expected_anchor]["metadata"]["frontier_checkpoint"]
    _require(isinstance(envelope, dict)
             and set(envelope) == {"schema_version", "payload", "payload_sha256"},
             "malformed governed Frontier checkpoint envelope")
    raw = _canonical(envelope)
    checkpoint = FrontierCheckpoint.from_bytes(raw)
    _require(checkpoint_hashes == {checkpoint.payload_sha256},
             "Frontier checkpoint bindings disagree across Programs")
    try:
        frontier = ResearchFrontier.restore(raw)
    except (KeyError, TypeError) as exc:
        raise ValueError("invalid governed Frontier checkpoint") from exc
    _require(frontier.checkpoint() == raw,
             "Frontier checkpoint is not canonical after restoration")
    _require(set(frontier.nodes) == set(programs),
             "Frontier checkpoint and OpenEvolve Program sets disagree")
    _validate_restored_frontier_graph(frontier)
    for node_id, node in frontier.nodes.items():
        program = programs[node_id]
        metadata = program["metadata"]
        primary_parent = node.parent_ids[0] if node.parent_ids else None
        _require(metadata.get("frontier_node") == asdict(node),
                 f"Program {node_id} Frontier node metadata disagrees with checkpoint")
        _require(metadata.get("frontier_primary_parent_id") == primary_parent
                 and metadata.get("frontier_additional_parent_ids") == node.parent_ids[1:],
                 f"Program {node_id} primary/additional parent mapping is inconsistent")
        _require(program.get("parent_id") == primary_parent
                 and program.get("generation", 0) == node.depth
                 and program.get("metrics", {}) == node.score_split,
                 f"Program {node_id} native fields disagree with governed Frontier state")
    return frontier


def read_openevolve_database(path: str | os.PathLike,
                             config: DatabaseConfig) -> OpenEvolveDatabaseSnapshot:
    """Read native disk state strictly, before OpenEvolve can clean or skip it."""
    root = Path(path)
    metadata_path = root / "metadata.json"
    _require(root.is_dir() and metadata_path.is_file(),
             "OpenEvolve database requires metadata.json")
    try:
        metadata = _json_loads(metadata_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError("unable to read OpenEvolve metadata") from exc
    _require(isinstance(metadata, dict) and set(metadata) == _STATE_FIELDS,
             "unsupported native OpenEvolve metadata schema")
    programs = []
    seen_files = set()
    programs_dir = root / "programs"
    if programs_dir.exists():
        _require(programs_dir.is_dir(), "OpenEvolve programs path must be a directory")
        for program_path in sorted(programs_dir.iterdir(), key=lambda item: item.name):
            if not program_path.name.endswith(".json"):
                continue
            _require(program_path.is_file(), "Program JSON entries must be regular files")
            try:
                data = _json_loads(program_path.read_text(encoding="utf-8"))
            except OSError as exc:
                raise ValueError(f"unable to read Program file {program_path.name}") from exc
            _require(isinstance(data, dict) and isinstance(data.get("id"), str),
                     f"malformed Program file {program_path.name}")
            _require(program_path.name == data["id"] + ".json",
                     "Program filename and embedded id disagree")
            _require(data["id"] not in seen_files, "duplicate Program id on disk")
            seen_files.add(data["id"])
            programs.append(data)
    saved_islands = metadata.get("islands")
    _require(isinstance(saved_islands, list)
             and len(saved_islands) == config.num_islands,
             "native island count must exactly match the supplied DatabaseConfig")
    state = copy.deepcopy(metadata)
    if isinstance(state.get("islands"), list):
        state["islands"] = [sorted(items) if isinstance(items, list) else items
                            for items in state["islands"]]
    if isinstance(state.get("archive"), list):
        state["archive"] = sorted(state["archive"])
    payload = {
        "config": _config_payload(config, config.num_islands,
                                  getattr(config, "feature_scaling_method", "minmax")),
        "programs": programs,
        "state": state,
    }
    return OpenEvolveDatabaseSnapshot(payload)


def write_openevolve_database(snapshot: OpenEvolveDatabaseSnapshot,
                              path: str | os.PathLike) -> None:
    """Atomically create a new native database and verify its exact disk roundtrip."""
    _require(isinstance(snapshot, OpenEvolveDatabaseSnapshot),
             "expected an OpenEvolveDatabaseSnapshot")
    destination = Path(path)
    _require(not destination.exists(), "native database destination must not already exist")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{destination.name}.tmp-",
                                      dir=destination.parent))
    try:
        database = snapshot.to_database()
        database.save(str(temporary), iteration=database.last_iteration)
        reread = read_openevolve_database(temporary, database.config)
        _require(reread.to_bytes() == snapshot.to_bytes(),
                 "native OpenEvolve save/load changed governed snapshot state")
        os.replace(temporary, destination)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


ARTIFACT_SCHEMA_VERSION = 1
ARTIFACT_ENVELOPE_KIND = "openevolve_artifact_bundle"


def _valid_digest(value) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and all(character in "0123456789abcdef" for character in value))


def _safe_artifact_name(value) -> bool:
    return (isinstance(value, str) and value not in {"", ".", ".."}
            and all(character.isalnum() or character in "._-" for character in value))


def _validate_small_artifacts(snapshot: OpenEvolveDatabaseSnapshot) -> None:
    _require(isinstance(snapshot, OpenEvolveDatabaseSnapshot),
             "expected an OpenEvolveDatabaseSnapshot")
    for program in snapshot.payload["programs"]:
        raw = program.get("artifacts_json")
        if not raw:
            continue
        try:
            artifacts = _json_loads(raw)
        except ValueError as exc:
            raise ValueError(f"invalid small artifacts for Program {program['id']}") from exc
        _require(isinstance(artifacts, dict)
                 and all(isinstance(key, str) for key in artifacts),
                 f"small artifacts for Program {program['id']} must be an object")
        _canonical(artifacts)


def _artifact_file_payload(name: str, content: bytes) -> dict:
    return {"name": name, "size": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
            "content_base64": base64.b64encode(content).decode("ascii")}


def _artifact_content(file_payload: dict) -> bytes:
    _require(isinstance(file_payload, dict)
             and set(file_payload) == {"name", "size", "sha256", "content_base64"},
             "unsupported artifact file schema")
    _require(_safe_artifact_name(file_payload["name"]),
             "unsafe OpenEvolve artifact filename")
    _require(_integer(file_payload["size"]) and file_payload["size"] >= 0
             and _valid_digest(file_payload["sha256"])
             and isinstance(file_payload["content_base64"], str),
             "invalid artifact size, digest or encoding")
    try:
        content = base64.b64decode(file_payload["content_base64"], validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("invalid artifact base64 content") from exc
    _require(len(content) == file_payload["size"]
             and hashlib.sha256(content).hexdigest() == file_payload["sha256"],
             "artifact content size or SHA256 mismatch")
    return content


def _validate_artifact_payload(payload: dict) -> None:
    _require(isinstance(payload, dict) and set(payload) == {"database_sha256", "artifacts"}
             and _valid_digest(payload["database_sha256"])
             and isinstance(payload["artifacts"], list),
             "unsupported OpenEvolve artifact bundle schema")
    program_ids = set()
    for entry in payload["artifacts"]:
        _require(isinstance(entry, dict) and set(entry) == {"program_id", "files"}
                 and isinstance(entry["program_id"], str) and entry["program_id"]
                 and isinstance(entry["files"], list),
                 "malformed Program artifact entry")
        _require(entry["program_id"] not in program_ids,
                 "duplicate Program artifact entry")
        program_ids.add(entry["program_id"])
        names = set()
        for file_payload in entry["files"]:
            _artifact_content(file_payload)
            _require(file_payload["name"] not in names,
                     "duplicate artifact filename within a Program")
            names.add(file_payload["name"])
    _canonical(payload)


def _validate_artifact_binding(payload: dict,
                               snapshot: OpenEvolveDatabaseSnapshot) -> None:
    _validate_artifact_payload(payload)
    _validate_small_artifacts(snapshot)
    _require(payload["database_sha256"] == _digest(snapshot.payload),
             "artifact bundle is bound to a different database snapshot")
    expected = {program["id"] for program in snapshot.payload["programs"]
                if program.get("artifact_dir")}
    actual = {entry["program_id"] for entry in payload["artifacts"]}
    _require(actual == expected,
             "artifact bundle entries do not exactly match Program artifact_dir references")


@dataclass(frozen=True)
class OpenEvolveArtifactEnvelope:
    schema_version: int
    kind: str
    payload: dict
    payload_sha256: str

    def to_bytes(self) -> bytes:
        return _canonical({"schema_version": self.schema_version, "kind": self.kind,
                           "payload": self.payload, "payload_sha256": self.payload_sha256})

    @classmethod
    def from_bytes(cls, raw: bytes,
                   snapshot: OpenEvolveDatabaseSnapshot) -> "OpenEvolveArtifactEnvelope":
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("invalid OpenEvolve artifact envelope encoding") from exc
        envelope = _json_loads(text)
        _require(isinstance(envelope, dict)
                 and set(envelope) == {"schema_version", "kind", "payload", "payload_sha256"}
                 and envelope["schema_version"] == ARTIFACT_SCHEMA_VERSION
                 and envelope["kind"] == ARTIFACT_ENVELOPE_KIND,
                 "unsupported OpenEvolve artifact envelope")
        payload = envelope["payload"]
        _require(isinstance(envelope["payload_sha256"], str)
                 and envelope["payload_sha256"] == _digest(payload),
                 "OpenEvolve artifact envelope integrity check failed")
        _validate_artifact_binding(payload, snapshot)
        return cls(ARTIFACT_SCHEMA_VERSION, ARTIFACT_ENVELOPE_KIND,
                   payload, envelope["payload_sha256"])


@dataclass(frozen=True)
class OpenEvolveArtifactBundle:
    """Raw external artifact bytes bound to one exact database snapshot."""

    payload: dict

    def __post_init__(self):
        _validate_artifact_payload(self.payload)

    def bind(self, snapshot: OpenEvolveDatabaseSnapshot) -> "OpenEvolveArtifactBundle":
        _validate_artifact_binding(self.payload, snapshot)
        return self

    def to_bytes(self) -> bytes:
        _validate_artifact_payload(self.payload)
        return OpenEvolveArtifactEnvelope(
            ARTIFACT_SCHEMA_VERSION, ARTIFACT_ENVELOPE_KIND,
            self.payload, _digest(self.payload)).to_bytes()

    @classmethod
    def from_bytes(cls, raw: bytes,
                   snapshot: OpenEvolveDatabaseSnapshot) -> "OpenEvolveArtifactBundle":
        return cls(OpenEvolveArtifactEnvelope.from_bytes(raw, snapshot).payload)

    def _write_files(self, artifact_root: Path) -> None:
        _require(not artifact_root.exists(), "artifact destination must not already exist")
        artifact_root.mkdir(parents=True)
        for entry in self.payload["artifacts"]:
            program_dir = artifact_root / entry["program_id"]
            _require(_safe_artifact_name(entry["program_id"]),
                     "unsafe Program artifact directory")
            program_dir.mkdir()
            for file_payload in entry["files"]:
                content = _artifact_content(file_payload)
                with (program_dir / file_payload["name"]).open("xb") as output:
                    output.write(content)

    def _relocated_snapshot(self, snapshot: OpenEvolveDatabaseSnapshot,
                            artifact_root: Path) -> OpenEvolveDatabaseSnapshot:
        self.bind(snapshot)
        payload = copy.deepcopy(snapshot.payload)
        for program in payload["programs"]:
            if program.get("artifact_dir"):
                program["artifact_dir"] = str(artifact_root / program["id"])
        return OpenEvolveDatabaseSnapshot(payload)


def export_openevolve_artifacts(snapshot: OpenEvolveDatabaseSnapshot,
                                artifact_root: str | os.PathLike) -> OpenEvolveArtifactBundle:
    """Read every referenced external artifact without following path escapes."""
    _validate_small_artifacts(snapshot)
    referenced = [program for program in snapshot.payload["programs"]
                  if program.get("artifact_dir")]
    entries = []
    if referenced:
        root = Path(artifact_root)
        _require(root.is_dir() and not root.is_symlink(),
                 "referenced artifacts require a non-symlink artifact root")
        resolved_root = root.resolve(strict=True)
        for program in referenced:
            directory = Path(program["artifact_dir"])
            _require(not directory.is_symlink() and directory.is_dir(),
                     f"artifact directory for Program {program['id']} is missing or unsafe")
            resolved = directory.resolve(strict=True)
            _require(resolved.parent == resolved_root and resolved.name == program["id"],
                     "artifact_dir must be a direct child named after its Program")
            files = []
            for path in sorted(directory.iterdir(), key=lambda item: item.name):
                _require(not path.is_symlink() and path.is_file(),
                         "artifact directories may contain only regular non-symlink files")
                _require(_safe_artifact_name(path.name),
                         "unsafe OpenEvolve artifact filename")
                try:
                    content = path.read_bytes()
                except OSError as exc:
                    raise ValueError(f"unable to read artifact {path.name}") from exc
                files.append(_artifact_file_payload(path.name, content))
            entries.append({"program_id": program["id"], "files": files})
    return OpenEvolveArtifactBundle({"database_sha256": _digest(snapshot.payload),
                                     "artifacts": entries})


def materialize_openevolve_artifacts(
        snapshot: OpenEvolveDatabaseSnapshot,
        bundle: OpenEvolveArtifactBundle,
        artifact_root: str | os.PathLike) -> OpenEvolveDatabaseSnapshot:
    """Atomically create an artifact root and return its relocated database snapshot."""
    _require(isinstance(bundle, OpenEvolveArtifactBundle),
             "expected an OpenEvolveArtifactBundle")
    bundle.bind(snapshot)
    destination = Path(artifact_root)
    _require(not destination.exists(), "artifact destination must not already exist")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_parent = Path(tempfile.mkdtemp(prefix=f".{destination.name}.tmp-",
                                             dir=destination.parent))
    temporary = temporary_parent / "artifacts"
    try:
        bundle._write_files(temporary)
        relocated = bundle._relocated_snapshot(snapshot, destination)
        verified = export_openevolve_artifacts(
            bundle._relocated_snapshot(snapshot, temporary), temporary)
        _require(verified.payload["artifacts"] == bundle.payload["artifacts"],
                 "materialized artifact content differs from its bundle")
        os.replace(temporary, destination)
        temporary_parent.rmdir()
        return relocated
    except Exception:
        shutil.rmtree(temporary_parent, ignore_errors=True)
        raise


def write_openevolve_database_with_artifacts(
        snapshot: OpenEvolveDatabaseSnapshot,
        bundle: OpenEvolveArtifactBundle,
        path: str | os.PathLike) -> OpenEvolveDatabaseSnapshot:
    """Atomically migrate native database and artifacts under one destination."""
    _require(isinstance(snapshot, OpenEvolveDatabaseSnapshot)
             and isinstance(bundle, OpenEvolveArtifactBundle),
             "expected matching database snapshot and artifact bundle")
    bundle.bind(snapshot)
    destination = Path(path)
    _require(not destination.exists(), "native database destination must not already exist")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{destination.name}.tmp-",
                                      dir=destination.parent))
    try:
        bundle._write_files(temporary / "artifacts")
        relocated = bundle._relocated_snapshot(snapshot, destination / "artifacts")
        database = relocated.to_database()
        database.save(str(temporary), iteration=database.last_iteration)
        reread = read_openevolve_database(temporary, database.config)
        _require(reread.to_bytes() == relocated.to_bytes(),
                 "native database save/load changed relocated snapshot state")
        verified = export_openevolve_artifacts(
            bundle._relocated_snapshot(snapshot, temporary / "artifacts"),
            temporary / "artifacts")
        _require(verified.payload["artifacts"] == bundle.payload["artifacts"],
                 "native artifact migration changed file content")
        os.replace(temporary, destination)
        return relocated
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def read_openevolve_database_with_artifacts(
        path: str | os.PathLike,
        config: DatabaseConfig) -> tuple[OpenEvolveDatabaseSnapshot, OpenEvolveArtifactBundle]:
    """Strictly read native state and all referenced external artifact bytes."""
    snapshot = read_openevolve_database(path, config)
    bundle = export_openevolve_artifacts(snapshot, Path(path) / "artifacts")
    return snapshot, bundle
