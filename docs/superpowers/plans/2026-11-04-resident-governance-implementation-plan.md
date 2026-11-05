# Resident controls and seven-account governance implementation plan

> **For agentic workers:** Use superpowers:executing-plans with TDD and one fresh final review per independently reviewable implementation stage. Implementation is in the isolated `codex/resident-governance` worktree; the earlier clean v71 acceptance is retained as failed evidence. User priority defers the next paid pilot.

**Goal:** Make opt-in configured Framework runs execute and account for resident independent random-search controls, with protected physical and shared monetary capacity, isolated inputs, recoverable invocations and live recomputable evidence.

**Architecture:** Extend the existing AssemblyConfig and HierarchicalBudget; keep Framework.evolve/inspect/replay and canonical Candidate/Proposal/EvidenceRecord. Main and controls use one governed invocation service and the same physical settlement authority. Control sessions are built from explicit registered factories, not copied from mutated live main adapters. Root audit reads the complete journal; soft components receive restricted views.

**Tech Stack:** Python standard library, existing registry and X1 journals, native and worktree execution adapters, current currency authority in the MLE adapter.

**Spec:** `docs/superpowers/specs/2026-11-04-resident-control-design.md`, `docs/ABSTRACTION_ALIGNMENT.md`, `autoresearch-fw/RUBRIC.md` C1–C4.


## Execution record (2026-11-04 development window)

The user requested parallel implementation instead of waiting for another paid experiment. Budget authority, fresh-session configuration and reference research were developed independently; runtime integration remained one shared implementation. No credential contents or live campaign ledger were copied or changed.

- Implemented: strict opt-in config; seven account projections; atomic future obligations; fixed main allocation; fresh factories and lane store views; native/worktree resident scheduling; typed pre-dispatch refusal; known-failure cost retention; native declared-state adoption; real SIGKILL boundary tests; read-only outcome replay; live cross-record audit.
- Provider receipts carry request hashes, run/lane/slot/intent/ordinal and frozen adapter identity. Their ordered digest is sealed into the existing physical settlement chain. Post-call binding identity survives a completion crash; known breaches retain actual charges and durably block both lanes.
- Implemented separately: explicit schema-2 CNY journal migration and protected obligation conversion, with schema-1 policy/history preservation and old-reader rejection. This was exercised only on test ledgers. **The provider bridge is not implemented.** Core rejects external monetary capabilities; no formal paid protection or real IID claim is enabled.
- Fresh final review found five Important issues, all reproduced before fixes: receipt deletion accepted by audit, post-call binding drift lost after crash, bound breach reported as protected, nested evaluator-provider receipts not adopted, and phase reservations below known minimums. The focused regressions now pass. Additional onboarding recovery exposed a lost frontier store view; declared native domain state also required terminal adoption. Both have regression coverage.
- First project-wide validation found a dependency cycle between the physical budget and its governance projection. Pure shared value contracts now live in `budget_contracts.py`; the unchanged static axiom check passes. The failed validation output is retained separately.
- Verified on implementation `bedc5b3`: 2,000 Linux tests, 64 tooling tests, all static axioms, package build/import verification, and checkout-external installed-wheel pause/resume/recorded replay. Clean unchanged v71 acceptance passed all 42 checks in 717.642 seconds; exact original bytes are archived with `m0/verifier/v72/v71-provenance.json`. The implementation branch was pushed. Hosted CI and the additive v72 candidate have separate evidence and must be reported at their actual terminal status.
- Stage 4 remains partial: the offline versioned CNY authority is implemented, but the provider bridge and dual-authority crash protocol are not. Stage 7 formal paid experiment remains open; the user deferred the third pilot.
- The original checklist below retains mixed or broader requirements as unchecked when only a subset is implemented. Architecture review is archived at `docs/review/2026-11-04-governance-depth.md`; it does not claim A7's whole-repository 1:3 condition is met.

Rulings: controls use an empty frozen initial context plus original task; unsupported external authority capability fails preflight; known invalid command identity is an integrity stop (canonical FAILED_TO_RUN remains a failed sample that drains); main cannot consume unused control slack; no arbitrary factory sandbox, supplier IID proof, exactly-once external side effects or power-loss guarantee is claimed.

## Fixed contracts and scope

Absent `governance` must serialize exactly as before, retain composed-v6 identity and all old behavior. Enabled identity is `composed-v7-governed`. Do not convert an old checkpoint to governed mode. All configuration remains finite JSON and registered names; no import paths, dynamic expressions, or model-supplied accounting labels.

The optional root `governance` object has exactly:

