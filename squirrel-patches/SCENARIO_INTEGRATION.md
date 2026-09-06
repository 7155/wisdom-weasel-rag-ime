# 选区与屏幕场景联通（更新至 2026-09-06）

用户直接要求：检查输入法 LLM/补全提示词、交互和稳健性；适配划词翻译；框选后弹出对话，根据屏幕对话、做笔记和 Computer Use；已有能力需要联通。工程化叙述必须来自真实链路与验证，不能把场景数量写成质量提升。

接续来源：Codex 任务「优化 PAW 输入法补全交互」（`01a071af-dafb-7cb0-a8d4-72502a1dc845`）。2026-09-05 接续读取了原始用户消息、最新命令和当前差异；下面的状态以本次检查为准。最初生成浮层的工作与边界见 [GENERATION_EXPERIENCE.md](GENERATION_EXPERIENCE.md)。

## 修复前的链路断点

- 主生成走 `PiSurfaceCompletionProvider -> AgentSurfaceRuntime.complete -> Pi completion.once`；旧 DeepSeek 直连提示词不是主链路的全部提示词。
- 选区快捷键只从 Input Client 捕获，硬编码 rewrite；AX/剪贴板备用函数存在，但这里未接入。
- `startRagImeVisualAssistFromContext` 获取窗口图片后传给拒绝 `visualContext` 的 Active RAG 路由。
- 深度检索已使用普通 Pi Session，但显式传入 `attachment_ids=[]`。
- Squirrel 打开会话仍发送旧 DistributedNotification；Electron 没有对应接收器。
- 图片已有 `AgentMediaStore`、导入、模型能力校验和 Pi images 链路；会话已有流式、追问、停止、恢复和桌面语义工具。屏幕入口应复用它们。

## 实施与验收

同一主 Session 负责整合；不创建新的工具循环或笔记存储权威。

| 工作项 | 修改边界 | 可运行验证 | 用户要求验证 | 状态 |
| --- | --- | --- | --- | --- |
| 明确选区任务 | Active RAG 请求、两种 Provider 提示词、正文编译 | 完整原文、语言、缩进、短结果、原样润色、重试回归通过 | 翻译、润色、摘要、解释有明确任务；只读结果复制，改写才允许替换选区 | 源码完成；真实编辑器与模型效果待验收 |
| 打开准确会话 | Squirrel 启动参数、Electron 单实例入口 | 冷启动/已有进程参数解析、准确路由、完整补丁应用与 Swift 解析通过 | 以 `--paw-session` 打开指定会话；框选使用 `--paw-capture` | 源码完成；安装后的原生启动待验收 |
| 框选进入对话 | Electron 原生框选、屏幕助手、现有 Session UI | 捕获取消、图片导入、同会话追问、失败重试、刷新恢复、真实组件布局通过 | 看见本次选区后发送，图片作为该 Session 的受管附件；沿用普通 Pi 对话与 Stop | 源码与组件完成；实际 macOS 选区待验收 |
| 场景动作 | 翻译、解释、笔记、桌面操作意图 | 提示词、按钮交互、临时 Markdown 文件精确落盘、保存回执通过 | 先生成笔记再由用户选择保存位置；桌面任务重读当前目标；可直接切换模型与权限 | 入口完成；真实模型/桌面工具执行待验收 |

回滚以新增场景入口和明确字段为界，保留现有补全默认行为。保留其他工作区修改，不提交、不推送、不替换安装。源码测试与合成预览不等于实际屏幕、模型、笔记落盘或桌面操作通过；前台验收另记。

## 本次接续补齐的缺口

1. **回复数据存在但窗口里不可见。** 独立屏幕页面漏载了会话布局样式，真实浏览器中的消息视口高度为 0。屏幕入口现在显式加载既有 App/Session 样式，并取消嵌入会话不需要的标题栏占位。640×760 时消息视口为 405 px，400×500 时为 205 px；输入栏均位于窗口底部，没有横向溢出。图片可折叠，给正文腾出空间。
2. **失败回合重试丢失选区来源。** `PawSessionWorkspace.replayTurnMessage` 现在与首次发送共用 `screenContextForMessage`，保留图片身份与来源约束。已有消息接纳和重试身份规则继续生效。
3. **刷新创建新会话并重复上传。** Electron 为每个弹窗保留既有 Session/附件回执的内存副本；刷新复用这些身份并读取原会话快照，已送达的图片不会重新放入待发送栏。上传失败也保留已创建的 Session。弹窗关闭会释放捕获图片与恢复副本；持久历史仍由 Pi 和受管附件存储负责。
4. **读图失败后无法调整模型。** 屏幕入口启用普通 Session 的模型/推理、权限和工具选择控件；其他嵌入界面的默认设置沿用原行为。未自动升级权限或切换 Provider。
5. **旧检查仍要求已替换的入口。** Squirrel 检查现在验证“框选对话”、准确 Session/框选参数，并确认旧 `com.rag-ime.control.open-agent` 通知不再存在。

