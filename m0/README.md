# AutoResearch M0 — governed evolution kernel

> A small evolution loop with a ledger, receipts, and a resident baseline.
> 调度器发意图、预算器可拒绝、准入留票据、随机基线永远陪跑。

This repository implements the M0 kernel defined by `../autoresearch-fw/初版范围-v2.md`.
It is not yet the full v1.0 framework; protocol extensions and external benchmark
certification are tracked by `../autoresearch-fw/RUBRIC.md`.

## Quickstart (offline, no API key)

```bash
python3 -m pytest -q
python3 examples/toy_gepa.py
python3 examples/gsm8k_offline.py
python3 examples/funsearch_offline.py
python3 ci/check_axioms.py    # standalone static architecture gate
python3 verifier/v57/verify.py  # current gate; proposer direct seccomp + all prior behavior
```

The GSM8K-style example uses the real dataset evaluator, per-item gate, reflective
operator, ledger and token metering. Only the LLM endpoints are deterministic scripts.

## Public API

```python
from core.loop import Framework, LoopConfig

fw = Framework(proposer_llm, evaluator, LoopConfig(), "/tmp/my_run")
result = fw.evolve("Task description")
print(fw.inspect())       # governance + self-attestation view
replayed = fw.replay()    # certified rerun into /tmp/my_run/replays/replay-*; mismatch raises
```

Or compile a classic-system profile without kernel changes:

```python
fw = Framework.from_profile("gepa_reflective", proposer_llm, evaluator,
                            LoopConfig(), "/tmp/gepa_run")
```

Available profiles: `gepa_reflective`, `funsearch_island`, `map_elites_grid`. Island
registration, round-robin selection, elite migration and evolve-block editing are implemented.
The MAP-Elites profile consumes numeric `result.public["features"]` according to its declared
dimensions and uses one elite per cell for parent selection; these features never enter M9.

## Real OpenAI-compatible endpoint

```python
from core.llm import OpenAICompatibleLLM
from core.tasks.gsm8k import GSM8KEvaluator, load_jsonl

proposer = OpenAICompatibleLLM("your-model")
solver = OpenAICompatibleLLM("your-model")
evaluator = GSM8KEvaluator(load_jsonl("gsm8k.jsonl", limit=50), solver)
fw = Framework(proposer, evaluator, LoopConfig(total_budget=2_000_000,
               intent_cost=20_000, reeval_floor=100_000), "/tmp/gsm8k_real")
result = fw.evolve("GSM8K prompt evolution")
```

`intent_cost` is the reserve estimate; actual proposer + solver token usage is
metered and settled. Set a realistic reserve for your model and context size.

## Kernel map (K1–K6)

- K1 `core/operator`: draft + reflective improve; LLM proposes, code lands.
- K2 `core/policy` + `core/budget`: allocation intents, three-way rejection, R4 low-tier reissue.
- K3 `core/budget`: append-only ledger, reserve→settle, control lock, reeval floor, pre-call hard cap.
- K4 `core/operator/types.py`: proposed→applicable→runnable→admitted funnels.
- K5 `core/eval`: per-item flip-count gate, noise-floor-zero, receipts, stop table.
- K6 `core/loop.py`: resident IID-RS baseline on the locked control account.

`core/x1` is the append-only evidence store. `core/extensions.py` contains the
opt-in novelty gate and H2 monitor reference plugins. `core/archive.py` implements
island membership, migration and soft eviction; `core/budget/probe.py` computes
M3 health ratios and admitted-per-1k-token efficiency. Protocol extensions add
atomic multi-currency accounting, cascade evaluation, judge calibration, anchored
evaluator promotion, scoped memory, and physically separated ground/audit knowledge.
Explicit M2 extensions implement environment-fact debug and contract-bound
crossover with deterministic parent ordering and debug fallback. `core/frontier`
implements a multi-currency performance/cost Pareto view without changing M9.
`zoo/mle_bench_lite` pins the official 22-task snapshot, protects grading assets,
redacts search feedback, invokes official grading into an audit-only evidence lane,
and pairs measured host/governed runs under identical model and budget declarations.
`zoo/re_bench` pins the deprecated official seven-task METR snapshot, invokes only
`TaskFamily.aggregate_scores` on real Vivaria logs, and requires a complete paired
matrix before numeric comparison. See `CONTEXT.md` for the shared vocabulary.

## M7 isolated execution and X2 review

`core/executor` implements the SPEC execution boundary with real local git
worktrees. A `CandidateBuilder` writes the candidate into an isolated branch;
`eval_cmd` then runs under the declared fidelity, seed set and timeout. Successful
runs persist a resolvable commit and return one `EvidenceRecord`. Timeouts,
nonzero exits, missing required outputs and protected-path changes become
`timeout` / `failed_to_run` / `invalid` evidence instead of escaping as loop
exceptions. Protected files are hashed at startup and before merge.

`core/hitl` is the single X2 control channel. `auto` appends automatic approval
evidence; `review` returns pending until a named reviewer approves the exact
action and canonical payload hash. Approval is single-use, while pause/resume and
all decisions survive controller reconstruction from the append-only store.
Pass `HITLController` as the executor's `hitl` extension to prevent execution
before approval. Git worktree alone is artifact isolation, not a security sandbox.
For untrusted evaluations, pass `sandbox=BubblewrapSandbox()` to the executor. This
opt-in backend uses real bwrap namespaces, a private filesystem, read-only system/
protected/data paths, a writable candidate worktree, network isolation and a cleared
environment with only explicit non-sensitive `AR_*` evaluation variables. On x86_64 it
also installs the versioned dangerous-syscall seccomp denylist by default; explicit
`seccomp=False` disables only that layer. It is not a complete syscall allowlist,
complete resource-limit policy or hostile-kernel boundary.

