# Agent Lab 通用工作台与应用交付验收 · 2026-09-07

本轮按 [LP-S14–LP-S16](requirements/PAWOS_REQUIREMENTS_292_297.md#lp-s14) 实现并操作了真实产品前端：两个新项目分别形成售后应用与交互式服务依赖图；售后项目完成材料、标准、校准、冻结、对照、修整及两个运行目标的应用交付。项目结构由 Agent 决定，平台没有增加统一业务目标表或强制 Golden 阶段。

验收环境是隔离的源码 Gateway、候选 Pi Runtime 和真实 Chromium 浏览器。独立应用在另一目录、另一服务进程中启动。浏览器操作由 Codex 执行，业务判定由 Codex 作出；这不是独立人工标注、生产用户试验、另一台物理机器或全局已安装原生 PAW 的验收。本轮没有提交、推送、部署或替换原生安装。

## 1. 已交付的产品行为

| 用户工作 | 当前行为与实际验证 |
| --- | --- |
| 带着描述或材料开始 | 通用项目入口接收描述、本机文本路径与上传文本文件；保存实际读取内容、来源、缺口和版本。两个新项目均由前端创建。 |
| Agent 组织不同结果 | 每个项目拥有普通 Pi Session；成果可为文档、表格、表单、代码、JSON 或隔离 HTML。售后与依赖图没有复用同一种业务表单。 |
| 持续修正 | 项目说明、材料、成果、应用保留版本；本地草稿、当前项目、成果页面与对话展开状态可恢复。项目切换后完整刷新仍打开正确项目。 |
| 准备与比较 | 可选 `golden.context_qa` 绑定复用真实执行 owner；Guide 可以读取绑定、发起受支持命令，人工审核/标签仍通过对应前端操作。 |
| 实际应用交付 | 同一冻结实现可试用、添加到 PAW、选择版本、回滚、下载 PAW 包和独立包；两个目标均完成真实模型咨询。 |
| 故障与恢复 | 未确认命令保留原身份并核对原请求；应用历史保留原输入、版本、时间、结果。独立服务重启不会自动重放未知调用。 |
| 保持执行归属 | `lab_project` 只面向实际绑定的项目 Guide；读取摘要也限定本项目，用户 UI 仍可列出自己的项目。App 调用结果取自 Pi settlement；Agent 文字不设置作业完成状态。 |

首版独立运行器支持声明的文本生成操作，使用 Python 标准库和目标环境提供的 OpenAI-compatible 凭据。任意本地命令、真实订单写入、任意外部工具、外部知识库连接和多租户云部署不在本轮可运行交付范围。PAW ZIP 的迁移方式是解包到新 Lab 项目执行目录再准备应用，未声明已有原生一键导入器。

## 2. 售后项目与真实对照

材料是本轮新编的《松果设备售后规则》，包含 7 条规则，涉及标准耳机、标准键盘、定制键帽、期限边界、运费缺口与实际业务动作边界。材料是合成业务资料，不来自真实订单。

- 项目：`lab-project-b581de4703264465be9dba8e663a05e5`。
- Guide：`agent:0f569e77-d687-42e5-884c-1e090ef3fbfa`。
- 材料 SHA-256：`e893c728d6c00fb560aa6c5d36ebf411aacde324904c6ef294a0807bf95eff43`。
- 题集：12 题，development 8 题、候选固定后的验证 4 题；校准样本 24 条。
- B0 使用完整规则与明确输出要求；C1 增加事实提取、逐条规则检查等方法指令。B0/C1 原始方法、输出与判定均保留。

第一轮真实对照使用旧评审协议，共 48 次调用。其评审提示把“评审证据应逐字引用”与“业务回答是否必须逐字引用”混在一起，部分判定因此偏离业务 rubric。旧回执没有重写；修正位置是评审协议，不把这类变化计作候选改善。

新协议 `paw.golden.context-qa-judge.v2` 明确评审引用与业务答案要求的区别。旧协议校准需要重新校准并冻结新版本后才能开始付费实验。复用原 24 个 Codex 标签重新校准：23/24 一致，1 条 false-fail、0 条 false-pass、0 条无法核对；该分歧仍保留，没有看结果后改标签。95.83% 是这一组样本上的一致率，不能推广为通用评审可靠性。

第二轮快照：`golden-snapshot:4b7e6a44-6908-410d-a9f8-71844845f6e3`。实际作业：`golden-job:53a8a527-9706-4627-b836-e96d4753f6eb`。

| 第二轮结果 | B0 | C1 |
| --- | --- | --- |
| Development，8 题 | 8 通过 | 7 通过、1 无法核对 |
| 固定候选后的验证，4 题 | 4 通过 | 4 通过 |
| 采用结论 | 保留原版的比较结论 | 不能确认改善 |

C1 的一条评审引用不能与原资料精确核对，保留为 uncertain。两轮正式比较均为 **inconclusive**，不报告质量或费用收益。第二轮的 4/4 验证题与前轮重合，服务记录 `ordinal=2`、`reused=true`、`overlappingQuestionCount=4`；没有称作全新或未见验证集。

最终在真实前端重新打开该次结果，确认页面显示“证据不足，暂不能判断改善”、8 题与 4 题的实际结果、4 题复用提示及费用缺失。截图与 DOM 记录对应同一项目、标准版本 40 和 03:30 完成的作业。

第二轮 48 次调用记录 input 123,290、output 21,404、total 216,374 tokens（total 包含 Runtime 的缓存计数口径，不能用前两列相加重算）。费用未提供。SDK 默认 `cost.total=0` 不再作为免费或有效零费用估计；显式报告的零费用仍可保留。

## 3. C2 应用与两个运行目标

首次独立应用实际咨询暴露商品范围问题：虽然拒绝定制键帽的七日无理由退货，后续步骤仍可能套用仅适合耳机/键盘的换货和保修规则。Guide 修改应用 Skill 为 C2，明确产品范围与未规定事项。C2 是针对已见失败的修整，未进入上述 B0/C1 比较，不能借用其分数宣称 C2 有统计改善。

在查看目标输出前保存验收标准：F1R 是已见失败回归；F2–F4 是新编检查探针。v8 的两个运行目标共 8 次真实调用均满足对应标准。

| 探针 | 主要检查 | v8 PAW 目标 | v8 独立目标 |
| --- | --- | --- | --- |
| F1R 定制键帽 | 不适用 R01；不能借用耳机/键盘 R02/R03；不编退款到账时间 | 通过，Lab 试用入口 | 通过 |
| F2 标准键盘 | 购买第 730 天的保修边界；不猜运费与处理时效 | 通过，已启用 App | 通过 |
| F3 耳机异常发热/鼓包 | 停用、停充、断电安全步骤；不虚构已退款/换新 | 通过，已启用 App | 通过 |
| F4 明确退货诉求 | 第 6 天退货、相应运费责任；不强迫重选诉求或编时效 | 通过，已启用 App | 通过 |

App `extension:lab-5af4e002f58b40bbbe0aeb7fc93d08f5` 的最终交付版本为 **v11**。v8→v10 的 `app.json`、spec、`SKILL.md` 与 `rules.md` 不变；改动是界面状态、展示顺序和独立主机请求校验。v10 在 PAW App 与独立目标再次完成 F1R，两个目标通过。其 PAW 回执为 `lab-app-call-14a9dc693b5b45adb5083bdf949ebfbd`；独立目标为 `d95db838-4f68-44a7-9b32-c1ed34adcc7a`。

随后 390px 窄屏检查发现，恢复历史后的状态文字挤压提交按钮，历史恢复按钮也变成逐字换行。Guide 仅修正 HTML 中的 CSS，准备 v11；两个包的 `app.json`、`app.py`、`SKILL.md`、`rules.md` 和 HTML 中全部非样式内容均与 v10 相同。v11 在两个目标各执行一次已见 F1R 回归并通过：PAW 回执 `lab-app-call-3d9978eef75347c69401a00cbc3ae06e`，独立回执 `189ea824-a2b8-483e-b26e-c1bf889599b5`。这是最终目标及样式版本检查，没有增加无偏质量评估的样本。

独立应用实测 390px、PAW iframe 内容实测 388px，内容没有横向溢出；提交与恢复按钮不换行，恢复结果时观察到 0 次 POST。PAW 的这一检查只覆盖应用内容，不代表整个 OS 的手机布局已验收。

界面先显示处理建议、依据、下一步及原问题，普通提醒收在下方可展开区域。运行时锁定输入、示例和历史恢复；完成结果与历史结果明确关联原问题。已知失败与“结果尚未确认”使用不同恢复说明。

两个 ZIP 均由真实前端下载，校验解压、源码对应、Python 编译和所需文件；不含当前模型凭据、本地状态库或机器配置。

| 文件 | SHA-256 |
| --- | --- |
| `songguo-support-v11-standalone.zip`，17,855 bytes | `6ed7b8bbeed2becbcfbe069c5af75b126fa9256d32906393decce7247c13daf8` |
| `songguo-support-v11-paw.zip`，18,205 bytes | `5f1e1e14e2df779ed44b20c5afe507eecbab5a06710c0586e8b5596f7ad278a6` |

最终冻结内容 hash：`6e9b5c5c8044687016364ddfefd01eca31b4215dc47b1fdb0cf4b391e6499af2`。独立包以自身 `app.py` 启动，不导入 PAW。PAW 端完成 v10→v8→v10，以及最终 v11→v10→v11 切换；旧窗口提示已启用版本变化并保留输入，由前端“载入已启用版本”切换内容。最终回滚前后均为 9 条已完成调用。独立 v10、v11 各自重启后均保留原来的 1 条已完成咨询，回执内容相同。较早的 PAW v10 停用再启用检查保留当时的 8 条记录，未发起额外咨询。旧版本目录、ZIP 与回执均保留。

随后在 PAW v10 中故意丢弃已接纳调用的前端响应，界面保留原请求并锁定本次输入；点击“核对原操作”发送相同 clientRequestId，最终只增加 1 条调用（总数 7→8）。该请求完成后控件恢复，耳机安全建议位于结果首段，未声称已执行退款。回执 `lab-app-call-a6fce02e5df7400385e51b79b9e4b746` 与同一次 settlement 对应。这是恢复与已知安全分支检查，不是新增的无偏质量评估。

Guide 通过真实 `lab_project` Tool 读取这条调用后更新交付成果。复核发现它把 PAW 的丢响应检查放在独立目标下；通过前端编辑器改为成果 v11，并核对原 v10 内容仍保持不变。最终应用更新后，在同一编辑器保存成果 v12，原成果 v11 也保持不变。说明采用逐目标回执，Agent 草稿没有直接成为验收结论。

## 4. 不同领域的第二个项目

《北辰服务依赖快照》是另一份合成材料，包含 8 个服务、7 条有向依赖。通过实际前端文件选择创建项目 `lab-project-c09c373c911a4f1b943f95506d2daf33`，Guide `agent:78c35a5e-2610-42e9-b23d-29dfdf335145` 生成一个 HTML 成果，而不是售后表单或问答题库。没有创建 Golden 绑定或应用包。

同一成果 `lab-artifact-0f3fccb514ad46a2a3b61769ca415360` 经真实浏览器发现并修正高亮缺失、方向箭头、窄容器节点重叠及中心坐标不一致，保留 v1/v2/v3；最终 v4 仅调整成果摘要，HTML 与已验证 v3 逐字相同。v3 在 1440px 与 1024px 浏览器宽度下检查：

- payments 只高亮 3 条结账同步边，商品查询不被判为宕机。
- cache、events、mailer 分别高亮对应 1 条降级/异步边，文字保留功能边界。
- 8 个节点全部在画布内，没有重叠；7 条边都有方向箭头。
- 窄容器实测 606px，内部画布可横向滚动至 920px。
- Enter 选择、Esc 清除、重置均正常；故障切换及这些动作期间观察到 **0 次 POST**，没有发消息给 Agent。

项目采用 focus 布局，用户仍可展开对话。材料、规则与业务交互都由项目表达，平台仅提供版本化成果和通用容器。

## 5. 本轮发现与修复

| 现象 | 修改位置与验证 |
| --- | --- |
| 初始 Guide 消息失败后状态难恢复 | 复用普通 Pi admission 与共享消息恢复；保留原请求身份和错误。 |
| 嵌入对话被固定头部高度挤压 | 修整 Lab 自己的容器布局；窄窗口按实际容器宽度切换，避免只看浏览器宽度。 |
| 最终答复可能被进程记录重复投影 | 共享 reducer 按实际持久消息/回执衔接，保留既有回归。 |
| 项目切换后刷新回到旧项目 | 活跃 Lab 路由同时更新外层 hash；两个项目互切和完整刷新均实际通过。 |
| App 调用历史无法在业务界面恢复 | `pawApp.history()` 返回本 App 最近记录，隔离其他 App；Guide 可读取本项目的 App 与实际调用详情。 |
| 历史增多可能挤掉活动调用；恢复可超过容量 | 返回最近历史并保留较早的活动调用，invoke/resume 共用每 App 的容量检查；查看新版时仍可识别并停止本 App 旧版本的活动调用。 |
| 预览 CSP 标签进入正文被忽略 | 预览 bootstrap 等 DOMContentLoaded 后替换文档；真实浏览器验证 head 内策略、脚本/样式执行和 connect-src 阻止。已有桌面/手机文件预览回归 2/2 通过。 |
| 独立服务接受不属于本机入口的 Host | GET/POST 校验实际 loopback Host/端口，配合已有 Origin 校验；真实历史入口返回 403 且记录未变。 |
| 评审协议改变后仍可能沿用旧校准 | 版本化协议、校准兼容性与新冻结快照；验证复用跨快照记录，原结果不改写。 |
| 新数据库迁移/需求后旧计数断言失败 | 显式更新到迁移 196 与 UR-297，迁移/需求组 29 项通过；未改写旧迁移。 |
| 旧导出校验器在全量环境出现高 FD 错误 | 用 DefaultSelector 替换 select；高 FD 真实启动回归先失败后通过。 |
| 健康检查测试误计其他测试的后台连接 | 原顺序诊断记录 8 次其他数据库的恢复线程连接，当前服务/前台为 0；测试继续捕获全部前台连接与本服务任意线程连接，排除其他测试的后台工作。16 项回归和 3 个正反控制例通过。 |

## 6. 验证范围与证据

已完成的本轮检查：最终前端全量 **299 files / 3354 tests passed**；项目本地 TypeScript 构建、生产前端构建、候选 Pi Runtime v7 构建和其 smoke；迁移/需求组 29 项、导出/健康组 19 项、预览路由/项目组 6 项、项目/应用服务组 34 项、Runtime 打包组 50 项；以及各新增项目、App、Golden、路由、工具、Skill 的定点回归。后端第二轮全库 **4,960 项、1 failure、2 skipped**，耗时 3960.636s；不能用这些子集通过替代全库通过。

第一轮后端全量运行 4,955 项，17 failures、1 error、2 skipped：15 项为新增迁移后的旧期望值，1 项为需求计数，1 项为全量环境下额外 SQLite 连接，1 项为旧导出校验器高 FD。迁移、需求与导出问题已修复。第二轮只剩 `test_repeated_health_session_and_room_reads_reuse_open_schema`，全局连接计数为 4，预期为 0。

保留原断言，按相同顺序执行至第 3,145 项检查，运行 2596.890s，复现 8 次额外连接：全部来自旧测试遗留的 `rag-ime-background-recovery` 线程，经 `agent_background_jobs.py` 的 `_recover_loop` 访问其他测试的临时数据库；当前服务数据库和前台线程连接均为 0。该诊断没有启动新的产品调用。进入这项检查时已有 431 条线程，说明旧测试 fixture 还有后台资源清理债务，不能把全局连接数作为本服务健康读取的开销。

只修正测试的测量范围：继续捕获前台线程对任何数据库的打开，以及任何线程对本服务数据库的打开；其他数据库的后台工作不混入该计数。完整健康模块 **16 项通过，26.287s**。三个控制例确认：外部数据库的后台读取可通过；本服务数据库的后台读取、前台线程打开其他数据库都仍使断言失败。最后这次测试修正后未重新运行全库，因此不声明后端全库已全部通过，也未宣称清理了所有旧 fixture。

本机可复核材料位于仓库外的 `lab-candidates/20260907-generic-v1` 目录，完整路径随当前会话的交付入口提供；这些原始数据不随应用导出。关键文件：

- `acceptance/B0-method.md`、`C1-method.md`、`experiment-B0-C1.json`、`experiment-B0-C1-judge-v2.json`。
- `acceptance/final-c2-probes.json`、`C2-v8-F*-*.json`、`C2-v10-F1R-*.json`、`C2-v11-F1R-*.json`。
- `acceptance/exports-v11-verification.json`、`paw-v11-rollback-verification.json`、`standalone-v11-restart-verification.json`、`app-deactivation-reactivation-verification.json`；较早的 v10 对应文件保留。
- `acceptance/standalone-v11-mobile-verification.json`、`paw-v11-mobile-verification.json`。
- `acceptance/topology-final-artifact.json`、`topology-v3-browser-verification.json`、`project-navigation-reload-verification.json`、`preview-bootstrap-verification.json`、`v10-recovery-probe-verification.json`。
- `acceptance/golden-v2-browser-result-verification.json`、`guide-v10-receipt-read-evidence.json`、`delivery-artifact-final-v12.json`；此前成果回执保留。
- `full-frontend-tests-complete.log`、`full-backend-tests-final.log`、`preview-browser-regressions.log`、`runtime-v7-build.log`。
- `acceptance/health-prefix-connection-traces.json`、`health-counter-final-diagnosis.json`、`health-scoped-counter-controls.json`；`health-scoped-regressions.log` 与 `health-prefix-diagnosis.log`。

当前 Lab Skill 的源码与候选 v7 包逐文件一致，含可选的按目标记录交付模板。已有 Pi Session 按设计保留先前加载的 Skill 正文；依赖图 Guide 的重复 `skill_load` 得到 already-active 回执，不能写成已重新加载新版。新版包与既有 Session 已加载版本的区别记录在 `acceptance/skill-bundle-v7-verification.json`。

`python3 scripts/check_project_harness.py`、`check_import_boundaries.py`、`check_route_ownership.py` 与 `check_pawos_frontend_source_map.py` 均通过。`check_public_release.py --repository-only` 未通过：既有 `.impeccable/review/painterly-20260906/assets.json` 存在机器路径，且工作区有未提交修改；本轮没有改动该文件，也没有清理其他任务的工作。扫描未发现凭据形态或禁入候选文件。这一检查不代表产品已发布。

截图在仓库忽略的 `output/playwright/lab-20260907/`。导出 ZIP 在上述材料根目录的 `exports/`；业务应用与实验原始数据保持分离。

## 7. 保留的边界与下一步

这是受支持范围内的通用项目、真实评测与双目标应用交付闭环，不能据此宣称所有垂直场景已覆盖或云 SaaS 已上线。文本材料之外的文档/仓库连接、真实业务动作适配、目标环境工具、服务侧费用硬限与多租户部署仍需相应实现。候选 Pi/前端与源 Gateway 的证明也不替代原生安装与真实前台验收。

C2 的回归探针支持修正具体商品范围问题，两个 B0/C1 比较均不能证明改善；当前费用不可用。继续扩展任务时应先补任务/环境与可判断标准，再做独立验证，不能通过反复查看同一验证集追求通过率。

旧测试 fixture 的后台生命周期清理和最终修正后的整库复跑也保留为后续集成工作；当前结果没有掩盖这两项边界。
