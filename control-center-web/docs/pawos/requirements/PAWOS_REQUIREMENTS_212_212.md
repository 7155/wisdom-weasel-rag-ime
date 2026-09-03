# PAWOS 用户需求账本 · UR-212

> 导航：[UR-210–UR-211](PAWOS_REQUIREMENTS_210_211.md) · [总索引](../PAWOS_REQUIREMENTS.md) · 下一份：[UR-213](PAWOS_REQUIREMENTS_213_213.md)
>
> `current` 只表示当前控制语义，不表示实现完成。实施状态与证据见
> [PAWOS_REQUIREMENT_STATUS.md](../PAWOS_REQUIREMENT_STATUS.md)。稳定编号、来源、修正关系和原话不得因拆卷而改写或丢失。

### UR-212 — App Builder Skill 必须交付 App 专属前端实现与完整验收合同

- **状态 / 优先级：** `current / P0 self-hosting frontend contract`
- **真实需求：** `pawos-app-builder` 不能只生成 manifest、业务 Skill 或抽象说明；
  它必须携带可复制并继续改造的 App 专属前端代码，明确垂直业务 owner、通用 PAWOS
  Host、普通 Pi Session/transport 和安装库存各自负责什么，并明确新建或修改
  `App.tsx`、`app.css`、前端回归与 owner 目录的实际方法。App 对话属于 App 界面，
  但执行仍复用普通 Pi Session，不得把垂直对话塞回 Agent 首页或另建 Agent Runtime。
- **交互与身份合同：** 模式切换必须隔离各自 Session、草稿、pending message 与
  Runtime 状态，并保留共享 Session 的 Follow-up、Steer、Stop、Tool、Markdown、
  compaction 和恢复。消息重试必须按 Runtime 事实分流：transport/未知接收使用相同
  `clientMessageId` 与相同 payload；持久 `failed` command receipt 才创建新 id 并携带
  `retryOfClientMessageId`；命令已经 accepted 后 turn/Provider/Tool 失败时创建新 id
  且不得携带 `retryOfClientMessageId`。
- **自举与生命周期：** Skill 必须覆盖候选源码的受管沙箱自测、冻结
  SandboxRun/Trace/Eval 证据，以及安装、启用/停用、更新、卸载和回滚；这些产品
  状态变化继续经过受管 Package 与显式确认，不得从 source/build/preview 推导
  installed，也不得在 Connector 缺失或失败时静默回退到 Host 执行。
- **完整测试矩阵：** 至少逐层列出并实施适用的 source/manifest/Package/Skill、
  前端模式与 restore、三类 retry identity、普通 Session/Steer/Stop/recovery、
  sandbox/Trace/Eval、响应式、可访问性、生产 build、生命周期、已安装 Runtime 与
  真实前台验收。窄窗口、键盘、焦点、状态播报、长文案、错误/停止/离线/版本不匹配
  必须有明确边界；截图、fixture、单测和 build 均不能替代真实安装态与前台验收。
- **不得做：** 不得以 starter 覆盖已有 App；不得把某一业务 App 的模式、样式或
  规则写进核心；不得把本条扩展为修改掌柜问数、Observability、RAG runner 或
  eval/interview-metrics；不得因本轮 Skill 文档完成而宣称 App 已安装或验收。
- **完成态证据层级：** 当前为 `unassessed`。后续至少需要 E1 精简 Skill 路由、
  专属 frontend/lifecycle references 与可复制前端资产，E2 Skill 校验和 starter
  行为回归，E3 候选 App 生产构建，E4 受管安装/更新/卸载/回滚收据，E5 安装库存与
  App-owned Session Runtime 读回，E6 已安装 App 的真实模式对话、Retry、Steer、
  Stop、Trace、响应式与键盘前台闭环；未执行的层级必须保持未验证。
- **原话依据（无损转录）：**

  > 技能得加上配套的前端代码或者指明前端怎么改，怎么做app，需要测试哪些

  来源：当前任务，2026-08-31；当前 Codex 文档环境未暴露稳定 message/turn ID，
  不伪造。稳定消息身份、模式切换、Stop/Steer、Trace/Eval、响应式/可访问性和
  真实安装态验收是将这条要求落实为可执行 App Builder 合同的解释层，不冒充新增
  用户逐字原话。

## 继续阅读 / 编辑

- 下一份：[UR-213](PAWOS_REQUIREMENTS_213_213.md)
- 实施状态：[PAWOS_REQUIREMENT_STATUS.md](../PAWOS_REQUIREMENT_STATUS.md)
- 总入口：[PAWOS_REQUIREMENTS.md](../PAWOS_REQUIREMENTS.md)
