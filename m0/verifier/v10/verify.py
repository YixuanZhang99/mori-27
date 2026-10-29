#!/usr/bin/env python3
"""Verifier v10: v9 plus M1 absorb and serial StateMutation behavior."""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import tempfile
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.executor import Candidate, EvalResult, EvalStatus, EvidenceRecord
from core.frontier import ResearchFrontier
from core.memory import MemoryEntry, ScopeContext, ScopedMemory
from core.memory.types import Payload, Provenance, TimeMeta
from core.policy import BestFirstPolicy, MutationOp, StateMutation
from core.state import StateApplier
from core.x1.store import AppendOnlyStore

CTX = ScopeContext("run-v10", "task-v10", "domain-v10")


def evidence(node="c1", status=EvalStatus.OK, executor="scored"):
    return EvidenceRecord(node, EvalResult(status, {"dev/score": .75},
                                           text_feedback="feedback"),
                          f"branch/{node}", executor, 2,
                          insight="distilled", result_text="raw result")


def fixture(root):
    store = AppendOnlyStore(root / "state.jsonl")
    frontier = ResearchFrontier(store=store)
    memory = ScopedMemory(store)
    return frontier, memory, StateApplier(frontier, memory, store), store


def check_absorb(root):
    frontier, memory, applier, _ = fixture(root)
    ev = evidence()
    applier.apply(StateMutation(MutationOp.ADD_NODE, "c1",
                                {"candidate": Candidate("c1"), "evidence": ev}, "add"))
    mutations = asyncio.run(BestFirstPolicy(CTX).absorb(ev))
    applier.apply_all(mutations)
    entry = memory.entries[mutations[1].target]
    failed = evidence("failed", EvalStatus.FAILED_TO_RUN, "failed_to_run")
    applier.apply(StateMutation(MutationOp.ADD_NODE, "failed",
                                {"candidate": Candidate("failed"), "evidence": failed}, "add"))
    failed_mutations = asyncio.run(BestFirstPolicy(CTX).absorb(failed))
    applier.apply_all(failed_mutations)
    failed_entry = memory.entries[failed_mutations[1].target]
    passed = ([mutation.op for mutation in mutations] == [
                  MutationOp.UPDATE_NODE, MutationOp.WRITE_MEMORY, MutationOp.PROMOTE_MEMORY]
              and entry.level == "L2" and entry.state == "active"
              and "raw result" in entry.payload.body and "distilled" in entry.payload.body
              and frontier.nodes["c1"].insight == "distilled"
              and len(failed_mutations) == 2 and failed_entry.level == "L1"
              and failed_entry.state == "candidate"
              and failed_entry.provenance.trust_tier == "ungated")
    return passed, {"ok_ops": [mutation.op.value for mutation in mutations],
                    "ok_level": entry.level, "ok_state": entry.state,
                    "failed_level": failed_entry.level,
                    "failed_state": failed_entry.state,
                    "failed_trust": failed_entry.provenance.trust_tier,
                    "legacy_m0_main_loop_migrated": False}


