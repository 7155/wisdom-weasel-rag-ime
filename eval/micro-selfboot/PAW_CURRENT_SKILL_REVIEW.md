# PAW 当前技能审查 · 2026-09-06

检查依据：用户要求“你检查PAW当前技能是否存在问题，例如边界，流程，使用等等”。

用户随后明确主要检查“询问到验收”那套流程。该范围的主结论与最新 8 个入口核对见 [核心技能流审查](CORE_SKILL_FLOW_REVIEW.md)；本文保留此前更广范围的检查证据，不能用垂直技能的问题代替核心流程结论。

结论：需要修正。发现 **3 处可复现的规则或路由不一致、2 处职责措辞风险**。核心方向已经符合按需使用 Skill、Pi 负责执行、Room 负责协作的边界；不能据此说全部技能没有问题，也不能从这次审查推导 Room 比单 Agent 更强。

本次是源码、已安装技能、当前配置和离线逻辑检查，没有调用付费模型，没有修改被审查的技能、配置或 Runtime，没有安装、提交或推送。它不是模型实际执行全部技能的成功率评测；本文涉及此前参与编写的评测材料，因此也不标为独立第三方验收。

## 范围与固定证据

- 读取了 19 个产品内置技能的入口，追踪了场景路由、Host 加载、普通 Session / Room 职责、初始化和 Trace 验收的相关实现。
- 当前 Gateway 技能目录有 27 项：19 个 bundled、6 个项目简历技能、2 个已启用 Package 技能。后 8 项检查了入口与可达性，没有执行其完整业务流程。
- 初次比对时，19/19 内置 `SKILL.md` 在源码、已安装配置和当前 Runtime Bundle 中一致。08:57 的完整文件快照中，69 个产品包文件有 68 个三方一致；`plugin-creator/SKILL.md` 的源码在检查期间出现新修改，安装配置和 Bundle 仍是之前相同的版本。不能把工作区的新修改算作已安装修复。
- 当前 Bundle 为 `pi-0.84.2-9c3f93c8b1c4-raghost-a70a646b22`。确认安装 Host 确实按 `allowedSkillNames.has(skill.name)` 过滤资源，`skill_load` 从该过滤后的资源中加载。
- 已安装 App 与当前源码中的 `agent_skill_routing.py`、`pi_runtime.py`、`agent_workspace.py`、`agent_execution_policy.py`、`trace_repair.py` 五个文件逐字一致。
- 19 个入口的名称与目录匹配；扫描到的 16 条相对 Markdown 链接均存在。此检查不等于所有代码块中的命令和动态引用都执行通过。

完整私有证据保存在 [skill-audit-20260906](<${PAW_DATA}/EvaluationArtifacts/skill-audit-20260906>)：入口和包文件 SHA-256、实际目录和路由、后端比对、离线探针、测试日志及文件清单。

## 确认的不一致

### F1 · P1 · Trace 技能把当前执行模式做不到的断网沙盒证明设为必要条件

**触发：** 用户确认一个工作区修复，Trace Repair 按技能使用 `control-center-auto-approve-v1` / `full_trust`，随后执行代表性测试。

**证据：** [Trace 技能](../../integrations/pi/skills/trace-agent-diagnostics/SKILL.md:174) 和 [repair-verification.md](../../integrations/pi/skills/trace-agent-diagnostics/references/repair-verification.md:29) 要求 Host 沙盒复测、网络被阻断，否则证据 blocked。相同技能及参考文档又指定全信任配置。

[WorkspaceHarness](../../rag_ime/agent_workspace.py:3709) 在该配置下直接令 `allow_network=True`，即使参数是 `allowNetwork=false`；[命令启动](../../rag_ime/agent_workspace.py:4283) 也使用 unrestricted 路径。离线调用真实 `prepare_command` 得到：

```text
requestedAllowNetwork = false
preparedAllowNetwork = true
preparedUnrestricted = true
commandExecuted = false
```

当前 [Trace 证据投影](../../rag_ime/trace_repair.py:411) 已支持 `sandboxRequired=false`、`sessionTerminalRequired=true`；[接收逻辑](../../rag_ime/trace_repair.py:618) 接受受管执行终态证明，并可返回 `sandboxStatus=not_required`。技能仍把断网沙盒写成所有工作区修复的硬条件，和实际接收契约不一致。

**影响：** 遵守技能的 Agent 可能把 Runtime 已能接受的有效测试判成 blocked；若顺着“已测试”强行写沙盒通过，又会夸大证据。这不是全信任模式本身的缺陷。

**最小修正：** 技能与参考文档应采用当前受管执行回执契约，区分“测试通过”和“断网沙盒通过”。只有任务明确需要隔离复测时，才走能提供该证明的专用执行路径。不要因此给正常修复增加一轮审批。

