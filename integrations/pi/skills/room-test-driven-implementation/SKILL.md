---
name: room-test-driven-implementation
description: Implement one bounded change from observable behavior, adding a failing test first and preserving existing contracts outside the approved scope.
when:
  - 明确变更需要从失败测试开始实现
  - 测试驱动实现
does: 以红绿重构输出受限改动及测试证据。
input: 明确需求、验收条件、模块边界、兼容约束和验证命令。
output: 失败测试、实现与回归证据、契约影响和剩余风险。
notFor:
  - 未知故障尚未定位
---

# Room Test-Driven Implementation

## Enter When

Use this Skill for an approved, bounded behavior change with a testable external
contract. An unknown failure belongs to systematic debugging first.

## Inputs

- exact requirement and acceptance references;
- owned module and existing test conventions;
- allowed files, compatibility constraints, and verification command.

## Workflow

1. Express the missing behavior as the narrowest meaningful failing test.
2. Confirm the failure is caused by the intended gap, not test setup.
3. Implement the smallest coherent production change.
4. Run the focused test, then relevant regression tests.
5. Refactor only when behavior remains green and ownership stays clear.
6. Report changed behavior, evidence, and residual risk.

## Output Contract

Return test evidence, changed files, contract impact, compatibility notes, and
remaining failures. Never report completion from source inspection alone.

## Exit Conditions

Exit when focused and relevant regression checks pass, or report a concrete
blocker. Any policy candidate remains advice for later review.

## Real Confusions

- A flaky or unexplained failure is not permission to patch until green.
- Adding assertions after the implementation does not prove the test could
  detect the original defect.

## Hard Boundaries

This Skill grants no filesystem, shell, Provider, or delegation capability. It
cannot create a Dispatch, invoke the next Skill, or send an `@`.
