# Verifier v6 acceptance criteria

Extends v5 without replacing it. v6 first executes the complete v5 verifier, then checks the external-benchmark protocol boundary:

1. v5 exits 0, including every earlier verifier, test and independent behavior check.
2. The MLE-Bench Lite adapter locks the official 22-task Low split, task-list SHA-256, upstream revision and per-task protected-file manifest. The core must remain free of ZOO/benchmark-specific imports and branches.
3. Adapter setup validates the official split and current task's config/grader/checksums/leaderboard/description hashes. Tampering is refused. Agent-visible setup contains only description, sample submission and provenance metadata, never grader, leaderboard or private answers.
4. Metric direction is derived from the official leaderboard ordering. Dev feedback exposes validity only, admission adds above-median without raw score, and score/medals are audit-only.
5. Host comparison accepts only externally measured records with evidence references, identical task-seed pairs, one locked task list, one backbone, equal declared physical budgets, complete expected task coverage and at least three consistent paired seeds per task.
6. Valid Submission and Any Medal are reported over all runs; paired delta, SEM, per-arm physical costs and an explicit noise-floor verdict are emitted. Missing, duplicate, unmeasured, unfair or incomplete inputs are refused rather than converted into a pass.
7. Offline fixtures verify protocol behavior only. They must not be represented as MLE-Bench execution or performance evidence. RUBRIC B2 remains open until real 22-task, paired-seed governed and host runs complete.
8. Every v6 invocation appends timestamped command, exit code, checks and observed values, including failures and exceptions. Earlier criteria and logs remain unchanged.
