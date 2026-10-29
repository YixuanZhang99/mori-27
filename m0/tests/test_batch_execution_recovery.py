"""v18 real owner-crash recovery from detached execution through batch admission."""
import asyncio
import json
import os
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.budget.ledger import BudgetLedger
from core.budget.types import AccountingStamp
from core.eval.decision import AdmissionDecision
from core.executor import (Candidate, EvalRequest, EvalStatus, ExecutorPool, ExecutorSpec,
                           GitWorktree, GitWorktreeExecutor)
from core.frontier import ResearchFrontier
from core.memory import ScopeContext, ScopedMemory
from core.orchestration import BatchScheduler
from core.policy import BestFirstPolicy, MutationOp, StateMutation
from core.policy.types import AllocationIntent
from core.state import StateApplier
from core.tasks.adapter import EvalContract, FidelityLevel
from core.x1.store import AppendOnlyStore

PROJECT = Path(__file__).resolve().parents[1]
IDS = ["batch-win", "batch-loss"]
STAMP = AccountingStamp("offline", "batch-recovery-v18", "tokens", "prices", "2026-10-26")


def git(repo, *args):
    return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()


def make_repo(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir()
    git(repo, "init", "--quiet")
    git(repo, "config", "user.email", "tests@example.invalid")
    git(repo, "config", "user.name", "Batch Recovery Tests")
    (repo / "solution.py").write_text("VALUE = 0\n")
    (repo / "eval.py").write_text('''import json, pathlib, time
root = pathlib.Path(__file__).parent
candidate = json.loads((root / "candidate.json").read_text())
time.sleep(2)
wins, losses = ((2, 1) if candidate["id"] == "batch-win" else (1, 2))
(root / "submission.csv").write_text("id,prediction\\n1,1\\n")
(root / "metrics.json").write_text(json.dumps({
    "dev/score": 0.1 if wins > losses else 0.99,
    "admission/flip_wins": wins, "admission/flip_losses": losses}))
''')
    git(repo, "add", "-A")
    git(repo, "commit", "--quiet", "-m", "base")
    return repo


def contract() -> EvalContract:
    return EvalContract(
        metric_direction="maximize", eval_cmd=f"{sys.executable} {{cwd}}/eval.py",
        fidelity_levels=(FidelityLevel("dev", {"eval_count": 1}, 1, "exploration"),),
        required_outputs=("submission.csv",), protected_paths=("eval.py",))


def builder(candidate, root):
    (root / "candidate.json").write_text(json.dumps({"id": candidate.id}))


def forbidden_builder(candidate, root):
    raise AssertionError("batch recovery attempted to rebuild/re-execute")


def candidates():
    return [Candidate(node, hypothesis="h", operator="improve") for node in IDS]


def intents():
    return [AllocationIntent(f"v18-{node}", "batch-v18", node, 10,
                             snapshot_ref="v18-cohort", account="exploit")
            for node in IDS]


def admission(candidate, evidence):
    admit = (evidence.eval_result.status is EvalStatus.OK
             and evidence.eval_result.metrics["admission/flip_wins"]
             > evidence.eval_result.metrics["admission/flip_losses"])
    return AdmissionDecision(admit, [StateMutation(
        MutationOp.MERGE if admit else MutationOp.PRUNE, candidate.id, {},
        "v18 recovered flip-only admission")])


def components(repo: Path, store: AppendOnlyStore, recover=False):
    ledger = BudgetLedger(1000, 0.05, 10, STAMP, store)
    frontier = ResearchFrontier(store=store)
    memory = ScopedMemory(store)
    policy = BestFirstPolicy(ScopeContext("v18-run", "task", "domain"))
    executor = GitWorktreeExecutor(contract(), forbidden_builder if recover else builder,
                                   store)
    pool = ExecutorPool(executor, 2, store)
    scheduler = BatchScheduler(pool, ledger, policy,
                               StateApplier(frontier, memory, store), store)
    return scheduler, pool, ledger, frontier, memory


def owner_main(repo: Path, store_path: Path, worktrees: Path) -> None:
    scheduler, _, _, _, _ = components(repo, AppendOnlyStore(store_path))
    workspace = GitWorktree(repo, worktrees)
    asyncio.run(scheduler.run(
        [ExecutorSpec(hypothesis="h") for _ in IDS], candidates(), workspace,
        [EvalRequest("dev", time_limit=30, seed_set=[18]) for _ in IDS],
        intents(), admission))


def test_real_batch_owner_crash_recovers_settles_and_admits_exactly_once(tmp_path):
    repo = make_repo(tmp_path)
    store_path, worktrees = tmp_path / "evidence.jsonl", tmp_path / "worktrees"
    owner = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--owner",
                              str(repo), str(store_path), str(worktrees)],
                             cwd=PROJECT, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True)
    store = AppendOnlyStore(store_path)
    deadline = time.monotonic() + 10
    started = []
    while len(started) < 2 and time.monotonic() < deadline:
        started = list(store.read("executor_process_started"))
        time.sleep(0.02)
    assert len(started) == 2
    execution_refs = {record["payload"].get("execution_ref") for record in started}
    assert len(execution_refs) == 1 and None not in execution_refs
    owner.kill()
    owner.wait(timeout=5)

    scheduler, pool, ledger, frontier, memory = components(repo, store, recover=True)
    workspace = GitWorktree(repo, worktrees)
    assert scheduler.recovery_state()["status"] == "execution_incomplete"
    with pytest.raises(RuntimeError, match="execution_pending"):
        asyncio.run(scheduler.resume(admission, workspace))
    assert list(store.read("batch_admission")) == []
    deadline = time.monotonic() + 10
    while True:
        try:
            results = asyncio.run(scheduler.resume(admission, workspace))
            break
        except RuntimeError as exc:
            if "execution_pending" not in str(exc) or time.monotonic() >= deadline:
                raise
            time.sleep(0.05)
    assert [result.candidate_id for result in results] == IDS
    assert [frontier.nodes[node].status for node in IDS] == ["merged", "pruned"]
    assert len(memory.entries) == 2 and scheduler.last_admissions == {
        "batch-win": True, "batch-loss": False}
    assert ledger.spent["exploit"] == 0 and not ledger.reserves
    assert len(ledger.settled_intents) == 2
    settled = list(store.read("batch_execution_settled"))
    assert len(settled) == 2 and all(record["payload"].get("recovered") for record in settled)
    assert len(list(store.read("executor_process_started"))) == 2
    assert len(list(store.read("executor_evidence"))) == 2
    assert len(list(store.read("batch_cycle_completed"))) == 1
    assert not list(worktrees.iterdir())
    assert scheduler.recovery_state()["status"] == "completed"
    before = list(store.read())
    repeated = asyncio.run(scheduler.resume(admission, workspace))
    assert [asdict(item) for item in repeated] == [asdict(item) for item in results]
    assert list(store.read()) == before
    pool.close()


