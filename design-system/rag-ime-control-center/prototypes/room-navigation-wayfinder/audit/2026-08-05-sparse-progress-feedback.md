# 2026-08-05 · 稀疏布局与进度反馈

> 类型：用户反馈与质量路由
> 状态：accepted_for_implementation

## Observed feedback

- 用户对当前可见页面的直接要求是“稀疏一些，还要进度”。
- 当前卡片在用户可见缩放下仍互相压住，行列空白不足。
- 阶段标签只能说明当前阶段，需要增加一眼可读的整体交付进度。

## Disposition

扩大 Project Field 世界和总览边界，保持上三、中二、下三结构并增加行列间距；所有收起 Room 增加由权威 `currentStage` 确定性派生的五段进度条和 `n/5`，完整阶段名称只在 Room Focus 展开。实现后重新执行确定性构建、自动检查和用户原生可见验收，质量门保持 pending。

## Source refs

- `session-codex-project-field`
- `doc-project-field-contract`
