# CONTEXT — code/design vocabulary

Only these names describe the corresponding concepts in code, profiles and review.
New concepts enter this table before implementation. `selector`/`picker` must not be
used as aliases for `parent_sample`; `score` is display-only at the admission gate.

| Code name | Meaning | Authority |
|---|---|---|
| `Framework` | Public governed-evolution surface: `evolve` / `inspect` / `replay` | RUBRIC A1 |
| `AllocationIntent` / `IntentReceipt` | Sole M1→M3 allocation request/response | M1 R1/R2 |
| `parent_sample` | Deterministic parent choice, greedy in M0 | M1-H1 |
| `reissue` | Same-lineage lower-tier retry after budget rejection | M3 R4 |
| `StopActionTable` / `stop_action` | Verdict/scope→action lookup; no policy recomputation | M1-H-查表 |
| `BudgetLedger` | Single-token reserve/settle ledger with seven cost accounts | M3-J/N |
| `MultiCurrencyBudgetLedger` | Atomic per-unit reserve/settle extension | M3-N1 |
| `CurrencyAccount` | One physical budget dimension and ceiling/floor | M3-N1 |
| `ExchangeRateTable` | Versioned explicit conversion layer and standard-coin anchor | M3-N14 |
| `ReserveRecord` | Open/released/settled reservation lineage | M3-N5 |
| `AccountingStamp` | Supplier/model/tokenizer/price/date measurement version | M3-J6 |
| `FunnelRecord` | proposed→applicable→runnable→admitted counts | M2-K4 |
| `VariationProposal` | LLM-proposed, deterministically applied candidate change | M2-I-LLM |
| `EvalResult` / `ItemResult` | Per-item evaluation plus display/feedback side channels | M8 |
| `Receipt` | Immutable admission evidence | M9/I-谱系 |
| `AdmissionGate` | Per-item flip/noise adjudication, never aggregate-score ranking | M9-B2/B7 |
| `CascadingEvaluator` | Shallow screen with deterministic full-evaluation escalation | M8 cascade |
| `EvaluatorMetaGate` | Held-out anchor non-regression and epoch-boundary promotion | M8M9 §6.4 |
| `EvoEvaluatorChannel` | Default-closed evaluator evolution with four prerequisites | RQGM decision |
| `receipt_invalidation` | Soft validity change; original receipt remains | I-谱系 |
| `MemoryEntry` / `ScopedMemory` | Governed internal experience and scoped lifecycle store | M5 |
| `ScopeContext` / `ScopeUpgradeEvidence` | Visibility coordinates and sharing-permission evidence | M5 §7.2 |
| `memory_invalidation` | Soft demotion/supersession of evidence-dependent lessons | M5/I-谱系 |
| `KnowledgeService` | Sole external-knowledge supply channel: `query` / `audit` | M6-D8 |
| `GroundedQuery` / `KnowledgeDigest` | Typed ground-lane request and opened-source compression | M6-K5/K12 |
| `AuditVerdict` | Three-tier advisory novelty signal, never a veto | M6-D2 |
| `AuditReliability` / `DualRateLedger` | Independent review coverage and false-novel/false-kill quality | M6-D3/K14 |
| `FetchLedger` | Opened URL/content hash/lane/truncation provenance | M6-D7 |
| `ground` / `audit` | Physically separated inspiration and certification lanes | M6-D1 |
| `InjectionGravityProbe` | Diversity-only post-injection attraction time series | M6-D6/K15 |
| `IslandArchive` | Island membership, migration and soft eviction | M4 extension |
| `FeatureDimension` / `MapElitesArchive` | Versioned numeric feature binning and one-elite-per-cell parent archive; features come from admitted candidates' public evaluation metadata, deterministic occupied-cell round-robin affects parent selection only, replaced/evicted candidates remain inspectable, and checkpoint/replay preserve exact grid state without entering M9 | M4/M1 MAP-Elites extension |
| `CrossoverContract` | Two-parent roles, deterministic permutation, structural compatibility and debug fallback | M2-C7/O12 |
| `debug` / `crossover` | Explicit one-parent repair and two-parent composition extensions | M2-O1/O12 |
| `PerformanceCostPoint` / `ParetoArchive` | Multi-currency performance/cost points and non-dominated M4 view; never an M9 input | M4/HarnessPro extension |
| `ResearchFrontier` / `FrontierNode` | Recoverable M4 tree state, node projections and deterministic sampling | SPEC §6 |
| `skeleton` / `reference` | Credit-bearing lineage edges versus information-only edges; never mixed | SPEC §6 |
| `FrontierCheckpoint` | Versioned canonical state bytes with GitState, inflight executors and messages | SPEC §6/§12 |
| `OpenEvolveDatabaseSnapshot` / `OpenEvolveInteropEnvelope` | Complete, canonical and integrity-hashed OpenEvolve Program/ProgramDatabase state with validated lineage, metrics, islands, grids, elites and feature scaling; host metrics remain display/sampling data and never become M9 evidence | M4 interoperability extension |
| `frontier_to_openevolve` / `read_openevolve_database` | Explicit eligible Frontier-to-host export and strict pre-validated native-disk import; no silent parent loss, stale-reference cleanup, malformed-file skipping or inference of admission from host scores | M4 interoperability extension |
| `frontier_primary_parent_id` / `frontier_additional_parent_ids` | Deterministic first-declared parent mapped to OpenEvolve's native single `parent_id`, with all remaining credit-bearing parents preserved losslessly in governance metadata; native host sampling remains single-primary-parent only | M4 interoperability extension |
| `frontier_checkpoint` / `frontier_from_openevolve` | Canonical complete Frontier checkpoint carried at the lexicographically first Program governance anchor, hash-bound by every exported Program and strictly restored only after per-node/native-field and graph-invariant validation; arbitrary host metrics never become M9 evidence | M4 interoperability extension |
| `OpenEvolveArtifactBundle` / `OpenEvolveArtifactEnvelope` | Snapshot-hash-bound, canonical SHA256 envelope for every referenced external artifact file, with raw bytes, size and per-file digest; small artifacts remain inside the Program snapshot | M4 interoperability extension |
| `write_openevolve_database_with_artifacts` / `read_openevolve_database_with_artifacts` | Atomic native database plus artifact migration with direct-child path containment and final-path rewriting; symlinks, nested entries, missing referenced directories and content forks fail before host reads | M4 interoperability extension |
| `StateMutation` / `MutationOp` | Sole M1/M9 state-change envelope with mandatory rationale | SPEC §1/§2 |
| `BestFirstPolicy` / `absorb` | Rule policy converting EvidenceRecord into deterministic state mutations | SPEC §3 |
| `StateApplier` | Semaphore-one validated write path into M4/M5 with append-only audit | SPEC §2 |
| `promote_level` / `delta` | Incremental L1→L2→L3 memory merge; never whole-memory replacement | SPEC §7 |
| `RunCheckpoint` | Atomic Framework cycle snapshot with integrity, config compatibility, frontier/memory and resume state | SPEC §12/C4 |
| `checkpoint_enabled` / `resume_from_checkpoint` | Framework cycle persistence and same-workdir recovery controls | SPEC §12 |
| `stop_after_generation` | Clean bounded-cycle stop for resumable runs and interruption drills | SPEC §12 |
| `TaskAdapter` / `EvalContract` | Benchmark-specific setup, immutable grading and provenance boundary in ZOO | ZOO §1 |
| `BenchmarkRunRecord` | Externally executed per-task/seed/arm evidence; never a planned result | RUBRIC B2/B3 |
| `SameBudgetComparison` | Paired task/seed/model/budget comparison with explicit noise-floor verdict | RUBRIC B2 |
| `ScoreRunRecord` / `SameBudgetScoreComparison` | Externally measured numeric-score run and strict paired comparison; identical task and seed sets, backbone, budgets, selection contract and physical cost-unit coverage, with directed noise-floor verdict | RUBRIC B3 |
| `SelectionContract` / `selection_object` | Explicit measured-score selection semantics: single_run, archive_best or best_single_chain, plus a non-empty versioned policy and data split; paired reports require one identical contract and never silently equate archive-best with a deployable single chain | RUBRIC B2/B3 evidence integrity |
| `declared_cost_units` / `actual_cost_units` | Transparent comparison-level physical resource vectors; every declared budget unit must have an actual measurement, all runs must use identical declared and actual unit sets, and missing units are never totaled as zero | RUBRIC B2/B3/B5 evidence integrity |
| `REBenchAdapter` | Pinned seven-task METR snapshot, official aggregate-only scoring, audit-only raw scores and usage-limit timeout boundary | RUBRIC B3/ZOO §5 |
| `preflight` / `run_campaign` | ZOO production all-task readiness check and real paired-arm process/official-grading campaign; incomplete matrices never compare | RUBRIC B2/B3 |
| `AgentRuntime` / `host_agent` / `governed_agent` | Shared public-data solution generation, Bubblewrap execution and official dev validity path for OpenEvolve host and governed prompt-only arms; local fixtures never become external scores | RUBRIC B2/SPEC §9 |
| `MeteredOpenAICompatibleLLM` / `MeteredHostLLM` | Per-call immutable physical token receipts plus reset-interval cumulative metering for governed and OpenEvolve host calls; missing or inconsistent usage fails closed | RUBRIC B5/SPEC §9 |
| `token_usage_summary` | Independent receipt-digest recomputation for agent/campaign agreement, actual backbone and declared token-budget enforcement; never an M9 input or USD price conversion | RUBRIC B5/SPEC §9 |
| `Candidate` / `ExecutorSpec` | M2 execution candidate and M7 role/hypothesis binding contract; `execution_ref` durably correlates a scheduler cohort | SPEC §1/§9 |
| `EvalRequest` / `EvalStatus` | Fidelity, timeout, seed/resume request and first-class execution outcome | SPEC §1 |
| `CostVec` / `actual_costs` | Explicit per-physical-unit execution cost and exact reserved-unit settlement projection; never an M9 input | M3-N1/SPEC §9 |
| `EvidenceRecord` | Exactly one execution result plus branch provenance, status and attempt | SPEC §1/§9 |
| `GitWorktree` / `GitWorktreeExecutor` | Isolated branch backend and protected-path/required-output execution | SPEC §9/§12 |
| `GitWorktree.adopt` / `recover_inflight` | Verified post-restart worktree adoption and pending/finished/lost detached-attempt reconciliation | SPEC §9/§12 |
| `ProcessJournal` / `executor_process_started` | Durable PID/start-time process identity, atomic results and exactly-once terminal evidence boundary; no environment persistence | SPEC §9/§12 |
| `BubblewrapSandbox` | Real bwrap isolation: private filesystem, read-only protected/data paths, cleared environment, no network and default x86_64 dangerous-syscall seccomp denylist; default for ExternalCommandEvaluator, otherwise explicitly selected; explicit `seccomp=False` disables only seccomp, with no complete-allowlist/resource-limit claim | SPEC §9 |
| `build_seccomp_policy` / `validate_seccomp_policy` | Canonical versioned x86_64 classic-BPF denylist with arch guard and EPERM action; durable payload must exactly match semantic reconstruction, so rehashed custom filters fail closed | SPEC §9 execution extension |
| `materialize_seccomp` / `seccomp_arguments` | Shared short-lived memfd and `pass_fds` binding for Bubblewrap detached wrapper and direct Popen; parent fd closes immediately after target launch and no environment or credential enters policy evidence | SPEC §9 execution extension |
| `seccomp_delivery` / `direct_seccomp_preexec` | Explicit `bwrap_memfd` or `direct_prctl` policy delivery; direct delivery applies resource limits, `NO_NEW_PRIVS` and the canonical filter in target preexec without Bubblewrap, while durable specs/journals bind the selected mechanism | SPEC §9 execution extension |
| `ExecutorPool` / `max_inflight` | Bounded real candidate execution with queued/running state and serial input-order finalization | SPEC §2/§9 |
| `BatchScheduler` | Frozen-cohort all-intent reservation, bounded execution, whole-cohort multi-currency settle-first accounting and serial canonical admission | SPEC §2/§3/§9 |
| `M0PromptExecutor` / `M0NativeOutcome` | Opt-in adapter from pre-registered M0 propose/apply/evaluate operations to metered canonical evidence plus its same-process gate payload; shared global metering remains serialized, proposal and evaluator operations have durable boundaries, and prepared zero/partial-start, ordered proposal-gap, durable active-call plus external or in-process terminal-outcome recovery through settlement/finalization rebuilds both payloads without a git workspace | SPEC §9/§12 |
| `ExternalCommandEvaluator` | Explicit versioned request/result/token-usage JSON evaluator using one journaled subprocess per candidate, strict parent validation, fail-closed default Bubblewrap with audited explicit disable, optional ResourcePolicy and bounded sequential or prepared-cohort crash adoption through finalization | SPEC §9/M8 |
| `ResourcePolicy` / `resource_limits` | Optional validated RLIMIT_AS/RLIMIT_FSIZE/RLIMIT_NPROC values applied before external target exec and recorded as non-sensitive process evidence; not a cgroup or complete resource quota | SPEC §9/§12 |
| `ExternalEvaluatorError` | Structured timeout/invalid/failed-to-run process or protocol failure consumed as M0 evidence rather than escaping sequential or batch execution | SPEC §1/§9 |
| `external_evaluator_outcome` / `native-outcome.json` | Atomic durable native result/failure, request/response hashes and physical token usage bound to candidate/head/execution ID; environment is never persisted | SPEC §9/§12 |
| `m0_proposal_started` | Intent-bound operation marker written before any possible cohort LLM call; a matching marker/durable-proposal prefix certifies a between-operation crash, while one extra marker is recoverable only through the original durable ExternalCommandLLM operation or a subsequent matching terminal `m0_proposal_outcome`; an ordinary in-process marker without that outcome remains fail-closed | SPEC §9/§12 |
| `ExternalCommandLLM` / `external_proposer_outcome` | Trusted detached proposal adapter with stable cohort/candidate request binding, atomic worker response, durable success/failure outcome and physical token usage; owner recovery adopts the original operation without provider retry, credentials are never persisted, replay uses independent evidence, and workers default to direct-prctl seccomp while deliberately retaining network/environment access rather than claiming filesystem or credential isolation | SPEC §9/§12 |
| `m0_proposal_outcome` | v46 separate durable non-OK terminal record for ordinary in-process proposal exceptions, bound to the exact marker SHA256 and deterministic cohort/candidate non-process execution ID; it permits zero-retry failure reconstruction but never certifies an active call or a legacy failure without this record | SPEC §9/§12 |
| `proposal_operation_state` / `recovery_nonprocess_executions` | Strict ordered proposal completion prefix containing successful evaluation starts or durable non-OK external/in-process proposer outcomes; terminal failures join scheduler evidence reconciliation through explicit operation records bound to real proposer executions or deterministic non-process identities, never fabricated evaluator process journals | SPEC §9/§12 |
| `m0_evaluation_started` / `evaluation_context` | Durable binding of sequential or prepared cohort candidate proposal, intent, head, operator, generation and proposer cost; external cohorts persist bindings before any process launch, sequential in-process starts require a matching terminal outcome before recovery, and a batch preparation marker alone never certifies that its evaluator ran | SPEC §9/§12 |
| `m0_batch_evaluation_started` / `inprocess_evaluation_operation_state` | v48 separate real-operation boundary written immediately before each in-process batch evaluator call, plus strict validation of unique prepared-context/operation/outcome bindings; zero/partial starts are distinguishable, while active or legacy operations without terminal outcomes fail closed | SPEC §9/§12 |
| `m0_evaluation_outcome` | Durable in-process evaluator success or terminal failure persisted before settlement; sequential outcomes bind the exact evaluation-start SHA256, while v48 batch outcomes additionally bind the real batch-operation SHA256 and prepared evaluation-context SHA256 with a deterministic non-process execution ID; recovery adopts native result, physical token usage and failure detail without reexecution, while active/legacy operations without it remain fail-closed | SPEC §9/§12 |
| `process_kind` / `execution_ref` | Independent external-process type and scheduler-cohort identity used to select exactly the original recoverable evaluations while keeping auxiliary external proposer workers outside the candidate execution matrix | SPEC §9/§12 |
| `restore_genesis_recovery` | No-checkpoint reconstruction from exactly one compatible run_start and generation-zero draft anchor; unrelated budget activity or ambiguous lineage fails closed | SPEC §12 |
| `m0_recovery_adopted` / `adopt_external_recovery` | Exactly-once sequential genesis/improve recovery from the original external process outcome or v47 exact-start-bound in-process terminal outcome through settlement and admission before cycle checkpoint; never a replacement execution | SPEC §12 |
| `m0_batch_recovery_adopted` / `M0PromptExecutor.recover_inflight` | Exactly-once prepared external or v48 in-process cohort recovery from original native outcomes plus one initial execution of each never-started candidate through settlement, finalization and Framework Receipts; certified proposal gaps invoke only the missing suffix once, durable active calls adopt their original proposer outcome, terminal proposal/evaluator failures produce original-operation-bound non-OK evidence whose settled payload and physical cost are revalidated through finalization and same-cycle control, scheduler reconciliation consumes explicit `m0_inprocess_proposer_terminal` or `m0_inprocess_evaluator_terminal` non-process executions rather than fabricated processes, and adoption separately counts continued, adopted, new and failed proposals plus continued/adopted evaluator operations | SPEC §12 |
| `mutation_start` / `_finalize_recovered` | Framework-only checkpoint cursor for exact batch apply-or-replay suffixes and mutation-bound journal markers; generic decision-without-admission recovery remains refused | SPEC §12 |
| `adopt_control_recovery` | Same-unfinished-cycle IID-RS native outcome adoption after sequential improve or completed batch recovery; exact control-account settlement and baseline/failure evidence without M9 or research-state admission | SPEC §12/K6 |
| `state_mutation_count` / `StateApplier.replay` | Checkpoint mutation cursor and evidence-silent frontier/memory reconstruction of an exactly matched post-checkpoint suffix | SPEC §12 |
| `AdmissionGate.evaluate` | Pure deterministic M9 adjudication used to validate an existing interrupted gate/Receipt before reuse; no score or cost input | M9/SPEC §12 |
| `reconcile_settled` | Native-cost-matched completion of a missing reserve-minus-actual delta without a second settlement or spend change | SPEC §12/M3-N5 |
| `ExternalCommandEvaluator.fork` | Reuse evaluator command assets while binding certified replay to independent process/outcome evidence and an isolated evaluation namespace | RUBRIC C4 |
| `batch_size` / `max_inflight` | Framework frozen-cohort size and executor quota; batch_size=1 preserves the legacy single-candidate path | SPEC §2/§9 |
| `AdmissionDecision` | Canonical M9 admit flag plus exactly one candidate-local MERGE or PRUNE mutation | M9/SPEC §2 |
| `recovery_state` / `BatchScheduler.resume` | Append-only cohort classification, detached-execution reconciliation, recovered settlement and serial finalization resume | SPEC §12 |
| `restore_from_journal` | Fresh-ledger replay of physical reserve/release/settle entries without unit conversion or duplicate live-state replay | SPEC §12/M3-N5 |
| `accounting_ambiguous` / `accounting_recovery_safe` | Active-cohort accounting interruption; only exact journal/evidence matches may resume, while release, missing reserves and cost mismatch fail closed | SPEC §12 |
| `batch_absorbed` / `batch_decision` | Recovery boundary between evidence absorption and admission mutation application; decision without admission is ambiguous | SPEC §12 |
| `HITLController` / `ControlDecision` | Unified auto/review authorization and immutable human-decision evidence | SPEC §13 |
| `degenerate_baseline` / `control` | Resident IID-RS and its locked cost account | Self-attestation covenant |
| `self_attestation` | Terminal B1 evidence: best score minus IID-RS mean strictly above declared noise floor; PASS/INADJUDICABLE/FAIL/INSUFFICIENT_EVIDENCE, never an M9 input | RUBRIC B1 |
| `admission_receipt` / `governance_audit` | Candidate/Receipt/admit binding plus live C1 ledger, C2 receipt and StopActionTable reconciliation; cached pass flags are not trusted | RUBRIC C1/C2 |
| `formal_pass` / `baseline_residence` | Separate C3 certificate requiring resident baseline evidence, actual control spending and no research-frontier leakage; basic governance remains meaningful for short protocol runs | RUBRIC C3 |
| `certified_snapshot_ref` / `receipt_chain_sha256` | Integrity-checked deterministic snapshot identity and ordered gate-to-Receipt chain identity; snapshot normalization excludes only resume controls and diagnostic node wall time | RUBRIC C4 |
| `replay_certificate` / `replay_certified` | Append-only original/replay comparison of snapshots, Receipt chains, stable results and governance; mismatch persists a failed certificate and raises | RUBRIC C4 |
| `inadjudicable` | Effect below measured noise, reported without claiming improvement | M1-G17 |
| `collapse_alarm` | Parent/diversity collapse signal | M1-H2 |

