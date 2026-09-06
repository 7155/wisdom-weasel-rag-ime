# PAWOS Product Requirements

## 用户需求账本总索引

这是 PAWOS 需求文档集的稳定入口。原始单文件账本已按稳定编号拆成四十四卷，
避免一次读取或编辑全部需求时发生截断。拆分只改变导航，不改变编号、
语义、优先级、来源、修正关系或实施状态。

`current` 只表示当前控制语义，**不表示已实现或验收完成**。实施状态、双轴
verdict 和 E1–E6 证据仍由
[PAWOS_REQUIREMENT_STATUS.md](PAWOS_REQUIREMENT_STATUS.md) 单独管理。

## 需求分卷

| 顺序 | 文件 | 内容 |
| --- | --- | --- |
| 1 | [UR-001–UR-030](requirements/PAWOS_REQUIREMENTS_001_030.md) | PAWOS 重构、Agent/Room 基线、OS/App/Browser 与初始 UI 契约 |
| 2 | [UR-031–UR-060](requirements/PAWOS_REQUIREMENTS_031_060.md) | Tutti 工作面、Composer、主题与安装/模型配置修正 |
| 3 | [UR-061–UR-090](requirements/PAWOS_REQUIREMENTS_061_090.md) | 主题收敛、窗口 chrome、工具/上下文/Browser 交互修复 |
| 4 | [UR-091–UR-120](requirements/PAWOS_REQUIREMENTS_091_120.md) | 单层窗口、真实数据、Session/Room 生命周期与前台验收 |
| 5 | [UR-121–UR-150](requirements/PAWOS_REQUIREMENTS_121_150.md) | Room Focus、Agent 时间线、沙箱、应用迁移与最终交付 |
| 6 | [UR-151–UR-180](requirements/PAWOS_REQUIREMENTS_151_180.md) | Demo、消息顺序、动态行星、项目文件夹、Trace/Eval 与 Trace Agent App |
| 7 | [UR-181](requirements/PAWOS_REQUIREMENTS_181_181.md) | 大型需求账本拆卷、连续导航及 Codex/Pi Skill 同步规则 |
| 8 | [UR-182](requirements/PAWOS_REQUIREMENTS_182_182.md) | Room 行星观察窗的紧凑只读边界与行星/卫星术语 |
| 9 | [UR-183–UR-187](requirements/PAWOS_REQUIREMENTS_183_187.md) | 桌面图标、协同铺排、严格时间线、Trace 诊断与 Room Markdown |
| 10 | [UR-188](requirements/PAWOS_REQUIREMENTS_188_188.md) | Trace 真实失败归因、授权修复与复验闭环 |
| 11 | [UR-189–UR-191](requirements/PAWOS_REQUIREMENTS_189_191.md) | 单层文件块、Agent 项目文件夹与 macOS 式 Dock/窗口 |
| 12 | [UR-192–UR-194](requirements/PAWOS_REQUIREMENTS_192_194.md) | Pi 插件市场沙箱、最终整理提交/合并归档与外部前端模型交接 |
| 13 | [UR-195](requirements/PAWOS_REQUIREMENTS_195_195.md) | Trace Agent 原对话、实际动作/工具时间线与诊断对话入口 |
| 14 | [UR-196–UR-205](requirements/PAWOS_REQUIREMENTS_196_205.md) | 本轮 MIT 参考边界、Dock、桌面文件/图标、后台活动、通知与性能/验收顺序 |
| 15 | [UR-206](requirements/PAWOS_REQUIREMENTS_206_206.md) | Room 行星的未分配起始面、协作任务表与独立最终结果分面 |
| 16 | [UR-207](requirements/PAWOS_REQUIREMENTS_207_207.md) | 垂直 App 自举、掌柜问数、专属 Skill、SGG 沙盒与安装/卸载生命周期 |
| 17 | [UR-208](requirements/PAWOS_REQUIREMENTS_208_208.md) | Memory 时间线首页、日记/活动分布、Memory 管家对话、偏好与加载恢复 |
| 18 | [UR-209](requirements/PAWOS_REQUIREMENTS_209_209.md) | 桌面图标移除、隐藏与恢复，不改变 App 或对象数据 |
| 19 | [UR-210–UR-211](requirements/PAWOS_REQUIREMENTS_210_211.md) | Extension App 沙箱选择与 RAG 冻结实验、选优、受控晋升/回滚 |
| 20 | [UR-212](requirements/PAWOS_REQUIREMENTS_212_212.md) | App Builder 专属前端代码、owner/改法、重试身份与完整测试/安装态验收矩阵 |
| 21 | [UR-213](requirements/PAWOS_REQUIREMENTS_213_213.md) | 自我进化实验的初学者详情网页、计算、前后变化、Keep/Reject 与证据边界 |
| 22 | [UR-214](requirements/PAWOS_REQUIREMENTS_214_214.md) | 优化报告迁出 System Monitor，成为独立网页与外部打开入口 |
| 23 | [UR-215–UR-220](requirements/PAWOS_REQUIREMENTS_215_220.md) | 单角色 Room、消息去重、Tool 折叠、Composer 稳定、对话性能与安装一致性 |
| 24 | [UR-221–UR-222](requirements/PAWOS_REQUIREMENTS_221_222.md) | Trace 全自动项目绑定与白话诊断/修复入口 |
| 25 | [UR-223–UR-224](requirements/PAWOS_REQUIREMENTS_223_224.md) | 终态通知幂等与 Session Stop 真实取消/即时回落 |
| 26 | [UR-225](requirements/PAWOS_REQUIREMENTS_225_225.md) | Trace 报告倒金字塔、白话因果链、证据缺口集中与双层读者 |
| 27 | [UR-226–UR-235](requirements/PAWOS_REQUIREMENTS_226_235.md) | 四项目质量/成本优化、Trace 修复闭环、运行/Case/diff 矩阵与 Judge/Golden 实例 |
| 28 | [UR-236](requirements/PAWOS_REQUIREMENTS_236_236.md) | 对话原文、需求、改动、运行与验收证据的双向追踪合同 |
| 29 | [UR-237–UR-239](requirements/PAWOS_REQUIREMENTS_237_239.md) | 对话 exactly-once 收敛、HTTP/SSE/Runtime 恢复与 Memory/冲突故障隔离 |
| 30 | [UR-240–UR-241](requirements/PAWOS_REQUIREMENTS_240_241.md) | 四场景 Skill 隔离、resume-builder 移除与 PAW Skill Diff Review 包修订 |
| 31 | [UR-242–UR-245](requirements/PAWOS_REQUIREMENTS_242_245.md) | 面试双 App 定位、交互重设计、两层自主优化及状态一致性优先 |
| 32 | [UR-246–UR-248](requirements/PAWOS_REQUIREMENTS_246_248.md) | 体验优先、Astra 并行、Room 分层权限与结果阅读重设计 |
| 33 | [UR-249–UR-250](requirements/PAWOS_REQUIREMENTS_249_250.md) | 白色星空主题、真实双向消息流与各行星卫星状态数量 |
| 34 | [UR-251–UR-253](requirements/PAWOS_REQUIREMENTS_251_253.md) | 删除废弃版本、工具调用与动效、整个 OS 重设计 |
| 35 | [UR-254–UR-255](requirements/PAWOS_REQUIREMENTS_254_255.md) | Lab 成本与成功率重点、Golden 起草审核校准冻结完整流程 |
| 36 | [UR-256–UR-259](requirements/PAWOS_REQUIREMENTS_256_258.md) | 四场景自举优化、近期 Demo/简历、收益指标及无额度时的状态一致性优先 |
| 37 | [UR-260–UR-264](requirements/PAWOS_REQUIREMENTS_260_264.md) | 整个 OS 浅色纵深动效、OAuth 与指标、多伙伴独立窗口、Runtime 同步及因果式文档 |
| 38 | [UR-265–UR-266](requirements/PAWOS_REQUIREMENTS_265_266.md) | 重做酷炫星际、主题记忆与可解释可视化 |
| 39 | [UR-267–UR-269](requirements/PAWOS_REQUIREMENTS_267_269.md) | 后台 Agent 星球壁纸、完整 Browser、粒子/暗色与 OS 性能 |
| 40 | [UR-270](requirements/PAWOS_REQUIREMENTS_270_270.md) | 移除爪印、统一星际标识及真实思考/工具星系动效 |
| 41 | [UR-271](requirements/PAWOS_REQUIREMENTS_271_271.md) | 项目文件夹全屏星系选择、实际状态/进度与项目 docs |
| 42 | [UR-272–UR-274](requirements/PAWOS_REQUIREMENTS_272_274.md) | 直接打开立体星系、重做渲染器与思考星核居中修正 |
| 43 | [UR-275–UR-277](requirements/PAWOS_REQUIREMENTS_275_277.md) | 真实天体质感、银河核心语义与自转/轨道模拟 |
| 44 | [UR-278–UR-283](requirements/PAWOS_REQUIREMENTS_278_283.md) | 模型标识、同步恢复、OS 内制作装卸、场景加载、代码艺术星系与双显示模式 |

