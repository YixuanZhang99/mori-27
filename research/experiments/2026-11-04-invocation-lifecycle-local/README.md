# Invocation lifecycle: local engineering evidence

[summary.json](summary.json) records frozen-source project verification: 2,129 Linux tests, 76 tooling tests, 11 static axioms, six examples, builds and original import integrity. The new wheel was installed independently and its CNY example ran outside the checkout; replay made no new HTTP request or ledger write.

A standalone governed-controls example first paused using the installed 75f397e wheel. Its installed runtime bytes were checked against that commit and the new lifecycle module was absent. Current code then resumed and replayed that same run: one completed control became three, all four main and three control calls have exactly seven original start/completion pairs, and recorded replay made no external call. This certifies that specific v7 cross-commit path, not every possible third-party checkpoint.

The refactor removes caller-owned start/meter/settle/integrity sequencing from hierarchical planning, both operator paths and evaluation. The real physical settlement adapter and legacy wall-clock injection remain. Ordinary ungoverned native exceptions do not acquire supervisor measurement authority. Existing tests and historical verifier sources are unchanged.

The active verifier remains v73: the change preserves runtime identities, formats and capability scope, and the new lifecycle file is covered by its complete unfiltered pytest group. Clean same-SHA acceptance and hosted CI must be reported separately after the implementation commit. This report does not close full A7, real benchmark requirements or formal release.
