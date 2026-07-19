---
name: room-delivery-closure
description: Close a delivery only after acceptance, required reviews, public evidence, cancellation cleanup, and remaining-risk ownership are explicit.
when:
  - 所有必需工作完成并需要最终收口
does: 核验验收、证据、清理和剩余风险。
notFor:
  - 仍需接手、复核或修复
---

# Room Delivery Closure

## Enter When

Use this Skill only when implementation, required review, feedback resolution,
and public delivery evidence are complete or explicitly waived by an authorized
owner.

## Inputs

- requirement and acceptance status;
- implementation, test, review, approval, and Room publication receipts;
- active Dispatch, retry, timer, lease, and cancellation state;
- residual risks and their named owners.

## Workflow

1. Verify every required acceptance item against evidence.
2. Confirm no required review or unresolved blocking finding remains.
3. Confirm active work, retries, timers, leases, and follow-ups are settled or
   deliberately retained with owners.
4. Publish the concise final outcome and residual risks through the governed
   Room commit path.
5. Recommend closure to the Kernel; do not synthesize `isFinal` from model text.

## Output Contract

Return acceptance evidence, unresolved non-blocking risks, cleanup state,
public-delivery reference, and a closure recommendation.

## Exit Conditions

Exit with `ready_to_close` or `not_ready`, including exact missing evidence.
There is no automatic next Skill or Agent.

## Real Confusions

- "The Agent said done" is not acceptance evidence.
- A background retry or child execution means the chain is not globally final.
- Work that still needs another owner belongs to structured handoff, not final
  closure.

## Hard Boundaries

This Skill cannot set Root terminal state, unlock the frontend, cancel work,
grant authority, create a Dispatch, invoke another Skill, or send an `@`.