`ExecutorPool` runs the blocking M7 backend under a fixed `max_inflight` quota.
`run()` returns exactly one matching EvidenceRecord; `run_many()` executes real
candidates in parallel, then invokes optional result callbacks serially in input
order for M1 absorb/StateApplier finalization. Duplicate active candidates are
refused, unexpected backend exceptions become failed evidence, and callback
exceptions propagate unchanged. `checkpoint_state()` refuses non-empty queued,
running or finalizing state. Shared worktree metadata, attempts/manifests and
JSONL evidence writes are locked; evaluation subprocesses still run concurrently.

`ProcessJournal` launches each evaluation through a detached wrapper with a durable
PID/start-time identity and an atomic result file; environment values are inherited,
not written to the spec or journal. Seccomp-enabled specs carry canonical filter bytes
and SHA256, while journal entries carry only the public policy summary. The detached
wrapper and direct MLE solution Popen share memfd/`pass_fds` setup and close the parent
fd immediately after launch. Durable `ExternalCommandLLM` workers instead default to
`direct_prctl`: the wrapper applies `NO_NEW_PRIVS` and the same filter in the target
preexec, deliberately retaining network and inherited environment access. Policy semantics
are rebuilt before execution, so rehashing a tampered filter does not make it valid. After an owner crash, a fresh executor and
`GitWorktree.adopt()` re-adopt the recorded branch/worktree. `recover_inflight()`
leaves live attempts pending, finalizes completed attempts without rebuilding or
re-execution, and kills the registered orphan process group when the wrapper is lost.
Missing, corrupt or unverifiable results fail closed. Recovered evidence is emitted
exactly once and the candidate branch remains resolvable after worktree cleanup.
The scheduler correlates these attempts with `ExecutorSpec.execution_ref`; recovery
also scans the process-finished/executor-evidence gap so a durable result cannot be
orphaned without final evidence.

`core/orchestration.BatchScheduler` adds the canonical frozen-cohort path on top of
that pool. It reserves every AllocationIntent before any execution, binds each
request to its intent budget, settles all returned EvidenceRecord token costs before
admission, and then serializes ADD_NODE, M1 absorb and AdmissionDecision mutations
in candidate input order. Non-OK evidence cannot be admitted, and every candidate
requires exactly one MERGE or PRUNE primary mutation. Active cohorts and open
reserves refuse checkpoints. MultiCurrencyBudgetLedger batches settle explicit
CostVec values into independent token, USD, eval_count, node, wallclock and gpu_hours
accounts; the whole cohort's vectors are validated before the first settlement, and
non-finite or mismatched costs cannot partially settle. Standard-coin conversion is
reporting-only and never enters M9. Append-only cohort, evidence, absorption and
decision journals support `recovery_state()` and settled-evidence-only `resume()`:
finalized candidates are not absorbed twice, fresh M4/M5 state can be rebuilt, and
completed resume appends nothing. A decision without its admission is ambiguous and
refused rather than replayed. With the original workspace, `resume()` also reconciles
an `execution_incomplete` cohort: complete allocation intents and fresh ledger state
are rebuilt from the journal, detached executor evidence is gathered without reruns,
and all remaining costs are validated before settlement and serial admission. Pending
execution refuses admission; a missing or released reserve remains
`accounting_ambiguous` and fails closed. A crash after token settlement or inside a
multi-unit basket is recoverable when every journaled unit cost matches executor
evidence: fully recorded intents only gain missing batch evidence, while partial
baskets settle exactly their missing units. Cost mismatches refuse before batch
settlement or admission. This is process-crash recovery, not machine power-loss
certification. The canonical M7 batch path deliberately does not parallelize the
sequential M0 evaluator's process-global usage meter.

Setting `LoopConfig(batch_size=N)` with N>1 opts the Framework improvement path into
that canonical scheduler. `M0PromptExecutor` turns each pre-registered propose/apply/
evaluate operation into canonical EvidenceRecord with metered token cost. A frozen
parent and incumbent are shared by the whole cohort; every candidate is settled before
serial M9/M4/M5 finalization, and accepted candidates only affect the next cohort.
Because the legacy LLM/evaluator meter is process-global, the adapter locks the full
metered section instead of claiming concurrency-safe usage attribution. `max_inflight`
bounds the pool but does not remove that lock. Failed evaluations become settled,
pruned evidence; IID-RS remains on the separate sequential control path. Cycle-boundary
checkpoint/resume and replay preserve batch runs. External cohort proposals are
persisted after atomic reservation and before any process launch. v34–v46 additionally
certify detached owner-crash recovery from prepared zero/partial starts through serial
finalization and Framework Receipts before checkpoint, including a started same-cycle
control after completed batch finalization, certified gaps between proposal operations,
active durable `ExternalCommandLLM` calls adopted without provider retry, and external or
durably terminated in-process proposal failures carried through settlement, finalization
and same-cycle control. Ordinary in-process marker-only calls without a terminal outcome,
legacy failures without `m0_proposal_outcome`, other legacy incomplete proposals, incomplete
proposals with evaluator processes or settlement, and control before completed batch
finalization remain uncertified.
`batch_size=1` retains the original single-candidate implementation.

`core/frontier/research.py` adds the recoverable M4 tree state. Skeleton edges
own lineage, pruning and credit topology; reference edges carry information only
and cannot affect sampling or best. `ResearchFrontier.checkpoint()` emits
canonical, integrity-checked JSON bytes containing schema version, GitState,
inflight executor nodes and messages. `restore()` reconstructs the same bytes and
allows running nodes to complete.

`Framework.evolve` now also writes an atomic `checkpoint.json` at every completed
cycle. With `LoopConfig(resume_from_checkpoint=True)` and the same workdir, task,
profile and compatible budget config, it restores the pool, per-item results,
frontier checkpoint bytes, JSON memory state, funnels, ledger, island archive and
stateful extensions, then continues at the next generation. Candidate IDs, evaluator heads and Receipt IDs are deterministic.
`stop_after_generation=N` provides a clean bounded stop for interruption drills;
completed-checkpoint resume is a search no-op. The checkpoint refuses tampering
and incompatible task/config recovery. Certified replay independently compares
normalized snapshot refs, ordered Receipt-chain hashes, stable results and live
governance, then appends a pass/fail certificate; mismatches raise instead of
being returned as successful replays. Normalization excludes only resume controls
and diagnostic per-node wall time. This validates cycle-boundary recovery and
local deterministic replay. The separate v30–v46 recovery paths below cover
started sequential external genesis, improve and IID-RS control candidates, plus
prepared external cohorts from zero/partial starts through finalization, same-cycle
control, certified proposal-operation gaps, active durable external proposer adoption
and external or durable in-process terminal-proposal-failure suffixes. v47 separately covers
sequential in-process evaluator terminal outcomes; active calls without a terminal outcome,
legacy failures without the new outcomes, batch in-process evaluator recovery and power-loss
windows remain uncertified.

