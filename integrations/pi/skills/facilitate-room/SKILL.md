---
name: facilitate-room
description: "Supervise a Room as a lightweight composition of ordinary Partner Sessions. Use when the current Session is the designated Room Facilitator responsible for shared alignment, explicit WorkItem ownership, delegation, two-axis verification, repair or reassignment, integration, and one truthful final result. Do not use in a standalone Session, Room Partner, Reviewer, or private Tool Agent; e.g., a Partner fixing one bounded item uses a task Skill."
---

# Facilitate a Room

Keep the Room lightweight. Partners remain ordinary Sessions and use the same task Skills as any other Session.

## Dispatch Roles

- Split implementation by independently deliverable outcomes, not separate
  frontend, backend, documentation, and testing lanes. Use `room_partner
  delegate` or `delegate_batch` primarily to dispatch implementation WorkItems.
- An implementation Partner delivers the assigned artifact and handoff; it does
  not own the independent test verdict.
- The Facilitator decides whether the requirements or risk justify a Reviewer.
  If selected, dispatch the Reviewer only after the implementation WorkItems
  are submitted and integrated, as a later dependent stage rather than in the
  implementation batch.
- The Reviewer is the tester. Test the integrated result against the current
  user requirements and the actual code or real path, never only the
  implementers' claims. Record the tested scope, commands, evidence, and finding
  severity. Do not pass while any P0 finding remains open; `no P0 found` applies
  only to the scope actually tested.
- If no Reviewer is assigned, report that independent testing was not performed
  instead of implying a pass.

The Facilitator is accountable for the Room Goal and closure; every delegated
WorkItem has one current responsible Partner and an explicit accountable owner.
Every active Room participant is otherwise an equal peer. When one Partner needs another
Partner's information or response, use `room_partner peer_list`, `peer_send`,
`peer_ask`, or `peer_reply` to contact that target directly. The Facilitator is
the supervisor and final Root integrator, not a message relay; never copy,
rewrite, or relay Partner wording to simulate peer conversation.

## Workflow

1. Read the project, outcome, precise requirement, Room brief, current workboard, and Runtime participant projection. Call `room_partner list` once to inventory unfinished, failed, orphaned, partial, and unclosed WorkItems before creating more. If its `recoverableWorkItems` is non-empty, execute the returned `recommendedOperation` with that exact `workItemId` and `expectedRevision` before considering any new delegation. A natural complex-project request is enough to begin; do not ask the user to restate the workflow. Before any requirements, business-code, configuration, or test write and before any `room_partner delegate` / `delegate_batch`, establish the Root authority and make one best-effort WorkDocument binding attempt:
   - Use `agent_goal list`; when no active Goal represents this Room request, use `agent_goal confirm_setup` with the request's objective, acceptance, and evidence expectations. Keep the returned `goalId` and revision.
   - Create or update one Root Markdown through `write` / `workspace_write`, passing `workDocument={authorityKind:"session_goal", authorityId:<goalId>, authorityRevision:<revision>, title:<title>}` when the optional audit trail is available. The opening body records objective, scope, acceptance, plan, and exact source refs.
   - A successful `workDocumentRegistration` is useful evidence, not a dispatch or submission gate. On every later bound write, copy the live `authorityRevision` from the current workboard or `work_documents` projection, not a previously remembered bound revision. The model-facing registration seam is the write's `workDocument` field; do not omit a valid binding because a standalone `work_documents register` Tool is absent from the current profile.
   - Before delegating or changing product files, publish one user-visible `room_partner post(kind=progress)` when the Root WorkDocument is available, linking its path and summarizing the objective, planned lanes, and acceptance. If binding, hash, or registration fails, publish one `documentSync` `pending`/`failed` reminder with its Trace and residual item, then continue. This is a plan receipt, not a new approval gate: unless a material user-owned choice is missing, continue automatically after publishing it. Update and re-publish the document receipt when the plan materially changes only if a usable binding exists.
   - If Goal setup fails, report the exact contract failure. If only the bound write or its registration receipt fails, do not create an unbound requirements file, but do continue the real product WorkItems and record the one `documentSync` `pending`/`failed` receipt. Do not retry or return a WorkItem solely for that document failure; only a document deliverable may let it affect the requirement verdict.
   For a new project, after that setup keep a proportional but complete `docs/` index, a lossless requirement ledger with stable IDs, user wording, and source, plus architecture, decisions, research, tasks, tests, acceptance, and final-result documents. Do not turn the user's prompt into a long test protocol.
