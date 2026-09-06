# OS 能力、同步与显示模式续接 · 2026-09-06

任务：`01a071a1-a095-7e73-a2d5-e97cfefaa09f`。需求：[UR-278–UR-283](requirements/PAWOS_REQUIREMENTS_278_283.md)。历史星空、完整 Browser、docs、物理近似和原检查记录见 [STELLAR_BROWSER_CONTINUATION_20260905.md](STELLAR_BROWSER_CONTINUATION_20260905.md)。

## 当前结果与视觉修正

用户明确否定新暗色烟雾效果并要求换回。源码桌面已恢复前一版星云绘景和已有行星；项目星系恢复前一版材质、灯光、尺度、名称和轨道呈现。撤掉无人消费的 StellarGalaxyCanvas、stellar-abstract.css，桌面不再新增常驻 WebGL 渲染器。只撤回本任务刚做的视觉试验，保留其他功能和并发工作。此恢复不表示用户已经满意旧版或接受新的战术星图。

列表和全屏星系双向入口保留。项目弹窗按钮原本统一 width:28px，带文案按钮因此被挤成竖排；新增独立类、auto 宽度、nowrap 与不可压缩约束。实际 Edge 源码页选中四个真实对话的未绑定项目，星系 → 文字列表 → 全屏星系保持同项目、同四个对话和 1× 播放。截图已观察到按钮横排；无新建 Session。

## 模型身份

- 新增 `src/features/paw-os/SatelliteModelBadge.tsx` 与样式：通过窗口自己绑定的 sessionId 读取 `agent.session.models`，校验返回 Session 身份，展示真实 selected provider/model。
- `PawOsSatelliteHost.tsx`：行星使用 participant Session；卫星只用真实 childSessionId，不能降级为父 Session。
- `PawWindowLayer.tsx`：观察窗标题增加模型 portal 槽。未知显示“模型未提供”，可见时 30 秒刷新，关闭后停止。
- 测试覆盖独立子模型、拒绝错误父 Session 返回和未绑定时不请求；真实运行中 Room/子 Agent 同时换模型的前台验收仍未做。

## Session 恢复原因与修复

共享 live-store 原有自动恢复；PawSessionWorkspace 消费者把网络/快照失败永久混入操作 error，连接恢复也不会清除。现在网络恢复状态独立，已有快照时保留聊天与输入草稿，标题显示恢复中，稳定事件或成功快照清除暂时错误。真正操作失败、首次不可用和工作目录缺失仍显示对应操作。

先复现两个红测，再补恢复/目录边界回归。测试确认自动恢复不发送用户 prompt。用户安装态截图的具体原始后端失败没有被重演，不能由消费者缺陷推断所有同步问题已经根治。未重启 Gateway/Pi，未调用 Provider。

## App Center 与原生 Pi Package

- 新增 `features/plugins/PluginStudio.tsx`：让 Agent 制作 App/插件的需求编辑器，或人工 Skill/Prompt 编辑器。Agent 路径只打开草稿，发送后才执行。人工路径经不可变 draftId 创建原生包、validate、preview，再进入同一个安装回执流程；失败保留内容，未改变的重试复用草稿。
- 新增“场景加载”，复用从配置页抽出的 `ScenarioSkillSettings.tsx`，不另造配置源。普通对话、Room、Trace、Lab 读取同一 skillRouting 规则；选择与实际加载文案分开。隐藏 App 不启动此页的查询。
- `agent_configuration.py` / `agent_service.py`：skillRouting 配置不再触发全 Runtime 重启或 busy 拦截；真实 Runtime 配置仍遵循原规则。新 Session 用新 allowlist，当前/重新打开的同一个 Session 保留 resourceSnapshot。
- `agent_tools.py`：增加 `plugins op=apply`，经当前 Session 既有 R2 权限、确切预览 token/digest 和已有批准执行路径。只读拒绝；包内容或模型输出不能自行授权。人和 Agent 最终调用同一 `AgentExtensionService.apply`。
- `agent_extensions.py`：读取准确 preview 而不先消费；错误 digest 不烧掉正确 token；成功后相同 token 在进程内 TTL 期间返回原回执，不重复安装。Host 执行结果不确定时不重新执行。此缓存不是跨 Gateway 重启的持久事务。
- Pi Package 解析/加载仍归 Pi；保留安装/启用/资源快照和历史数据边界。Skill 的场景选择不声称动态卸载所有 Extension、Prompt、Theme。
- 实际源页面已打开 App Center → 制作 → 自己编写，以及场景加载入口。未创建、安装、卸载测试包，也未更改用户场景配置；真实生命周期端到端与已安装 App 更新是后续独立验收。

## 新鲜验证

工作目录为仓库或注明的 `control-center-web`。完整命令与日志保留在本机 /tmp，不能把其他任务的构建当成本轮证据。

