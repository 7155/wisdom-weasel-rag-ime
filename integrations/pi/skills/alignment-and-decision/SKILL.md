---
name: alignment-and-decision
description: Clarify requirements and implementation before planning.
when:
  - Scope, acceptance, or the approach is unclear
does: Investigate, ask one question, then decide.
input: Request, evidence, constraints, and authority.
output: Confirmed scope, optional decision, and next stage.
notFor:
  - Clear work
  - Planning, execution, debugging, or review
---

# Align and Decide

Settle success, then the route. A solution never rewrites or
weakens the requirements.

## Core Boundary

- Start an immutable `User Source` block: copy the opening request and explicit
  end-state vision verbatim, in the original language and order. Never
  translate, summarize, correct, or overwrite them. If vision was not stated,
  write `Not separately stated`; do not invent it.
- Append corrections verbatim in source order. Keep every AI explanation in a
  separate, revisable derived section.
- In a Room, retain the original RequirementAnchor bytes, ref, and hash; a
  derived catalog statement is not original user text.
- Planning consumes this packet by project reference. Do not invent a workflow
  or work ID between stages.
- Read source, tests, configuration, docs, and runtime state before asking.
  Separate inspectable facts, reversible defaults, and user-owned choices.
- Lock the requirements before comparing solutions. Reopen them only for a user
  correction or evidence that they cannot be met.
- This Skill creates no Goal, Task, Dispatch, approval, or execution authority.

## Workflow

1. Capture `User Source`, then derive goal, scope, observable acceptance,
   constraints, permissions, non-goals, defaults, and open questions.
   Acceptance describes behavior, not "implement the backend."
2. If a fact is missing, investigate it. If you still cannot explain the
   implementation path, state owner, failure boundary, or verification method
   without guessing, stop and ask. Say exactly what is unclear, offer at most
   three genuinely different options, recommend one, and ask one question.
3. Use the user's language and sound like a thoughtful teammate: "I'm still not
   clear whether X should own this state. I recommend A because ... Which should
   we use?" Avoid introductions, repeated requests, filler, and questionnaires.
   Keep contract field names unchanged. Accept "use your recommendation"
   without asking the same thing again.
4. Append the user's answer to `User Source` when it corrects or extends the
   request, then update only the derived interpretation. Ask another question
   only when a different material decision still blocks planning. Challenge
   the decision, not the user.
5. In a managed Room, settle a bounded user choice through `room_commit` with
   `decision="wait"`, `waitingFor="user"`, a specific `resumeCondition`,
   `question="<one prompt>"`, and `questionOptions=[...]` containing 2-5 unique
   options; mark at most one `recommended`. When no honest bounded set exists,
   an ordinary text wait remains valid: keep `question` and omit
   `questionOptions` rather than inventing choices. This is the existing Room
   wait path, not a second question Tool.
6. Get direct confirmation for a material new interpretation, permission,
   acceptance condition, or user-owned choice. A complete, safe original
   request is evidence; do not demand a fixed phrase.
7. Lock requirements. If one path clearly works or was specified, skip
   comparison.
8. Compare only approaches that materially change behavior, ownership, failure
   containment, reversibility, migration, compatibility, observability,
   testability, or cost. Drop failures; prefer one discriminating check over a
   long symmetric list.
9. Recommend one. Record evidence, rejected alternatives, tradeoffs, risks, and
   invalidation evidence. Facts come from evidence; the user owns product,
   permission, and irreversible choices.
10. Write a glossary, ADR, or decision record only on explicit request and
    approved write. Put `User Source` first and preserve it through revisions
    and archive. Read local guidance first. Glossary terms need a confirmed
    meaning; ADRs need a hard-to-reverse or surprising tradeoff.
11. Recommend planning only when no material question remains, required
    confirmation is recorded through the active channel, and the chosen
    solution satisfies every acceptance condition.

## Output Contract

Keep one structured `AlignmentDecisionPacket` for the caller:

```text
User Source (immutable; first when persisted):
  Original User Request: verbatim text | required UTF-8 SHA-256 | source ref
  Original User Vision: verbatim text | required UTF-8 SHA-256 or Not stated
  Later User Corrections: append-only verbatim entries
AI Interpretation (derived):
  Requirements: goal | scope | acceptance | constraints | non-goals | defaults
Decision: omit when no comparison was needed
  question | selected approach and evidence | rejected alternatives
  accepted tradeoffs | open risks | invalidation conditions
Open questions:
Confirmation evidence and channel:
Documentation receipt: omit unless an approved write succeeded
Status:
Next stage:
```

Status is `needs_user_answer`, `needs_confirmation`,
`blocked_by_external_fact`, or `ready_for_planning`. `Next stage` is
`waiting_user`, `blocked_external`, or `planning`, never a Runtime transition.

Do not dump the packet into the public reply. Give minimal context, a
recommendation and one question; if ready, summarize the agreement; if blocked,
name the blocker and needed evidence.

## Self-Check

- Are the original request and vision still byte-preserved above all AI text?
- Did I reread them instead of trusting only a prior AI interpretation?
- Is every acceptance condition verifiable?
- Did I investigate before asking one useful question with a recommendation?
- If implementation was still unclear, did I ask instead of guessing?
- Were requirements locked, and does the solution meet them?
- Is every persisted decision backed by a direct user choice and approved write?

## Boundaries

Do not ask for inspectable facts, invent alternatives, widen scope, weaken
acceptance, or persist guesses as user decisions. Redact credentials explicitly
without changing other user text. Documentation approval is not execution
approval. Do not plan tasks, modify behavior, route an Agent, or claim done.
