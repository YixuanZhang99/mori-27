"""M4 ResearchFrontier edge, projection and portable-checkpoint behavior."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.executor import Candidate, CostVec, EvalResult, EvalStatus, EvidenceRecord
from core.frontier import ResearchFrontier
from core.x1.store import AppendOnlyStore


def candidate(node, parents=()):
    return Candidate(node, parents=list(parents), hypothesis=f"hypothesis:{node}",
                     operator="improve" if parents else "draft")


def evidence(node, score, status=EvalStatus.OK, attempt=1):
    result = EvalResult(status, metrics={"dev/score": score, "test/hidden": -1},
                        cost=CostVec(wall_seconds=2.5), fidelity="dev",
                        uncertainty=0.1, text_feedback=f"feedback:{node}")
    return EvidenceRecord(node, result, f"branch/{node}", "scored", attempt,
                          insight=f"insight:{node}", result_text=f"result:{node}")


def populated(store=None):
    frontier = ResearchFrontier(store=store, sample_seed=17)
    frontier.add(candidate("root"), evidence("root", .5))
    frontier.add(candidate("left", ("root",)), evidence("left", .8))
    frontier.add(candidate("right", ("root",)), evidence("right", .7))
    frontier.add(candidate("child", ("left",)), evidence("child", .9))
    return frontier


def test_skeleton_lineage_best_scopes_and_deterministic_sampling():
    frontier = populated()
    assert frontier.nodes["child"].depth == 2
    assert frontier.nodes["root"].children_ids == ["left", "right"]
    assert frontier.get_best() == "child"
    assert frontier.get_best("right") == "right"
    assert frontier.sample(3, "greedy") == ["child", "left", "right"]
    first = frontier.sample(4, "uniform")
    assert first == frontier.sample(4, "uniform")
    assert set(first) == {"root", "left", "right", "child"}
    assert frontier.nodes["left"].code_ref == "branch/left"
    assert frontier.nodes["left"].cost["wall_seconds"] == 2.5
    assert frontier.nodes["left"].test_score == -1


def test_reference_edges_are_information_only_and_prune_uses_skeleton_only(tmp_path):
    store = AppendOnlyStore(tmp_path / "frontier.jsonl")
    frontier = populated(store)
    before = frontier.sample(4, "uniform")
    frontier.add_reference("right", "left", "reuse analysis only")
    assert frontier.sample(4, "uniform") == before
    assert frontier.get_best() == "child"
    pruned = frontier.prune("left", "held-out regression")
    assert pruned == ["child", "left"]
    assert frontier.nodes["left"].status == frontier.nodes["child"].status == "pruned"
    assert frontier.nodes["right"].status == "done"
    assert frontier.get_best() == "right"
    assert frontier.edges["reference"] == [
        {"source": "right", "target": "left", "rationale": "reuse analysis only"}]
    events = list(store.read("frontier_pruned"))
    assert events[0]["payload"]["hard_deleted"] is False
    assert "PRUNE child: ancestor:left" in frontier.view("constraints")
    assert "| child | pruned | 2 | 0.9 |" in frontier.view("markdown")
    assert '"reference"' in frontier.view("json")


def test_pending_running_completion_and_failed_evidence_are_not_ranked():
    frontier = ResearchFrontier()
    frontier.add(candidate("root"), evidence("root", .5))
    frontier.add(candidate("pending", ("root",)), None)
    assert frontier.get_best() == "root"
    frontier.start("pending")
    assert frontier.nodes["pending"].status == "running"
    frontier.add(candidate("pending", ("root",)), evidence("pending", .8))
    assert frontier.get_best() == "pending"
    frontier.add(candidate("failed", ("root",)),
                 evidence("failed", 100, EvalStatus.FAILED_TO_RUN))
    assert frontier.nodes["failed"].score is None
    assert frontier.get_best() == "pending"
    with pytest.raises(ValueError, match="already materialized"):
        frontier.add(candidate("pending", ("root",)), evidence("pending", .9))
    with pytest.raises(ValueError, match="pending nodes"):
        frontier.start("pending")


def test_checkpoint_roundtrip_preserves_git_inflight_messages_and_can_resume(tmp_path):
    store = AppendOnlyStore(tmp_path / "checkpoint-evidence.jsonl")
    frontier = ResearchFrontier(store=store, git_state={"branch": "run/1", "head": "abc123"},
                                messages=[{"role": "system", "content": "frozen message"}])
    frontier.add(candidate("root"), evidence("root", .5))
    frontier.add(candidate("running", ("root",)), None)
    frontier.start("running")
    frontier.add_reference("root", "running", "context only")
    raw = frontier.checkpoint()
    envelope = json.loads(raw)
    assert envelope["schema_version"] == 1
    assert envelope["payload"]["git_state"]["head"] == "abc123"
    assert envelope["payload"]["inflight_executor"] == ["running"]
    assert envelope["payload"]["messages"][0]["content"] == "frozen message"

    restored = ResearchFrontier.restore(raw, store)
    assert restored.checkpoint() == raw
    assert restored.sample(1, "uniform") == frontier.sample(1, "uniform")
    restored.add(candidate("running", ("root",)), evidence("running", .75))
    assert restored.get_best() == "running"
    assert json.loads(restored.checkpoint())["payload"]["inflight_executor"] == []
    assert len(list(store.read("frontier_restored"))) == 1


def test_checkpoint_integrity_schema_and_lineage_are_validated():
    frontier = populated()
    raw = frontier.checkpoint()
    envelope = json.loads(raw)
    envelope["payload"]["nodes"][0]["score"] = 999
    with pytest.raises(ValueError, match="integrity"):
        ResearchFrontier.restore(json.dumps(envelope).encode())
    unsupported = json.loads(raw)
    unsupported["schema_version"] = 2
    with pytest.raises(ValueError, match="unsupported"):
        ResearchFrontier.restore(json.dumps(unsupported).encode())
    with pytest.raises(ValueError, match="encoding"):
        ResearchFrontier.restore(b"not-json")


def test_minimize_direction_and_invalid_lineage_are_enforced():
    frontier = ResearchFrontier(direction="minimize")
    frontier.add(candidate("root"), evidence("root", 5))
    frontier.add(candidate("better", ("root",)), evidence("better", 3))
    assert frontier.get_best() == "better"
    with pytest.raises(ValueError, match="missing skeleton parents"):
        frontier.add(candidate("orphan", ("absent",)), evidence("orphan", 1))
    with pytest.raises(ValueError, match="does not match"):
        frontier.add(candidate("mismatch", ("root",)), evidence("other", 1))