```json
{
  "schema_version": 1,
  "controls": {
    "after_main_cycles": [0, 2, 4],
    "seed": 1,
    "provider": {"name": "registered-fresh-provider", "options": {}},
    "domain": {"name": "registered-fresh-domain", "options": {}},
    "operator": {"name": "draft", "options": {}},
    "request": {"fidelity": "dev", "split_id": "dev", "seed_set": [1]},
    "reservations": {
      "operator": {"token": 1000, "node": 1, "eval_count": 0},
      "evaluation": {"token": 0, "node": 0, "eval_count": 1}
    }
  }
}
```

The numeric example is a controlled-fixture configuration, not a sufficient allowance for DeepSeek. The schedule is a nonempty strictly increasing integer list, starts at0 and cannot exceed max_generations+1. `0` means before any main cycle; `2` means after two committed main cycles. One draw per listed position; no redraw on failure. Seed is a nonnegative integer. Only a parentless operator is admitted; control evaluation uses a frozen dev request, with no resume_from or adaptive rung. Reservations explicitly cover exactly every configured physical unit. Unknown fields, omitted units, unsupported factories, impossible holdback and missing bound/currency capabilities fail before any provider or evaluator call.

Control provider/domain factories are registered through existing Registry.register. They receive a BuildContext with new optional `invocation_scope` and `governance` fields; default None preserves old callers. Control context has `llm=None` and `evaluator=None` until its own provider/domain are built: the factory does not receive live main adapters. Use existing assembly executor configuration with a control-specific operation/workspace namespace. No new registry component kind or Framework method is added.

`Registry.build_control(assembly, context, slot)` builds only the selected provider/domain/operator/executor, with all specs validated before any constructor. Each slot gets fresh semantic instances, distinct from main and every earlier slot. Functions/objects are not silently deep-copied. A default provided/native adapter without an explicit fresh factory is rejected in this mode, with a useful preflight error. Immutable datasets, transport pools and one currency authority may be shared under the factory's explicit contract; conversational state, random counters, output caches and mutable evaluator/search state are not implicitly shared.

The provider's `governance_binding()` declares finite JSON sampling parameters actually applied, fresh-session contract, supported request bounds and external capacity authorities. Before stage2 code starts, specify and test the exact versioned binding/quote payload fields against the selected adapter implementations; the method name alone is not a complete wire contract. A supplied temperature that the service ignores cannot serve as an IID guarantee. A seed sent only as a nonce is not evidence of independent model draws. The runtime verifies frozen parameters, namespaces and observed identities; it cannot prove a black-box service's randomness or a malicious trusted factory's hidden global state. Report supplier assumptions separately from enforced input/state isolation. Unsupported sampling contracts fail formal preflight rather than certifying fake IID-RS.

## Cost authority and protection

Accounts are exactly explore, exploit, reeval, control, repair, handoff, overhead. They are projections of existing settlements, not extra charges. In governed mode an intent gains `lane`, `control_slot` and a derived `account`. The caller cannot assign an arbitrary account:

| Invocation | Account |
| --- | --- |
| Main planning, observe/ideate/select and absorb hooks | overhead |
| Main parentless proposal and its first dev evaluation | explore |
| Main one/two-parent proposal and its first dev evaluation | exploit |
| dev_baseline, anchor, admission, final evaluation | reeval |
| Frozen control proposal and control dev evaluation | control |
| No explicit repair or handoff operation implemented | zero repair / zero handoff |

Failures retain original attribution. Every actual physical cost remains fully charged; no estimate, clipping or reclassification hides a breach. Multiple provider calls in one hook use the same invocation identity and increasing ordinals, and settle once. Unresolved costs stop both lanes.

`HierarchicalBudget(..., governance=None)` keeps old construction valid. `reserve_operation(..., lane="main", control_slot=None)` derives and validates account. Add `protect_controls(plan)` and `reserve_control_operation(slot_id, phase, candidate, request=None)`. Protection is a journaled capacity obligation, not spent money and not a permanently open call. Main quotes subtract outstanding control obligations; converting a slot phase to a real reservation happens inside the existing budget lock in one reduction step. The converted portion cannot be double counted or transiently exposed to main. On known failure, unused evaluation obligation is explicitly cancelled with the slot's failed outcome; failure stays in the sample set. Future slots remain protected. Direction/candidate ceilings and each physical unit remain independent. A control dev intent validates against its frozen control request rather than the main adaptive fidelity rung; control calls cannot advance main direction counters.

A protected quote must cover a defensible adapter total-call bound, including input, output and billed categories. Main's remaining quote cannot consume control holdback. The DeepSeek estimated UTF-8 policy does not qualify as a formal hard bound. Its model-capacity policy may qualify under documented service limits but requires a deliberately declared larger physical allowance; no completed failed run or authorized campaign amount is rewritten to make it fit. Admission drift/actual overrun invalidates protection, charges the original account and stops both lanes.