- 前端 14 文件 **228 项通过**：project-galaxy-stage、surfaces、model、PawProjectGalaxyScene、PawProjectGalaxy、PawStellarBackdrop、PawWayfinderWork、plugins-feature、PluginStudio、configuration/management-writes、SatelliteModelBadge、PawOsSatelliteHost、PawSessionWorkspace、PawWindowLayer。命令 `pnpm exec vitest run src/paw-os/shell/project-galaxy-stage.test.ts src/paw-os/shell/project-galaxy-surfaces.test.ts src/paw-os/shell/project-galaxy-model.test.ts src/paw-os/shell/PawProjectGalaxyScene.test.tsx src/paw-os/shell/PawProjectGalaxy.test.tsx src/paw-os/shell/PawStellarBackdrop.test.tsx src/paw-os/shell/PawWayfinderWork.test.tsx src/features/plugins/plugins-feature.test.tsx src/features/plugins/PluginStudio.test.tsx src/features/configuration/management-writes.test.tsx src/features/paw-os/SatelliteModelBadge.test.tsx src/features/paw-os/PawOsSatelliteHost.test.tsx src/paw-os/apps/PawSessionWorkspace.test.tsx src/paw-os/shell/PawWindowLayer.test.tsx --maxWorkers=1 --testTimeout=30000`，日志 `/tmp/paw-restored-galaxy-lifecycle-tests-20260906.log`。JSDOM 两条缺少 canvas 实现的提示不构成真实 GPU 验收；实际源浏览器已看到恢复后的 WebGL 星系。
- 双向模式新增断言单独检查通过（1 项，24 项按名称过滤跳过）：`pnpm exec vitest run src/paw-os/shell/PawWayfinderWork.test.tsx --maxWorkers=1 --testNamePattern='opens the selected folder'`，日志 `/tmp/paw-both-project-modes-test-20260906.log`。
- 后端配置、场景路由、扩展生命周期、3 个 Gateway apply/权限测试和 busy 路由保存测试，共 **45 项通过**，日志 `/tmp/paw-plugin-lifecycle-backend-final-20260906.log`。准确命令：

```bash
python3 -m unittest tests.test_agent_configuration tests.test_agent_skill_routing tests.test_agent_extensions tests.test_agent_tools.ControlToolGatewayTests.test_agent_applies_exact_plugin_preview_through_existing_session_authority tests.test_agent_tools.ControlToolGatewayTests.test_agent_can_search_create_validate_and_propose_a_package tests.test_agent_tools.ControlToolGatewayTests.test_agent_can_propose_plugin_lifecycle_previews_without_applying_them tests.test_agent_service.AgentServiceTests.test_scene_skill_save_during_active_work_keeps_runtime_and_uses_new_selection
```
- Pi fake Host 两项通过：`python3 -m unittest tests.test_pi_runtime_v2.PiRuntimeV2Tests.test_session_skill_allowlist_reaches_pi_session_open tests.test_pi_runtime_v2.PiRuntimeV2Tests.test_session_open_receipt_freezes_skill_refs_across_reuse`；日志 `/tmp/paw-plugin-session-snapshot-tests-20260906.log`。新 allowlist 传入与既有快照复用/重开都被检查，无 Provider 调用。
- 恢复后的生产构建通过：`VITE_CONTROL_TRANSPORT=http VITE_BUILD_CHANNEL=production pnpm run build --outDir output/stellar-build`，日志 `/tmp/paw-restored-galaxy-lifecycle-build-20260906.log`；仍有现有的大 chunk 提示。
- `python3 scripts/check_import_boundaries.py`、`python3 scripts/check_route_ownership.py` 通过。
- 需求状态检查通过：283 条、44 卷；UR-283 的本轮源码显示模式边界已验证。仓库总 harness 未通过，原文为 `release candidate scope misses base-to-HEAD paths: tests/test_agent_workspace_sqlite_scratch.py`；该路径不在本任务改动内，未扩写发布候选清单。不能宣称全仓验收通过。
- 本任务路径的 `git diff --check` 通过。
- 本轮无 commit、push、App 安装、Gateway/Pi 重启。浏览器是 Edge 中 `http://127.0.0.1:5183/?frontend=paw-os` 的源码页；这些源码与 fake Host 检查不能变成已安装态完成声明。

## 星际 II 参考研究

用户询问星空风格及星际 II 地图选择，不表示接受再一次自动替换。可比较：星云绘景（色彩/壁纸感）、写实深空（大尺度/精细灯光）、全息战术星图（投影/选中/状态）、神族水晶星图（蓝金几何/仪式感）、极简数据星图（点线/阅读效率）。

[暴雪的 UI 说明](https://news.blizzard.com/en-us/article/19911221/new-user-interface-coming-to-starcraft-ii)明确讲到腾出内容空间、在各屏幕嵌入 3D 场景；[UI 设计师 Alex Sun 的项目回顾](https://alexandersun.me/case-studies/blizzard-ui)强调统一视觉语言、内容选择与进度的可读性。这些是公开依据，不是该星图的内部 shader 源码。[虚空之遗星图实图出处](https://www.softpedia.com/reviews/games/pc/starcraft-2-legacy-of-the-void-review-496002.shtml)仅用作画面参考，不据评论推断引擎实现。

针对 PAW 的设计建议（未实施/未获用户最终选择）：以全息战术星图组织项目，抽象节点代表对话，选中节点增强形体/光圈，稳定详情区显示模型、状态、进度与 docs；相机过渡明确但标签在操作时保持稳定。背景、导航节点、交互详情分别分配亮度和动效预算。材质、景深、动画曲线及实际美感仍需用可审阅画面确定，不把“换 shader”当成已完成设计。
