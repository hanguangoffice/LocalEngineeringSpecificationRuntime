# Runtime 2.0 release gate

- Contract version: Runtime `2.0.0`; Canonical Format `1.0`
- State: `PASS`
- Verified code scope: `52fd494..17cb104` in PR #21

## Product result

The ordinary product path now starts from a natural-language goal or an imported
specification, selects exact vendored upstream templates, creates the engineering
structure and editable Workspace, and starts a Mission with a Work Package dependency
graph. Agents claim bounded work, evaluate the real Workspace, and continue automatically
for ordinary work. Only an actual engineering choice is persisted as a human Decision
Request. Formal review, signature, Apply, and Baseline remain available at their genuine
governance boundaries.

The primary Web views are Engineering Map, Missions, Decisions, Engineering Content, and
Versions. Technical identifiers and protocol records remain in Technical Details. Motion
uses the packaged GSAP runtime with reduced-motion handling; the interface was inspected at
1920x1080, 1366x768, and 390x844.

## Local verification

Reference run: Windows 11, Python 3.12.13, repository virtual environment.

- Baseline manifest: 81/81 files verified.
- Construction schemas: 55 schemas and 5 examples verified.
- Vendored upstream intake sources: 38 files verified before use.
- Pytest: 253 collected; 252 passed and 1 platform-specific test skipped on Windows.
- Ruff: passed.
- strict mypy: passed for 44 source files.
- Wheel and sdist: one `2.0.0` artifact of each type built and verified byte-for-byte.
- Isolated wheel installation: package version, CLI entry, all intake assets, source
  verification, and one event-driven template selection passed.

## Acceptance scenario

The browser test creates a new temporary project named `edge-telemetry-observatory`. A raw
MQTT/edge-device request selects the event-driven pack, creates four engineering Work
Packages, allows an agent to claim and complete the first package after real Workspace
validation, and makes the dependent package ready without a human Decision Request or a
premature Canonical Revision. The separate formal path still completes Edit -> Validate ->
Review -> Human Sign -> Apply -> Baseline.

The existing `D:\Proj\gpu-lab-manager` project is outside the test scope and is not read or
modified.

## Compatibility and failure cases

- Runtime 1.x Canonical governance records with the retired helper hash fields are accepted
  and their old values are checked; Runtime 2 does not emit those duplicate fields.
- Git compare-and-swap, Review Package evidence binding, Ed25519 human approval, external
  source verification, and Workspace state hashing remain at their existing boundaries.
- Mission, Agent Run, Decision Request, task progress, and Presentation Mapping are local
  runtime/projection state rather than Canonical engineering facts.
- Tests cover concurrent claims, dependency progression, out-of-mandate work, blocked and
  human decision routes, approval invalidation, browser security, responsive navigation,
  package omissions, and old-record read compatibility.

## Remote release evidence

PR [#21](https://github.com/hanguangoffice/LocalEngineeringSpecificationRuntime/pull/21)
ran the locked-dependency matrix against code head `17cb104`:

- [Ubuntu](https://github.com/hanguangoffice/LocalEngineeringSpecificationRuntime/actions/runs/33288288666/job/99195302278): `PASS`, 2m08s.
- [Windows](https://github.com/hanguangoffice/LocalEngineeringSpecificationRuntime/actions/runs/33288288666/job/99195302402): `PASS`, 10m28s.

Both jobs executed manifest and schema verification, Ruff, strict mypy, the complete Pytest
suite, wheel/sdist build, exact package-content checks, and isolated installation. The
evidence-closing documentation commit contains no runtime or contract change; its own PR
checks must also pass before merge.

## Retained limitation

One external FastAPI test dependency emits a Starlette deprecation warning for its current
`httpx` compatibility shim. It does not affect runtime behavior or the isolated install.
