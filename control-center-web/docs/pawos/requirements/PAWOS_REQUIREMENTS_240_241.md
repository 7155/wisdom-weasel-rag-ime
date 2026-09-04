# PAWOS 用户需求账本 · UR-240–UR-241

> 导航：[UR-237–UR-239](PAWOS_REQUIREMENTS_237_239.md) · [总索引](../PAWOS_REQUIREMENTS.md) · 下一份：[用户逐字证据](PAWOS_REQUIREMENT_EVIDENCE.md)
>
> `current` 只表示当前控制语义，不表示实现完成。实施状态与证据见
> [PAWOS_REQUIREMENT_STATUS.md](../PAWOS_REQUIREMENT_STATUS.md)。

## User Requirement Ledger

### UR-240 — Settings 按 Session、Room、Trace、Lab 场景控制 Skill，并移除 resume-builder

- **状态 / 优先级：** `current / P0 context and Skill isolation`
- **当前控制要求：** Settings 必须显示并持久化不同运行场景的 Skill 配置。普通
  Session 不加载 Room、Trace 或 Agent Lab 的私有场景 Skill；Room 只在普通 Session
  基线上增加 Room Skill；Trace 只在 Trace 场景增加诊断 Skill；Agent Lab 只在实验室
  场景增加 Lab Skill。Agent Lab 内创建 Room 时可组合 Lab 与 Room 的必需能力，但不能
  把任一场景 Skill 反向泄漏给普通 Session。
- **移除要求：** `resume-builder` 必须从 PAW 的源码目录、受管 Pi bundle、Settings/
  catalog 投影和新 Session 的可加载集合中移除；不能只隐藏一个前端标签，也不能删除
  用户自己的简历文件或独立于 PAW 的个人 Skill。
- **用户可见验收含义：** Settings 能分别查看四类场景的 effective Skill 集合；依次创建
  普通 Session、Room、Trace 与 Agent Lab 任务后，Runtime `session.open` 收据显示的
  SkillRefs 与该场景一致。重启后设置保持，已经运行的 Session 保留其创建时的稳定
  resource snapshot，不被后台热改。
- **必须保留：** Pi 仍是 Skill/Package 加载 owner；PAW Settings 只管理显式场景策略和
  投影。必需的共享基础 Skill 可以由 Runtime 明确列出，但不得借“基础能力”重新注入
  Room/Trace/Lab 私有 Skill。
- **不得做：** 不得把所有 Skill 全局注入；不得仅靠提示词宣称隔离；不得从
  `resume-builder` 名称删除推导为清理其他 resume Skills；不得用 mock/catalog 截图冒充
  已安装 Runtime 验收。
- **来源原话（OMP active path）：**

  > `5f7ae0a5` · `2026-09-03T04:55:11.479Z` · “resume-builder移除paw”

  > `ab09270f` · `2026-09-03T06:13:48.669Z` · “设置里面需要在不同场景加载不同的技能，比如说 CS 模式它就完全不要加载。Room 机，Room 里面的那些机能，然后 Room 里面 嗯，就相对塞辛增加相应的技能就行了。然后崔丝的技能就 确实那个场景在增加 然后的话 嗯，可以再 嗯，比如说 那个 lab 的技能，就实验室的技能，只能实验室增加。”

  > `481dcb39` · `2026-09-03T06:14:11.717Z` · “这个务必完成”

  > `9e594fe7` · `2026-09-03T06:15:28.287Z` · “就是设置里面加入技能控制”

- **解释边界：** 原话“CS 模式”按同一句与上下文中的“普通 Session / Room / Trace /
  Lab”四场景理解为普通 Session 基线；保留原始口误，不把它改写成新的产品名。

### UR-241 — 审查并修订 PAW Skill Diff Review 包后再集成

- **状态 / 优先级：** `current / P1 Skill review delivery`
- **当前控制要求：** 检查用户指定的 `PAW_SKILL_DIFF_REVIEW.zip` 是否与当前 PAW
  Skill/Runtime/文档责任边界一致，修正过期基线、错误职责、重复流程、缺少的 owner
  联动和验证说明；不能因为包内 patch 自称通过 `git apply --check` 就直接整包应用。
- **审查与交付：** 对每一项提案记录“怎么改 / 为什么 / 是否采纳 / 当前代码差异 /
  所需联动 / 验证结果”，保留 side-by-side diff、manifest 和验证收据。若原包需要保留
  作为审计证据，生成新的修订版而不覆盖原文件；只有确认兼容的最小改动才进入仓库。
- **必须保留：** Pi 的 Agent loop、Tool loop、Session/Room owner 和按需 Skill 路由；
  当前 `AGENTS.md` 的最小 bootstrap；现有无损需求来源与双轴验证。Skill 不得建立第二
  Runtime、强制每个任务进入项目生命周期或让文档成为 Kernel 完成门。
- **不得做：** 不得加入用户已拒绝的 `LICENSE.resume-skills`；不得把 ZIP、HTML 或
  Agent 总结当作当前源码事实；不得从旧 baseline 覆盖后来已接受的 Skill 精简与职责
  修正；不得提交原始 OMP transcript、机器绝对路径或个人上下文。
- **用户可见验收含义：** 用户能打开修订包查看当前 main 与最终提案的逐文件 diff，
  `WHY_AND_HOW.md` 说明采纳/拒绝理由，manifest 与包内容一致，Skill validator、项目
  harness 和相关路由测试通过；仓库只包含经验证的兼容增量。
- **来源原话（OMP active path）：**

  > `170ffbb3` · `2026-09-03T12:59:17.629Z` · “/Volumes/undo\ 4t/MyGlobalDownloads/PAW_SKILL_DIFF_REVIEW.zip这个技能看看对不对，，然后改一下”

- **修正关系：** 本条受当前对话中“不要添加这些 [LICENSE.resume-skills]”以及“等我干完
  再统一这些”的既有修正约束；完成本次完整闭环前先审查、再做最小集成，禁止把外部
  提案机械覆盖到当前 Skill 套件。

## 继续阅读 / 编辑

- 下一份：[用户逐字证据](PAWOS_REQUIREMENT_EVIDENCE.md)
- 实施状态：[PAWOS_REQUIREMENT_STATUS.md](../PAWOS_REQUIREMENT_STATUS.md)
- 总入口：[PAWOS_REQUIREMENTS.md](../PAWOS_REQUIREMENTS.md)
