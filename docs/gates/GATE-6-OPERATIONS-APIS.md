# Gate 6 — Tasks, operations and public interfaces

- Contract version: `1.0.0`
- State: `PASS`

Persistent task queue, requests, progress, checkpoints and results live only in
`.lesr/runtime.sqlite3`; their updates do not move the Canonical Ref. Tasks support
durable queue/claim, batch checkpoints, cooperative cancellation, interrupted-state
detection and explicit resume. Full validation, Deep Trace, migration, backup and
large impact are the only task families. Canonical Git may receive a completed
high-risk Result Record later, never mutable progress.

Backup emits a Git Bundle, exact Repository Manifest binding and SHA-256 manifest.
Restore refuses non-empty destinations, verifies bytes before cloning, restores the
Canonical Ref and validates the 1.0 Manifest. Migration is post-1.0 forward-only,
always plans first, and creates a backup Ref before a registered step; an absent
step cannot advance Canonical State. Workspace GC is dry-run by default, retains 30
days, 20 latest checkpoints and every governance reference, and never requests
`git prune`.

CLI and MCP negotiate one frozen Capability Descriptor. MCP includes the approved
read/write subset and excludes private signing, arbitrary file/SQL/shell and all
administrative migration/restore/GC operations. Tests cover persistence/restart,
cancellation, Git isolation, tampered backup, empty restore, migration version
boundary, GC retention and capability exposure.
