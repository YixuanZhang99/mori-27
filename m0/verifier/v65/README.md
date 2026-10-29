# v65 acceptance: S6 periodic anchors and proxy validity feedback

This version adds an explicit configured-runtime group for periodic paid development-calibration
anchors, proxy-validity rank rules, and negative feedback into scoped memory.
Configuration and limits are described in the [S6 usage guide](../../../docs/PROXY_VALIDITY_V65.md).
The implementation scope is recorded in the
[alignment checklist](../../../docs/ABSTRACTION_ALIGNMENT.md); a rank threshold
and minimum-sample rule do not by themselves certify statistical validity or
external benchmark quality. Worktree/process adoption and population assembly
are subsequent stages with independent acceptance.

The new group runs `tests/test_proxy_validity.py` and
`tests/test_composed_proxy.py`. Every v64 command group and timeout remains
unchanged, including the complete offline research example, S1–S5 groups,
full unfiltered pytest, static axioms, real Linux sandbox/seccomp/process and
recovery regressions. A complete successful run contains 35 checks:
26 command groups and 9 historical/source checks. Pytest enforces
`--fail-on-skip --strict-markers` throughout.

The certificate adds `proxy_validity_stage_evidence` separately from earlier
stage evidence. S6 success requires its own complete passing Linux run at the
exact commit; main advances only after that evidence is verified. Run
`make check` on Mac and `make accept-linux` on supported Linux x86_64.
The wrapper runs in a disposable copy and requires a fresh passing certificate,
exactly one matching new journal entry and unchanged historical sources.
Implementation creates no initial v65 `LAST_RUN.json` or `runs/v65.jsonl`.

## Archived v64 evidence provenance

Historical journals are required through v64, retaining rejected-v14 and
superseded-recursive-v43 exceptions. Existing v1–v64 verifier sources and
records remain immutable. New `verifier/v64/LAST_RUN.json` and
`verifier/runs/v64.jsonl` are exact copies from successful
[S5 CI run 40904572252](https://github.com/YixuanZhang99/mori-27/actions/runs/40904572252),
head `685fd5fffae41d693cc4f4865bd763cb64dcae15`. The artifact name is
`linux-acceptance-685fd5fffae41d693cc4f4865bd763cb64dcae15`, with acceptance
directory `linux-acceptance/20261029T154442.392721Z-9mjgcdyd/`.

Archival independently checked the successful completed Actions job and exact
artifact workflow head, verified the downloaded archive digest, compared the
local handoff receipt and its log hashes, and compared extracted evidence to
the archive. The summary reports exit zero, a fresh passing certificate/journal,
unchanged source history, no timeout and no errors. All 34 checks and 1,398
pytest cases passed in 644.819 seconds. The single journal entry matches the
certificate checks and its bytes equal `new-runs.jsonl`. Absent archive targets
were created exclusively; no history was overwritten or rerun against v65
wiring.

| Archived file | SHA-256 |
| --- | --- |
| `verifier/v64/LAST_RUN.json` | `981959d2dc3b24d5c0a70e70739c18fb7422bc7fc779963538fb66f5c4681c39` |
| `verifier/runs/v64.jsonl` | `8758830c77ec2392140ae7ddb0205d8687e2fbbbc0862c760c179b677dbdef6a` |

Tooling protects these exact bytes and earlier archives. This records the
precise S5 result at its own commit; it does not certify S6 or later stages.
