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

This Skill prepares evidence; it neither approves delivery nor computes the
authoritative result.

## Core Principle

No completion claim without fresh, claim-shaped evidence. Tests, diffs, UI
inspection, Provider payloads, installed-runtime receipts, and external results
prove different things. The Kernel binds aliases and derives coverage and readiness.
For code, a complete matrix is evidence-ready. Review is optional:
the Facilitator decides whether risk warrants `independent-review` after
integration; review is not mandatory for every task.

## Workflow

1. Re-read verbatim user text, append-only corrections, and confirmed
   requirements. A directory is navigation, never a replacement for the words.
2. List every acceptance check by its short human-readable aliases. Do not
   invent backend IDs or omit an inconvenient item.
3. Collect fresh evidence shaped for each claim: focused diff, test output,
   installed-runtime receipt, Provider payload, artifact, inspected UI state,
   or explicit external result.
4. Propose `pass`, `fail`, or `not_verified`. A pass needs an inspectable
   successful ref. Unavailable, stale, or failed evidence remains not verified.
5. Probe negative paths proportional to risk: cancellation, retry,
   idempotency, permission, recovery, compatibility, stale state, migration,
   and rollback.
6. Separate product defects, test/canary defects, and external Provider
   instability. Record residual risk and its owner.
7. Translate the result into the active lifecycle Tool's exact private
   schema. For `room_commit`, put only verified items in `evidence` as
   `{"acceptance":"AC-1","refs":["<evidenceRef>"]}`. Put failures and unknowns
   in private summary and risk fields. The user-facing
   `publicSummary` states outcome, behavioral verification, uncertainty, and
   next step without internal aliases or refs.
8. For `decision=deliver`, send only loaded-schema fields. Do not send
   `acceptanceAliases`; it belongs to `decision=handoff`, while current-task
   coverage belongs in `evidence`.

## Evidence Matrix

| Field | Meaning |
|---|---|
| Claim | Observable behavior asserted |
| Evidence | Fresh successful ref or inspectable artifact |
| Scope | Revision, runtime, data, model, environment, or viewport |
| Result | `pass`, `fail`, or `not_verified` |
| Gap | Remaining unknown or failure |

For a user-facing result, also record the visibility delta:

| Surface | Target | Observed | Missing/degraded behavior | Evidence | Disposition |
|---|---|---|---|---|---|

This table cites existing criteria and has no authority to set a result or Kernel verdict.
A missing named surface remains unverified unless a confirmed requirement
revision removes it; an internal-only item may state a visibility exemption.

Match evidence to the claim:

- source/contract: focused diff plus contract test;
- runtime: real request, transition, and returned effect;
- UI: actual interaction plus visible and accessibility state;
- Provider context: final prompt, messages, and Tools payload;
- installed product: clean revision, install provenance, health, launch, and
  foreground behavior where required.

## Managed Room Boundary

- Work only on the current participant's bounded responsibility. The Kernel
  owns WorkItem settlement and any review handoff; the Facilitator owns
  integration and decides whether review is warranted. This Skill cannot
  complete the Root or choose the Reviewer.
- When review is chosen, implementation evidence hands off after integration
  to a distinct Reviewer. Do not self-review or use `room_collaborate` as the
  review route. When review is not chosen, integrated evidence proceeds to the
  same Kernel gates without manufacturing a review stage.
- Use `room_state` for current authority and `room_commit` for evidence, wait,
  block, or handoff. Rejected/stale authority cannot be replaced by model state.
- Keep private summaries, refs, workspace paths, and participant details
  private. Only the Facilitator/reporter owns the final public Room summary.
- Only the Facilitator/reporter emits the final public summary.

## Gate Outcomes

- `deliver recommendation`: all required evidence is fresh and unblocked; if
  the Facilitator chose review, advance to the distinct post-integration
  Reviewer, otherwise advance to Kernel settlement with integration evidence;
- `continue`: a legal action can produce missing evidence;
- `handoff`: another capability or owner is needed;
- `wait`: a user, permission, credential, or external signal is needed;
- `blocked`: bounded alternatives are exhausted.

These are proposals, never the Kernel's verdict.

## Output Contract

Return `original_request_checked`, one status and evidence refs per alias,
failed/unverified observations, residual risks/owners, and one gate
recommendation. The matrix is a working result, not a Tool payload; use only
the exact loaded schema when calling a lifecycle Tool.

## Self-Check

- Did I verify original words and every named surface?
- Does each pass have fresh, reproducible evidence for this revision?
- Did I preserve failures and unknowns rather than lower a threshold?
- Can an independent reviewer reproduce each material claim?

## Boundaries

Do not waive requirements, self-approve, manufacture evidence, reuse stale
evidence without applicability proof, rewrite fixtures to match a defect,
hide a missing check, choose the reviewer, or claim this Skill completed work.
