# v72: resident controls and protected budgets

This version retains all 33 v71 command groups and their exact timeouts. Four additional command groups bring the expected successful total to 46 checks:

- Opt-in configuration, seven-account physical protection, and isolated sessions.
- Resident scheduling, native and real worktree recovery, integrity-stop boundaries, and recorded replay.
- Explicit currency journal v2 migration, shared campaign protection, known overrun charges, pending unknown usage, and semantic audit.
- The offline governed-controls example, including pause, resume and replay.

Certificates state the tested capability scope. Deterministic local fixtures do not establish IID sampling or superiority. The external provider/currency bridge is not implemented. No supplier invoice, live campaign migration, cross-authority atomicity, arbitrary native in-flight recovery, machine power-loss durability, formal release, or rubric A/B/C completion is certified.

The v72 provider admission report names its own command group; layered admission retains its separate group. Both require whole-run success.

## Historical preservation

All existing verifier source and archived evidence bytes are retained. `transition-baseline.json` records their hashes and hashes of the historical transition test method ASTs and exact method source. AST dump formatting differs between Python 3.12 and 3.13; the original 3.13 AST hashes are preserved as provenance, while interpreter-independent source hashes enforce unchanged methods. Removing the one exact approved historical-context `setUp` insertion must also reproduce the entire original test file byte-for-byte. The historical v71 scope unit test reads the exact archived wrapper from commit `53d2ba14dcc9b1575510a08333bfa08abac5dff7`; the new v72 scope test reads the actual active wrapper and controls.

## Archived v71 provenance

The complete unchanged v71 run passed on clean implementation `bedc5b31fe737dfd207fa8466f68fecb58c5c294`: 42 checks in 717.642 seconds. `v71-provenance.json` identifies that exact source commit, source-clean checks, original run ID, original console and summary hashes, and exact certificate/journal hashes. The archived files are original run bytes, not reconstructed JSON. The clean baseline 53d2ba1 run failed and must remain reported as failed. No targeted test result may be substituted for that full acceptance run, and a local run is not same-SHA remote CI evidence.
