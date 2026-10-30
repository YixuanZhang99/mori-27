"""Population retention, selection pressure and authority-preserving recovery."""
import json
import pytest
from core.executor.types import Candidate, CostVec, EvalResult, EvalStatus, EvidenceRecord
from core.frontier.population import PopulationFrontier, population_options
from core.frontier.research import FrontierCheckpoint, ResearchFrontier, _digest
from core.memory.store import ScopedMemory
from core.policy.types import MutationOp, StateMutation
from core.state import MutationError, StateApplier
from core.x1.store import AppendOnlyStore


def add(frontier, identifier, score, *, parents=(), admitted=False, status=EvalStatus.OK, cycle=0):
    candidate = Candidate(identifier, list(parents), created_cycle=cycle)
    result = EvalResult(status, {frontier.metric: score, "test/hidden": 9999}, CostVec(), fidelity="dev")
    frontier.add(candidate, EvidenceRecord(identifier, result))
    frontier.finalize(identifier, admitted=admitted, reason="actual M9 fixture decision",
        selected_id=identifier if admitted else frontier.protected_id, decision_ref="receipt:" + identifier)
    return candidate


def populated(**options):
    frontier = PopulationFrontier(capacity=3, **options)
    add(frontier, "selected", 1, admitted=True)
    add(frontier, "a", 5, parents=["selected"], cycle=1)
    add(frontier, "b", 10, parents=["selected"], cycle=2)
    return frontier


@pytest.mark.parametrize("change", [{"capacity": 0}, {"capacity": True}, {"retention": "novelty"},
    {"temperature": 0}, {"temperature": float("nan")}, {"selection": "random-magic"},
    {"tournament_size": -1}, {"sample_seed": True}, {"unknown": 1}])
def test_options_reject_invalid_values_and_unimplemented_novelty(change):
    with pytest.raises(ValueError):
        population_options(change)


def test_retention_is_dev_only_and_gate_rejected_valid_candidates_can_be_parents():
    frontier = populated()
    assert frontier.member_ids == ("a", "b", "selected")
    assert frontier.nodes["a"].status == "done" and frontier.nodes["selected"].status == "merged"
    assert frontier.get_best() == "b" and frontier.protected_id == "selected"
    assert frontier.sample(3, "greedy") == ["b", "a", "selected"]


def test_eviction_and_explicit_pruning_preserve_descendants_and_protected_incumbent():
    frontier = PopulationFrontier(capacity=2)
    add(frontier, "selected", 0, admitted=True)
    add(frontier, "parent", 5, parents=["selected"], cycle=1)
    add(frontier, "child", 10, parents=["parent"], cycle=2)
    assert frontier.member_ids == ("child", "selected")
    assert set(frontier.nodes) == {"selected", "parent", "child"}
    assert frontier.nodes["parent"].children_ids == ["child"] and frontier.nodes["child"].depth == 2
    assert frontier.nodes["parent"].status == "done"
    assert frontier.prune("parent", "explicit invalidation") == ["parent"]
    assert frontier.nodes["child"].status == "done" and "child" in frontier.member_ids
    with pytest.raises(ValueError, match="selected"):
        frontier.prune("selected", "capacity pressure")


def test_new_m9_selection_replaces_protection_without_inventing_a_promotion():
    frontier = populated()
    add(frontier, "new", -100, admitted=True, cycle=3)
    assert frontier.protected_id == "new" and frontier.member_ids == ("a", "b", "new")
    frontier.add(Candidate("forged"), EvidenceRecord("forged", EvalResult(EvalStatus.OK, {"dev/score": 20})))
    before = frontier.checkpoint()
    with pytest.raises(ValueError, match="invent"):
        frontier.finalize("forged", admitted=False, reason="not promoted", selected_id="forged", decision_ref="wrong")
    assert frontier.checkpoint() == before


@pytest.mark.parametrize("status", [EvalStatus.INVALID, EvalStatus.FAILED_TO_RUN, EvalStatus.TIMEOUT])
def test_failed_and_invalid_high_scoring_nodes_cannot_be_parents_or_selected(status):
    frontier = populated()
    add(frontier, "invalid", 100000, status=status, cycle=3)
    assert "invalid" not in frontier.member_ids and "invalid" not in frontier.sample(100)
    frontier.add(Candidate("bad-selected"), EvidenceRecord("bad-selected", EvalResult(status, {"dev/score": 1e9})))
    with pytest.raises(ValueError, match="valid"):
        frontier.finalize("bad-selected", admitted=True, reason="wrong", selected_id="bad-selected", decision_ref="wrong")


