# Protected control obligations on the existing CNY authority

This is an offline-tested authority contract. The provider bridge is not implemented, and the framework still rejects providers declaring an external currency authority. No live campaign ledger was read, migrated, copied, reset or charged during this implementation.

## Compatibility and migration

`CampaignBudget` retains the original policy row, policy hash, campaign ID, authorization amount, prices and prior event bytes. The policy remains schema 1 because its pricing meaning does not change. New journal events explicitly use schema 2.

`enable_governance(expected_policy_sha256=..., expected_head={"seq": n, "sha256": h})` performs the lifecycle transition. It requires the exact current head and policy and refuses any pending call. It appends a marker inside the existing SQLite transaction. It does not grant money or change old rows. A frozen original reader rejects this marker, so old writers cannot silently ignore future obligations. There is no automatic migration in construction, protection or admission.

Rehearsal on an authorized, verified ledger copy and quiescence of all old readers are prerequisites for a future real migration. This implementation does not authorize that migration.

## Public adapter API

- `quote_call(output_allowance)` returns `{"schema_version":1,"output_allowance":n,"reserved_micro_cny":m}`. The amount is full input context capacity times the frozen input rate plus the output allowance times the frozen output rate. Output allowance is a positive integer within the existing policy maximum. An estimated input length is not accepted as this bound.
- `protect_run(run_id, plan_ref, obligations)` freezes a nonempty list of `{"slot_id":s,"phase":"operator"|"evaluation","ordinal":n,"bound":quote}` entries. Slot/phase/ordinal tuples must be unique. The method sorts them canonically, refuses impossible capacity, and is idempotent only for the identical run, plan and obligations.
- `admit_call(run_id, lane, slot_id, call_binding, bound)` takes `call_binding={"call_id":c,"request_sha256":h,"phase":p,"ordinal":n}`. Main uses `lane="main", slot_id=None`; control uses `lane="control"` with its frozen slot. A control call must match an untouched obligation and fit its bound. Conversion and the real reservation commit in one transaction. All calls share the existing one-pending-operation constraint.
- `settle(call_id, usage, response_sha256)` remains the settlement interface. Governed calls record all known input/output charges even when actual usage violates the declared bound. A violation permanently blocks new main and control calls. Legacy schema-1 calls retain their original settlement behavior.
- `cancel_control(run_id, slot_id, reason=...)` cancels only untouched obligations. It refuses cancellation while any call is pending. Settled charges and admitted calls cannot be cancelled. Identical completed cancellation is idempotent.
- `audit_run(run_id, plan_ref)` reduces the current journal each time and returns run and campaign charges, outstanding obligations, pending calls, per-slot statuses, breaches and the current head. It does not write ledger bytes. The caller must compare currency call IDs and request bindings with its physical authority.

Run IDs use the existing 64-character hexadecimal identity. Plan references use `sha256:` followed by a 64-character hexadecimal digest. Ordinals are nonnegative integers. Reasons are bounded text. No arbitrary currency, exchange-rate or model expression enters the API.

## Version-two event payloads

Every new event has integer `schema_version: 2`. Event rows retain the original sequence/hash-chain format and head table.

| Kind | Other exact fields |
| --- | --- |
| `governance_enabled` | `previous_head`, `policy_sha256` |
| `protect_run` | `run_id`, `plan_ref`, canonical `obligations` |
| `governed_reserve` | `call_id`, `run_id`, `plan_ref`, `lane`, `slot_id`, `phase`, `ordinal`, `request_sha256`, `output_allowance`, `reserved_micro_cny` |
| `governed_settle` | `call_id`, validated `usage`, `response_sha256`, `upper_bound_micro_cny`, boolean `bound_violation` |
| `cancel_control` | `run_id`, `plan_ref`, `slot_id`, `reason` |

After migration, legacy `reserve` events also subtract all outstanding control obligations. A legacy caller cannot spend the protected capacity by omitting governance metadata. All readers validate the complete resulting journal before a transaction commits.

## Recovery table

| Last committed state | Recovery behavior |
| --- | --- |
| Before protection | No obligations exist; explicit protection can be attempted. |
| Protected obligation, no admission | Capacity remains held; the exact frozen call may be admitted. |
| Admitted call, no authoritative usage | Its reservation remains pending; both lanes refuse further admission. No automatic retry or cancellation is permitted. |
| Settled call | The full known charge remains; only identical settlement can be adopted without another event. |
| Cancelled untouched obligation | The capacity is released; that obligation can never be admitted. |
| Settled bound violation | The full known charge remains and all future admission is blocked. |

Protection is capacity, not spending. Outstanding obligations plus a real pending reservation are never double-counted. The system cannot atomically commit across SQLite currency and the physical journal: the future bridge must persist preparation identities, obtain both admissions before HTTP, and preserve any unresolved reservation if either side crashes. The tests establish process-crash behavior, not universal power-loss durability or exactly-once external effects.

## Evidence and remaining limits

Offline tests cover old charge/history preservation, anchored migration, changed plans, strict bounds, concurrent main/control admission, shared runs, cancellation, full overrun charges, recomputed audit, semantically invalid rehashed events, and actual SIGKILL immediately after protection/admission/settlement commits. The frozen original schema-1 reader was also executed against a migrated temporary fixture and rejected the marker.

The hash chain and head detect damaged history; they do not prove resistance to an owner replacing the entire ledger and every external anchor. Supplier invoices remain unverified. The authority does not prove provider sampling independence. The provider bridge, cross-authority recovery handshake, installed-artifact exercise and a separately authorized real migration remain outstanding.
