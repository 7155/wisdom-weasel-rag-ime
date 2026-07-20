---
name: room-independent-vision-review
description: Independently review whether a delivery solves the intended user problem and satisfies architecture, safety, and acceptance constraints.
when:
  - 交付需要独立角色按愿景和约束复核
  - 独立愿景复核
does: 独立输出偏航、缺口、失控风险和复核结论。
output: 独立 verdict、按严重度排序的 findings、证据和必修项。
notFor:
  - 实施者自己的收工检查
---

# Room Independent Vision Review

## Enter When

Use this Skill when a separate reviewer must assess the delivered behavior,
especially for shared contracts, safety boundaries, migrations, or user-facing
workflows.

## Inputs

- immutable original requirement and current derived requirement directory;
- approved decision, implementation evidence, tests, and runtime traces;
- explicit review scope and separation-of-duty identity.

## Workflow

1. Reconstruct intended behavior from requirements, not the implementer's
   narrative.
2. Inspect the real path and evidence independently.
3. Test high-risk assumptions, negative cases, rollback, cancellation, and
   observable completion semantics.
4. Classify findings by severity with exact evidence and ownership.
5. Distinguish required fixes from optional improvements.

## Output Contract

Return an independent verdict, ordered findings, evidence, affected
requirements, required fixes, residual risk, and unanswered questions.

## Exit Conditions

Exit with `approve`, `approve_with_risk`, or `changes_required`. Policy
candidates are advisory; the Kernel owns any follow-up Task or Dispatch.

## Real Confusions

- Repeating the implementer's test summary is not independent review.
- Style preferences must not be promoted to blocking findings without a linked
  requirement or material risk.

## Hard Boundaries

This Skill cannot mutate the reviewed work, grant authority, create a Dispatch,
invoke another Skill, or send an `@`.