def test_pending_unfinalized_and_nan_nodes_are_not_sampled():
    frontier = populated()
    frontier.add(Candidate("pending"), None)
    frontier.add(Candidate("unfinalized"), EvidenceRecord("unfinalized", EvalResult(EvalStatus.OK, {"dev/score": 1e9})))
    add(frontier, "nan", float("nan"), cycle=4)
    assert set(frontier.sample(100)) == {"selected", "a", "b"}


def test_elite_ties_use_earlier_cycle_then_id_and_minimize_is_respected():
    frontier = PopulationFrontier(capacity=2, direction="minimize")
    add(frontier, "z", 8, cycle=0)
    add(frontier, "b", 3, cycle=2)
    add(frontier, "a", 3, cycle=1)
    add(frontier, "c", 3, cycle=3)
    assert frontier.member_ids == ("a", "b") and frontier.get_best() == "a"


@pytest.mark.parametrize("strategy", ["uniform", "tournament", "softmax"])
def test_sampling_without_replacement_recovers_the_exact_next_draw(strategy):
    frontier = populated(selection=strategy, sample_seed=18)
    for _ in range(3):
        assert len(set(frontier.sample(2))) == 2
    raw = frontier.checkpoint()
    restored = PopulationFrontier.restore(raw)
    assert restored.checkpoint() == raw
    assert [restored.sample(2) for _ in range(10)] == [frontier.sample(2) for _ in range(10)]
    assert restored.rng_state == frontier.rng_state and restored.checkpoint() == frontier.checkpoint()


def test_tournament_temperature_and_uniform_change_actual_parent_selection():
    tournament = populated(selection="tournament", tournament_size=3)
    assert [tournament.sample(1) for _ in range(20)] == [["b"]] * 20
    cold = populated(selection="softmax", temperature=0.001)
    assert [cold.sample(1) for _ in range(20)] == [["b"]] * 20
    uniform = populated(selection="uniform")
    assert {uniform.sample(1)[0] for _ in range(30)} == {"a", "b", "selected"}


def test_invalid_or_empty_sample_cannot_advance_rng():
    frontier = populated()
    before = frontier.rng_state
    assert frontier.sample(0) == []
    for size, strategy in ((True, "uniform"), (-1, "uniform"), (1, "unknown")):
        with pytest.raises(ValueError):
            frontier.sample(size, strategy)
    assert frontier.rng_state == before and frontier.sampling_receipts == []
    empty = PopulationFrontier()
    assert empty.sample(2) == [] and empty.rng_state == {"counter": 0, "calls": 0}


def test_detached_sampling_commits_by_recomputation_not_arbitrary_state_copy(tmp_path):
    store = AppendOnlyStore(tmp_path / "events.jsonl")
    live = populated(store=store, selection="uniform")
    view = PopulationFrontier.restore(live.checkpoint())
    one, two = view.sample(2), view.sample(1)
    view.nodes["a"].result = {"forged": True}
    accepted = live.commit_sampling(view.sampling_receipts)
    assert live.rng_state == view.rng_state
    assert accepted[0]["selected"] == one and accepted[1]["selected"] == two
    assert "forged" not in live.nodes["a"].result
    with pytest.raises(ValueError, match="authoritative"):
        live.commit_sampling(view.sampling_receipts)
    assert len(list(store.read("population_sampling_committed"))) == 1


def test_budget_excluded_members_are_masked_for_sampling_without_mutating_population():
    live = populated(selection="uniform")
    view = PopulationFrontier.restore(live.checkpoint())
    view.nodes["b"].status = "pruned"
    assert set(view.sample(2)) == {"selected", "a"}
    live.commit_sampling(view.sampling_receipts, allowed_ids={"selected", "a"})
    assert live.nodes["b"].status == "done" and "b" in live.member_ids


