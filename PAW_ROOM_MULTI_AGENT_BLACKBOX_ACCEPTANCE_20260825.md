# PAW Room 多 Agent 黑盒验收记录（2026-08-25）

## 结论

PAW Room 的后端协作主链已通过一轮全新 8 参与者黑盒和一轮行星间真实消息复验：Harness 能从自然用户目标自行建立文档合同、按依赖动态拆分并并发派发、让伙伴使用私有 Tool Agent、以异步 receipt + durable wake 汇合、由主管做显式双轴验收，并在必要时追加独立 Reviewer。两个 Root 均只有一个 `turn_completed`，没有 `turn_failed`。

本记录不把后端通过冒充为整机前端通过。旧前端在 Gateway 重启后的 Room 活跃态重建仍出现“最后 Root 已完成但 composer 仍进入 steer”的 P0；该问题已附精确 Room/root/event 证据转交 `main` 前端修复，合并前必须单独通过前台复验。

## 验收对象与环境

- 审查分支：`codex/room-recovery-eight-partners-20260825`
- 黑盒项目：隔离测试目录 `paw-room-eight-blackbox-20260825`（不纳入产品 Git）
- Room：`room:c70ea0c0-a004-4a19-8d3f-7a21c13c8acf`
- 参与者：8 个，包括主管 Earth 与最多 7 个可见行星伙伴
- 黑盒期间临时模型：全部 `openai-codex/gpt-5.6-luna` / `max`，用于缩短验收时间
- 验收后生产路由已恢复：Primary `gpt-5.4/high`、Room Coordinator `gpt-5.6-sol/high`、Subagent/Tool Agent `gpt-5.6-luna/max`
- PAW Browser：只使用 PAW 同窗 Browser 检查旧前端；没有调用用户外部 Chrome

## 主黑盒流程网络

主 Root：`room-turn:f2b3e9cd-cf4c-46ac-97cc-9893aa96da4b`

1. 用户只提交自然语言目标，没有手工拆 WorkItem、派伙伴或逐步调用 Tool。
2. Earth 自行建立 Root WorkDocument、lossless 需求账本、`AGENTS.md` 与 `docs/` 索引。
3. Harness 根据依赖只启用两个真正可并行的生产 lane，没有为了展示而占满所有伙伴：
   - Mars：`room-work:069109d0-20bb-4a14-be2b-e4436cbd93e1`，负责章节 01–04。
   - Venus：`room-work:4b23efb4-9477-494c-b072-c5cf332b1c25`，负责章节 05–07。
4. Venus 的私有 Tool Agent 真实并行完成 2 个子任务；Mars 的额外 Tool Agent 因全局并行上限被拒后由 Mars 自己继续，没有把 Tool 失败伪装成任务失败。
5. 两个伙伴完成后只进入 submitted/review；Earth 依据 expected revision、运行可操作性、需求满足度和证据引用分别显式 `accept`。
6. 因文档交付复杂度，Earth 条件式追加 Jupiter 独立 Reviewer：`room-work:13a461de-19cf-4e15-a307-4686b0b4aafd`。Reviewer 发现 Root WorkDocument 缺终态修订，Earth 修正后再汇合。
7. 最终 `room_post(kind=result)` 位于 sequence 1535，Goal complete receipt 位于 1540，唯一 `turn_completed` 位于 1566；观察 20 秒后没有第二个终态。

## 双轴验收证据

三个 WorkItem 最终均为 `done`，但不是由伙伴提交自动闭环：

| WorkItem | 伙伴提议 | 主管复核 | Reviewer |
| --- | --- | --- | --- |
| `room-work:069109d0...` | passed / satisfied | passed / satisfied | Earth |
| `room-work:4b23efb4...` | passed / satisfied | passed / satisfied | Earth |
| `room-work:13a461de...` | passed / satisfied | passed / satisfied | Earth |

每项的 `review_evidence_refs_json` 都绑定具体章节 SHA-256、Worker/Reviewer WorkDocument revision 或检查脚本 SHA-256。Partner 的结论只是 proposed verdict；最终 review verdict 和 reviewer participant 由主管显式写入。

## 文档正确性

黑盒项目生成并维护：

- `AGENTS.md`
- `docs/README.md`
- `docs/agent/requirements.md`
- Root、Worker 与 Reviewer WorkDocument，以及 ACTIVE/ARCHIVE 索引
- `docs/release-runbook/01-preparation.md` 至 `07-incident-review.md`
- `docs/verification/consistency-check.md`
- `docs/verification/final-result.md`
- `tools/check_docs.py`

