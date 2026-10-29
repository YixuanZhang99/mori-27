"""Measured benchmark evidence and strict paired host comparisons."""
from __future__ import annotations

import hashlib
import json
import math
import statistics
from dataclasses import asdict, dataclass, field
from typing import Literal

from core.x1.store import AppendOnlyStore


@dataclass(frozen=True)
class SelectionContract:
    """Selection semantics attached to one externally measured run."""

    selection_object: Literal["single_run", "archive_best", "best_single_chain"]
    policy: str
    split: str

    def validate(self) -> None:
        if self.selection_object not in {"single_run", "archive_best", "best_single_chain"}:
            raise ValueError("selection_object must be single_run, archive_best or best_single_chain")
        if not isinstance(self.policy, str) or not self.policy.strip():
            raise ValueError("selection policy must be a non-empty versioned identifier")
        if not isinstance(self.split, str) or not self.split.strip():
            raise ValueError("selection split must be explicit and non-empty")


@dataclass(frozen=True)
class SelectionCandidate:
    """One auditable candidate eligible for declared pre-test selection."""

    candidate_id: str
    evidence_ref: str
    validation_score: float | None = None
    chain_id: str | None = None
    terminal: bool = False

    def validate(self) -> None:
        if not isinstance(self.candidate_id, str) or not self.candidate_id.strip():
            raise ValueError("selection candidate_id must be non-empty")
        if not isinstance(self.evidence_ref, str) or not self.evidence_ref.strip():
            raise ValueError("selection candidate evidence_ref must be non-empty")
        if self.chain_id is not None and (not isinstance(self.chain_id, str)
                                         or not self.chain_id.strip()):
            raise ValueError("selection chain_id must be non-empty when present")
        if not isinstance(self.terminal, bool):
            raise ValueError("selection terminal flag must be boolean")
        if self.validation_score is not None and (
                isinstance(self.validation_score, bool)
                or not isinstance(self.validation_score, (int, float))
                or not math.isfinite(self.validation_score)):
            raise ValueError("selection validation_score must be finite when present")


@dataclass(frozen=True)
class SelectionReceipt:
    """Hash-bound, deterministic replay of selection before official test scoring."""

    contract: SelectionContract
    candidates: tuple[SelectionCandidate, ...]
    selected_candidate_id: str
    receipt_sha256: str = ""

    def __post_init__(self) -> None:
        if not self.receipt_sha256:
            if isinstance(self.contract, SelectionContract):
                self.contract.validate()
            for candidate in self.candidates:
                if isinstance(candidate, SelectionCandidate):
                    candidate.validate()
            object.__setattr__(self, "receipt_sha256", self._computed_sha256())

    def _computed_sha256(self) -> str:
        payload = {"contract": asdict(self.contract),
                   "candidates": [asdict(candidate) for candidate in self.candidates],
                   "selected_candidate_id": self.selected_candidate_id}
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False, allow_nan=False).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def validate_and_replay(self) -> SelectionCandidate:
        if not isinstance(self.contract, SelectionContract):
            raise ValueError("selection receipt requires a SelectionContract")
        self.contract.validate()
        if self.receipt_sha256 != self._computed_sha256():
            raise ValueError("selection receipt hash mismatch")
        if not isinstance(self.candidates, tuple) or not self.candidates:
            raise ValueError("selection receipt requires a non-empty candidate tuple")
        if any(not isinstance(candidate, SelectionCandidate) for candidate in self.candidates):
            raise ValueError("selection receipt candidates have invalid types")
        for candidate in self.candidates:
            candidate.validate()
        by_id = {candidate.candidate_id: candidate for candidate in self.candidates}
        if len(by_id) != len(self.candidates):
            raise ValueError("selection candidate ids must be unique")
        if self.selected_candidate_id not in by_id:
            raise ValueError("selected candidate is absent from the selection pool")
        if self.contract.selection_object == "single_run":
            eligible = list(self.candidates)
            if len(eligible) != 1:
                raise ValueError("single_run selection requires exactly one candidate")
        else:
            if self.contract.split == "not_applicable":
                raise ValueError("pool-based selection requires an explicit validation split")
            if self.contract.selection_object == "archive_best":
                eligible = list(self.candidates)
            else:
                chains = {candidate.chain_id for candidate in self.candidates}
                if None in chains:
                    raise ValueError("best_single_chain requires a chain_id for every candidate")
                for chain_id in chains:
                    terminals = [candidate for candidate in self.candidates
                                 if candidate.chain_id == chain_id and candidate.terminal]
                    if len(terminals) != 1:
                        raise ValueError("every selection chain requires exactly one terminal")
                eligible = [candidate for candidate in self.candidates if candidate.terminal]
            if any(candidate.validation_score is None for candidate in eligible):
                raise ValueError("pool-based selection requires finite validation scores")
            eligible.sort(key=lambda candidate: (-candidate.validation_score,
                                                 candidate.candidate_id))
        expected = eligible[0]
        if expected.candidate_id != self.selected_candidate_id:
            raise ValueError("selected candidate does not match deterministic selection replay")
        return expected


