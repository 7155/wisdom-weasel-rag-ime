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

Rebuild the expected behavior without relying on the author's narrative.
High-risk shared contracts, security, migration, cancellation, and release
claims require a reviewer who did not author the relevant change. Review
evidence is not authority to edit or approve the work.

## Fixed Point And Axes

Pin one review fixed point from the accepted implementation base, commit,
branch, tag, or merge-base supplied by the Runtime. Resolve it once and capture
the complete diff and commit list. If the point is missing, invalid, or produces
no relevant diff, stop without a review verdict and name the required baseline.

Run two passes and keep their findings separate:

- **Requirement Fidelity**: compare the diff with verbatim `User Source`,
  corrections, confirmed acceptance, and non-goals. Find missing, partial,
  incorrect, or unrequested behavior.
- **Code Standards**: read the nearest repository guides, contribution rules,
  architecture decisions, and tooling boundaries. The repository overrides
  generic advice. Also inspect these judgment-only smells: mysterious names,
  duplication, feature envy, data clumps, primitive obsession, repeated
  switches, shotgun surgery, divergent change, speculative generality, message
  chains, middle men, and refused bequest. Skip rules already enforced by tools.

Do not merge or rerank findings across axes. A change can pass either axis and
fail the other.

## Workflow

1. Reconstruct intended behavior from the verbatim user text supplied by the Runtime,
   later append-only corrections, and confirmed acceptance—not the implementer's
   summary.
2. Inspect the complete relevant diff and trace the real state owner, call
   path, side effects, and downstream consumer.
3. Complete the Requirement Fidelity pass, including omissions, wrong behavior,
   and scope creep.
4. Complete the Code Standards pass. Treat documented violations as defects;
   report a smell only with concrete impact and never as a mechanical rule.
5. Re-run or independently inspect the evidence. Probe negative paths
   proportional to risk, including cancellation, idempotency, permissions,
   recovery, compatibility, rollback, and observable completion.
6. Report findings first under the two axis headings, ordered by severity
   within each axis. Each finding needs a precise location or boundary, impact,
   evidence, and a verifiable fix condition.
7. Separate required fixes, residual risks, test gaps, and optional
   improvements. Do not promote style preferences into defects.

## Finding Contract

Each actionable finding contains:

```text
Axis:
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
by separate Requirement Fidelity and Code Standards findings, evidence,
affected acceptance, required fixes, residual risk, unanswered questions, and
counts per axis. These are reviewer findings, not the Kernel's delivery verdict.

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
- Did I pin one valid fixed point and review the complete resulting diff?
- Did I keep Requirement Fidelity and Code Standards separate?
- Did I reproduce or independently inspect critical evidence?
- Are findings ordered by impact only within their own axis?
- Did I keep optional architecture ideas separate from defects?
- Does required re-review remain assigned to an independent owner?

## Boundaries

Do not repeat the author's test summary as review, mutate the reviewed work,
self-approve a required fix, grant authority, create follow-up work, or route
another Agent.
