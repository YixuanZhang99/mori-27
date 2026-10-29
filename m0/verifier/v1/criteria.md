# Verifier v1 acceptance criteria

All checks must pass offline. This verifier supports, but does not by itself prove, full RUBRIC v1.0 completion; paid/external benchmarks remain separate runs.

1. `pytest` entire suite exits 0.
2. Toy GEPA end-to-end: best score 1.0, every resident IID-RS score below it, control spending > 0, all funnels monotone.
3. Replay: two identical runs produce identical best prompt, best score, main trajectory and baseline trajectory.
4. Inspect: exposes ledger summary, baseline/main comparison, receipt and funnel counts; every ACCEPT pool candidate has a persisted receipt.
5. GSM8K-style evaluator: numeric answer extraction and per-item feedback tests pass; an offline solver can run through the same Framework API.
6. OpenAI-compatible adapter: importable, deterministic request construction and usage metering tested without network.
7. Static guards: M1/M3/gate sync code contains no LLM/network/wall-clock calls; gate never reads `combined_score`; evidence store has no mutation API.
8. Extensions: novelty gate and H2 monitor register through configuration/hooks only and execute their trigger behavior in tests.
9. Profiles: `gepa_reflective` and `funsearch_island` compile to framework configuration with no kernel source modification.
10. Required project docs and machine-readable verifier run records exist.
