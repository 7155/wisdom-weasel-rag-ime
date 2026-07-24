---
name: room-implementation-planning
description: Turn a user-confirmed Room requirement packet into bounded, dependency-aware work candidates before managed execution.
when:
  - 已确认 Room 需求包需要拆成任务
  - 实施计划与任务拆解
does: 输出任务候选、依赖、责任边界和验证门，不自行分派。
input: 已确认需求、模块边界、成员能力、依赖、权限和验收。
output: 可追溯、按所有权拆分且带验证门的任务候选。
notFor:
  - 需求未确认、仍在讨论或已开始受管执行
---

# Room Implementation Planning

## Enter When

Use this Skill only after `room-requirement-clarification` returned a
user-confirmed packet, or when the user supplied an equally explicit scope,
acceptance, constraints, and non-goals in the original message. Use it before
the Kernel creates managed work.

## Inputs

- the confirmed original-goal reference and current requirement packet;
- accepted product and architecture decisions;
- module ownership, dependency, workspace, and permission boundaries;
- acceptance checks, rollback needs, and capabilities of available peer Room
  Sessions.

## Workflow

1. Refuse to plan if the confirmation packet is missing or contradicted by a
   later user correction. Return the unresolved item to intake.
2. Map every acceptance check to implementation and verification work.
3. First decide whether one Session can finish coherently. Add peer Room
   members only for independent research, implementation, or review that has a
   concrete boundary.
4. Split by state ownership, module boundary, or independently verifiable
   outcome, never by arbitrary file count or collaboration role labels.
5. Name dependencies, parallel-safe lanes, shared contracts, integration order,
   permissions, and cancellation implications.
6. Give each candidate a concrete expected output, evidence requirement,
   completion signal, and failure or rollback path.
7. Identify backward-compatibility and non-goal guards. Keep the smallest plan
   that covers every confirmed acceptance check.

## Output Contract

Return:

- confirmed requirement references;
- an ordered list of task candidates with objective, expected output,
  acceptance links, owner boundary, dependencies, and evidence;
- which candidates may run in parallel and which must be serialized;
- integration and review gates;
- explicit non-goals and rollback points;
- `ready_for_kernel_start` or `needs_requirement_decision`.

A candidate is not a WorkItem, Task, or Dispatch until the authoritative
runtime accepts it.

## Exit Conditions

Exit when every confirmed acceptance check is covered exactly once by a
verifiable owner boundary, or when one missing decision is returned to the
same user conversation.

## Real Confusions

- "Backend, frontend, tests" is not a dependency-aware plan.
- Four Room members are not four required tasks. One coherent task stays with
  one Session when parallelism adds only coordination cost.
- Parallel work that edits the same contract without one owner is not truly
  parallel.

## Hard Boundaries

This Skill does not allocate Agents, create WorkItems, Roots, Tasks or
Dispatches, grant Tools, or start implementation. It never sends an `@` or
turns peer Room Sessions into a master/sub-Agent hierarchy. Kernel routing and
the user's confirmed start remain authoritative.
