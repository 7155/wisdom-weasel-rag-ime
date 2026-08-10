---
name: independent-review
description: Review a fixed delivery diff on separate requirement-fidelity and code-standards axes, using an independent owner for shared or high-risk work.
when:
  - A code change has passed its quality gate
  - 共享契约、安全、迁移或发布需要独立复核
does: 从原始需求和项目标准分别复核差异与真实路径。
input: 原始需求、验收、交付物、差异、证据和范围。
output: 单一复核轴的结论、P0、建议项、证据和风险。
notFor:
  - 没有固定差异的作者自述、开放讨论或纯风格偏好
---

# Independent Review

## Separation Rule

Review is a risk decision owned by the Facilitator after the authoritative
integration workspace contains the accepted Worker results; it is not a
mandatory stage for every task. When review is warranted, rebuild expected
behavior without the author's narrative. The Reviewer must be a distinct
participant who did not author or integrate the relevant change, and must not
review its own implementation. Review evidence grants no edit or delivery
authority.

## Workflow

1. Reconstruct intent from the verbatim user text supplied by the Runtime,
   append-only corrections, acceptance, and non-goals.
2. Pin one review fixed point from the Runtime-supplied base, commit, branch,
   tag, or merge-base. Resolve it once; capture the complete relevant diff and
   commit list. Missing or empty scope stops review without a verdict.
3. Trace the actual owner, call path, state changes, downstream consumer, and
   side effects.
4. Each managed Review Task owns exactly one Runtime-supplied `reviewAxis`.
   For `requirements`, run a **Requirement Fidelity** pass for omissions,
   partial or wrong behavior, scope creep, and unrequested work. Do not inspect
   unrelated code quality or invent acceptance beyond the verbatim request.
5. For `technical`, run a **Code Standards** pass using nearest repository guidance,
   architecture decisions, and tooling boundaries. Inspect concrete-impact
   smells such as duplication, data clumps, shotgun surgery, speculative generality,
   message chains, middle men, and refused bequest. Skip mechanically enforced rules
   and do not re-judge product scope already owned by the requirements axis.
6. Independently reproduce critical evidence and probe risk-shaped negative
   paths: cancellation, duplicate operation, permission, recovery,
   compatibility, rollback, and observable completion.
   `workspace_shell` may run bounded foreground tests or builds: the Runtime
   keeps reviewed source and Git metadata read-only, disables network access,
   and discards its command-owned temporary caches. Background jobs remain
   unavailable. Treat a command that requires writing generated output into
   the reviewed tree as unsupported; do not work around the sandbox.
7. Report only the current axis. The Kernel preserves the two Review Tasks and
   their receipts independently. Do not merge or rerank findings across axes,
   or collapse them into one prose verdict.
8. Separate required fixes, residual risk, test gaps, and optional improvement.

## P0-Only Return Rule

- Only a reproducible `critical` defect may be `blocking`: security or
  authorization bypass, privacy/data loss, destructive behavior, unavailable
  core runtime, material acceptance failure, or a regression that makes the
  requested product path unusable.
- P1/P2/P3 correctness, test, performance, UX, maintainability,
  documentation, and optional improvements remain `advisory`. Keep them in
  the Review result, residual risks, and project documentation; they do not
  return work to implementation and may stay open under
  `accepted_with_notes`.
- A repair rechecks only the affected axis and changed scope. A later review
  cannot introduce a new blocker unless it is a newly evidenced P0 in the
  narrow safety/data/core-runtime exception set.
- Do not repeat a passed axis for an unchanged `reviewTargetRevision`. Review
  retry and repair budgets are bounded; exhausting them reports the residual
  P0 truthfully instead of looping.

## Managed Room Boundary

- Review is a post-integration Kernel ownership handoff to a distinct
  participant, not a `room_collaborate` child. Use the existing Root/Task,
  WorkItem, aliases, receipts, and the review participant's bound workspace
  harness; a filesystem root is not participant identity.
- The Facilitator chooses whether review is warranted and names an eligible
  existing participant or requests an explicit capability change. This Skill
  must not require review for every task, select by round-robin, or wake a
  reviewer through free-text mention.
- The `room_collaborate for review` route is forbidden; a review before
  integration is invalid.
- Submit findings and eligible evidence through `room_commit`; the Kernel
  decides settlement. Missing, stale, failed, or ineligible evidence means
  `changes_required`, wait, or blocked, never a prose-based pass.
- Use `room_state` to inspect the current aliases and integration receipts;
  submit only eligible evidence receipts through the review participant's
  bound workspace harness.
- For `decision=deliver`, do not send `acceptanceAliases`; those are only for
  `decision=handoff`. Keep private Session reasoning and refs private. Only the
  facilitator/reporter emits the Root's final public summary.

## Finding Contract

```text
Axis | Severity | Location or owner | Observed behavior
Expected behavior | Impact | Evidence | Fix condition
Affected acceptance
```

Severity measures impact, not confidence. State the deciding experiment when
evidence is incomplete. A missing test is a finding only when a material path
remains unprotected.

## Output Contract

Return `review_clear`, `review_clear_with_risk`, or `changes_required` for the
current `reviewAxis`, then findings, evidence, affected acceptance, required
P0 fixes, residual risks, questions, and counts. `changes_required` is valid
only when at least one open P0 remains. These are findings, not the Kernel
verdict.

A clear result recommends `candidate_done`; no later workflow Skill owns that
transition. `changes_required` returns to `implementation-execution`. Use
`structured-handoff` only when responsibility must move to another owner.

## Self-Check

- Did I pin one valid fixed point and inspect its complete downstream effect?
- Did I inspect only the Runtime-supplied review axis?
- Is every blocking item a reproducible P0 rather than a preference or P1+?
- Did I independently reproduce critical evidence?
- Are defects evidence-backed and optional ideas kept optional?
- Will an independent owner re-review required fixes?

## Boundaries

Do not repeat the author's summary as review, mutate reviewed work,
self-approve a fix, grant authority, create follow-up work, expose private
state, route another Agent, or turn taste into a defect.
