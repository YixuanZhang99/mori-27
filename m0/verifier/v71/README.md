# v71: provider admission and durable known refusals

Retains all 32 v70 command groups and their exact timeouts. Adds one unfiltered 480-second group, `provider_input_admission_refusal_and_durable_replay`, running provider, MLE currency-integration, composed-budget and composed-recovery tests. A successful run has 42 checks: 33 command groups and 9 historical/source checks. Strict markers and fail-on-skip remain enabled.

`provider_admission_evidence.certified` requires both the new group and the complete run to pass. It covers input-plus-full-output pre-dispatch admission, explicit estimate/capacity policy distinction, independent per-run journal prefix reconciliation, preservation of measured charges, retained admitted candidates on normal capacity exhaustion, durable typed-refusal replay and completion metadata. The default UTF-8 input envelope is not a proven hosted-tokenizer bound. The conservative service-capacity mode depends on its frozen service assumptions and refuses the current 60,000-token run. No actual invoice, external provider request, arbitrary native crash adoption or third real pilot is certified by this verifier.

No initial v71 certificate or journal is supplied. The active wrapper executes the verifier in a disposable copy and requires fresh matching evidence. Hosted same-SHA CI remains required before main integration. The [second real pilot](../../../research/experiments/2026-11-04-deepseek-pilot-attempt-2/README.md) is an independent partial-success matrix, not evidence that this revision was already tested externally.

## Archived v70 provenance

The archived v70 certificate and single-entry journal are exact bytes from local Linux acceptance on clean commit `aedede3c2b78a5c2b57074c70d510af710f5af4e`, run `20261104T082351.249747Z-i_v639my`. All 41 checks and 1,821 pytest cases passed; acceptance took 901.868 seconds. Source commit, clean state and history matched before/after. This is local evidence, not hosted CI.

| Artifact | SHA-256 |
| --- | --- |
| `verifier/v70/LAST_RUN.json` | `750a0ab259f0ba3648fe67a17b87d8e0ca4231c6cad80498445b95ae24d8a2d4` |
| `verifier/runs/v70.jsonl` | `fd411c00b85d866bc9e3254cd564f8ddd7275736676c36364b49820edaf9737a` |

[v70-provenance.json](v70-provenance.json) retains independently verified artifact hashes and evidence boundaries. Existing verifier source and history were neither rewritten nor rerun to manufacture a historical pass. Transition tests pin archive bytes, matching certificate/journal, every preceding command/timeout and conservative certification flags.