## v53 measured-comparison evidence contract

`SelectionContract(selection_object, policy, split)` binds every externally measured
benchmark record to exactly one selection meaning: `single_run`, `archive_best`, or
`best_single_chain`. A paired matrix must use one identical contract, so archive-best
cannot be silently compared with a deployable single chain or with a different selector
or split. These fields are audit metadata, never M9 evidence.

Every declared budget unit requires an actual measurement. All runs in one comparison
must have identical declared and actual cost-unit sets; `required_cost_units` additionally
enforces campaign-specific physical dimensions. Summation indexes each actual unit
directly instead of converting missing values to zero. Extra actual units remain visible
in the report, but do not create a price table, USD-efficiency or host-parity claim.
The 2026-10-27 reversal review again favors this measurement layer over adding another
sampler: recent RSI evaluations distinguish archive-best, best-single-chain and deployed
objects and charge proposal, validation, rejected-attempt and execution costs.

## v54 replayable selection evidence

`SelectionCandidate` binds a candidate ID to validation evidence, an optional finite
validation score, and optional chain/terminal metadata. `SelectionReceipt` hash-binds the
SelectionContract, complete candidate tuple and selected ID. `validate_and_replay()` must
reproduce the choice: one candidate for `single_run`; validation-max with candidate-ID tie
break for `archive_best`; and validation-max across exactly one terminal per chain for
`best_single_chain`. Pool selection requires an explicit validation split.

