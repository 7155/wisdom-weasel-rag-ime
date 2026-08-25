---
name: implementation-planning
description: "Turn a confirmed change into the smallest dependency-aware set of verifiable work items. Use when work spans multiple steps, owners, shared contracts, integration points, or rollback boundaries. Do not use for one coherent action, an unknown failure, an unresolved material choice, or to manufacture parallel tasks; e.g., one localized edit plus its focused test does not need a plan."
---

# Plan Implementation

Plan only as much structure as the work needs. Prefer one coherent Session when it can finish the task safely.

## Workflow

1. Read the TaskBrief, acceptance criteria, decisions, relevant ContextRefs, and current implementation seams.
2. Stop and suggest `alignment-and-decision` only if a newly discovered material user choice prevents a valid plan.
3. Map each acceptance criterion to an observable implementation seam and to two distinct verification questions: whether the implementation/real path runs, and whether the observed result satisfies the current precise requirement.
4. Create the smallest vertical work items that produce independently inspectable results; do not use file lists as tasks.
5. For every work item, record requirement refs, current and accountable owner roles, Session/conversation and WorkDocument refs, acceptance, dependencies, next action, verification responsibility, integration order, and rollback point. Runtime supplies actual identities and live state.
6. Recommend parallel work only when items are independent and concurrency has a material benefit.
7. Recommend owner roles, capabilities, and workspace needs; leave actual Agent creation, assignment, reassignment, and workspace binding to the supervising caller.
8. Update the owned workboard with the accepted plan, material blockers, and next frontier.

## Document Responsibility

- Update the existing workboard or return a proposed delta when write access is absent.
- Keep runtime state, Agent presence, and workspace status out of prose; reference their Runtime projections.
- Link decisions, evidence, and affected contracts instead of copying their full contents.

## Output

Return the common `AgentResult` envelope with:

```text
work items and responsibility fields | two-axis acceptance mapping
dependencies | executable frontier | integration order | rollback
review recommendation
workboard update receipt or proposed delta
```

## Not For

Do not execute work, create Agents, force parallelism, invent a worktree, or introduce a mandatory review or quality-gate stage.

Example: a localized behavior change with a known owner and one focused test should proceed directly with the implementation Skill.
