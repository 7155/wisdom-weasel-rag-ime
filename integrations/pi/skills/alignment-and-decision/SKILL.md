---
name: alignment-and-decision
description: Settle material user-owned choices after inspection.
when:
  - Inspection leaves a material user-owned choice
  - The user asks to be grilled or challenged
does: Investigate facts and settle one smallest choice group.
input: Request, evidence, constraints, and authority.
output: Settled choice or one native Ask group.
notFor:
  - Inspectable facts or reversible defaults
  - Work with no material user choice
---

# Align and Decide

Settle success, then the route. A solution never rewrites or
weakens the requirements.

## Source Contract

- Start an immutable `User Source` block with the original request and vision verbatim in
  the user's language and order; never invent, translate, or overwrite it.
- Append corrections verbatim. Keep every AI explanation in a
  separate section; source bytes, hashes, and RequirementAnchor outrank summaries.
- Inspect source, tests, config, docs, and runtime before asking. Separate facts,
  reversible defaults, and user-owned choices.
- Lock the requirements before comparing solutions. Reopen only for a user
  correction or evidence that they cannot be met.

## Workflow

1. Capture `User Source`; derive goal, scope, observable acceptance, constraints,
   permissions, non-goals, defaults, and open questions.
2. Investigate missing facts from source, tests, config, docs, and runtime. Never
   turn an inspectable path, owner, failure boundary, or verification result into
   a user choice.
3. Classify what remains: choose reversible defaults within authority; mark an
   unreachable external fact as blocked; reserve Ask for a user-owned choice.
4. A material user choice changes goal, scope, acceptance, authority, data,
   compatibility, observable behavior, reversibility, or cost.
5. Use the user's language; append only corrections or extensions, and
   challenge the decision, not the user.
6. Confirm material choices; a complete request needs no fixed phrase.
7. For genuine routes, record evidence, rejections, risks, and invalidation.
8. Write a glossary, ADR, or decision record only on explicit request and
   approved write; glossary terms need a confirmed meaning. Every persisted
   decision needs a direct user choice and approved write. Proceed only when
   every acceptance condition can be met.

## Native Ask

- After inspection, use native `ask` for each remaining material user choice,
  not free-text confirmation, another question Tool, or a status update.
- Group 1-4 independent questions; separate dependent ones. Each has 2-5 unique
  options, no hand-written `Other`; `multi` is only for independent choices.
- Recommend one zero-based `recommended` index only with evidence. Explain
  tradeoffs; recommendation, custom text, and cancellation are not approval.
- Never invent an answer or continue past an unanswered material choice.

## Managed Room Intake

- The facilitator/reporter owns one alignment Root/Task/Dispatch. Inspect
  `room_state`; never fan out work before requirements are settled.
- Infer inspectable facts and reversible defaults; never ask a serial checklist.
- Ask at most one clarification round. For 2-4 independent material questions,
  put numbered A/B/C choices in `question="<numbered prompts with A/B/C choices>"`;
  use `room_commit`, `decision="wait"`, `waitingFor="user"`,
  `questionKind="unbounded"`, omit `questionOptions`, and accept a compact answer
  such as `1A 2C`. Never continue past an unanswered choice.
- For exactly one genuinely mutually exclusive decision, use `questionKind="bounded"`
  and `questionOptions=[...]` with 2-5 distinct options and at most one `recommended`.
  Each needs a stable `value`, short `label`, and one-paragraph `description` of
  scope, effort, or tradeoff instead of repeating the label. The interface supplies `Other`;
  never write it as an option. This is not a second question Tool.
- Keep `publicSummary` and `question` a natural continuation of the user's message;
  acknowledge the goal and explain why the choice matters. Never announce a work-card read,
  declare the request insufficient, or recite goal/deliverable/acceptance categories.
- The next ordinary Room message answers the wait: append its source span to the
  RequirementAnchor, create one resume Dispatch, and never reuse the alignment Dispatch.
- Once settled, use `room_state`, then `room_define` with the durable requirements
  packet and a visible vertical plan of 1-4 peer Agent tasks; show the proposed execution plan before `开始行动`.
  With no material choice call it without a
  confirmation message; Start approval still authorizes work; never substitute `room_commit deliver`.
- The Facilitator owns decomposition. `room_collaborate` creates only bounded,
  non-overlapping implementation work, never intake or review.

## Explicit Grill Mode

In explicit Grill Mode, explore every material decision-tree branch in dependency
order, including nonblocking tradeoffs. Ask one question at a time, recommend, wait and
investigate facts yourself. Stop only after the user confirms shared understanding.

## Output Contract

Keep an `AlignmentDecisionPacket` for the caller:

```text
User Source (immutable and byte-preserved):
  Original User Request | Original User Vision | Later User Corrections
  UTF-8 SHA-256 and source refs
AI Interpretation:
  Requirements | acceptance | constraints | non-goals | defaults
  Domain Language Delta: confirmed terms | conflicts | unresolved meanings
Decision: selected approach | evidence | rejected alternatives | risks | invalidation
Open questions | confirmation evidence | documentation receipt
Status | Next stage
```

Status is `needs_user_answer`, `blocked_by_external_fact`, or
`ready_for_planning`.
Do not dump the packet into the public reply; give context, a recommendation
and one smallest question group, or proceed.

## Self-Check

- Are source bytes preserved, acceptance observable, facts investigated, and the
  route within requirements and authority?

## Boundaries

Do not ask inspectable facts, invent choices, weaken scope or acceptance, persist
guesses, expose private Room state, plan or execute work, route Agents, or claim
completion. Redact credentials without changing other user text; documentation
approval grants no execution.
