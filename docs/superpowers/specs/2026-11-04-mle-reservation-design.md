# Variable-usage proposal reservation

The first real pilot on `5fa85d3` exposed a configuration mismatch: a CNY-authorized DeepSeek response used 3,190 input + 10,204 output = 13,394 tokens; the MLE profile reserved only `60000 // 5 = 12000`. The physical ledger correctly settled the actual cost and halted on overrun before evaluating the first candidate. This is a failed run, not a missing invoice or model quality result.

Keep the running experiment and its evidence unchanged. This repair affects a future source version. User authorization covers autonomous repository repairs; implementation and review proceed without another routine setup question. Paid reruns, if needed after full validation, must reuse the existing CNY 200 campaign.

## Decision

Add an explicit optional `reservation_modes` field to hierarchical budget options. Initially the only operation supported is `operator`; each configured physical unit can select `remaining`. The existing numeric reservation remains its minimum admission requirement. At reservation time, under the same budget lock, reserve the largest available amount allowed by all applicable global/direction/candidate limits, after settled and open usage. If that amount is below the numeric minimum, ordinary admission rejects without a paid call. Other units and operations retain fixed reservations.

Example: `reservation_modes: {operator: {token: remaining}}`. For a 60,000-token shared scope with a 12,000-token numeric minimum, the first quote is 60,000; after settling 13,394 it is 46,606. Actual costs are charged once. Unused headroom is released on settlement. Concurrent reservations cannot both claim the same headroom; unknown or overrun state still blocks new work.

Alternative: raising the fixed per-call quote merely moves the premature-stop threshold and can reject later calls despite sufficient actual headroom. Alternative: allowing settlement overruns to continue weakens an existing invariant. The chosen policy keeps the reservation truthful and the guard intact. This is a generic physical-budget allocation policy; service pricing stays in `zoo`.

Journal reconstruction must recompute the quote from the state immediately before each reservation, including prior open operations. Rehashing a forged amount must not make it valid. Existing configurations without the option retain their exact serialized identities and behavior.

Enable this policy for both MLE profile arms. Keep task/model/output limits, iteration ceilings, currency policy, actual-usage validation and terminal scoring rules unchanged. This does not provide an exact pre-request prompt-token counter: a supplier response exceeding the remaining total token budget still retains known costs and fails closed. The CNY reservation remains the separate pre-request monetary safeguard.

## Evidence required

- Reproduce the 13,394-token first proposal through public Framework execution and local HTTP, with no external service, then obtain a valid frozen submission after repair.
- Verify literal 60,000 → 46,606 quote amounts and unchanged actual charges; mixed-unit/scoped/open-reservation/floor cases.
- Restore exact journal/checkpoint state; reject rehashed forged remaining quotes; preserve unknown-usage and true-overrun stopping.
- Complete the existing MLE and hierarchical/recovery regressions, full Linux suite, build/import/axiom checks and independent review before real rerun.
- Retain the original failed pilot and compare attempts without selecting away failures. A new versioned verifier must preserve authentic historical v69 evidence; no earlier certificate certifies this repair.

## Validation-discovered X1 prerequisite

Final Linux validation found a separate pre-existing race: the external batch recovery observer parsed a partially appended JSONL record from a live owner process. The suite retained 1 failure and 1,815 passes. A per-instance thread lock cannot coordinate a second process or store instance.

Cooperating Mac/Linux store instances now require an exclusive descriptor lock through append flush/close and a shared lock while copying the readable prefix. Iteration releases the file/thread locks before yielding, so callers can append without deadlocking or extending that snapshot. Persistent malformed rows still raise, never disappear. This uses standard-library `fcntl`, introduces no new public entry point and does not claim Windows support, fsync durability, crash-atomic large records, protection from non-cooperating writers, or a subscription protocol. Reading a snapshot retains its raw lines in memory; this tradeoff avoids holding a process lock across arbitrary caller code.

Deterministic tests pause the real append path after half a record, then start a separate reader/writer. They must wait and subsequently observe whole records. A separate child verifies append during snapshot consumption does not deadlock; persistent malformed tails must remain errors. The original full-suite failure must also pass after repair. This prerequisite is included in v70's explicit coverage.
