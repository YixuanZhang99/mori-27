# OpenEvolve paired-cell wall-clock implementation plan

> **For agentic workers:** Use superpowers:executing-plans and test-driven-development. Finish integration before describing the cap as enforced.

**Goal:** Apply one auditable total elapsed-time limit to each vendor/Mori cell without losing or repeating billed work.

**Architecture:** A durable per-cell deadline authority binds cell identity, boot identity, monotonic start and fixed duration to a dedicated continuation journal, separate from the Framework replay cursor. Both arm supervisors must share it with admission and the currency bridge. The supervisor owns worker lifetimes; actual accounting remains with the existing physical journal and campaign ledger. An unverifiable restart or unfinished operation remains unresolved.

**Tech stack:** Python 3.12, continuation journal, existing physical/currency authorities, Linux process supervision.

**Spec:** `docs/superpowers/specs/2026-11-05-openevolve-design.md`, paired pilot wall-clock paragraphs.

## Global constraints

- One deadline begins before setup/control for either arm and includes final validation; the draft cap is 2700 seconds.
- Never retry an uncertain provider call or reset the ¥200 campaign. Preserve paid and unresolved evidence.
- Never place credentials in workers, plans or journals. This plan does not authorize a live run before all pilot gates pass.
- The initial native clock implementation is Linux-only (`CLOCK_BOOTTIME` and boot UUID); other platforms fail closed, rather than claim a suspend-aware deadline.
- The deadline journal must be dedicated to clock records and never share a Framework replay cursor.
- The original campaign journal anchors the first creation and each observation head. The pilot must validate that ledger and cell identity against the frozen matrix before using this authority; a missing journal alone never establishes that a cell is new. A crash between clock-journal and campaign-head writes remains unresolved.
- Both arms enforce the same mechanism and cap; results arriving after expiry are not eligible candidates.

## Review focus

- A process restart on another boot must not reset or extend a deadline.
- Checks and admission must share a serialization boundary; a call cannot be sent on an expired check.
- A started provider request can finish late and its charge must still settle; its result must not resume search.
- A killed or escaped descendant must make the cell unresolved unless termination is verified.
- A corrupted, missing or duplicated journal boundary must fail closed before work starts.

## Task 1: Durable time authority

**Files:** Create `m0/zoo/circle_packing/cell_deadline.py` and `m0/tests/test_openevolve_cell_deadline.py`.

**Interface:** `CellDeadline.start(store, *, lifecycle, cell_id, plan_ref, seconds)` and `CellDeadline.restore(store, *, lifecycle, cell_id, plan_ref, seconds)` create or recover exactly one frozen deadline. `remaining()` returns finite nonnegative seconds; `check()` raises `DeadlineExpired` after expiry and raises on identity, journal, boot or monotonic regression. Use the current system boot identity and monotonic clock; journal a single initial authority and reject duplicate, altered or malformed boundaries.

- [ ] Write red tests for a real start/restore, expiry, duplicate or altered identity, monotonic regression and changed boot.
- [ ] Implement and run focused tests. The authority alone is not a live pilot or a claim of hard time enforcement.

## Task 2: Admission and accounting integration

**Files:** Modify the existing vendor dispatch and currency bridge, plus Mori governed runtime entrypoints and their relevant tests.

**Interface:** Supply the same deadline authority for the entire cell, serialize checks with the respective physical reservation and check again immediately before transport. Preserve existing refusal, recovery, known-bill and pending-call semantics; a late outcome is settled and barred from candidate use.

- [ ] Add tests for both arms with expiration before reservation, between reservation and transport, during transport, and after a response. Verify no late dispatch and no missing/double charges.
- [ ] Implement against the existing accounting owners; rerun the old recovery and governance suites.

## Task 3: Process supervision and final audit

**Files:** Extend existing process supervisor and pilot entrypoint; add integration tests.

**Interface:** The same authority bounds setup, control, controller worker, sandbox and final validation. On expiry terminate and verify every worker descendant or preserve an unresolved terminal; restart never creates a new deadline. Export original timing, process and accounting evidence for independent recalculation.

- [ ] Add real-process tests for expiry during sandbox execution, timeout between search and final validation, child escape/unresolved handling, supervisor restart and reboot identity mismatch.
- [ ] Wire both arms into an executable frozen plan; run offline paired integration, independent review and full checks. Until then retain `draft_not_executable` and no paid launch.
