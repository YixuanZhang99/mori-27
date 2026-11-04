# M7 construction core: local engineering evidence

The private construction interface now generates artifacts using a bound role, hypothesis and projection of an existing ContextPack. Twenty new regressions cover role/context effects, provenance and detached inputs, frozen rejection/free attribution, bounded repair, malformed output and known/unknown provider usage. The initial run failed because the module was absent; implementation then passed the new tests and 37 existing context tests.

The frozen-source full project run passed 2,152 Linux tests, 76 tooling tests, 11 axioms, examples, builds and original import integrity. See [summary.json](summary.json) for exact timestamps and hashes. Scripted external-provider substitutes were used; no real provider request or live campaign change occurred.

This is Task 1 of the [M7 implementation plan](../../../docs/superpowers/plans/2026-11-04-m7-execution.md). It is not wired into Framework yet, and does not certify durable materialization, Git publication, controls, v9 currency integration, M7-03 concurrency or full framework completion. Those remain required work. Whole-branch independent review and same-SHA acceptance belong to the integrated milestone, not this core-only result.
