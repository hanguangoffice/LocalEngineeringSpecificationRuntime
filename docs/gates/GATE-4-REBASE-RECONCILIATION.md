# Gate 4 — Rebase, Merge and Reconciliation

- Contract version: `1.0.0`
- State: `PASS`

Rebase and Workspace Merge share one Base/Ours/New Base semantic three-way engine.
Different fields, Fragments and Relation identities merge automatically. Same-field,
delete/modify, Kind/Facet, Human Key, Relation endpoint and governed
Rule/Profile/Deviation changes become immutable, hashed Merge Conflict resources.
Every conflict remains open until an explicit Resolution Operation; high-risk
identity and governance conflicts reject AI/tool resolution.

Every rebase result unconditionally invalidates prior Approvals and requires rebuild
of Graph Snapshot, Rule, Validation, Context, Impact and Review Package. The engine
does not treat an ordinary Git merge as Canonical authority.

Foreign Canonical Ref movement is captured as a hashed Foreign Diff and opens a
dedicated Workspace marked non-authoritative pending reconciliation. No file edit or
merge commit advances semantic authority without the normal review/apply pipeline.

The production Runtime, CLI, MCP and loopback HTTP adapter expose Rebase, Workspace
Merge, explicit Conflict Resolution and Reconciliation Open through the uniform write
envelope. Workspace refs persist merge state across process restart, and a rebase or
merge removes the prior Submission, Review Package, evidence and review records.

Tests exercise independent-field auto-merge, dual edits, governed identity conflict,
human-only resolution, public API persistence, invalidation/rebuild flags and foreign
merge reconciliation.