Official benchmark test scores never enter this receipt. A changed test score therefore
cannot change selection, while a changed pool, contract or selected ID invalidates the
receipt hash; recomputing the unkeyed hash does not bypass semantic replay. Comparison
reports expose every run's receipt digest. These records are run-level audit evidence,
not candidate feedback or M9 input.

## v55 embedding-backed database portability

OpenEvolve snapshots now preserve `embedding_model`, `embedding_api_base` and Program
embedding vectors. API bases must be explicit HTTP(S) URLs without userinfo, query or
fragment; model names are trimmed non-empty identifiers. Vectors must be finite, non-empty
and share one dimension. Native save/load and strict disk reads enforce the same contract.

`novelty_llm` remains a live runtime dependency, not portable JSON state, and is still
rejected by snapshot export. A restored embedding client can compute future vectors only
through its explicitly configured service or an injected client; offline certificates use
test doubles and do not claim to reproduce external embedding responses. Stored vectors,
cosine similarity and novelty judgments remain host-side state, never M9 evidence.

## v56 Bubblewrap seccomp execution evidence

The default Bubblewrap evaluation policy now includes a versioned x86_64 classic-BPF
program. It checks `seccomp_data.arch`, kills on architecture mismatch, returns `EPERM`
for an explicit dangerous-syscall denylist, and allows other syscalls. The denied set and
numeric mapping are fixed source data rather than host-header discovery or caller input.
This is deliberately not described as a complete syscall allowlist.

