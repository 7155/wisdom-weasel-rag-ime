# Minecraft Harness Session / Room 前端测试包

这不是演示剧情，也不是生产 store。它来自 2026-08-24 至 2026-08-25
安装版 PAW 对一个原创 3D 体素生存游戏 Goal 的真实黑盒运行，供 Agent
Session、Room、伙伴卫星、WorkItem、失败恢复和长时间线前端开发使用。

视觉与交互基线已经位于远端 `main`：
[`../../../docs/references/pawos-conversation-baseline.html`](../../../docs/references/pawos-conversation-baseline.html)。
该 HTML 是参考，不是生产 App，也不能代替下面的真实 Runtime projection。

## 从哪里开始

1. `manifest.json`：文件、计数、角色与项目 ZIP 索引。
2. `scene-index.json`：四个可直接定位的 UI 场景及 sequence 范围。
3. `room/snapshot.json`：生产 `agent.room.snapshot` 形状，含最新 373 条事件。
4. `room/history.jsonl`：完整 3261 条公开 Room chronology；必须先经
   `parseRoomEvent` 和 Room reducer，禁止一条事件渲染一张卡。
5. `sessions/*.snapshot.json`：Facilitator、Reviewer、Core 与 UI Partner
   四个生产 `agent.session.snapshot` 形状；对话与 Agent 轨迹应从同一
   projection 派生，而不是复制两份聊天正文。
6. `project/minecraft-harness-project.zip`：真实可玩项目，含源码、测试、
   构建产物和项目 `docs/agent/`；`project/files.json` 是 Files App 可用的
   目录/大小/hash 索引。
7. `ACCEPTANCE.md`：该运行的独立验收结论与故障边界。

## 必须覆盖的显示状态

- 四位伙伴真实并行与各自独立 Session；
- 长 Tool 活动折叠、Tool Agent timeout/abort、伙伴 submitted/review；
- Browser Provider 失败、旧失败在新输入后不再保留主重试操作；
- `workspace_job` orphan 后重启、durable wake 与一次“继续”恢复；
- Browser/Ego 最终成功、唯一 Root final 与自然 `turn_completed`；
- Reviewer 明确 `FAILED/UNVERIFIED`，但 Facilitator 错误 accept 的矛盾态；
- 超长 Room 历史分页、实时尾部、刷新后 scroll/focus 保持。

## 隐私与真实性边界

- schema、事件类型、sequence、时间、状态、正文关系和成功/失败均来自
  真实安装态运行；源 UUID、hash 和本机路径已换成稳定 alias。
- 不包含系统提示词、凭据、Cookie、浏览历史、其他 Session、Provider
  私有上下文或无关本机日志。
- `project.zip` 是原创测试产物，不含 Mojang/Minecraft 代码、素材、音乐
  或商标；它是核心 MVP，不是完整 Java 版复刻。

重新导出只用于同一 canary 的受控刷新：

```bash
python3 scripts/export_minecraft_harness_fixture.py \
  --room-id room:... \
  --project-root /path/to/project \
  --room-jsonl /path/to/room.jsonl \
  --acceptance-report /path/to/report.md \
  --output e2e/fixtures/minecraft-harness-20260825
```
