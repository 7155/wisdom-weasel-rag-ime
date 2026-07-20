---
name: room-review-feedback-resolution
description: Resolve independent review findings one by one with evidence, preserving disagreement and requiring re-review where the finding demands it.
when:
  - 独立复核意见需要修复、回应或申诉
  - 复核意见处理
does: 逐项闭环复核意见并输出状态、证据与复核要求。
input: 不可变 finding、相关需求、修复证据和 reviewer 身份。
output: 每条 finding 的状态、修复证据、复核要求和剩余风险。
notFor:
  - 尚未产生正式复核意见
---

# Room Review Feedback Resolution

## Enter When

Use this Skill only after a formal review produced findings that require fixes,
evidence, clarification, or a reasoned disagreement.

## Inputs

- immutable review finding IDs, severity, evidence, and required outcome;
- affected requirements and implementation ownership;
- new tests, fixes, explanations, and reviewer identity.

## Workflow

1. Keep each finding's original text and status immutable.
2. Classify the response as fixed, evidenced, clarified, disputed, deferred, or
   blocked.
3. For fixes, add a regression check and verify the relevant real path.
4. For disputes, answer the evidence and requirement, not the reviewer.
5. Mark findings ready for re-review; never self-approve a required independent
   check.

## Output Contract

Return per-finding status, changed evidence, tests, unresolved disagreement,
required re-review, and residual risk.

## Exit Conditions

Exit when every finding has an explicit status and required evidence, or report
a blocker. Reviewer-owned policy candidates are not automatic invocations.

## Real Confusions

- Silently editing a finding destroys auditability.
- "Not reproducible" without environment and evidence is not resolution.

## Hard Boundaries

This Skill cannot approve its own response, erase findings, create a Dispatch,
invoke another Skill, or send an `@`.
