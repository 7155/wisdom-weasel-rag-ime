# Grill 到验收：当前技能流核对

日期：2026-09-05。范围固定为仓库七个核心方法、Codex 本地对应副本、已安装 PAW 的配置目录与 bundled Skill，以及 `agent_skill_routing.py`。这是既有技能流的只读审查，没有改写 Skill。

## 需求与判断

用户原话：“顺便看看，我们的技能流有没有问题，就是grill到验收的我们自己做的技能流”。同时沿用本任务“小任务、token 不够、为了简历数据、OS 自举”的限制。

结论：PAW 当前设计方向正确，不应恢复成每次必走 Grill→规划→执行→独立审查的固定流水线。D-004 已明确按需路由：简单工作可以不用流程 Skill，父 Session 保留完成权。

正确的最短路径是：有重大未决选择才 alignment/Grill → 多边界修改才 planning → 原因未知才 debugging → 已知行为才 implementation → 作者做相应验证 → 有独立复核需求或风险才 independent-review → 父 Session 对原需求与实际运行分别收口。

## F1 · Codex 本地副本与 PAW 当前方法不同（应修正的同步问题）

本轮读取七份仓库、Codex、安装配置、安装 bundle：

- 仓库与已安装 PAW：七份全部一致。配置目录和 bundled 目录分别核对，不把源码存在当安装证据。
- 仓库与 Codex：alignment、debugging、implementation 相同；planning、independent-review、orchestrate-session、facilitate-room 不同。
- Codex `orchestrate-session/SKILL.md` 第 3、17、28 行附近偏向必须多个子 Agent 批量派发，明确排除单子任务委派；仓库新版第 3、17–19 行允许一个确有收益的专门子任务。相同任务在两个宿主可能得到不同人数与上下文开销。
- Codex independent-review 缺少仓库第 26 行的“重要证据未复现，不得给 clear/passed”补充；通用核验约束仍在，不能说旧版完全允许虚假验收。

建议把仓库作为这七个 PAW 方法的权威源，通过已有 Skill 分发流程逐份同步 Codex；保存差异与回滚，不能重装全部个人 Skills。这次用户只要求检查，因此未覆盖本地副本。

## F2 · 旧 grilling 与 alignment 是两种入口，不宜混用（适用性风险）

Codex `${CODEX_HOME}/skills/grilling/SKILL.md` 第 8 行要求一轮提出整个就绪问题集合，第 20 行要求为可查事实派子 Agent，第 22、27–28 行要求确认共同理解。PAW alignment 第 13–18 行则先查事实、应用可逆默认，只在显式 Grill 时逐个重大分支等待。

PAW 当前 `agent_skill_routing.py` 的通用默认列表包含 alignment，没有 grilling。因此这不是已安装 PAW 自动强制 Grill 的证据，而是 Codex 显式调用旧 grilling 时可能多问、多派发的风险。旧文末 P0/P1 限制已缩小追问范围，不能断言它必定穷举全部 P1/P2 分支。

建议普通实现沿用 alignment；grilling 保留为用户明确要压力讨论时的入口。不要因为提到“检查 Grill 技能”就实际启动追问流程。

## F3 · 小预算需要放进任务合同（改进建议，不是已证实缺陷）

核心方法要求 bounded TaskBrief，但没有统一的模型调用/输入输出数值预算；Lab optimizer 已有 budget、maxCandidates、停止条件，并注明 agent_observed 不等于 Host 硬限额。把数值上限放在本次任务单与执行入口即可，不应让所有 Skill 都再复制一套预算状态机。

本次 micro suite 采用最多六次完成请求、一次候选、768 单次输出上限，以及结算后 20k token 停止阈值。它不是输入 token 的实时硬闸。失败样本保留，不无限重跑来制造全绿。

## 验证与边界

本次真实小实验还暴露了两个必须由最终验收纠正的问题：模型诊断正确不代表修复后的候选已通过；最后一条 assistant usage 不代表完整 turn 的模型成本。已有 Room 错误候选被固定 verifier 拒绝；主 Session 按真实 transcript 全 turn 对账后，将费用候选从 quality-only Keep 解释为 no-improvement。这支持保留父 Session 的最终核对责任，而不是再增加一个强制 Skill 阶段。

- `python3 -m unittest tests.test_agent_skill_routing tests.test_agent_eval_room_optimizer_skill tests.test_trace_agent_diagnostics_skill`：7 项通过。
- 检查覆盖场景隔离、Skill 必要合同和修复权限的源码测试，不能替代真实 Agent 完整执行 Grill→验收的行为评测。
- 独立审查方法的已有规则正确区分“能运行”和“满足需求”，也禁止作者自称独立审查。Lab/Trace 的模型判断不能代替宿主验收器；修复后需要新回执。
- operability：静态分发与路由已核对，端到端 Skill 行为未全面复验。
- requirement satisfaction：已完成用户要求的技能流问题核对；没有宣称技能流绝对无缺陷。

相关事实源：[D-004](../../DECISIONS.md#d-004--skills-are-conditional-methods-not-a-pipeline)、[alignment](../../integrations/pi/skills/alignment-and-decision/SKILL.md)、[planning](../../integrations/pi/skills/implementation-planning/SKILL.md)、[review](../../integrations/pi/skills/independent-review/SKILL.md)、[routing](../../rag_ime/agent_skill_routing.py)。

Public source note: `${PAW_DATA}`, `${PAW_STORAGE}`, `${CODEX_HOME}` and `${PI_WORKTREE}` denote private machine-local evidence roots; these artifacts are not bundled in this repository.
