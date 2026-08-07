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

one continuous suite:
`alignment-and-decision -> implementation-planning -> implementation-execution
-> quality-gate -> independent-review`.

- Project scope selects the shared recovery note automatically. Do not create a
  workflow or work ID; Runtime refs only separate concurrent responsibility.
- Reread the upstream `User Source` before each slice. Original request,
  vision, and corrections outrank plans. Return changed choices to alignment
  and changed seams or dependencies to planning.
- This Skill owns code changes and loads one conditional inner
  method at a time: `test-driven-implementation` for known work or
  `systematic-debugging` while the cause is unknown.
- Runtime state is authority; recovery notes navigate, not grant permission.

## Workflow

1. Confirm Runtime responsibility, acceptance aliases, permissions,
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
   Treat the same governed Markdown file as two clearly separated logical
   records: the requirement record (`User Source` plus confirmed interpretation)
   and the execution record (accepted plan, current slice, evidence, failures,
   and next action). Do not create two independently drifting documents.
   If the user adds, corrects, withdraws, or reprioritizes a requirement, append
   the exact words immediately, reconcile the current interpretation and plan,
   and return to alignment or planning when the change affects a user-owned
   choice or task boundary. Never continue from a stale summary.
5. Choose a dependency-ready vertical slice producing evidence for
   one unmet acceptance alias.
6. For known behavior, load TDD and follow its red/green loop. For an
   unexplained failure, debug until the cause is located. Return here after
   locating the cause and repair through TDD when a valid seam exists. Do not
   load both inner Skills at once.
7. Change the owning seam, inspect the real effect, and map fresh evidence to
   the exact alias. A Tool call, file, checkbox, or model claim is not proof.
8. Update the same WorkDocument and continuity block from your own real progress
   whenever material state changes: current slice/Todo, changed artifacts,
   evidence, failed route, blocker, recovery decision, remaining risk, handoff,
   or next action. Do not wait until the final summary and do not copy a Tool
   transcript. In a Room, mirror the Runtime-owned workspace lifecycle in its one
   compact `Workspace Ledger`; follow the continuity reference and never infer
   ownership or success from a path.
   The active execution owner writes it; helpers return a small proposed delta.
9. Continue while a materially different legal action can advance acceptance.
   Preserve failed routes so compaction does not repeat them.
10. After planned code and slice checks pass, return `ready_for_quality`.
    Code, data, artifact, and integration-changing Room work requires a bounded
    independent review target after integration. Pure discussion or read-only
    work may proceed without review only when `room_state.executionPolicy`
    records that exemption. A model must not silently disable review.
11. When repairing an independent-review finding, the original feature owner or
    another eligible non-reviewer performs the change and records new evidence.
    The Reviewer does not repair and approve the same target; the changed
    revision returns through quality and receives a fresh independent review.

Read [the continuity contract](references/execution-continuity-contract.md)
before the first update and after compaction or handoff. A terminal authority
receipt archives the document; normal recovery excludes archives, which have
no automatic deletion timer.

## Managed Room Boundary

- Do not start writes or tests before user approval of the visible execution plan.
- After governed handoff, reuse the bound Root, stable feature `RoomTask`,
  participant, and workspace. A retry or replacement creates another attempt,
  never another Task identity.
- A peer companion owns one accepted user-visible feature end-to-end.
  Coordination, scoped integration, review, and final reporting are separate
  responsibilities; none creates a permanent master/worker rank.
- Receipted workspaces grant filesystem authority. Concurrent writes need
  separate Root worktrees; never claim one without its receipt.
- Never clean a workspace with `git stash/reset/clean/checkout/restore`;
  preserve existing work and repair its Room/worktree owner.
- One Room Agent owns a user-visible feature end-to-end; helpers may do bounded
  private work, but their parent verifies and integrates it. Other Room peers
  should receive separate complete features, not summary work that a private
  helper could perform.
- Recoverable batch processing through the project's existing public entry is one feature and stays single-owner unless other independent features exist.
- Treat that example as a located boundary fix, then apply the analogy to any project type: preserve failures, retry decisions, and evidence inside the owning feature.
- Do not call `room_collaborate` to recreate or reorder an approved plan. Start
  materializes every stable Task and the Kernel automatically releases each
  dependency-ready owner attempt. `room_collaborate` remains only for a
  separately authorized legacy/nested scope outside PlanRevision; it is never
  intake or review. Return evidence with `room_commit`.
- Keep one concrete Session Todo. After material progress, call
  `todo.checkpoint` with file, diff, artifact, or test references; avoid count-only churn.
- Any eligible peer may receive a scoped integration responsibility under the
  Kernel's single active lease for that scope. Required review targets are
  selected from real authorship, repair, and integration provenance. Re-read
  `room_state` after rejection/handoff; stale authority blocks work rather than
  replacing it. Integration and review are performed by a distinct participant
  where the target policy requires it, through the bound workspace harness and
  accepted evidence receipts; prose or a filesystem path cannot substitute.

## No-Progress And Cancellation

Stop when two consecutive attempts leave the same acceptance, blocker, evidence and next
action, or budget ends. Handoff, wait, or block with a resume condition. On
cancellation, stop immediately and make no late write.

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
- Does it reflect the newest user requirements and my latest material progress?
- Is exactly one inner method active and producing fresh evidence?
- Did I verify owning source rather than trust a recovery note?
- Is continuity small enough to read before project files?

## Boundaries

Do not run for intake, planning, review, or ordinary chat; create another state
store or replacement state; invent IDs; manually move archives; record secrets, personal facts, raw
logs, or guesses; continue after cancellation; or claim final delivery. If
guidance forbids documentation writes, return the proposed document delta
to the caller instead of inventing storage.
