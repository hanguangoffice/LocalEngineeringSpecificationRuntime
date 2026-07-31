# LESR MVP Architecture

YAML is the Git-managed fact source. SQLite is a rebuildable FTS5 index.
Domain services mediate all writes and append audit records. CLI and MCP are
transport adapters; neither embeds business rules nor directly writes SQL.
