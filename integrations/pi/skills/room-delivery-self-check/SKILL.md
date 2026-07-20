---
name: room-delivery-self-check
description: Check the implementer's own delivery against requirements, tests, side effects, handoff state, and unresolved blockers before settling.
when:
  - 实施者收工前需要逐项自检
  - 收工前自检
does: 核对并输出交付、验证、交接和阻塞状态。
input: 原始与派生需求、改动、测试、运行证据和交接状态。
output: 带证据的自检清单、缺口、阻塞和 settle 建议。
notFor:
  - 需要独立角色做愿景复核
---

# Room Delivery Self-Check

## Enter When

Use this Skill before the implementing Agent settles, publishes a completion
claim, or hands work to another owner.

## Inputs

- original and derived requirements;
- implementation diff, tests, runtime evidence, and receipts;
- expected handoff, waiting, or blocker state.

## Workflow

1. Map every changed behavior to a requirement and verification result.
2. Check scope drift, untested branches, compatibility, migrations, cancellation,
   idempotency, and unintended side effects.
3. Confirm the result was published or handed off through an explicit governed
   path rather than left in private Session output.
4. State whether the Agent is complete, waiting, delegated, or blocked.
5. Never convert uncertainty into a completion claim.

## Output Contract

Return a checklist with evidence references, gaps, handoff state, blockers, and
a settle recommendation. This is self-review, not independent approval.

## Exit Conditions

Exit with `ready`, `needs_fix`, `waiting`, or `blocked`, each backed by evidence.
Policy may suggest a reviewer, but no next Dispatch is created here.

## Real Confusions

- Passing unit tests does not prove migration, cancellation, or actual product
  integration.
- Self-check cannot substitute for an independent reviewer when policy requires
  separation of duties.

## Hard Boundaries

This Skill cannot mark a Root complete, approve its own sensitive work, grant
capabilities, invoke a next Skill, send an `@`, or create a Dispatch.
