---
name: implementation-planning
description: "Turn a confirmed change into the smallest dependency-aware plan without executing or assigning it. Use when work spans multiple dependent steps, owner boundaries, shared contracts, integration points, or rollback seams and a plan will materially reduce risk. Do not use for one coherent action, an unknown failure, an unresolved material choice, or to manufacture parallel tasks; e.g., one localized edit plus its focused test needs no plan."
---

# Plan Implementation

Produce only the minimum plan needed to make a confirmed change executable.
Planning describes responsibility and dependency topology; Runtime owns actual
Sessions, assignments, workspace bindings, and live state.

## Workflow

1. Read the confirmed requirement, acceptance, relevant decisions, ContextRefs,
   and current implementation seams.
2. Stop and route to `alignment-and-decision` only when a newly discovered
   material user-owned choice prevents a valid plan. Route an unknown failure to
   `systematic-debugging` instead of planning around a guess.
3. Map every acceptance criterion to an observable implementation seam and two
   distinct verification questions: whether the implementation or real path
   runs, and whether the observed result satisfies the current precise
   requirement.
4. Create the smallest vertical WorkItems that yield independently inspectable
   results. Do not use file lists, technology labels, or test/documentation
   phases as artificial tasks.
5. Record objective, expected output, acceptance, dependencies, owner role,
   verification responsibility, integration order, rollback point, exact refs,
   and capability/workspace needs for each item.
6. Recommend parallel execution only when items are independent and concurrency
   has a material benefit. Recommend an independent review only when risk or the
   user request justifies it.
7. Return the executable frontier and proposed workboard delta. Leave Agent
   creation, dispatch, reassignment, and execution to the supervising Session or
   Room Facilitator.

## Output

Return the common `AgentResult` envelope with:

```text
WorkItems and owner roles | acceptance-to-seam mapping
dependencies | executable frontier | integration order
operability checks | requirement-satisfaction checks
capability and workspace needs | rollback points
review recommendation | proposed workboard delta
```

## Not For

Do not execute work, create or assign Agents, reproduce a Runtime state machine,
force parallelism, invent a worktree, or make planning and review mandatory.

Example: a cross-process contract change with a migration, frontend consumer,
and rollback boundary benefits from a plan. A localized behavior change with one
known owner and focused test should proceed directly.
