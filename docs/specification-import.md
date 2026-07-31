# Specification Import Preview

LESR imports specifications in two stages:

1. preview source content as review candidates;
2. publish explicitly approved candidates through a controlled workflow.

Only the first stage is currently implemented. A preview never creates formal
Artifacts, Relations, audit events, versions, or runtime indexes.

## Supported input

The initial importer accepts UTF-8 Markdown files inside the selected LESR
project directory. Each non-empty level-two heading becomes one candidate:

```markdown
# Home communication standard

## RULE-COM-001 MQTT reconnect

The client shall reconnect after an unexpected disconnect.
```

Headings should start with a stable LESR ID. Missing IDs and empty sections are
reported as review warnings. The importer does not invent missing requirements.

## Command

```powershell
lesr import-preview demo specifications/demo-standard.md `
  --artifact-type coding_rule `
  --version 1.0
```

The command returns JSON containing:

- normalized source identity and SHA-256 hash;
- candidate Artifact IDs, types, titles, statements, and review status;
- source section and exact Markdown line range;
- deterministic normative-level hints;
- stable warnings that require human review.

Relative source paths are resolved against the project directory. Sources
outside the project directory and non-UTF-8 or unsupported files are rejected
with stable LESR error codes.

## Trust boundary

All output has `review_status: candidate`. Preview output must not be treated as
an approved engineering specification. A later workflow will support explicit
review, correction, approval, rejection, formal persistence, and audit.
