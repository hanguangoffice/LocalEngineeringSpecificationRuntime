# Gate 8 — Semantic closure and product-state round trip

- Contract: LESR Runtime / Canonical Format `1.0`
- Candidate: `1.0.0rc3`
- Status: `PASS`
- Scope: RC2 independent re-audit findings plus the Baseline v1.0 acceptance contract

## Closure decisions

| Re-audit finding | RC3 product behavior | Executable evidence |
|---|---|---|
| Enforcement did not control Apply | Every Rule outcome is combined with its operation-specific Enforcement Mapping into an immutable `OperationDecision`. Apply requires zero unresolved blocking findings; review/acknowledgement findings remain governance work and observations remain non-blocking. The Git boundary rechecks the same decision. | integrated validation and Git-boundary tests |
| Deviation field mismatch | Configuration reads only `active_deviation_revision_uids`. A deviation must be selected, in date, approved, subject-bound, compensating-control complete and reference an effective relaxable Rule. Suppressed findings are canonical and non-blocking. | Rule fixtures, validation models and candidate Apply tests |
| Apply did not evolve Configuration | Review preparation calculates and hashes `Configuration@next`, replacing selections by Logical Object / Relation Assertion identity. The Review Package binds that hash; Candidate and Configuration advance in one Git commit. | Playwright product round trip and Git atomicity tests |
| Baseline could omit applied content | Baseline preparation consumes the returned Configuration UID. The end-to-end test asserts Manifest Revision and Relation membership exactly equal the post-Apply Configuration. | `test_gate7_playwright.py` |
| Rich graph AST and product Rule model diverged | `RuleCompiler` emits the canonical typed `ConstraintExpression`; field, relation, bounded path, lifecycle/evidence, external/human observation and all aggregate operators use that representation. | Rule/compiler and graph evaluation suites |
| Kind/Facet were nominal | Facet revisions own typed field and Fragment contracts; Kind revisions select exact Facets. Unknown Kind, unknown field, missing required field, wrong type/cardinality or unknown unit is rejected before Rule evaluation. | Profile kernel and runtime validation tests |
| Compiler inferred schema/units from candidates | Symbols come from selected Kind/Facet revisions or the versioned runtime resource contract. Units come only from Profile-owned `unit_definitions`; candidates never expand the compiler environment. | Profile determinism, Rule compiler and strict typing gates |
| Validation Targets were revision-only | The runtime constructs typed Revision, Relation, Workspace, Configuration, Activity, Operation and State Transition evaluation environments. | Rule target contract and runtime validation suite |
| Workflow guards/evidence were inert | Submit executes role checks plus deterministic `field:`, `attestation:` and `evidence:` guards and verifies referenced evidence kinds. Unsupported guards are rejected rather than ignored. | Workspace/Workflow tests and strict runtime path |
| Context ignored conditional/sensitivity/formal trace | Context applies invariant, mandatory, conditional, forbidden-sensitivity and mandatory Formal Trace policies. Missing formal credit or relations and confidentiality omissions remain explicit completeness states. | Context and Formal Trace tests |
| Impact propagation was shallow | Product Impact identifies selected Rules, Configuration, matching Baselines and Deviations, while preserving external/depth/profile/configuration incompleteness. | Impact tests and service contract |
| Review Package mutated after comment | Package and signature hash remain immutable. Comments are independent subject-bound records; unresolved comments block governance without rewriting the signed package. | Gate 5 and restart/recovery tests |
| Findings were not canonical | Apply writes the exact Validation Run and every Finding beside the bound evidence before the atomic ref advance. | candidate-integrity and projection rebuild tests |
| Performance evidence was overstated | Historical medium/large numbers are explicitly reclassified as Layer-1 semantic-kernel measurements. Product claims require separate Projection/application, governed-transaction and product timing. | performance protocol and runner output |
| UI used only incidental motion | GSAP Core 3.15.0 is vendored and packaged. Timelines represent boot hierarchy, panel focus, Workspace state, enforcement decision, governance, Apply progress, graph focus and task progress. Reduced-motion is tested. | Playwright GSAP and reduced-motion tests |

## Failure modes retained by design

- Unknown Kind, unit, Profile conflict, external endpoint, unsupported Workflow guard,
  incomplete formal trace, stale base, changed evidence hash, invalid/expired signature or
  unresolved blocking finding fails closed.
- Projection failure marks Projection stale and never rolls back the authoritative Git ref.
- Tag failure leaves a reconstructable Baseline Manifest and reports pending tag rebuild.
- Persistent Task execution is explicit: workers claim queued work through CLI/local UI
  lifecycle rather than silently running inside every read-only process.

## Performance evidence boundary

The fixed scale and latency targets remain the release protocol. RC3 withdraws the earlier
implication that an in-memory Graph/Context microbenchmark measures the product path.
Layer-1 measurements remain useful capacity evidence; the Playwright flow is functional,
not a latency claim. A final stable release may only publish medium product latency after
all four layers are measured under the frozen reference conditions.

## Gate result

Manifest `81/81`, construction schemas, deterministic serialization, pytest including
Playwright and reduced-motion, Ruff, strict mypy, wheel/sdist verification and isolated
installation are the required RC3 evidence set. No P0/P1/P2 item is intentionally deferred.
