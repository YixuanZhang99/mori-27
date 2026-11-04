# GEPA instance frontier component check

This checks an isolated candidate-selection component, not a complete GEPA reproduction or a benchmark result. The reference is GEPA `gepa-ai/gepa` commit `3d34469165f0d604df3b48f1d5c776e9080f3da0`, specifically `src/gepa/gepa_utils.py`. Obtain that file separately from its [pinned source](https://github.com/gepa-ai/gepa/blob/3d34469165f0d604df3b48f1d5c776e9080f3da0/src/gepa/gepa_utils.py) and run:

```sh
PYTHONPATH=m0 python research/experiments/2026-11-05-gepa-frontier/compare_reference.py --reference /path/to/gepa_utils.py
```

The command checks the reference file SHA-256 first, then compares retained per-candidate winner frequencies on 200 deterministic synthetic score matrices with unique aggregate scores. The local component requires a complete, frozen validation set, uses validation mean for pruning, uses insertion order to break aggregate ties, and fixes candidate ordering for seeded draws. The pinned reference supports more general scoring/evaluation policies and its set iteration may choose a different tie/order; matching probability weights on these synthetic cases does not certify identical seeded draws, arbitrary policies, reflection, or final task quality.

The component and tests remain isolated from the public `Framework` runtime. Minibatch evaluation, reflective mutation, acceptance, data binding and full end-to-end reporting remain required before calling the repository's support a GEPA reproduction.
