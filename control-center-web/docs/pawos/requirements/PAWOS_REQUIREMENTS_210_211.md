# PAWOS 用户需求账本 · UR-210–UR-211

> 导航：[UR-209](PAWOS_REQUIREMENTS_209_209.md) · [总索引](../PAWOS_REQUIREMENTS.md) · 下一份：[用户逐字证据](PAWOS_REQUIREMENT_EVIDENCE.md)
>
> `current` 只表示当前控制语义，不表示实现完成。实施状态与证据见
> [PAWOS_REQUIREMENT_STATUS.md](../PAWOS_REQUIREMENT_STATUS.md)。稳定编号、来源、修正关系和原话不得因拆卷而改写或丢失。

### UR-210 — Extension App 可以显式选择受管沙箱执行

- **状态 / 优先级：** `current / P0 self-hosting safety`
- **真实需求：** 创建 Extension App 时可以声明沙箱能力，App 在创建实验或运行
  候选任务时可以显式选择是否使用已经安装并启用的受管 Sandbox Connector。这个
  选择属于 App 的运行配置，不把业务 App 塞进通用 Agent 界面，也不让 App 自己
  实现第二套进程、Tool loop、Trace 或隔离 Runtime。
- **所有权解释：** App 负责展示选择、实验参数和结果；App-owned Session 负责本次
  对话与任务；PAW/Pi Runtime 负责真正创建、停止和回收沙箱，并发布
  `SandboxRun`、Trace 与 Eval 收据。选择“不使用沙箱”不得扩大 Host 权限；需要
  写入、构建或执行候选代码的实验必须保持在已授权的受管边界内，否则明确不执行。
- **版本与可复现性：** 使用沙箱时，App 版本、Sandbox Connector/profile、workspace
  binding、网络/写入策略、预算和 Stop 边界必须形成不可变运行快照，并能从实验结果
  回跳查看；插件不可用、版本不匹配或收据缺失必须成为可见失败，不能静默切换到
  Host 直接执行。
- **依赖 / 复用：** 复用 `UR-176` 的受治理 workspace/network/budget/Stop 边界、
  `UR-178`/`UR-192` 的 Pi Package Connector 生命周期，以及 `UR-207` 的
  Extension App 自举与安装合同；不新建平行插件市场、Loader 或 SandboxRun。
- **完成态证据层级：** 至少需要 E1 App/Runtime 选择合同与唯一 owner，E2 选择、
  缺失 Connector、Stop 和收据绑定回归，E3 生产构建，E4 安装 App 与 Connector，
  E5 真实 `SandboxRun`/Trace/Eval 读回，以及 E6 在已安装 App 中选择沙箱并完成一轮
  可见实验。
- **原话依据（无损转录）：**

  > 我的意思是创建APP，然后它能够选择使用沙箱吗？

  来源：当前任务，2026-08-31；稳定 message/turn ID 在当前 Codex 文档环境未
  暴露，不能伪造。

### UR-211 — RAG 实验 App 逐轮冻结、可比选优并受控晋升

- **状态 / 优先级：** `current / P0 RAG self-optimization`
- **真实需求：** 为本项目的 RAG 优化建立独立 Extension App，而不是把实验面板
  混进通用 Agent。App 负责选择语料/索引版本、数据集与切分、参数搜索空间、模型、
  预算和指标，反复创建冻结实验，在同一可比合同下找出更优参数，并用 Trace/Eval
  展示为什么胜出、改进多少和在哪些样例上退化。
- **冻结合同：** 每轮执行前冻结 corpus/index revision、输入与 ground truth split、
  baseline generation、候选配置、模型与推理参数、随机种子、evaluator/metric、
  沙箱策略和预算。任一冻结字段变化都必须产生新轮次，禁止改写已经运行的结果或把
  不同合同的分数直接比较。
- **选优与晋升：** 结果保留 winner、rejected candidates、逐指标差异、失败案例及
  SandboxRun/Trace/Eval 身份。winner 仍只是候选配置；写入 active RAG/profile 前
  必须显示影响预览、获得显式确认，并保留当前 active generation 作为 rollback
  target。拒绝、取消、失败或沙箱不可用都不能改变当前生产配置。
- **不得做：** 不得让 AI Judge 成为唯一权威；确定性指标、人工问题/答案或 ground
  truth 与 AI Judge estimate 必须分栏。不得用 fixture 分数冒充真实生产效果，也
  不得把“最高总分”掩盖为某个关键指标或安全边界的回退。
- **完成态证据层级：** 至少需要 E1 独立 App、冻结合同和 promotion owner，E2 同
  合同比较、不可比拒绝、失败不写入和回滚回归，E3 生产构建，E4 App/Skill/Connector
  安装，E5 真实多候选 SandboxRun/Trace/Eval 与 promotion receipt，以及 E6 已安装
  App 中完成“建实验—冻结—运行—比较—确认或拒绝晋升”的前台闭环。
- **原话依据（无损转录）：**

  > 本项目如果要做，就是Agent这个rag的沙盒优化，这是一个rag项目。AG怎么让它就是选取最好的参数，就是在同一个，就是它反复冻结嘛，然后来项目实验。那这个是在本项目的话，是建立一个新的APP，还是就在Agent里面就能使用沙盒？

  来源：当前任务，2026-08-31；稳定 message/turn ID 在当前 Codex 文档环境未
  暴露，不能伪造。

### 来源覆盖审计 · UR-210–UR-211

| 当前任务可见用户原话 | 映射 | 分类 |
| --- | --- | --- |
| “我的意思是创建APP，然后它能够选择使用沙箱吗？” | `UR-210` | App 的沙箱选择面与 Runtime 权限边界 |
| “本项目如果要做……它反复冻结嘛，然后来项目实验……建立一个新的APP，还是就在Agent里面就能使用沙盒？” | `UR-211` | 独立 RAG 实验 App、冻结实验和参数选优 |

**覆盖结论：** 两条直接用户原话均已映射。Sandbox Connector/profile、冻结字段、
promotion 与 rollback 是为了让原需求可执行和可验收的解释层，不冒充用户逐字原话。

## 继续阅读 / 编辑

- 下一份：[用户逐字证据](PAWOS_REQUIREMENT_EVIDENCE.md)
- 实施状态：[PAWOS_REQUIREMENT_STATUS.md](../PAWOS_REQUIREMENT_STATUS.md)
- 总入口：[PAWOS_REQUIREMENTS.md](../PAWOS_REQUIREMENTS.md)