**验收：** 用真实 WorkspaceHarness 的准备结果连到真实 Trace 证据分类，覆盖全信任测试与隔离测试两种情况；分别验证 `not_required` / `passed`，不能只检查两段文字各自存在。本次没有实际启动修复任务。

### F2 · P2 · Lab 的后续技能引用与场景路由不闭合

**触发：** Lab 评测发现 Memory 问题或需要跨 Session 因果诊断，按 [Lab 技能](../../integrations/pi/skills/agent-eval-room-optimizer/SKILL.md:187) 转交 `memory-curation` / `trace-agent-diagnostics`。

当前实际 Agent Lab 路由以及 Lab Room 组合路由的计算结果：

| 被引用技能 | 当前可直接加载 | 原因 |
|---|---|---|
| `rag-retrieval-optimization` | 是 | 在当前 Lab 路由中 |
| `memory-curation` | 否 | 当前四个场景均未选中 |
| `trace-agent-diagnostics` | 否 | 属于 Trace 私有技能 |

[路由规范化](../../rag_ime/agent_skill_routing.py:83) 对把 Trace 私有技能加入 Lab 返回：`Skill trace-agent-diagnostics belongs to the trace scenario, not agentLab`。已安装 Host 的精确名称过滤也实际存在。这证明当前直接加载路径不成立；没有运行模型来测量其失败频率。

**影响：** 后续动作可能停在不可加载的技能名上，或者由模型自行猜测如何跨 App 转交。场景隔离本身是正确约束，不应通过放开全部私有技能解决。

**最小修正：** 区分当前 Session 可用的方法与显式 App 转交。跨 Session 取证可以优先使用当前可用的 `trace_diagnostics.inspect`；若需要专用 Trace 报告，给出真实 Trace App 入口和证据交接。Memory 则根据已授权用途配置该技能或明确其可用替代路径，并在执行前检查可达性。

**边界：** `memory-curation` 缺省不可加载，不证明自动 Memory 系统坏了。内部 curation Session 使用专门的固定配置，刻意关闭工具和技能；日常 `memory_capture` 也不依赖这个技能。

**验收：** 用真实场景路由检查技能的后续引用；不可达时必须有可执行的替代或转交。不能把“文件里存在这个名字”当成通过。

### F3 · P2 · 项目初始化的正式说明与自动触发条件不同

[OUTCOMES.md](../../OUTCOMES.md:95) 声明新项目只在用户调用 `/init` 时初始化；但 [bootstrap 技能](../../integrations/pi/skills/bootstrap-project-context/SKILL.md:3) 允许 Runtime 发现缺少根指南时触发，且 [system prompt 构造](../../rag_ime/pi_runtime.py:226) 会在缺少 `AGENTS.md` 的项目中注入“先加载 bootstrap 并在授权允许时创建”的指令。

**离线复现：** 临时空目录、`projectContextEnabled=true`，没有 `/init` 输入，真实函数仍返回上述初始化指令；将 project context 关闭后不再返回。探针自身没有创建 `AGENTS.md`，Session 创建函数也没有直接写文件。

**影响：** “什么时候初始化”对用户和 Agent 有两套答案，普通修改任务可能额外进入初始化流程。根 AGENTS 与技能目前允许缺失时初始化，因此不能简单认定一切自动初始化都是越权。

**最小修正：** 统一现有根指南、Outcome、Skill 和 Runtime 的触发契约：要么明确保留缺失指南时的有界初始化，要么让 `/init` 成为唯一触发。当前这是一项可复现的规则矛盾，不是已观测到的未授权写入。

**验收：** 覆盖显式 `/init`、普通项目任务缺少指南、已有指南、project context 关闭四类入口，并让文档声明与断言一致。

## 职责与流程措辞风险

### F4 · P2 · 通用执行技能没有明确区分主 Agent 与受委派 Agent

[test-driven-implementation](../../integrations/pi/skills/test-driven-implementation/SKILL.md:18) 无条件写“更新 worker 文档、交给 supervising Agent、不要声明整个 Goal 完成”；[systematic-debugging](../../integrations/pi/skills/systematic-debugging/SKILL.md:20) 也采用 supervisor 收口措辞。它们同时属于普通 Session 的通用技能。

受委派 Agent 应把证据交回主 Agent，这个边界正确；普通 Session 的主 Agent 自己加载技能时，却不存在额外的 supervising Agent。文案也没有注明仅在已分配 worker 文档时更新。

**风险：** 主 Agent 可能多造文档、等待不存在的上级，或只交回阶段结果。本次没有模型行为证据证明它必然发生，所以不计为已复现的执行故障。