前三处恢复行为与控件检查均先取得失败回归，再实现修复。布局问题由实际浏览器的尺寸测量和截图复现，修复后重测；没有用字符串 CSS 断言代替可见性检查。

## 当前数据链与提示词

- 划词：Squirrel 明确操作/目标语言 → Active RAG 请求 → `input_task.py` 统一任务语义 → Pi 单次生成或直连 Provider → 保留版式的正文编译 → 复制或替换。问句翻译的提示词明确要求忠实翻译，原文内命令是材料；超长原文明确报错，不静默截断。
- 框选：`screencapture -i -s` → Electron 临时文件清理与弹窗专属 IPC → 普通 Session → 受管图片导入 → `screenContext` 来源字段 → `AgentPromptApplicationService` → Pi `images` 参数。不会把截图再塞进拒绝 `visualContext` 的 Active RAG 请求。
- 追问/重试：保持同一 Session 和原始 `mediaId`；服务端检查附件归属和首次送达。`screen_context.py` 明确这是一张历史选区，不能代替实时桌面读取，也不授予工具权限。
- 笔记：仅已完成的 Assistant 正文可保存，附来源、采集时间和 Session；Electron 原生保存对话框决定位置，`writeFile` 成功后才返回“已保存”。该文件不是自动写入个人 Memory 或 Knowledge。
- Computer Use：用户填写具体操作后走原有 Pi 工具循环与会话权限。选区提供任务背景，桌面/网页工具负责读取当前目标与执行，入口不另建控制循环。

## 可复现验证

本次三组后端回归分别为 125、92、215 项通过（选区上下文用例有重叠）；前端 51 项、Electron 37 项通过。

```sh
python3 -m unittest tests.test_input_task_scenarios tests.test_screen_context tests.test_assistant_generation_behavior tests.test_native_active_rag_cancel tests.test_active_rag_service tests.test_active_rag_candidate_compiler tests.test_deepseek_completion
python3 -m unittest tests.test_screen_context tests.test_assistant_generation_stage_plan tests.test_build_patched_squirrel tests.test_assistant_overlay tests.test_prediction_status tests.test_control_api_route_policy
python3 -m unittest tests.test_prediction_trigger tests.test_prediction_manager tests.test_prediction_stability tests.test_prediction_first tests.test_predictor tests.test_rime_sidecar tests.test_side_lane_scheduler tests.test_agent_surface_runtime
cd control-center-web
pnpm exec vitest run src/features/screen-assistant/screen-assistant-model.test.ts src/paw-os/apps/PawSessionWorkspace.test.tsx --maxWorkers=1 --testTimeout=60000
pnpm run test:electron
pnpm exec vite build --outDir /tmp/paw-screen-continuation-final-20260905
```

`test_screen_context` 另通过真实 loopback HTTP Gateway/路由/应用服务检查：原始图片字节与来源规则到达 Pi 调用边界；此处 Pi Runtime 响应使用测试替身，不是在线模型效果验证。完整补丁已在独立临时目录应用到 Squirrel 基线 `2158538`，14 个 Swift 文件以 `swiftc -frontend -enable-bare-slash-regex -parse` 通过；实际 AppKit 浮层源码另通过 `preview_assistant_generation.py --typecheck-only`。

项目上下文、导入边界、路由归属、`git diff --check` 通过。9 月 5 日前端生产源码单独类型检查通过，完整 `pnpm run typecheck` 当时被范围外的 `ExperimentWorkspace.test.tsx:135,165` 和 `golden/GoldenWorkflow.test.tsx:74,80,81` 阻塞：Testing Library 的 Role 查询不接受 `exact` 参数。这些文件正在其他工作中修改，本次没有覆盖它们。当时的生产源码检查使用 `node_modules/.tmp/screen-assistant-source-tsconfig.json` 明确排除测试文件；9 月 6 日完整类型检查已通过，见下方新回执。

