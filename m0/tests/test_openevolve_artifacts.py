"""v51 native OpenEvolve external-artifact migration and adversarial checks."""
from copy import deepcopy
import base64
import hashlib
import json
import os
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor" / "openevolve"))

from openevolve.database import ProgramDatabase

from core.openevolve_interop import (
    OpenEvolveArtifactBundle,
    OpenEvolveDatabaseSnapshot,
    export_openevolve_artifacts,
    materialize_openevolve_artifacts,
    read_openevolve_database_with_artifacts,
    write_openevolve_database_with_artifacts,
)
from tests.test_openevolve_interop import config, native_database


class ArtifactCase:
    def __init__(self, root):
        self.root = root
        self.source = root / "source"
        self.source.mkdir()
        self.database = native_database()
        self.database.config.db_path = str(self.source)
        self.database.config.artifacts_base_path = str(self.source / "artifacts")
        self.database.config.artifact_size_threshold = 8
        self.binary = bytes(range(256)) * 2 + b"\x00\xff"
        self.database.store_artifacts("root", {
            "small": "hello", "large.txt": "large-text-" * 20})
        self.database.store_artifacts("left", {"blob.bin": self.binary})
        # A referenced empty directory is part of the native state too.
        empty_dir = self.source / "artifacts" / "right"
        empty_dir.mkdir(parents=True)
        self.database.get("right").artifact_dir = str(empty_dir)
        self.snapshot = OpenEvolveDatabaseSnapshot.from_database(self.database)
        self.bundle = export_openevolve_artifacts(self.snapshot, self.source / "artifacts")

    def config(self):
        return config(artifact_size_threshold=8)


@pytest.fixture
def case(tmp_path):
    return ArtifactCase(tmp_path)


def test_native_text_binary_small_and_empty_artifact_migration(case, tmp_path):
    destination = tmp_path / "migrated"
    relocated = write_openevolve_database_with_artifacts(
        case.snapshot, case.bundle, destination)
    assert relocated.payload != case.snapshot.payload
    for program in relocated.payload["programs"]:
        if program["id"] in {"root", "left", "right"}:
            assert program["artifact_dir"] == str(destination / "artifacts" / program["id"])
    native = ProgramDatabase(case.config())
    native.load(str(destination))
    assert native.get_artifacts("root") == {
        "small": "hello", "large.txt": "large-text-" * 20}
    assert native.get_artifacts("left") == {"blob.bin": case.binary}
    assert native.get_artifacts("right") == {}
    assert (destination / "artifacts" / "right").is_dir()
    reread, bundle = read_openevolve_database_with_artifacts(destination, case.config())
    assert reread.to_bytes() == relocated.to_bytes()
    assert bundle.payload["artifacts"] == case.bundle.payload["artifacts"]
    # Migrated content has no hidden dependency on the old artifact directory.
    import shutil
    shutil.rmtree(case.source)
    assert native.get_artifacts("left")["blob.bin"] == case.binary


def test_artifact_envelope_roundtrip_and_snapshot_binding(case):
    raw = case.bundle.to_bytes()
    decoded = OpenEvolveArtifactBundle.from_bytes(raw, case.snapshot)
    assert decoded.to_bytes() == raw
    changed = deepcopy(case.snapshot.payload)
    changed["programs"][0]["metrics"]["combined_score"] = 12345
    other_snapshot = OpenEvolveDatabaseSnapshot(changed)
    with pytest.raises(ValueError, match="different database snapshot"):
        OpenEvolveArtifactBundle.from_bytes(raw, other_snapshot)


