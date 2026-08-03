---
name: systematic-debugging
description: Build a tight red-capable feedback loop for an unknown failure, localize it with evidence, and verify the smallest supported fix.
when:
  - 未知、间歇或跨层故障需要复现和定位
does: 先构造精确反馈环，再用可区分实验定位和修复原因。
input: 症状、预期、环境、日志、轨迹和正常对照。
output: 复现、故障边界、原因或假设、修复和回归证据。
notFor:
  - 普通实现、机械改动或原因已被可重复证据定位
---

# Systematic Debugging

Method provenance: this Room-bounded Skill adapts Matt Pocock's
`diagnosing-bugs` at upstream commit
`2ab958093e83e0ec752e6c1c5932da465bf23e0c`. The upstream method supplies the
feedback-loop discipline; Room policy, capability, workspace, and receipts
remain authoritative.

## Observation Ledger

Keep four columns separate:

```text
observation | hypothesis | discriminating experiment | result
```

An HTTP 400, empty snapshot, stale UI, and upstream timeout are different
observations even when the user sees one failed turn. Preserve request shape,
timing, state revision, and ownership boundary before changing code.

## Feedback Loop Gate

Before ranking hypotheses or editing production code, build one tight,
deterministic, fast, agent-runnable command that goes red on the exact user
symptom. Minimize it until every remaining input and step is load-bearing.
Skip this gate only with an explicit, evidence-based reason.

Use a focused test, direct request or CLI fixture, trace replay, headless
interaction, throwaway harness, differential check, or bisect as appropriate.
If no loop is possible after named attempts, stop and request the missing
environment, artifact, or instrumentation permission. Do not theorize.

## Workflow

1. Write the exact symptom, expected behavior, environment, time window, and
   user-visible impact. Healthy service status is not a reproduction.
2. Run the feedback command at the real failing boundary and preserve request,
   state transition, side effect, response, and error evidence.
3. Separate observations from hypotheses. Trace the value across its owners,
   then state three to five ranked, falsifiable hypotheses with predicted
   observations.
4. Choose one experiment whose outcomes distinguish the leading hypotheses.
   Change one variable, record the result, and update the hypothesis set.
   For a performance regression, establish a repeatable baseline and use a
   profiler, query plan, or timing/bisection harness; measure before changing
   code instead of replacing a performance signal with broad logs.
5. Fix only the smallest cause supported by evidence. Add a regression that
   would fail on the original defect.
6. Re-run the exact feedback command, real path, and proportional regression.
   Remove temporary instrumentation. When lifecycle staleness matters, verify
   both a fresh client and an already-running client.
7. Record the confirmed hypothesis, why alternatives failed, and any missing
   test seam. Return a structural seam gap to architecture work; do not hide it
   behind a brittle regression.

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
- Can one command go red on the exact symptom and green after the fix?
- Which exact owner first diverged from the expected value?
- Did I rank falsifiable hypotheses before testing them?
- Does the experiment distinguish at least two hypotheses?
- Would the regression fail on the original defect?
- Did I verify the real path after the focused test?

## Boundaries

Do not patch a plausible line before runtime evidence connects it to the
symptom, change several variables at once, call health checks a user-path pass,
restart without authority, leave diagnostic instrumentation behind, create
managed work, or route another Agent.
