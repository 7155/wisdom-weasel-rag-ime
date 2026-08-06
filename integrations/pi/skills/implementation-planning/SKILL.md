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

- Reread the confirmed packet's immutable `User Source`; the original request and vision outrank every AI summary.
  Do not grill the user or revise the selected route.
- Begin each persisted plan with that block byte-for-byte. Preserve its ref and
  revision; do not invent a work ID between stages.
- Plan backward from observable acceptance. A candidate is a verifiable
  vertical result for one fresh context window, never a file list.
- One canonical owner controls each shared contract; derived copies are read-only.

## Workflow

1. Compare interpretation with verbatim request, vision, corrections, scope,
   acceptance, permissions, and decision. If a new user-owned choice appears,
   stop with `needs_alignment_decision` and return it to
   `alignment-and-decision`; do not ask or compare options here.
2. Inspect implementation plus the confirmed Domain Language Delta, glossary,
   and ADRs. Locate owners, dependency direction, test seams, migrations,
   permissions, and extension points. Planning goes deeper than alignment only
   to locate executable seams.
3. Map every acceptance check to implementation and fresh verification. Prefer
   the highest stable behavior seam already present.
4. If one Session can finish coherently, return one candidate. Otherwise use
   tracer-bullet candidates: each crosses affected layers, produces observable
   behavior, is independently verifiable, and fits one fresh context window.
   Each candidate owns one user-visible feature end-to-end. Never split one feature by technical layer.
5. Express dependencies as blocking edges. Work with no unfinished blocking
   edges is on the frontier. Name owner, order, permission, cancellation,
   integration, and rollback boundaries.
6. For wide migrations use expand-migrate-contract: add a compatible form,
   migrate bounded batches, then remove the old form after consumers move.
7. Parallelize only when at least two candidates have non-overlapping
   responsibilities, no unmet prerequisite, and a material waiting-time
   benefit. Otherwise serialize or combine them under one owner; never create
   parallel work merely to fill a roster.
   Always lock shared contracts before parallel work; expose dependency waves and write boundaries.
8. Keep one Facilitator/Integrator accountable for shared contracts and the
   authoritative workspace. For concurrent writable children, require a
   separate receipted workspace from the same Root baseline; read-only work
   may share a baseline.
9. Every active Room companion is a peer. The Facilitator may own a complete
   feature while coordinating and integrating; an owner may return in a later
   wave, never twice in one wave. Select any required Reviewer after integration
   from actual provenance, not from a permanent capability tier.
10. Keep the smallest plan covering all acceptance without widening scope.
11. Produce a bounded WorkDocument delta from the latest user requirements and
    planning progress: current interpretation, accepted/rejected route,
    vertical candidates, dependencies, waves, risks, and next action. Before
    Start this is a proposed delta only; after approval the execution owner
    writes it to the one bound WorkDocument instead of creating a second plan
    file.

## Managed Room Boundary

`room_define` is the alignment commit, not a planning Tool. Consume the
existing Root/Task, WorkItem, aliases, participant binding, and receipts after
Kernel handoff. Do not create another Root, Task, Dispatch, WorkItem, or task
store. The Facilitator owns decomposition, assignment, reassignment,
dependency handling, and integration; this Skill may describe candidate
capabilities and owners, but must not silently recruit or create Dispatches.
Candidates remain non-overlapping; review is post-integration, never a planning child.
Stale, foreign, or missing authority returns a governed wait or blocker.
- Consume `room_state` for the current aliases, then use
  `room_commit(handoff)` only after the active alignment Dispatch has fenced
  the next target. `room_collaborate` remains only a bounded implementation
  child; review is an optional post-integration handoff to a distinct
  participant.
- Participant Session/Dispatch identity is distinct from filesystem roots.
  Act only through the bound workspace harness and accepted evidence receipts;
  a path does not establish isolation.

## Durable State Gate

State-changing plans must include:

- a stateful-object census of identity, fields, lifecycle, replicas, caches,
  indexes, projections, and receipts;
- one canonical owner per object and transition;
- a transition table with state, event, preconditions, atomic effects,
  durable evidence, and recovery;
- invariants for authorization, uniqueness, ordering, and terminal states;
- adversarial checks for crash boundaries, concurrent or duplicate operations,
  restart/restore/replay, and bypass attempts.

Map every invariant and adversarial check to observable evidence.

## Candidate Contract

```text
Objective | end-to-end behavior | owned state or contract
Inputs and blocking candidates | acceptance aliases
Test seam and fresh evidence | permissions and cancellation
Rollback or integration signal
```

Shared contracts need one integration owner and explicit order: contract,
independent consumers, integration verification.

## Output Contract

Start with `User Source`, then AI interpretation. Return source hash/ref,
ordered candidates, capability-compatible owner recommendations for the
Facilitator, blockers, frontier, explicit parallel/serial choice, one
integration owner/workspace, review-warrant decision, evidence gates,
non-goals, rollback, and `ready_for_kernel_start`,
`needs_alignment_decision`, or `blocked_by_external_fact`. Once the Runtime
accepts the plan, route the accepted plan reference and exact acceptance
aliases to `implementation-execution`.

Publicly show titles, blocking graph, material risks, continuity, and status in
the user's language and from the user's point of view. Do not repeat the
confirmed requirements, expose internal type or field inventories, assert an
uninspected entry point as fact, or dump every field unless requested.

## Self-Check

- Does every acceptance item map to implementation and fresh verification?
- Is each candidate a complete vertical result for one fresh Session?
- Are blocking edges, frontier, shared owners, order, and rollback explicit?
- Could one coherent Session do this more simply?
- Did I leave assignment and roster changes to the Facilitator/Kernel rather
  than use round-robin or free-text mentions?

## Boundaries

Do not allocate Agents, create managed work, publish tracker tickets, write
implementation code, reopen confirmed choices, or invent a hierarchy.
