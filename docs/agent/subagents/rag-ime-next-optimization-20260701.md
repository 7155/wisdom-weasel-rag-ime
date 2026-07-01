# RAG-IME 下一轮并行优化复查

- 日期: 2026-07-01
- 角色: read-only auxiliary worker
- 约束: 不修改 `rag_ime/local_sqlite_core.py` 和 `tests/test_local_sqlite_core.py`
- 结果: 本轮只新增本文档, 未改代码

## 已读文件

实现:

- `rag_ime/codex_history.py`
- `rag_ime/debug_server.py`
- `rag_ime/rime_sidecar.py`
- `rag_ime/suggestion_compiler.py`
- `rag_ime/predictor.py`
- `rag_ime/history_context.py`
- `rag_ime/adapter.py`
- `rag_ime/payloads.py`
- `rag_ime/models.py`
- `rag_ime/embeddings.py`
- `rag_ime/core_client.py`
- `rag_ime/cli.py`
- `rag_ime/renderer.py`
- `debug/app.js`

测试:

- `tests/test_codex_history.py`
- `tests/test_rime_sidecar.py`
- `tests/test_debug_server.py`
- `tests/test_predictor.py`
- `tests/test_adapter.py`

文档:

- `README.md`
- `docs/codex-history-eval.md`
- `docs/debug-surface.md`
- `docs/shared-core-adapter-contract.md`
- `docs/local-model-prediction-benchmark.md`
- `docs/wisdom-weasel-issues-map.md`
- `docs/rime-squirrel-framework-decision.md`
- `docs/macos-frontend-adapter.md`
- `docs/interview-project-difficulties.md`
- `docs/interview-project-notes.md`
- `docs/ux-design-v0.md`
- `docs/eval/codex-history-cases.example.jsonl`
- `docs/agent/notes.md`
- `docs/agent/chat-summary.md`
- `squirrel-patches/README.md`

刻意未读/未改:

- `rag_ime/local_sqlite_core.py`
- `tests/test_local_sqlite_core.py`

只看了 `git diff --stat -- rag_ime/local_sqlite_core.py tests/test_local_sqlite_core.py`, 用来确认主线程锁定文件仍有未提交改动。

## 当前判断

项目的主边界是成立的:

- Rime/Squirrel 负责 raw pinyin、词库、候选页和数字键基础体验。
- RAG/记忆和本地小模型只作为 side candidates, 不替代拼音解析。
- debug page 负责 pipeline、cache、vector、payload 观测; 真实 IME 面板保持小面积。
- `history_context -> predictor` 已经把最近 committed input 合进模型预测。
- `/rime-suggest` 已有语义 cache key、trigger guard、vector state invalidation 和 side slot 策略。

因此下一轮不宜大改框架。更值得做的是小而可验收的质量补丁。

## 最有价值的后续优化

### 1. Codex history 噪声过滤/降权

建议文件:

- `rag_ime/codex_history.py`
- `tests/test_codex_history.py`
- `docs/codex-history-eval.md`

问题:

- 当前 importer 已过滤 system/developer/context/tool-output 常见片段, 但真实 eval 里仍可能出现类似 `[319] tool apply_patch call` 的 assistant/tool 转录。
- 这些记录会污染个人记忆库, 也会把召回优化带偏: rerank 可能学会匹配工具日志, 而不是用户决策和项目结论。

建议:

- 新增一个更窄的 `_looks_like_tool_trace_fragment()`。
- 只过滤明显的运行转录, 例如行首形态是 `[\d+] tool ... call`, `tool ... call`, `function_call`, `function_call_output`, `Chunk ID:`, 大段 patch/tool stdout。
- 不要简单过滤所有包含 `tool call output` 的普通说明文字, 因为文档/总结里可能正是在解释噪声过滤策略。
- dry-run 报告可加 `filteredRuntimeSamples` 或先只在测试里覆盖, 避免泄露私密长文本。

风险:

- 过度过滤会删掉有价值的 assistant 总结。
- 如果过滤规则太宽, `codex-history-noise-filter` 这类评测 case 反而会缺少描述性证据。

测试:

- 在 `tests/test_codex_history.py` 增加 fixtures:
  - bracketed tool call transcript should be skipped;
  - normal assistant summary mentioning "tool call output" should be kept;
  - user decision text should be kept.
