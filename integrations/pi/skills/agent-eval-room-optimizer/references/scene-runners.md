# 实际业务 Runner 与候选装载

这些入口执行真实业务工具或记忆管线，不生成候选，也不接管 Pi 的模型与 Tool loop。
输入由本机已绑定的场景资产提供；不要从公开展示快照猜测私有路径或 Gold。
每次使用独立输出目录。只有报告和 Host verifier 能判定结果，退出码 0 本身不是质量通过。

| 场景 | Runner | 通用 Prompt 候选 | 判据 |
| --- | --- | --- | --- |
| EnterpriseOps | `scripts/run_enterpriseops_csm_eval.py` | `--candidate-prompt-file`，Validation | 原任务、seed、Tool catalog 与 SQL verifier；需要本机 Gym |
| CloudOps | `scripts/run_cloudops_agent_eval.py` | `--candidate-prompt-file`，Validation/development | 12 题/3 批、固定 blind suite、Host scorer |
| Enterprise RAG | `scripts/run_rag_agent_ablation.py` | `--candidate-prompt-file --answer-only --development-only --evaluation-split validation` | 独立 Judge、逐事实引用、拒答、Tool/终态 |
| Memory | `scripts/eval_personal_memory_luna.py` | 固定现有 Prompt contract；没有通用 Prompt 文件入口 | shadow 整理、召回、拒记、回滚与 replay |

Prompt 文件只包含本轮通用指令，最多 16,000 UTF-8 字节。它追加到冻结业务合同后；
不会替换任务、Tool 权限、Host Gold 或 verifier。报告的 `candidatePrompt` 表示实际
装载内容身份，逐任务 Prompt 身份来自实际提交文本。禁止把一个数据集的答案写入候选文件。

RAG 将业务模型 `--model-override` 和评审模型 `--judge-model` 分开固定。新的默认
Judge 是 Sol；历史报告可能让 Judge 随业务模型切换，不能把历史记录改称固定 Judge。
任何跨模型结论都需在同一评审模型、题集和标准下重新运行基线/候选。

RAG 的 `--scene-recipe` 固定原方案。追加 Prompt 文件时，回执使用
`conditions.parentSceneRecipe` 与 `conditions.candidatePrompt`，表示从原方案派生；
原方案复跑使用 `conditions.sceneRecipe`。模型候选使用显式模型和冻结的其余参数，
结果另行绑定原 recipe 与 baselineRunId，不能覆盖已登记版本。

成本导出支持 `scripts/build_agent_lab_cost_receipt_from_runtime_db.py --all-models`，
各模型分别计价后合计，包括失败请求。它输出明确的 multi-model 回执，而不是单模型
总 token 乘一个价格。价格或 usage 不完整时保留运行目录，修正后重算回执即可；不要重跑
已经完成的付费请求。RAG 断点复用的旧 lane 和本次新执行不在同一个 DB，未合并旧回执前
不能导出整轮成本。费用仍是 Runtime 用量估算，不是 Provider 账单。

CloudOps 的文件候选比较器核对同一业务、scorer、Runtime、模型、Prompt 基体、Tool
和其他冻结控制，再比较质量与 usage。EnterpriseOps 旧 Held-out promoter 尚不接收
文件候选；这不影响 Validation，但不能跳过晋升合同。

Tool/Skill/Workflow 实现候选需在独立源码副本真实修改、执行对应 Tool fixture 或
回归，然后再运行同一业务 suite；上述 Prompt 参数不能被描述为任意 Tool/Skill 装载接口。
Memory 的旧 CLI transport 是评测适配器；接 resident Pi 时必须保留真实 Session/turn
结算身份，不得把 `private-luna:*` 的历史审计 ID 当作 Pi turn 回执。
