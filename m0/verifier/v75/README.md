# v75: stable full-regression acceptance

V75 retains all v74 command groups and checks. The full project regression alone
has a 900-second deadline instead of 600 seconds; the 35-minute verifier deadline
and 45-minute CI job deadline leave time for cleanup. This responds to v74 push
runs that timed out at 600 seconds while a separate PR run passed the same group
in 595.72 seconds. It does not remove or skip tests.

V74 verifier sources and their wrapper remain unchanged. V75 independently checks
their recorded SHA-256 digests, adding one check for 56 total. Prior acceptance
artifacts retain their original version and outcome; this version does not turn
a failed or timed-out v74 run into a pass. Acceptance remains scoped to the same
M7 construction and governance boundaries as v74, not a full release or a claim
of benchmark superiority.