def _validate_costs(costs: dict[str, float], name: str, allow_empty: bool = False) -> None:
    if not isinstance(costs, dict) or (not costs and not allow_empty):
        raise ValueError(f"{name} must be a non-empty physical cost mapping")
    if any(not isinstance(unit, str) or not unit.strip() for unit in costs):
        raise ValueError(f"{name} units must be non-empty strings")
    if any(isinstance(value, bool) or not isinstance(value, (int, float))
           or not math.isfinite(value) or value < 0 for value in costs.values()):
        raise ValueError(f"{name} amounts must be finite and non-negative")


def _validate_run_costs(budget: dict[str, float], actual_costs: dict[str, float]) -> None:
    _validate_costs(budget, "budget")
    _validate_costs(actual_costs, "actual costs")
    missing = set(budget) - set(actual_costs)
    if missing:
        raise ValueError("actual costs missing declared budget units: " +
                         ", ".join(sorted(missing)))


def _validate_matrix_contracts(all_runs, required_cost_units: set[str] | None) -> tuple:
    selections = {run.selection for run in all_runs}
    if len(selections) != 1:
        raise ValueError("paired comparison requires one identical selection contract")
    declared = {tuple(sorted(run.budget)) for run in all_runs}
    actual = {tuple(sorted(run.actual_costs)) for run in all_runs}
    if len(declared) != 1 or len(actual) != 1:
        raise ValueError("paired comparison requires identical declared and actual cost-unit sets")
    declared_units, actual_units = next(iter(declared)), next(iter(actual))
    if required_cost_units is not None:
        if any(not isinstance(unit, str) or not unit.strip() for unit in required_cost_units):
            raise ValueError("required cost units must be non-empty strings")
        missing = set(required_cost_units) - set(declared_units)
        if missing:
            raise ValueError("comparison lacks required declared cost units: " +
                             ", ".join(sorted(missing)))
    return next(iter(selections)), declared_units, actual_units


@dataclass(frozen=True)
class BenchmarkRunRecord:
    benchmark: str
    task_list_sha256: str
    task_id: str
    seed: int
    arm: Literal["host", "governed"]
    backbone: str
    budget: dict[str, float]
    actual_costs: dict[str, float]
    valid_submission: bool
    any_medal: bool
    above_median: bool | None = None
    evidence_refs: tuple[str, ...] = ()
    measured: bool = False  # plans/fixtures must never masquerade as external runs
    selection: SelectionContract | None = None
    selection_receipt: SelectionReceipt | None = None

    def validate_measured(self) -> None:
        if not self.measured or not self.evidence_refs:
            raise ValueError("comparison requires externally measured runs with evidence refs")
        if not self.benchmark or not self.task_list_sha256 or not self.task_id or not self.backbone:
            raise ValueError("benchmark, task-list hash, task and backbone are required")
        if not isinstance(self.selection, SelectionContract):
            raise ValueError("measured comparison requires an explicit selection contract")
        self.selection.validate()
        if not isinstance(self.selection_receipt, SelectionReceipt):
            raise ValueError("measured comparison requires an explicit selection receipt")
        self.selection_receipt.validate_and_replay()
        if self.selection_receipt.contract != self.selection:
            raise ValueError("selection receipt and measured-run contract differ")
        _validate_run_costs(self.budget, self.actual_costs)
        for unit, actual in self.actual_costs.items():
            if unit in self.budget and actual > self.budget[unit]:
                raise ValueError(f"actual {unit} cost exceeds the declared budget")


