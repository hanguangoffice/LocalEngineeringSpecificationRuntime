# LESR v1.0 prototype gate summary

Date: 2026-08-05 (Asia/Shanghai)

## Overall decision

`P1=PASS`, `P2=PASS`, `P3=PASS`, `P4=PASS`,
`P5=BLOCKED_CLIENT_VALIDATION`.

The final construction specification and destructive `src/lesr` cutover are
not authorized because the design baseline requires P1-P5 all to pass. This is
an intentional safety outcome, not an incomplete silent migration.

## Accepted prototype decisions

- P1: separate logical identity, immutable Revision and immutable lifecycle
  records; use UUIDv7 and canonical JSON as leading candidates.
- P2: use a LESR-owned closed typed AST; keep SHACL/Rego as restricted export
  projections; unknown never becomes pass or not-applicable.
- P3: require explicit Evaluation Context, deterministic Mandatory Read Set,
  stale exclusion and explicit completeness.
- P4: build a complete tree through a temporary Git index and atomically
  advance the canonical ref with an expected old value; projections remain
  rebuildable.
- P5 code: keep the protocol-free capability/error/write-envelope contract and
  a thin replaceable MCP adapter.

## Evidence

- Design baseline Manifest: 81/81 entries verified.
- Legacy baseline: 28 tests pass on Python 3.12.13.
- Prototype/legacy combined suite: 64 tests pass before final quality cleanup.
- Codex live MCP probe: PASS.
- Claude Code live MCP probe: BLOCKED; non-MCP control prompts also time out.

The repository CI re-runs Manifest verification, pytest, Ruff and strict mypy.

## Required unblock action

Restore a working Claude Code model session without changing LESR. Re-run the
two read-only calls (`capabilities`, `resolve`) using the strict temporary MCP
configuration documented in `P5-client-probes.md`. If they return contract
`1.0-prototype` and UID `OBJ-REQ-1`, change P5 to PASS, review all gate reports,
and only then write the final construction specification and replace the legacy
runtime.

## Preserved recovery points

- Git tag `legacy-mvp-v0.1.0` points to the untouched old MVP.
- Branch `refactor/baseline-v1-prototypes` contains independent commits for the
  baseline and P1-P5 work.
- The old implementation specification remains marked `SUPERSEDED`; it has not
  been deleted.
