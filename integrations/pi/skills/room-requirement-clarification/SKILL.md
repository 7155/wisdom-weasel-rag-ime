---
name: room-requirement-clarification
description: Clarify material ambiguity while preserving the user's original requirement as immutable evidence and recording only revisable derived requirements.
when:
  - 关键歧义会改变范围、约束或验收
  - 需求澄清
does: 保留原文并输出可追溯的澄清项与就绪状态。
output: 来源不变的澄清结果、假设、开放问题和就绪状态。
notFor:
  - 需求清楚且能安全继续
---

# Room Requirement Clarification

## Enter When

Use this Skill only when an unresolved ambiguity can materially change scope,
constraints, acceptance, safety, ownership, or irreversible work. Lack of minor
detail is not enough when a conservative implementation can proceed.

## Inputs

- immutable original requirement references;
- current derived requirement entries and revision history;
- known facts, open questions, constraints, and evidence references;
- the current Root, Task, and Dispatch references supplied by the Kernel.

## Workflow

1. Quote or reference the exact ambiguous source without rewriting it.
2. Separate facts, assumptions, choices, and missing evidence.
3. Ask the smallest question that changes the decision, or state a conservative
   default when the action is reversible.
4. Propose a revision to the derived requirement directory. Never mutate the
   original requirement.
5. Record the decision owner, evidence, affected requirement IDs, and remaining
   uncertainty.

## Output Contract

Return a compact clarification result containing source references, clarified
facts, explicit assumptions, open questions, proposed derived-requirement
revisions, and a readiness status. Do not create a Dispatch or claim that the
Root is complete.

## Exit Conditions

Exit when the material ambiguity is resolved, explicitly deferred with a safe
default, or reported as blocking. Policy candidates are advice only. The Kernel
decides whether any next Task or Dispatch exists.

## Real Confusions

- "What color should the inactive icon be?" is not a blocker when the design
  system already defines it.
- "Does Stop cancel already-running child Agents?" is material because it
  changes runtime safety and acceptance.
- A user's later clarification revises the requirement directory; it never
  erases the original request.

## Hard Boundaries

This Skill provides instructions, not authority. It grants no Tool, Provider,
database, cancellation, or delegation capability. It never auto-invokes a next
Skill, sends an `@`, or constructs a Dispatch.
