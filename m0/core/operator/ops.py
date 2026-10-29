"""M2 operators (M0): draft + reflective improve. LLM proposes; code lands (I-LLM).

The LLM is a plain callable (prompt -> str), so the sync path of M1/M3 never
touches it: operators run on the execution side, after an intent is granted.
"""
from __future__ import annotations

import hashlib
import uuid
from typing import Callable

from core.operator.types import CrossoverContract, OperatorSpec, VariationProposal

LLM = Callable[[str], str]


def draft(llm: LLM, spec: OperatorSpec, task_desc: str,
          proposal_id: str | None = None) -> VariationProposal:
    if not spec.prompt_version:
        raise ValueError("prompt_version required (empty = registration refused)")
    assert spec.kind == "draft"
    text = llm(f"[draft v{spec.prompt_version}] {task_desc}")
    return VariationProposal(proposal_id=proposal_id or uuid.uuid4().hex[:12],
                             parent_ids=[], patch_text=text,
                             apply_result="ok", apply_attempts=1)


def reflective_improve(llm: LLM, spec: OperatorSpec, parent_id: str,
                       parent_prompt: str, eval_text_feedback: str,
                       score: float, proposal_id: str | None = None) -> VariationProposal:
    """GEPA-shaped improve: current prompt + evaluation trajectory text in,
    a rewritten prompt proposal out. S-3/S-4: feedback text is mandatory."""
    if not spec.prompt_version:
        raise ValueError("prompt_version required")
    assert spec.kind == "improve"
    if eval_text_feedback == "":
        raise ValueError("reflective improve requires eval_text_feedback (S-4)")
    prompt = (f"[reflective improve v{spec.prompt_version}]\n"
              f"CURRENT PROMPT:\n{parent_prompt}\n\n"
              f"SCORE: {score}\nEVALUATION TRAJECTORY:\n{eval_text_feedback}\n\n"
              "Rewrite the prompt to fix the observed failures.")
    text = llm(prompt)
    return VariationProposal(proposal_id=proposal_id or uuid.uuid4().hex[:12],
                             parent_ids=[parent_id], patch_text=text,
                             apply_result="ok", apply_attempts=1)


EVOLVE_START = "<EVOLVE-BLOCK>"
EVOLVE_END = "</EVOLVE-BLOCK>"


def _evolve_parts(parent_text: str) -> tuple[str, str, str]:
    if parent_text.count(EVOLVE_START) != 1 or parent_text.count(EVOLVE_END) != 1:
        raise ValueError("parent lacks EVOLVE-BLOCK structural boundaries")
    before, rest = parent_text.split(EVOLVE_START, 1)
    block, after = rest.split(EVOLVE_END, 1)
    return before, block, after


def apply_evolve_block(parent_text: str, proposed_block: str) -> str:
    """Deterministic patcher: only the marked region may change (C5)."""
    before, _, after = _evolve_parts(parent_text)
    # A model may return the markers; strip them before re-wrapping.
    block = proposed_block.replace(EVOLVE_START, "").replace(EVOLVE_END, "").strip()
    if not block:
        raise ValueError("empty evolve block")
    return f"{before}{EVOLVE_START}\n{block}\n{EVOLVE_END}{after}"


def evolve_block_improve(llm: LLM, spec: OperatorSpec, parent_id: str,
                         parent_prompt: str, eval_text_feedback: str,
                         score: float, proposal_id: str | None = None) -> VariationProposal:
    """FunSearch-shaped improve: frozen skeleton, editable block only."""
    if not spec.prompt_version:
        raise ValueError("prompt_version required")
    if not eval_text_feedback:
        raise ValueError("evolve-block improve requires feedback (S-4)")
    prompt = (f"[evolve-block improve v{spec.prompt_version}]\n"
              f"FROZEN SKELETON AND EDITABLE BLOCK:\n{parent_prompt}\n\n"
              f"SCORE: {score}\nEVALUATION TRAJECTORY:\n{eval_text_feedback}\n\n"
              "Rewrite only the content inside EVOLVE-BLOCK.")
    proposed = llm(prompt)
    try:
        patched = apply_evolve_block(parent_prompt, proposed)
        result = "ok"
    except ValueError:
        patched, result = proposed, "failed"
    return VariationProposal(proposal_id=proposal_id or uuid.uuid4().hex[:12],
                             parent_ids=[parent_id], patch_text=patched,
                             apply_result=result, apply_attempts=1)


# ---- Explicit M2 extensions; none are selected by the M0 default loop. ----

