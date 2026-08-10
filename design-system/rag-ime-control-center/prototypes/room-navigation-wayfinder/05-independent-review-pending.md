# Room 导航与项目图谱 · 独立复核

> Room: `project-field`
> Stage: `independent-review`
> 状态：pending
> 进入条件：质量门全部通过并取得用户原生可见验收。

## Fixed-diff pre-review · 2026-08-05

- 第一轮发现三项必修问题：详情缺少决定、收起 Room 暴露完整五段轨、来源需要二次展开。
- 修复后逐项复查均为 `pass`：决定由八份 Room docs 确定性投影；收起 Room 只保留标题、需求和短阶段；一次点击直接显示决定、交付文档与来源。
- Requirement Fidelity：`review_clear_with_risk`。
- Code Standards：`review_clear`。
- 唯一未清风险是用户原生可见验收仍为 `not_verified`，因此本阶段不登记为完成。

## Review scope

- 八个 Room 是否都按纵向用户结果划分，而不是技术层、聊天或工单。
- 从第一个真实输入 Room 开始的时间分化、带回执关系、贯穿式验收轨道和未抵达目的地是否表达一致；共享架构只能是 Room 的实现约束，不得成为图上对象。
- 纸张摘要与详情是否完全来自权威 docs，manifest 是否只拥有布局和 receipts。
- 路径自然分化与收拢是否在没有独立汇聚节点、没有未验收目的地连接的前提下成立。
- 阶段和验收证据进度是否相互独立，任何完成比例是否都能回到具体验收项与来源回执。
- 五段外层交付链是否固定，测试驱动实现是否只属于实现执行内层。
- 来源、隐私、Owner 与真实验收边界是否保持失败关闭。

## Possible outcomes

- `approved`：质量门完整通过后，独立复核无阻断问题，Room 可以进入完成结算。
- `changes_requested`：带具体证据返回实现执行。
- `blocked`：仅用于存在无法在当前授权或环境中解决的真实阻断。

## Source refs

- `doc-project-field-contract`
- `session-codex-project-reconstruction`
- `doc-handoff-goal`
