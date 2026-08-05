# LESR MVP Architecture

> **SUPERSEDED:** 本文仅描述可从 `legacy-mvp-v0.1.0` 恢复的 YAML MVP。
> v1 架构以 `LESR_Codex_Construction_Spec_v1.0.md` 和新版基线为准。

YAML is the Git-managed fact source. SQLite is a rebuildable FTS5 index.
Domain services mediate all writes and append audit records. CLI and MCP are
transport adapters; neither embeds business rules nor directly writes SQL.
