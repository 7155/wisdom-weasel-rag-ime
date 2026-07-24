---
name: managed-task-execution
description: Keep an explicit Goal, Task, or Room Dispatch moving until it is verified, legitimately handed off, waiting, blocked, cancelled, or accepted. Use only when the runtime supplies managed work state; never use it to turn ordinary chat into a task loop.
when:
  - 当前 Session 有显式 Goal、Task 或 Room Dispatch，需要持续执行和验收
does: 围绕当前责任执行、验证、记录证据，并选择一个合法生命周期出口。
input: 原始需求、当前任务、验收条件、阻塞、交接、权限和预算状态。
output: 实际产物、验证证据、剩余工作和完成、交接、等待或阻塞建议。
notFor:
  - 普通闲聊、开放讨论或没有受管任务状态的对话
  - 通过反复自我提醒制造无限循环
---

# Managed Task Execution

## Workflow

1. Verify that the runtime supplied an authoritative Goal, Task, or Room
   Dispatch. For Room work, the state must include the confirmed original-goal
   reference, current responsibility, and acceptance conditions. If those are
   absent or contradict a later user correction, do not reconstruct them from
   chat history; report the managed task as blocked for requirement repair.
2. Read blockers, handoff, permission mode, cancellation generation, and
   remaining budget. Treat peer Room Sessions as independent owners of their
   assigned Tasks, not as subordinate reasoning branches.
3. Choose the smallest concrete next action that advances one unmet acceptance
   condition.
4. Execute through already authorized tools. Capture real outputs and verify
   effects before updating progress.
5. Continue in the same native Agent loop while acceptance remains unmet and a
   distinct, authorized action can produce new evidence for an unmet criterion.
   A tool result is input to the next decision, not a reason to stop. A failed
   action should produce a bounded diagnosis or materially different fallback,
   never the same call or prompt again.
6. Treat the end of one model response as a settle candidate, not task
   completion. If the Kernel returns a governed follow-up, resume from the
   authoritative task state and the exact missing acceptance item. Do not spend
   that follow-up restating progress or consuming the continuation budget.
7. Before proposing completion or formal handoff, load `quality-gate` and close
   every failed or unverified required item.
8. Propose exactly one legal exit:
   - completed with evidence;
   - handed off with completed work, remaining work, reason, and next owner;
   - waiting with the awaited signal and resume condition;
   - blocked with evidence and the missing decision or capability;
   - cancelled with no further tool activity.

## Bounded Continuation

Stop trying and propose a lifecycle exit as soon as there is no distinct legal
action that can advance acceptance:

- use `handoff` when another participant or model capability is a better fit;
  include completed work, failure evidence, unmet criteria, the recommended
  capability or model, and the exact takeover point;
- use `wait` when a user decision, permission, credential, or external signal
  is required; ask only the smallest question that can resume work and record
  the awaited signal and resume condition;
- use `blocked` when acceptance is unreachable, a required capability is
  unavailable, or bounded diagnosis and fallbacks are exhausted.

Never burn follow-ups, retries, budget, or context to appear persistent. The
model proposes the exit; the Kernel owns terminal truth and enforces attempts,
deadline, cancellation, fences, and budget.

## Exit Contract

Return the current outcome, evidence, unmet acceptance items, and one lifecycle
recommendation. In a managed Room, use its canonical state, post, and commit
tools exactly as the loaded schema requires. Do not call `room_commit` merely
because one Provider response is ending; call it only for a valid lifecycle
exit.

## Boundaries

Do not activate this Skill for Room intake, ordinary chat, planning before user
confirmation, or any conversation without authoritative managed state. Do not
invent acceptance, treat Tool loading as authorization, keep working after
cancellation or a staged commit, create empty evidence, or mark the
authoritative Goal, Task, Dispatch, or Root complete yourself.
