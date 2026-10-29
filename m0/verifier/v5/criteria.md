# Verifier v5 acceptance criteria

Extends v4 without replacing it. v5 first executes the complete v4 verifier, then independently checks the static CI gate and the new explicit M2/M4 extensions:

1. v4 exits 0, including all earlier pytest runs and independent behavior checks.
2. `python3 ci/check_axioms.py` exits 0 as a standalone process. Its channel, forbidden-import, gate-not-rank, stop-table, public-API, append-only, dependency-acyclicity, benchmark-isolation, vocabulary and no-audit-veto checks must all be true. Gate-not-rank also rejects cost fields.
3. A CI workflow exists for push/pull-request validation and invokes the standalone static gate, the complete tests and this v5 verifier. This criterion verifies wiring, not a claim that a hosted CI service has executed.
4. Debug refuses LLM bugginess judgments and consumes structured environment failure facts. Evolve-block repair preserves frozen structure.
5. Crossover enforces its signature/role/debug-fallback contract, deterministic parent permutation and two-parent lineage, rejects incompatible frozen signatures before calling the LLM, and applies only the editable block.
6. The fusion+repair pipeline executes a valid child, sends an environment failure to debug, and never executes a child whose deterministic apply failed. Crossover ancestry and fallback linkage survive.
7. The performance/cost archive keeps physical cost units as independent minimization axes, retains tradeoff points, excludes only dominated points from the frontier view, preserves all offers in append-only evidence, and rejects mixed-unit or invalid offers atomically.
8. Changing aggregate score or cost side channels does not change M9 per-item flip adjudication. Pareto data is not consumed by the gate.
9. Every v5 invocation appends a timestamped record with command, exit code, checks and observed values, including failed checks and exceptions. Earlier criteria and logs remain unchanged.
