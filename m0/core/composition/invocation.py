"""Measured physical calls: one owner for start, usage, settlement and failure.

The physical settlement adapter owns unit coverage and durable measurements.
This module owns its ordering with invocation, outcome and integrity evidence.
"""
from __future__ import annotations

from contextlib import nullcontext
from dataclasses import asdict
import math
import time

from core.composition.contracts import OperatorFailure, Proposal
from core.composition.evaluation import measured_costs
from core.executor.types import CostVec, EvidenceRecord
from core.llm import UsageError


def _physical(cost):
    if not isinstance(cost, CostVec):
        raise UsageError("operation must return explicit physical costs")
    for name, value in asdict(cost).items():
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise UsageError("physical costs must be finite and nonnegative")
        if name in {"tokens_in", "tokens_out", "eval_count", "node_count"} and type(value) is not int:
            raise UsageError("physical token and count costs must be integers")
    return {"token": cost.tokens_in + cost.tokens_out, "eval_count": cost.eval_count,
            "node": cost.node_count, "wallclock": cost.wall_seconds,
            "gpu_hours": cost.gpu_hours, "usd": cost.usd}


def check_provider_floor(store, receipt, provider, before, cost):
    observed = provider.usage_total - before
    reported = _physical(cost)["token"]
    if reported < observed:
        store.append("composed_usage_discrepancy", {"intent_id": receipt.intent_id,
            "provider_tokens": observed, "reported_tokens": reported})
        raise UsageError("reported token cost is below observed provider usage")


class _Operation:
    """Private state; callers cannot separately start, meter or settle a call."""
    def __init__(self, owner, receipt, provider, lane="main", slot_id=None):
        self.owner, self.receipt, self.provider = owner, receipt, provider
        self.lane, self.slot_id = lane, slot_id
        self.settled = False

    def __enter__(self):
        self.owner.budget.start_operation(self.receipt.intent_id, fingerprint=self.receipt.fingerprint)
        try:
            self.before = self.provider.usage_total
            self.started = self.owner.clock()
        except Exception as error:
            self._unresolved(error)
            raise
        return self

    def _unresolved(self, error):
        self.owner.budget.mark_unresolved(self.receipt.intent_id, fingerprint=self.receipt.fingerprint,
                                         reason=type(error).__name__ + ": " + str(error))

    def __exit__(self, kind, error, traceback):
        # A real process interruption has no trustworthy ordinary terminal.
        if isinstance(error, Exception) and not self.settled:
            self._unresolved(error)

    async def invoke(self, function):
        governance = self.owner.governance
        meter = (governance.meter(self.provider, self.receipt, lane=self.lane, slot_id=self.slot_id)
                 if governance is not None else nullcontext())
        with meter:
            return await function()

    def check_floor(self, cost):
        check_provider_floor(self.owner.store, self.receipt, self.provider, self.before, cost)

    def finish(self, cost, coverage, elapsed=None, *, evaluation=False, operator=False, integrity=True):
        if self.settled:
            raise UsageError("physical invocation has already settled")
        self.check_floor(cost)
        self.owner.settle(self.receipt, cost, coverage,
            self.owner.clock() - self.started if elapsed is None else elapsed,
            evaluation=evaluation, operator=operator)
        self.settled = True
        if integrity and self.owner.governance is not None:
            self.owner.governance.check_integrity(self.receipt)


class InvocationLifecycle:
    """Execute measured phases without exposing their accounting choreography."""
    def __init__(self, budget, store, settle, *, governance=None, clock=None):
        self.budget, self.store, self.settle, self.governance = budget, store, settle, governance
        self.clock = time.monotonic if clock is None else clock

    async def planning(self, receipt, provider, invoke):
        with _Operation(self, receipt, provider) as operation:
            def finish():
                tokens = provider.usage_total - operation.before
                if tokens and set(self.budget.units) & {"gpu_hours", "usd"}:
                    raise UsageError("paid planning has no GPU/currency meter")
                operation.finish(CostVec(tokens_in=tokens),
                                 ("token", "eval_count", "node", "gpu_hours", "usd"))
            try:
                result = await operation.invoke(invoke)
            except UsageError:
                raise
            except Exception:
                finish()
                raise
            finish()
            return result

    async def operator(self, operator, request, candidate, receipt, *, provider, lane="main", slot_id=None):
        with _Operation(self, receipt, provider, lane, slot_id) as operation:
            failure = None
            try:
                proposal = await operation.invoke(lambda: operator.propose(request))
            except OperatorFailure as error:
                failure = error
                proposal = Proposal(candidate, "", error.cost, error.measured_cost_units)
            if not isinstance(proposal, Proposal):
                raise UsageError("operator returned no measurable Proposal")
            operation.check_floor(proposal.cost)
            if self.governance is not None:
                self.store.append("governed_operator_outcome", {
                    "intent_id": receipt.intent_id, "fingerprint": receipt.fingerprint,
                    "proposal": asdict(proposal),
                    "failure_type": type(failure).__name__ if failure else None})
            operation.finish(proposal.cost, proposal.measured_cost_units, operator=True)
            if "node" in proposal.measured_cost_units and proposal.cost.node_count != 1:
                raise ValueError("operator node measurement differs from the actual candidate attempt")
            return proposal, failure

    async def evaluation(self, receipt, provider, invoke, *, identity, domain, elapsed=None,
                         lane="main", slot_id=None):
        from core.composition.worktree import MeasuredCommandError
        with _Operation(self, receipt, provider, lane, slot_id) as operation:
            measured_elapsed = None
            try:
                if self.governance is not None:
                    async def recorded():
                        return await self.store.evaluation_call(identity, invoke, provider=provider, domain=domain)
                    evidence, measured_elapsed = await operation.invoke(recorded)
                else:
                    evidence = await operation.invoke(invoke)
            except MeasuredCommandError as error:
                if self.governance is None and elapsed is None:
                    # Legacy native executors have no supervisor attestation.
                    raise
                operation.check_floor(error.cost)
                if self.governance is not None:
                    self.store.append("governed_evaluation_failure", {"intent_id": receipt.intent_id,
                        "fingerprint": receipt.fingerprint, "cost": asdict(error.cost),
                        "measured_cost_units": list(error.measured_cost_units), "reason": "MeasuredCommandError"})
                operation.finish(error.cost, error.measured_cost_units, error.wall_seconds,
                                 evaluation=True, integrity=False)
                if self.governance is not None:
                    self.store.append("governed_integrity_failure", {"intent_id": receipt.intent_id,
                        "reason": "measured_evaluation_rejected"})
                raise
            if self.governance is None and elapsed is not None:
                # Timing retrieval cannot attest a replacement executor bill.
                measured_elapsed = elapsed()
            if not isinstance(evidence, EvidenceRecord):
                raise UsageError("executor returned no measurable canonical evidence")
            operation.check_floor(evidence.eval_result.cost)
            measured_costs(evidence.eval_result)
            operation.finish(evidence.eval_result.cost, evidence.eval_result.contract.measured_cost_units,
                             measured_elapsed, evaluation=True)
            if evidence.eval_result.cost.eval_count < 1:
                raise ValueError("evaluation count is below the actual domain invocation")
            return evidence
