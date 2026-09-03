# PAWOS 用户需求账本 · UR-213

> 导航：[UR-212](PAWOS_REQUIREMENTS_212_212.md) · [总索引](../PAWOS_REQUIREMENTS.md) · 下一份：[UR-214](PAWOS_REQUIREMENTS_214_214.md)
>
> `current` 只表示当前控制语义，不表示实现完成。实施状态与证据见
> [PAWOS_REQUIREMENT_STATUS.md](../PAWOS_REQUIREMENT_STATUS.md)。稳定编号、来源、修正关系和原话不得因拆卷而改写或丢失。

### UR-213 — 自我进化实验数据必须有面向初学者的可追溯详情网页

- **状态 / 优先级：** `current / P1 evidence comprehension`
- **真实需求：** System Monitor 增加一张“优化报告”详情页。它不是宣传大屏或只显示
  六个大数字的简历卡片，而是把 RAG 调参 Agent、沙盒测试 Agent、评价 Agent、
  Keep/Reject 门禁和 Trace 的职责先讲清楚，再逐项解释 RAG、CloudOps、Trace、
  Extension App 沙盒与上下文缓存实验。
- **阅读合同：** 假设读者不了解 RAG、nDCG、MRR、Recall、CA、JRA、Validation、
  Held-out、canary 或 Provider cache。每个实验必须显示原理、冻结输入、基线与候选
  原始值、计算方式、以前的问题、实际改动、效果、判定理由、证据文件和禁止外推的
  边界；检索质量与回答逐事实引用质量必须分开。
- **真实性：** 页面从已保留的实验收据制作有日期的阅读快照，不把 Validation、沙盒、
  安装或真实前台互相冒充。缓存结论必须按冷轮 `10,647` 与热轮 `941/963` 重新计算为
  `90.96%–91.16%`，并明确纠正先前摘要中的 `92.7%–92.9%` 抄录错误。
- **可用性：** 页面需要稳定的章节导航、窄窗口重排、键盘焦点、减少动效支持和可读的
  数据表；主要解释默认可见，不能把用户要看的原理和效果藏进默认关闭的 disclosure。
- **后续位置修正：** `UR-214` 只修正页面归属：报告必须迁出 System Monitor，成为
  独立网页；本条的数据、解释与证据合同继续有效。
- **原话依据（无损转录）：**

  > - RAG Validation：nDCG、MRR、Recall 分别提升约 44.78% / 43.53% / 42.19%。
  > - Trace 闭环记录：8 个契约缺陷得到闭环处理，另有 3 个源码级修复；分类不可相加。
  > - CloudOps 基线：12/12 回答、98/98 Tool 调用成功、CA 1.0、JRA 0.8333。
  > - 搜索型候选虽然耗时降低 26.58%、Top-3 JRA 达到 1.0，但 CA 降至 0.8333、Tool 调用增加 92.86%，因此被门禁自动 Reject，未安装、未查看 Held-out。
  > - 掌柜问数沙盒：SGG 固定夹具 Precision/Recall/F1 为 1.0，Provider 调用 0，生产写入被阻止；这不是生产 Text-to-SQL 准确率。
  > - 缓存 canary：未缓存输入量降低约 92.7%–92.9%，命中 9,728 cached tokens。这些做成网页，我看看效果

  > 我是为了看详情，是怎么回事

  > 把我当做不了解的人，网页把原理和效果，改变全部讲清楚

  来源：当前任务，2026-09-01；当前 Codex 文档环境未暴露稳定 message/turn ID，
  不伪造。缓存百分比属于用户引用上一条 Agent 摘要后的展示需求；原始收据复核后的
  `90.96%–91.16%` 是本条的事实修正，不改写用户原话。

## 继续阅读 / 编辑

- 下一份：[UR-214](PAWOS_REQUIREMENTS_214_214.md)
- 实施状态：[PAWOS_REQUIREMENT_STATUS.md](../PAWOS_REQUIREMENT_STATUS.md)
- 总入口：[PAWOS_REQUIREMENTS.md](../PAWOS_REQUIREMENTS.md)
