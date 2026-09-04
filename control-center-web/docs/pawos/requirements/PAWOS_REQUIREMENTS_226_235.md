# PAWOS 用户需求账本 · UR-226–UR-235

> 导航：[UR-225](PAWOS_REQUIREMENTS_225_225.md) · [总索引](../PAWOS_REQUIREMENTS.md) · 下一份：[UR-236](PAWOS_REQUIREMENTS_236_236.md)
>
> `current` 只表示当前控制语义，不表示实现完成。实施状态与证据见
> [PAWOS_REQUIREMENT_STATUS.md](../PAWOS_REQUIREMENT_STATUS.md)。

## User Requirement Ledger

### UR-226 — 四个垂直项目都必须有可检查的真实运行矩阵

- **状态 / 优先级：** `current / P0 evidence access`
- **需求：** EnterpriseOps、Enterprise RAG、CloudOps、Memory Maintenance 四个项目
  各自展示任务、冻结 Case/数据集、每次运行、Trace、Eval、结果和证据入口，不能只显示
  一个聚合分数或 Agent 口播。
- **验收：** 用户能从项目进入运行矩阵，再定位到某次真实运行及其 Case、原始回执和终态；
  四项目不可互相借用成功数字。

### UR-227 — Trace Agent 必须从定位推进到候选修复与同 Case 复验

- **状态 / 优先级：** `current / P0 repair closure`
- **需求：** 对 Skill、Tool、Prompt、Workflow、Runtime/协议问题，流程为真实失败、Trace
  定位、冻结任务与环境、一次只改一项、重复运行、确定性验收、语义评分、质量硬门禁、
  成本比较、Keep/Reject、同 Case 重放、安装态 Canary。来源任务已选择 `full_trust` 时，
  Trace 诊断 Agent 可以在同一可追踪任务内直接实施候选修复并复验；内部另开普通可写
  repair Session 只是可选的责任隔离，不能成为第二次用户审批或让流程停在“只会分析”。
  无论采用哪种内部形态，新的 Trace/Eval 都必须独立复检，并把来源项目身份、改动 diff、
  同 Case 结果与终态绑定在一条审计链上。
- **禁止：** 不能因 Sol/Luna/Max 型号强就假定不会失败，也不能把“分析出问题”写成
  “已经修复”。RAG Agentic Runtime/协议链路必须按本合同处理并记录真实修复边界。

### UR-228 — 默认以最终任务结果定义成功

- **状态 / 优先级：** `current / P0 success semantics`
- **需求：** “结果成功就算成功”。默认不要求 Agent 复刻唯一轨迹；只要终态、业务副作用
  和产品结果正确，该 run 可计成功。
- **硬门禁例外：** Tool 参数、副作用、Schema/协议、安全、幂等、引用或特定顺序本身属于
  产品合同的场景，仍由确定性 gate 验收，不能用自然语言结果掩盖合同失败。

### UR-229 — 四项目最终结果改善成功率、质量与成本，耗时仅观察

- **状态 / 优先级：** `current / P0 optimization outcome`
- **需求：** 四项目分别在同 Case、同环境、同质量门禁和可比较价格口径下，交付任务成功率/
  质量和成本优于各自有效 baseline 的结果。耗时继续展示、解释和用于发现死循环，但按用户
  最新修正不再是 Keep 的硬门槛。
- **验收：** 成功率/质量、成本和耗时都显示 old→new 绝对值、delta、样本量、运行身份和
  门禁；质量或成本未改善则保持 `incomplete/Reject`。禁止换分母、把缺失 usage 当零成本、
  拿失败 baseline 做虚假提升，或伪造结果。
- **修正：** 本条以“耗时不重要”修正先前“成功率、成本、时间都变好”的时间硬门槛，
  其余四项目共同目标不变。

### UR-230 — Agent Lab 逐次展示任务、数据、原结果、优化与新结果

- **状态 / 优先级：** `current / P0 App information architecture`
- **需求：** 每次运行在 PAWOS 独立 Agent Lab App 内按“任务定义 / 数据集 Cases / 原结果 /
  优化记录 / 新结果”组织，并显示谁改了什么、怎么改、为什么改和优化效果。
- **验收：** 运行身份、模型卡、冻结字段、时间、Token、价格、Trace/Eval/Sandbox/Artifact
  引用和 Keep/Reject 彼此可追溯；不能把静态演示卡冒充 Runtime 数据。

### UR-231 — Task 与 Dataset 使用 App 内证据浏览器

- **状态 / 优先级：** `current / P0 interaction`
- **需求：** 点击 Task/Dataset 默认在 App 内打开详情，而不是弹 Finder。Task 显示目标、
  成功条件、硬门禁和冻结环境；Dataset 显示 split、Case、输入、Gold/requiredFacts、证据、
  负例/拒答、hash 和泄漏边界。