## External M0 evaluator protocol

`ExternalCommandEvaluator` adapts an explicit argv command to the M0 evaluator
interface. Each candidate runs in a real journaled subprocess and exchanges a
versioned request/result/token-usage JSON envelope. The parent validates candidate
and head binding, unique per-item verdicts, finite scores, reliability and physical
token usage, then persists an atomic native outcome and append-only evidence.
Timeouts, nonzero exits and malformed responses become structured failures;
sequential execution settles and records EvidenceRecord instead of allowing an
evaluator exception to escape, while batch execution settles and prunes failed
candidates before M9. Certified replay forks process/outcome evidence into an
independent history.

For sequential `batch_size=1` improve, the Framework persists
`m0_evaluation_started` before launching the process. It binds the completed
proposal, open intent, head, operator, generation and proposer token cost to the
process journal. Resume rebuilds the ledger from its journal first, reconciles
checkpoint spending against open reserves, and adopts only the original native
outcome. It does not repropose or launch a replacement command; settlement then
reenters the normal absorb/M9/checkpoint path and records
`m0_recovery_adopted(reexecuted=False)`. A real owner-SIGKILL test proves two
total process starts, one recovered adoption and one improve gate, equality with
an uninterrupted control, matching certified snapshots and fresh certified replay.
Post-checkpoint settlement without a completed matching native outcome is still
refused instead of settled twice.

v31 extends that same candidate through settlement and admission before its cycle
checkpoint. The checkpoint records a state-mutation cursor. Recovery recomputes the
canonical absorb/admission suffix, replays existing mutations only into frontier and
memory, and appends only missing evidence. A pure gate evaluation validates any
existing gate and Receipt before reuse; admission and recovery-adoption records must
be unique and exact. A crash between settle and reconcile-delta restores only the
missing reserve-minus-actual delta, without another settlement or spend change.
Real SIGKILL drills cover that gap, absorb, gate, admission mutation, admission
Receipt and failed-evaluation evidence. Divergent suffixes fail before recovery is
marked adopted, and recovered snapshots and certified replay match controls.

v32 adds the no-checkpoint genesis window. Recovery requires exactly one compatible
`run_start` and one generation-zero draft evaluation anchor, deterministic candidate
lineage, one matching process and no unrelated reserve or settlement. The same native
outcome, settlement reconciliation and exact mutation/Receipt suffix rules apply;
real SIGKILL drills cover the open-reserve window through admission before the first
checkpoint. Missing or duplicate anchors, wrong lineage, existing checkpoint evidence
and mutation forks fail closed. One process start and ForbiddenLLM prove no replacement
execution or reproposal, while snapshots and fresh certified replay match controls.

v33 recovers IID-RS control in the same unfinished cycle as its preceding improve.
Checkpoint restoration binds only that native improve/control pair, including the
`settled improve + open control` window. Recovery finishes the improve suffix first,
then adopts the deterministic `control:generation` outcome on the locked control
account. A successful result produces exactly one baseline score and generation/
main-score-bound evidence; a failure produces structured executor evidence and no
baseline. Control never enters M9, frontier, memory or admission Receipts. Real
SIGKILL drills cover pre-settlement, settle/delta, baseline and failure evidence;
baseline forks and wrong lineage fail before control adoption, and completed resume
does not readopt or re-execute.

v34 recovers a frozen external M0 cohort only after every candidate has been
proposed and started and before any batch settlement. Each process journal binds
the original cohort, intent, proposal, head and proposer cost; process type and
cohort identity are separate fields. Recovery uses ForbiddenLLM in the real drill,
rebuilds M0 and canonical M7 outcomes from the original native results, then calls
the original scheduler's `resume()` for exactly-once settlement and serial M9
finalization. It never opens a replacement cohort. Partially started and already
settling cohorts fail closed without a recovery-adoption record.

v35 supersedes that post-settlement refusal. Recovery now rebuilds the original
frozen cohort independent of remaining budget, reconciles settled native costs and
uses the checkpoint mutation cursor to apply only missing suffix entries while
replaying exact durable mutations into frontier/memory. Absorb, decision,
admission and completion markers must match those mutation boundaries; existing
M9 Receipts and Framework admission Receipts are reused exactly. Real SIGKILL
drills extend through batch completion and the final Framework Receipt. Generic
scheduler recovery without this cursor still refuses decision-without-admission.

v36 extends the certified window to a started same-cycle IID-RS control after that
cohort has completed finalization and all required Framework admission Receipts.
Recovery replays the v35 batch suffix first, then adopts the original parentless
`control:generation` outcome on the locked control account. Success writes exactly
one baseline and its evidence; failure writes structured executor evidence only.
Control still bypasses M9, frontier, memory and admission Receipts. Real SIGKILL
drills cover pre-settlement, settle/delta, baseline and failure evidence, with
baseline-fork and lineage guards plus completed-resume no-op behavior.

v37 prepares every external cohort proposal after reservation and before any process
launch. With one exact durable proposal per candidate and no settlement, recovery now
accepts zero or partial process starts. Existing native outcomes are adopted, while
only never-started candidates execute once from their original proposals; ForbiddenLLM
proves that no proposal is regenerated. Adoption evidence distinguishes adopted and
continued processes. Incomplete proposal journals, context forks and missing processes
combined with settlement fail before any continuation, and completed resume is a no-op.

