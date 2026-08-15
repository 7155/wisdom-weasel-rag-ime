---
name: improve-codebase-architecture
description: Find evidence-backed architecture improvements before refactoring.
when:
  - User explicitly asks to improve codebase architecture
does: Inspect real friction and return one to three candidates for user selection.
input: Repository, scope, recent changes, architecture docs, and checks.
output: Candidates with evidence, benefit, risk, and deletion test.
notFor:
  - Known local bug or formatting cleanup
  - An unselected broad refactor
---

# Improve Codebase Architecture

Method provenance: this Room-bounded Skill adapts Matt Pocock's
`improve-codebase-architecture` at upstream commit
`2ab958093e83e0ec752e6c1c5932da465bf23e0c`. Its deep-module vocabulary and
deletion test are retained; Room alignment, execution, workspace, review, and
user-decision gates remain authoritative.

## Evidence Standard

Architecture work earns its cost only when it removes repeated decisions,
clarifies lifecycle ownership, or makes a meaningful boundary independently
testable. File size, naming taste, and abstract "cleanliness" are not evidence.

## Workflow

1. Read the repository guide, domain glossary, architecture decisions, current
   plan, and recent changes before proposing structure.
2. Inspect real friction: mixed lifecycle ownership, repeated branching,
   duplicated contracts, unstable dependencies, hard-to-test state, and files
   that change for unrelated reasons. File size alone is not evidence.
3. Trace each candidate through its interface, callers, state owner, side
   effects, tests, and downstream consumer. Ask:
   - **depth**: does the module hide meaningful complexity behind a small,
     stable interface?
   - **locality**: can a maintainer understand and change one behavior without
     opening unrelated lifecycle owners?
   - **seam**: is there a natural boundary for testing, substitution, or
     migration, rather than an artificial wrapper?
   - **adapter**: is compatibility translated once at the edge, or leaking
     branches through the core?
   - **leverage**: will one change delete repeated decisions across callers?
4. Keep only one to three candidates with concrete evidence and a reversible
   boundary. Prefer deletion, a thinner entry point, a deeper owner module, or
   composition over a new abstraction.
5. For each candidate, state:
   - symptom and source locations;
   - current owner and desired owner;
   - smallest coherent change;
   - compatibility, migration, and rollback risk;
   - the **deletion test**: which branches, adapters, state copies, or files become
     unnecessary afterward;
   - verification that would prove the change.
6. Recommend an order, but do not implement until the user selects a candidate.
7. After selection, send any unresolved module shape, seam, surviving-test, or
   product tradeoff to `alignment-and-decision` in explicit Grill Mode. Carry
   its Domain Language Delta into `implementation-planning`. If no material
   choice remains, planning may consume the selected card directly.

## Candidate Card

```text
Symptom and locations:
Current owner -> desired owner:
Callers and downstream consumers:
Smallest coherent change:
What becomes deletable:
Compatibility and migration:
Rollback:
Fresh verification:
Expected maintenance gain:
```

Reject a candidate when it only moves lines, creates a wrapper without hiding
complexity, duplicates a runtime path, or requires broad migration before any
behavior can be verified.

## Output Contract

Return the shortlist and stop at `awaiting_selection`, `no_high-value_candidate`,
or `blocked_by_missing_evidence`.

## Self-Check

- Does each candidate follow a real call path and state owner?
- Will the change delete branches, state copies, or repeated translations?
- Is the entry point thinner and the owning module deeper?
- Can the change be verified and rolled back independently?
- Did I keep implementation outside the architecture-selection phase?

## Boundaries

Do not refactor to satisfy a line-count target, invent a second runtime path,
silently change public contracts, open managed execution, or claim architectural
improvement without a focused diff and fresh verification. Runtime lifecycle and
native permission rules remain authoritative.
