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

This is the code implementation stage of one continuous suite:
`alignment-and-decision -> implementation-planning -> implementation-execution
-> quality-gate -> independent-review`.

- Project scope selects the shared recovery note automatically. Do not create a
  workflow or work ID. Existing Goal, Task, or Dispatch references only
  distinguish concurrent Runtime responsibilities.
- Reread the upstream `User Source` block before each new slice. Its verbatim
  request, vision, and appended corrections outrank derived plans. Return a
  changed user choice to `alignment-and-decision` and a changed implementation
  seam or dependency to `implementation-planning`.
- This Skill is the outer owner of code changes. Use one conditional inner
  method at a time: `test-driven-implementation` for a known code slice, or
  `systematic-debugging` while the cause is unknown.
- Runtime state remains authoritative. The project recovery note is navigation,
  not permission, task state, or completion evidence.

## Workflow

1. Confirm the active plan, acceptance aliases, Runtime responsibility,
   permissions, cancellation state, blockers, budget, and latest handoff.
2. Read only the bounded continuity block at the top of
   `docs/agent/chat-summary.md` when it exists. After compaction or handoff,
   start there and then inspect only the source paths needed for the next
   action. Source wins whenever the note is stale, contradicted, or about to
   govern an edit or verification claim.
3. Locate the one active WorkDocument bound to the existing `session_plan`,
   `session_goal`, or `room_work_item`. On its first approved write, register
   that authority explicitly; later slices and commits update the returned
   canonical active path. Never create a document per commit or code slice.
4. Keep `<!-- user-source:start -->` at the top of that document. Preserve
   `Original User Request` and `Original User Vision` byte-for-byte; append
   later user corrections verbatim. AI interpretation, plans, progress, and
   explanations live below the block and may change. Recheck their SHA-256 and
   restore drift from the Runtime source or Room RequirementAnchor before code.
5. Choose the smallest dependency-ready vertical code slice that can produce
   fresh evidence for one unmet acceptance alias.
6. For a known behavior gap, load `test-driven-implementation` and follow its
   red/green loop. For an unexplained failure, use `systematic-debugging`;
   return here after locating the cause, then use TDD for the repair when a
   valid test seam exists. Do not load both inner Skills at once.
7. Change the owning implementation seam, inspect the actual effect, and map
   fresh evidence to the exact acceptance alias. A successful Tool call,
   generated file, or checkbox is not behavioral proof.
8. Update the same WorkDocument and the small continuity pointer only when the
   active slice, blocker, next
   action, verified project fact, failed approach, or evidence state changes.
   The active execution owner writes it; helpers return a small proposed delta.
9. Continue while code acceptance remains unmet and a materially different
   legal action can advance it. Preserve failed branches so they are not
   repeated after compaction.
10. When planned code and slice checks pass, return `ready_for_quality`.
    Code-changing work then runs `quality-gate` and `independent-review`; only
    a clear review may reach settlement.

The existing WorkDocument lifecycle moves the complete file to archive only
after its authority emits a canonical terminal receipt. Archived documents are
excluded from normal recovery context and have no automatic deletion timer;
only a separate, explicit approval-bound erase may remove one.

Read [the simple continuity contract](references/execution-continuity-contract.md)
before the first update and after compaction or handoff.

## No-Progress And Cancellation

Stop automatic work when two consecutive attempts leave the same unmet
acceptance, blocker, evidence, and proposed next action, or when the Runtime
budget is exhausted. Handoff, wait, or block with an objective resume
condition. On observed cancellation, stop immediately and attempt no late
write.

## Output Contract

Return:

```text
upstream alignment and plan refs | Runtime responsibility
WorkDocument path/revision | current slice and changed files
evidence by acceptance alias
red/green or debugging result | continuity block update
failed branches | blocker | smallest next action
status | unverified boundaries
```

Use one status: `continue`, `needs_alignment`, `needs_replan`,
`ready_for_quality`, `handoff`, `wait`, `blocked`, or
`observed_cancellation`. Public updates mention only material behavior,
verification, risk, and the next user-relevant action.

## Self-Check

- Am I implementing the accepted plan rather than reopening it?
- Are the original request and vision still verbatim at the document top?
- Am I updating one authority-bound document rather than creating commit logs?
- Is only one inner implementation method active?
- Did the last action change code, observation, decision, or evidence?
- Did I verify the owning source before relying on a recovery note?
- Can each code claim point to fresh evidence for an acceptance alias?
- Is the continuity block still small enough to read before project files?

## Boundaries

Do not activate for intake, planning, review, or ordinary chat; create a second
task store; invent a work ID; manually move an archive; turn either document
into a per-commit diary; record secrets, personal facts, raw logs, or guesses;
continue after cancellation; or claim final delivery. If project guidance or
permissions forbid a documentation write, return the proposed document delta
to the caller instead of inventing another storage path.