- **次级动作：** “在 Finder 显示”或复制绝对路径只作为专家辅助；普通用户无需理解本机
  文件树即可检查结果。

### UR-232 — 最终优化结果使用可下钻的 diff 矩阵

- **状态 / 优先级：** `current / P0 comparison matrix`
- **需求：** 四项目各有完整矩阵。每行是一项真实改动，至少显示“怎么改 / 为什么 / 影响
  Case / diff / 成功率或质量 / 时间 / Token / 成本 / Keep-Reject”。
- **验收：** 数值用 old→new 和 delta；点击改动进入 App 内 side-by-side diff，能回到对应
  run、Case、Trace 和验证收据。失败候选不得从审计历史消失，但不能继续出现在现行候选、
  默认比较或当前分母中。

### UR-233 — Judge 与 Golden Data 用项目真实例子解释

- **状态 / 优先级：** `current / P1 interview evidence`
- **需求：** 面试文档用 Enterprise RAG 的实际问题、`requiredFacts`、answer/evidence、
  host-private qrels、匿名候选、严格 JSON、确定性 parser、语义 Judge 和发布硬门禁逐层
  展示如何打分；Golden Data 展示真实语料、split、可答/拒答、事实到 source/chunk/quote
  绑定、hash、标注/复核和漂移规则。
- **真实性：** 明确多人一致率、人工双标/仲裁、Held-out 或生产泛化中尚未具备的证据，
  不能把通用方法论或强 Judge 自评包装成已验证事实。

### UR-234 — 每个问题都记录怎样处理以及为什么

- **状态 / 优先级：** `current / P0 audit narrative`
- **需求：** 每项修复记录真实失败、Trace 发现、根因、为何选择该修改、具体 diff、验证命令、
  before/after 指标、Keep/Reject、残余风险和安装/前台边界；必须能回答“为什么看到了问题
  却没改正”。
- **验收：** 文档叙述和 App 矩阵指向同一运行/收据，不能另写一套无法对应代码与结果的故事。

### UR-235 — 全部当前要求无损落账并隔离旧错误

- **状态 / 优先级：** `current / P0 requirement and projection hygiene`
- **需求：** 本轮关于四项目、成功语义、质量/成本优化、Trace 修复、Judge/Golden、App
  结构、diff 矩阵和旧错误处理的要求都进入正式账本，不能只留在聊天。
- **旧错误语义：** 被替代的错误代码/配置/active projection 在证明无现行消费者后删除或
  迁出当前路径；历史失败 receipt 留在隔离审计区，标记 superseded/rejected，不参与当前
  选择、指标聚合或默认 UI。禁止为“彻底删除”而抹掉可审计历史。

## 来源、修正与覆盖审计

- **当前任务逐字来源（2026-09-03）：** user-message ordinals `721`、`798`、`1181`、
  `1526`、`1713`、`1727`、`1831`、`2339`、`2547`、`2996`、`3239`、`6433`、
  `6465`，以及紧随其后的“耗时不重要……是 Luna Max 吗”。完整逐字摘录保存在
  [PAWOS_REQUIREMENT_EVIDENCE.md](PAWOS_REQUIREMENT_EVIDENCE.md)；ordinal 只用于来源
  对齐，不作为 Runtime 或完成证据。
- **修正关系：** UR-228 把默认成功口径从“理想轨迹一致”修正为“最终任务结果正确”，但
  不废除产品硬合同；UR-229 在此之上要求质量/成功与成本改善，并取消耗时硬门槛。一次
  run 可以任务成功，但项目仍可能因引用或成本保护门禁未过而 Reject。
- **参考边界：** 用户粘贴的 Agent 评测口播和既有 Judge/Golden 草稿用于提出建议与要求
  真实示例，不作为 PAW 已经完成的事实。两张矩阵截图只提供信息组织与视觉参考。
- **历史执行边界：** 此前“直接 git push”“不要添加这些 [License]”“等我干完再统一”
  属于先前上传任务及其修正，不自动授权把本轮未完成实验/UI 推送；不得重新加入已拒绝的
  License。macOS Dock 图标问题已由“ok了”终结，“继续”只恢复当前任务。

## 继续阅读 / 编辑

- 下一份：[UR-236](PAWOS_REQUIREMENTS_236_236.md)
- 实施状态：[PAWOS_REQUIREMENT_STATUS.md](../PAWOS_REQUIREMENT_STATUS.md)
- 总入口：[PAWOS_REQUIREMENTS.md](../PAWOS_REQUIREMENTS.md)
