# Verifier v3 acceptance criteria

Extends v2 without replacing it. v3 first executes the complete v2 verifier (which itself executes v1), then checks the evaluation-governance and multi-currency slice:

1. v2 exits 0, including the complete pytest suite and all earlier behavior checks.
2. Cascade evaluation meters shallow plus full costs, escalates a competitive candidate, stops a weak candidate after shallow evaluation, and prevents that incomplete result from admission.
3. Judge governance utilities execute deterministically: position-swap detects positional bias, Cohen's kappa matches a known value, and isotonic calibration preserves fitted block values and monotonicity.
4. Evaluator meta-gate rejects any per-item held-out anchor regression; a valid promotion occurs only at a new epoch and appends soft invalidations for all receipts tied to the old evaluator while retaining the original receipts.
5. EvoEvaluator is disabled by default and refuses activation when any of the four prerequisites is absent: the identified held-out anchor, enabled meta-gate, cascade-invalidation readiness, or measured evaluator-bottleneck evidence.
6. Multi-currency intents reserve every requested unit atomically, insufficient funds in one unit leave no partial reserve, release restores every unit, settlement reconciles actual per-unit costs, and standard-coin reporting uses the recorded exchange-table version.
7. Every v3 invocation appends a timestamped record with command, exit code, checks and observed values, including failed checks and exceptions. v1/v2 criteria and logs remain unchanged.
