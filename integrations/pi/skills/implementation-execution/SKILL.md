---
name: implementation-execution
description: Implement an accepted plan through bounded code slices while keeping a small project recovery note.
when:
  - An accepted plan needs code
does: Implement and verify one bounded slice; keep project continuity.
input: Plan, acceptance, authority, scope, permissions and evidence.
output: Code, slice evidence, continuity update and next stage.
notFor:
  - Alignment, planning, review, delivery or unknown failures
---

# Implementation Execution

## Suite Contract

This is one code stage in one continuous suite:
`alignment-and-decision -> implementation-planning -> implementation-execution
-> quality-gate -> independent-review`.

- Project scope selects the shared recovery note automatically. Do not create a
  workflow or work ID; Runtime refs only separate concurrent responsibility.
- Reread the upstream `User Source` before each slice. Original request,
  vision, and corrections outrank plans. Return changed choices to alignment
  and changed seams or dependencies to planning.
- This outer Skill is the outer owner of code changes and loads one conditional inner
  method at a time: `test-driven-implementation` for known work, or
  `systematic-debugging` while the cause is unknown.
- Runtime state is authority. Recovery documents are navigation, never
  permission, task state, or completion evidence.

## Workflow

1. Confirm active Runtime responsibility, acceptance aliases, permissions,
   cancellation, blockers, budget, and latest handoff.
2. Read only the bounded continuity block at the top of
   `docs/agent/chat-summary.md`, then inspect source needed for the next action.
   Source wins before an edit or verification claim.
3. Locate the single WorkDocument bound to active Runtime authority. Register
   its authority on the first approved write and reuse the canonical path.
   Never create a document per commit or code slice.
4. Preserve the WorkDocument's top `User Source`: `Original User Request` and
   `Original User Vision` stay byte-for-byte; corrections append verbatim and
   AI material stays below. Recheck hashes after recovery.
5. Choose the smallest dependency-ready vertical slice producing evidence for
   one unmet acceptance alias.
6. For known behavior, load TDD and follow its red/green loop. For an
   unexplained failure, debug until the cause is located. Return here after
   locating the cause and repair through TDD when a valid seam exists. Do not
   load both inner Skills at once.
7. Change the owning seam, inspect the real effect, and map fresh evidence to
   the exact alias. A Tool call, file, checkbox, or model claim is not proof.
8. Update the same WorkDocument and continuity block only when material state
   changes. In a Room, mirror the Runtime-owned workspace lifecycle in its one
   compact `Workspace Ledger`; follow the continuity reference and never infer
   ownership or success from a path.
   The active execution owner writes it; helpers return a small proposed delta.
9. Continue while a materially different legal action can advance acceptance.
   Preserve failed routes so compaction does not repeat them.
10. After planned code and slice checks pass, return `ready_for_quality`.
    Review is optional: the Facilitator decides whether risk warrants a
    distinct, post-integration review.

Read [the continuity contract](references/execution-continuity-contract.md)
before the first update and after compaction or handoff. A terminal authority
receipt archives the document; normal recovery excludes archives, which have
no automatic deletion timer.

## Managed Room Boundary

- Start only after Kernel alignment/definition/handoff. Continue the existing
  Root/Task/WorkItem, aliases, and participant binding; never create parallel
  state.
- A Worker executes only its directed responsibility. The Facilitator owns
  decomposition, reassignment, dependencies, and authoritative integration.
  A Worker may reject with a structured reason but never widen scope silently.
- Room companions are peers, not permanently reserved workers or reviewers. If
  several accepted slices are ready, the Facilitator dispatches every ready
  peer slice before using implementation files or commands, and may keep one
  explicit slice. Review is a later scoped duty for a peer independent of that
  authored or integrated scope.
- Participant identity is not a filesystem root. Use only the bound workspace
  harness and accepted evidence receipts. Read-only work may share a baseline;
  concurrent writable Workers need separate receipted workspaces from the same
  Root baseline. Never claim automatic worktree cloning.
- When implementation is authorized and a feature slice may require changes,
  start it as `isolated_writable`. A read-only task never becomes writable
  through handoff, a renamed objective, or a different owner. If read-only work
  finds a defect, return the evidence to the Facilitator; create a new
  `isolated_writable` implementation slice, integrate it, and assign a fresh
  post-integration review. Never loop a fix among read-only participants.
- `room_collaborate` is a bounded non-overlapping implementation child only
  after definition; never use it for intake, mention-based assignment, or review.
- Submit artifacts/evidence/handoff via `room_commit`; reserve `room_post` for
  progress. The Facilitator integrates results, then decides if risk warrants
  review; when chosen, the Kernel hands the WorkItem to a distinct participant.
- Re-read `room_state` after rejection or handoff. Stale or foreign authority
  blocks work and leaves ownership with the Facilitator; never replace state.
- Only the Facilitator/reporter emits the final public summary.

## No-Progress And Cancellation

Stop when two consecutive attempts leave the same acceptance, blocker,
evidence, and next action, or budget ends. Handoff, wait, or block with a
resume condition. On cancellation, stop immediately and make no late write.

## Output Contract

```text
alignment and plan refs | Runtime responsibility
WorkDocument path/revision | Workspace Ledger delta | current slice and changed files
evidence by acceptance alias | red/green or debugging result
continuity update | failed routes | blocker | smallest next action
status | unverified boundaries
```

Status: `continue`, `needs_alignment`, `needs_replan`, `ready_for_quality`,
`handoff`, `wait`, `blocked`, or `observed_cancellation`. Public updates mention only material behavior,
verification, risk, and the next user-relevant action.

## Self-Check

- Am I following the accepted plan and preserving original request and vision?
- Is one authority-bound document reused instead of a commit diary?
- Is exactly one inner method active and producing fresh evidence?
- Did I verify owning source rather than trust a recovery note?
- Is continuity small enough to read before project files?

## Boundaries

Do not run for intake, planning, review, or ordinary chat; create another state
store; invent IDs; manually move archives; record secrets, personal facts, raw
logs, or guesses; continue after cancellation; or claim final delivery. If
guidance forbids documentation writes, return the proposed document delta
to the caller instead of inventing storage.
