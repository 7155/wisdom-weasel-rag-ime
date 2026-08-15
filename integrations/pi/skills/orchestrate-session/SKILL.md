---
name: orchestrate-session
description: "Delegate bounded supporting work through native Session subagents and integrate their event results. Use when parallel investigation, specialist help, or a private child task has a concrete benefit. Do not use when the current Agent can finish coherently faster, to create a formal Room Partner, or merely to fill concurrency; e.g., one short file read should stay in the parent Session."
---

# Orchestrate a Session

Use the Session's native subagent capability. This Skill guides delegation; it does not define another event bus, scheduler, cancellation system, or task store.

## Workflow

1. Decide whether delegation has a concrete benefit. Keep the work local when coordination would cost more than execution.
2. Give each child one bounded TaskBrief containing objective, scope, acceptance, expected output, exact ContextRefs, exact SkillRefs, workspace binding, and capabilities.
3. Choose the child's model, model card, persona, read/write access, peer-call access, and child-spawn permission at creation time.
4. Do not copy the full parent transcript. Pass summaries first and let the child load referenced bodies or sources when needed.
5. Consume progress, finding, document-update, failure, cancellation, and final-result events. Steer or cancel through the native Session mechanisms.
6. Allow direct peer calls for bounded collaboration, while keeping responsibility for each result explicit.
7. Integrate child results against the parent TaskBrief. Treat findings as evidence, not automatic decisions or completion.
8. Return one parent result. Preserve child evidence and artifact refs without dumping private process.

## Document Responsibility

- The parent Session owns its work document.
- A private child normally returns a proposed document delta; grant direct document ownership only explicitly.
- Code write permission and document ownership are separate choices.

## Output

Return the common `AgentResult` envelope with integrated child summaries, evidence, artifacts, document updates, unresolved conflicts, and residual risk.

## Not For

Do not create subagents merely to fill concurrency, expose private child chatter as public progress, or turn a private Session child into a formal Room partner implicitly.

Example: reading one small configuration file locally is cheaper and clearer than spawning a child Agent to read it.
