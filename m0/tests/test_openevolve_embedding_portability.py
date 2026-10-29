"""v55 embedding-backed OpenEvolve state portability with offline test doubles."""
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

from core.openevolve_interop import (OpenEvolveDatabaseSnapshot,
                                     read_openevolve_database,
                                     write_openevolve_database)

VECTORS = {"root = 1": [1.0, 0.0], "other = 2": [0.0, 1.0],
           "similar = 3": [0.9, 0.1], "different = 4": [-1.0, 0.0]}


class OfflineEmbeddingClient:
    calls = []

    def __init__(self, model, api_base=None):
        self.model = model
        self.api_base = api_base

    def get_embedding(self, code):
        self.calls.append(code)
        return list(VECTORS[code])


@pytest.fixture(autouse=True)
def offline_embedding(monkeypatch):
    OfflineEmbeddingClient.calls = []
    monkeypatch.setattr("openevolve.embedding.EmbeddingClient", OfflineEmbeddingClient)
    monkeypatch.setenv("OPENAI_API_KEY", "offline-sentinel-never-serialize")


def config(**overrides):
    values = dict(num_islands=1, population_size=20, archive_size=20,
                  feature_dimensions=["score"], feature_bins=2,
                  embedding_model="offline-embedding-v1",
                  embedding_api_base="http://127.0.0.1:65535/v1",
                  similarity_threshold=0.8)
    values.update(overrides)
    return DatabaseConfig(**values)


def native_database():
    database = ProgramDatabase(config())
    for pid, code, score in (("root", "root = 1", 0.5), ("other", "other = 2", 0.7)):
        assert database.add(Program(pid, code, parent_id="root" if pid == "other" else None,
                                    generation=1 if pid == "other" else 0,
                                    metrics={"combined_score": score}),
                            iteration=0, target_island=0) == pid
    return database


def test_embedding_model_base_and_vectors_roundtrip_exactly_offline():
    database = native_database()
    snapshot = OpenEvolveDatabaseSnapshot.from_database(database)
    restored = snapshot.to_database()
    assert restored.config.embedding_model == "offline-embedding-v1"
    assert restored.config.embedding_api_base == "http://127.0.0.1:65535/v1"
    assert isinstance(restored.embedding_client, OfflineEmbeddingClient)
    assert restored.get("root").embedding == [1.0, 0.0]
    assert restored.get("other").embedding == [0.0, 1.0]
    assert OpenEvolveDatabaseSnapshot.from_database(restored).to_bytes() == snapshot.to_bytes()
    assert b"offline-sentinel-never-serialize" not in snapshot.to_bytes()


def test_native_save_load_and_strict_disk_read_preserve_embedding_state(tmp_path):
    snapshot = OpenEvolveDatabaseSnapshot.from_database(native_database())
    destination = tmp_path / "embedding-db"
    write_openevolve_database(snapshot, destination)
    assert read_openevolve_database(destination, config()).to_bytes() == snapshot.to_bytes()
    native = ProgramDatabase(config())
    native.load(str(destination))
    assert native.get("root").embedding == [1.0, 0.0]
    assert OpenEvolveDatabaseSnapshot.from_database(native).to_bytes() == snapshot.to_bytes()


def test_restored_vectors_drive_native_cosine_and_novelty_without_network():
    restored = OpenEvolveDatabaseSnapshot.from_database(native_database()).to_database()

    class Judge:
        def __init__(self):
            self.calls = 0

        async def generate_with_context(self, **_kwargs):
            self.calls += 1
            return "NOT_NOVEL"

    judge = Judge()
    restored.novelty_llm = judge  # explicit runtime dependency; never serialized
    restored.programs["similar"] = Program("similar", "similar = 3")
    restored.programs["different"] = Program("different", "different = 4")
    assert restored._is_novel("similar", 0) is False
    assert judge.calls == 1
    assert restored._is_novel("different", 0) is True
    assert judge.calls == 1
    assert restored.get("similar").embedding == [0.9, 0.1]


def test_live_novelty_llm_object_remains_outside_portable_state():
    database = ProgramDatabase(config(embedding_model=None, embedding_api_base=None,
                                      novelty_llm=object()))
    with pytest.raises(ValueError, match="live novelty LLM objects"):
        OpenEvolveDatabaseSnapshot.from_database(database)


@pytest.mark.parametrize("overrides", [
    {"embedding_model": " bad-model "},
    {"embedding_model": None},
    {"embedding_api_base": "https://user:secret@example.test/v1"},
    {"embedding_api_base": "https://example.test/v1?api_key=secret"},
    {"embedding_api_base": "file:///tmp/embeddings"},
])
def test_invalid_or_sensitive_embedding_configuration_fails_closed(overrides):
    with pytest.raises(ValueError):
        OpenEvolveDatabaseSnapshot.from_database(ProgramDatabase(config(**overrides)))


@pytest.mark.parametrize("embedding", [[], [1.0, float("nan")], [1.0, True]])
def test_empty_or_invalid_embedding_vectors_fail_closed(embedding):
    payload = OpenEvolveDatabaseSnapshot.from_database(native_database()).payload
    payload["programs"][0]["embedding"] = embedding
    with pytest.raises(ValueError):
        OpenEvolveDatabaseSnapshot(payload)


def test_embedding_dimension_fork_fails_even_in_otherwise_valid_snapshot():
    payload = OpenEvolveDatabaseSnapshot.from_database(native_database()).payload
    payload["programs"][0]["embedding"] = [1.0, 0.0, 0.0]
    with pytest.raises(ValueError, match="consistent dimension"):
        OpenEvolveDatabaseSnapshot(payload)


def test_strict_native_reader_rejects_embedding_tamper(tmp_path):
    snapshot = OpenEvolveDatabaseSnapshot.from_database(native_database())
    destination = tmp_path / "db"
    write_openevolve_database(snapshot, destination)
    path = destination / "programs" / "root.json"
    data = json.loads(path.read_text())
    data["embedding"] = [1.0, 0.0, 0.0]
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="consistent dimension"):
        read_openevolve_database(destination, config())


def test_similarity_threshold_and_disabled_embedding_config_remain_exact():
    disabled = ProgramDatabase(config(embedding_model=None, embedding_api_base=None,
                                      similarity_threshold=0.0))
    disabled.add(Program("root", "root = 1", metrics={"combined_score": 0.5}))
    snapshot = OpenEvolveDatabaseSnapshot.from_database(disabled)
    restored = snapshot.to_database()
    assert restored.embedding_client is None and restored.similarity_threshold == 0.0
    assert restored.get("root").embedding is None
    assert OpenEvolveDatabaseSnapshot.from_database(restored).to_bytes() == snapshot.to_bytes()
