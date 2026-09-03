---
name: orchestrate-session
description: "Delegate bounded supporting work through private child Sessions while the current Session remains the visible supervisor. Use when one or more child Sessions provide a concrete benefit through specialist context, isolation, independent evidence, or useful concurrency. Do not use for one coherent action the parent can finish directly, visible Room responsibility, or idle delegation; e.g., read one small local file directly."
---

# Orchestrate a Session

Use the Session's native subagent capability. This Skill guides private
delegation; it does not define another event bus, scheduler, cancellation
system, task store, or Room. The parent Session remains responsible for the
Goal, integration, verification, and one final result.

## Workflow

1. Read the precise requirement, acceptance, current Runtime projection, and
   existing unfinished child work before creating more.
2. Decide whether a child provides a concrete benefit. A single specialist
   child is valid when it creates real leverage; several children are justified
   only when their responsibilities are independent.
3. Give each child one bounded `TaskBrief` with objective, scope, expected
   output, acceptance, exact ContextRefs and SkillRefs, capabilities, workspace,
   verification responsibility, and result shape. Do not send the full parent
   transcript by default.
4. Choose `fresh/new` or `fork` from the task's actual continuity needs. This
   Skill does not rank either mode as intrinsically better.
5. **Batch dispatch** several independent children in one wave when concurrency
   has a material benefit. Do not manufacture parallel lanes, and do not call a
   series of dependent launches parallel.
6. Treat child execution as asynchronous. Continue useful parent work when
   available, consume delivered progress and completion events, and use an
   explicit wait only at a genuine integration barrier. Never busy-poll.
7. Integrate child evidence against two questions: does the implementation or
   real path run, and does the observed result satisfy the current precise
   requirement? A pass on only one axis is not closure.
8. Revise, retry, cancel, or report blocked work through native Session
   controls. Return one bounded parent result without exposing private child
   chatter or raw Tool history.

## Boundary With Room

Private children produce supporting evidence for their parent. Use a Room
Partner instead only when the user should see an independently accountable
participant and WorkItem in the Room timeline. Never turn a private child into a
formal Room Partner implicitly, and never load `facilitate-room` inside a child.

## Documents

The parent owns any shared work document. A child normally returns a proposed
delta or artifact refs; grant direct document ownership only when explicitly
needed. Code write access and document ownership are separate decisions.

## Output

Return the common `AgentResult` envelope with:

```text
parent responsibility | child TaskBriefs and context modes
dispatch receipts | child evidence and artifacts
integrated result | operability verdict | requirement-satisfaction verdict
cancelled, revised, partial, or blocked child work | residual risk | next action
```

## Not For

Do not spawn a child merely to demonstrate multi-Agent behavior, delegate a
trivial read, require several children when one is enough, busy-poll, expose
private transcripts, transfer final responsibility to a child, or use this
Skill for visible Room responsibility.

Example: one child may inspect a risky compatibility surface while the parent
implements a known local seam. Three independent investigations may be launched
as one batch, then integrated by the parent.