v38 makes Bubblewrap the fail-closed default for `ExternalCommandEvaluator`. Omitting
`sandbox` or passing `True` requires bwrap at construction; only explicit
`sandbox=None` or `sandbox=False` disables isolation. Every process start records its
`sandbox_policy`, and replay forks inherit that policy with independent evidence. Real
tests cover default environment clearing, host-file/network isolation and private writes
that cannot reach the host, explicit-disabled host access, missing-bwrap refusal before
launch, and all historical owner-crash recovery paths under the default policy.

v39 adds optional `ResourcePolicy(memory_bytes=..., file_bytes=..., process_count=...)`.
The detached wrapper applies hard `RLIMIT_AS`, `RLIMIT_FSIZE` and `RLIMIT_NPROC` values
before executing the sandboxed or explicitly unsandboxed target. Configured numbers are
recorded in the process spec and start evidence, replay inherits them, and unconfigured
policy remains an empty object. Real probes prove excessive allocation, file writes and
candidate forks are refused; an unstartable process limit becomes structured failure
evidence. Resource-policy owner-crash recovery adopts the original outcome exactly once.
These per-process POSIX controls are not cgroup aggregate CPU, memory, disk or GPU quotas.

v40 adds the RUBRIC B3 RE-Bench adapter and generic `ScoreRunRecord` numeric evidence.
The locked snapshot covers seven task families and 36 official files. Real campaign
scoring uses only official `TaskFamily.aggregate_scores` on Vivaria score logs; raw
scores remain in run-level audit. Process-group timeout preserves actual wallclock,
and an existing log is scoreable after timeout only when the official task declares
`score_on_usage_limits: true`. Comparison requires identical task and seed sets,
backbone and budgets across a complete seven-task, at-least-three-seed paired matrix.
Local fixtures verify these mechanics but are not external RE-Bench execution.

v41 writes an intent-bound `m0_proposal_started` marker before every possible external
LLM proposal call. Recovery accepts only an exact ordered durable-proposal prefix with
a matching marker prefix, proving that the owner stopped between proposal operations.
Persisted proposals are rebound without another model call; only the missing suffix is
proposed once, and all original candidate processes then execute once. Adoption evidence
separates continued proposals from continued processes. A marker beyond the durable
prefix means a call may be active and fails closed, as do legacy incomplete journals and
incomplete proposals combined with processes or settlement. Real SIGKILL recovery matches
uninterrupted results, ledger, governed state, normalized snapshot and fresh replay.

v42 adds `ExternalCommandLLM`, a trusted detached proposal adapter whose request is stably
bound to cohort/candidate identity. Its worker writes an atomic response and the parent
persists a journaled native outcome with physical token usage; credentials are inherited
but never serialized. On owner SIGKILL after the active marker and process start, resume
reuses that marker, waits for the original worker and adopts its outcome instead of issuing
another provider request. Only later missing candidates start new proposal calls. Malformed
and timeout outcomes are durable terminal results adopted without retry, changed requests
fail closed, and auxiliary proposer processes stay outside the evaluator execution matrix.
The real OpenAI-compatible worker is tested against a local HTTP server, not an external
API. Replay forks proposer evidence into an independent namespace. Ordinary in-process
active calls and mixed process/settlement windows remain outside this certificate.

v43 recovers a pre-settlement cohort when an active external proposal reaches a durable
non-OK outcome. Proposal completion is an ordered prefix of successful evaluation starts
or bound terminal proposer outcomes, so a failed first proposal no longer makes a later
successful start look like a forbidden gap. Recovery adopts or restores the original
failure without another LLM call and invokes only the missing suffix. Its canonical
EvidenceRecord uses the original proposer execution/request binding; an explicit
non-process recovery record joins scheduler evidence reconciliation instead of a forged
evaluator process. Real SIGKILL drills cover process-started and outcome-persisted crash
points with one invalid and one successful sibling, exact settlement/pruning, matching
snapshots and fresh replay. Proposal-failure gaps combined with settlement/finalization
remain uncertified in v43 and are addressed by v45.

v45 carries that durable terminal proposal failure through the existing batch settlement
and finalization suffix. Checkpoint restoration recognizes the non-OK proposer outcome as
native settled-intent evidence, while the missing evaluator process is recognized as the
expected failure hole rather than a lost successful execution. Both Framework and executor
recovery bind the original proposer process/request hash, compare reconstructed non-OK
EvidenceRecord and token cost with settled evidence, and reconcile the exact ledger cost
and reserve-minus-actual delta. Original terminal failure evidence uses zero diagnostic
wall time in both uninterrupted and recovered execution, making the comparison deterministic.
Ten real batch SIGKILL windows, two same-cycle control windows and five adversarial guards
verify exact suffix recovery, no provider retry, non-OK PRUNE without a fabricated M9
Receipt, completed-resume no-op behavior and fresh certified replay.

v46 adds a separate durable non-OK `m0_proposal_outcome` for ordinary in-process proposal
exceptions. It binds the exact proposal-marker SHA256 and a deterministic cohort/candidate
non-process execution ID, distinct from an external proposer outcome or evaluator process.
Only after that terminal outcome exists can recovery reconstruct the settled failure and
token cost without recalling the failed LLM; missing successful siblings are still proposed
once, and only the remaining settlement/finalization/control suffix resumes. Real SIGKILL
tests cover the outcome boundary, ten batch windows, two control windows and active-marker,
marker-hash, evidence, ledger and missing-outcome refusal. An active marker alone and legacy
failures without the new outcome remain fail-closed rather than being inferred complete.

v47 persists `m0_evaluation_outcome` for sequential ordinary in-process evaluator calls.
Both successful native results and structured terminal failures are written before settlement,
bound to the exact evaluation-start SHA256 and a deterministic candidate/start execution ID.
Recovery adopts genesis, improve and same-cycle IID-RS control outcomes without calling the
evaluator again, checks native token cost, ledger settlement and persisted failure detail,
then resumes only the missing absorb/gate/admission/baseline suffix. Real SIGKILL tests cover
pre-settlement and post-settlement windows, completed no-op and fresh replay. A start without
its outcome, legacy starts, duplicate outcomes and binding/cost/evidence forks fail closed.

