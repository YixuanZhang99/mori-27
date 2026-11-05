# M7 whole-branch review and correction record

Review range: `f7ab27395b7907b851196ad7a88b38dd7bf5986d..8b5e018bd801429e6194f3607852a7f093a32ab2`. The independent reviewer worked read-only and ran 125 focused M7 tests (31.89 seconds). Its interrupted review resumed after the user resumed development; no second reviewer or review loop was added. Subsequent `1756188` changes delivery documentation only.

## Findings and disposition

The review found two Important issues, no Critical issues and no deferred Minor issues. Both were independently reproduced through the public Framework before editing implementation code.

1. A deeply nested JSON response escaped as RecursionError; an escaped unpaired surrogate artifact failed while writing its terminal. Each response had 5 known tokens, but 0 tokens/nodes were settled and the entire 10-token/1-node reservation remained outstanding. The correction validates UTF-8 text and catches decoding depth failures inside the measured construction failure/repair boundary. Six public cases covering artifact/hypothesis encoding and deep JSON, with and without repair, failed before the fix and passed afterward. Resume consumes the original outcome without replacement calls.

2. Native evaluation encoded and validated the full result before physical settlement. Wrong candidate identity, invalid status or NaN metrics could therefore strand a valid 7-token/1-evaluation bill. The correction preserves a distinct measured rejection terminal, validates its cost/coverage independently, settles that bill once, and then raises the integrity error. It does not fabricate valid scoring evidence or relax the existing canonical evidence codec. Three public cases failed before the fix and passed afterward. Additional checks cover a crash after terminal persistence, control-lane recovery, and missing coverage retaining the unresolved reservation.

The focused correction suite passed 107 tests in 2.24 seconds. The post-correction full project check passed 2,269 Linux tests, 84 tooling tests, 11 axiom checks, public examples, build and import verification in 332.45 seconds with unchanged source. The independent installed-wheel check verified 127 module bytes and ran all three copied examples outside the checkout. Exact source hashes and installed results are in research/experiments/2026-11-04-m7-integrated-acceptance/post-review-*.json. Final same-SHA acceptance remains pending; this document is not a passing v74 certificate.

## Review boundaries explicitly retained

- Configured concurrency, full A7, benchmark effectiveness and Mac acceptance remain open requirements. M7 review cannot close those requirements by implication.
- The first clean v74 run was stopped by the user's pause and remains interrupted. It is neither a successful certificate nor a regression failure. Final-source acceptance and hosted evidence remain necessary.
- Process-crash evidence does not certify whole-machine power-loss durability.
- Multi-file construction and symlink/submodule bases remain explicitly unsupported and rejected in the current backend.
- Custom plugins are trusted Python code. Hidden plugin state and non-text custom-provider returns require their own conformance contract; this review's malformed-output reproductions used supported text responses.

The new rejected-outcome representation is an explicit failure record, not an evaluation result that can enter admission. Future consumers must preserve that distinction. Missing or invalid measurements still prevent settlement; a failed score/identity check alone no longer erases a known bill.

The larger delivery scope remains the [evidence-led plan](../superpowers/plans/2026-11-04-evidence-delivery.md) and the original alignment/RUBRIC. No new model request, live-ledger migration, benchmark improvement or full release is claimed by this correction.
