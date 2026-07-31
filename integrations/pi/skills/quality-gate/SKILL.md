---
name: quality-gate
description: Gather fresh evidence for a delivery claim and map it to the confirmed acceptance checks; the Kernel, not the model, decides whether work may settle.
when:
  - 即将交付、移交、复核或发布结果
does: 按原始需求和验收收集新鲜证据。
input: 原始需求、验收别名、改动、证据、产物和风险。
output: 各项证据提议、失败、未验证项、风险和下一步。
notFor:
  - 尚无交付主张，或用自述、旧日志和降低阈值冒充验证
---

# Quality Gate

This Skill prepares evidence. It does not approve delivery and it does not
compute the authoritative final status.

## Core Principle

No completion claim without fresh, claim-shaped evidence. Tests, diffs, UI
inspection, Provider payloads, installed-runtime receipts, and external results
prove different things; one green command cannot stand in for all of them.
The Kernel binds aliases and decides settlement. For code changes, a complete
matrix is evidence-ready; `independent-review` still owns review clearance.

## Workflow

1. Re-read the verbatim user text supplied by the Runtime, later append-only
   corrections, and the current confirmed requirement directory. The directory
   is navigation; it never replaces the user's words.
2. List every current acceptance check using the short human-readable aliases
   supplied in task context. Do not invent backend IDs or omit an inconvenient
   item.
3. For each check, collect fresh evidence appropriate to the claim: focused
   diff, test output, installed-runtime receipt, Provider payload, artifact,
   inspected UI state, or an explicit external result.
4. Classify the evidence proposal as `pass`, `fail`, or `not_verified`.
   A `pass` needs at least one inspectable reference. An unavailable check is
   `not_verified`, never a pass.
5. Test negative paths proportional to risk: cancellation, retry, idempotency,
   permission boundary, recovery, compatibility, stale state, migration, and
   rollback where relevant.
6. Separate product defects from test/canary defects and external Provider
   instability. Record residual risk and its owner.
7. Translate the proposal into the active lifecycle Tool's exact private schema.
   For `room_commit`, include only verified items as
   `{"acceptance":"AC-1","refs":["<evidenceRef>"]}` inside `evidence`.
   Put failed or unverified observations in the private summary and residual
   risks, then continue, hand off, wait, or report blocked. The required
   `publicSummary` translates relevant outcome, behavioral verification,
   uncertainty, and next step into natural language without exposing aliases
   or reference IDs. The Kernel binds aliases to authoritative criteria,
   verifies eligible receipts and freshness, derives coverage and readiness,
   then accepts settlement or returns the exact missing item.
   For `decision=deliver`, send `decision`, private `summary`, user-facing
   `publicSummary`, `evidence`, and `residualRisks`, plus optional `blocks`.
   Do not send `acceptanceAliases`: that field is only for `decision=handoff`;
   current Task AC coverage always belongs in `evidence`.

## Evidence Matrix

For each acceptance alias, record:

| Field | Required meaning |
|---|---|
| Claim | The observable behavior being asserted |
| Evidence | Fresh successful `evidenceRef` or inspectable artifact |
| Scope | Environment, revision, model, data, viewport, or runtime tested |
| Result | `pass`, `fail`, or `not_verified` |
| Gap | What remains unknown or failed |

For user-facing acceptance, also record this concise visibility delta:
| Surface | Confirmed target | Observed behavior | Missing/degraded behavior | Evidence refs | Disposition |
|---|---|---|---|---|---|

A missing named surface remains `not_verified` unless a confirmed requirement revision removes it;
author-only deferral is not evidence. Internal-only work may state a visibility exemption.
The table cites existing criteria/receipts and has no authority to set a result or Kernel verdict.

Use evidence that matches the claim:

- source or contract claim -> focused diff plus contract test;
- runtime claim -> real request, state transition, and returned effect;
- UI claim -> actual interaction plus visible and accessibility state;
- Provider-context claim -> final `systemPrompt + messages + tools` payload;
- installed-product claim -> clean commit, install provenance, health, and
  launch evidence.

## Gate Outcomes

- **deliver recommendation**: every required alias has fresh evidence and no
  blocker; code changes advance to review and are not review-cleared;
- **continue**: an authorized action can still produce missing evidence;
- **handoff**: another participant or model capability is needed;
- **wait**: one user, permission, credential, or external signal is required;
- **blocked**: bounded alternatives are exhausted or the requirement is
  unreachable.

These are proposals. Do not write the Kernel's verdict yourself.

## Output Contract

Return:

- `original_request_checked`;
- one item per acceptance alias with `status` and `evidence_refs`;
- failed and unverified observations;
- residual risks and owners;
- a recommendation: deliver, continue, handoff, wait, or blocked.

The recommendation is advisory. The matrix is a working result, not a Tool
payload. When calling `room_commit`, never send `status`, `evidence_refs`,
`criterionId`, `pass`, `verdict`, a coverage set, Root status, or frontend
completion state. Use only the exact fields in the loaded `room_commit` schema.

## Self-Check

- Did I verify the user's original words, not only a derived checklist?
- Is every `pass` backed by a fresh successful reference from this revision?
- Did I distinguish product failure, canary failure, and Provider instability?
- Did I preserve failures and unverified items instead of lowering a threshold?
- Would an independent reviewer be able to reproduce the claim?

## Boundaries

Do not waive requirements, self-approve sensitive work, manufacture evidence,
reuse stale evidence without proving it still applies, rewrite screenshots or
fixtures to match a defect, call a missing check "not relevant" without a
confirmed requirement change, or claim that the Skill itself completed the
task.
