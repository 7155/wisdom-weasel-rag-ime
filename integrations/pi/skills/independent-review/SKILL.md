---
name: independent-review
description: Review a fixed delivery diff on separate requirement-fidelity and code-standards axes, using an independent owner for shared or high-risk work.
when:
  - A code change has passed its quality gate
  - 共享契约、安全、迁移或发布需要独立复核
does: 从原始需求和项目标准分别复核固定差异与真实路径。
input: 原始需求、验收、交付物、差异、证据和范围。
output: 两轴结论、分级发现、证据、必修项和风险。
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
4. Run a **Requirement Fidelity** pass for omissions, partial or wrong
   behavior, scope creep, and unrequested work.
5. Run a separate **Code Standards** pass using nearest repository guidance,
   architecture decisions, and tooling boundaries. Inspect concrete-impact
   smells such as duplication, data clumps, shotgun surgery, speculative generality,
   message chains, middle men, and refused bequest. Skip mechanically enforced rules.
6. Independently reproduce critical evidence and probe risk-shaped negative
   paths: cancellation, duplicate operation, permission, recovery,
   compatibility, rollback, and observable completion.
7. Report findings under their original axes and order only by severity within
   each axis. Do not merge or rerank findings across axes.
8. Separate required fixes, residual risk, test gaps, and optional improvement.
9. Record the review outcome in the bound WorkDocument through the current
   review authority, or return a bounded proposed delta when the document is
   owned elsewhere. Preserve the reviewed fixed point, findings, reproduced
   evidence, required repair, residual risk, and next action without rewriting
   the original user source.

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

Return `review_clear`, `review_clear_with_risk`, or `changes_required`, then
separate Requirement Fidelity and Code Standards findings, evidence, affected
acceptance, required fixes, residual risks, questions, and per-axis counts.
These are findings, not the Kernel verdict.

A clear result recommends `candidate_done`; no later workflow Skill owns that
transition. `changes_required` returns to `implementation-execution`. Use
`structured-handoff` only when responsibility must move to another owner.

## Self-Check

- Did I pin one valid fixed point and inspect its complete downstream effect?
- Are Requirement Fidelity and Code Standards still separate?
- Did I independently reproduce critical evidence?
- Are defects evidence-backed and optional ideas kept optional?
- Will an independent owner re-review required fixes?

## Boundaries

Do not repeat the author's summary as review, mutate reviewed work,
self-approve a fix, grant authority, create follow-up work, expose private
state, route another Agent, or turn taste into a defect.
