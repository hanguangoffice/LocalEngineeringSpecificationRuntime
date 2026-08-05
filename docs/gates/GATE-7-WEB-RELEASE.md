# Gate 7 — Local Web product and RC release

- Contract version: `1.0.0`
- State: `PASS`
- Runtime candidate: `1.0.0rc1`

## Implemented contract

The product UI uses FastAPI/Uvicorn, packaged server templates, and native JavaScript
and CSS. It has no Node build, CDN, or remote asset, and binds only to `127.0.0.1`.
The interface exposes repository health, structured search, Context, Working Copy,
review/signing, Baseline, persistent task, and maintenance surfaces. Capability
negotiation does not advertise MCP tools absent from the adapter.

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
- Real Playwright browser flow through unlock, Resolve/Query, Context, and lock.
- One-shot signer and encrypted-key fallback tests.
- Small CI performance data: 1,000 Objects, 5,000 Revisions, 10,000 Relations with full
  Formal Trace semantics and 10 warm-ups plus 100 measured samples.
- Medium local measurement: 10,000/50,000/100,000, 12.764 s dataset construction and
  0.019268 s Context Manifest P95. The machine is a documented non-reference Windows
  environment; it does not replace the frozen Windows 11/32 GiB record.
- One wheel and one sdist, verified byte-for-byte for runtime sources, schemas, Web
  assets, type marker, metadata, and isolated installation.

The medium release and large stress protocols remain distinct recorded measurements;
they do not weaken or disable Formal Trace, Rule, Configuration Resolution, or
transaction integrity.