def _canonical_digest(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def test_envelope_tamper_and_rehashed_content_tamper_fail_closed(case):
    envelope = json.loads(case.bundle.to_bytes())
    envelope["payload"]["artifacts"][0]["files"][0]["content_base64"] = "Y2hhbmdlZA=="
    with pytest.raises(ValueError, match="integrity"):
        OpenEvolveArtifactBundle.from_bytes(
            json.dumps(envelope).encode(), case.snapshot)
    envelope["payload_sha256"] = _canonical_digest(envelope["payload"])
    with pytest.raises(ValueError, match="size or SHA256"):
        OpenEvolveArtifactBundle.from_bytes(
            json.dumps(envelope).encode(), case.snapshot)
    with pytest.raises(ValueError, match="unsupported"):
        OpenEvolveArtifactBundle.from_bytes(b'{"schema_version":2}', case.snapshot)


def test_invalid_base64_size_duplicates_and_unsafe_names_fail_closed(case):
    base = case.bundle.payload
    invalid = deepcopy(base)
    invalid["artifacts"][0]["files"][0]["content_base64"] = "not base64!"
    with pytest.raises(ValueError, match="base64"):
        OpenEvolveArtifactBundle(invalid)
    wrong_size = deepcopy(base)
    wrong_size["artifacts"][0]["files"][0]["size"] += 1
    with pytest.raises(ValueError, match="size or SHA256"):
        OpenEvolveArtifactBundle(wrong_size)
    duplicate_file = deepcopy(base)
    entry = duplicate_file["artifacts"][0]
    entry["files"].append(deepcopy(entry["files"][0]))
    with pytest.raises(ValueError, match="duplicate artifact filename"):
        OpenEvolveArtifactBundle(duplicate_file)
    duplicate_program = deepcopy(base)
    duplicate_program["artifacts"].append(deepcopy(duplicate_program["artifacts"][0]))
    with pytest.raises(ValueError, match="duplicate Program artifact"):
        OpenEvolveArtifactBundle(duplicate_program)
    unsafe = deepcopy(base)
    unsafe["artifacts"][0]["files"][0]["name"] = "../escape"
    with pytest.raises(ValueError, match="unsafe"):
        OpenEvolveArtifactBundle(unsafe)


def test_missing_and_extra_bundle_entries_fail_exact_binding(case):
    missing = deepcopy(case.bundle.payload)
    missing["artifacts"].pop()
    with pytest.raises(ValueError, match="exactly match"):
        OpenEvolveArtifactBundle(missing).bind(case.snapshot)
    extra = deepcopy(case.bundle.payload)
    extra["artifacts"].append({"program_id": "leaf", "files": []})
    with pytest.raises(ValueError, match="exactly match"):
        OpenEvolveArtifactBundle(extra).bind(case.snapshot)


def test_export_rejects_missing_directory_and_malformed_small_json(case):
    payload = deepcopy(case.snapshot.payload)
    next(row for row in payload["programs"] if row["id"] == "root")["artifacts_json"] = "{bad"
    with pytest.raises(ValueError, match="small artifacts"):
        export_openevolve_artifacts(OpenEvolveDatabaseSnapshot(payload),
                                    case.source / "artifacts")
    import shutil
    shutil.rmtree(case.source / "artifacts" / "left")
    with pytest.raises(ValueError, match="missing or unsafe"):
        export_openevolve_artifacts(case.snapshot, case.source / "artifacts")


def test_export_rejects_outside_wrong_name_and_nested_paths(case, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    payload = deepcopy(case.snapshot.payload)
    next(row for row in payload["programs"] if row["id"] == "left")["artifact_dir"] = str(outside)
    with pytest.raises(ValueError, match="direct child"):
        export_openevolve_artifacts(OpenEvolveDatabaseSnapshot(payload),
                                    case.source / "artifacts")
    wrong_name = deepcopy(case.snapshot.payload)
    next(row for row in wrong_name["programs"] if row["id"] == "left")["artifact_dir"] = str(
        case.source / "artifacts" / "root")
    with pytest.raises(ValueError, match="direct child"):
        export_openevolve_artifacts(OpenEvolveDatabaseSnapshot(wrong_name),
                                    case.source / "artifacts")
    (case.source / "artifacts" / "left" / "nested").mkdir()
    with pytest.raises(ValueError, match="regular non-symlink files"):
        export_openevolve_artifacts(case.snapshot, case.source / "artifacts")


def test_export_rejects_symlinked_directory_file_and_unsafe_filename(case, tmp_path):
    left = case.source / "artifacts" / "left"
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"secret")
    (left / "blob.bin").unlink()
    os.symlink(outside, left / "blob.bin")
    with pytest.raises(ValueError, match="non-symlink"):
        export_openevolve_artifacts(case.snapshot, case.source / "artifacts")
    (left / "blob.bin").unlink()
    (left / "blob.bin").write_bytes(case.binary)
    (left / "bad name").write_text("x")
    with pytest.raises(ValueError, match="unsafe"):
        export_openevolve_artifacts(case.snapshot, case.source / "artifacts")
    (left / "bad name").unlink()
    os.symlink(case.source / "artifacts" / "root", left / "linked")
    with pytest.raises(ValueError, match="non-symlink"):
        export_openevolve_artifacts(case.snapshot, case.source / "artifacts")


def test_materialize_is_atomic_relocated_and_source_independent(case, tmp_path):
    destination = tmp_path / "materialized"
    relocated = materialize_openevolve_artifacts(case.snapshot, case.bundle, destination)
    native = relocated.to_database()
    assert native.get_artifacts("left")["blob.bin"] == case.binary
    assert native.get_artifacts("root")["large.txt"] == "large-text-" * 20
    with pytest.raises(ValueError, match="must not already exist"):
        materialize_openevolve_artifacts(case.snapshot, case.bundle, destination)
    wrong = deepcopy(case.snapshot.payload)
    wrong["programs"][0]["code"] = "different"
    rejected_root = tmp_path / "rejected"
    with pytest.raises(ValueError, match="different database snapshot"):
        materialize_openevolve_artifacts(OpenEvolveDatabaseSnapshot(wrong), case.bundle,
                                         rejected_root)
    assert not rejected_root.exists()


def test_combined_writer_refuses_overwrite_or_wrong_binding_without_partial_output(case, tmp_path):
    destination = tmp_path / "existing"
    destination.mkdir()
    with pytest.raises(ValueError, match="must not already exist"):
        write_openevolve_database_with_artifacts(case.snapshot, case.bundle, destination)
    changed = deepcopy(case.snapshot.payload)
    changed["programs"][0]["code"] = "different"
    rejected = tmp_path / "rejected"
    with pytest.raises(ValueError, match="different database snapshot"):
        write_openevolve_database_with_artifacts(
            OpenEvolveDatabaseSnapshot(changed), case.bundle, rejected)
    assert not rejected.exists()
    assert not list(tmp_path.glob(".rejected.tmp-*"))


def test_database_without_external_artifacts_reads_empty_bundle(tmp_path):
    database = native_database()
    snapshot = OpenEvolveDatabaseSnapshot.from_database(database)
    bundle = export_openevolve_artifacts(snapshot, tmp_path / "absent")
    assert bundle.payload["artifacts"] == []
    root = tmp_path / "plain"
    relocated = write_openevolve_database_with_artifacts(snapshot, bundle, root)
    reread, empty = read_openevolve_database_with_artifacts(root, config())
    assert reread.to_bytes() == relocated.to_bytes()
    assert empty.payload["artifacts"] == []