v48 extends durable in-process evaluator recovery to frozen batch cohorts. Proposal
preparation remains `m0_evaluation_started`; a separate `m0_batch_evaluation_started` is
written only immediately before the real evaluator call. Each `m0_evaluation_outcome` binds
both that operation's exact SHA256 and the prepared evaluation-context SHA256, together with
its deterministic non-process execution ID, native result or terminal failure and physical
token usage. Recovery adopts completed outcomes without reexecution and invokes only prepared
candidates whose real operation never started, so zero- and partial-start cohorts are handled
without confusing preparation with execution. The scheduler reconciles explicit
`m0_inprocess_evaluator_terminal` operations rather than fabricated process journals, then
resumes settlement, absorb, decisions, admission, completion and same-cycle IID-RS control.
Real SIGKILL tests cover success and failure through settlement/finalization/control,
completed no-op and fresh replay. Active operations without outcomes, legacy operations,
duplicates and operation/context/result/cost/evidence/mutation forks fail closed.

These certificates remain narrow: ordinary in-process proposal or evaluator calls without a
durable terminal outcome, control observed before completed batch finalization and machine
power loss are not covered. The v56/v57 seccomp certificates cover only an explicit x86_64
denylist on evaluation and durable external-proposal workers, not a complete allowlist,
resource-limit policy or hostile-kernel boundary. Direct-prctl proposal workers retain
network and environment access and are not filesystem or credential sandboxes.

## MAP-Elites feature-grid parent pool

v49 adds the opt-in `map_elites_grid` profile and `MapElitesArchive`. Declared
`FeatureDimension` ranges bin finite numeric metadata from admitted candidates'
`result.public["features"]`; values outside a range are explicitly clipped to its boundary,
while NaN, infinity, booleans and missing dimensions fail closed. Each cell retains only its
current elite for parent selection, using score and candidate ID as a deterministic tie-break.
Parents are selected by occupied-cell round-robin. Replaced candidates remain in the entry
history, and soft eviction removes selection/delivery eligibility without hard deletion.
The archive does not import or modify AdmissionGate: per-item flips alone still decide M9.

Checkpoints persist dimensions, all entries, current cell bindings and replacement counts.
Restore rejects topology mismatches, wrong elites, invalid coordinates and active cells with
neither an elite nor an eviction explanation. Sequential and batch stop/resume match
uninterrupted controls, and replay starts from an independent empty grid. Default M0 greedy
selection and the existing island profile are unchanged.

## OpenEvolve database interoperability

v50 uses the real vendored `Program` and `ProgramDatabase`, not same-named local stand-ins.
`OpenEvolveDatabaseSnapshot` captures program code, native primary-parent lineage, generations,
finite metrics, metadata, island membership, feature grids, archive/best IDs, iteration/migration
state and feature-scaling statistics. Its schema-versioned canonical JSON envelope carries a
SHA256 integrity check. `frontier_to_openevolve` exports complete OK Frontier nodes with explicit
code and rejects pending/failed, missing-code or population-cap loss. Since v52, the first declared
parent maps to native `parent_id`; all additional parents and the complete Frontier checkpoint are
preserved in governance metadata rather than silently discarded.

```python
from core.openevolve_interop import (
    OpenEvolveDatabaseSnapshot, frontier_to_openevolve, frontier_from_openevolve,
    read_openevolve_database, write_openevolve_database,
)

database = frontier_to_openevolve(frontier, code_by_id, database_config)
snapshot = OpenEvolveDatabaseSnapshot.from_database(database)
restored = snapshot.to_database()              # real ProgramDatabase; ready to sample
write_openevolve_database(snapshot, native_path)
reread = read_openevolve_database(native_path, database_config)
assert reread.to_bytes() == snapshot.to_bytes()
assert frontier_from_openevolve(reread).checkpoint() == frontier.checkpoint()
```

The strict native-disk reader validates every Program file and all references before OpenEvolve's
own loader can skip malformed files or clean dangling state. Duplicate IDs/membership, unknown
parents, non-finite metrics, wrong islands/grids/elites, schema forks and integrity tampering fail
closed. Native save/load and host parent/inspiration sampling are tested. Host metrics and feature
coordinates remain sampling/display state and never become M9 evidence.

v52 adds strict `frontier_from_openevolve` recovery. Every exported Program binds the same checkpoint
hash and its complete `FrontierNode`; the lexicographically first Program carries the canonical
checkpoint. Recovery cross-checks native parent/generation/metrics, primary/additional parents,
node sets, depths, children, skeleton and reference edges before returning a Frontier. Arbitrary
host databases or incomplete governance metadata are refused. Native MAP-Elites replacement may
deactivate a Program from host sampling; export retains its code and governance lineage without
fabricating island or elite membership. OpenEvolve itself still samples and propagates credit only
through its native single primary-parent field.

v51 adds `OpenEvolveArtifactBundle`: every referenced external file is stored as raw bytes with its
size and SHA256 in a canonical envelope bound to the exact database snapshot. Small artifacts stay
inside the protected Program snapshot. `write_openevolve_database_with_artifacts` atomically writes
the native database and `artifacts/` content, rewrites every `artifact_dir` to its final destination,
and verifies exact native re-read; `read_openevolve_database_with_artifacts` performs the strict
reverse import. Text, binary, small and referenced empty-directory artifacts are tested through
native `get_artifacts` after deleting the source. Wrong bindings, path escapes, symlinks, nested
entries, unsafe names, missing referenced directories, duplicates and content tampering fail closed.
Unreferenced/orphaned directories are not migrated. Novelty-LLM/embedding portability remains a
separate boundary; v52 handles multi-parent governance lineage but not native multi-parent credit.

## M1 evidence absorption and governed state writes

