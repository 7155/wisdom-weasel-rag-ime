# Room Context / Provider Cache 评估

## 结论

- 正式 Pi staged build 已捕获真实 Provider 前的规范化 Context：43,203 bytes；其中 System Prompt 为 40,853 bytes。
- ContextInspection 默认脱敏，不保存 hidden thinking、凭据或二进制正文；Pi JSONL 只返回 hash、bytes、line count、entry types 和 leaf ref。
- 本轮真实 DeepSeek canary 在 Provider 网络阶段返回 `Connection error.`，usage 全为 0。因此缓存能力、稳定前缀命中和 changed-prefix miss 均为 **未证明**，不能用 deterministic Provider 或规范化零值冒充。
- 随后按正式静态 catalog 运行 `gpt/gpt-5.6-luna`；`session.open` 成功，但首轮 `session.prompt` 在 preflight 返回 `PROMPT_REJECTED`。本机 `models.json` 只有环境变量引用，当前 canary 进程拿不到对应 GPT credential，因此同样是 **未证明**，没有伪造 usage/cache 字段。
- production 保持关闭，staged payload 未安装。

## 真实证据

- Pi source: `c4752416150b715b5079549024efd0299fa259e5`
- staged manifest SHA-256: `dab863ccdaed917c986855ee5fbf25e21f1342c9af116339be989676b608fab8`
- 固化 receipt: `tests/fixtures/room_context_inspection/real-provider-canary-failed.v1.json`
- GPT receipt: `tests/fixtures/room_context_inspection/real-gpt-luna-canary-failed.v1.json`
- canary command: `scripts/canary_pi_context_cache.py`，正式 runtime RPC 依次执行 `hello -> session.open -> session.prompt -> agent_settled -> session.debug.context`。

## 门禁

1. Provider Context、System Prompt 或真实 usage 任一缺失，canary 立即失败。
2. `usage` 全零表示 unavailable；`input/output > 0` 只证明 usage 可用，不证明缓存支持。
3. 只有正数 `usage.cacheRead` 能证明 cache hit。
4. stable 组使用超过 2k token 的固定无敏感前缀，连续三轮；control 从 System Prompt 首块改变，并比较 stable/control 的 cacheRead 差值。
5. 每个 RPC、`agent_settled` 和 inspection 后原子写证据并 `fsync`；崩溃时保留最后完成阶段与脱敏错误摘要。

## 合同评估边界

合成 fixtures 覆盖普通 Agent、subagent、Room A/B/reviewer、同 Root 新 Post、A -> B -> A、compaction/recovery、新 Root、旧 generation、重复 JSONL 和 crash tail。它们只证明 fail-closed 合同，不作为真实 Provider 缓存命中证据。
