---
name: quality-gate
description: Verify a claimed delivery against the immutable original request, current requirement directory, acceptance conditions, and fresh evidence. Use before requesting review, handing off completed work, or claiming a task is done.
when:
  - 即将声称完成、请求评审、正式移交或发布交付
does: 逐项对账原始需求和验收证据，明确通过、失败与未验证项。
input: 原始需求、可修订需求目录、改动、测试、运行证据和剩余风险。
output: 覆盖矩阵、失败或未验证项、证据引用和是否可交付的建议。
notFor:
  - 工作仍在早期探索且没有交付主张
  - 用旧日志、模型自述或降低门槛替代新鲜验证
---

# Quality Gate

## Workflow

1. Re-read the immutable original request. Treat the derived requirement
   directory as editable navigation, never as a replacement for the original.
2. Build a compact matrix of each requirement and acceptance condition:
   `pass`, `fail`, or `not_verified`.
3. Attach fresh evidence to every pass: focused diff, test result, runtime
   receipt, Provider payload, artifact, or inspected UI state as appropriate.
4. Check negative paths proportional to risk: cancellation, retry,
   idempotency, permission boundary, recovery, compatibility, and stale state.
5. Separate implementation defects from test-environment or external-provider
   failures. Never turn an unavailable check into a pass.
6. State remaining risks and their owner. Recommend delivery only when all
   required items pass or an authorized owner explicitly waives them.

## Output Contract

Return:

- original-request coverage;
- acceptance matrix and evidence references;
- failed and unverified items;
- regression and operational risks;
- `ready_to_deliver` or `not_ready`.

## Boundaries

This Skill does not lower thresholds, rewrite screenshots to match a defect,
approve its own sensitive action, emit a Room commit, set Goal or Root terminal
state, or unlock the frontend. It provides evidence for the authoritative
lifecycle owner.
