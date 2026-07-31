---
name: implementation-planning
description: Turn confirmed requirements and decisions into the smallest dependency-aware implementation plan without starting work. Use for multi-step changes that need task boundaries, blockers, ownership, verification, or rollback.
when:
  - Confirmed work spans multiple steps or owners
does: Map acceptance to vertical tasks, blockers, owners, and evidence.
input: Confirmed alignment, implementation facts, constraints, and authority.
output: Ordered tasks, dependencies, integration gates, evidence, and rollback.
notFor:
  - Unconfirmed decisions, one-step work, execution, or file lists
---

# Implementation Planning

## Planning Invariants

- Reread the confirmed packet's immutable `User Source` block before planning.
  The original request and vision outrank every AI summary. Do not grill the
  user, replay requirement questions, or revise the selected approach.
- Begin each persisted plan with that block byte-for-byte. Keep originals,
  append corrections, and put planning interpretation below it.
- Preserve its reference and revision instead of copying it into a new workflow
  record. Project scope is automatic; do not invent a work ID between stages.
- Plan from observable acceptance backward, not from a directory tree forward.
- One state owner owns each shared contract; parallel lanes must not race on it.
- A candidate delivers an independently verifiable vertical result that fits
  one fresh Session; it is not a file list or an arbitrary Agent-sized chunk.

## Workflow

1. Compare the confirmed interpretation back to the verbatim request, vision,
   and appended corrections. Verify that scope, acceptance, permissions, and
   any material solution choice remain confirmed. If planning exposes a new
   user-owned choice, stop with `needs_alignment_decision` and return it to
   `alignment-and-decision`; do not ask or compare options here.
2. Inspect the current implementation before decomposing work. Resolve
   inspectable facts yourself. Identify state and contract owners, dependency
   direction, existing test seams, migrations, permissions, and extension
   points. Planning goes deeper than alignment only to locate executable seams.
3. Map every acceptance check to implementation work and fresh verification.
   Prefer the highest stable behavior seam already present.
4. First test whether one Session can finish the change coherently. If so,
   return one candidate instead of manufacturing parallel work.
5. Otherwise split into tracer-bullet candidates: each cuts a narrow but
   complete path through the affected layers, produces observable behavior,
   is independently verifiable, and fits one fresh context window. Do not split
   into "backend, frontend, tests" or per-file tasks.
6. Express every dependency as a blocking edge. A candidate with no unfinished
   dependencies is on the frontier. Name shared-contract owners, integration
   order, permission needs, cancellation effects, and rollback points.
7. Treat a wide mechanical migration as the exception to vertical slicing.
   Use expand-migrate-contract: introduce the compatible form, migrate
   blast-radius-sized batches, then remove the old form after every consumer
   has moved. Add an integrate-and-verify candidate when no batch can stay
   independently green.
8. Allow parallel candidates only when they cannot compete for the same state
   or contract. Otherwise serialize or combine them under one owner.
9. Keep the smallest plan that covers all acceptance without widening scope.

## Durable State Gate

When a plan adds or changes durable state, it is not ready until it includes:

- A stateful-object census: identity, persisted fields, lifecycle, and any
  replicas, caches, indexes, projections, or receipts for each object.
- One canonical owner for every object and transition, with all other copies
  explicitly read-only or derived.
- A transition table covering source state, event, preconditions, destination
  state, atomic effects, durable evidence, and recovery for each transition.
- Invariants that must hold within and across objects, including authorization,
  uniqueness, ordering, and terminal-state rules where applicable.
- Adversarial checks for crash boundaries, concurrent or duplicate operations,
  restart/restore/replay, and bypass attempts through alternate entry points.

Map every invariant and adversarial check to observable verification evidence.

## Task Candidate Contract

Each candidate must state:

```text
Objective:
End-to-end behavior:
Owned state or contract:
Inputs and blocking candidates:
Acceptance aliases:
Test seam and fresh evidence:
Permissions, workspace, and cancellation:
Rollback or integration signal:
```

When candidates share a contract, add one integration owner and an explicit
order: contract first, independent consumers second, integration verification
last. Serialize candidates that must edit the same owner.

## Output Contract

The full plan starts with `User Source`, then labeled AI interpretation. Return
its source hash/ref, ordered candidates, owners, blockers, frontier,
parallel/serial choice, evidence gates, non-goals, rollback, and one status:
`ready_for_kernel_start`, `needs_alignment_decision`, or
`blocked_by_external_fact`. A candidate is not managed work until the Kernel
accepts it. Once bound to a Goal, Task, or Dispatch, route the accepted plan
reference and exact acceptance aliases to `implementation-execution`.

Keep the full contract for the caller. In a public reply, show the ordered
candidate titles, blocking graph, material risks, and status. Do not repeat the
confirmed requirements or dump every field unless requested.

## Self-Check

- Does every acceptance item map to implementation and verification?
- Did I check the plan against original request and vision, not an AI summary?
- Is each candidate a complete vertical result sized for one fresh Session?
- Are blocking edges and the current frontier explicit?
- Is every parallel lane safe without concurrent ownership of the same state?
- Is the integration order and rollback point explicit?
- Could one coherent Session do this more simply?
- Did I avoid re-grilling, creating work, or choosing Agents?

## Boundaries

Do not allocate Agents, create WorkItems or Dispatches, grant capabilities,
publish tracker tickets, write implementation code, or invent a master/sub-Agent
hierarchy. Revise a plan from specific feedback, but do not turn planning into
another interview or overwrite the `User Source` block. User approval belongs
to material choices; Kernel acceptance turns candidates into managed work.
