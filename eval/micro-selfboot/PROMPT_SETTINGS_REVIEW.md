# 系统提示词与 docs 感知压缩：实现与验收

2026-09-06。本地候选版的源码、真实 SDK 离线检查与独立设置页已验收。现用 PAW 网关及原有会话尚未切换。

## 已实现

设置 → 配置 → **系统提示词与压缩**，另有“提示词”快捷入口。

- 查看 PAW 内置基础规则；编辑系统补充指令、压缩补充指令。
- 多行保存、恢复默认草稿、版本冲突保留草稿；重新读取后可以比较当前内容，再按最新版本保存。
- 复用既有 `agent.configuration.get/update` 和 revision，只修改变化的提示词字段，保存不重启 Runtime。
- 设置在普通 Session 首次绑定时保存快照；之后修改只影响尚未启动的会话，旧会话重连保留原补充设置。输入法、语音精炼和内部记忆整理的专用提示不受影响。
- 手动、自动及长回合拆分摘要都接收压缩补充指令；单次手动指令追加在默认补充后。清空该设置可使用 Pi 原生摘要。

## docs 与摘要的分工

| 内容 | 放在哪里 | 使用方式 |
| --- | --- | --- |
| 通用工作边界、提问及验收责任 | 内置系统规则 | 短且稳定；设置页展示基础层 |
| 用户表达和工作偏好 | 系统补充指令 | 作为单独一层加入普通会话 |
| 项目愿景、术语、已落盘决定和结果 | AGENTS.md、根文档及相关 docs | 按任务读取；摘要保留准确路径、章节或稳定 ID 与一句用途 |
| 最新纠正、尚未落盘决定、未完成项、阻塞及下一步 | 压缩摘要 | 保留接续所需的实质信息；文档缺失或是否更新不明时不能只留路径 |
| 当前运行、取消、权限、文件及 WorkItem revision | Runtime 与工作区 | 继续前按需核对；摘要与文档只代表上次观察 |

压缩不要求先写 docs，也不让摘要模型继续任务。Pi 继续拥有压缩触发、截断位置、保留最近上下文、重试和取消。默认新增补充为 470 字符，仅在压缩调用中使用。

## 优化与发现

### 2026-09-06：明确 docs 恢复入口

默认压缩补充从 470 字符增加至 641 字符：当文档索引替代接续所需正文时，要求摘要在 Next Steps 告知接续 Agent 先读哪些文档、章节及用途；已充分保留的信息不重复读取，不重读全部 docs。多 worktree 保留准确绑定路径，已有反馈 ID/revision 一并保留，不猜测标识。

SDK 离线检查改为从 `default_prompt_settings()` 读取实际产品默认值，替代占位字符串。修改前在真实 SDK 模型请求处因缺少接续 Agent 指引失败；修改后自动/手动 × 普通/拆分及空默认共 5 个场景通过，并保留原生文件清单、手动追加指令和取消信号检查。使用 Pi worktree `${PI_WORKTREE}`；先前尝试的 `/private/tmp/paw-pi-clean-b2b33fb7` 缺少构建产物，未用其环境错误作为红测证据。

这是提示词接线验证，模型返回值仍为离线替身；未证明真实模型生成摘要的质量或压缩后实际读取 docs。本次不变更已保存的用户提示词、已绑定会话或现用 Runtime，不构建安装、不提交推送。

本次回归：`python3 -m unittest tests.test_agent_prompt_settings tests.test_pi_prompt_settings_overlay tests.test_agent_configuration`，20/20 通过；`python3 scripts/smoke_pi_prompt_settings.py --pi-worktree '${PI_WORKTREE}'`，5/5 通过。

提问规则收敛到 `work-policy`，能力路由层引用该规则；补充“只读约束属于当前阶段”及主/子 Agent 的验收责任，避免阶段完成被误当整个任务结束。

| 测量范围 | 修改前字符 | 修改后字符 | 变化 |
| --- | ---: | ---: | ---: |
| PAW core rails | 1,611 | 1,463 | -148 |
| 能力与 Skill 路由 | 1,099 | 1,064 | -35 |
| 两层合计 | 2,710 | 2,527 | -6.75% |

对应 UTF-8 字节为 6,260 → 5,769（-7.84%）。这是两层文本长度测量，不是完整请求 token、任务成功率或成本收益；本次没有付费模型 A/B。

