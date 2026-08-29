---
name: orchestrate-session
description: "Delegate bounded supporting work through concurrent background Session subagents and close it under the Session main Agent. Use when private child Sessions provide a concrete benefit and multiple independent lanes can run as one batch while the parent continues useful work. Do not use for one simple coherent action, serial single-child delegation, or idle waiting; e.g., read one small local file directly."
---

# Orchestrate a Session

Use the Session's native subagent capability. This Skill guides delegation; it does not define another event bus, scheduler, cancellation system, or task store.

The Session main Agent is the supervisor and accountable integrator. It owns the
Goal, knows which WorkItems remain unfinished or unclosed, assigns or reassigns
them, and produces one truthful terminal result. Subagents own bounded execution
or verification responsibilities; they never replace that supervision.

## Multi-Subagent Background Execution

- **Batch dispatch**: when subagents are warranted, dispatch multiple subagents at once in a batch across distinct, independent facets (e.g. multi-path exploration, parallel code checks, distinct research areas) rather than launching single subagents serially.
- **Non-blocking background tools**: treat subagents as background tools. Once dispatched, the parent Session **continues executing its own work concurrently** (synthesizing existing context, preparing integration seams, organizing requirements, inspecting other layers) and must not be blocked in an idle wait loop.
- **Reactive event integration**: reactively consume subagent events (progress, findings, completions) when delivered; do not busy-poll.
- **Native background contract**: every native `agents` `delegate` call uses `wait=false` (the PAW bridge normalizes an omitted value to false). Never select or load the legacy standalone `subagent` package/tool: it waits for child completion inside the parent turn and is not a background path.
- **Per-task context choice**: select `fresh/new` or `fork` for each child from that task's continuity and context-reuse needs. Both are supported first-class modes; this Skill does not rank either mode as intrinsically better.

## Workflow

1. Read the precise requirement, acceptance, owned workboard, and Runtime projection. Inventory unfinished, failed, orphaned, partial, and unclosed WorkItems before creating more.
2. Decide whether delegation has a concrete benefit. When selected, map multiple independent execution or verification responsibilities and dispatch them as one concurrent batch. Keep a single coherent lane in the parent rather than manufacturing one child.
3. Give every child one bounded TaskBrief containing requirement refs, objective, scope, current and accountable owner roles, acceptance, expected output, Session/conversation and WorkDocument refs, exact ContextRefs and SkillRefs, workspace binding, capabilities, and result shape.
4. Choose each child's context mode independently. With `fresh/new`, start from the bounded envelope and referenced sources. With `fork`, reuse the managed parent prefix and append the bounded child brief. Never hard-code one mode as the general preference.
5. Choose each child's model, model card, persona, read/write access, peer-call access, and child-spawn permission at creation time.
6. Launch the batch as background tools and immediately continue the parent's own useful lane without blocking. Consume progress, document-update, failure, cancellation, and final-result events reactively; steer or cancel through native Session mechanisms.
7. Allow direct peer calls for bounded collaboration while keeping current and accountable ownership explicit.
8. Integrate child evidence against two questions: whether the implementation or real path runs, and whether the observed result satisfies the current precise requirement. A pass on only one axis is not closure.
9. Repair or reassign failed, orphaned, partial, or unclosed WorkItems to the responsible stage. Reconcile every item to `complete`, `partial`, or `blocked`, with evidence, next action, and document receipt.
10. Return one parent result. Preserve bounded child evidence and artifact refs without dumping private process.

## Document Responsibility

- The parent Session owns its work document.
- Every delegated WorkItem links the precise requirement, responsible child,
  Session/conversation, and WorkDocument. A private child normally returns a
  proposed document delta; grant direct document ownership only explicitly.
- Code write permission and document ownership are separate choices.

## Output

Return the common `AgentResult` envelope with:

```text
supervisor and WorkItem ownership | context mode per child | batch dispatch receipt
parent concurrent progress | execution and verification results
operability verdict | requirement-satisfaction verdict | repair/reassignment
terminal reconciliation | evidence/artifacts | document receipts | residual risk
```

## Not For

- Do not launch subagents serially one-by-one when a concurrent batch is appropriate.
- Do not hard-code `fresh/new` or `fork` as universally better, or use context mode as a substitute for a bounded TaskBrief.
- Do not stall or block parent Session execution waiting for background subagents.
- Do not busy-poll or idle-wait on running subagents.
- Do not spawn subagents for trivial local tasks that the parent can finish faster directly.
- Do not declare the Goal closed while a WorkItem lacks an owner/receipt or only one verification axis passed.
- Do not expose private child chatter as public progress, or turn a private Session child into a formal Room partner implicitly.

Example: reading one small configuration file locally is cheaper and clearer than spawning a child Agent to read it; when delegating, launch multiple specialized children in parallel while continuing parent work.
