# Local resident-governance verification

The optional composed-v7-governed path now runs frozen resident controls through the public Framework API, projects seven accounts from one physical authority, protects future capacity, and replays recorded outcomes without dispatch. Legacy configured behavior remains composed-v6 when governance is absent.

`make axioms test-linux examples tooling build verify-import` passed on an unchanged source snapshot: 2,000 Linux tests, 64 tooling tests, static axioms, four established examples, wheel/sdist build and 1,020 historical import payload checks. The import check is source integrity verification, not installed-wheel execution.

A separate clean Python environment installed the built wheel. The copied public example ran outside the checkout under isolated Python: pause (one control complete, two pending), resume (all three complete), and recorded replay (passed, zero external calls). The numeric fixture is synthetic; it makes no benchmark or supplier-randomness claim.

The [summary](summary.json) binds the validation log, source manifest and installed artifact hashes. Private logs remain local. The earlier clean53 v71 failure and first current dependency-cycle failure were retained; neither was reclassified as passed. The worktree supervisor's post-result fsync race has a real-process regression, and the unchanged architecture checker verifies the shared-contract extraction.

This report does not certify a release candidate, formal paid IID-RS, superiority, invoice correctness or same-SHA hosted CI. The CNY authority migration/protection exists and is tested on temporary ledgers; its provider bridge remains absent, so the configured governed runtime rejects external monetary capabilities. No paid calls or live-ledger migrations were made for this work.
