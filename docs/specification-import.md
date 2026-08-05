# Specification import boundary

Import is a preview-only adapter. It produces structured semantic operations for
a Change Workspace and never writes Canonical State, approves content, creates a
Baseline or updates the query projection.

## Supported preview inputs

- UTF-8 Markdown: one candidate per non-empty heading section.
- Text PDFs that the operator is entitled to process: one candidate per selected
  page, with page number and source hash provenance.

Encrypted/restricted PDFs are rejected before text extraction. OCR, password
handling and permission bypass are not features. Source PDFs and extracted
licensed standard text must not be committed.

Each candidate contains exactly two schema-valid operations:

1. `create_logical_object` with a new Internal UID and Human Key;
2. `create_revision` with imported provenance and source anchors.

The candidate must then pass ordinary Workspace, review-package, human approval,
Delegation and atomic Apply controls. There is no import-specific authority path.

## Determinism and provenance

The source content hash, local filename, section/page anchor and extractor
identity are fields of the candidate Revision. Re-running preview may allocate
new candidate UIDs; accepting a candidate therefore binds the reviewed semantic
operation hashes and exact source hash in the Review Package.

## Local evaluation corpus

`测试文档/` is ignored by Git. The unencrypted local ASPICE-like document is used
for page-anchor integration tests. The encrypted MISRA document is used solely
to verify fail-closed refusal. Executable MISRA-like rules in the committed test
suite are synthetic and do not reproduce protected standard text.