Shared currency protection is necessary whenever a provider has an external spending authority. Add a generic adapter capability with operations `protect_run(run_id, plan_ref, obligations)`, `admit_call(run_id, lane, slot_id, call_binding, bound)` and `audit_run(run_id, plan_ref)`. The MLE implementation remains in cny_budget.py/provider.py; no CNY conversion enters core. Extend the existing journal additively to represent future obligations, conversion and cancellation, retaining all old charges/policy identity and refusing unsupported event versions in old readers. Before stage4 code starts, finalize the versioned event schemas and migration/recovery state table against cny_budget.py; this draft does not yet authorize a live ledger migration. Never modify the live attempt3 ledger while its frozen old reader is running. A migration is a separately tested lifecycle change, not a new budget or reset.

Cross-authority reservation is not a distributed atomic transaction: journal preparation identities, preserve any unresolved reservation after a crash, and never issue HTTP until both physical and currency admission have committed. On recovery verify both authorities before adoption/cancellation. A capability-less provider cannot be formally protected merely because physical token capacity is available.

## Input isolation and durable invocation

Freeze initial task, allowed initial public ContextPack, operator/distribution settings, exact evaluation request, slot IDs/seeds, request templates and capacity obligations before the first main call. Controls receive no main parents, current budget usage, search memory, learned skills, adaptive scores, prior control outputs, admission data or hidden final scores. `OperatorRequest.cycle=0` within each independent draw; slot/candidate identities stay in metadata and must not perturb prompt bytes unless the frozen sampling contract explicitly defines that random variable. The draft prompt path currently keeps proposal ID out of the model prompt; preserve that separation.

The current registry passes a shared root store to all factories. Governed mode must replace that for soft components: `LaneStoreView` exposes only allowed lane/component records and rejects unauthorized writes. Main policy cannot read control outcomes; control components cannot read main or audit records. Only runtime/budget/executor authorities retain root-store access. This prevents accidental/declared-interface leakage, not arbitrary malicious Python access to the host filesystem. Both view restrictions and exact frozen prompt/context hashes are audited.

Create `GovernedInvocation` in `core/composition/governed.py`, composed by ComposedRuntime rather than another runtime mixin. It owns lane/slot/phase/ordinal binding, provider metering, terminal evidence adoption and settlement sequencing. It uses existing executor/domain protocols and canonical evidence. Main and control operator/evaluation calls both route through it when enabled. Controls bypass frontier, memory absorption, proxy calibration and M9 admission entirely; their evidence remains under control records and never becomes a main parent or incumbent.

Persist each provider outcome before downstream actions: returned text, typed known refusal and known-cost failure have distinct whitelisted outcome records; unknown usage remains unresolved. Do not stringify arbitrary exception objects or retry a start without an authoritative result. Store result artifacts privately with content hashes, exact usage, adapter binding and request hash. Native evaluation can adopt a persisted terminal canonical EvidenceRecord; a crash during an opaque native evaluation without durable terminal evidence remains blocked. Worktree evaluation adopts the existing validated operation result. No exactly-once external effects or power-loss durability is promised.

## Scheduling, inspection and replay

Run slot0 before main. Execute later slots after their frozen committed-cycle positions. Ordinary main exhaustion/convergence or a known pre-dispatch capacity refusal drains remaining controls; explicit checkpoint pause does not. Integrity/unknown-cost/bound violations never trigger drain. Introduce a typed internal stop disposition rather than matching human-readable strings. Persist slot transitions `pending -> proposed -> evaluated|failed` (unresolved is not terminal) and cancellation reasons; resume adopts already completed work without paid repetition.

`inspect()` recomputes seven-account reconciliation and baseline residence from the current authoritative journal every time. Missing/failed/incomparable controls remain explicit; no cached success. Report account coverage, planned/completed/failed/unresolved slots, preserved capacity, sampling assumptions and violations separately. C1/C3 formal status requires every required condition; residence does not assert superiority, B1/B2 success, invoice verification or C4 replay.

Governed `replay()` must use recorded provider/evaluator outcomes to reconstruct deterministic state without new paid calls. Keep re-experimentation distinct from evidence replay. Snapshot and receipt-chain anchors, request/ordinal/lane bindings and canonical artifact/evaluation identities must match. A missing, altered or extra outcome fails replay; it must not fall back to live HTTP. Real currency authority is read-only during replay; reconstructed physical/account projections do not create new financial charges. Existing ungoverned replay stays compatible.

## Implementation stages and verification

### 1. Strict config, account mapping and protected physical capacity

Files: contracts.py, registry.py, defaults.py, budget.py; new governance.py. Tests: new test_governed_config.py and test_governed_budget.py; retain every existing config/budget/recovery test.