`BestFirstPolicy.absorb` converts executor `EvidenceRecord` values into explicit
`StateMutation` commands. `StateApplier` is the semaphore-one write boundary for
`ResearchFrontier` and `ScopedMemory`: validation and append-only auditing share
one critical section, empty rationales and non-whitelisted node fields are rejected,
only scored done nodes can merge, and pruning remains a soft state transition.
Memory promotion is incremental L1→L2→L3 only; raw evidence and distilled insight
are appended rather than replacing a whole payload, while failed evidence remains
candidate L1 and ungated. `Framework.evolve` now routes every evaluated main-search
candidate through this path and maps M9 ACCEPT/REJECT to MERGE/soft PRUNE; rejected
nodes are ineligible for best-first parenting. IID-RS remains resident on the control
account but never enters the research frontier or memory. The accepted pool remains
a compatibility projection for M0 outputs and island archives. ExecutorPool and
BatchScheduler provide a composable canonical M7 execution/admission path, now also
used by opt-in M0 frozen cohorts. Detached crash recovery of the in-process M0 adapter is
certified only at durable proposal/evaluator terminal-outcome boundaries; active or legacy
calls without those outcomes remain fail-closed. The external evaluator defaults to Bubblewrap.

## Verification

`tests/` encodes axioms as executable tests. `verifier/v1/` independently checks
end-to-end behavior, replay, receipt coverage, static architecture guards, profiles,
extensions and required docs. `verifier/v2/` adds real island/evolve-block behavior,
apply-failure containment, soft eviction and M3 health checks. `verifier/v3/` adds
cascade/judge/meta-gate/multi-currency behavior; `verifier/v4/` adds M5/M6 scoped
memory and two-lane knowledge behavior; `verifier/v5/` adds standalone CI axioms,
debug/crossover and performance/cost Pareto behavior; `verifier/v6/` adds the
MLE-Bench Lite adapter and measured same-budget comparison protocol;
`verifier/v7/` adds official grading evidence, real M7 git/process execution and
X2 approval/pause/restore behavior; `verifier/v8/` adds M4 ResearchFrontier edge
semantics and portable state checkpoint/recovery; `verifier/v9/` compares
interrupted/resumed Framework runs with uninterrupted controls; `verifier/v10/`
adds M1 evidence absorption, guarded StateMutation application and real threaded
write integrity; `verifier/v11/` adds Framework main-loop absorption/admission
mutations, resident-control isolation and exact frontier/memory recovery;
`verifier/v12/` adds real bounded ExecutorPool concurrency, failure isolation,
serial finalization and quiescent-only checkpoints; `verifier/v13/` adds frozen-
cohort scheduling, atomic batch reservation, settle-first accounting, canonical
AdmissionDecision mutations and non-OK/checkpoint guards. `verifier/v14/` preserves
a historical standard-coin arithmetic failure; current `verifier/v15/` repeats the
same behavioral checks with the corrected 447 expectation and adds no implementation
shortcut; `verifier/v16/` adds durable batch finalization recovery, fresh-state
reconstruction, completed no-op resume and ambiguous-interruption refusal;
`verifier/v17/` adds real SIGKILL owner-crash injection, detached-process takeover,
worktree adoption, exactly-once recovered evidence and orphan/corruption guards;
`verifier/v18/` extends the real crash drill through fresh ledger restoration,
recovered batch settlement and exactly-once serial admission; `verifier/v19/` adds
real crashes after token settlement and inside multi-unit settlement, with exact
journal/evidence reconciliation and missing-unit-only recovery. `verifier/v20/`
requires real bubblewrap and probes host-file/environment/network isolation,
read-only paths, private writes, timeout and sandboxed owner-crash recovery; skipped
sandbox tests are not acceptance. `verifier/v21/` adds opt-in Framework frozen
cohorts, frozen-incumbent gate-not-rank counterexamples, serialized exact token
metering, failed-candidate settlement/pruning, resident-control isolation and batch
checkpoint/replay equivalence. `verifier/v22/` adds the production MLE-Bench
paired-arm campaign CLI, all-task preflight, real process-group timeout,
official-report-only measured records and strict 22-task/3-seed comparison guards.
Its fixtures test process mechanics only; the real CLI preflight currently fails
closed because the official package/data are unavailable. `verifier/v23/` adds real
OpenEvolve host and governed Framework agent CLIs sharing one generator, solution
execution and official-dev-validity path. Production workspaces expose public
train/test inputs while generated solutions run in Bubblewrap without inherited
credentials or private grading paths. A local OpenAI-compatible HTTP service drives
both complete arms in offline smoke tests; its grading fixture is not an external
benchmark result. `verifier/v24/` adds immutable per-call token receipts for governed
proposer/solution and OpenEvolve host-evolution calls, independent campaign recomputation,
actual-backbone evidence and fail-closed missing/tampered/over-budget checks. Token actuals
are reported physical costs only; they never enter M9 and are not converted to invented USD.
`verifier/v25/` checks B1 terminal self-attestation against the resident IID-RS mean and
strict declared noise floor, including tie, failure and missing-baseline outcomes. The
attestation is persisted evidence and does not change per-item M9 admission; controlled
fixtures do not certify an external GEPA run. `verifier/v26/` adds live C1/C2 reconciliation:
settlement/reserve/intent lifecycles, seven-account zero-gap totals, reconcile deltas,
Receipt-bound admission decisions and StopActionTable replay. `inspect()` recomputes these
checks so later orphan or conflicting evidence fails rather than leaving a cached pass.
`verifier/v27/` requires a fresh evidence history for every non-resume run and executes the
offline tracers repeatedly; reused histories now fail before spending, while each CLI run
allocates an independent directory and must report a live C1/C2 pass. `verifier/v28/` separates
C3 `formal_pass` from basic C1/C2/stop governance, requiring resident baseline evidence,
actual control spending and no frontier leakage for formal runs. It also certifies replay by
comparing normalized snapshots, Receipt-chain hashes, stable results and governance; failed
comparisons persist a failed certificate and raise. `verifier/v29/` adds the real external
M0 evaluator subprocess protocol, strict response validation, durable native outcomes,
sequential/batch failure containment and independent replay evidence. `verifier/v30/`
adds real owner-SIGKILL adoption for sequential pre-settlement external improve only:
journal-first ledger restoration, no reproposal/re-execution, exactly-once settlement
and admission, uninterrupted-control equality, certified snapshot/replay and ambiguous
post-checkpoint-settlement refusal. `verifier/v31/` extends the same candidate through
settle/delta, absorb, gate and admission: exact mutation-suffix replay, missing-delta
completion, unique Receipt/adoption evidence and real SIGKILL drills for successful and
failed evaluations. `verifier/v32/` adds no-checkpoint external genesis recovery from
process start through admission, unique run/evaluation anchors, exact lineage and budget
history, twelve real-crash/guard tests and fresh certified replay. `verifier/v33/`
adds same-cycle improve/IID-RS control recovery, native-bound two-intent ledger
restoration, exactly-once baseline/failure evidence and seven real-crash/guard tests.
`verifier/v34/` adds real owner-SIGKILL recovery of a fully started, zero-settlement
external M0 cohort, with original-outcome adoption, no reproposal/re-execution and
recovered serial finalization. `verifier/v35/` supersedes its post-settlement refusal,
preserves the historical verifier/test archive, and certifies exact mutation-suffix
recovery through absorb, M9, batch completion and Framework admission Receipts.
`verifier/v36/` adds same-cycle control recovery after completed batch finalization,
with exactly-once baseline/failure evidence and no research-state admission.
`verifier/v37/` adds durable proposal preparation and zero/partial-start continuation
without reproposal, with incomplete-proposal and settlement/context guards.
`verifier/v38/` makes Bubblewrap the external evaluator's fail-closed default, audits
explicit disable and per-process policy, and rechecks policy-preserving replay plus all
historical recovery paths. `verifier/v39/` adds real address-space, file-size and UID-wide
process/thread hard limits with policy audit, replay and owner-crash interoperability.
`verifier/v40/` adds the pinned RE-Bench numeric-score adapter, official aggregate-only
audit scoring, real campaign process groups, usage-limit timeout rules and strict paired
matrix guards. Protocol fixtures are not external benchmark scores. `verifier/v41/` adds
real SIGKILL recovery at certified proposal-operation boundaries, exactly-once missing-suffix
proposal calls, independent proposal/process adoption counts and ambiguous-call refusal.
`verifier/v42/` adds real owner-SIGKILL adoption of an active detached external proposal call,
durable protocol outcomes, a local OpenAI-compatible worker probe and mixed-window guards.
`verifier/v43/` adds failed-active-proposal recovery at process/outcome crash boundaries,
explicit non-process failure evidence and mixed failed/successful cohort finalization.
`verifier/v44/` preserves those functional checks but replaces recursive historical wrappers
with prior-pass journal validation after repeated legacy v36→v35 300-second timeouts; all
v43 failure records remain intact and no current behavior assertion is removed.
`verifier/v45/` adds terminal-proposal-failure recovery through ten batch settlement/
finalization windows and two same-cycle control windows, plus evidence, ledger, mutation,
process and missing-outcome fork refusal. Its first run preserved a historical-chain error:
v43 has no passing journal because its recursive harness timed out; the corrected check uses
v44 as that functionality's acceptance successor while retaining the failed v45 record.
`verifier/v46/` adds marker-hash-bound durable in-process proposal failure outcomes,
zero-retry recovery through settlement/finalization/control and active-call fail-closed
guards. Its 53 proposal/recovery tests, 167 recovery/governance regressions and 317-test
complete local regression passed, alongside the 11/11 static axiom gate. `verifier/v47/`
adds sequential in-process evaluator terminal outcomes and zero-reexecution recovery for
genesis/improve/control. Its 52 sequential recovery tests, 53 proposal regressions, 191
recovery/governance regressions and 341-test complete local regression passed with the same
11/11 static axiom gate. `verifier/v48/` adds separately started, double-hash-bound batch
in-process evaluator outcomes, zero/partial-start continuation and non-process recovery through
settlement/finalization/control. Its 28 real-crash/adversarial tests, 52 sequential recovery
tests, 53 proposal regressions, 219 recovery/governance regressions and 369-test complete local
regression passed with the same 11/11 static axiom gate. Active-call-without-outcome, legacy
operations without durable outcomes and power-loss windows remain outside those certificates.
`verifier/v49/` adds the MAP-Elites feature-grid archive, profile compilation, deterministic
elite/parent behavior, soft-eviction history, checkpoint integrity and sequential/batch replay.
Its 11 feature/gate tests, 50 integration tests, 230 recovery/governance regressions and
380-test complete local regression passed with the 11/11 static axiom gate; v48's 28/52/53
recovery groups were also rerun. Active-call-without-outcome, legacy operations without
durable outcomes and power-loss windows remain outside those certificates.
`verifier/v50/` adds real OpenEvolve ProgramDatabase snapshots, strict native-disk import,
single-parent Frontier export, canonical integrity envelopes and host-metric/M9 isolation.
Its 15 interoperability tests, 52 interoperability/governance tests, 245 recovery/governance
regressions and 395-test complete local regression passed with the 11/11 static axiom gate;
the 50-test MAP-Elites and v48's 28/52/53 recovery groups were also rerun. External artifact
migration, multi-parent export and novelty/embedding portability remain outside this certificate.
`verifier/v51/` adds snapshot-bound external artifact bytes, atomic database-plus-content migration,
final-path relocation and strict path/symlink/nesting/tamper checks. Its 26 database/artifact tests,
63 interoperability/governance tests, 256 recovery/governance regressions and 406-test complete
local regression passed with the 11/11 static axiom gate; all v50 behavior remains in the gate.
`verifier/v52/` adds deterministic primary/additional-parent mapping, checkpoint-bound Frontier
reverse recovery, native save/load checkpoint equivalence, displaced-Program retention and semantic
graph-tamper refusal. Its 38 interoperability/artifact/DAG tests, 75 interoperability/governance
tests, 268 recovery/governance regressions and 418-test complete local regression passed with the
11/11 static axiom gate; v51 artifact migration and all recovery groups remain in the gate.
`verifier/v53/` adds explicit measured-run selection object/policy/split contracts and strict
matrix-wide declared/actual physical cost-unit coverage. Both benchmark campaign runners
require their declared physical dimensions; missing costs cannot become implicit zero, and
selection or cost metadata never enters M9. Its 53 benchmark/campaign tests, 435-test complete
local regression and 16-check versioned acceptance pass; all v52 behavior stays in the gate.
`verifier/v54/` adds hash-bound, replayable selection receipts over complete candidate pools,
validation evidence and chain terminals. Archive-best, best-single-chain and single-run
choices are checked independently of official test scores; comparison reports include every
receipt digest, and semantic tampering fails even after unkeyed rehashing. Its 70 benchmark/
campaign tests, 452-test regression and 16-check acceptance pass; all v53 behavior stays gated.
`verifier/v55/` adds portable embedding model, credential-free API base and finite vector state,
with native save/load and restored-vector novelty checks under offline clients. Live novelty
LLM objects remain unportable and future external embeddings are not claimed reproducible.
Its 53 interoperability tests, 467-test regression and 17-check acceptance pass; prior behavior stays gated.
`verifier/v56/` adds an arch-guarded x86_64 seccomp denylist with real ptrace `EPERM`
probes, canonical durable policy evidence and shared memfd lifecycle for detached and
direct-Popen execution. ExternalCommandEvaluator, GitWorktreeExecutor and both MLE agent
arms exercise the same policy; fork and owner-crash recovery preserve it without reruns.
Its 485-test complete regression and 19-check acceptance gate cover rehashed-tamper refusal
and all prior behavior. This is not a complete allowlist, proposer sandbox, cgroup, complete
resource policy, non-x86_64 certificate or hostile-kernel boundary.
`verifier/v57/` adds direct-prctl delivery of that denylist to durable ExternalCommandLLM
proposal workers by default. Real probes check ptrace `EPERM` and kernel seccomp status;
local OpenAI-compatible HTTP and Authorization inheritance remain functional, while
rehashed policy tampering and invalid delivery fail before target start. Fork and
owner-crash recovery preserve the original policy and provider call. Its 12 proposer/seccomp
tests, 42 evaluation-seccomp tests, 300 recovery/governance regressions, 490-test complete
regression and 21-check acceptance pass with the 11/11 static axiom gate. The proposal command
is a trusted adapter, not a Bubblewrap, filesystem, network or credential sandbox; fallback
and arbitrary in-process calls are outside this seccomp certificate.
Every verifier run appends a timestamped record under
`verifier/runs/` (successes, failures and exceptions alike).
The workflow in `.github/workflows/axioms.yml` wires the static gate and current v57
acceptance for push/pull requests; historical verifiers remain archived rather than being
recursively executed in CI. No hosted-CI execution is claimed by the local verifier.

