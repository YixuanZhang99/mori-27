# Arbor v1: invalid parent identity in the second planning round

This is the complete original failed pilot packet, not a successful benchmark result.
Source: `3fe91198d94ac9e4fe79aef420a28b4f99832405`.
The nine-cell matrix was declared before any calls; spooky seed 0 was its smoke cell.
It stopped after 126.760 seconds with one completed main candidate and one incomplete
planning round. The other eight declared cells never ran. No final submission or
official score exists; no failed or unrun cell has been replaced.

The model returned three new hypotheses in round two. The selected hypothesis had
an eligible executed candidate as parent, but two unselected hypotheses used IDs
of still-pending, unexecuted hypotheses as parents. The policy correctly rejected
the whole batch with `ValueError: Arbor hypothesis parent is not eligible`.
This was reproduced offline from the original reply and previous policy state,
without provider or training calls. The v1 prompt distinguished them only through
the word "eligible" and separate observation/pending objects; it did not enumerate
eligible parent candidate IDs. The v2 prompt supplies that explicit list and states
that pending hypothesis IDs are valid only as `selection.pending_id`. It retains
strict validation for every proposed idea and does not silently drop invalid ideas.

The completed candidate's development loss was **0.4819319177746601**. This is not
an official benchmark score, and the batch has no replay/physical-submission
certificate because search did not reach a frozen submission. Independent export
and recalculation verified the partial evidence and all nine declared outcomes.
Original receipts account for **¥0.183060** in this batch, with zero pending calls.
The original cumulative ¥200 campaign then stood at **¥31.074266**, leaving
**¥168.925734**. The cost is a token-price upper bound, not a verified invoice.

Recalculate without credentials, model calls or datasets:

```bash
python research/experiments/2026-11-05-arbor-mle/recalculate.py \
  research/experiments/2026-11-05-arbor-mle/parent-identity-v1
```

A revised v2 protocol must be declared and frozen separately; its results must not
be pooled with this v1 batch. The cumulative campaign must not be reset.
