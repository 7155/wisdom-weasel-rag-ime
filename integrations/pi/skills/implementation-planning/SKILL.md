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
- Give every vertical result one stable `RoomTask` identity with kind `feature`.
  Retry, recovery, reassignment, or another execution attempt must retain that
  task identity. Do not add a parallel FeatureWorkItem, Job, Unit, or Step
  lifecycle beside existing Task and Dispatch owners.
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
5. Express dependencies through stable feature `RoomTask` identities as blocking edges.
   Reject missing targets, self-dependencies, cycles, and a manually declared
   wave that contradicts the graph. Work with no unfinished blocking edges is
   on the frontier; waves are derived from the graph and resource/write
   conflicts. Name owner, order, permission, cancellation, integration, and
   rollback boundaries.
6. For wide migrations use expand-migrate-contract: add a compatible form,
   migrate bounded batches, then remove the old form after consumers move.
7. Parallelize only when at least two candidates have non-overlapping
   responsibilities, no unmet prerequisite, and a material waiting-time
   benefit. Otherwise serialize or combine them under one owner; never create
   parallel work merely to fill a roster.
   Always lock shared contracts before parallel work; expose dependency waves and write boundaries.
8. Keep one authoritative owner for each shared contract and one active
   integration lease for each affected shared scope; do not turn that lease into
   a permanent Integrator rank. For concurrent writable feature owners, require
   separate receipted workspaces from the same Root baseline; read-only work may
   share a baseline. Integration scopes may be assigned to any eligible peer
   and must record their own provenance.
9. Every active Room companion is a peer. The receiving/coordinating companion
   may own a complete feature; an owner may return in a later wave, never twice
   in one wave. Do not reserve an idle Reviewer. For code, data, artifact, or
   integration-changing Rooms, plan bounded independent review targets after
   integration from actual authorship and integration provenance. Pure
   discussion or read-only work may carry an explicit policy exemption.
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
store. This Skill proposes the PlanRevision and stable vertical `RoomTask`
definitions; the
Kernel owns accepted identities, assignment revisions, dependency readiness,
and execution release. It must not silently recruit companions or create
Dispatches. Candidates remain non-overlapping; review is post-integration and
is represented by bounded targets, never a planning child or permanent role.
Stale, foreign, or missing authority returns a governed wait or blocker.
- Consume `room_state` for the current aliases, then use
  `room_commit(handoff)` only after the active alignment Dispatch has fenced
  the next target. Start materializes approved `RoomTask` identities and the
  Kernel releases their attempts from dependency state; the model does not call
  `room_collaborate` to consume plan positions or supply replacement free text.
  Review is a post-integration handoff to an eligible participant for each
  required bounded target.
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

Shared contracts need one authoritative owner and explicit order: contract,
independent consumers, scoped integration lease, integration verification.

## Output Contract

Start with `User Source`, then AI interpretation. Return source hash/ref,
PlanRevision proposal, ordered stable feature Tasks, peer owner recommendations,
blocking feature identities, frontier, derived waves, explicit parallel/serial
choice, scoped integration owners/workspace, required review targets or an
explicit read-only exemption, evidence gates,
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
- Did I leave accepted identity, assignment, readiness, and roster changes to
  the Kernel rather than call order, round-robin, or free-text mentions?

## Boundaries

Do not allocate Agents, create managed work, publish tracker tickets, write
implementation code, reopen confirmed choices, or invent a hierarchy.
