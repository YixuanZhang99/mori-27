# Governed currency bridge: local engineering evidence

The implementation extends the verified ff5c441 v72 baseline. [summary.json](summary.json) records a frozen-source project check: 2,116 Linux tests, 70 tooling tests before the acceptance transition, all axioms, six examples, wheel/sdist build and original import integrity. After adding v73, all 76 tooling tests passed. The clean v73 acceptance and hosted CI must be assessed separately at the resulting commit; this report does not certify them.

The built wheel was installed into an isolated environment. Its standalone example was copied outside the checkout and run with isolated Python: four loopback requests, two completed controls, pause/resume and recorded replay passed. Replay added no HTTP requests or currency events. The 152 micro-CNY fixture usage is synthetic, not actual spend.

Coverage includes fixed main/control capacity, physical and monetary admission, exact invocation identity, known refusal evidence, state-preserving recovery after actual SIGKILL, native/worktree public APIs and independently replayed currency evidence. Public Framework.replay first captures and validates the original live ledger; only the subsequent reconstruction is detached and read-only. Deleting the original ledger before public replay is not certified.

No external model request, live campaign migration, supplier invoice check, IID guarantee, benchmark superiority or complete release is claimed. Existing failed runs and historical verifier sources remain preserved. See [the current scope](../../../docs/FRAMEWORK_STATUS.md) and [usage guide](../../../docs/GOVERNED_CURRENCY.md).
