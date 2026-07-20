---
name: room-solution-convergence
description: Compare viable approaches against evidence and explicit constraints, then record one reviewable decision without silently widening scope.
when:
  - 多个可行方案需要按约束收敛
  - 方案比较与收敛
does: 比较取舍并输出可审查的方案决策与否决项。
output: 选定方案、证据化比较、否决项、取舍和失效条件。
notFor:
  - 已有明确方案只需实施
---

# Room Solution Convergence

## Enter When

Use this Skill when at least two credible approaches remain and choosing among
them affects architecture, compatibility, risk, cost, or acceptance.

## Inputs

- immutable original requirements and the current derived requirement view;
- candidate approaches with evidence and unresolved assumptions;
- architecture boundaries, risk limits, migration constraints, and acceptance
  conditions.

## Workflow

1. State the decision question and non-negotiable constraints.
2. Keep only viable candidates; explain every rejection with evidence.
3. Compare behavior, failure containment, reversibility, migration cost,
   observability, and testability.
4. Select one recommendation or report that evidence is insufficient.
5. Record consequences, rejected alternatives, and what could invalidate the
   decision.

## Output Contract

Return a decision record with the selected approach, comparison, evidence,
known tradeoffs, rejected alternatives, and unresolved risks. Do not hide a
product decision inside implementation detail.

## Exit Conditions

Exit with one reviewable decision or a named blocker. Policy candidates are
advice only; only the Kernel owns Task and Dispatch creation.

## Real Confusions

- Do not reopen settled architecture merely because another implementation is
  aesthetically attractive.
- A list of ideas is not convergence. A decision must explain why it satisfies
  the constraints better than the rejected alternatives.

## Hard Boundaries

This Skill cannot grant capabilities, approve destructive work, invoke another
Skill, send an `@`, or create a Dispatch.
