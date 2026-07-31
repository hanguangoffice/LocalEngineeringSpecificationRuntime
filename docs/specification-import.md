# Specification Import Preview

LESR imports specifications in two stages:

1. preview source content as review candidates;
2. accept one exact reviewed candidate as a formal draft Artifact.

A preview never creates formal Artifacts, Relations, audit events, versions, or
runtime indexes. Acceptance is an explicit CLI action and creates only a draft;
it does not approve or baseline the Artifact.

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
an approved engineering specification.

## Accepting one reviewed candidate

After reviewing the preview, copy the exact candidate ID and source content
hash into the acceptance command:

```powershell
lesr import-accept demo specifications/demo-standard.md `
  CAND-C2E1FAE70A36 `
  --expected-source-hash "sha256:..." `
  --actor reviewer `
  --artifact-type coding_rule `
  --version 1.0
```

The candidate identity is bound to the source path, normalized content hash,
source version, Artifact type, section location, ID, title, and statement.
Acceptance therefore fails if reviewed inputs are silently changed.

Acceptance also fails before formal writing when:

- the current source hash differs from the reviewed hash;
- the candidate is absent from the newly generated preview;
- the candidate does not contain a stable Artifact ID;
- the candidate has unresolved warnings;
- the Artifact ID already exists.

A successful acceptance creates:

- `artifacts/<ID>.yaml` with `status: draft`;
- `.lesr/versions/<ID>/v0001.json`;
- an `artifact.create` audit event attributed to the human actor.

The Artifact stores its original document ID, path, content hash, version,
section, line range, page (when available), and import candidate ID under
`attributes.provenance`.

Acceptance does not approve, baseline, index, or expose the Artifact through
MCP automatically. Those actions remain separate controlled workflows.
