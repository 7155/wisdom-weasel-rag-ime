---
name: implementation-planning
description: Turn a user-confirmed requirement packet into the smallest dependency-aware plan whose tasks have clear ownership and verification.
when:
  - 已确认需求需要跨步骤、模块或参与者实施
does: 把验收映射为少量有依赖和所有者的任务。
input: 需求、边界、现状、依赖、权限和验收。
output: 任务、依赖、责任、证据、集成门和回滚点。
notFor:
  - 需求未确认、单步任务或机械按文件拆分
---

# Implementation Planning

## Planning Invariants

- Plan from observable acceptance backward, not from a directory tree forward.
- One state owner owns each shared contract; parallel lanes must not race on it.
- A Task is independently understandable and verifiable, not merely a file
  list or an Agent-sized chunk.
- Planning proposes work. Only the Kernel creates managed Tasks or Dispatches.

## Workflow

1. Verify that the current requirement packet is explicitly confirmed and not
   contradicted by a later correction. Otherwise return to
   `requirement-alignment`.
2. Inspect the current implementation before designing work. Identify the
   state owner, public contracts, dependency direction, tests, migration
   boundaries, and existing extension points.
3. Map each acceptance check to implementation work and independent
   verification. First ask whether one Session can finish coherently.
4. Split only where state ownership, module boundaries, or independently
   verifiable outcomes make the separation real. Add another participant only
   when work can proceed without competing for the same state or contract.
5. State dependencies, parallel-safe lanes, shared-contract owners,
   integration order, permission needs, cancellation effects, and rollback.
6. Give every candidate one objective, one expected output, linked acceptance
   checks, fresh evidence requirements, and a completion signal.
7. Keep the smallest plan that covers all acceptance without widening scope.

## Task Candidate Contract

Each candidate must state:

```text
Objective:
Owned boundary:
Inputs and dependencies:
Expected artifact or behavior:
Acceptance aliases:
Fresh evidence:
Permissions and workspace:
Handoff or completion signal:
```

When candidates share a contract, add one integration owner and an explicit
order: contract first, independent consumers second, integration verification
last. When two candidates must edit the same owner at the same time, keep them
serial or combine them.

## Output Contract

Return the confirmed requirement reference, ordered task candidates, owner and
dependency boundaries, parallel/serial decision, evidence and review gates,
non-goals, rollback points, and `ready_for_kernel_start` or
`needs_requirement_decision`. A candidate is not managed work until the Kernel
accepts it.

## Self-Check

- Does every acceptance item map to implementation and verification?
- Is every parallel lane safe without concurrent ownership of the same state?
- Is the integration order and rollback point explicit?
- Could one coherent Session do this more simply?
- Did I avoid creating work or choosing Agents in the planning text?

## Boundaries

Do not allocate Agents, create WorkItems or Dispatches, grant capabilities,
start implementation, or invent a master/sub-Agent hierarchy. "Backend,
frontend, tests" is not a plan unless those boundaries own independent state
and have an explicit integration owner.
