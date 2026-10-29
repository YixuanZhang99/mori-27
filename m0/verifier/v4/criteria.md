# Verifier v4 acceptance criteria

Extends v3 without replacing it. v4 first executes the complete v3 verifier, then checks M5 scoped memory and M6 two-lane knowledge behavior:

1. v3 exits 0, including all earlier pytest and independent behavior checks.
2. Memory entries carry provenance/time/scope; task isolation and domain promotion work, global promotion requires evidence, and candidate entries cannot be retrieved before activation.
3. Retrieval always performs deterministic recall followed by utility reranking; negative lessons can be included or filtered, TTL causes demotion rather than silent deletion, and normal lifecycle operations preserve records.
4. Evidence invalidation cascades to dependent memories as soft demotion/supersession while entries and append-only logs survive; physical deletion requires the explicit hygiene path.
5. Knowledge startup rejects shared backend objects, shared cache namespaces and non-superset audit corpora. Ground queries cite only opened sources present in the fetch ledger; repair requires a structured M8 failure signal.
6. Benchmark mode produces violation evidence and no backend calls in either lane. Audit queries are fresh from idea text, verdicts remain advisory and cannot be consumed as merge references before independent quality review.
7. Cross-lane fetched-text overlap appends soft verdict invalidation and is excluded from false-novel/false-kill calibration. Gap-card independence and diversity-only injection-gravity checks execute.
8. Every v4 invocation appends a timestamped record with command, exit code, checks and observed values, including failed checks and exceptions. Earlier criteria and logs remain unchanged.