@dataclass(frozen=True)
class ScoreRunRecord:
    """Externally measured numeric score under a declared paired-run budget."""

    benchmark: str
    task_list_sha256: str
    task_id: str
    seed: int
    arm: Literal["host", "governed"]
    backbone: str
    budget: dict[str, float]
    actual_costs: dict[str, float]
    score: float
    metric_direction: Literal["maximize", "minimize"] = "maximize"
    timed_out: bool = False
    evidence_refs: tuple[str, ...] = ()
    measured: bool = False
    selection: SelectionContract | None = None
    selection_receipt: SelectionReceipt | None = None

    def validate_measured(self) -> None:
        if not self.measured or not self.evidence_refs:
            raise ValueError("score comparison requires measured runs with evidence refs")
        if not self.benchmark or not self.task_list_sha256 or not self.task_id or not self.backbone:
            raise ValueError("benchmark, task-list hash, task and backbone are required")
        if isinstance(self.score, bool) or not isinstance(self.score, (int, float)) \
                or not math.isfinite(self.score):
            raise ValueError("measured score must be finite")
        if not isinstance(self.selection, SelectionContract):
            raise ValueError("score comparison requires an explicit selection contract")
        self.selection.validate()
        if not isinstance(self.selection_receipt, SelectionReceipt):
            raise ValueError("measured comparison requires an explicit selection receipt")
        self.selection_receipt.validate_and_replay()
        if self.selection_receipt.contract != self.selection:
            raise ValueError("selection receipt and measured-run contract differ")
        _validate_run_costs(self.budget, self.actual_costs)
        for unit, actual in self.actual_costs.items():
            if unit in self.budget and actual > self.budget[unit] \
                    and not (self.timed_out and unit == "wallclock"):
                raise ValueError(f"actual {unit} cost exceeds the declared budget")


@dataclass(frozen=True)
class SameBudgetComparison:
    benchmark: str
    task_list_sha256: str
    backbone: str
    paired_runs: int
    task_count: int
    seeds_per_task: int
    host_valid_rate: float
    governed_valid_rate: float
    host_medal_rate: float
    governed_medal_rate: float
    medal_delta: float
    paired_delta_sem: float
    noise_floor: float
    verdict: Literal["within_noise_floor", "governed_above_noise", "governed_below_noise"]
    selection: SelectionContract | None = None
    actual_cost_totals: dict[str, dict[str, float]] = field(default_factory=dict)
    declared_cost_units: tuple[str, ...] = ()
    actual_cost_units: tuple[str, ...] = ()
    selection_receipt_sha256: dict[str, str] = field(default_factory=dict)


def _selection_digests(all_runs) -> dict[str, str]:
    return {f"{run.arm}/{run.task_id}/{run.seed}": run.selection_receipt.receipt_sha256
            for run in sorted(all_runs, key=lambda item: (item.arm, item.task_id, item.seed))}


def _index(runs: list[BenchmarkRunRecord], arm: str) -> dict[tuple[str, int], BenchmarkRunRecord]:
    result = {}
    for run in runs:
        run.validate_measured()
        if run.arm != arm:
            raise ValueError("run placed under the wrong comparison arm")
        key = (run.task_id, run.seed)
        if key in result:
            raise ValueError(f"duplicate {arm} run: {key}")
        result[key] = run
    return result


