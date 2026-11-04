# FunSearch population calculation check

This is a building-block check, not a public benchmark or complete reproduction. `core.funsearch_population.FunSearchPopulation` is not yet wired into the public Framework. The upstream reference is the original [programs database at `cc53f274237d7ab05c19df939edbc1f9616a7c19`](https://github.com/google-deepmind/funsearch/blob/cc53f274237d7ab05c19df939edbc1f9616a7c19/implementation/programs_database.py); the checker accepts only the exact SHA-256 recorded in `summary.json`.

Run after downloading that pinned file to a local path and providing NumPy and SciPy:

```bash
PYTHONPATH=m0 python research/experiments/2026-11-05-funsearch-population/compare_reference.py /path/to/programs_database.py
PYTHONPATH=m0 python -m pytest -q m0/tests/test_funsearch_population.py
```

The 200 seeded synthetic cases compare test signatures, the last-case score reduction, temperature-scheduled cluster probabilities, and length-based probabilities. Scores are provided in frozen sorted case order; upstream instead reduces the last key of the supplied mapping. Its RNG and exact draws differ from this component's independently seeded Python generator. The component records resets rather than discarding history, requires an island epoch for post-initial registrations to reject late writes, and permits global seeding only at initialization. When the runtime supplies an eligibility set, sampling is conditioned on non-pruned candidates and removes empty clusters; this is an explicit budget-governance adaptation. The caller must serialize access; this standalone object does not provide concurrent locking or authenticate its checkpoint. Upstream uses wall-clock reset scheduling and explicitly leaves stale asynchronous writes unresolved. This comparison does not validate prompt construction, model calls, reset distribution, evaluator integration, or benchmark performance.
