---
name: review-feedback-resolution
description: Resolve independent review findings one by one with evidence, preserving disagreement and requiring re-review where the finding demands it.
when:
  - 正式复核意见需要修复、补证、澄清或异议
does: 保留原发现，逐项给出处置和证据。
input: 原发现、严重度、证据、验收、实现和复核者。
output: 各发现状态、新证据、回归、复核要求和风险。
notFor:
  - 尚无正式发现，或仅是一般建议和风格偏好
---

# Review Feedback Resolution

## Response Matrix

Preserve the original finding and add, never replace:

| Status | Meaning |
|---|---|
| `fixed` | implementation changed and original path now has regression evidence |
| `evidenced` | implementation was correct; new evidence proves the requested behavior |
| `clarified` | scope or wording was ambiguous; no defect claim is silently erased |
| `disputed` | requirement or evidence contradicts the finding |
| `deferred` | only valid with an explicitly confirmed scope change |
| `blocked` | a named external condition prevents resolution |

## Workflow

1. Preserve each finding's original text, severity, evidence, and requested
   outcome. Never edit history to make a fix look easier.
2. Classify the current response as `fixed`, `evidenced`, `clarified`,
   `disputed`, `deferred`, or `blocked`.
3. For a fix, reproduce the reported path, make the smallest supported change,
   and add a regression that would detect the original defect.
4. For a dispute, answer the requirement and evidence rather than the reviewer.
   New evidence may change a finding; confidence or tone may not.
5. Link every changed artifact and verification result, then mark the finding
   ready for its required re-review. Never self-approve separation-of-duty work.

## Per-Finding Packet

Include original text and severity, chosen status, response, changed artifacts,
fresh evidence, regression for the original path, unresolved disagreement,
residual risk, and required re-review owner. Resolve findings one by one; a
passing broad suite does not answer a specific behavioral finding.

## Output Contract

Return one row per finding with status, changed artifacts, evidence, tests,
unresolved disagreement, required re-review, and residual risk.

## Self-Check

- Can the reviewer see the original finding unchanged?
- Does a `fixed` response reproduce and protect the original path?
- Does a dispute cite requirement and evidence rather than confidence?
- Did I avoid self-approval and hidden deferral?

## Boundaries

Do not erase or rewrite findings, call "not reproducible" without environment
and evidence, approve your own response, create follow-up work, or route
another Agent.