- [x] RED absent-key byte equality; invalid schema/unknown factories/duplicate schedule/boolean counts/incomplete baskets fail before constructor calls.
- [x] RED journaled main explore/exploit/reeval/overhead and control attribution; all seven totals equal one global actual total per unit. Rehashed wrong account/lane/slot cannot replay.
- [x] RED main cannot consume future obligations, atomic obligation conversion has no free-capacity window, concurrent reservations remain serialized, true actual overrun preserves bill and invalidates protection, unknown costs block both lanes.
- [x] Implement validated GovernanceConfig and deterministic frozen ControlPlan; extend HierarchicalBudget reducer/checkpoints conditionally. Run entire existing budget/config suites, then complete project checks before claiming this stage complete.

### 2. Fresh sessions and lane input isolation

Files: registry.py, contracts.py, provider.py; new governance.py lane views/session builder. Tests: test_governed_sessions.py.

- [x] RED uncopyable provider succeeds through a fresh registered factory; reused main/control raw adapters are rejected before calls. Stateful evaluator/provider fixtures cannot leak counters/history across draws.
- [x] RED poisoned main memory/admission/control result records are unavailable to inappropriate factories/hooks and do not enter control prompts. Initial context, prompt/config hashes and actual sampling contracts remain fixed.
- [x] Implement preflight building of declared sessions, namespace bindings, restricted store interfaces and explicit capability failures. Preserve benchmark knowledge restrictions and existing six-kernel public abstraction.

### 3. Shared governed invocation and terminal recovery

Files: new governed.py; runtime.py, hierarchical_runtime.py, recovery.py, worktree.py as required. Tests: test_governed_invocations.py, existing composed worktree tests.

- [ ] RED both main/control calls use one reserve/start/outcome/settle identity. Multi-call hooks retain earlier charges on refusal; failure cannot relabel cost. Include explicit crossover refusal and custom multi-call operator-stop cases deferred by v71.
- [x] RED actual SIGKILL boundaries around start, known success/failure, physical settlement and checkpoint; missing authority blocks both lanes, recorded outcomes produce no repeat HTTP/evaluation. Native opaque in-flight evaluation remains explicitly unsupported rather than retried.
- [x] Implement private shared orchestration. Keep successful legacy event shapes and ungoverned v6 identity intact. Verify real worktree and native public Framework entry paths.

### 4. Shared external currency capacity

Files: cny_budget.py, provider.py, currency integration tests; no mutation of a running frozen campaign.

- [ ] RED old ledger rows/policy identity/cumulative spend survive additive migration; no fresh budget is created. Formal controls cannot be scheduled against a budget main may exhaust first.
- [ ] RED crash windows between physical/currency obligations, conversion, response receipt and settlement; independent authority audit detects missing/cross-run obligations and preserves unknown calls.
- [ ] Implement provider capability adapter and existing-authority journal extension; test old immutable receipts with explicit reader-version handling. Rehearse migration on a verified copy before any authorized live ledger transition.

### 5. Resident scheduling and public result boundaries

Files: runtime.py, governed.py, governance.py. Tests: test_governed_runtime.py and test_governed_worktree.py.

- [x] RED initial/interleaved schedule, ordinary early-stop drain, explicit pause without drain, failure in predetermined sample set, integrity failure stops all work, repeated resume does not reissue calls.
- [x] RED controls absent from frontier, parent selection, memory, proxy fitting, admission and final main selection; scores use the frozen comparable request. State and capacity remain auditable even with failed controls.
- [ ] Implement composed-v7-governed scheduler and checkpoints; at least native and worktree examples use exactly the same governance schema.

### 6. Live audit and evidence replay

Files: governance.py/governed.py/runtime.py and reporting docs/examples. Tests: test_governed_audit.py, test_governed_replay.py.

- [x] RED post-run appended/tampered evidence invalidates fresh inspect; account totals, control slots, stop disposition and receipt coverage are independently recomputed.
- [ ] RED non-deterministic remote-like provider fixture replay consumes recorded outcomes without network, preserves canonical results/receipt chain and detects wrong request, missing result, altered context, extra ordinal or changed adapter. Currency journal bytes remain unchanged.
- [ ] Implement explicit separate C1/C2/C3/C4 reports, no fake aggregate pass or superiority inference.

### 7. Versioned and real evidence

- [ ] Fresh independent review, all historical tests/verifiers retained, full Linux/portable tooling/build/examples and additive next-version acceptance from clean source.
- [ ] Public API usability from an installed artifact; two execution adapters, boundary failures and replay demonstrated. No private credential/data/result bodies in public artifacts.
- [ ] Only after complete capability checks: measured formal run using an explicitly frozen policy and the existing authorized monetary budget, with resident IID-RS and account reports. Earlier diagnostic runs remain labelled nonformal; no retroactive certification.
- [ ] Continue A1–A7, B1–B5, C1–C4 and D obligations. This plan alone does not establish a release candidate or a unique capability other repositories cannot reproduce.
