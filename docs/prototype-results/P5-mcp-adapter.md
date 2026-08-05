# P5 MCP Adapter

**Gate status: PASS (approved client substitution)**

## Question and hypothesis

Can LESR expose stable domain capabilities to different MCP clients without
binding the semantic core to an SDK revision? A protocol-free domain port plus
a thin FastMCP adapter should preserve the boundary.

## Scope and alternatives

The prototype defines Resolve, Inspect, Query, Context, Workspace, Governance
and Compliance capability groups. It includes read-only object resources,
paged query, long-task lifecycle and a structured write envelope. Fine-grained
storage tools, SQL, shell and raw file access are deliberately absent.

## Measurements and results

- The domain contract module has no MCP import.
- All write schemas require Workspace, Expected Base, Idempotency Key, Actor,
  Delegation, Dry Run, Risk Class and structured Operation.
- Errors use the versioned nine-field domain contract and preserve retry advice.
- Resource templates and capability negotiation are exposed independently of
  concrete tool names.
- Contract tests execute resolve, context, workspace, review-gated Apply,
  idempotent replay and long-task paths.
- A real stdio `ClientSession` initializes the subprocess, lists tools and calls
  `capabilities` and `resolve` successfully.

## Client validation

The repository includes a stdio entry point suitable for Codex Desktop and
Claude Code. A real Codex CLI 0.146.0 client discovered and called both tools,
returning `1.0-prototype` and `OBJ-REQ-1`. Claude Code 2.1.220 timed out twice;
a control probe without MCP also timed out, so this is classified as a client
session/endpoint blocker rather than an LESR protocol failure. No user-level
client configuration was changed.

## Failure modes

Clients differ in resource-template discovery, enum schema handling, long-task
UX and maximum response size. The adapter must retain pagination and the
protocol-independent start/status/cancel/result fallback.

## Decision and reversal cost

The adapter boundary, independent stdio client and Codex probe pass. On
2026-08-05 the project owner accepted the independent MCP `ClientSession` plus
Codex as the P5 client evidence because Claude Code cannot establish even a
non-MCP control session in the current environment. Claude remains a deferred
interoperability check rather than an LESR gate blocker. Reversal cost is low
because only `p5_mcp.py` imports the SDK.

## Code to keep / delete

Keep capability/error/write-envelope contract tests. Replace the in-memory
domain service and experimental tool naming after live-client evidence.

## Open issues

Record a Claude Code probe when its endpoint/session is repaired. Response
pagination limits, authentication mapping, async task transport and adapter
version negotiation remain final-runtime work.

## Runtime cutover note

The disposable `p5_mcp.py` adapter was replaced by `src/lesr/adapters/mcp.py`.
The formal adapter advertises domain contract `1.0`; its independent stdio test
and the Codex Desktop live revalidation both pass. Claude Code remains deferred.
