---
name: room-implementation-planning
description: Turn an approved solution into bounded, dependency-aware implementation and verification work while preserving ownership and acceptance links.
when:
  - 已批准方案需要拆成可执行任务
  - 实施计划与任务拆解
does: 输出有依赖、所有者和验证门的实施计划。
input: 已批准方案、需求目录、模块边界、依赖和验收条件。
output: 需求可追溯、按所有权拆分且带验证门的实施计划。
notFor:
  - 方案尚未收敛
---

# Room Implementation Planning

## Enter When

Use this Skill after a solution is sufficiently settled and before work crosses
multiple modules, Agents, migrations, or verification gates.

## Inputs

- approved decision and affected derived requirements;
- module ownership and dependency boundaries;
- acceptance checks, migration limits, rollback needs, and available Agents.

## Workflow

1. Map each requirement to one or more implementation and verification steps.
2. Split work by ownership boundary, not arbitrary file count.
3. Name dependencies, parallel-safe lanes, shared contracts, and merge order.
4. Give every step a concrete completion signal and failure rollback.
5. Identify changes that must remain backward compatible.

## Output Contract

Return an ordered plan with requirement references, owned modules, dependencies,
verification commands, integration gates, and explicit non-goals. A plan entry
is not a runtime Task or Dispatch until the Kernel creates it.

## Exit Conditions

Exit when every planned step has an owner boundary and verification signal, or
when a missing decision is reported. Policy candidates never become automatic
calls.

## Real Confusions

- "Backend, frontend, tests" is not a dependency-aware plan.
- Parallel work that edits the same contract without one owner is not truly
  parallel.

## Hard Boundaries

This Skill does not allocate Agents, create Dispatches, grant Tools, or start
implementation. It never sends an `@` or auto-loads another Skill.
