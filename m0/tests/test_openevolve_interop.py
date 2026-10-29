"""v50 real OpenEvolve ProgramDatabase interoperability and fail-closed validation."""
from copy import deepcopy
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
    OpenEvolveInteropEnvelope,
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


def native_database():
    database = ProgramDatabase(config())
    programs = [
        Program("root", "value = 1", changes_description="genesis", generation=0,
                iteration_found=0, metrics={"dev/score": 0.4, "combined_score": 0.4,
                                            "novelty": 0.1},
                metadata={"origin": "fixture"}),
        Program("left", "value = 2", parent_id="root", generation=1,
                iteration_found=1, metrics={"dev/score": 0.7, "combined_score": 0.7,
                                            "novelty": 0.5}),
        Program("right", "value = 3", parent_id="root", generation=1,
                iteration_found=2, metrics={"dev/score": 0.6, "combined_score": 0.6,
                                            "novelty": 0.9}),
        Program("leaf", "value = 4", parent_id="left", generation=2,
                iteration_found=3, metrics={"dev/score": 0.9, "combined_score": 0.9,
                                            "novelty": 0.5}),
    ]
    for program, island in zip(programs, (0, 0, 1, 0)):
        assert database.add(program, iteration=program.iteration_found,
                            target_island=island) == program.id
    database.island_generations = [2, 1]
    database.last_migration_generation = 1
    return database


def test_real_vendored_database_snapshot_roundtrip_and_sampling():
    database = native_database()
    assert "vendor" in str(Path(sys.modules["openevolve.database"].__file__).resolve())
    snapshot = OpenEvolveDatabaseSnapshot.from_database(database)
    assert [row["id"] for row in snapshot.payload["programs"]] == [
        "leaf", "left", "right", "root"]
    restored = snapshot.to_database()
    assert isinstance(restored, ProgramDatabase)
    assert OpenEvolveDatabaseSnapshot.from_database(restored).to_bytes() == snapshot.to_bytes()
    assert restored.get("leaf").parent_id == "left"
    assert restored.get("left").generation == 1
    assert restored.best_program_id == "leaf"
    assert restored.island_generations == [2, 1]
    assert restored.last_migration_generation == 1
    expected_coords = database._calculate_feature_coords(database.get("right"))
    actual_coords = restored._calculate_feature_coords(restored.get("right"))
    assert actual_coords == expected_coords
    # Historical cells are preserved exactly; OpenEvolve does not re-bin old elites.
    assert restored.island_feature_maps == database.island_feature_maps
    parent, inspirations = restored.sample_from_island(0, num_inspirations=2)
    assert parent.id in restored.islands[0]
    assert all(item.id in restored.programs for item in inspirations)


def test_scalar_bins_and_scaling_mode_roundtrip():
    database = ProgramDatabase(config(feature_dimensions=["score"], feature_bins=2))
    database.feature_scaling_method = "percentile"
    database.add(Program("root", "x = 1", metrics={"combined_score": 0.5}))
    snapshot = OpenEvolveDatabaseSnapshot.from_database(database)
    restored = snapshot.to_database()
    assert restored.feature_scaling_method == "percentile"
    assert restored.feature_bins == database.feature_bins >= 2
    assert OpenEvolveDatabaseSnapshot.from_database(restored).to_bytes() == snapshot.to_bytes()


def test_portable_envelope_is_exact_and_integrity_checked():
    snapshot = OpenEvolveDatabaseSnapshot.from_database(native_database())
    raw = snapshot.to_bytes()
    assert OpenEvolveDatabaseSnapshot.from_bytes(raw).to_bytes() == raw
    envelope = OpenEvolveInteropEnvelope.from_bytes(raw)
    assert envelope.schema_version == 1
    decoded = json.loads(raw)
    decoded["payload"]["programs"][0]["code"] = "tampered = True"
    with pytest.raises(ValueError, match="integrity"):
        OpenEvolveDatabaseSnapshot.from_bytes(json.dumps(decoded).encode())
    with pytest.raises(ValueError, match="unsupported"):
        OpenEvolveDatabaseSnapshot.from_bytes(b'{"schema_version":2}')
    with pytest.raises(ValueError, match="duplicate JSON object key"):
        OpenEvolveDatabaseSnapshot.from_bytes(
            b'{"schema_version":1,"schema_version":1,"payload":{},"payload_sha256":"x"}')
    with pytest.raises(ValueError, match="encoding"):
        OpenEvolveDatabaseSnapshot.from_bytes(b"\xff")


