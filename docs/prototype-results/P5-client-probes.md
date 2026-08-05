# P5 live client probes

Date: 2026-08-05 (Asia/Shanghai)

## Server

- Command: project Python 3.12, module `prototypes.lesr_v1.p5_mcp`
- Transport: stdio
- Domain contract: `1.0-prototype`
- Probe sequence: `capabilities` then `resolve("REQ-SW-0001")`
- Expected result: `OBJ-REQ-1`

## Codex

- Client: Codex CLI `0.146.0-alpha.9.2`, invoked directly from the installed
  Codex Desktop bundle because the npm shim points to an obsolete binary path.
- Configuration: ephemeral command-line MCP configuration; no user config edit.
- First run: server discovered; read-only/never-approve mode cancelled the MCP
  call as designed by the client permission policy.
- Controlled retry: ephemeral bypass mode, prompt restricted to the LESR MCP
  server and two read-only calls.
- Result: PASS.

```json
{"domain_contract":"1.0-prototype","resolved_uid":"OBJ-REQ-1"}
```

## Claude Code

- Client: Claude Code `2.1.220`.
- Configuration: temporary strict MCP JSON removed after each probe; no user
  configuration edit.
- Result: BLOCKED. Two MCP probes timed out after 120/180 seconds without output.
- Control: a 30-second and a 60-second `Return only OK` probe without MCP also
  timed out.
- Diagnostics: `claude auth status` reports an OAuth login; `claude doctor`
  reports a healthy installation but an unconnected custom endpoint/session.
  Endpoint values and credentials are intentionally not recorded.

## Gate consequence

The independent MCP `ClientSession` subprocess tests and Codex both pass and
exercise different client implementations. Claude cannot currently establish a
normal model session. On 2026-08-05 the project owner approved Codex plus the
independent stdio client as the current P5 acceptance evidence, so P5 is `PASS`
with a documented client substitution. Claude validation is deferred and must
not be represented as passed.

## Long-term runtime revalidation

Date: 2026-08-05 (Asia/Shanghai)

- Server: project Python 3.12, module `lesr.adapters.mcp`.
- Domain contract: `1.0`.
- Client: Codex Desktop bundled CLI `0.146.0-alpha.9.2`, invoked directly because
  the unrelated npm shim still points to an obsolete Desktop build.
- Configuration: ephemeral command-line MCP configuration; no user config edit.
- Calls: `capabilities`, then `resolve("REQ-SW-0001")`.
- Result: PASS.

```json
{"domain_contract":"1.0","capability_groups":["resolve","inspect","query","context","workspace","governance","compliance"],"uid":"018f0000-0000-7000-8000-000000000001","revision_uid":"018f0000-0000-7000-8000-000000000002"}
```

The client emitted a PowerShell shell-snapshot warning before the probe; both MCP
calls completed and the warning is unrelated to the stdio protocol. Claude Code
remains deferred and is not represented as passed.
