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
- Whenever the user adds, corrects, withdraws, or reprioritizes a requirement,
  append those exact words immediately and replace only the derived current
  interpretation. Never leave the newest requirement solely in chat prose.
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

- The receiving companion holds the current alignment and public-report
  responsibility; this is not command authority over peer companions. Inspect
  `room_state`; never fan out work before requirements are settled.
- Before the visible Start approval, use only the user's messages and
  already-projected Room, requirement, plan, and product metadata. Do not call
  project file, shell, test, install, write, or peer-dispatch Tools. Lifecycle
  projection, wait, and definition Tools may be used only to preserve the same
  Root/Task, record the user's answer, and present the proposed plan. An
  implementation fact that can be discovered safely after Start is not a user
  question; record it as the first discovery step and keep the pre-Start plan at
  the user-outcome level.
- Infer inspectable facts and reversible defaults; never ask a serial checklist.
- A broad multi-feature request is not automatically a complete request. Before
  skipping clarification, explicitly check whether data identity, destructive merge or undo behavior, import compatibility,
  retention, permissions, or another user-visible boundary is still owned by the
  user. If one or more of those choices materially change the delivered workflow,
  ask them together in the single clarification round; do not silently promote
  them all to defaults or replace the round with a formal summary.
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
  RequirementAnchor under the same Root and Task, create exactly one new resume
  Dispatch, and never reuse the alignment Dispatch.
- Once settled, use `room_state`. If `room_define` is not yet disclosed, use
  `tool_search` for that exact lifecycle Tool and then one `tool_load`; do not
  pre-load unrelated schemas. Call `room_define` with the durable RequirementCatalog
  packet and a visible vertical plan of 1-4 peer Agent tasks; show the proposed execution plan before `开始行动`.
  Write every user-visible plan field in the user's language and from the user's
  point of view. Describe shared behavior, not English type declarations,
  camelCase field inventories, protocol names, or unverified repository entry
  points. Never publish internal role words such as `Facilitator`, `Reporter`,
  or `Reviewer`; use the companion's display name or natural user-language
  phrases such as the local equivalents of coordinating or reviewing companion.
  Put implementation details in the post-start WorkDocument or an expandable
  technical detail instead.
  All active Room companions are peers. Coordination, vertical feature work,
  integration, review, and the one final report are bounded responsibilities,
  not permanent ranks. The receiving companion may own a complete feature; any
  eligible peer may own an integration scope. An owner may take another feature
  in a later wave, not two in the same wave.
  Do not keep a permanent idle Reviewer; after integration, choose review from
  actual authorship and integration provenance so nobody reviews their own target.
  Treat each proposed vertical result as a stable feature `RoomTask` identity with a
  user-visible outcome, owner, dependencies, write boundary, and acceptance.
  The Kernel, not call order or a companion's prose, owns the approved graph,
  derives runnable waves, and releases attempts only after Start.
  Include a continuity statement: the definition stage prepares the WorkItem's
  single governed WorkDocument, and Start freezes its approved plan revision
  before any implementation attempt can run. The document has separate sections for the
  verbatim user source and vision, confirmed requirements, execution plan,
  evidence, failed routes, and next action. Recovery and handoff read it before
  current source and runtime state.
  With no material choice, skip clarification but still show this plan and wait
  for the typed Start approval; never substitute `room_commit deliver`.
- The receiving companion may propose decomposition and ownership, but only the
  approved Kernel PlanRevision creates or changes `RoomTask` identity, assignment,
  dependency, and runnable state. Start materializes the graph and the Kernel
  releases approved runnable features directly; a companion must not recreate
  them with free-text `room_collaborate`. That Tool remains a governed legacy or
  nested-scope path and never performs intake or creates review work.
  `room_post` is not a second clarification channel.
  Filesystem roots and Git worktree paths are execution evidence and authority
  bindings, never participant identity or proof of completion.

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
