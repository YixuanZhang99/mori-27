# OpenEvolve circle-packing fixture

The named runner exercises Mori's public Framework, the pinned OpenEvolve host
and the sandboxed 26-circle evaluator with deterministic synthetic patches.
It makes no model requests and its scores are **not benchmark results**.

From the repository root on Linux with the project's sandbox dependencies:

```bash
PYTHONHASHSEED=0 PYTHONPATH=m0 python -m zoo.circle_packing.runner \
  --output /tmp/mori-circle-fixture --seed 0 --iterations 1
```

The command emits JSON, writes a frozen configuration and terminal record, and
verifies recorded replay with zero external calls. Running the same command
again verifies and resumes the terminal without running the provider or
candidate evaluator. Changed configuration or incomplete output is rejected.
`PYTHONHASHSEED` must be set before Python starts for repeatable host behavior.

Live mode is deliberately unavailable here until the common currency and
physical budgets, independent upstream controller, comparison plan and evidence
export have been integrated and verified. Fixture metrics do not populate the
planned paired pilot results.

An independent offline host plumbing check uses the pinned upstream controller,
its process worker and the same stage sandbox with a synthetic client:

```bash
PYTHONHASHSEED=0 PYTHONPATH=m0 python -m zoo.circle_packing.host_reference \
  --output /tmp/mori-circle-host-fixture --seed 0 --iterations 1
```

This command passes only an allowlisted environment to the host worker; it does
not load credentials. It records fixture stage and message evidence for local
debugging. It is not the governed reference runner, does not enforce a paired
physical budget, and cannot be used to make a benchmark claim.

The local `HostBridgeClient`/`HostBroker` plumbing is tested with the real
spawned host and an existing currency bridge using a temporary test ledger.
The broker is only a transport: its caller must supply an authenticated,
durable physical-and-currency dispatcher. No such live dispatcher or full
reference recovery is enabled by this fixture.

`HostPhysicalAdmission` exercises the existing hierarchical budget and its
journal: it blocks a second call while a prior physical operation is open and
only settles against an original completed provider receipt. The experimental
`HostDispatchCoordinator` joins it to the CNY bridge and checks both authorities;
loopback tests include a spawned upstream worker and crash after admission.
`HostStageAdmission` separately charges each sandbox stage and checks the first
stage's geometry before authorizing the second. A local fixture routes the real
upstream worker's provider and cascade requests through both budget authorities
and audits their recorded stages. These components are not a complete live
reference runner: wall-clock limits, control execution, full run recovery and
end-to-end result export are pending.

`governed_setup` is an internal composition factory for the existing CNY
bridge and a fresh circle control. Its loopback tests cover role-bound requests,
settlement, unknown usage and recorded replay. It does not freeze a fair paired
plan or start a real run; the named runner continues to reject live mode until
the complete comparison and audit are ready.

`pilot_plan.build_draft_plan` computes a six-cell draft (three seeds times two
arms) from a verified campaign policy and explicit source/dependency hashes.
It records the proposed common numeric caps, but labels the result
`draft_not_executable`: reference-side enforcement and final source freezing
must be completed before it can authorize any call.

`host_runtime.build_reference_authorities` composes the existing reference
control, physical budget, currency bridge and stage router for one frozen cell.
It currently accepts only an explicit loopback provider and is an offline
fixture interface, not a live entry point. Its original campaign records one
authority per cell, binds the initial physical journal and records when work
starts. Initialization can resume before work starts; once work starts, the
factory refuses to reconstruct the authority until complete work recovery is
implemented. Use the returned context manager or call `close()` after work ends.
The new authority events use the existing campaign v2 journal; older readers
cannot read a campaign containing them. They have only been used in temporary
test campaigns. Full supervisor recovery and the paired pilot remain unfinished.

The optional reference-cell integration uses a local HTTP fixture and an
explicitly populated uv cache; it is separate from the default pytest suite:

```bash
cd m0
MORI_TEST_OFFLINE_CACHE=/path/to/uv-cache PYTHONHASHSEED=0 PYTHONPATH=.:tests \
  python -m pytest -q verification/test_reference_cell_locked.py
```

`host_runtime.run_reference_cell_fixture` joins those authorities to the named
offline worker and loopback broker. It checks the worker's reported selection
against measured, deadline-eligible stage records. Its output remains a fixture:
it is not an independently anchored final selection or a benchmark result, and
it does not provide whole-cell hard supervision or live-provider authorization.

