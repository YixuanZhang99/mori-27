"""v19 real SIGKILL injection inside token and multi-unit settlement."""
import asyncio
import subprocess
import sys
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.budget.currency import MultiCurrencyBudgetLedger
from core.budget.ledger import BudgetError, BudgetLedger
from core.budget.types import CurrencyAccount, ExchangeRateTable
from core.executor import EvalRequest, ExecutorPool, ExecutorSpec, GitWorktree, GitWorktreeExecutor
from core.frontier import ResearchFrontier
from core.memory import ScopeContext, ScopedMemory
from core.orchestration import BatchScheduler
from core.policy import BestFirstPolicy
from core.state import StateApplier
from core.x1.store import AppendOnlyStore
from tests.test_batch_execution_recovery import (IDS, STAMP, admission, builder, candidates,
                                                 components, contract, forbidden_builder,
                                                 git, intents, make_repo)

PROJECT = Path(__file__).resolve().parents[1]


class BlockingTokenLedger(BudgetLedger):
    def __init__(self, *args, marker, **kwargs):
        super().__init__(*args, **kwargs)
        self.marker = Path(marker)

    def _write(self, **kw):
        entry = super()._write(**kw)
        if kw.get("entry_kind") == "settle" and not self.marker.exists():
            self.marker.write_text("token settle journaled")
            time.sleep(30)
        return entry


class CorruptingTokenLedger(BlockingTokenLedger):
    def settle(self, intent, actual_cost, admission_outcome=None):
        return super().settle(intent, actual_cost + 1, admission_outcome)


class BlockingMultiLedger(MultiCurrencyBudgetLedger):
    def __init__(self, *args, marker, **kwargs):
        super().__init__(*args, **kwargs)
        self.marker = Path(marker)

    def _write(self, unit, **kw):
        entry = super()._write(unit, **kw)
        if unit == "token" and kw.get("entry_kind") == "settle" \
                and not self.marker.exists():
            self.marker.write_text("first basket unit journaled")
            time.sleep(30)
        return entry


