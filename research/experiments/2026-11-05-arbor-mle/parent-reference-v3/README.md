# Arbor v3: candidate-reference namespace failure

Original source: `7c47a39419d83d7bf9f1e8972f329fd356dc6f8f`; recipe `arbor-mle-v3`.
The predeclared matrix contained three tasks and three search seeds. The smoke
cell (spooky, seed 0) stopped after 415.624 seconds: three valid main candidates,
zero failed completed candidates, and one incomplete planning cycle. Eight cells
were not run. The original outcome is `execution_failed`; there is no frozen
final submission or official score.

All three constructors and the independent initial control produced valid
programs. The development losses were 0.4848067507, 0.4326271432 and 0.4146486693.
These are development observations, not delivered benchmark performance.

In the fourth ideation response, two new hypotheses used `candidate:<ID>` as
`parent_id`. The underlying IDs were eligible executed candidates, but the
parser accepted only bare IDs. The same prefixed representation was already
used for `source_refs`. Offline execution of the original response reproduced
`ValueError: Arbor hypothesis parent is not eligible`. Changing only the parent
representation to the equivalent bare IDs accepted all three proposals.

The v4 protocol explicitly accepts a bare eligible ID or exactly one
`candidate:` prefix for that same ID. It normalizes the parent before hashing
and retaining the hypothesis, then applies the unchanged eligibility and depth
checks. It does not guess a different parent, drop an invalid idea, or retry a
model call. Unknown references, pending hypothesis IDs, repeated prefixes,
non-text values, exhausted directions and excessive depth remain rejected.
The original provider response remains in the transcript.

Original receipts account for 17 paid calls and 95,158 tokens, with an upper
cost of **¥0.532886** (main ¥0.485996, control ¥0.046890). No call remains pending.
The original cumulative campaign reached **¥32.293898**, leaving **¥167.706102**.
These are the frozen price upper bounds, not a supplier invoice.

The packet retains its original failed state and nine-cell denominator. It was
exported from original records and independently recalculated using:

```bash
python research/experiments/2026-11-05-arbor-mle/recalculate.py \
  research/experiments/2026-11-05-arbor-mle/parent-reference-v3
```

The v4 declaration must be separate; v3 is not resumed or replaced. No new
currency campaign is created.
