# Arbor v2: completed search, failed delivery audit

Original frozen source: `64cecb67ab2784b495ac58314397a3b15d4c2b4b`.
All nine task/seed cells were declared before calls. The smoke cell (spooky seed 0)
ran five cycles in 416.484 seconds: one candidate succeeded, four construction
attempts exhausted their two tries after returning bare code instead of the
required JSON object. The independent initial control also failed construction.
All failures and the other eight unrun cells remain in this packet.

Search and zero-call recorded replay completed. Local development loss was
0.4844238709374809 and frozen final loss was 0.4889852815089852. Delivery stopped
at `currency_audit_failed`, before submission materialization or official grading.
These are local losses, not official benchmark scores. The run has no successful
physical-submission audit or official score. Its original failure is unchanged.

The receipt auditor compared the construction reducer's operator-only call count
with all billed calls, including planning and insight synthesis. The campaign
itself had no pending usage, protection breach or charge discrepancy. Reproducing
the old auditor on original records yields `construction transcript does not cover
currency calls`. The corrected read-only auditor joins every phase to its original
provider transcript and validates construction against operator calls only. It
rejects omitted/tampered planning contexts, usage and results. The separately
labelled diagnostics bind the corrected auditor bytes and do not replace the
original run report or turn this failed delivery into a successful experiment.

Independent export/recalculation and the corrected read-only audit agree on
**27 calls** (12 operator, 15 planning/synthesis), **138,647 tokens**, and a batch
cost upper bound of **¥0.686746**. The original campaign reached **¥31.761012**, with
**¥168.238988** remaining and zero pending calls. This is not a verified invoice.

For v3, the response-format instruction belongs only to the constructor phase,
not shared task text or planner prompts. An opt-in `explicit_json_output` flag
preserves previous constructors' default prompts. The named Arbor profile enables
it for main and control construction. The parser remains strict, max attempts
remains two, and no failed program is silently accepted. Both bugs have reproducing
regressions; a complete loopback live runner now covers independent audits,
submission and terminal resume, beyond the previous Framework-only fee tests.

```bash
python research/experiments/2026-11-05-arbor-mle/recalculate.py \
  research/experiments/2026-11-05-arbor-mle/audit-coverage-v2
```

A new v3 matrix must be frozen separately. No v2 cell is rerun/replaced and no new
currency campaign is created. v1, v2 and v3 results must remain separate.
