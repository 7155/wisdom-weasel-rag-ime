---
name: solution-convergence
description: Compare viable approaches against evidence and explicit constraints, then record one reviewable decision without silently widening scope.
when:
  - 多个可行方案会改变风险、兼容性或验收
does: 按同一组约束比较候选并记录决定。
input: 已确认需求、候选、证据、约束和验收。
output: 决定、取舍、否决理由、失效条件和未决项。
notFor:
  - 已有明确方案，或事实可直接查明
---

# Solution Convergence

## Decision Matrix

Compare only viable candidates using the same columns:

```text
user-visible behavior | state owner | failure containment | reversibility
migration/compatibility | observability | testability | cost
```

Mark whether each value is observed, documented, or still assumed. One
discriminating experiment is more useful than a long list of symmetric pros
and cons.

## Workflow

1. State one decision question and the non-negotiable constraints from the
   confirmed requirement.
2. Remove non-viable candidates with evidence. Do not keep decorative variants
   to make the comparison look broader.
3. Compare the survivors on user-visible behavior, ownership, failure
   containment, reversibility, migration cost, observability, and testability.
4. Inspect source or run a small discriminating experiment when one unknown can
   decide the choice.
5. Recommend one option. If the remaining difference is a user-owned product
   tradeoff, follow an already loaded `grill-me`, or load that exact Skill once
   when absent, for that single decision instead of guessing.
6. Record the chosen rule, consequences, rejected alternatives, and the
   evidence that would invalidate the choice later.

## Decision Record

Include the decision question, non-negotiable constraints, viable candidates,
comparison evidence, selected option, why it wins, rejected options and
reasons, tradeoffs accepted, open risks, and invalidation conditions.

Example: choosing append-only Context Epoch updates is not "simpler." It wins
only if it preserves identical prior Prompt bytes, gives new data a stable
tail, and defines compaction as the explicit cache-generation boundary.

## Output Contract

Return one decision record or one named blocker. Include the selected approach,
comparison, evidence, tradeoffs, rejected alternatives, unresolved risks, and
invalidation conditions.

## Self-Check

- Did every candidate satisfy the confirmed requirement before comparison?
- Did I compare behavior and ownership rather than names and aesthetics?
- Can one small experiment resolve the remaining uncertainty?
- Is the remaining choice technical evidence or a user-owned tradeoff?

## Boundaries

Do not reopen settled architecture for aesthetic preference, silently widen
scope, hide a product choice inside implementation detail, grant authority,
create managed work, route an Agent, or start implementation.
