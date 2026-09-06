# 询问到验收：PAW 核心技能流审查

日期：2026-09-06。当前核对点：09:08，Asia/Shanghai。

用户本次澄清：“技能主要是指询问到验收那一套的例如边界，流程，使用等等”。本报告据此收敛到 7 个核心方法，加上文档整理的旁路：alignment、planning、debugging、implementation、Session 编排、Room 协作、independent review，以及 organize-work-documents。Lab、Trace、Memory、App 等垂直技能不作为本报告的主要结论。

**结论：主流程的责任划分已经合理，但两处作用范围仍应写清楚：通用执行技能的主 Agent / 子 Agent 边界，以及跨阶段选用技能的边界。没有发现需要恢复强制 Grill → 规划 → 执行 → 独立审查流水线的理由。**

这两处属于有源码依据的指令歧义，没有测出它们导致任务失败的频率。此次完成检查和报告，未修改技能、Runtime 或设置，也没有调用付费模型。

## 每一步应如何使用

| 环节 | 什么时候用 | 谁负责 | 退出条件与下一步 |
|---|---|---|---|
| 询问 / alignment | 查完事实后，仍有影响范围、验收、权限、兼容、成本或可见行为的重要用户选择；或用户明确要求 Grill | 当前主 Agent；受委派者只解决被分配的问题 | 重要选择已解决，继续已授权工作；用户只要求讨论时，交付讨论结果即可 |
| planning | 跨多个步骤、责任边界、共享契约或集成点，规划确有价值 | 主 Agent 可自己规划，也可使用有界只读规划子任务 | 得到可执行项、依赖、验收与集成顺序；任务包含实施时继续实施，不把计划当完成 |
| debugging | 原因尚无可复现证据 | 当前负责该问题的 Agent | 定位原因；有界且已授权时修复并复验，否则返回证据和阻塞点 |
| implementation | 已知行为、负责位置和有意义的可执行检查 | 当前实施者 | 获得改动与验证证据；主 Agent 收口，子 Agent 提交结果 |
| orchestrate-session | 私有辅助结果确有收益；一个专家子任务也可以 | 父 Session | 父 Agent 集成并验收所有相关子任务，给出最终结果 |
| facilitate-room | 多个结果需要在 Room 中独立可见、负责和交接 | 指定 Facilitator；普通 Partner 不使用此技能 | Partner 提交后由 Facilitator accept/return；职责闭合后发布一个 Root 结果 |
| independent-review | 用户要求独立复核，或风险值得独立复核 | 未参与该固定结果编写的 Reviewer | 返回固定范围的裁决与证据；主 Agent 决定返修、重新验证和最终验收 |
| organize-work-documents | 明确需要需求、证据、结果和交接记录，或后台整理 | 已分配文档责任的 Agent | 维护语义记录与来源；不决定 Runtime 状态，不成为普通任务的强制步骤 |

验收不是一定要再调用一个 Skill。主 Agent / Facilitator 始终对“真实路径能运行”和“结果满足当前精确需求”负责；独立 Reviewer 只提供另一个固定范围的判断。

## C1 · P2 · 通用任务技能仍沿用了无条件的 worker / supervisor 收口措辞

**位置：** [test-driven-implementation 第 18 行](../../integrations/pi/skills/test-driven-implementation/SKILL.md:18)、[systematic-debugging 第 20 行](../../integrations/pi/skills/systematic-debugging/SKILL.md:20)。

实现技能要求更新 owned worker document，把未通过验收的结果交给 supervising Agent，并且不要声明整个 Goal 完成。排错技能也要求更新 worker 文档，不替 supervising Agent 作终态声明。

这些约束适合受委派 Agent；但是两份技能也通过普通 Session 路由供主 Agent 自己使用。文本没有明确注明“被委派时”及“存在已分配文档时”。主 Agent 处理一个完整且有界的修改，可能既是实施者，又是任务的最终负责人。

**风险：** 把阶段性结果交给一个不存在的上级、结束在“请主管验收”，或为了满足文案多建 worker 文档。当前主提示已有主 Agent 负责最终结果的规则，因此不能断言这些行为一定发生；需要消除的是局部技能和主职责之间的歧义。

**建议：** 保留同一套任务方法，补上两个条件：

```text
被委派时：提交 AgentResult，由父 Agent / Facilitator 集成验收；不结束整个任务。
作为主 Agent 时：核对原请求与实际证据，完成已授权范围并向用户收口。
已分配负责文档时才更新该文档；否则直接返回证据，不额外造文档。
```

**验收用例：** 同一个小修复分别由普通主 Session 与一个有界子任务执行。前者能直接完成用户目标，后者只提交自己的范围；两者都不因为没有 worker 文档而停住。

## C2 · P2 · “最多两个技能”和阶段性只读约束没有明确作用范围

**位置：** [共享 capability policy 第 10–18 行](../../rag_ime/agent_templates.py:10)、[alignment 的阶段边界](../../integrations/pi/skills/alignment-and-decision/SKILL.md:40)、[planning 的返回规则](../../integrations/pi/skills/implementation-planning/SKILL.md:32)。已安装 App 的共享 policy 与当前源码一致。

共享提示写“最多两个互补 Skill”，但没有说明是当前阶段的职责组合，还是整个 Session 累计只能加载两个。与此同时，已安装 Host 会记住已经加载的技能及正文；逐步完成的问题可能自然经历 alignment、planning、implementation，Room 还可能需要一个职责技能。

alignment 与 planning 不实施、不派发的约束，在它们自己的阶段内是正确的；当前文本没有显式说明阶段结束后由同一个主 Agent 继续已授权工作时，这些限制只约束此前的方法阶段。