- 跑:
  - `python3 -W ignore::ResourceWarning -m unittest tests.test_codex_history`
  - 真实库 dry-run: `python3 -m rag_ime.cli import-codex-history --path "$HOME/.codex/sessions" --dry-run --limit 50 --sample-size 10`
  - 34-case eval 对比 pass/top1/noiseRate。

### 2. 输入法候选压缩: 从首句截断升级为候选化策略

建议文件:

- `rag_ime/suggestion_compiler.py`
- `tests/test_adapter.py`
- `tests/test_rime_sidecar.py`
- `docs/ux-design-v0.md`

问题:

- `SuggestionCompiler` 目前主要依赖 `first_sentence()` 和 `truncate_text()`。
- 这能保证小面积, 但对 RAG 段落不够好: 首句可能是背景铺垫, 真正可插入内容在第二句或项目符号里。

建议:

- 保持 JSON contract 不变: `surface_text` 短, `metadata.insert_text` 可长。
- 新增内部 `compress_surface_text(source_text, tags)`:
  - 优先抽取包含 query/project/action 词的短句或项目符号;
  - 删除明显的源码路径、日志前缀、时间戳、纯命令片段;
  - 对 `structure/template/style_hint` 保留更强类型信号;
  - `surface_text` 目标 18-32 字, 上限继续由 `CompilerOptions.max_surface_chars` 控制。

风险:

- 压缩太激进会改变用户真正想插入的语义。
- 如果把 `insert_text` 也压缩, 会破坏 RAG 候选作为段落/模板的价值。应该只压缩 `surface_text`, 保留 full insert。

测试:

- 在 `tests/test_adapter.py` 加长段落、多 bullet、命令日志、style hint 的候选压缩用例。
- 在 `tests/test_rime_sidecar.py` 确认 side candidate 的 `text` 短、`insertText` 保留完整。
- 跑:
  - `python3 -W ignore::ResourceWarning -m unittest tests.test_adapter tests.test_rime_sidecar`
  - `python3 -m rag_ime.cli --core-mode fixture acceptance`

### 3. VCP 风格缓存命中: 先做 embedding exact cache 和 in-flight dedupe

建议文件:

- `rag_ime/embeddings.py`
- `tests/test_codex_history.py` 或新增窄测试文件
- `docs/codex-history-eval.md`

问题:

- 现有缓存已经覆盖两层:
  - `/rime-suggest` 短 TTL semantic cache;
  - local core suggestion LRU cache。
- 真正接入 WSL/local embedding endpoint 后, 最慢且最容易重复的是同一个 query/text 的 embedding 请求。

辩证参考 VCP:

- VCP 的 vector/cache/pending request 思路值得迁移。
- 但输入法请求更短、更高频, 不能引入复杂全局缓存导致输入路径不可解释。

建议:

- 给 `OpenAICompatibleEmbeddingProvider` 外包一层可选 exact text cache:
  - key = provider fingerprint + normalized text;
  - value = normalized vector;
  - bounded LRU, 默认 256 或 512;
  - 失败/空 vector 不长时间缓存, 最多短 TTL。
- 如果后续 debug server 变为异步, 再加 in-flight dedupe; 现在同步 CLI/HTTP 路径可以先不复杂化。

风险:

- embedding provider、dimensions、extra_body 改变后必须换 fingerprint, 否则会混用旧向量。
- 对长文 backfill 缓存收益有限; 对 IME 重复 query 收益更大。

测试:

- mock `/v1/embeddings` handler 统计同一 text 的请求次数。
- 同一 query 重复调用只 hit 一次远端。
- provider fingerprint 改变后必须 miss。
- `eval-codex-history --repeat 3` 观察 embedding handler call count 和 latency。

### 4. 历史输入上下文进入小模型预测: 拆成 typed lanes

建议文件:

- `rag_ime/history_context.py`
- `rag_ime/debug_server.py`
- `rag_ime/rime_sidecar.py`
- `tests/test_debug_server.py`
- `tests/test_predictor.py`

问题:

- 当前 `build_prediction_context()` 把 explicit recent context 和 recent committed history 合成一段文本。
- 这已经能工作, 但后续模型预测容易被混杂上下文影响: active document tail、accepted memory、typed history 的作用不同。

建议:

