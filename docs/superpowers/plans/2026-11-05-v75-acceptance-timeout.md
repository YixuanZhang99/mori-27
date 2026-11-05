# V75 acceptance deadline

- Preserve the v74 verifier and source history, all command groups, and all test selections.
- Increase only the full-regression inner deadline from 600 to 900 seconds; give the outer verifier 2100 seconds and the hosted job 45 minutes.
- Verify v74 source and wrapper digests, current Git source binding, all checks, and complete hosted artifacts. Retain the v74 timeout failures as historical evidence.
- Run contract and wrapper regression tests before the full local and hosted v75 acceptance; do not treat prior v74 success as a v75 result.
