---
name: room-systematic-debugging
description: Reproduce and localize an unknown failure with evidence before changing production behavior, then verify the smallest supported fix.
when:
  - 未知故障需要复现、定位和验证
does: 建立证据链并定位最小故障边界。
notFor:
  - 普通实现或已知机械改动
---

# Room Systematic Debugging

## Enter When

Use this Skill when the observed failure has no verified cause, crosses runtime
boundaries, is intermittent, or conflicts with apparently healthy status.

## Inputs

- exact symptom, affected runtime, time, environment, and expected behavior;
- logs, traces, receipts, state snapshots, and reproduction steps;
- relevant source paths and known-good comparison.

## Workflow

1. Reproduce the symptom at the real failing boundary.
2. Separate observations from hypotheses.
3. Trace input, state transitions, side effects, and output across owners.
4. Use one discriminating experiment at a time to eliminate hypotheses.
5. Fix the smallest verified cause and retain a regression test.
6. Verify both fresh and already-running state when lifecycle staleness matters.

## Output Contract

Return reproduction evidence, localized boundary, confirmed cause or remaining
hypotheses, fix evidence, regression coverage, and residual uncertainty.

## Exit Conditions

Exit only when the cause is supported and the symptom is verified fixed, or a
specific blocker is named. The Kernel may later consider policy candidates.

## Real Confusions

- Healthy service status does not prove the user-visible path works.
- A plausible source line is a hypothesis until runtime evidence connects it to
  the symptom.

## Hard Boundaries

This Skill cannot grant tools, restart systems without authority, create a
Dispatch, invoke another Skill, or send an `@`.
