# Gate 7 — Local Web product and RC release

- Contract version: `1.0.0`
- State: `PASS`
- Runtime candidate: `1.0.0rc2`

## Implemented contract

The product UI uses FastAPI/Uvicorn, packaged server templates, and native JavaScript
and CSS. It has no Node build, CDN, or remote asset, and binds only to `127.0.0.1`.
The HTTP adapter exposes repository health, structured search, Context, Working Copy,
Rebase/Merge/Conflict Resolution, review records/signing, Apply, Baseline, persistent
task, Reconciliation and maintenance capabilities. The HTML console completes the
primary product workflow from Working Copy through Baseline. Capability negotiation
does not advertise MCP tools absent from the adapter.

Access requires a process-generated one-time launch token. The resulting 15-minute
idle session uses an HttpOnly/SameSite=Strict cookie, Host/Origin validation, CSRF,
no-store responses, and a restrictive Content Security Policy. Before signing, the UI
loads the Canonical Review Package and displays Package Hash, Effective Model, Scope,
role, conditions, and expiry. The signing endpoint reloads the Canonical resources and
requires explicit human confirmation.

Windows private keys use current-user DPAPI. Linux uses Secret Service when available;
otherwise scrypt-derived AES-GCM protects an Ed25519 PKCS#8 document with user-only
permissions and a password. A one-request broker communicates over a Windows Named Pipe
or Unix socket and exits after signing. There is no plaintext fallback or MCP signing
capability.

## Evidence

- HTTP security and packaged-asset contract tests.
- Real `LocalRuntimeService` Playwright browser flow through unlock, repository-backed
  Query and lock, plus Open -> Edit -> Submit -> one-shot Human Sign -> atomic Apply ->
  Baseline Prepare -> Human Sign -> Baseline Apply. No in-memory product fake is used.
- One-shot signer and encrypted-key fallback tests.
- Small CI performance data: 1,000 Objects, 5,000 Revisions, 10,000 Relations with full
  Formal Trace semantics and 10 warm-ups plus 100 measured samples.
- Medium local measurement (2026-08-10): 10,000/50,000/100,000, 11.844956 s dataset
  construction and 0.016315 s Context Manifest P95. Large stress measurement:
  100,000/500,000/1,000,000, 119.446989 s construction and 0.162790 s Context P95,
  with no semantic feature disabled. The machine is a documented non-reference Windows
  environment; it does not replace the frozen Windows 11/32 GiB record.
- One wheel and one sdist, verified byte-for-byte for runtime sources, schemas, Web
  assets, type marker, metadata, and isolated installation.

Gate 7 passes the internal RC2 release gate. This is not an independent certification
or the final historical runtime tag; external reassessment is the remaining
release-boundary activity. Medium and large measurements do not weaken or disable
Formal Trace, Rule, Configuration Resolution, or transaction integrity.
