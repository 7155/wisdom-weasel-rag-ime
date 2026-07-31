---
name: independent-review
description: Review a delivery from the original requirement and real evidence in a separate context, with separation of duty for shared or high-risk work.
when:
  - 共享契约、安全、迁移或发布需要独立复核
does: 从原始需求重建预期并检查真实路径。
input: 原始需求、验收、交付物、差异、证据和范围。
output: 结论、分级发现、证据、必修项和风险。
notFor:
  - 作者自检、开放讨论或纯风格偏好
---

# Independent Review

## Separation Rule

Rebuild the expected behavior without relying on the author's narrative.
High-risk shared contracts, security, migration, cancellation, and release
claims require a reviewer who did not author the relevant change. Review
evidence is not authority to edit or approve the work.

## Workflow

1. Reconstruct intended behavior from the verbatim user text supplied by the Runtime,
   later append-only corrections, and confirmed acceptance—not the implementer's
   summary.
2. Inspect the complete relevant diff and trace the real state owner, call
   path, side effects, and downstream consumer.
3. Re-run or independently inspect the evidence. Probe negative paths
   proportional to risk, including cancellation, idempotency, permissions,
   recovery, compatibility, rollback, and observable completion.
4. Report findings first, ordered by severity. Each finding needs a precise
   location or boundary, impact, evidence, and a verifiable fix condition.
5. Separate required fixes, residual risks, test gaps, and optional
   improvements. Do not promote style preferences into defects.

## Finding Contract

Each actionable finding contains:

```text
Severity:
Location or owning boundary:
Observed behavior:
Expected behavior:
Impact:
Evidence:
Fix condition:
Affected acceptance:
```

Use severity for impact, not confidence. If evidence is incomplete, say what
experiment would decide it. A missing test is a finding only when it leaves a
material behavior or regression path unprotected.

## Output Contract

Return `review_clear`, `review_clear_with_risk`, or `changes_required`, followed
by ordered findings, evidence, affected acceptance, required fixes, residual
risk, and unanswered questions. These are reviewer findings, not the Kernel's
delivery verdict.

`review_clear` and `review_clear_with_risk` return a `candidate_done`
recommendation to the Room Kernel; no further workflow Skill owns that
transition. `changes_required` returns the findings to
`implementation-execution`. Use `structured-handoff` only when responsibility
must move to a different owner, never as an automatic review stage.

When a Room review Task is complete, translate verified current-Task AC aliases
into `room_commit.evidence`. For `decision=deliver`, do not send
`acceptanceAliases`; that field belongs only to a new Task created by
`decision=handoff`.

## Self-Check

- Did I inspect the entire relevant change and its downstream consumer?
- Did I reproduce or independently inspect critical evidence?
- Are findings ordered by user or system impact?
- Did I keep optional architecture ideas separate from defects?
- Does required re-review remain assigned to an independent owner?

## Boundaries

Do not repeat the author's test summary as review, mutate the reviewed work,
self-approve a required fix, grant authority, create follow-up work, or route
another Agent.
