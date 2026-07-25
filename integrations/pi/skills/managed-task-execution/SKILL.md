---
name: managed-task-execution
description: Keep an explicit Goal, Task, or Room Dispatch moving until acceptance is evidenced or a legitimate handoff, wait, block, or observed cancellation requires exit.
when:
  - 当前 Session 已收到权威 Goal、Task 或 Room Dispatch，需要持续执行和验收
does: 围绕当前责任选择可产生新证据的下一步，执行、验证，并提出一个合法生命周期出口。
input: 原始需求、当前责任、验收别名、权限、预算、阻塞、交接和取消状态。
output: 实际产物、验证证据、剩余验收和完成、交接、等待或阻塞建议；取消只报告 Runtime 已观察到的状态。
notFor:
  - 普通聊天、需求对齐、开放讨论、未确认计划或没有受管任务状态的对话
  - 通过重复提示、重复失败动作或空转制造无限循环
---

# Managed Task Execution

## Core Principle

Persistence means repeatedly choosing a legal action that can change the
evidence state. It does not mean repeating a prompt, retrying the same failed
call, or keeping a model alive after no-progress and cancellation gates.

## Work Loop

1. Confirm that the runtime supplied authoritative managed work. Read the
   original request, current responsibility, acceptance aliases, permissions,
   cancellation state, remaining budget, blockers, and latest handoff. If they
   conflict with a later user correction, stop for requirement repair instead
   of guessing.
2. Choose the smallest authorized action that can create new evidence for one
   unmet acceptance check. A tool result is input to the next decision, not a
   reason to stop.
3. Execute, inspect the actual effect, and record the evidence. Do not count a
   successful tool transport as successful product behavior.
4. Continue while acceptance remains unmet and a materially different legal
   action can advance it. After a failure, diagnose or try a distinct fallback;
   never repeat the same call or prompt to appear persistent.
5. Treat the end of a model response as a settle candidate, not completion. If
   the Kernel returns a bounded continuation, resume from the named missing
   acceptance item without restating the entire task.
6. Before a delivery claim, follow the already loaded `quality-gate` body. If
   it is absent and the current stage requires it, load that exact Skill once;
   do not reload an active Skill. The Kernel decides whether the resulting
   evidence permits settlement.
7. Propose exactly one next lifecycle action:
   - deliver when all required acceptance has eligible evidence;
   - handoff when another participant or model capability is a better fit;
   - wait when one user decision, permission, credential, or external signal
     is required;
   - blocked when acceptance is unreachable or bounded alternatives are
     exhausted;
   - when cancellation is visible, stop immediately and report the last
     accepted state. Cancellation is a Runtime observation, not a
     `room_commit` decision.

## Progress Ledger

Before another automatic continuation, compare:

```text
unmet acceptance | blocker | evidence set | last action | proposed next action
```

Continue only when the next action is legal and can materially change at least
one field. Preserve failed approaches that rule out a branch; do not repeat
them after compaction or handoff.

## No-Progress Exit

Stop automatic work when two consecutive attempts leave the same unmet
acceptance, blocker, evidence set, and proposed next action, or when the Kernel
reports that the continuation/repair budget is exhausted. Handoff, wait, or
block with the observed evidence and exact resume condition. Do not spend
context or budget proving determination.

## Lifecycle Packet

- **deliver**: completed behavior, changed artifacts, evidence by acceptance
  alias, and residual risk;
- **handoff**: receiver capability, exact takeover point, evidence, remaining
  acceptance, and expected output;
- **wait**: who or what is awaited, one necessary question if applicable, and
  an objective resume condition;
- **blocked**: blocker, attempted materially different alternatives, and an
  unlock condition;
- **observed cancellation**: last accepted state and confirmation that no
  further action or late write was attempted; do not call `room_commit` after
  cancellation.

## Output Contract

Return the current outcome, changed artifacts, evidence, unmet acceptance,
failed approaches worth preserving, residual risks, and one lifecycle
recommendation. In Room work, use the already loaded Room state, public post,
collaboration, and commit Tools according to their exact schemas.

## Self-Check

- Did the last action change an artifact, observation, decision, or evidence?
- Am I continuing because acceptance is open, not because the response ended?
- Is the next step inside current permission, budget, and cancellation state?
- If I cannot finish, did I identify a specific receiver, question, or unlock
  condition instead of asking the Kernel to loop again?

## Boundaries

Do not activate this Skill for intake or ordinary chat, invent requirements,
interpret Tool disclosure as authorization, continue after cancellation,
change a staged handoff, claim terminal state, or create a new owner through
free-text `@`.