2. Clarify material user choices only when necessary. Use planning only when the work truly needs multiple items or owners.
3. Before editing, identify independently verifiable tracks such as protocol/runtime, implementation, UI, and acceptance. If two or more can progress independently and an eligible Partner is available, delegate at least one bounded track. Otherwise publish one short single-lane reason and keep the coherent responsibility in the Facilitator.
4. Delegate bounded Partner tasks with requirement refs, objective, scope, acceptance, current and accountable owner roles, relevant Session/conversation and active WorkDocument refs, exact SkillRefs, workspace binding, capabilities, verification responsibility, and expected output. Do not copy document bodies into the delegation. `room_partner delegate` returns an immediate durable dispatch receipt with the exact `childDispatchId` and `workItemId`; it does not wait for the Partner to finish. Keep those IDs for later collection, document, and evidence references. The target Session receives both that WorkItem and a soft Room document index. If a worker binding is useful, attempt it at most once; a binding, hash, or registration failure gets one `documentSync` `pending`/`failed` receipt with Trace and a public residual reminder. Before ending, submit the actual result with separate operability and requirement-satisfaction evidence; do not retry or return solely because the document failed. A Todo label alone is not a delegation.
   - Use `delegate` for one lane.
   - When one stage has 2–7 independent, non-overlapping lanes, make one `delegate_batch` call with a short `phase` and one explicit delivery contract per target. Use only the lanes the work actually needs; never create work just to fill the Room. This is the only evidence that those lanes were started as one parallel wave.
   - If a lane consumes another lane's output, dispatch it in a later stage. Never send dependent or overlapping writes in the same batch and never describe consecutive `delegate` calls as parallel.
5. Let each Partner choose private Session subagents within its granted capabilities. Add a later Reviewer WorkItem only when the user asks for Grill or independent review, implementation risk or task complexity warrants it, or the document chain needs a separate consistency check. Give it to an eligible Partner that did not own the reviewed implementation. The Reviewer checks the original user requirements, runnable defects, each Partner's bounded context refs, and whether worker documents, indexes, cross-references, and terminal updates are correct. It owns a registered review WorkDocument and reports honest evidence; never place this artifact-dependent Reviewer in the producer's wave. For ordinary low-risk work, the Facilitator performs the normal two-axis review directly without manufacturing another WorkItem.
6. Let Partners communicate directly through peer intercom. Partner completion schedules a durable wake for the Facilitator; react to that wake instead of keeping `delegate` open or polling. Use `room_partner collect` or `wait` only at an explicit stopping point, addressed by `childDispatchId` or `workItemId`. A `wait` timeout never cancels the Partner or changes the WorkItem; continue useful Facilitator work or report the still-running item.
7. Integrate Partner results into the authoritative workspace and shared workboard. For each submitted WorkItem, inspect current evidence and revision, then judge separately whether the implementation/real path runs and whether the observed result satisfies the current precise requirement. A `documentSync` `pending`/`failed` receipt is a visible residual and does not by itself require `return` or `retry`; only when the requested deliverable is the document itself may that failure make the requirement verdict unsatisfied or unverified. The Facilitator must explicitly call `accept` or `return` with `expectedRevision`, both verdicts, `evidenceRefs`, and a non-empty `reason`. Copy the verdicts actually observed. Accept only with `operabilityVerdict=passed` and `requirementVerdict=satisfied` plus a `reason` stating what was verified; Runtime rejects accept without that reason and rejects accept over Partner proposed failed/unverified/not_satisfied unless `supersededByWorkId` names a later submitted review WorkItem that is a direct child of the failed item and itself proposes passed/satisfied. If a reviewer reported `unverified`, `changes_required`, `failed`, or unresolved HIGH/MEDIUM findings, `return` the item; do not store `passed`/`satisfied` over that evidence. Otherwise return it with a concrete `reason` and responsible next action. A returned item remains `active` with `reviewFeedback`; send it back for revision with `room_partner retry`, the original `workItemId`, its latest `expectedRevision`, and a concrete `reason`. Omit `targetParticipantId` to retain the current owner, or use an exact ID from `list` only when reassigning. Do not call `delegate`, create a replacement WorkItem, or create a Reviewer merely to continue that same revision chain. Web verification uses the product `browser` tool (PAW Browser / ego-browser). Never launch or drive standalone Chrome/Edge through `desktop_semantic`.
8. Repair or reassign returned, failed, orphaned, partial, or unclosed WorkItems to the responsible stage. A returned active item and a failed or blocked Partner result all continue through the same `retry(workItemId, expectedRevision, reason)` operation; only failed or blocked items require a preceding `collect` to inspect their terminal evidence. Do not use the review-only `return` operation for failed or blocked work. Use `return` only for a submitted item in review. If retry is unavailable, exhausted, or not useful, record the honest terminal boundary, evidence, owner, and next action. Request an independent fixed-scope review only when the user asks or risk warrants it; review does not replace either verification axis.
9. Reconcile every WorkItem to `complete`, `partial`, `blocked`, `abandoned`, or an explicit unresolved result with owner, evidence, next action, and any document receipt. When a Reviewer WorkItem exists, resolve it and its findings before closure; a failed or unverified review is not a pass. The Root Agent alone merges the shared index and owns the integrated terminal result. Then update and register the Room final document when that optional binding is usable, or retain one `documentSync` `pending`/`failed` Trace and residual reminder if it is not; do not reopen completed WorkItems for document repair. Runtime remains responsible for enforcing the unique terminal event.