def debug(llm: LLM, spec: OperatorSpec, parent_id: str, parent_prompt: str,
          failure_signal: dict) -> VariationProposal:
    """Repair from an environment fact, never from an LLM bugginess judgment."""
    if not spec.prompt_version:
        raise ValueError("prompt_version required")
    if spec.kind != "debug":
        raise ValueError("debug operator requires kind=debug")
    required = {"item_id", "error", "source"}
    if not required.issubset(failure_signal) or failure_signal["source"] != "env_fact":
        raise ValueError("debug requires item_id/error/source=env_fact")
    if not str(failure_signal["error"]).strip():
        raise ValueError("debug requires a non-empty environment error")
    prompt = (f"[debug v{spec.prompt_version}]\n"
              f"BUGGY CANDIDATE:\n{parent_prompt}\n\n"
              f"FAILED ITEM: {failure_signal['item_id']}\n"
              f"ENVIRONMENT ERROR:\n{failure_signal['error']}\n\n"
              "Repair the candidate without changing its public interface.")
    proposed = llm(prompt)
    try:
        patched = (apply_evolve_block(parent_prompt, proposed)
                   if spec.representation == "evolve_block" else proposed.strip())
        if not patched:
            raise ValueError("empty debug patch")
        result = "ok"
    except ValueError:
        patched, result = proposed, "failed"
    return VariationProposal(proposal_id=uuid.uuid4().hex[:12],
                             parent_ids=[parent_id], patch_text=patched,
                             apply_result=result, apply_attempts=1)


def _ordered_parents(parents: tuple[dict, dict], perm_seed: int) -> list[dict]:
    ids = [str(parent.get("candidate_id", "")) for parent in parents]
    if not all(ids) or ids[0] == ids[1] or any("prompt" not in p for p in parents):
        raise ValueError("crossover requires two distinct identified parents")
    # SHA256, rather than process-randomized hash(), makes replay independent of
    # argument order and Python's hash seed while retaining explicit permutation.
    return sorted(parents, key=lambda p: (
        hashlib.sha256(f"{perm_seed}\0{p['candidate_id']}".encode()).hexdigest(),
        p["candidate_id"]))


def crossover(llm: LLM, spec: OperatorSpec, contract: CrossoverContract,
              parents: tuple[dict, dict], perm_seed: int) -> VariationProposal:
    """Deterministically ordered, role-labelled evolve-block composition."""
    if not spec.prompt_version:
        raise ValueError("prompt_version required")
    if spec.kind != "crossover" or spec.representation != "evolve_block":
        raise ValueError("crossover requires kind=crossover and evolve_block representation")
    contract.validate()
    ordered = _ordered_parents(parents, perm_seed)
    base, donor = ordered
    base_parts, donor_parts = _evolve_parts(base["prompt"]), _evolve_parts(donor["prompt"])
    if (base_parts[0], base_parts[2]) != (donor_parts[0], donor_parts[2]):
        raise ValueError("crossover parents have incompatible structural signatures")
    role_text = "\n\n".join(
        f"PARENT ROLE: {role}\nPARENT ID: {parent['candidate_id']}\n{parent['prompt']}"
        for role, parent in zip(contract.role_labels, ordered))
    prompt = (f"[crossover v{spec.prompt_version}; perm_seed={perm_seed}]\n"
              f"{role_text}\n\n"
              "Compose complementary behavior from both parents. Return only the "
              "child EVOLVE-BLOCK content; preserve the shared public signature.")
    proposed = llm(prompt)
    try:
        patched = apply_evolve_block(base["prompt"], proposed)
        result = "ok"
    except ValueError:
        patched, result = proposed, "failed"
    metadata = {
        "n_parents": 2,
        "signature_constraint": contract.signature_constraint,
        "role_labels": list(contract.role_labels),
        "parent_order": [p["candidate_id"] for p in ordered],
        "perm_seed": perm_seed,
        "debug_fallback_required": contract.debug_fallback_required,
    }
    return VariationProposal(proposal_id=uuid.uuid4().hex[:12],
                             parent_ids=[p["candidate_id"] for p in ordered],
                             patch_text=patched, apply_result=result, apply_attempts=1,
                             crossover_meta=metadata)


def crossover_with_debug_fallback(
        llm: LLM, spec: OperatorSpec, debug_spec: OperatorSpec,
        contract: CrossoverContract, parents: tuple[dict, dict], perm_seed: int,
        run_child: Callable[[VariationProposal], dict | None]) -> VariationProposal:
    """Fusion+repair pipeline; run_child returns None or an environment failure."""
    if debug_spec.kind != "debug":
        raise ValueError("crossover fallback requires a debug OperatorSpec")
    child = crossover(llm, spec, contract, parents, perm_seed)
    if child.apply_result in ("ok", "retry_ok"):
        failure = run_child(child)
        repair_base = child.patch_text
    else:
        # A deterministic apply failure is itself an environment fact; the raw
        # model response is not executable, so repair starts from the base parent.
        failure = {"item_id": child.proposal_id,
                   "error": "deterministic crossover apply failed", "source": "env_fact"}
        ordered = _ordered_parents(parents, perm_seed)
        repair_base = ordered[0]["prompt"]
    if failure is None:
        child.crossover_meta = dict(child.crossover_meta or {}, debug_fallback_invoked=False)
        return child
    repaired = debug(llm, debug_spec, child.proposal_id, repair_base, failure)
    repaired.crossover_meta = {
        "debug_fallback_invoked": True,
        "debug_fallback_of": child.proposal_id,
        "crossover_parent_ids": child.parent_ids,
        "perm_seed": perm_seed,
    }
    return repaired
