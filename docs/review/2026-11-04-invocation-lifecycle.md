# Physical invocation lifecycle review

Base: 75f397e. Reviewed candidate: 9afc1d2. One fresh independent reviewer inspected the complete branch and independently ran 18 focused tests. Existing tests and historical verifier sources were unchanged. The reviewer found one Important accounting regression, no Critical or Minor findings.

## Finding and fix

The first extraction placed the ungoverned durable timing supplier inside the executor's MeasuredCommandError handler. A registered executor returned canonical evidence costing 7 tokens, then metadata retrieval raised the same exception carrying 1 token. Baseline retained a 10-token/1-evaluation reservation; the extracted candidate settled 1 token and released it. The public Framework path reproduced this without bypassing validation.

The fix moves timing retrieval after the executor exception handler, restoring the authority distinction. `test_timing_supplier_cannot_replace_evaluation_cost_with_its_exception_bill` failed on the reviewed implementation, then passed. The public registered-executor timing variant also failed using the reviewed 9afc1d2 method loaded into an isolated test process, then passed under the fix. The companion executor-origin variant verifies that a genuine measured rejection still settles 7 evaluation tokens once. The 92-test lifecycle/budget/governance/recovery/CNY group passes; the final frozen-source project run passes 2,132 Linux tests, 76 tooling checks, axioms, examples, builds and import integrity. The installed wheel also passes the CNY example outside the checkout, with zero external model calls and no replay HTTP/ledger writes. Clean-source acceptance and hosted CI are reported separately.

## Architecture result

Hierarchical planning, main/control operator execution, and evaluation now use InvocationLifecycle. A private per-operation state owns start, meter cleanup, provider-floor validation, settlement disposition and unresolved retention. Orchestration no longer pairs those lifecycle steps. The physical settlement adapter retains unit coverage, actual-node/evaluation normalization, durable measurements and receipt proofs. The owner receives budget/store/settlement/governance/clock dependencies, not the whole runtime.

This closes the identified caller-ordering duplication within hierarchical invocation. It does not prove the whole-repository A7 ratio or eliminate every dynamic provider hook. Flat accounting remains on its existing protocol and uses the retained provider-floor adapter. No new public Framework method or authority is introduced.

## Decisions and open scope

- Retain the original runtime wall-clock injection by explicit clock dependency; this preserves existing wall measurement regressions. Losing that seam would weaken timing-policy verification.
- Ungoverned native exceptions do not become supervisor attestations simply by using a class name; preserve unresolved behavior there. Accepting arbitrary attached costs could erase unknown usage.
- Separate implementation task completion from final review, clean acceptance and push; each remains independently evidenced. Treating the first as release approval would overstate validation.
- The reviewer excluded migration of flat accounting; its unchanged floor adapter was inspected. This refactor claims no migration of that separate protocol, so its independent compatibility complexity remains.
- Full A7, paid research, live campaign migration and release certification were outside the code review. They remain open goal requirements or separately checked engineering gates, not assumed successes.

No minor finding was deferred. The single Important finding is covered by direct and public-entry regressions. No second review was substituted for the required final tests.
