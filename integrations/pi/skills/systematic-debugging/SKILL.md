---
name: systematic-debugging
description: Reproduce and localize an unknown failure with evidence before changing production behavior, then verify the smallest supported fix.
when:
  - 未知、间歇或跨层故障需要复现和定位
does: 用可区分实验定位边界，只修已证明的原因。
input: 症状、预期、环境、日志、轨迹和正常对照。
output: 复现、故障边界、原因或假设、修复和回归证据。
notFor:
  - 普通实现、机械改动或无法观察真实路径
---

# Systematic Debugging

## Observation Ledger

Keep four columns separate:

```text
observation | hypothesis | discriminating experiment | result
```

An HTTP 400, empty snapshot, stale UI, and upstream timeout are different
observations even when the user sees one failed turn. Preserve request shape,
timing, state revision, and ownership boundary before changing code.

## Workflow

1. Write the exact symptom, expected behavior, environment, time window, and
   user-visible impact. Healthy service status is not a reproduction.
2. Reproduce at the real failing boundary and preserve the request, state
   transition, side effect, response, and error evidence.
3. Separate observations from hypotheses. Trace the value across its owners
   rather than reading the largest file and guessing.
4. Choose one experiment whose outcomes distinguish the leading hypotheses.
   Change one variable, record the result, and update the hypothesis set.
5. Fix only the smallest cause supported by evidence. Add a regression that
   would fail on the original defect.
6. Re-run the real path plus proportional regression. When lifecycle staleness
   matters, verify both a fresh client and an already-running client.

## Failure Classification

Before proposing a fix, name the class:

- product defect in the owning code path;
- fixture, test, or canary defect;
- stale installed/runtime artifact;
- permission or cancellation boundary;
- Provider or external-system instability;
- not yet localized.

Do not turn the last class into a production patch.

## Output Contract

Return the reproduction, observations, eliminated hypotheses, localized owner,
confirmed cause or remaining hypotheses, fix evidence, regression coverage,
and residual uncertainty. If blocked, name the one experiment or external
signal needed next.

## Self-Check

- Did I reproduce the user-visible failure, not merely a healthy dependency?
- Which exact owner first diverged from the expected value?
- Does the experiment distinguish at least two hypotheses?
- Would the regression fail on the original defect?
- Did I verify the real path after the focused test?

## Boundaries

Do not patch a plausible line before runtime evidence connects it to the
symptom, change several variables at once, call health checks a user-path pass,
restart without authority, create managed work, or route another Agent.