def test_native_disk_save_load_preserves_complete_state_and_refuses_overwrite(tmp_path):
    snapshot = OpenEvolveDatabaseSnapshot.from_database(native_database())
    destination = tmp_path / "native-db"
    write_openevolve_database(snapshot, destination)
    assert read_openevolve_database(destination, config()).to_bytes() == snapshot.to_bytes()
    # Exercise OpenEvolve's own loader as well as the strict adapter reader.
    native = ProgramDatabase(config())
    native.load(str(destination))
    assert OpenEvolveDatabaseSnapshot.from_database(native).to_bytes() == snapshot.to_bytes()
    assert native.get("leaf").code == "value = 4"
    with pytest.raises(ValueError, match="must not already exist"):
        write_openevolve_database(snapshot, destination)


@pytest.mark.parametrize("value", [True, float("nan"), float("inf"), "0.9"])
def test_non_finite_or_non_numeric_metrics_fail_closed(value):
    payload = OpenEvolveDatabaseSnapshot.from_database(native_database()).payload
    payload["programs"][0]["metrics"]["dev/score"] = value
    with pytest.raises(ValueError, match="metrics"):
        OpenEvolveDatabaseSnapshot(payload)


def test_duplicate_missing_parent_generation_and_unknown_program_fields_fail_closed():
    original = OpenEvolveDatabaseSnapshot.from_database(native_database()).payload
    duplicate = deepcopy(original)
    duplicate["programs"].append(deepcopy(duplicate["programs"][0]))
    with pytest.raises(ValueError, match="duplicate Program id"):
        OpenEvolveDatabaseSnapshot(duplicate)
    missing = deepcopy(original)
    next(row for row in missing["programs"] if row["id"] == "left")["parent_id"] = "absent"
    with pytest.raises(ValueError, match="unknown or invalid parent"):
        OpenEvolveDatabaseSnapshot(missing)
    generation = deepcopy(original)
    next(row for row in generation["programs"] if row["id"] == "left")["generation"] = 0
    with pytest.raises(ValueError, match="child generation"):
        OpenEvolveDatabaseSnapshot(generation)
    unknown = deepcopy(original)
    unknown["programs"][0]["future_unvalidated_field"] = 1
    with pytest.raises(ValueError, match="Program schema"):
        OpenEvolveDatabaseSnapshot(unknown)


def _state_case(name, mutate):
    payload = OpenEvolveDatabaseSnapshot.from_database(native_database()).payload
    mutate(payload["state"])
    with pytest.raises(ValueError):
        OpenEvolveDatabaseSnapshot(payload)


def test_dangling_duplicate_and_inconsistent_database_state_fail_closed():
    _state_case("archive", lambda state: state["archive"].append("absent"))
    _state_case("best", lambda state: state.__setitem__("best_program_id", "absent"))
    _state_case("island-best", lambda state: state["island_best_programs"].__setitem__(0, "right"))
    _state_case("duplicate-member", lambda state: state["islands"][0].append("root"))
    _state_case("multi-island", lambda state: state["islands"][1].append("root"))
    _state_case("grid-reference", lambda state: state["island_feature_maps"][0].__setitem__("0-0", "absent"))
    _state_case("grid-island", lambda state: state["island_feature_maps"][0].__setitem__("0-0", "right"))
    _state_case("grid-schema", lambda state: state["island_feature_maps"][0].__setitem__("0", "root"))
    _state_case("grid-range", lambda state: state["island_feature_maps"][0].__setitem__("99-0", "root"))
    _state_case("generations", lambda state: state.__setitem__("island_generations", [0]))
    _state_case("stats", lambda state: state["feature_stats"].__setitem__("score", {"min": 2, "max": 1, "values": []}))


def test_program_island_metadata_must_match_membership():
    payload = OpenEvolveDatabaseSnapshot.from_database(native_database()).payload
    root = next(row for row in payload["programs"] if row["id"] == "root")
    root["metadata"]["island"] = 1
    with pytest.raises(ValueError, match="island metadata"):
        OpenEvolveDatabaseSnapshot(payload)


def _write_native(tmp_path):
    snapshot = OpenEvolveDatabaseSnapshot.from_database(native_database())
    path = tmp_path / "db"
    write_openevolve_database(snapshot, path)
    return path


def test_strict_disk_reader_rejects_malformed_duplicate_and_dangling_native_state(tmp_path):
    malformed = _write_native(tmp_path / "malformed")
    (malformed / "programs" / "root.json").write_text("not-json")
    with pytest.raises(ValueError, match="JSON"):
        read_openevolve_database(malformed, config())

    duplicate = _write_native(tmp_path / "duplicate")
    data = json.loads((duplicate / "programs" / "root.json").read_text())
    (duplicate / "programs" / "alias.json").write_text(json.dumps(data))
    with pytest.raises(ValueError, match="filename|duplicate"):
        read_openevolve_database(duplicate, config())

    dangling = _write_native(tmp_path / "dangling")
    metadata_path = dangling / "metadata.json"
    metadata = json.loads(metadata_path.read_text())
    metadata["archive"].append("missing")
    metadata_path.write_text(json.dumps(metadata))
    with pytest.raises(ValueError, match="archive"):
        read_openevolve_database(dangling, config())

    mismatch = _write_native(tmp_path / "mismatch")
    with pytest.raises(ValueError, match="island count"):
        read_openevolve_database(mismatch, config(num_islands=3))