## 同一文档集的其他文件

| 文件 | 作用 |
| --- | --- |
| [用户逐字证据](requirements/PAWOS_REQUIREMENT_EVIDENCE.md) | 用户原始消息、来源覆盖与修正证据；不得用 Agent 转述替代 |
| [产品契约](requirements/PAWOS_PRODUCT_CONTRACT.md) | 跨需求的产品定义、所有权、App/Room/Browser/动效与验收边界 |
| [实施状态](PAWOS_REQUIREMENT_STATUS.md) | 每条 UR 的实际完成度、验证边界和收据 |
| [PAWOS 文档入口](README.md) | 需求、Trace/Eval、设计讨论和 handoff 的总目录 |
| [2026-09-05 可靠性续接技术记录](PAWOS_RELIABILITY_CONTINUATION_20260905.md) | 本轮根因、改法、回归与 source / Runtime / native 验收边界；不代替需求或状态账本 |

## 读取与编辑规则

- 从本索引进入后按四十四卷顺序读取。每卷顶部和末尾都列出上一份、总索引与
  下一份；最后一卷继续到逐字证据、产品契约和实施状态，不会静默结束。
- 修正已有需求时，编辑包含该稳定 ID 的分卷；不得重新编号。新增需求追加到
  最后一卷，超过可维护规模后再新建下一卷，并同时更新本索引与相邻导航。
- 每条用户来源必须映射到至少一个 UR，或明确标记为重复、仅参考、非需求或
  不可获得。分卷不允许删减原话、来源、冲突或 supersedes 关系。
- 文档结构检查只帮助发现漏项和断链，不是产品完成门。不要因为 hash、文档
  同步或普通格式问题阻塞真实功能结果与最终回复。

## 继续阅读 / 编辑

- 下一份：[UR-001–UR-030](requirements/PAWOS_REQUIREMENTS_001_030.md)
- 若只查最新要求：[UR-278–UR-283](requirements/PAWOS_REQUIREMENTS_278_283.md)
- 若记录实现结果：[PAWOS_REQUIREMENT_STATUS.md](PAWOS_REQUIREMENT_STATUS.md)
