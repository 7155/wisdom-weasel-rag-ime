# PAWOS 用户需求账本 · UR-236

> 导航：[UR-226–UR-235](PAWOS_REQUIREMENTS_226_235.md) · [总索引](../PAWOS_REQUIREMENTS.md) · 下一份：[UR-237–UR-239](PAWOS_REQUIREMENTS_237_239.md)
>
> `current` 只表示当前控制语义，不表示实现完成。实施状态与证据见
> [PAWOS_REQUIREMENT_STATUS.md](../PAWOS_REQUIREMENT_STATUS.md)。

## User Requirement Ledger

### UR-236 — 对话原文、需求、改动与运行证据必须双向可追踪

- **状态 / 优先级：** `current / P0 evidence lineage`
- **用户原话：** “对话记录证据都要可追踪”。
- **需求：** 用户原始消息、从消息解释出的 Requirement、实施 diff、Trace finding、冻结
  Case/Dataset、Runner/Judge/Golden receipt、before/after 指标、Keep/Reject 和验收命令必须
  组成可双向下钻的证据链，不能只保留 Agent 总结或无法回到来源的截图。
- **来源身份：** 平台提供稳定 message/thread ID 时必须原样记录；当前界面没有暴露稳定
  message ID 时，必须明确标记此缺口，并至少保留线程边界、真实时间、消息顺序、逐字原文
  与原文 SHA-256。禁止伪造 ID，后续取得真实 ID 时以追加映射补齐，不覆盖原记录。
- **验收：** 任一 Agent Lab 结论都能从 `requirementId → sourceRef → exact quote/hash →
  changed factor/diff → runId/caseId → Trace/Judge/Gold receipt → verdict` 正向检查，也能从
  receipt、run 或 diff 反查控制它的 Requirement 和用户原话；历史失败保留只读 lineage，
  但按 `projectionState=history` 隔离，不污染当前结论。

## 来源与覆盖审计

- **sourceRef：** `current-thread/2026-09-03/after-UR-235`
- **capturedAt：** `2026-09-03T22:00:16+08:00`
- **exactQuoteSha256：** `78346ec80196cd9e6c13a34046f440c238bf5ba0bcc48cef94c0e1be7c8afdd4`
- **messageId：** `unavailable-in-current-codex-interface`；这是显式证据缺口，不是自造 ID。
- 本条补强 `UR-230`、`UR-232`、`UR-234` 与 `UR-235` 的 lineage 要求，不改变它们的
  成功、成本、历史隔离或 App 信息架构语义。

## 继续阅读 / 编辑

- 下一份：[UR-237–UR-239](PAWOS_REQUIREMENTS_237_239.md)
- 实施状态：[PAWOS_REQUIREMENT_STATUS.md](../PAWOS_REQUIREMENT_STATUS.md)
- 总入口：[PAWOS_REQUIREMENTS.md](../PAWOS_REQUIREMENTS.md)