Room posts are typed. `op=post`, `kind=progress` is non-terminal: it publishes
material progress but never completes a WorkItem, the Room Goal, or the current
Session turn. Never infer terminality or result kind from a content prefix or
other prose; only the explicit `kind` field carries that meaning.

For a normal completion, only after every WorkItem is reconciled and the
Facilitator has recorded both `operabilityVerdict=passed` and
`requirementVerdict=satisfied`, call `room_partner` with `op=post`, `kind=result`
exactly once. Only after that Tool receipt succeeds, call `agent_goal complete`;
the Runtime rejects Goal completion while the active Root lacks its typed result.
Do not post a second result. After the Goal completion receipt succeeds, finish
the normal assistant turn so Pi emits the ordinary `turn_completed`;
the result post is the Room's public receipt, not a replacement terminal event
or a content-triggered settle hook. For a partial or blocked completion, call
`room_partner` once with `op=post`, `kind=blocked`; the content must state what
is already established, the blocker, and one executable next step.
After either terminal post, do not process later ordinary Partner-completion
wakes or reopen normal work; only bookkeeping that preserves the already
emitted terminal result may continue.

If a bounded finalization wake itself reaches `turn_completed` but the model
still omits `post(kind=result)`, Runtime may append one idempotent terminal
receipt only when every WorkItem under that Root is already `done` and carries
the Facilitator's persisted `passed` / `satisfied` review, reviewer identity,
and non-empty evidence refs. That fallback projects the existing review ledger;
it never accepts WorkItems, parses assistant prose, or turns an incomplete Root
into success. If any predicate is absent, the missing-result failure remains
visible for repair.

## Failure Recovery and Terminal Rule

- Treat Session Todo as a working plan, not Room authority. Partner assignment exists only after a real delegated dispatch.
- A batch result may be `partial`: keep every returned Partner result visible, repair or reassign only the failed lane, and do not paint the whole Room as failed.
- A passing build or runnable path does not prove requirement satisfaction, and a convincing requirement narrative does not prove the path runs. Record both axes before closeout.
- Partner completion, prose, and WorkDocument revisions are submission evidence only. None of them accepts a WorkItem without the Facilitator's explicit evidence-backed review transition.
- After the same operation family fails twice, change to one smaller supported operation or declare that item blocked; do not create dummy reads or partial writes merely to keep the loop moving.
- A blocked or optional item must not leave the root running forever. Reconcile remaining Todo items into completed, blocked, abandoned, or unresolved-result entries, then emit the best evidence-backed partial or blocked final.
- Do not pause a live Room Goal to wait for the user, UI, or a later message. Pause silences the live Root. Leave the Goal active and emit `blocked`/`partial` with the blocker and one executable next step so a user message can continue the Root.
- Before finalizing, consume the latest Partner events once. Do not poll an idle inbox or repeat discovery after the evidence needed for the result is already available.

## Document Responsibility

- Own and, when possible, bind the Root WorkDocument to the active `session_goal` before substantive execution, and own the Room `BRIEF`, shared `WORKBOARD`, `docs/` index, and `FINAL` documents. A plain `docs/agent/requirements.md`, Todo, or Room post is not that binding; a successful `workDocumentRegistration` receipt is useful evidence but not a hard dispatch or submission gate. The Root Agent alone merges Partner document links and terminal conclusions into those shared authorities.
- Let each Partner own its worker document and a Reviewer own the review document.
- Keep every active worker document registered to its `room_work_item` when the binding succeeds. The Room context tells each Partner the matching `documentId`, `docs/` path, participant, and Session; the Partner verifies it with `work_documents list/get` and reads the body with `workspace_read`. An opening registration and at least one later content revision are useful evidence, but are not prerequisites for submission, not acceptance. A failed binding gets one `documentSync` `pending`/`failed` Trace and public residual reminder; the Partner still submits real results, and the Facilitator still judges both verification axes from evidence and explicitly accepts or returns the current revision. Only a document deliverable makes this sync failure affect the requirement verdict.
- Treat the index as navigation, not a hard context bundle. Prefer entries marked `你负责`; use direct peer `@` when another Partner's context is needed, and never inherit or scan an unrelated Session transcript.
- Reference Runtime state rather than copying running, cancellation, workspace, or queue facts into Markdown.

## Output

Return the common `AgentResult` envelope with the Goal supervisor, WorkItem owners and terminal reconciliation, integrated outcome, operability and requirement-satisfaction verdicts, artifacts, document receipts, repair/reassignment, unresolved risks, and any unverified boundary.

## Not For

Do not reproduce Room rules inside task Skills, require a Kernel formatting gate, manufacture review, treat Partner prose as automatic acceptance, pause a live Room Goal as a wait, or leave an unfinished/unowned WorkItem hidden behind the Room final.

Example: a Partner implementing one bounded change uses `test-driven-implementation`; it does not load this Skill merely because its parent belongs to a Room.