真实 SDK 检查发现：手动压缩参数没有覆盖自动压缩，长回合前半段摘要也没有接收附加指令。本次在共享原生入口和拆分摘要参数处补齐，保留原有模型、取消信号、重试回调与文件操作清单。

构建还发现 `plugin-creator` 路由卡与已修改的 Skill frontmatter 不一致。已用不超过 200 字符的同义输出说明同步两处，没有扩大卡片预算。

## 验收

| 检查 | 结果 | 边界 |
| --- | --- | --- |
| 配置、核心提示、提示审计 | 39/39 | 旧配置补默认、持久化、文本校验、提示层 |
| Runtime 构建与 overlay | 51/51 | 固定源码锚点、共享入口参数及构建资源 |
| Session 绑定及专用场景 | 5/5 | 首次绑定、重连冻结、旧 Host、空设置及专用场景 |
| Service 与委派接线 | 4/4 | 设置入口、不重启及原有 Runtime/委派合同 |
| 设置前端 | 18/18 | 保存、冲突比较、恢复默认及相关设置回归 |
| 真实 Pi SDK 离线压缩 | 5/5 | 自动/手动 × 普通/拆分，加空默认；模型返回值使用离线替身 |
| 新 Runtime 构建及暂存目录冒烟 | 通过 | 新能力、离线 Session、Steer、Stop 与收口 |
| TypeScript、169 个合同重现、导入/路由边界、生产 HTTP 前端 | 通过 | 编译及结构检查 |
| 独立浏览器 + 真实配置 API | 通过 | 多行保存、刷新和预览服务重启后保留；恢复默认只改草稿，显式保存成功 |

共 99 个 Python 定向回归、18 个前端用例；真实 SDK 的 5 个用例另计。SDK 检查入口：

```bash
python3 scripts/smoke_pi_prompt_settings.py --pi-worktree '<固定的 Pi worktree>'
```

`python3 scripts/check_project_harness.py` 未通过：已有 release candidate 的 base-to-HEAD 范围缺少 `tests/test_agent_workspace_sqlite_scratch.py`。本次没有修改该文件或发布范围清单，不能声称全仓检查全绿。

## 交付与启用边界

- 独立预览：`http://127.0.0.1:8878/#/configuration?section=prompts`，使用独立数据库，模型执行关闭。验收后恢复默认设置。
- Runtime 已用产品脚本 `--no-activate` 暂存：`pi-0.84.2-9c3f93c8b1c4-raghost-4f4e19331e`；manifest SHA-256 `955f16c5d438f60fd56803699864b6c174ae16c1f76ddb6b7de2acb53c5deafa`。
- 前端候选：`/tmp/paw-prompt-web-20260906-r2`；dist SHA-256 `b42567b1091b362817c72daa14a825e850a973fd70307fb6f2961ef693d40b56`。
- 详细本机回执：`~/Library/Application Support/RagIme/EvaluationArtifacts/prompt-settings-20260906/`。
- 10:01 现用网关仍有活动会话。正式启用需在可重启时成套更新后端、前端和 Host，再验证安装版设置保存与新 Session 绑定。只升级后端会因旧 Host 缺少能力而拒绝新绑定。
- 升级前保留旧应用、Runtime 指针和配置快照。回退至不认识 `prompts` 字段的旧后端时须同步恢复对应配置，不能只切换可执行文件。

本次未提交或推送。预览与暂存不代表已在现用安装版启用。

## 源码入口

- 默认值和展示规则：`rag_ime/agent_prompt_settings.py`
- 持久化和 API：`rag_ime/agent_configuration.py`、`rag_ime/agent_service.py`
- 会话注入和快照：`rag_ime/pi_runtime.py`、`rag_ime/pi_runtime_v2.py`
- Host/SDK 适配：`scripts/build_managed_pi_runtime_v2.py`
- 设置页：`control-center-web/src/features/configuration/PromptSettingsPanel.tsx`
- 真实 SDK 验收：`scripts/smoke_pi_prompt_settings.py`、`tests/fixtures/pi_prompt_settings_probe.mjs`

Public source note: `${PAW_DATA}`, `${PAW_STORAGE}`, `${CODEX_HOME}` and `${PI_WORKTREE}` denote private machine-local evidence roots; these artifacts are not bundled in this repository.
