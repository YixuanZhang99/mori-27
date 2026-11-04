# Same-search governance intensity comparison

Compare one resident control after cycle 0 with two controls after cycles 0 and
2. Both arms use the same M7 population search, provider, public task data,
seed, iteration limit, candidate sandbox, currency authority and declared token
and wall limits. This measures the marginal cost and quality difference of an
additional scheduled control, not the effect of removing all governance.

We considered (1) comparing the existing baseline/full pilot, (2) disabling all
controls, and (3) varying only the resident-control schedule. The existing
pilot changes its search algorithm; disabling controls would also remove a
protected safety mechanism. Option 3 directly fits the existing control-plan
interface and preserves the common accounting and isolation boundaries.

Expose an explicit control schedule on the M7 agent, retain its current [0]
default, and reject schedules without an initial control, duplicates, invalid
cycles or insufficient worst-case token and node capacity to reach the last
scheduled control. The existing runtime may drain a remaining control early
after an unrelated stop or failure; comparison evidence must distinguish
planned timing from observed timing and must not label an early drain as the
planned after-cycle measurement.
The timing projection reconstructs committed cycles from the run journal and
checks each increment against matching candidate evidence and decision records.
Those records are produced by the same run; their internal hashes alone are not
an external attestation. The comparison report must retain the original
journal and separately audited physical and currency receipts.
The frozen agent contract and summary must include the exact schedule. Legacy
runtime and existing pilot defaults remain unchanged.

Before any paid comparison, a separate runner must freeze task/data identities,
both profiles and execution order, shared CNY ledger, model alias, price and
all budgets; it must record failures and independently audit receipts and
official scores. Existing MLE results have already been observed and are not a
pre-result registration for this new comparison. Local seed controls the data
split and search, not provider randomness. Equal budget does not guarantee
equal main calls: extra control reservations may reduce main-search capacity,
which is part of the measured overhead. In the current synthetic 3-iteration
fixture, the shared node cap admits three main calls and two controls instead
of four main calls and one control. The real run must report observed counts;
the fixture is not a benchmark result. No statistical or broad governance
benefit claim follows from a small pilot.

Implement the comparison as an explicit `governance-intensity` pilot mode with
arm labels `one_control` and `two_controls`; both launch `variant=full` and
their frozen profiles differ only in control schedule. Keep the existing
baseline/full mode and its report schema unchanged. The comparison mode must
preserve the pilot's preflight, separate anonymization keys per task/seed,
one-shot output, independent receipt audit, stop-on-uncertainty, and grade only
after all runs stop. It must reject a run as a valid scheduled pair if the
additional control was drained early. Reports use comparison-specific delta
field names, never the old baseline/full interpretation.
The public comparison runner holds the existing cooperative campaign lock for
the whole comparison. The grading gate rechecks the original campaign for
unresolved or protected currency immediately before scoring. A process that
ignores the cooperative lock is outside this coordination guarantee; the
campaign's own transactional currency cap remains authoritative.

Source checks compare tracked checkout bytes and child imports with the frozen
commit at specific times. They do not attest the executed runtime: normal Python
startup can load site hooks before the child checks itself, and dependencies
are not pinned by these checks. A trusted bootstrap and dependency identity are
required before presenting a paid run as source-bound benchmark evidence.
Accordingly formal comparison preflight fails closed until those controls are
implemented; the synthetic protocol fixtures remain available.
An isolated bootstrap now checks a frozen digest of installed dependency roots,
disables Python site initialization, redirects source bytecode caches and uses
stdlib-first imports. A local loopback fixture exercises the governance agent
under that bootstrap. This does not yet exercise the public formal comparison
entry end to end; interpreter, standard/native libraries and the host remain
trusted rather than comprehensively attested. The formal gate remains closed.
Fixture comparisons use a newly created private ledger, a literal loopback
provider address and a fixture-only credential. The public fixture entry rejects
caller-supplied ledgers so a test cannot accidentally modify a campaign ledger.
The fixture child receives an explicit environment; this prevents inheritance
of unrelated environment variables but is not file, network or process isolation.
