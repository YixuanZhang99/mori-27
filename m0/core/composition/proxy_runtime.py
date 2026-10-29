"""Budgeted calibration calls and evidence-authorized negative feedback."""
from __future__ import annotations

from core.budget.ledger import BudgetError
from core.composition.evaluation import encode_evidence
from core.executor.types import EvalStatus


class ProxyRuntime:
    async def _calibrate_candidates(self, proposal, evidence, cycle):
        """Return continuation, optional admission veto and M5 mutations.

        Calibration is development evidence from its own content context.
        Neither held-out admission evidence nor final audit enters this path.
        """
        if self.proxy is None or evidence.eval_result.status is not EvalStatus.OK \
                or not self.proxy.needs_anchor(cycle):
            return True, None, []
        request = self.proxy.anchor_request
        work = []
        if self.incumbent:
            incumbent, dev = self.proposals[self.incumbent], self.evidence[self.incumbent]
            if self.proxy.cached_anchor(incumbent, dev, anchor_binding=self._binding(incumbent, request)) is None:
                work.append((incumbent, dev, "baseline"))
        work.append((proposal, evidence, "candidate"))
        reserved = []
        for target, dev, role in work:
            self._validate_domain(request)
            receipt = self._reserve_physical(target.candidate, "anchor", f"{role}:{cycle}", request=request)
            if not receipt.granted:
                for _, _, _, previous in reserved:
                    self.budget.release_operation(previous.intent_id, fingerprint=previous.fingerprint)
                self.store.append("proxy_budget_rejected", {"cycle": cycle, "reason": receipt.reason})
                self._halt_physical(cycle, "required calibration anchor cannot be funded: " + receipt.reason, started=True)
                return False, None, []
            reserved.append((target, dev, role, receipt))
        observation = None
        for index, (target, dev, role, receipt) in enumerate(reserved):
            try:
                self.budget.pre_call_check()
            except BudgetError as error:
                for _, _, _, remaining in reserved[index:]:
                    self.budget.release_operation(remaining.intent_id, fingerprint=remaining.fingerprint)
                self._halt_physical(cycle, str(error), started=True)
                return False, None, []
            # Baseline calls run first. Build each plan against the current
            # monitor state, which may have changed after a failed baseline.
            plan = self.proxy.plan(target, dev, cycle, anchor_binding=self._binding(target, request),
                                   force=True, role=role)
            begun = recorded = False
            try:
                self.proxy.begin(plan)
                begun = True
                anchor = await self._evaluate_physical(target, request, receipt)
                result = self.proxy.record(plan, anchor)
                recorded = True
                self.store.append("composed_anchor", {"cycle": cycle, "role": role, "pair_id": plan.key,
                    "evidence": encode_evidence(anchor), "monitor": self.proxy.state()})
                if role == "baseline" and anchor.eval_result.status is not EvalStatus.OK:
                    for _, _, _, remaining in reserved[index + 1:]:
                        self.budget.release_operation(remaining.intent_id, fingerprint=remaining.fingerprint)
                    return True, "incumbent calibration baseline did not succeed", []
                if role == "candidate":
                    observation = result
            except Exception as error:
                for _, _, _, remaining in reserved[index + 1:]:
                    self.budget.release_operation(remaining.intent_id, fingerprint=remaining.fingerprint)
                if not begun:
                    self.budget.release_operation(receipt.intent_id, fingerprint=receipt.fingerprint)
                elif not recorded:
                    self.proxy.mark_failed(plan, type(error).__name__)
                raise
        if observation is None:
            raise RuntimeError("required candidate calibration produced no observation")
        mutations = self.memory.prepare_proxy_feedback(observation.negative_feedback, self.proxy, cycle=cycle) \
            if observation.negative_feedback is not None else []
        rejected = None
        if self.proxy.state()["mode"] == "degraded" and not self.proxy.allows_advancement(observation.pair_id):
            rejected = "degraded proxy requires a successful anchor exceeding the comparable true best"
        return True, rejected, mutations