def check_guards(root):
    frontier, memory, applier, store = fixture(root)
    applier.apply(StateMutation(MutationOp.ADD_NODE, "c1",
                                {"candidate": Candidate("c1"), "evidence": evidence()}, "add"))
    before = frontier.checkpoint()
    refusals = []
    for mutation in (
            StateMutation(MutationOp.UPDATE_NODE, "c1", {"insight": "x"}, ""),
            StateMutation(MutationOp.UPDATE_NODE, "c1", {"parent_ids": ["x"]}, "illegal")):
        try:
            applier.apply(mutation)
            refusals.append(False)
        except ValueError:
            refusals.append(True)
    entry = MemoryEntry("raw", Payload("text", "original"), Provenance("run-v10"),
                        TimeMeta(created_at=1), CTX, level="L1")
    applier.apply(StateMutation(MutationOp.WRITE_MEMORY, "raw",
                                {"entry": entry, "at": 1}, "write"))
    try:
        applier.apply(StateMutation(MutationOp.PROMOTE_MEMORY, "raw",
                                    {"target_level": "L2", "delta": {"body": "replace"}},
                                    "replace"))
        refusals.append(False)
    except Exception:
        refusals.append(True)
    applier.apply(StateMutation(MutationOp.MERGE, "c1", {}, "admission approved"))
    merged = frontier.nodes["c1"].status
    applier.apply(StateMutation(MutationOp.PRUNE, "c1", {}, "regression"))
    passed = (all(refusals) and frontier.checkpoint() != before
              and memory.entries["raw"].payload.body == "original"
              and memory.entries["raw"].level == "L1" and merged == "merged"
              and frontier.nodes["c1"].status == "pruned" and "c1" in frontier.nodes
              and len(list(store.read("state_mutation_rejected"))) == 3)
    return passed, {"guard_refusals": refusals, "memory_body_preserved": True,
                    "merged_status": merged, "pruned_status": frontier.nodes["c1"].status,
                    "rejected_receipts": 3}


def check_serial(root):
    _, memory, applier, store = fixture(root)

    def write(index):
        entry = MemoryEntry(f"m{index}", Payload("text", f"lesson {index}"),
                            Provenance("run-v10"), TimeMeta(created_at=1), CTX)
        applier.apply(StateMutation(MutationOp.WRITE_MEMORY, entry.id,
                                    {"entry": entry, "at": 1}, f"write {index}"))

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(write, range(24)))
    sequences = sorted(record["payload"]["seq"] for record in store.read("memory_evidence"))
    receipts = len(list(store.read("state_mutation")))
    passed = len(memory.entries) == 24 and receipts == 24 and sequences == list(range(1, 25))
    return passed, {"memory_entries": len(memory.entries), "mutation_receipts": receipts,
                    "sequence_first_last": [sequences[0], sequences[-1]],
                    "unique_sequences": len(set(sequences))}


def check_tests(_root):
    proc = subprocess.run([sys.executable, "-m", "pytest", "-q",
                           "tests/test_state_mutation.py"], cwd=ROOT,
                          text=True, capture_output=True)
    return proc.returncode == 0, {"exit_code": proc.returncode,
                                  "output": (proc.stdout + proc.stderr)[-2000:]}


def check_ci(_root):
    text = (ROOT / ".github/workflows/axioms.yml").read_text()
    commands = ["python3 -m pytest -q"] + [
        f"python3 verifier/{version}/verify.py"
        for version in ("v5", "v6", "v7", "v8", "v9", "v10")]
    present = [command for command in commands if command in text]
    return len(present) == len(commands), {"commands_present": present,
                                           "hosted_ci_executed": False}


def main():
    checks, values = {}, {}
    v9 = subprocess.run([sys.executable, "verifier/v9/verify.py"], cwd=ROOT,
                        text=True, capture_output=True)
    checks["v9_complete"] = v9.returncode == 0
    values["v9_exit"] = v9.returncode
    if v9.returncode:
        values["v9_stderr"] = v9.stderr[-2000:]
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        for name, fn in (("absorb_lifecycle", check_absorb),
                         ("mutation_whitelist_and_merge", check_guards),
                         ("serial_write_integrity", check_serial),
                         ("state_mutation_contract_tests", check_tests),
                         ("ci_workflow_wiring", check_ci)):
            try:
                checks[name], values[name] = fn(root / name)
            except Exception as exc:
                checks[name] = False
                values[name] = {"error": str(exc), "traceback": traceback.format_exc()}
    passed = all(checks.values())
    record = {"timestamp": datetime.now(timezone.utc).isoformat(),
              "command": "python3 verifier/v10/verify.py", "version": "v10",
              "exit_code": 0 if passed else 1, "checks": checks, "values": values,
              "external_benchmark_execution": {"executed": False, "scores_produced": False}}
    with (ROOT / "verifier/runs/v10.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    print(json.dumps(record, ensure_ascii=False, indent=2, default=str))
    return record["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
