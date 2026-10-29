"""v52 lossless multi-parent Frontier/OpenEvolve interoperability."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor" / "openevolve"))

from openevolve.config import DatabaseConfig
from openevolve.database import Program, ProgramDatabase

from core.eval.gate import AdmissionGate
from core.eval.types import EvalResult, ItemResult
from core.executor import Candidate, CostVec, EvalResult as ExecutorResult, EvalStatus, EvidenceRecord
from core.frontier import ResearchFrontier
from core.openevolve_interop import (
    OpenEvolveDatabaseSnapshot,
    frontier_from_openevolve,
    frontier_to_openevolve,
    read_openevolve_database,
    write_openevolve_database,
)
from core.x1.store import AppendOnlyStore


def config(**overrides):
    values = dict(num_islands=2, population_size=30, archive_size=30,
                  feature_dimensions=["novelty", "score"],
                  feature_bins={"novelty": 3, "score": 4}, random_seed=7,
                  exploration_ratio=0.0, exploitation_ratio=1.0)
    values.update(overrides)
    return DatabaseConfig(**values)


def candidate(node, parents=()):
    return Candidate(node, parents=list(parents), hypothesis=f"hypothesis:{node}",
                     operator="crossover" if len(parents) > 1 else (
                         "improve" if parents else "draft"),
                     created_cycle=len(node))


def evidence(node, score):
    return EvidenceRecord(node, ExecutorResult(
        EvalStatus.OK,
        metrics={"dev/score": score, "combined_score": score, "novelty": score / 10},
        cost=CostVec(wall_seconds=1.25), text_feedback=f"feedback:{node}"),
        branch_ref=f"branch/{node}", insight=f"insight:{node}")


def governed_frontier():
    frontier = ResearchFrontier(sample_seed=19, git_state={"head": "abc123"},
                                messages=["governed history"])
    frontier.add(candidate("root"), evidence("root", 0.4))
    frontier.add(candidate("left", ("root",)), evidence("left", 0.8))
    frontier.add(candidate("right", ("root",)), evidence("right", 0.6))
    # Declaration order is intentional: right is the native primary parent.
    frontier.add(candidate("merged", ("right", "left")), evidence("merged", 0.9))
    frontier.nodes["merged"].status = "merged"
    frontier.add_reference("merged", "root", "information only")
    frontier.add_reference("left", "right", "alternative branch")
    return frontier


def codes(frontier):
    return {node: f"prompt = '{node}'" for node in frontier.nodes}


def exported_snapshot():
    frontier = governed_frontier()
    database = frontier_to_openevolve(
        frontier, codes(frontier), config(),
        island_by_id={"root": 0, "left": 0, "right": 1, "merged": 0})
    return frontier, OpenEvolveDatabaseSnapshot.from_database(database)


def program(snapshot, node):
    return next(row for row in snapshot.payload["programs"] if row["id"] == node)


def canonical(payload):
    return json.dumps(payload, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode()


def rehash_checkpoint(snapshot, mutate):
    """Recompute unkeyed hashes so semantic validation, not only digesting, is tested."""
    anchor = min(row["id"] for row in snapshot.payload["programs"])
    envelope = program(snapshot, anchor)["metadata"]["frontier_checkpoint"]
    mutate(envelope["payload"])
    digest = hashlib.sha256(canonical(envelope["payload"])).hexdigest()
    envelope["payload_sha256"] = digest
    for row in snapshot.payload["programs"]:
        row["metadata"]["frontier_checkpoint_sha256"] = digest


def test_multi_parent_native_roundtrip_is_checkpoint_exact(tmp_path):
    frontier, snapshot = exported_snapshot()
    merged = program(snapshot, "merged")
    assert merged["parent_id"] == "right"
    assert merged["metadata"]["frontier_primary_parent_id"] == "right"
    assert merged["metadata"]["frontier_additional_parent_ids"] == ["left"]
    carriers = [row["id"] for row in snapshot.payload["programs"]
                if "frontier_checkpoint" in row["metadata"]]
    assert carriers == ["left"]
    # Native cell replacement displaced left; governance retains it without fake membership.
    members = set().union(*map(set, snapshot.payload["state"]["islands"]))
    assert {row["id"] for row in snapshot.payload["programs"]} == set(frontier.nodes)
    assert "left" not in members
    assert "island" not in program(snapshot, "left")["metadata"]

    restored = frontier_from_openevolve(snapshot)
    assert restored.checkpoint() == frontier.checkpoint()
    assert restored.nodes["merged"].parent_ids == ["right", "left"]
    assert restored.nodes["right"].children_ids == ["merged"]
    assert restored.edges["reference"] == frontier.edges["reference"]
    assert restored.git_state == {"head": "abc123"}
    assert restored.messages == ["governed history"]

    destination = tmp_path / "native"
    write_openevolve_database(snapshot, destination)
    disk = read_openevolve_database(destination, config())
    assert frontier_from_openevolve(disk).checkpoint() == frontier.checkpoint()
    native = ProgramDatabase(config())
    native.load(str(destination))
    assert native.get("merged").parent_id == "right"
    assert native.get("merged").code == "prompt = 'merged'"
    assert frontier_from_openevolve(native).checkpoint() == frontier.checkpoint()


def test_export_rejects_empty_pending_and_failed_sources():
    with pytest.raises(ValueError, match="at least one"):
        frontier_to_openevolve(ResearchFrontier(), {}, config())
    pending = governed_frontier()
    pending.add(candidate("pending", ("merged",)), None)
    with pytest.raises(ValueError, match="completed OK"):
        frontier_to_openevolve(pending, codes(pending), config())
    failed = governed_frontier()
    failed.nodes["merged"].eval_status = "failed"
    with pytest.raises(ValueError, match="completed OK"):
        frontier_to_openevolve(failed, codes(failed), config())


def test_arbitrary_host_database_cannot_be_promoted_to_frontier():
    host = ProgramDatabase(config())
    host.add(Program("host", "x = 1", metrics={"dev/score": 1.0,
                                               "combined_score": 1.0,
                                               "novelty": 0.1}))
    with pytest.raises(ValueError, match="governed Frontier metadata"):
        frontier_from_openevolve(host)


@pytest.mark.parametrize("field,value", [
    ("frontier_primary_parent_id", "left"),
    ("frontier_additional_parent_ids", ["right"]),
])
def test_primary_and_additional_parent_tampering_fails_closed(field, value):
    _, snapshot = exported_snapshot()
    program(snapshot, "merged")["metadata"][field] = value
    with pytest.raises(ValueError, match="parent mapping|native fields"):
        frontier_from_openevolve(snapshot)


def test_missing_duplicate_and_unbound_checkpoint_metadata_fails_closed():
    _, missing = exported_snapshot()
    del program(missing, "left")["metadata"]["frontier_checkpoint"]
    with pytest.raises(ValueError, match="deterministic anchor"):
        frontier_from_openevolve(missing)

    _, duplicate = exported_snapshot()
    duplicate_envelope = deepcopy(program(duplicate, "left")["metadata"]["frontier_checkpoint"])
    program(duplicate, "root")["metadata"]["frontier_checkpoint"] = duplicate_envelope
    with pytest.raises(ValueError, match="deterministic anchor"):
        frontier_from_openevolve(duplicate)

    _, unbound = exported_snapshot()
    program(unbound, "root")["metadata"]["frontier_checkpoint_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="bindings disagree"):
        frontier_from_openevolve(unbound)

    _, absent = exported_snapshot()
    del program(absent, "right")["metadata"]["frontier_node"]
    with pytest.raises(ValueError, match="node metadata"):
        frontier_from_openevolve(absent)


def test_checkpoint_config_and_node_forks_fail_closed():
    _, config_fork = exported_snapshot()
    anchor = min(row["id"] for row in config_fork.payload["programs"])
    envelope = program(config_fork, anchor)["metadata"]["frontier_checkpoint"]
    envelope["payload"]["config"]["metric"] = "combined_score"
    with pytest.raises(ValueError, match="integrity"):
        frontier_from_openevolve(config_fork)

    _, node_fork = exported_snapshot()
    rehash_checkpoint(node_fork, lambda payload: next(
        row for row in payload["nodes"] if row["id"] == "merged").__setitem__(
            "hypothesis", "forked"))
    with pytest.raises(ValueError, match="node metadata disagrees"):
        frontier_from_openevolve(node_fork)


@pytest.mark.parametrize("kind", ["children", "skeleton", "depth", "reference"])
def test_semantic_graph_tampering_is_rejected_even_with_recomputed_hashes(kind):
    _, snapshot = exported_snapshot()

    def mutate(payload):
        if kind == "children":
            node = next(row for row in payload["nodes"] if row["id"] == "right")
            node["children_ids"] = []
        elif kind == "skeleton":
            payload["edges"]["skeleton"] = [
                edge for edge in payload["edges"]["skeleton"]
                if (edge["parent"], edge["child"]) != ("left", "merged")]
        elif kind == "depth":
            node = next(row for row in payload["nodes"] if row["id"] == "merged")
            node["depth"] = 1
        else:
            payload["edges"]["reference"][0]["rationale"] = ""

    rehash_checkpoint(snapshot, mutate)
    with pytest.raises(ValueError):
        frontier_from_openevolve(snapshot)


def test_native_field_and_host_metric_forks_never_rewrite_governed_scores(tmp_path):
    frontier, snapshot = exported_snapshot()
    changed = deepcopy(snapshot.payload)
    program_changed = next(row for row in changed["programs"] if row["id"] == "merged")
    program_changed["metrics"]["combined_score"] = 1e100
    with pytest.raises(ValueError, match="native fields"):
        frontier_from_openevolve(OpenEvolveDatabaseSnapshot(changed))

    # Host-only sampling/display fields may change without changing Frontier state or M9.
    host_only = deepcopy(snapshot.payload)
    row = next(row for row in host_only["programs"] if row["id"] == "merged")
    row["complexity"] = 1e100
    row["diversity"] = 1e100
    restored = frontier_from_openevolve(OpenEvolveDatabaseSnapshot(host_only))
    assert restored.checkpoint() == frontier.checkpoint()

    incumbent = EvalResult("base", "head", [ItemResult("x", 0), ItemResult("y", 1)],
                           combined_score=0.9)
    winner = EvalResult("winner", "head", [ItemResult("x", 1), ItemResult("y", 1)],
                        combined_score=-1e100)
    loser = EvalResult("loser", "head", [ItemResult("x", 0), ItemResult("y", 0)],
                       combined_score=1e100)
    gate = AdmissionGate(AppendOnlyStore(tmp_path / "gate.jsonl"))
    assert gate.evaluate(winner, incumbent)[0].verdict.kind == "ACCEPT"
    assert gate.evaluate(loser, incumbent)[0].verdict.kind == "REJECT"