def compare_same_budget(host_runs: list[BenchmarkRunRecord],
                        governed_runs: list[BenchmarkRunRecord], noise_floor: float,
                        expected_task_ids: set[str] | None = None,
                        min_seeds: int = 3,
                        store: AppendOnlyStore | None = None,
                        required_cost_units: set[str] | None = None) -> SameBudgetComparison:
    """Refuse incomplete or unfair comparisons instead of emitting a pass/fail score."""
    if not 0 <= noise_floor <= 1 or min_seeds < 1:
        raise ValueError("noise_floor must be in [0,1] and min_seeds positive")
    host, governed = _index(host_runs, "host"), _index(governed_runs, "governed")
    if not host or set(host) != set(governed):
        raise ValueError("host/governed task-seed sets must be complete and identical")
    all_runs = list(host.values()) + list(governed.values())
    selection, declared_units, actual_units = _validate_matrix_contracts(
        all_runs, required_cost_units)
    if len({r.benchmark for r in all_runs}) != 1 or len({r.task_list_sha256 for r in all_runs}) != 1:
        raise ValueError("all runs must use one benchmark and one task-list snapshot")
    if len({r.backbone for r in all_runs}) != 1:
        raise ValueError("paired comparison requires the same backbone")
    task_ids = {task for task, _ in host}
    if expected_task_ids is not None and task_ids != expected_task_ids:
        raise ValueError("comparison does not cover the locked benchmark task list")
    seed_sets = {task: frozenset(seed for t, seed in host if t == task) for task in task_ids}
    seed_counts = {task: len(seeds) for task, seeds in seed_sets.items()}
    if len(set(seed_sets.values())) != 1 or next(iter(seed_counts.values())) < min_seeds:
        raise ValueError(f"every task requires the same seed set and at least {min_seeds} seeds")

    differences = []
    for key in sorted(host):
        h, g = host[key], governed[key]
        if h.budget != g.budget:
            raise ValueError(f"budget mismatch for {key}")
        differences.append(float(g.any_medal) - float(h.any_medal))
    delta = statistics.fmean(differences)
    sem = statistics.stdev(differences) / math.sqrt(len(differences)) if len(differences) > 1 else 0.0
    verdict = ("within_noise_floor" if abs(delta) <= noise_floor else
               "governed_above_noise" if delta > 0 else "governed_below_noise")
    totals = {}
    for arm, runs in (("host", host.values()), ("governed", governed.values())):
        units = set().union(*(r.actual_costs.keys() for r in runs))
        totals[arm] = {unit: sum(r.actual_costs[unit] for r in runs)
                       for unit in sorted(units)}
    first = next(iter(host.values()))
    report = SameBudgetComparison(
        benchmark=first.benchmark, task_list_sha256=first.task_list_sha256,
        backbone=first.backbone, paired_runs=len(host), task_count=len(task_ids),
        seeds_per_task=next(iter(seed_counts.values())),
        host_valid_rate=statistics.fmean(float(r.valid_submission) for r in host.values()),
        governed_valid_rate=statistics.fmean(float(r.valid_submission) for r in governed.values()),
        host_medal_rate=statistics.fmean(float(r.any_medal) for r in host.values()),
        governed_medal_rate=statistics.fmean(float(r.any_medal) for r in governed.values()),
        medal_delta=delta, paired_delta_sem=sem, noise_floor=noise_floor,
        verdict=verdict, selection=selection, actual_cost_totals=totals,
        declared_cost_units=declared_units, actual_cost_units=actual_units,
        selection_receipt_sha256=_selection_digests(all_runs))
    if store is not None:
        store.append("same_budget_comparison", asdict(report))
    return report


@dataclass(frozen=True)
class SameBudgetScoreComparison:
    benchmark: str
    task_list_sha256: str
    backbone: str
    metric_direction: Literal["maximize", "minimize"]
    paired_runs: int
    task_count: int
    seeds_per_task: int
    host_mean_score: float
    governed_mean_score: float
    score_delta: float
    paired_delta_sem: float
    noise_floor: float
    verdict: Literal["within_noise_floor", "governed_above_noise", "governed_below_noise"]
    selection: SelectionContract | None = None
    actual_cost_totals: dict[str, dict[str, float]] = field(default_factory=dict)
    declared_cost_units: tuple[str, ...] = ()
    actual_cost_units: tuple[str, ...] = ()
    selection_receipt_sha256: dict[str, str] = field(default_factory=dict)


