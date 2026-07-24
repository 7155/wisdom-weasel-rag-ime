---
name: room-requirement-clarification
description: Align a collaboration Room goal with the user before managed work exists. Preserve the user's words, ask only material questions, and wait for explicit confirmation.
when:
  - Room 目标尚未完成范围、验收或禁区对齐
does: 保留原话，只补关键缺口，形成待确认需求包。
input: 当前对话、原始目标、已知事实与未决问题。
output: 目标、范围、验收、禁区、未决项与确认状态。
notFor:
  - 已有受管任务、闲聊或需求已确认
---

# Room Requirement Clarification

## Enter When

Use this Skill before managed work exists. Enter when a Room message expresses
a goal that may become work and one unresolved point can materially change
scope, acceptance, safety, permission, cost, ownership, or irreversible action.
Do not manufacture questions for minor details that source inspection or a
reversible default can settle.

## Inputs

- the user's verbatim goal and later corrections in the current Room
  conversation;
- known source, test, configuration, runtime, and workspace facts;
- already confirmed product decisions, constraints, non-goals, and permissions;
- prior questions and answers from this same Agent Session.

There must be no active Root, Task, or Dispatch for this intake. If managed work
state is present, stop and use its lifecycle instead of reopening intake.

## Workflow

1. Recover the user's original goal from the current conversation. Keep it as a
   source reference; later wording may clarify it but never replace it.
2. Separate four things: facts the system can inspect, user-owned choices,
   reversible implementation defaults, and missing information.
3. Inspect available evidence before asking. Never ask the user for a fact the
   workspace, configuration, runtime, or source can answer.
4. Ask only the smallest material question, one at a time. When the uncertainty
   is a genuine product or architecture tradeoff, use `grill-me`; routine intake
   stays in this Skill.
5. Accept concise answers and corrections without repeating resolved questions.
   Preserve both the old wording and the new decision.
6. When no material question remains, present one compact confirmation packet:
   - original goal;
   - in-scope result;
   - acceptance checks stated in user-visible language;
   - constraints and permissions;
   - explicit non-goals;
   - reversible defaults and remaining risks.
7. Ask the user to confirm or correct that packet. Do not start planning or
   execution before an explicit confirmation. "按这个做", "确认", or an equally
   clear approval counts; silence and topic change do not.

## Output Contract

Return a compact, human-readable result with exactly one status:

- `needs_user_answer`: one material question is open;
- `ready_for_confirmation`: the confirmation packet is complete but not yet
  approved;
- `confirmed`: the user explicitly approved the current packet;
- `blocked_by_external_fact`: required evidence cannot currently be obtained.

For `confirmed`, include the original-goal reference, confirmed scope,
acceptance checks, constraints, non-goals, decisions, and remaining risks. This
is the input to planning; it is not yet a runtime Task.

Keep two stable fields in every result so the next turn never has to infer
whether intake is complete:

- `Open questions`: only unresolved material choices or external facts;
- `Readiness status`: exactly one status from the list above.

## Exit Conditions

Exit when the user has answered the current question, explicitly confirmed the
packet, corrected it, or when an external fact blocks alignment. Return control
to the same Agent Session after every exit so the next user message continues
the same conversation.

## Real Confusions

- "What color should the inactive icon be?" is not a user question when the
  existing design system already defines it.
- "Does Stop cancel already-running child Agents?" is material because it
  changes safety and acceptance.
- "全部按建议" confirms the recommendations currently on the table; do not
  reopen each item.
- A later correction changes the confirmation packet but never erases the
  original goal or the fact that it was corrected.

## Hard Boundaries

This Skill provides conversation instructions, not authority. It grants no
Tool, Provider, database, cancellation, task, or delegation capability. It does
not create a WorkItem, Root, Task, Dispatch, send an `@`, or assign another
Agent. Room members remain peer Sessions; confirmation does not create a
master/sub-Agent hierarchy.