def test_driver_checks_actual_returned_parent_ids_before_committing_any_rng():
    live = populated(selection="uniform")
    view = PopulationFrontier.restore(live.checkpoint())
    selected = view.sample(2)
    before = live.rng_state
    for invalid in ([], [selected[0], selected[0]], list(reversed(selected)), ["not-sampled"]):
        with pytest.raises(ValueError):
            live.commit_selection(invalid, view.sampling_receipts)
        assert live.rng_state == before
    live.commit_selection(selected, view.sampling_receipts)
    assert live.rng_state == view.rng_state


@pytest.mark.parametrize("forgery", ["selected", "counter", "score", "member"])
def test_forged_sampling_never_advances_authoritative_rng(forgery):
    live = populated(selection="uniform")
    view = PopulationFrontier.restore(live.checkpoint()); view.sample(2)
    receipts = view.sampling_receipts
    if forgery == "selected": receipts[0]["selected"] = ["selected", "selected"]
    elif forgery == "counter": receipts[0]["after"]["counter"] += 1
    elif forgery == "score": receipts[0]["eligible"][0]["score"] = 9999
    else: receipts[0]["eligible"][0]["id"] = "unknown"
    before = live.checkpoint()
    with pytest.raises(ValueError, match="authoritative"):
        live.commit_sampling(receipts)
    assert live.checkpoint() == before


def test_two_parent_lineage_and_reference_edges_survive_ancestor_eviction():
    frontier = populated(selection="uniform")
    add(frontier, "cross", 100, parents=["a", "b"], cycle=3)
    frontier.add_reference("selected", "cross", "information only")
    assert "a" not in frontier.member_ids
    raw = frontier.checkpoint(); restored = PopulationFrontier.restore(raw)
    assert restored.nodes["cross"].parent_ids == ["a", "b"] and restored.nodes["cross"].depth == 2
    assert restored.nodes["a"].children_ids == restored.nodes["b"].children_ids == ["cross"]
    assert restored.edges == frontier.edges and restored.checkpoint() == raw


@pytest.mark.parametrize("fault", ["members", "protection", "lineage", "rng", "outcome"])
def test_rehashed_invalid_population_snapshot_is_rejected(fault):
    payload = json.loads(populated().checkpoint())["payload"]
    if fault == "members": payload["population"]["members"] = ["a"]
    elif fault == "protection": payload["population"]["protected_id"] = "a"
    elif fault == "lineage": next(n for n in payload["nodes"] if n["id"] == "selected")["children_ids"] = []
    elif fault == "rng": payload["population"]["rng_state"]["counter"] = True
    else: payload["population"]["outcomes"][0]["selected_id"] = "a"
    with pytest.raises(ValueError):
        PopulationFrontier.restore(FrontierCheckpoint(1, payload, _digest(payload)).to_bytes())


def test_state_applier_is_single_writer_and_default_tree_merge_remains_unchanged(tmp_path):
    store = AppendOnlyStore(tmp_path / "state.jsonl"); memory = ScopedMemory(store)
    population = PopulationFrontier(capacity=2, store=store); applier = StateApplier(population, memory, store)
    candidate = Candidate("one"); evidence = EvidenceRecord("one", EvalResult(EvalStatus.OK, {"dev/score": 1}))
    applier.apply(StateMutation(MutationOp.ADD_NODE, "one", {"candidate": candidate, "evidence": evidence}, "dev"))
    applier.apply(StateMutation(MutationOp.POPULATION_FINALIZE, "one", {"admitted": True,
        "reason": "gate", "selected_id": "one", "decision_ref": "receipt-one"}, "driver result"))
    assert population.member_ids == ("one",) and population.protected_id == "one"
    applier.apply(StateMutation(MutationOp.UPDATE_NODE, "one", {"score": 0.5}, "paid dev baseline"))
    assert population.nodes["one"].score == 0.5
    tree = ResearchFrontier(); tree_applier = StateApplier(tree, memory, store)
    tree_applier.apply(StateMutation(MutationOp.ADD_NODE, "one", {"candidate": candidate, "evidence": evidence}, "dev"))
    tree_applier.apply(StateMutation(MutationOp.MERGE, "one", {}, "gate"))
    assert tree.nodes["one"].status == "merged"
    with pytest.raises(MutationError):
        tree_applier.apply(StateMutation(MutationOp.POPULATION_FINALIZE, "one", {}, "wrong topology"))
