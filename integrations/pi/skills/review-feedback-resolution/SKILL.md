---
name: review-feedback-resolution
description: Preserve and classify independent review findings, route code repairs through implementation execution, and attach returned evidence for re-review.
when:
  - 正式复核意见需要修复、补证、澄清或异议
does: 保留原发现，逐项分类并把代码修复交回实施外层。
input: 原发现、严重度、证据、验收、实现和复核者。
output: 修复包或各发现状态、新证据、复核要求和风险。
notFor:
  - 尚无正式发现，或仅是一般建议和风格偏好
---

# Review Feedback Resolution

## Response Matrix

Preserve the original finding and add, never replace:

| Status | Meaning |
|---|---|
| `needs_execution` | a bounded repair packet must return to the implementation outer loop |
| `fixed` | implementation changed and the original path has a behavioral regression or a focused verifier that would fail on the original non-behavioral defect |
| `evidenced` | implementation was correct; new evidence proves the requested behavior |
| `clarified` | scope or wording was ambiguous; no defect claim is silently erased |
| `disputed` | requirement or evidence contradicts the finding |
| `deferred` | only valid with an explicitly confirmed scope change |
| `blocked` | a named external condition prevents resolution |

## Workflow

1. Preserve each finding's original text, severity, evidence, and requested
   outcome. Never edit history to make a fix look easier.
2. Classify the current response as `needs_execution`, `fixed`, `evidenced`,
   `clarified`, `disputed`, `deferred`, or `blocked`.
3. When a finding requires code or artifact changes, return a repair packet to
   `implementation-execution`; do not change code here. Include the original
   path, acceptance, owner, expected fix condition, and required re-review.
   Execution chooses TDD or debugging, updates continuity, and returns the
   behavioral regression or a focused verifier that would fail on the original
   non-behavioral defect. Only then classify the finding as `fixed`.
4. For a dispute, answer the requirement and evidence rather than the reviewer.
   New evidence may change a finding; confidence or tone may not.
5. Attach returned artifacts and evidence, then mark the finding ready for its
   required re-review. Never self-approve separation-of-duty work.

## Repeated-Failure Sweep

When two verified findings share the same invariant class, state that invariant
once, sweep bounded sibling call sites and state transitions for the same
failure mode, and report affected references plus prevention evidence.
Unrelated findings do not trigger this sweep. If a third review round finds the
same invariant failure on the same state object, stop issuing instance repair
packets and return an advisory planning/requirement gap packet with the original
findings, object, missing transition or invariant, and evidence. The existing
Runtime owner decides routing and state. This Skill creates neither.

## Per-Finding Packet

Include original text and severity, chosen status, response, changed artifacts,
fresh evidence, behavioral regression or focused failing verifier as
applicable, sweep/escalation result, unresolved disagreement, residual risk,
and required re-review owner. Resolve findings one by one; a passing broad
suite does not answer a specific finding.

## Output Contract

Return one row per finding with status, changed artifacts, evidence, tests,
unresolved disagreement, required re-review, and residual risk. When changes
remain, return `needs_execution` with the repair packet instead of a final row.

## Self-Check

- Can the reviewer see the original finding unchanged?
- Does a `fixed` response reproduce and protect the original path?
- Does a dispute cite requirement and evidence rather than confidence?
- Did I avoid self-approval and hidden deferral?

## Boundaries

Do not erase or rewrite findings, modify implementation, bypass execution/TDD
or continuity, call "not reproducible" without environment and evidence,
approve your own response, create follow-up work, or route another Agent.
