---
name: systematic-debugging
description: "Reproduce and localize an unknown, intermittent, cross-layer, or performance failure with discriminating experiments. Use when the cause is not yet supported by repeatable evidence. Do not use for a known mechanical change, pure research, implementation planning, or a speculative patch without reproduction; e.g., a known label change should use direct implementation rather than a debugging loop."
---

# Debug Systematically

Adapt the feedback-loop discipline from Matt Pocock's `diagnosing-bugs`: prove where behavior first diverges before changing production code.

## Workflow

1. State the exact symptom, expected behavior, environment, timing, and user-visible impact.
2. Build the tightest practical command or interaction that reproduces the real failure. A health check is not a reproduction.
3. Keep observations, hypotheses, discriminating experiments, and results separate.
4. Trace the failing value or event across its real owners. Rank a small set of falsifiable hypotheses.
5. Run one experiment that distinguishes the leading hypotheses; change one variable and update the evidence ledger.
6. Classify the failure as product code, test/canary, stale runtime, permission/cancellation, external provider, or not yet localized.
7. Apply a smallest supported fix only when the cause is localized and the repair is bounded. Otherwise return the confirmed cause and suggest the appropriate implementation Skill.
8. Re-run the reproduction and proportional real path to establish the operability axis; separately compare the observed result with the current precise requirement. Add or identify regression protection and remove temporary instrumentation.
9. Update the owned worker document with material observations, eliminated hypotheses, confirmed cause, both verification axes, and any repair or reassignment needed. Do not claim terminal completion for the supervising Agent.

## Output

Return the common `AgentResult` envelope with:

```text
reproduction | observations | eliminated hypotheses | localized owner
confirmed cause or next experiment | fix and regression evidence
operability verdict | requirement-satisfaction verdict | repair owner/next stage
worker-document update receipt or proposed delta | residual uncertainty
```

## Not For

Do not patch a plausible line before evidence connects it to the symptom, change several variables at once, or turn an unlocalized failure into a production fix.

Example: if the requested change is already localized to a known UI label, implement and verify it instead of inventing hypotheses.