项目内真实运行 `python3 tools/check_docs.py` 通过，回执包括 7/7 章节交叉引用、本地链接检查、每章固定字段、统一术语、外部 URL=0、网络访问=0。Reviewer 另外检查了文档边界，没有把真实构建、生产发布或回滚写成已经发生。

## 行星消息合同复验

第一次复验暴露真实身份合同缺陷：前端显示 Earth/Mars/Venus/Jupiter，但 `room_partner list` 只向模型提供 Agent 1/2/3/4，主管正确拒绝猜测 Participant ID。

修复后，`list` 与 `peer_list` 同时提供稳定 `celestialName`。第二 Root `room-turn:3e42a894-44db-42e5-af91-20d586fb8bea` 的真实证据为：

- Earth 调用 `peer_ask`，目标为 Jupiter 的 participant `participant:acb9bcad-c628-496d-a7d6-7b834777c776`。
- ask `room-message:5f27bffb-0644-4e3e-911e-9aa6530b497d`：queued → delivered → replied。
- reply `room-message:fffc1b75-83ae-4135-b84f-d6a5e92e1abb`：Jupiter → Earth，状态 delivered，正确绑定 `reply_to_message_id`。
- Earth 读取回复并公开汇总；sequence 1621 只有一个 `turn_completed`，没有创建 WorkItem、没有改项目文件。

这轮复验同时证明 `agent_room_prompt_context.py` 的普通 intercom hard-tail 修复有效；修复前遗留失败记录明确写着局部变量 `work_item_id` 未绑定，修复后的新 ask/reply 均无 error。

## Browser/Ego 与前端边界

PAW 同窗 Browser 已用于真实 DOM 读取、Room 打开、同步重试、composer 输入和发送尝试。它确认了 Browser 控制路径可用于代码驱动的前台验证，也确认测试没有跳到外部 Chrome。

旧前端同时复现一个独立 P0：Room 最新 Root 已由事件 1588 `turn_completed`，主持 Session API 为 `idle`，但 `#/agent` 刷新后仍显示“当前任务仍在执行”，把新消息错误提交给 steer 并显示“Room 消息没有发送”。后端新的 message API 可以正常启动下一 Root，因此归属为前端 snapshot/history/SSE 重建问题。该问题必须由最新 `main` 前端修复后再做最终整机门禁。

## 自动化回归

最终受影响模块回归：

```text
python3 -m unittest \
  tests.test_agent_definitions \
  tests.test_agent_event_projection \
  tests.test_agent_room_partner_application \
  tests.test_agent_room_partner_revision_loop \
  tests.test_agent_room_partner_async_application \
  tests.test_agent_room_partner_restart_recovery \
  tests.test_agent_room_prompt_budget \
  tests.test_agent_rooms \
  tests.test_agent_service \
  tests.test_agent_tools \
  tests.test_browser_control

Ran 324 tests in 477.930s
OK
```

另有聚焦行星别名合同回归：22 tests / OK。测试期间出现既有 SQLite `ResourceWarning`，未造成失败；它不作为本轮功能阻塞，但也没有被宣称为已修复。

## 已修正的产品行为

- Room 最多 8 个可见参与者，按任务动态决定实际伙伴数量。
- `delegate_batch` 支持 2–7 个伙伴并行，而不是固定 4 个。
- Partner completion 只进入 review；主管显式 accept/return。
- accept 携带 revision、双轴 verdict、证据和理由；不允许把 failed/unverified 直接升级为通过。
- 委派返回异步 receipt，以 durable wake/collect 汇合；包含恢复、幂等与取消账本。
- 新输入能从旧失败/重试根正确建立 retry 关联。
- 提示词分段预算强制保留用户请求、WorkItem 身份、尾部规则和 `</room-context>`。
- SSE gap 为当前订阅者的合成帧，不污染共享历史。
- Browser/Ego 控制优先使用 PAW 管理的浏览器，不回退启动外部 Chrome；修复 host marker 与 zombie PID。
- 行星别名进入后端工具合同，模型不再靠 UI 映射猜 Participant ID。

## 未夸大的边界

- 本轮没有证明所有任意复杂任务都会一次成功；证明的是一条真实复杂文档 Goal 和一条伙伴询问链能闭环。
- 独立 Reviewer 是按风险/文档需要条件式创建，不是每个任务强制增加一层。
- Browser 后端与同窗控制已验证；旧前端 stale-running P0 需最新 `main` 修复后再验收。
- 本记录没有把黑盒项目加入产品 Git 历史；它是隔离测试数据与审计证据。