**风险：** Agent 可能把“少加载”理解成累计数量硬限制，或把规划阶段的只读边界延伸到整个任务。共享 policy 已写“计划不算完成”，这是缓解；本次也没有发现 Runtime 实际拒绝第三个技能的硬闸。因此这是指令作用范围不清，不是已复现的第三次加载错误。

**建议：** 将数量限制表达为当前工作阶段选择最少必要、互补的方法；允许需求变化后按需转入下一阶段。阶段结果不等于用户任务完成，是否继续由原请求和剩余验收条件决定。无需新增流程状态机、技能卸载工具或一次一确认的开关。

**验收用例：** 一个已授权实施的跨边界小任务先解决一个重要选择，再规划、实施并验证，能够在同一主 Session 连续完成；对照“只给计划，不改代码”的请求则应停在计划交付。不能只用“没有加载第三个技能”作为优化目标。

## 核心之外的相邻入口

`improve-codebase-architecture` 的 [第 60–63 行](../../integrations/pi/skills/improve-codebase-architecture/SKILL.md:60) 仍让未决模块形状 / seam 转入 explicit Grill，并引用 alignment 当前输出里没有的 `Domain Language Delta`。这不是核心 alignment 自己的问题，但从架构建议进入这套流程时可能多问或等待旧产物，应一起清理该调用方。

旧 Codex `grilling` 是另一个宿主的单独入口，不等于 PAW 当前正式路由的 `alignment-and-decision`。检查时不能因名称里有 Grill 就实际启动追问，也不能把旧 Codex 文件的行为当作已安装 PAW 的行为。

## 目前已经合理、应保留的部分

- **询问有门槛。** 能查看的事实先查看；授权范围内的可逆默认直接采用。重要用户选择才问；显式 Grill 才逐个重要分支讨论。当前规则没有要求每项修改都先确认。
- **规划不越过派发责任。** 规划描述可执行项、依赖和验收，不凭计划文字创建真正的 Agent / WorkItem。简单改动可以跳过规划。
- **排错与实现按已知程度分流。** 未知原因先拿复现证据；已知行为直接选择合理的实现和测试方式，不强制每次跑两遍流程。
- **多 Agent 按结果责任选择。** 私有辅助归父 Session，用户可见独立责任归 Room。并行要有独立工作和实际收益，不按前端、后端、测试标签机械拆人。
- **作者验证、独立审查、最终验收分开。** Reviewer 不改被审对象、不分配返修、不替主 Agent 发最终答复；当前已安装 review 还明确禁止把重要证据未复现的结果写成 clear/passed。
- **子任务完成不等于验收。** Room 提交进入 review，accept/return 需要当前 revision、两条验收结论与证据；失败提案不能无新证据直接改成通过。
- **失败继续同一职责。** 按当前 Runtime 操作重试或返修，不新建替代项掩盖失败；等待超时也不意味着取消。
- **文档不成为前台障碍。** WorkDocument 可保留需求与证据，不能替代 Runtime 状态；同步 pending 不阻断非文档交付。

这些规则来自当前 [D-004](../../DECISIONS.md:41)、[共享 policy](../../rag_ime/agent_templates.py:8)、[Room 技能](../../integrations/pi/skills/facilitate-room/SKILL.md:19) 及实际 Room 行为测试。

## 验证记录

09:08 的新快照确认本报告的 **8/8 个入口在源码、安装配置、当前 Runtime Bundle 中逐字一致**，因此上述核心问题不能归咎于这三处副本没有同步。最新 [快照](<${PAW_DATA}/EvaluationArtifacts/skill-audit-20260906/core-flow-snapshot.json>) 保存各文件 SHA-256。

相关检查 **20/20 通过**，耗时 17.918 秒，覆盖 Room 提示的角色分工、提交不是验收、明确双轴证据和 revision、失败返修与 superseding evidence、文档同步 pending、显式 accept 以及产品技能打包契约：

```bash
python3 -m unittest \
  tests.test_agent_room_prompt_budget \
  tests.test_agent_room_work \
  tests.test_agent_room_partner_application.RoomPartnerApplicationTest.test_completed_work_stays_in_review_until_facilitator_decides \
  tests.test_agent_room_partner_application.RoomPartnerApplicationTest.test_completed_work_submits_when_document_sync_is_pending \
  tests.test_agent_room_partner_async_application.RoomPartnerAsyncApplicationTest.test_accept_maps_public_work_item_id_and_records_explicit_review \
  tests.test_build_managed_pi_runtime_v2.ManagedPiRuntimeV2BuildTests.test_product_owns_all_managed_skills -v
```

详见 [测试日志](<${PAW_DATA}/EvaluationArtifacts/skill-audit-20260906/core-flow-tests.log>)。日志有测试夹具的 SQLite `ResourceWarning`，无测试失败；本次未扩大为数据库资源清理任务。

这些结果证明相关提示契约和 Runtime 分工检查通过，**没有证明真实模型已经完整走过询问到验收，也没有证明不会多问或中途停住**。后续行为验收用少量有明确终点的案例即可：直接小修复、只给计划、询问后继续实施、单个私有子任务、Room 返修后验收。记录是否多问、是否跳过必需检查、是否重复派发、最终完成归谁，再比较收益；不必先跑大规模多 Agent 任务。

本次交付：限定范围的审查完成；上述措辞修正与行为验收尚未实施。

Public source note: `${PAW_DATA}`, `${PAW_STORAGE}`, `${CODEX_HOME}` and `${PI_WORKTREE}` denote private machine-local evidence roots; these artifacts are not bundled in this repository.