def fast_repo(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    repo = make_repo(root)
    eval_path = repo / "eval.py"
    eval_path.write_text(eval_path.read_text().replace("time.sleep(2)", "time.sleep(0.2)"))
    git(repo, "add", "eval.py")
    git(repo, "commit", "--quiet", "-m", "fast recovery fixture")
    return repo


def multi_components(repo: Path, store: AppendOnlyStore, marker: Path | None = None):
    accounts = {"token": CurrencyAccount("token", 10_000, floor=10),
                "usd": CurrencyAccount("usd", 100),
                "eval_count": CurrencyAccount("eval_count", 20),
                "node": CurrencyAccount("node", 20),
                "wallclock": CurrencyAccount("wallclock", 100),
                "gpu_hours": CurrencyAccount("gpu_hours", 10)}
    exchange = ExchangeRateTable("v19-fx", {
        ("usd", "token"): 100, ("eval_count", "token"): 50,
        ("node", "token"): 10, ("wallclock", "token"): 2,
        ("gpu_hours", "token"): 200}, "token")
    ledger_type = BlockingMultiLedger if marker is not None else MultiCurrencyBudgetLedger
    kwargs = {"marker": marker} if marker is not None else {}
    ledger = ledger_type(accounts, 0.05, STAMP, store, exchange, **kwargs)
    frontier, memory = ResearchFrontier(store=store), ScopedMemory(store)
    policy = BestFirstPolicy(ScopeContext("v19-run", "task", "domain"))
    executor = GitWorktreeExecutor(contract(), builder if marker else forbidden_builder, store)
    pool = ExecutorPool(executor, 2, store)
    scheduler = BatchScheduler(pool, ledger, policy,
                               StateApplier(frontier, memory, store), store)
    return scheduler, pool, ledger, frontier, memory


def multi_intents():
    batch = intents()
    for intent in batch:
        intent.requested_amounts = {"token": 100, "usd": 2, "eval_count": 1,
                                    "node": 1, "wallclock": 10, "gpu_hours": 1}
    return batch


def owner_main(repo: Path, store_path: Path, worktrees: Path, marker: Path, multi: bool,
               corrupt: bool = False):
    store = AppendOnlyStore(store_path)
    if multi:
        scheduler, _, _, _, _ = multi_components(repo, store, marker)
        batch = multi_intents()
    else:
        ledger_type = CorruptingTokenLedger if corrupt else BlockingTokenLedger
        ledger = ledger_type(1000, 0.05, 10, STAMP, store, marker=marker)
        frontier, memory = ResearchFrontier(store=store), ScopedMemory(store)
        policy = BestFirstPolicy(ScopeContext("v19-run", "task", "domain"))
        executor = GitWorktreeExecutor(contract(), builder, store)
        pool = ExecutorPool(executor, 2, store)
        scheduler = BatchScheduler(pool, ledger, policy,
                                   StateApplier(frontier, memory, store), store)
        batch = intents()
    workspace = GitWorktree(repo, worktrees)
    asyncio.run(scheduler.run(
        [ExecutorSpec(hypothesis="h") for _ in IDS], candidates(), workspace,
        [EvalRequest("dev", time_limit=30, seed_set=[19]) for _ in IDS], batch, admission))


def start_owner(mode: str, repo: Path, store_path: Path, worktrees: Path, marker: Path):
    return subprocess.Popen([sys.executable, str(Path(__file__).resolve()), mode,
                             str(repo), str(store_path), str(worktrees), str(marker)],
                            cwd=PROJECT, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True)


def kill_at_marker(owner, marker: Path):
    deadline = time.monotonic() + 15
    while not marker.exists() and time.monotonic() < deadline:
        if owner.poll() is not None:
            raise AssertionError(f"owner exited before marker: {owner.returncode}")
        time.sleep(0.01)
    assert marker.exists()
    owner.kill()
    owner.wait(timeout=5)
    assert owner.returncode == -9


def settle_keys(store):
    return Counter((record["payload"]["intent_id"], record["payload"].get("unit", "token"))
                   for record in store.read("ledger")
                   if record["payload"].get("entry_kind") == "settle")


def assert_completed(scheduler, pool, ledger, frontier, memory, store, worktrees):
    assert [frontier.nodes[node].status for node in IDS] == ["merged", "pruned"]
    assert len(memory.entries) == 2 and not ledger.reserves
    assert len(ledger.settled_intents) == 2
    assert len(list(store.read("batch_execution_settled"))) == 2
    assert len(list(store.read("executor_process_started"))) == 2
    assert len(list(store.read("batch_cycle_completed"))) == 1
    assert scheduler.recovery_state()["status"] == "completed"
    assert not list(worktrees.iterdir())
    before = list(store.read())
    asyncio.run(scheduler.resume(admission, GitWorktree(store.path.parent / "repo", worktrees)))
    assert list(store.read()) == before
    pool.close()


def test_real_crash_after_token_settle_only_appends_missing_batch_evidence(tmp_path):
    repo = fast_repo(tmp_path)
    store_path, worktrees = tmp_path / "evidence.jsonl", tmp_path / "worktrees"
    marker = tmp_path / "token-settled.marker"
    owner = start_owner("--owner-single", repo, store_path, worktrees, marker)
    kill_at_marker(owner, marker)
    store = AppendOnlyStore(store_path)
    assert len(settle_keys(store)) == 1
    assert list(store.read("batch_execution_settled")) == []
    scheduler, pool, ledger, frontier, memory = components(repo, store, recover=True)
    workspace = GitWorktree(repo, worktrees)
    state = scheduler.recovery_state()
    assert state["status"] == "accounting_ambiguous" and state["accounting_recovery_safe"]
    results = asyncio.run(scheduler.resume(admission, workspace))
    assert [result.candidate_id for result in results] == IDS
    keys = settle_keys(store)
    assert len(keys) == 2 and set(keys.values()) == {1}
    assert ledger.spent["exploit"] == 0
    assert_completed(scheduler, pool, ledger, frontier, memory, store, worktrees)


def test_journaled_cost_mismatch_fails_before_batch_settlement_or_admission(tmp_path):
    repo = fast_repo(tmp_path)
    store_path, worktrees = tmp_path / "evidence.jsonl", tmp_path / "worktrees"
    marker = tmp_path / "corrupt-settled.marker"
    owner = start_owner("--owner-corrupt", repo, store_path, worktrees, marker)
    kill_at_marker(owner, marker)
    store = AppendOnlyStore(store_path)
    scheduler, pool, ledger, frontier, memory = components(repo, store, recover=True)
    with pytest.raises(BudgetError, match="costs differ"):
        asyncio.run(scheduler.resume(admission, GitWorktree(repo, worktrees)))
    assert list(store.read("batch_execution_settled")) == []
    assert list(store.read("batch_admission")) == []
    assert not frontier.nodes and len(memory.entries) == 0
    pool.close()


def test_real_crash_inside_multi_unit_basket_settles_only_missing_units(tmp_path):
    repo = fast_repo(tmp_path)
    store_path, worktrees = tmp_path / "evidence.jsonl", tmp_path / "worktrees"
    marker = tmp_path / "multi-settled.marker"
    owner = start_owner("--owner-multi", repo, store_path, worktrees, marker)
    kill_at_marker(owner, marker)
    store = AppendOnlyStore(store_path)
    assert len(settle_keys(store)) == 1
    assert list(store.read("batch_execution_settled")) == []
    scheduler, pool, ledger, frontier, memory = multi_components(repo, store)
    workspace = GitWorktree(repo, worktrees)
    state = scheduler.recovery_state()
    assert state["status"] == "accounting_ambiguous" and state["accounting_recovery_safe"]
    results = asyncio.run(scheduler.resume(admission, workspace))
    assert [result.candidate_id for result in results] == IDS
    keys = settle_keys(store)
    assert len(keys) == 12 and set(keys.values()) == {1}
    assert ledger.spent["token"]["exploit"] == 0
    assert ledger.spent["usd"]["exploit"] == 0
    assert ledger.spent["wallclock"]["exploit"] > 0
    assert ledger.account_summary()["standard_spent"] > 0
    assert_completed(scheduler, pool, ledger, frontier, memory, store, worktrees)


if __name__ == "__main__" and len(sys.argv) == 6:
    if sys.argv[1] == "--owner-single":
        owner_main(Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4]),
                   Path(sys.argv[5]), False)
    elif sys.argv[1] == "--owner-multi":
        owner_main(Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4]),
                   Path(sys.argv[5]), True)
    elif sys.argv[1] == "--owner-corrupt":
        owner_main(Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4]),
                   Path(sys.argv[5]), False, True)