- 暂不改 provider API, 先把字符串格式稳定成分段:
  - `历史输入: ...`
  - `当前上下文: ...`
  - 后续可加 `已接受记忆: ...`
- 加 option 或内部 helper, 确保每段有固定顺序、固定前缀、固定长度上限。
- debug payload 保持 `historyContext`, 但可以新增 `historyContextParts` 供 debug page 展示。

风险:

- 改 prompt/context 格式可能影响本地模型候选, 需要和 `eval-prediction` 同步验证。
- 过多字段会让 IME 面板变复杂; 只在 debug payload 展示, 不进入真实面板。

测试:

- `tests/test_debug_server.py` 断言 model provider 收到的 context 包含 typed prefix。
- `tests/test_predictor.py` 维持 provider fail-open 和 parser 行为不变。
- 用 mock model 跑 `eval-prediction`。

### 5. Debug observability: 把缓存/触发/噪声原因放进评测报告

建议文件:

- `rag_ime/codex_history.py`
- `rag_ime/cli.py`
- `debug/app.js`
- `docs/debug-surface.md`

问题:

- 当前 eval 已有 pass/top1/MRR/noiseRate/latency/cacheStats/vectorStats。
- 但下一轮优化会同时调 importer、cache、candidate compiler 和 predictor, 需要知道失败 case 是召回不到、召回到了但候选压缩不对, 还是 cache/trigger 没跑。

建议:

- 对每个 failed case 输出更小的 diagnostic:
  - top candidate source types;
  - query basis / trigger reason when走 rime-suggest;
  - whether candidate evidence contains forbidden terms;
  - optional importer/runtime-noise count。
- 保持隐私: 默认只显示短 surface 和指标, 不 dump full evidence。

风险:

- eval JSON 变大, 真实 Codex 历史容易泄露更多片段到终端。
- 因此只加短字段, 或加 `--diagnostic` 开关。

测试:

- `tests/test_codex_history.py` 验证报告 schema。
- 真实 34-case eval 只看 summary 和 failed case ids。

## 建议先做的最小 patch

先做 `Codex history tool-trace noise filter`。

原因:

1. 不碰主线程锁定的 `local_sqlite_core.py` / `test_local_sqlite_core.py`。
2. 直接改善真实个人记忆库质量, 避免后续 rerank/vector/model 在脏 corpus 上调参。
3. 与当前 34-case gold set 的 `codex-history-noise-filter` 对齐。
4. 测试入口清楚, 只需要 `tests/test_codex_history.py` 和真实 dry-run/eval。

最小实现范围:

- `rag_ime/codex_history.py`
  - 新增窄规则 `_looks_like_tool_trace_fragment(text)`;
  - 在 `_extract_clean_text_fragments()` 里追加过滤;
  - 保留普通说明文字。
- `tests/test_codex_history.py`
  - 增加一个 "tool transcript skipped but explanatory summary kept" 测试。
- 可选文档:
  - `docs/codex-history-eval.md` 追加一行说明 tool transcript filtering。

验收:

```bash
python3 -W ignore::ResourceWarning -m unittest tests.test_codex_history
python3 -m rag_ime.cli import-codex-history --path "$HOME/.codex/sessions" --dry-run --limit 50 --sample-size 10
python3 -m rag_ime.cli --db-path /private/tmp/rag-ime-noise-filter-check.sqlite import-codex-history --path "$HOME/.codex/sessions" --project wisdom-weasel-rag-ime --limit 5000 --sample-size 0
python3 -m rag_ime.cli --db-path /private/tmp/rag-ime-noise-filter-check.sqlite eval-codex-history --cases-file docs/eval/codex-history-cases.example.jsonl --top-k 5 --match any --repeat 1
```

## 不建议马上做的事

- 不要现在把 VCP 的完整 hybrid/vector/cache 体系搬过来。输入法的瓶颈和 Agent prompt cache 不完全一样, 先用小 patch 证明收益。
- 不要让本地小模型处理 raw dirty pinyin。这个边界已经被 Rime/Squirrel/Wisdom-Weasel 研究反复确认。
- 不要把 debug page 的 pipeline 信息搬到真实 IME 面板。真实面板继续只显示短候选和一行 evidence hint。
- 不要在主线程召回修复提交前改 `local_sqlite_core.py`, 避免互相覆盖。