**最小修正：** 增加明确的角色条件：主 Agent 验证并向用户完成收口；受委派 Agent 返回 `AgentResult`，不替主 Agent结束整个任务；已有负责文档时才更新。无需另造一个“验收技能”。

### F5 · P2 · 架构改善技能仍引用过时的 Grill 交接产物

[improve-codebase-architecture](../../integrations/pi/skills/improve-codebase-architecture/SKILL.md:60) 把未决 module shape、seam、surviving-test 或产品取舍转到 explicit Grill Mode，并要求携带 `Domain Language Delta`。当前 [alignment-and-decision](../../integrations/pi/skills/alignment-and-decision/SKILL.md:12) 只要求解决影响范围、验收、权限、兼容、成本或可见行为的重要用户选择，其输出没有 `Domain Language Delta`。

**风险：** 架构选项已经被用户选定后，普通实现细节仍可能被再次拿去 Grill；规划阶段也可能等待上游不会产出的字段。末句“没有重要选择时可直接规划”已有缓解，但前面列举和旧输出名仍不一致。

**最小修正：** 直接引用 alignment 当前的触发边界和输出；只有重要用户选择未决或用户明确要求 Grill 时提问。不要因模块内部形状本身而强制再问一轮。

## 已确认合理的边界

- [D-004](../../DECISIONS.md:41) 已经明确废除强制执行、质量、审查、交接、归档流水线；简单任务可以不使用工作流技能，review 是可选方法。
- `orchestrate-session` 与 `facilitate-room` 区分私有辅助结果和用户可见的独立责任。没有证据支持“凡复杂任务都必须 Room”或“每步都多 Agent”。
- Room Partner 虽能看到 Room 场景技能，实际修改成员、验收派发和发布唯一 `kind=result` 仍有 Facilitator / accountable owner 检查。仅凭技能可见性不能判为权限穿透。
- WorkDocument 与 Runtime 状态在根契约中分离；文档是可选语义证据，不能用 Markdown 代替正在运行、完成、取消或验收的判断。
- Session 的技能列表在打开时保留资源快照；后续改设置不会自动改写已有 Session 的加载集合。这是稳定会话语义，排查“改了设置但没生效”时应先核对绑定快照。
- 项目简历技能保留了事实来源、待确认指标、母版保护和不默认提交等边界；此次没有执行生成 PDF / Canvas、外部包安装或真实数据业务任务。

## 使用时容易误解的地方

当前目录中这 9 个名字未出现在四个场景的现有选择里：`memory-curation`、6 个项目简历技能、`session-workflow`、`zhanggui-wenshu`。目录中的 `installed/enabled` 与 Session 的有效技能路由是两回事。不要看到“已安装”就指示当前 Session 直接加载；也不能据此断言相关底层工具或整个 App 不可用。专用 App 的其他正文注入路径未在本次做运行验收。

`plugin-creator` 的源码在本次检查期间改变了确认/应用流程，而安装副本仍是旧版。这属于正在变化的安装差异，未当成这次已修复事项。审查修复时必须同时确认技能与 Tool 的实际调用契约，单独同步文字不足以验收。

## 验证记录与修复顺序

现有聚焦检查 **15/15 通过**，耗时 10.796 秒：场景路由 2 项、Lab 技能 3 项、Trace 技能 2 项、RAG 技能 1 项，以及初始化 2 项、Runtime 技能传递/快照/Memory profile 3 项、Host overlay 1 项、全信任命令准备 1 项。详见 [focused-tests.log](<${PAW_DATA}/EvaluationArtifacts/skill-audit-20260906/focused-tests.log>)。

新增离线探针覆盖了路由后续引用、Trace 命令准备与证据分类、无 `/init` 时的初始化指令。探针没有发送模型请求或执行 Shell 测试命令；其中模拟回执只用于调用真实分类函数，不能作为真实修复成功证据。详见 [offline-probes.json](<${PAW_DATA}/EvaluationArtifacts/skill-audit-20260906/offline-probes.json>) 和 [可重跑脚本](<${PAW_DATA}/EvaluationArtifacts/skill-audit-20260906/offline-probes.py>)。

建议先修 F1 和 F2 的实际衔接，再统一 F3 的初始化契约，最后收紧 F4/F5 的角色与提问条件。随后用少量有明确终点的小任务检查触发与收口，再测一个中等规模任务的持续执行；本次不新增 token 成本或成功率收益数字。

本次状态：审查完成，修复未实施。运行逻辑可复现与模型任务表现仍是两种证据，不能互相替代。

Public source note: `${PAW_DATA}`, `${PAW_STORAGE}`, `${CODEX_HOME}` and `${PI_WORKTREE}` denote private machine-local evidence roots; these artifacts are not bundled in this repository.
