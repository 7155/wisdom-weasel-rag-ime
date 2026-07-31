---
name: test-driven-implementation
description: Implement one bounded code slice from observable behavior, starting with a correctly failing test.
when:
  - An active execution slice needs code and regression protection
does: Prove the gap, implement at the owning seam, and verify the slice.
input: Acceptance alias, behavior, owner, compatibility limits and test seam.
output: Red/green evidence, implementation, contract impact and risk.
notFor:
  - Unexplained failures, reading, research or formatting-only work
---

# Test-Driven Implementation

This is the inner code-change loop of `implementation-execution`, not a
standalone delivery stage. Return its evidence to the outer execution packet;
do not settle the Task or move directly to review.

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
   residual risk to `implementation-execution`.

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
