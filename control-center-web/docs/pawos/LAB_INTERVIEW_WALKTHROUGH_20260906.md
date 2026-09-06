# Agent Lab 面试展示：一条任务的优化过程

## 用户需求账本

- **当前要求：** “我们需要展示，怎么展示这一系列，我需要面试展示”
- **来源：** 用户直接消息 msg_01a07678-f226-7e51-88ca-a1f9e197c09a，UTC 2026-09-06T11:27:12.934Z，Session 01a07530-02ad-7a31-92c8-8a7ae531da07。
- **承接：** [UR-284–UR-291](requirements/PAWOS_REQUIREMENTS_284_291.md)，重点是垂直任务成功率与成本选择、真实环境、可解释改动，以及前端逐步展示。
- **本稿性质：** Agent 提出的展示结构与讲述脚本，供用户查看和调整；不视为用户已接受具体布局、个人历史动机或简历措辞。数据来自既有历史运行，交互预览不执行模型或业务操作。

## 观众需要理解什么

面试官应能沿一个真实执行过的仿真任务理解：业务 Agent 怎样办事、如何判定
完成、低价模型在哪里失败、候选怎样改动，以及 Lab 如何据此选择配置。
工程价值围绕任务环境、版本与候选、执行证据和验收展开。

首条建议使用 EnterpriseOps CSM 的 Sol → Luna → Luna + 通用 Prompt
路径。它有业务读写、确定性数据库检查及拒绝/保留记录，适合解释模型价格
与成功率的取舍。来源是公开企业流程仿真基准；没有客户生产数据或线上收益
证据，不能称为 PAW 客户生产案例。

这条故事当前只证明模型与 Prompt 的一轮对照。Tool、Skill、Workflow 和
其他垂直场景仍按各自实际实验补证，不能借用本案的收益。

## 六幕讲述，约 5 分 40 秒

| 幕 / 时间 | 主画面与点击 | 讲述重点 | 深挖时展开 |
| --- | --- | --- | --- |
| 1. 业务任务 / 40 秒 | Larson 请求；客户、设备/合同、工单、知识文档关系 | 一个请求需要跨对象操作；成功由最终业务状态判定 | 原始请求、来源、15 项检查的业务含义 |
| 2. 执行环境 / 50 秒 | 初始 SQL → 独立数据库；Pi → 业务工具；Host → SQL 判定 | 每轮从相同状态开始；数据可见范围与实际写入范围明确 | 初始化、工具绑定、判定与结束清理源码 |
| 3. 模型对照 / 60 秒 | Sol、Luna、Luna + 规则的三列对照 | 仅换低价模型出现质量退步，所以先拒绝再适配 | 固定任务集、判定器、工具目录与成本回执 |
| 4. 失败与改动 / 90 秒 | 第 15 项失败；三组规则变化摘要 | 失败在负责人选择约束；候选依据失败加入通用方法 | 失败检查、Prompt 分支、原 Trace；缺失轨迹不补画 |
| 5. 复验与选择 / 50 秒 | 三条任务检查矩阵与保留理由 | 原有通过项保持通过，失败项恢复；报告质量与成本取舍 | 单轮样本边界、未调优任务和应用状态 |
| 6. 工程与边界 / 50 秒 | 环境可重复、候选身份、可核对结果、待补齐路径 | 说明哪些能力能复用，哪些仍需要实验或前端接入 | 环境适配、工具契约、版本应用与回退的真实实现 |

面试不需要等待一轮耗时数分钟的评测结束。可先操作真实产品中的已保存历史
证据；若现场重新运行，应显示真实运行身份和状态。历史结果、录屏回放与
现场运行具有不同时间身份，不能借同一套动画混成“正在执行”。

## 当前可使用的数字

| 同一冻结集合 | Sol / max 原方案 | Luna / max 仅换模型 | Luna / max 加通用 Prompt |
| --- | ---: | ---: | ---: |
| 完整任务成功 | 3 / 3 | 2 / 3 | 3 / 3 |
| 数据库检查通过 | 31 / 31 | 30 / 31 | 31 / 31 |
| Larson 任务检查 | 15 / 15 | 14 / 15 | 15 / 15 |
| 三条任务合计成本估算（USD） | 1.711214 | 0.09453296 | 0.07291692 |
| 历史决策 | 基线通过 | 拒绝候选 | 保留候选 |

口径：单轮 source-local Validation；3 条任务包含 31 项检查，不能视为
31 个独立任务。费用是 runtime_cost_reconciled 的 Runtime 用量对账与
价格估算，billing.status=not_provided。最终候选较 Sol 的估算低约
95.7%，不是 Provider 账单节省或未经评测的普遍生产收益。

第 15 项对应知识文档负责人地区/任职条件。本轮 Prompt 同时补充角色与
地区/任职筛选、已选工具目录约束和精确枚举优先三组规则；没有逐条消融，
不能把全部收益单独归因于其中一条。当前汇总没有完整展示具体误选人员和
逐步查询过程；正式深挖应读取原 Trace 后再展示。

## 60 秒开场稿

> Agent Lab 的目标是为垂直任务选择质量和成本合适的 Agent 配置。这里用
> 一条企业客户服务任务说明：Agent 需要操作多个业务对象，最终由数据库
> 状态检查是否真正完成。我们已有一组三任务对照：原模型全部完成；只换
> 低价模型后，有一条未完成，所以候选先被拒绝。随后固定低价模型，调整
> 通用提示词规则，同题复验恢复了全部通过，合计成本估算也下降。接下来
> 我会打开失败项、具体规则和复验结果，说明这个选择是怎样作出的。这是
> 公开仿真任务的单轮验证，新的任务和重复运行还需要补齐。

