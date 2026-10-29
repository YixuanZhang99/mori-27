"""M2 debug/crossover contracts: deterministic structure and real fallback behavior."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.operator.ops import (EVOLVE_END, EVOLVE_START, crossover,
                               crossover_with_debug_fallback, debug)
from core.operator.types import CrossoverContract, OperatorSpec


def block(body, head="HEAD\n", tail="\nTAIL"):
    return f"{head}{EVOLVE_START}\n{body}\n{EVOLVE_END}{tail}"


def parent(cid, body="old", **kwargs):
    return {"candidate_id": cid, "prompt": block(body, **kwargs)}


def test_debug_consumes_environment_facts_and_preserves_structure():
    prompts = []
    spec = OperatorSpec("dbg", "debug", "v1", representation="evolve_block")

    def llm(prompt):
        prompts.append(prompt)
        return "repaired"

    proposal = debug(llm, spec, "p1", block("bug"), {
        "item_id": "case-7", "error": "AssertionError: expected 4", "source": "env_fact"})
    assert proposal.apply_result == "ok"
    assert proposal.parent_ids == ["p1"]
    assert proposal.patch_text == block("repaired")
    assert "case-7" in prompts[0] and "AssertionError" in prompts[0]
    assert "SCORE" not in prompts[0] and "combined_score" not in prompts[0]
    with pytest.raises(ValueError, match="env_fact"):
        debug(llm, spec, "p1", block("bug"), {
            "item_id": "case-7", "error": "looks bad", "source": "llm_judgment"})


def test_crossover_order_roles_and_patch_are_replay_deterministic():
    spec = OperatorSpec("xo", "crossover", "v2", representation="evolve_block")
    contract = CrossoverContract()
    prompts = []

    def llm(prompt):
        prompts.append(prompt)
        return "composed"

    first = crossover(llm, spec, contract, (parent("a"), parent("b")), perm_seed=17)
    second = crossover(llm, spec, contract, (parent("b"), parent("a")), perm_seed=17)
    assert prompts[0] == prompts[1]
    assert first.patch_text == second.patch_text == block("composed")
    assert first.parent_ids == second.parent_ids
    assert first.crossover_meta == second.crossover_meta
    assert first.crossover_meta["n_parents"] == 2
    assert first.crossover_meta["parent_order"] == first.parent_ids
    assert first.crossover_meta["perm_seed"] == 17
    assert set(first.crossover_meta["role_labels"]) == {"base", "donor"}


def test_crossover_refuses_incomplete_contract_and_incompatible_signature():
    spec = OperatorSpec("xo", "crossover", "v2", representation="evolve_block")
    with pytest.raises(ValueError, match="requires signature"):
        crossover(lambda p: "x", spec,
                  CrossoverContract(signature_constraint=False),
                  (parent("a"), parent("b")), 0)
    calls = []
    with pytest.raises(ValueError, match="incompatible"):
        crossover(lambda p: calls.append(p) or "x", spec, CrossoverContract(),
                  (parent("a"), parent("b", head="OTHER\n")), 0)
    assert calls == []


def test_runtime_failure_invokes_debug_fallback_and_preserves_crossover_lineage():
    spec = OperatorSpec("xo", "crossover", "v2", representation="evolve_block")
    repair = OperatorSpec("dbg", "debug", "v3", representation="evolve_block")
    stages = []

    def llm(prompt):
        stage = "debug" if prompt.startswith("[debug") else "crossover"
        stages.append(stage)
        return "repaired" if stage == "debug" else "composed"

    executed = []

    def run_child(proposal):
        executed.append(proposal.proposal_id)
        return {"item_id": "case-9", "error": "TimeoutExpired", "source": "env_fact"}

    result = crossover_with_debug_fallback(
        llm, spec, repair, CrossoverContract(), (parent("a"), parent("b")), 3, run_child)
    assert stages == ["crossover", "debug"] and len(executed) == 1
    assert result.apply_result == "ok" and result.patch_text == block("repaired")
    assert len(result.crossover_meta["crossover_parent_ids"]) == 2
    assert result.crossover_meta["debug_fallback_of"] == executed[0]


def test_apply_failure_takes_debug_path_without_executing_invalid_child():
    spec = OperatorSpec("xo", "crossover", "v2", representation="evolve_block")
    repair = OperatorSpec("dbg", "debug", "v3", representation="evolve_block")

    def llm(prompt):
        return "fixed" if prompt.startswith("[debug") else ""

    result = crossover_with_debug_fallback(
        llm, spec, repair, CrossoverContract(), (parent("a"), parent("b")), 3,
        lambda proposal: pytest.fail("invalid child must not execute"))
    assert result.apply_result == "ok"
    assert result.patch_text == block("fixed")
    assert result.crossover_meta["debug_fallback_invoked"] is True