def test_partial_or_released_accounting_is_ambiguous(tmp_path):
    store = AppendOnlyStore(tmp_path / "evidence.jsonl")
    scheduler, pool, ledger, frontier, memory = components(tmp_path, store)
    cohort_id = "partial-accounting"
    batch = intents()
    store.append("batch_cycle_started", {
        "cohort_id": cohort_id, "candidate_ids": IDS,
        "intent_ids": [intent.intent_id for intent in batch],
        "candidates": [asdict(candidate) for candidate in candidates()],
        "intents": [asdict(intent) for intent in batch]})
    for intent in batch:
        assert ledger.quote_reserve(intent).verdict == "granted"
    ledger.settle(batch[0], actual_cost=1)
    state = scheduler.recovery_state()
    assert state["status"] == "accounting_ambiguous"
    assert state["accounting_ambiguous_candidates"] == [IDS[0]]
    with pytest.raises(RuntimeError, match="accounting_ambiguous"):
        asyncio.run(scheduler.resume(admission))
    assert not frontier.nodes and len(memory.entries) == 0
    pool.close()


def test_multi_currency_journal_restores_open_and_settled_accounts(tmp_path):
    from tests.test_batch_multicurrency import fixture as multi_fixture
    from tests.test_batch_multicurrency import intents as multi_intents
    from tests.test_batch_multicurrency import run as multi_run

    open_scheduler, open_pool, _, open_ledger, _, _ = multi_fixture(tmp_path / "open")
    batch = multi_intents()
    for intent in batch:
        assert open_ledger.quote_reserve(intent).verdict == "granted"
    expected_open = open_ledger.spent
    _, reopened_pool, _, reopened, _, _ = multi_fixture(tmp_path / "open")
    reopened.restore_from_journal()
    assert reopened.spent == expected_open
    assert set(reopened.reserves) == {intent.intent_id for intent in batch}
    assert reopened.reserves[batch[0].intent_id].amounts == batch[0].requested_amounts
    open_pool.close()
    reopened_pool.close()

    scheduler, pool, _, ledger, _, _ = multi_fixture(tmp_path / "settled")
    multi_run(scheduler)
    expected_spent = ledger.spent
    _, new_pool, _, restored, _, _ = multi_fixture(tmp_path / "settled")
    restored.restore_from_journal()
    assert restored.spent == expected_spent
    assert not restored.reserves and len(restored.settled_intents) == 2
    assert restored.account_summary()["standard_spent"] == 447
    pool.close()
    new_pool.close()


def test_fresh_ledger_replays_released_reservation_without_renewing_it(tmp_path):
    store = AppendOnlyStore(tmp_path / "ledger.jsonl")
    ledger = BudgetLedger(1000, 0.05, 10, STAMP, store)
    intent = intents()[0]
    ledger.quote_reserve(intent)
    ledger.release_for(intent)
    restored = BudgetLedger(1000, 0.05, 10, STAMP, store)
    restored.restore_from_journal()
    assert restored.spent["exploit"] == 0 and not restored.reserves
    assert not restored.settled_intents
    assert restored.quote_reserve(intent).verdict == "granted"


if __name__ == "__main__" and len(sys.argv) == 5 and sys.argv[1] == "--owner":
    owner_main(Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4]))
