---
name: facilitate-room
description: "Coordinate a Room as a lightweight composition of ordinary Partner Sessions. Use when, and only when, the current Session is the designated Room Facilitator responsible for shared alignment, delegation, integration, optional review, and one final result. Do not use in a standalone Session, Room Partner, Reviewer, or private Tool Agent; e.g., a Partner fixing one bounded file uses a task Skill rather than Room facilitation."
---

# Facilitate a Room

Keep the Room lightweight. Partners remain ordinary Sessions and use the same task Skills as any other Session.

Every active Room participant is an equal peer. When one Partner needs another
Partner's information or response, use `room_partner peer_list`, `peer_send`,
`peer_ask`, or `peer_reply` to contact that target directly. The Facilitator is
only the final Root integrator; never copy, rewrite, or relay Partner wording to
simulate peer conversation.

## Workflow

1. Read the project, outcome, Room brief, current workboard, and Runtime participant projection.
2. Clarify material user choices only when necessary. Use planning only when the work truly needs multiple items or owners.
3. Before editing, identify independently verifiable tracks such as protocol/runtime, implementation, UI, and acceptance. If two or more can progress independently and an eligible Partner is available, delegate at least one bounded track. Otherwise publish one short single-lane reason and keep the coherent responsibility in the Facilitator.
4. Delegate bounded Partner tasks with objective, scope, acceptance, relevant active WorkDocument path, exact SkillRefs, workspace binding, capabilities, and expected output. Do not copy document bodies into the delegation. The Runtime atomically creates the real WorkItem and returns its exact ID with the accepted dispatch; use that returned ID for later document and evidence references. The target Session receives both that WorkItem and a soft Room document index. Its first action is to register the worker Markdown with a `room_work_item` binding and write objective/scope/plan before implementation. Before ending, it updates the same document with result, evidence, changed files, verification, and residual risk, then registers the new hash. A Todo label alone is not a delegation.
   - Use `delegate` for one lane.
   - When one stage has 2–3 independent, non-overlapping lanes, make one `delegate_batch` call with a short `phase` and one explicit delivery contract per target. This is the only evidence that those lanes were started as one parallel wave.
   - If a lane consumes another lane's output, dispatch it in a later stage. Never send dependent or overlapping writes in the same batch and never describe consecutive `delegate` calls as parallel.
5. Let each Partner choose private Session subagents within its granted capabilities.
6. Let Partners communicate directly through peer intercom. Consume Partner progress and result events, publish only material shared progress, and resolve dependencies or conflicts from evidence without acting as a message relay.
7. Integrate Partner results into the authoritative workspace and shared workboard.
8. Request an independent fixed-scope review only when the user asks or risk warrants it.
9. Update the Room final document and emit one integrated final result. Runtime remains responsible for enforcing the unique terminal event.

For a normal completion, call `room_partner post` exactly once with `kind=result` before the final assistant response. For a partial or blocked completion, call it once with `kind=blocked`; the content must state what is already established, the blocker, and one executable next step. This post is the Room's public result receipt, not a mechanical settle hook or a Kernel gate. Pi's ordinary `agent_settled` event remains the terminal owner.

## Failure Recovery and Terminal Rule

- Treat Session Todo as a working plan, not Room authority. Partner assignment exists only after a real delegated dispatch.
- A batch result may be `partial`: keep every returned Partner result visible, repair or reassign only the failed lane, and do not paint the whole Room as failed.
- After the same operation family fails twice, change to one smaller supported operation or declare that item blocked; do not create dummy reads or partial writes merely to keep the loop moving.
- A blocked or optional item must not leave the root running forever. Reconcile remaining Todo items into completed, blocked, abandoned, or unresolved-result entries, then emit the best evidence-backed partial or blocked final.
- Before finalizing, consume the latest Partner events once. Do not poll an idle inbox or repeat discovery after the evidence needed for the result is already available.

## Document Responsibility

- Own the Room `BRIEF`, shared `WORKBOARD`, and `FINAL` documents.
- Let each Partner own its worker document and a Reviewer own the review document.
- Keep every active worker document registered to its `room_work_item`. The Room context tells each Partner the matching `documentId`, `docs/` path, participant, and Session; the Partner verifies it with `work_documents list/get` and reads the body with `workspace_read`. A delegated WorkItem is automatically accepted only after that document has both an opening registration and at least one later content revision; there is no human review step.
- Treat the index as navigation, not a hard context bundle. Prefer entries marked `你负责`; use direct peer `@` when another Partner's context is needed, and never inherit or scan an unrelated Session transcript.
- Reference Runtime state rather than copying running, cancellation, workspace, or queue facts into Markdown.

## Output

Return the common `AgentResult` envelope with the integrated outcome, acceptance evidence, artifacts, document receipts, unresolved risks, and any unverified boundary.

## Not For

Do not reproduce Room rules inside task Skills, require a Kernel formatting gate, manufacture review, or treat Partner prose as automatic acceptance.

Example: a Partner implementing one bounded change uses `test-driven-implementation`; it does not load this Skill merely because its parent belongs to a Room.