## Honest current limits

- Paid/external benchmark numbers (MLE-Bench Lite, RE-Bench) are not claimed. The
  official MLE-Bench Lite snapshot and adapter protocol are implemented and checked;
  prepared Kaggle data, full paired-seed external runs and host-parity results remain open.
  The v22 production runner and v23/v24 real host/governed entrypoints can execute and
  officially grade paired commands, but no such 22-task campaign has run here; no medal,
  validity or parity number is claimed. The local HTTP/grading fixtures certify only calling,
  isolation, token-accounting and evidence mechanics. The v40 RE-Bench adapter and real
  campaign runner are likewise mechanism-checked only: no official seven-task paired
  campaign has run, so no RE-Bench score, host parity or B3 completion is claimed.
  Since v53/v54, both comparison paths bind physical cost coverage and replayable selection
  evidence; this strengthens evidence completeness but does not manufacture external results.
  Without a real price table, neither benchmark path emits USD or `admitted_per_usd`.
- The M0 loop uses a single token currency and deterministic evaluation. Optional
  extensions now implement multi-currency, judge calibration and governed evaluator
  evolution; deployment authorization remains pending. External knowledge is off
  in benchmark mode and no live retrieval credentials are required by offline tests.
- Island topology/migration, evolve-block editing and MAP-Elites feature-grid parent selection
  work offline with checkpoint/replay support. v50–v52 certify OpenEvolve database-state,
  referenced external-artifact migration and lossless multi-parent Frontier recovery, native
  save/load, sampling and `get_artifacts`; unreferenced/orphaned artifact directories,
  v55 certifies stored embedding state; live novelty-LLM objects, future external embedding
  responses and native multi-parent credit propagation remain open.