def _candidate(node, parents=()):
    return Candidate(node, parents=list(parents), hypothesis=f"hypothesis:{node}",
                     operator="improve" if parents else "draft", created_cycle=len(node))


def _evidence(node, score, status=EvalStatus.OK):
    return EvidenceRecord(node, ExecutorResult(
        status, metrics={"dev/score": score, "combined_score": score, "novelty": score / 10},
        cost=CostVec(wall_seconds=1.25), text_feedback=f"feedback:{node}"),
        branch_ref=f"branch/{node}", insight=f"insight:{node}")


def governed_frontier():
    frontier = ResearchFrontier()
    frontier.add(_candidate("root"), _evidence("root", 0.4))
    frontier.add(_candidate("left", ("root",)), _evidence("left", 0.8))
    frontier.add(_candidate("right", ("root",)), _evidence("right", 0.6))
    return frontier


def test_frontier_export_preserves_lineage_code_metrics_and_governance_metadata():
    frontier = governed_frontier()
    codes = {node: f"prompt = '{node}'" for node in frontier.nodes}
    database = frontier_to_openevolve(frontier, codes, config(),
                                      island_by_id={"root": 0, "left": 0, "right": 1})
    snapshot = OpenEvolveDatabaseSnapshot.from_database(database)
    assert set(database.programs) == set(frontier.nodes)
    assert database.get("left").parent_id == "root"
    assert database.get("left").generation == frontier.nodes["left"].depth == 1
    assert database.get("left").code == codes["left"]
    assert database.get("left").metrics["dev/score"] == 0.8
    metadata = database.get("left").metadata
    assert metadata["operator"] == "improve"
    assert metadata["code_ref"] == "branch/left"
    assert metadata["cost"]["wall_seconds"] == 1.25
    assert metadata["host_metrics_not_m9_evidence"] is True
    assert database.get("right").metadata["island"] == 1
    assert snapshot.to_database().sample(1)[0].id in database.programs


def test_frontier_export_rejects_lossy_or_incomplete_sources():
    frontier = governed_frontier()
    frontier.add(_candidate("merged", ("left", "right")), None)
    with pytest.raises(ValueError, match="completed OK"):
        frontier_to_openevolve(frontier, {node: node for node in frontier.nodes}, config())
    incomplete = governed_frontier()
    incomplete.add(_candidate("pending", ("left",)), None)
    with pytest.raises(ValueError, match="completed OK"):
        frontier_to_openevolve(incomplete, {node: node for node in incomplete.nodes}, config())
    with pytest.raises(ValueError, match="population cap"):
        frontier_to_openevolve(governed_frontier(), {"root": "r", "left": "l", "right": "r2"},
                               config(population_size=2))


def test_host_metric_mutation_does_not_change_m9_flip_verdict(tmp_path):
    # Native host metrics remain snapshot/display data; M9 still sees only per-item flips.
    snapshot = OpenEvolveDatabaseSnapshot.from_database(native_database())
    changed = deepcopy(snapshot.payload)
    for program in changed["programs"]:
        program["metrics"]["combined_score"] = 1e100
        program["metrics"]["novelty"] = 0.0
    changed_snapshot = OpenEvolveDatabaseSnapshot(changed)
    assert changed_snapshot.payload != snapshot.payload
    incumbent = EvalResult("base", "head", [ItemResult("x", 0), ItemResult("y", 1)],
                           combined_score=0.9)
    winner = EvalResult("winner", "head", [ItemResult("x", 1), ItemResult("y", 1)],
                        combined_score=-1e100, public={"features": {"novelty": 1.0}})
    loser = EvalResult("loser", "head", [ItemResult("x", 0), ItemResult("y", 0)],
                       combined_score=1e100, public={"features": {"novelty": 0.0}})
    gate = AdmissionGate(AppendOnlyStore(tmp_path / "gate.jsonl"))
    assert gate.evaluate(winner, incumbent)[0].verdict.kind == "ACCEPT"
    assert gate.evaluate(loser, incumbent)[0].verdict.kind == "REJECT"
    evidence = gate.evaluate(winner, incumbent)[1]
    assert set(evidence.signals_snapshot) == {"F", "B", "N", "noise_floor"}
