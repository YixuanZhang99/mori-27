# Verifier v2 acceptance criteria

Extends v1 without replacing it. v2 first executes the complete v1 verifier, then checks the M4/M3 extension slice:

1. v1 exits 0 (including the now-expanded pytest suite).
2. Real FunSearch-shaped offline run: frozen skeleton survives, evolve-block edits apply, best score reaches 1.0, and at least one inter-island migration occurs.
3. Apply-failure containment: an evolve-block/profile mismatch produces improve funnels with zero runnable and zero admitted candidates.
4. Island archive: round-robin parent selection, elite membership migration, and soft eviction without record deletion behave as specified.
5. M3 health: effective-budget, reconciliation-delta, hidden-account, control-fulfillment and admitted-per-1k-token metrics are produced from ledger/funnel data; control fulfillment matches the known toy value.
6. Replay with islands reproduces the main trajectory and archive health exactly.
7. Every run appends a timestamped v2 record; v1 records remain available for reproduction.
