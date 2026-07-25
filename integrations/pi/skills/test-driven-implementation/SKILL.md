---
name: test-driven-implementation
description: Implement one bounded change from observable behavior, adding a failing test first and preserving existing contracts outside the approved scope.
when:
  - 已确认的行为变更可测试并需要回归保护
does: 先证明缺口，再做最小完整实现并验证。
input: 需求、验收、模块所有权、兼容约束和测试入口。
output: 失败复现、实现、测试结果、契约影响和风险。
notFor:
  - 未知故障尚未定位，或仅需读取、调研和格式整理
---

# Test-Driven Implementation

## Red-Green Contract

The red check must fail because the confirmed behavior is missing. A failure
caused by a stale fixture, unavailable Provider, wrong environment, or invalid
test setup is diagnostic evidence, not the red phase.

## Workflow

1. Trace the real public behavior and state owner before writing a test.
2. Express the missing behavior as the narrowest meaningful failing check.
   Confirm that it fails for the intended product gap, not bad setup, stale
   state, provider instability, or an obsolete fixture.
3. Implement the smallest coherent production change at the owning boundary.
   Preserve unrelated user work and compatibility outside the confirmed scope.
4. Run the focused check, then the relevant contract, integration, and
   regression checks proportional to risk.
5. Refactor only after behavior is green, and only when it improves ownership,
   dependency direction, or deletion of duplicated logic.
6. Report the behavior changed, evidence, contract impact, unrun checks, and
   residual risk.

## Evidence Sequence

```text
public behavior traced
-> focused test fails for the intended reason
-> smallest owning implementation changes
-> focused test passes
-> affected contracts and integrations pass
-> proportional real-path verification passes
```

For a bug, preserve the original symptom in the regression. For a new
contract, test both the accepted shape and at least one material rejection
path. Refactoring belongs after green and must not create another runtime path.

## Output Contract

Return changed behavior and files, red/green evidence, relevant regression
evidence, compatibility notes, remaining failures, and residual risk. Source
inspection or a test added after the fix is not completion evidence.

## Self-Check

- Does the test express an observable contract instead of an implementation
  detail?
- Did it fail before the production change for the correct reason?
- Is the change located at the real state owner?
- Did I preserve unrelated behavior and user work?
- Did I report every relevant check that was not run?

## Boundaries

This workflow grants no filesystem, shell, Provider, routing, or approval
authority. Do not patch an unexplained flaky failure, loosen an assertion to
make it green, create managed work, choose the next Agent, or claim acceptance.
