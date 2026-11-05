# Arbor MLE evidence tools

The first real pilot stopped in planning after one completed candidate; its original
[nine-cell failed packet](parent-identity-v1/README.md) and costs are retained.
There is no successful real matrix or official Arbor score yet. These tools export a declared
matrix and independently recalculate its selection, coverage and currency from
original records. They do not call a model, retrain programs, read credential
contents, or recompute hidden-label losses.

```bash
python research/experiments/2026-11-05-arbor-mle/export_runs.py \
  --matrix /absolute/path/to/arbor-mle-v1 \
  --ledger /absolute/path/to/existing-campaign.db \
  --output /absolute/path/to/new-evidence-directory
python research/experiments/2026-11-05-arbor-mle/recalculate.py \
  /absolute/path/to/new-evidence-directory
```

The input matrix needs its predeclared `matrix-manifest.json` and
`official-prepared-identity.json`. The campaign is opened read-only; only receipts
attributed to these runs are exported. Data CSVs, anonymous mapping keys and API
credentials are excluded. The output directory must not already exist.

The reducer separates development optimum, admitted trunk, local frozen final
loss and official score. It checks admission against original evaluation records,
strict configured margins, query cap, frozen predictions, summary projections,
source-bound insight versions, declared/unrun cells, incomplete cycles and the
original campaign's 2/8 micro-CNY token upper prices. Training that finished before
an interrupted synthesis remains uncommitted evidence, not a successful search
node. Failed construction is persisted before synthesis and checked against its
original constructor outcome, even when no evaluator ran. Pending usage retains
its reservation and a null total cost; a durable pre-dispatch budget refusal with
zero tokens is counted separately from charged calls.

Official scores require a separate original grading audit, pinned prepared-data
identity and raw grader report. Original journals, programs, six-stage events,
pending hypothesis proposals and source bindings remain available in the packet.
The hashes detect accidental or partial changes; they are not signatures from an
external witness. Evaluator losses remain trusted source measurements. The
exporter is not a replacement for the runner's physical/replay audits.

Validation includes synthetic gate rejection, forged receipt and prediction
bindings, unknown cost, interrupted synthesis, source substitution, official score
tampering and an export/recalculate round trip. Synthetic results are not benchmark
performance. The real nine-cell matrix and final exact-head CI remain delivery
requirements.