- Main-search M4/M5 writes use absorb/StateApplier. `batch_size=1` remains the legacy
  single-candidate path; larger batches use the canonical scheduler, while their shared
  token meter is serialized. The explicit external evaluator defaults to Bubblewrap and
  supports v30–v33 sequential genesis/improve/control owner-crash adoption plus v34–v46
  recovery of prepared cohorts from zero/partial starts through finalization, same-cycle
  control, certified proposal-operation gaps, active durable proposer adoption and external
  or durable in-process terminal proposal failures through settlement/finalization. Sequential
  ordinary in-process evaluator terminal outcomes are recoverable under v47, and v48 extends
  the same terminal-outcome discipline to frozen batch cohorts with real-operation starts,
  zero/partial-start continuation and non-process scheduler reconciliation. Ordinary in-process
  calls without a terminal outcome, legacy failures without their durable outcome and other
  legacy incomplete proposals remain open.
  Arbitrary in-process evaluators are not sandboxed by this default. Optional external
  ResourcePolicy covers three POSIX limits only; it is not a cgroup or complete resource
  policy. v56/v57 certify only the explicit x86_64 syscall denylist on evaluation paths
  and durable ExternalCommandLLM workers. Direct-prctl proposers retain network and
  environment access: Bubblewrap, filesystem/network/credential isolation, fallback or
  arbitrary in-process call protection, other architectures, machine power loss and a
  complete syscall allowlist remain outside those certificates.