def _score_index(runs: list[ScoreRunRecord], arm: str) -> dict[tuple[str, int], ScoreRunRecord]:
    result = {}
    for run in runs:
        run.validate_measured()
        if run.arm != arm:
            raise ValueError("score run placed under the wrong comparison arm")
        key = (run.task_id, run.seed)
        if key in result:
            raise ValueError(f"duplicate {arm} score run: {key}")
        result[key] = run
    return result


def compare_scores_same_budget(host_runs: list[ScoreRunRecord],
                               governed_runs: list[ScoreRunRecord], noise_floor: float,
                               expected_task_ids: set[str] | None = None,
                               min_seeds: int = 3,
                               store: AppendOnlyStore | None = None,
                               required_cost_units: set[str] | None = None) -> SameBudgetScoreComparison:
    """Compare directed numeric scores only for a complete, equally budgeted matrix."""
    if not math.isfinite(noise_floor) or noise_floor < 0 or min_seeds < 1:
        raise ValueError("score noise_floor must be finite/non-negative and min_seeds positive")
    host, governed = _score_index(host_runs, "host"), _score_index(governed_runs, "governed")
    if not host or set(host) != set(governed):
        raise ValueError("host/governed score task-seed sets must be complete and identical")
    all_runs = list(host.values()) + list(governed.values())
    selection, declared_units, actual_units = _validate_matrix_contracts(
        all_runs, required_cost_units)
    if len({r.benchmark for r in all_runs}) != 1 \
            or len({r.task_list_sha256 for r in all_runs}) != 1:
        raise ValueError("all score runs must use one benchmark and one task-list snapshot")
    if len({r.backbone for r in all_runs}) != 1:
        raise ValueError("paired score comparison requires the same backbone")
    if len({r.metric_direction for r in all_runs}) != 1:
        raise ValueError("paired score comparison requires one metric direction")
    task_ids = {task for task, _ in host}
    if expected_task_ids is not None and task_ids != expected_task_ids:
        raise ValueError("score comparison does not cover the locked benchmark task list")
    seed_sets = {task: frozenset(seed for t, seed in host if t == task) for task in task_ids}
    seed_counts = {task: len(seeds) for task, seeds in seed_sets.items()}
    if len(set(seed_sets.values())) != 1 or next(iter(seed_counts.values())) < min_seeds:
        raise ValueError(f"every score task requires the same seed set and at least {min_seeds}")
    direction = next(iter(all_runs)).metric_direction
    sign = 1.0 if direction == "maximize" else -1.0
    differences = []
    for key in sorted(host):
        h, g = host[key], governed[key]
        if h.budget != g.budget:
            raise ValueError(f"score budget mismatch for {key}")
        differences.append(sign * (g.score - h.score))
    delta = statistics.fmean(differences)
    sem = statistics.stdev(differences) / math.sqrt(len(differences)) if len(differences) > 1 else 0.0
    verdict = ("within_noise_floor" if abs(delta) <= noise_floor else
               "governed_above_noise" if delta > 0 else "governed_below_noise")
    totals = {}
    for arm, runs in (("host", host.values()), ("governed", governed.values())):
        units = set().union(*(r.actual_costs.keys() for r in runs))
        totals[arm] = {unit: sum(r.actual_costs[unit] for r in runs)
                       for unit in sorted(units)}
    first = next(iter(host.values()))
    report = SameBudgetScoreComparison(
        benchmark=first.benchmark, task_list_sha256=first.task_list_sha256,
        backbone=first.backbone, metric_direction=direction,
        paired_runs=len(host), task_count=len(task_ids),
        seeds_per_task=next(iter(seed_counts.values())),
        host_mean_score=statistics.fmean(r.score for r in host.values()),
        governed_mean_score=statistics.fmean(r.score for r in governed.values()),
        score_delta=delta, paired_delta_sem=sem, noise_floor=noise_floor,
        verdict=verdict, selection=selection, actual_cost_totals=totals,
        declared_cost_units=declared_units, actual_cost_units=actual_units,
        selection_receipt_sha256=_selection_digests(all_runs))
    if store is not None:
        store.append("same_budget_score_comparison", asdict(report))
    return report
