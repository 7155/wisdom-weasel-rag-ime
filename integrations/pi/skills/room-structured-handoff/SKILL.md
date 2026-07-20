---
name: room-structured-handoff
description: Package bounded work, evidence, state, decisions, risks, and exact next action for another owner without leaking private Session monologue.
when:
  - 未完成工作需要明确交给下一所有者
  - 跨 Agent 工作交接
does: 输出可接管、可去重、可取消的结构化交接包。
input: Root 与 Dispatch 引用、已完成证据、剩余工作、风险和下一动作。
output: 带所有权、证据、剩余工作、风险和下一动作的交接包。
notFor:
  - 无人接手的最终收口
---

# Room Structured Handoff

## Enter When

Use this Skill when another owner must continue the same governed work. Do not
use it merely to narrate progress to the Room.

## Inputs

- Root, Task, Dispatch, generation, and current owner references;
- completed work and verification receipts;
- remaining work, blockers, risks, relevant files, and exact next action;
- public Room facts only, with private Session reasoning excluded.

## Workflow

1. State what is complete and prove it with evidence.
2. State what remains, why, and the smallest next action.
3. Preserve IDs, generation, idempotency, capability, and cancellation context.
4. Include decisions and rejected paths only when needed to avoid repeated work.
5. Mark the sender as waiting, delegated, or blocked only through the Kernel's
   governed state transition.

## Output Contract

Return a structured handoff packet containing ownership references, completed
evidence, remaining work, next action, risks, blockers, and relevant artifacts.
The packet itself is not a Dispatch.

## Exit Conditions

Exit when a receiver can act without reconstructing private history, or report
that no eligible receiver exists. The Kernel alone decides delivery and wakeup.

## Real Confusions

- Dumping an entire transcript is not a handoff and pollutes Room context.
- Final closure with no remaining owner is not a handoff.

## Hard Boundaries

This Skill does not select or wake an Agent, send an `@`, create a Dispatch,
grant capability, or invoke another Skill.
