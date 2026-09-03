# PAWOS 用户需求账本 · UR-214

> 导航：[UR-213](PAWOS_REQUIREMENTS_213_213.md) · [总索引](../PAWOS_REQUIREMENTS.md) · 下一份：[UR-215–UR-220](PAWOS_REQUIREMENTS_215_220.md)
>
> `current` 只表示当前控制语义，不表示实现完成。实施状态与证据见
> [PAWOS_REQUIREMENT_STATUS.md](../PAWOS_REQUIREMENT_STATUS.md)。

### UR-214 — 优化报告必须是 PAWOS 外部的独立网页

- **状态 / 优先级：** `current / P1 information architecture correction`
- **真实需求：** `/evolution-report` 是独立 Web 文档，不挂载在 System Monitor 的
  窗口内容区，也不属于任何 PAWOS App。直接打开该路径时只出现报告页、轻量站点头和
  返回 PAW 的入口，不渲染桌面、Dock、窗口或 System Monitor 侧栏。
- **发现入口：** System Monitor 可以保留“优化报告（网页）”按钮，但它只能打开独立
  URL，不能把报告重新作为内部 pageId 渲染。
- **兼容边界：** 报告继续复用 `UR-213` 的初学者解释、原始数据、计算、Keep/Reject
  与证据边界；本条只 supersede `UR-213` 中“System Monitor 增加详情页”的归属描述。
- **验收：** 独立 URL 在普通浏览器和 PAW 本机 Web Host 均可直接打开；窄屏、键盘
  焦点、章节导航、减少动效继续成立；PAWOS App registry 不得把该路径映射回
  `system-monitor`。
- **原话依据（无损转录）：**

  > 报告放外面网页

  来源：当前任务，2026-09-01；当前 Codex 文档环境未暴露稳定 message/turn ID，
  不伪造。

## 继续阅读 / 编辑

- 下一份：[UR-215–UR-220](PAWOS_REQUIREMENTS_215_220.md)
- 实施状态：[PAWOS_REQUIREMENT_STATUS.md](../PAWOS_REQUIREMENT_STATUS.md)
- 总入口：[PAWOS_REQUIREMENTS.md](../PAWOS_REQUIREMENTS.md)
