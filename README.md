# LESR

Local Engineering Specification Runtime (LESR) turns Git-managed engineering
specifications into structured, auditable local objects.

## Current implementation

The Phase 0–7 MVP is implemented: structured YAML facts, Profile validation,
SQLite/FTS5 retrieval, controlled change and baselines, context construction,
MCP query tools, and the `examples/home-control` project.

```powershell
python -m lesr.cli.main init demo
python -m lesr.cli.main artifact-create demo REQ-SW-0001 software_requirement "Reconnect MQTT" --statement "The client shall reconnect after an unexpected disconnect."
python -m lesr.cli.main artifact-get demo REQ-SW-0001
```

YAML files are the source of truth. The `.lesr/` directory contains rebuildable
runtime state, snapshots, and audit records.

## Specification import preview

UTF-8 Markdown specifications can be converted into review candidates without
writing formal project data:

```powershell
lesr import-preview demo specifications/demo-standard.md --artifact-type coding_rule
```

Every candidate includes source provenance and remains in `candidate` review
status. See [the import-preview documentation](docs/specification-import.md).