此稿描述已核对的实验事实，不替用户补写未确认的个人职责或历史动机。

## 视觉与交互

- **主次：** 每幕一个主要结论、一个主体图或对照表、一个下一步入口。
  任务关系、环境责任、候选比较和失败定位分别呈现。主要内容沿同一阅读
  位置替换，导航稳定，不将全部内容塞入配置表单。
- **阅读：** 展示稿标题约 30px，正文约 16px，局部标题 18px；小字只用于
  元数据。运行 ID、哈希与完整路径收进“查看依据”。常规工作台的
  10–12px 正文不能直接当作投屏展示字号。
- **颜色：** 当前步骤使用蓝色；通过/保留、失败/拒绝同时使用文字与颜色。
  成本柱使用共同尺度并直接标原值；缺失和未验证不画成零。
- **讲述：** “讲述提示”控制本地说明展开。候选阶段不自动切换，不添加
  虚构执行进度。支持步骤按钮、上一幕/下一幕及左右键。
- **窄窗口：** 导航换行，对象关系和对照分组重排，不缩小整页。浅色与
  深色使用对应的不透明阅读表面。

## 真实 Lab 前端怎样承接

以下是下一步实现建议，当前没有把预览安装为产品功能。

| 展示职责 | 复用的现有位置 | 接入时需要补齐 |
| --- | --- | --- |
| 从选中实验进入逐步展示 | [Lab 入口](../../src/features/eval-lab/index.tsx)、[ExperimentWorkspace](../../src/features/eval-lab/ExperimentWorkspace.tsx) | 固定实验和运行身份，退出后返回原位置 |
| 失败、归因、变化、复验 | [OptimizationWorkbench](../../src/features/eval-lab/optimization/OptimizationWorkbench.tsx) | 放大阅读层级；缺少 Trace 时保留缺口，不合成工具轨迹 |
| 候选实际改动 | [CandidatePatchEvidence](../../src/features/eval-lab/CandidatePatchEvidence.tsx) | 绑定运行实际使用的版本，区分中文摘要与原始差异 |
| 逐案结果与费用 | [ExperimentResultSummary](../../src/features/eval-lab/ExperimentResultSummary.tsx) | 串出三阶段路径，每列使用对应运行和同一口径 |
| 生效与恢复 | [ExperimentApplication](../../src/features/eval-lab/ExperimentApplication.tsx) | 核对真实应用、新运行配置和回退回执；历史 Keep 不写成已应用 |

前台验收必须用真实入口从业务任务走到候选对照，并能展开源记录；若演示
“重新运行”或“应用版本”，还需要执行与生效回执。展示稿不关闭 UR-284
或 UR-291。

## 证据入口

- 三阶段目录：[agent-experiments.v1.json](../../../eval/interview-metrics/agent-experiments.v1.json)，条目 enterpriseops-csm.luna-prompt-adaptation-r7.v1。
- 原方案：[Sol r8](../../../eval/interview-metrics/runs/enterpriseops-csm-sol-max-preloaded-current-runtime-validation-20260904.r8.v1.json)。
- 低价模型失败：[Luna r5](../../../eval/interview-metrics/runs/enterpriseops-csm-luna-preloaded-model-only-validation-20260904.r5.v1.json)。
- Prompt 候选：[Luna r7](../../../eval/interview-metrics/runs/enterpriseops-csm-luna-explicit-enum-prompt-validation-20260904.r7.v1.json)。
- 成本回执：[Sol](../../../eval/interview-metrics/runs/agent-lab-cost-enterpriseops-sol-max-preloaded-current-runtime-20260904.r8.v1.json)、[Luna](../../../eval/interview-metrics/runs/agent-lab-cost-enterpriseops-luna-max-preloaded-model-only-20260904.r5.v1.json)、[Luna + Prompt](../../../eval/interview-metrics/runs/agent-lab-cost-enterpriseops-luna-max-explicit-enum-prompt-20260904.r7.v1.json)。
- 环境与判定：[执行器](../../../scripts/run_enterpriseops_csm_eval.py)、[冻结场景合同修正](../../../eval/enterpriseops-csm-suite-v2.overlay.v1.json)。
- 业务基准：[ServiceNow EnterpriseOps-Gym](https://github.com/ServiceNow/EnterpriseOps-Gym)。

## 本次核对与完成边界

完成的是展示结构、讲述稿和对话中的可点击预览。六幕导航、讲述提示、
证据展开及首尾按钮状态已实际操作；1024 / 736 / 360px、浅色/深色下对
四个主要画面进行了 24 组布局检查，未发现横向溢出。宽屏与窄屏已目视
检查；抽查浅色正文、状态和脚注对比度为 5.56–7.06，浏览器未记录脚本错误。

HTML 形态与 JavaScript 语法检查通过。Impeccable 检查器因缺少 HTML
解析依赖退回正则模式并返回空列表，它不构成完整无缺陷结论；浏览器和
计算样式核对单独记录。未启动新模型评测，未新增安装或产品应用回执。

继续阅读：[用户需求](requirements/PAWOS_REQUIREMENTS_284_291.md) ·
[当前 Lab 工作文档](LAB_GOLDEN_WORKFLOW_20260905.md) ·
[状态账本](PAWOS_REQUIREMENT_STATUS.md) · [文档索引](README.md)。