The internal `reference_worker.run_reference_fixture` entry runs the upstream
fixture from a campaign-bound source snapshot through a local broker. It checks
a disposable broker capability with a no-dispatch handshake before consuming
the cell's worker claim. This synthetic fixture is not a live benchmark
entrypoint. A trusted caller supplies the actual in-process broker object and
capability; the fixture checks socket identity and the peer process before
sending it. A standalone probe does not authenticate an arbitrary service in
the same process. The worker can read the capability, which is not a provider
API key.

The offline reference evaluator records its physical stage receipt as an
OpenEvolve artifact, so the selected program can be associated with one
actual evaluation even when identical code is evaluated repeatedly. A scoped
adapter hides only this internal receipt from host prompt artifacts while
retaining other artifacts. The filter is process-wide during the fixture;
fixture calls are serialized, and unrelated same-process database callers can
also observe the filter. The named entry runs it in an isolated worker process. The receipt is a host-worker assertion joined to
physical records, not an independent final-winner proof or benchmark result.

The draft paired plan allocates a common token ceiling of 14 worst-case call
bounds per cell: two bounds remain protected for control and two are reserved
per Mori mutation across six configured iterations. This is a capacity ceiling,
not a grant of money; the original shared currency ledger still gates each
actual call, and budget, deadline, or other termination can stop either arm
before six iterations. No paid pilot is enabled by this draft.
Drafts with schema 1 produced by the earlier 4-bound formula do not validate under this
new schema 2 formula. Those drafts were used only with temporary fixture campaigns;
they cannot be resumed by this code. Do not reinterpret old evidence as the
new plan.

`snapshot_matrix` inventories the original six declared cells at an
independently pinned campaign journal head. `not_claimed` refers only to that
head; `claimed_outcome_unverified` does not say whether a cell completed,
failed, or is still running. Scores remain null until a separate terminal
result and its accounting and geometry evidence can be independently verified.
This read-only inventory does not authorize or start a run.

`recalculate_reference_snapshot` joins a pinned campaign, recorded worker,
physical stages and the original plan, then recalculates the
selected stage's geometry with both the shared validator and the pinned
upstream geometry function, then checks the predeclared public-range condition without
running the candidate or calling a provider. Its result is explicitly a
host-attested snapshot, not proof that the run ended or that the selection is
the final winner; fixture output is not a benchmark score.
The upstream cross-check validates the recorded coordinates independently of
the shared validator; it does not rerun the candidate or establish provenance
on its own. Borderline coordinates may be rejected when the two floating-point
implementations differ at the tolerance boundary.

`recover_reference_snapshot` reconstructs the original worker proof from its
bounded no-follow journal and execution-bound output files, then invokes the
same pinned campaign and physical-evidence recalculation. It starts no worker,
model or evaluator. Missing, changed or unanchored evidence is rejected; this
recovers a previously anchored snapshot, not interrupted work or a final winner.

The offline reference fixture freezes its host-reported selection after the
worker and broker finish, binds it to the prior physical snapshot and a fresh
on-time clock observation, and rejects later operations through that authority
and new currency reservations for that run. This is a trusted-host assertion;
it is not proof that every descendant terminated or that the cell is a live
benchmark result. A crash between the snapshot and freeze remains unresolved.
The new campaign event is used only by temporary fixtures and requires a reader
that understands it.

`mori_fixture_worker` is the named controller used by the frozen paired
loopback integration. It accepts only an explicit loopback HTTP endpoint and a
fixed fake credential, verifies the frozen source, runtime and original cell
clock, then runs the public Framework and its zero-external-work replay. It is
not a live entry point or proof of whole-cell supervision.
The controller requires a dedicated campaign created with `create_fixture`.
Its irreversible marker is written during creation, and an existing ledger
cannot be converted. Use this only for temporary test ledgers.
The governed currency bridge restricts marked campaigns to loopback providers;
older ledger readers do not understand the fixture marker event.
Temporary ledgers produced by the earlier experimental marker-after-governance
implementation cannot be reopened; recreate those fixtures. This does not
change existing unmarked campaign ledgers. The bridge's loopback restriction
alone does not prevent a caller from supplying a real key to a local service;
the named worker itself always supplies the fixed fake credential.