`ProcessJournal` stores canonical filter bytes and SHA256 in the durable spec and a public
summary without bytes in its journal. Before target launch, `materialize_seccomp()` rebuilds
the expected policy and rejects any divergence, including a modified filter with recomputed
unkeyed digest. A memfd is written, rewound and substituted for the unique `--seccomp`
marker; `pass_fds` transfers it to bwrap and the parent closes it immediately after Popen.
The detached evaluator/worktree wrapper and MLE direct solution execution share this path.

Real tests execute `ptrace(PTRACE_TRACEME)` and require `-1/EPERM`, while normal Python,
external evaluation, git-worktree scoring and MLE host/governed local official fixtures
continue to run. Fork preserves policy with independent evidence; owner-crash recovery
adopts the original process outcome without generating a new filter or process. Explicit
`seccomp=False` and explicit sandbox disable remain separate audited choices. The policy
contains no environment values or credentials and does not enter M9.

The certificate does not cover non-x86_64 architectures, a complete allowlist, cgroup or
aggregate resource quotas, machine power loss, a hostile-kernel boundary, or Bubblewrap/
seccomp protection for `ExternalCommandLLM` and arbitrary in-process proposers/evaluators.

## v57 direct-prctl external proposal evidence

`ExternalCommandLLM` workers now default to `seccomp_delivery="direct_prctl"`. Before
fork, the wrapper validates the same canonical v56 policy and prepares the BPF structures;
in target preexec it applies resource limits, then `PR_SET_NO_NEW_PRIVS` and
`PR_SET_SECCOMP`. No Bubblewrap argv or seccomp-fd placeholder is involved in this
delivery. Invalid delivery and semantically modified policies fail before target start.

Real proposal probes require ptrace `-1/EPERM`, `NoNewPrivs=1`, `Seccomp=2` and at least
one installed filter. Durable specs carry the canonical policy and delivery; public journal
entries omit filter bytes and environment values. Fork preserves both, and owner-crash
recovery adopts the original outcome without another provider request. Explicit
`seccomp=False` is the only disable switch and remains visible in evidence.

This path intentionally retains network and inherited environment access so a real local
OpenAI-compatible HTTP request with Authorization still succeeds. It is therefore syscall
filtering for a trusted proposal adapter, not Bubblewrap, filesystem/network isolation or
credential isolation. Fallback calls made without an operation context and arbitrary
in-process proposers/evaluators do not pass through this worker and are not covered.
