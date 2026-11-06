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
Mori's frozen final audit now uses the same independent upstream cross-check
on its original selected stage; it does not rerun candidate code or call a
model. The validator implementations are bound in the domain identity.
When Mori's final audit completes, its Framework evidence exposes
`test/sum_radii` and `test/validity` alongside the normalized `test/score`.
These values come from the selected candidate's frozen, cross-checked geometry;
an absent or skipped final audit must not be reported as a benchmark score.
The Mori fixture report exposes those values and the frozen public-range
threshold as `final_measurement`; skipped and failed audits produce `null`.
Fixture measurements are simulated engineering evidence, not live results.

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

In the frozen paired fixture, the named reference worker receives the model
alias and maximum output allowance from the validated campaign plan. Both
worker reports expose those settings so the integration checks their equality.
This does not make the fixture a live entry point or establish score parity.

`launch_fixture_controller` starts the named Mori controller from a fresh
private directory after checking the original fixture campaign, cell clock,
frozen plan, source and runtime. Its process journal and deadline guard retain
execution evidence. It claims the cell before process launch; a duplicate or
interrupted claim cannot silently start the controller again. It does not
certify all descendants or authorize live use.
`mori_controller.build_controller` shares the governed Framework composition
between the fixture and a future live supervisor. It takes the credential in
memory, not in the frozen configuration, and does not itself start a search
or authorize a live pilot. It verifies the original ledger, campaign and cell
clock; fixture ledgers require loopback, while a non-fixture ledger requires
the provider URL frozen in that campaign.
`verification/test_mori_live_preparation.py` exercises the latter composition
with a disposable unmarked ledger and a fake key. It forbids provider and
sandbox execution and checks that no calls or charges occurred. This is a
preparation check, not permission to execute the draft or a live result.
The same verification module also runs six Mori rounds using the real-provider
configuration and a temporary unmarked ledger while intercepting transport and
blocking socket connections. It tests the real configuration path, simulated
currency accounting and recorded replay; it does not contact the provider.
It also exercises the reference controller with a test-only override of the
closed live gate, fake responses, and only local socket connections. The test
reconstructs the anchored selection and geometry without any new model or
candidate work; this is not a real result or a live readiness certification.
`build_reference_provider` prepares the reference-side transport for the
original campaign endpoint without sending a request. The existing reference
cell launcher remains fixture-only; preparation alone does not authorize a
real reference run. Its fixture authority also requires a separately created
fixture ledger and the fixed fake key before it can reserve or execute work.
Reference `live_preparation` can assemble real-provider authorities without
starting control, model or stage work. Preparation does write a durable
reference claim and protects currency in the supplied campaign, so use only a
dedicated temporary campaign for tests. Live work remains disabled until the
pilot readiness gate is implemented.
