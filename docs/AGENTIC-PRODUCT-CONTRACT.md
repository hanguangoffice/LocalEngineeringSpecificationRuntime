# LESR agentic product contract

Status: implementation contract for the post-1.2 product line.

## Product purpose

LESR is the deterministic engineering control plane used by people and AI agents.
It is not a local single-user ALM clone and does not expose its internal semantic
operations as the normal user workflow.

A user starts a **Mission** with a goal, scope and acceptance criteria. LESR then:

1. derives the applicable engineering structure from the active Profile and source
   templates;
2. supplies exact Context to specialist agents;
3. coordinates recoverable Working Copies, validation, impact analysis and tests;
4. continues automatically while work remains inside the Mission Mandate; and
5. creates a readable Decision Request only when policy requires a human decision.

## Product layers

```text
Human product surface
  Project map / Missions / Engineering content / Decisions / Versions

Agent execution plane
  Mission / Work Package DAG / Agent Run / integration / retry / hand-off

Deterministic control plane
  Configuration / Context / Workspace / Rule / Impact / Governance / Git transaction

Persistence
  Git Canonical State and Workspace refs / rebuildable SQLite runtime projections
```

The product surface never asks a person to assemble Workspace, UID, Hash, Git Ref,
Delegation or Context Contract inputs. Those remain inspectable in audit diagnostics.

## Mission and Work Package boundary

- A Mission is local runtime state representing one user goal.
- A Mission Mandate records the actor, repository, configuration, allowed engineering
  scope, permitted operation families, limits and expiry.
- Work Packages form an acyclic dependency graph. A blocked package does not prevent
  unrelated ready packages from progressing.
- Agent Runs record execution, evidence and hand-off state. They are operational state,
  not engineering facts and do not enter Canonical Git.
- Candidate engineering work remains recoverable through Workspace refs.
- Completed engineering changes enter Canonical State only through the existing Git
  transaction boundary.

## Decision policy

The caller does not choose a risk class. LESR derives one of four dispositions from
the actual semantic diff, lifecycle state, active Profile, Mission Mandate, impact and
external effects:

- `AUTO_EXECUTE`: continue without interrupting the user;
- `BATCH_FOR_MILESTONE`: retain the item and include it in one coherent milestone
  decision;
- `HUMAN_DECISION_NOW`: create a Decision Request and pause only dependent work;
- `BLOCK`: the proposed action cannot proceed under the current model.

Planning, Context collection, Working Copy editing, validation, testing, repair,
checkpointing, agent review and conflict-free rebase are automatic. A human decision is
reserved for a change to the requested outcome or acceptance criteria, an unresolved
material alternative, an explicitly human Profile role, Profile/trust/authority changes,
Deviation or Exception approval, destructive external effects, and formal Baseline or
Release responsibility.

An in-scope delegated Apply is recorded as delegated execution. It is never represented
as an AI-issued human Approval.

## Decision Request

A Decision Request is persistent and has one primary action. Its normal representation
contains:

- decision type and engineering area;
- the Mission goal and why the decision is needed;
- a readable before/after change summary;
- affected requirements, design, tests, evidence and deliverables;
- validation results and remaining uncertainty;
- the integrating agent's recommendation and materially different alternatives; and
- what accepting or rejecting the decision will do.

Technical identifiers and detached signatures are audit details, not the explanation.

## Engineering presentation

Presentation mappings are non-authoritative Profile/template-owned revisions. They map
Kind, Facet and Relation Type selections into engineering areas, hierarchy, document,
matrix, graph and baseline views. They do not create objects, relations, applicability
or compliance facts.

The Web product must therefore derive its navigation from the selected mapping. An
ASPICE-like Profile may expose SYS/SWE/SUP; a general software Profile may expose Goal,
Requirement, Architecture, Implementation, Verification and Release; another domain may
use different areas. The Web adapter must not hard-code any of those taxonomies.

## Integrity and signing boundary

- Git Commit/Tree identity and expected-old-value ref updates protect stored state and
  concurrency.
- Stable semantic UIDs identify domain resources.
- One canonical subject digest may bind a detached formal human decision or an exported
  artifact.
- Per-object or per-operation digests need a documented boundary consumer; hashes are
  not added merely to duplicate Git storage integrity.
- Human signing is optional unless the active Profile requires it. When required, the
  private key remains outside the repository and is protected by the operating system or
  an encrypted fallback.
- A local process challenge does not by itself prove human presence. The product must not
  claim stronger presence guarantees than the selected key provider supplies.

## Compatibility

This contract deliberately changes the default 1.2 interaction model. Existing 1.0
Canonical resources remain readable while the new Mission, agent and presentation data
are introduced. The old step-by-step Web workflow and caller-supplied `risk_class` are
not compatibility promises.
