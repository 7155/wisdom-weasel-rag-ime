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

- Start an immutable `User Source` block with the original request and vision
  verbatim in the user's language and order; never invent, translate, or overwrite it.
- Append corrections verbatim. Keep every AI explanation in a
  separate derived section; original bytes, hashes, and RequirementAnchor outrank
  summaries, and planning consumes its ref.
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
6. Confirm material interpretations, permissions, acceptance, and user-owned
   choices. A complete request needs no fixed phrase.
7. Compare only genuinely different routes; record evidence, rejections, risks,
   and invalidation.
8. Write a glossary, ADR, or decision record only on explicit request and
   approved write; glossary terms need a confirmed meaning. Every persisted
   decision needs a direct user choice and approved write. Proceed only when
   every acceptance condition can be met.

## Native Ask

- After inspection, use native `ask` for each remaining material user choice,
  not free-text confirmation, another question Tool, or a status update.
- Group 1-4 independent questions; separate a dependent one. Each has 2-5
  unique options and no hand-written `Other`; `multi` is only for independent choices.
- Recommend one zero-based `recommended` index only when evidence supports it.
  Explain tradeoffs; never treat recommendation, custom text, or cancellation as approval.
- Never invent an answer or continue past an unanswered material choice.

## Managed Room Intake

- The facilitator/reporter owns one alignment Root/Task/Dispatch. Inspect
  `room_state`; never fan out work before requirements are settled.
- Ask about one user-owned decision at a time, in dependency order. Never bundle
  the target surface, required interactions, and acceptance boundary into one prompt.
- Use `room_commit` with `decision="wait"`,
  `waitingFor="user"`, `questionKind="bounded"`,
  `question="<one prompt>"`, and `questionOptions=[...]` containing 2-5
  unique, genuinely different options with at most one `recommended`. The
  interface supplies `Other` for custom text, so never write an Other option and
  never replace the options with an open text box. This is not a second
  question Tool.
- The next ordinary Room message answers the wait: append its source span to the
  RequirementAnchor and make one new resume Dispatch under the same Root; never
  reuse the alignment Dispatch.
- Once settled, re-read `room_state`, use `tool_search`, then one `tool_load` for
  `room_define`. It binds one RequirementCatalog and is terminal for that model
  turn. When no material clarification was needed, call it directly without a
  confirmation message; never substitute `room_commit deliver` for definition.
- The Facilitator owns decomposition. `room_collaborate` creates only bounded,
  non-overlapping implementation work, never intake or review.
- `room_post` is not a second clarification channel; it carries material progress.
  Only the facilitator/reporter emits the final public summary.
- Filesystem roots are not participant identity. Require receipts; do not claim
  automatic Git worktree cloning or isolation without proof.

## Explicit Grill Mode

In explicit Grill Mode, explore every material decision-tree branch in
dependency order, including nonblocking tradeoffs. Ask one question at a time,
recommend an answer, and wait. Investigate facts yourself. Do not stop merely
because planning could begin; stop only after the user confirms shared understanding.

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
and one smallest question group, or proceed with the settled decision.

## Self-Check

- Are request and vision byte-preserved above AI text?
- Is acceptance observable, and did I investigate before asking?
- Does the chosen route meet locked requirements and direct authorization?

## Boundaries

Do not ask for inspectable facts, invent alternatives, widen scope, weaken
acceptance, persist guesses, expose private Room state, plan tasks, modify
behavior, route an Agent, or claim completion. Redact credentials explicitly
without changing other user text. Documentation approval grants no execution.
