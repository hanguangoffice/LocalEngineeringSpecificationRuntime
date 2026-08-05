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

Protocol subprocess tests and Codex pass. Claude cannot currently establish a
normal model session, so it cannot supply the second-client evidence. P5 remains
`BLOCKED_CLIENT_VALIDATION`; P1-P5 are therefore not all passed, and the legacy
runtime must not be replaced yet.