浏览器证据位于忽略目录 `output/playwright/screen-assistant-continuation-20260905/`：`setup.js`、`restore.js`、`verify.js`、`final-640.png`、`followup-visible-400.png` 和 `followup-collapsed-400.png`。真实组件跑完翻译发送、刷新、追问、保存和打开准确会话：1 次创建、1 次导入、2 次消息、1 次保存调用、1 次准确打开；第二次消息不重复附图。该浏览器流程使用明确标注的合成截图、模型响应和保存回执；原生文件写入由 Electron 测试另行验证。

## 安装与剩余验收

本次没有提交、推送、安装或生成发布清单。读取的现有正式路径标记仍为 build 1429、Electron WebView、源提交 `046b87e8a284a7775267dda601ef18e93f5d8fc5`，不能作为本次候选安装证据。

公共仓库检查尚未通过：共享工作区不干净，另有范围外 `eval/micro-selfboot/SKILL_FLOW_REVIEW.md` 的机器路径；发行与前台门槛仍待完成。

下一次安装验收需在同一候选 Squirrel、Electron 和 Gateway 上完成：真实编辑器划词翻译/复制/改写；框选与 Escape、系统屏幕权限、冷启动/已有进程准确会话；配置的视觉模型读图与追问、Stop/重试；用户选择保存位置；按具体用户操作通过已有桌面/浏览器工具得到真实结果。源码、测试和合成响应不证明这些前台结果。

## 2026-09-06：完整构建接续

实际运行 `prepare_squirrel_workspace.sh` 发现两个安装前检查仍要求旧的 `com.rag-ime.control` 字符串。补丁现在按正式 App 路径启动 Electron，所以准备流程会在进入 Xcode 前失败。先把现有脚本回归夹具更新为当前启动形态并取得失败，再修复准备／构建脚本：同时检查 `Applications/RagImeControl.app`、`--paw-session=` 和 `--paw-capture`。匹配函数使用 `grep -Fq --`，确保启动参数被作为正文匹配。

- `tests.test_prepare_squirrel_workspace` 与 `tests.test_build_patched_squirrel`：27 项通过；真实准备脚本在新目录成功，未重置已有工作区。
- 完整 Squirrel Xcode Release 构建通过，包含实际 Swift 类型检查与链接；候选保留 `LSRegisterProhibited=true`，未注册为第二套输入法。使用本机已有完整 Xcode 的命令级 `DEVELOPER_DIR`，未修改全局选择。
- Electron 预览 App 通过完整 TypeScript 检查、Vite 构建和签名验证；包内五个入口／屏幕模块与当前源码逐字节一致。旧预览构建已恢复原位，新候选单独保留。构建时跳过重复的全量测试执行，全量测试结果单独记录如下；这不是发行或安装通过。
- 当日重测输入任务／屏幕上下文／生成取消等后端回归 126 项、屏幕与 Session 前端回归 51 项、Electron 回归 37 项，均通过。最后一次项目上下文检查、导入边界、路由归属及 `git diff --check` 通过；既有 Sidecar／Gateway 健康检查正常。

全量前端测试没有通过：`PawNativeApps.test.tsx` 的 `takes the Project overview into the production Planning preview/apply/rollback path` 找不到“新任务”按钮。已单独复现该失败（1 failed、27 skipped），未覆盖其他任务正在修改的项目工作台。全量运行后续长时间没有新输出且单个 worker 持续占用 CPU，在 6 分 53 秒时停止了本次测试进程，因此不能声称其余全量用例已通过。日志分别为 `/tmp/paw-screen-web-suite-20260906.log` 和 `/tmp/paw-screen-project-planning-repro-20260906.log`。

原生验收另外被自动化工具阻塞：按正式 App 路径读取 PAW 窗口，连续两次返回 `ScreenCaptureKit.SCStreamErrorDomain -3811`。这是本轮原生窗口捕获的失败证据，尚不能归因为 PAW 框选实现的问题。没有修改系统权限，也未把浏览器模拟替代成原生验收。

候选与日志索引保存在本机忽略目录 `output/ime-screen-assistant-20260906/candidate.json`；该回执标注源提交、脏工作区、源码散列、两个 App 路径、构建与测试证据。当前仍未替换正式 Squirrel／Electron／Gateway，未调用在线模型，未提交或推送。下一步先恢复原生可观测性并处理全量前端阻塞，再通过现有安装流程保留回滚副本、安装匹配版本，完成上节列出的真实选区、视觉模型、保存与桌面工具验收。
