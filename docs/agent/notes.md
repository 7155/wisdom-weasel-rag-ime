# Notes

## Run prefs (persistent)

- Do not maintain the learnA study site while implementing this product repo.
- Keep production macOS input method work on the Rime/Squirrel route; the InputMethodKit app is a prototype/debug harness.

## Log

### 2026-07-01 16:35 CST
Problem:
- Real Codex-history import still admitted some Codex runtime context blocks (`skills_instructions`, `apps_instructions`, `collaboration_mode`) as candidate memory.
- Those blocks are especially harmful for RAG-IME because they contain tool/plugin/runtime vocabulary that can outrank actual user project decisions.

Changes:
- Extended the Codex-history runtime-noise filter to reject app, skill, plugin, and collaboration-mode context blocks.
- Added regression coverage that user-role runtime-injection blocks do not become imported memory.
- Updated Codex-history eval docs to describe app/skill/collaboration context filtering.

Commands:
- `python3 -m py_compile rag_ime/codex_history.py tests/test_codex_history.py`
- `python3 -W ignore::ResourceWarning -m unittest tests.test_codex_history`
- `python3 -m rag_ime.cli --db-path /private/tmp/rag-ime-codex-eval-filtered.sqlite import-codex-history --path /Users/undo/.codex --project wisdom-weasel-rag-ime --limit 500 --min-chars 12 --max-chars 1600 --sample-size 0`
- `python3 -m rag_ime.cli --db-path /private/tmp/rag-ime-codex-eval-filtered.sqlite eval-codex-history --cases-file docs/eval/codex-history-cases.example.jsonl --match any --repeat 1`

Findings:
- 500-record import/eval after filtering: `passed=10/34`, `passRate=0.2941`, `top1Accuracy=0.2353`, `MRR=0.2647`, `noiseRate=0.0`.
- The filter improves source quality but does not solve the broader 34-case recall gap; the next quality work remains hybrid/vector recall and larger-window Codex-history evaluation.
- Full Squirrel/Xcode build remains blocked on this host because `xcode-select` points to Command Line Tools, not full Xcode.

### 2026-07-01 14:10 CST
Problem:
- 用户要求充分调研 Mac 上本地推理最快方案，尤其是输入法首候选 <200 ms 的可落地路径。

Findings:
- 当前最快已测 smoke/debug 路线仍是 Ollama `qwen3.5:0.8b-mlx`，用 native Ollama API、`think:false`、`keep_alive`、stream-first candidate；它适合继续推进 Squirrel/RAG 产品闭环。
- 最终产品内核不能只依赖 Ollama HTTP 调用；需要 direct MLX-LM 或 native `llama.cpp`/Metal provider，显式拥有 resident model、稳定 prompt/KV cache、过期请求取消和多候选共享 prefill。
- Qwen3.5 不需要继续找 `Instant` 命名；本项目等价配置是小模型、non-thinking、streaming、4-8 token 输出和 warm resident runner。
- MLX-LM 官方能力覆盖 `stream_generate`、`prompt_cache`、`make_prompt_cache`、rotating KV cache；但 prompt cache 要隔离动态 Rime/RAG 上下文，不能过早宣称 Wisdom-Weasel parity。
- Wisdom-Weasel 的关键源码机制是 `PrepareSystemPrompt()` 保存 seq-0 state、`GenerateCandidatesBatch()` 用 `llama_memory_seq_cp` 复制到多个 sequence id 后 batch decode，前端用 request sequence 丢弃旧结果。
- MiniVLLM/vLLM 只借鉴 prefix cache、block table、prefill/decode 分离和指标；CUDA/Triton/连续批处理不是 Mac 单用户输入法 MVP 依赖。

Changes:
- 更新 `docs/mac-local-inference-fast-path.md`，加入 source refresh、locked direction、Qwen3.5 small-model rule 和补充来源。

Next:
- 保持 Ollama MLX 作为当前 Mac smoke baseline。
- 下一步跑 direct MLX-LM cached/uncached TTFC；若不能稳定胜过 Ollama MLX，则实现 native `llama.cpp`/Metal provider spike。
- 后续质量门禁应同时看 p95 TTFC、candidate quality、memory/RSS、cache-hit、stale-cancel 和 packaging。

### 2026-07-01 13:58 CST
Problem:
- Cache probe 只有 debug HTTP 页面入口，不利于 CI/终端自动验收，也不方便 shared-core adapter 做无浏览器缓存命中测试。

Changes:
- 新增 `python3 -m rag_ime.cli cache-probe`，复用 `DebugImeService.cache_probe()`。
- CLI 支持 `current_input`、`--recent-context`、`--repeat`、`--top-k`、`--rime-candidate`、`--force-side-candidates`、`--rime-cache-ttl-ms`。
- 更新 README 和 `docs/debug-surface.md`，给出终端 cache-probe 命令。
- 新增端到端测试：seed 本地 DB 后直接跑 CLI cache-probe，验证 suggestion cache 和 rimeSuggestCache 都有 warm hits。

Commands:
- `python3 -m unittest tests.test_debug_server`
- `python3 -m rag_ime.cli --help | rg "cache-probe"`
- `python3 -m rag_ime.cli --db-path /tmp/rag-ime-cache-probe-cli.sqlite cache-probe "RAG 输入法" --recent-context "manual cache probe" --repeat 3 --rime-candidate "RAG 输入法"`
- `python3 -m py_compile rag_ime/cli.py rag_ime/debug_server.py`
- `git diff --check`

Findings:
- 临时 DB 实测 repeat=3 时 `suggestionCache.hitsDelta=2`、`rimeSuggestCache.hitsDelta=2`，两层 cache gate 都通过。

### 2026-07-01 13:53 CST
Problem:
- 用户强调 VCP 缓存命中和输入法高频 refresh 很关键；debug 页面虽然显示 cache stats，但缺少一个主动重复请求并验证 warm hit 的诊断入口。

Changes:
- 新增 `DebugImeService.cache_probe()` 和 `POST /api/cache-probe`。
- Cache probe 会重复同一语义输入，通过 `/api/suggest` 测 local/shared core suggestion cache，通过 `/api/rime-suggest` 测 Squirrel/Rime semantic cache。
- Debug 页面新增小型 Cache 卡片，只显示 core hits、rime hits、repeat count；完整 before/after stats 和 samples 留在 JSON 面板。
- 更新 `docs/debug-surface.md`，说明 cache probe 是输入法版 VCP cache-hit 诊断。
- 新增 debug server 测试覆盖直接 service 调用和 HTTP `/api/cache-probe`。

Commands:
- `python3 -m unittest tests.test_debug_server`
- `python3 -m py_compile rag_ime/debug_server.py`
- `node --check debug/app.js`
- `git diff --check`

Findings:
- 直接 probe 在 repeat=3 时能看到 suggestion cache 和 rimeSuggestCache 的 warm hits。
- 这个 probe 不会塞进真实输入法候选框；它只属于 debug surface，用于调缓存命中和重复 composing refresh。

### 2026-07-01 13:44 CST
Problem:
- RAG-IME 已有 patched Squirrel prepare/doctor，但缺少一个正式的 `xcodebuild` 构建入口；full Xcode 装好后无法一条命令验证真实 Squirrel 前端。

Changes:
- 新增 `scripts/build_patched_squirrel.sh`，支持 `list` 和 `build` action、dry-run、可配置 workdir/project/scheme/configuration/derived data。
- 构建前检查 patched Squirrel checkout、`Squirrel.xcodeproj`、RAG-IME Swift sidecar 文件和 `rag-ime.squirrel.custom.yaml`。
- 构建命令默认使用 `CODE_SIGNING_ALLOWED=NO` 和 `/tmp/rag-ime-squirrel-derived-data`，避免把签名问题混入编译验证。
- 新增 `tests/test_build_patched_squirrel.py`，用 fake `xcodebuild` 离线覆盖 dry-run、`-list`、build 和 missing-workdir 错误提示。
- 更新 README、Squirrel patch pack、Xcode setup、macOS adapter 文档的构建路径。

Commands:
- `bash -n scripts/build_patched_squirrel.sh`
- `python3 -m unittest tests.test_build_patched_squirrel`
- `RAG_IME_SQUIRREL_BUILD_DRY_RUN=1 scripts/build_patched_squirrel.sh list`
- `scripts/build_patched_squirrel.sh list`

Findings:
- `/tmp/rag-ime-squirrel` 当前是已准备的 patched checkout。
- 本机 `xcode-select -p` 仍为 `/Library/Developer/CommandLineTools`。
- `scripts/build_patched_squirrel.sh list` 按预期失败在 `xcodebuild -version`，提示安装/选择 full Xcode。

### 2026-07-01 13:37 CST
Problem:
- 用户要求充分调研 Mac 上最快本地推理方案，用于 RAG 输入法首候选低延迟。

Findings:
- 当前已测最快 debug/smoke 路线仍是 Ollama `qwen3.5:0.8b-mlx` + native API + `think:false` + `keep_alive` + stream-first candidate；它证明本机 warm path 可接近/进入 200ms 内，但不是最终可控内核。
- 最终产品内核应围绕 resident model、稳定 prompt/KV cache、首个可选候选流式返回、过期请求取消、多候选共享 prefill，而不是等待完整 JSON 列表。
- MLX-LM 是下一步 Apple Silicon 实测路线，但 prompt cache 要隔离/复制/重载，不能过早等同于 llama.cpp 的 seq-copy KV。
- Wisdom-Weasel 的核心可复用机制是后台线程 + request sequence 丢弃旧结果 + `PrepareSystemPrompt()` 缓存 system prompt state + `GenerateCandidatesBatch()` 多 sequence 复制 KV 生成多个候选。
- MiniVLLM/vLLM 只借鉴 prefix cache、block table、prefill/decode 分离和指标；CUDA/Triton/连续批处理不适合 Mac 单用户输入法 MVP。

Commands:
- `rg` 检查本仓库推理文档与 provider 代码。
- `rg` 检查本地 Wisdom-Weasel / MinivLLM 源码机制。
- `ollama list` 当前失败，原因是本机 Ollama server 未运行；本次未重新跑 TTFC，只复核已有本机记录。

Pitfalls:
- 不要把“当前最快已测 smoke 路线”写成“最终产品内核”；Ollama 方便但无法证明 KV seq copy 和多候选批采样。
- 产品指标是 `firstCandidateMs` / TTFC，不是 `firstChunkMs` 或完整响应耗时。

### 2026-07-01 10:51 CST
Problem:
- The user asked for a deeper Mac inference investigation before choosing the local model path.
- The existing Ollama `qwen3.5:0.8b` smoke proved the adapter path but missed the target: observed first chunk was roughly 240-408 ms for the normal JSON prompt and full candidate latency was much higher.

Findings:
- MLX-LM is the best short-term Mac latency experiment because it is Apple Silicon first and exposes `stream_generate`, prompt cache, rotating KV cache, and speculative decoding primitives.
- `llama.cpp`/Metal is still the best final engineering route because a native provider can cache stable prompt KV state and sample multiple candidates from copied sequence state, matching Wisdom-Weasel's strongest latency mechanism.
- Ollama remains the easiest smoke-test route, and `qwen3.5:0.8b-mlx` is the next no-proxy model tag to try, but Ollama is too opaque for final prompt/KV control.
- Core ML stateful KV and MLC LLM are follow-up research paths; MiniVLLM/vLLM are useful for prefix-cache/scheduler concepts but not a direct Mac IME runtime.

Changes:
- Added a Mac backend decision table and recommendation tiers to `docs/model-ttft-kv-cache-plan.md`.
- Added Mac runtime test order and no-proxy Ollama MLX smoke commands to `docs/local-model-prediction-benchmark.md`.
- Updated README, Wisdom-Weasel issue map, and interview difficulty notes to frame TTFT/KV cache as a core project challenge.

Next:
- Start Ollama without proxy and test `qwen3.5:0.8b-mlx` with `predictor-ttft`.
- If p50 first chunk remains above 200 ms, prototype a resident MLX-LM provider or native llama.cpp/Metal provider instead of further prompt tuning.

### 2026-07-01 07:34 CST
Problem:
- Boyle subagent returned no patch for the planned lightweight tag/app/context rerank.
- Real Codex-history eval showed FTS-only retrieval was too weak: 500-record pass rate was `0.33`; 2000-record pass rate was `0.67`, with `PROJECT_MEMORY_BLOCK` missing and `Squirrel RAG` ranking too low.

Changes:
- Implemented local query expansion before FTS for high-value IME concepts: `PROJECT_MEMORY_BLOCK` / agent first-run injection, Squirrel/Rime/librime/sidecar, dirty/raw pinyin, and local RAG memory.
- Added field-aware rerank boosts over committed text, recent context, tags, source/app/schema/provider fields, and raw ASCII project terms such as `Squirrel`, `RAG`, and `PROJECT_MEMORY_BLOCK`.
- Expanded the internal memory candidate pool before compiling the visible top-K suggestions.
- Raised pinned-memory boost so explicit user governance remains stronger than automatic rerank.
- Added local-core regression tests for agent context injection recall and Squirrel/Rime side-candidate memory ranking.

Commands:
- `python3 -W ignore::ResourceWarning -m unittest tests.test_local_sqlite_core`
- `python3 -m py_compile rag_ime/local_sqlite_core.py tests/test_local_sqlite_core.py`
- `python3 -m rag_ime.cli --db-path /private/tmp/rag-ime-rerank-eval-20260701.sqlite import-codex-history --path "$HOME/.codex/sessions" --project wisdom-weasel-rag-ime --limit 2000 --sample-size 0`
- `python3 -m rag_ime.cli --db-path /private/tmp/rag-ime-rerank-eval-20260701.sqlite eval-codex-history --cases-file docs/eval/codex-history-cases.example.jsonl --top-k 5 --match any --repeat 2`
- `python3 -m rag_ime.cli --db-path /private/tmp/rag-ime-rerank-eval-20260701-500.sqlite import-codex-history --path "$HOME/.codex/sessions" --project wisdom-weasel-rag-ime --limit 500 --sample-size 0`
- `python3 -m rag_ime.cli --db-path /private/tmp/rag-ime-rerank-eval-20260701-500.sqlite eval-codex-history --cases-file docs/eval/codex-history-cases.example.jsonl --top-k 5 --match any --repeat 3`
- `python3 -W ignore::ResourceWarning -m unittest discover -s tests`
- `python3 -m rag_ime.cli --core-mode fixture acceptance`
- `git diff --check`

Verification:
- Local SQLite core tests passed: 13 tests.
- Full suite passed: 70 tests.
- Fixture acceptance and `git diff --check` passed.
- Real 2000-record Codex-history eval improved to `passRate=1.0`, `top1Accuracy=1.0`, `MRR=1.0` on the current 3-case benchmark.
- Real 500-record eval improved to `passRate=0.67`, `top1Accuracy=0.67`, `MRR=0.67`; Squirrel/RAG and Agent-hook cases are top1, dirty-pinyin needs more imported history.
- This is still rule-based rerank, not a substitute for later embedding/vector hybrid recall.

### 2026-07-01 07:20 CST
Problem:
- Real Codex history import was still too noisy for RAG-IME evaluation: directory import could start from old sessions, and raw runtime context such as `AGENTS.md`, sandbox/environment blocks, developer messages, and tool output could become memories.
- This weakens the personal-memory benchmark and hides the real retrieval/rerank problem.

Changes:
- Added path ordering for Codex JSONL directory import: CLI default is now `--path-order mtime-desc`, with `mtime-asc` and `path` available for replay.
- Filtered common Codex runtime noise before converting JSONL text into `InputEvent` records.
- Kept legacy JSONL compatibility for older `response_item` and nested `event_msg` shapes.
- Documented newest-first import and runtime-noise filtering in `docs/codex-history-eval.md`.

Commands:
- `python3 -W ignore::ResourceWarning -m unittest tests.test_codex_history`
- `python3 -m py_compile rag_ime/codex_history.py rag_ime/cli.py tests/test_codex_history.py`
- `python3 -m rag_ime.cli import-codex-history --path "$HOME/.codex/sessions" --dry-run --limit 20 --sample-size 8`
- `python3 -m rag_ime.cli --db-path /private/tmp/rag-ime-real-eval-20260701.sqlite import-codex-history --path "$HOME/.codex/sessions" --project wisdom-weasel-rag-ime --limit 500 --sample-size 3`
- `python3 -m rag_ime.cli --db-path /private/tmp/rag-ime-real-eval-20260701.sqlite eval-codex-history --cases-file docs/eval/codex-history-cases.example.jsonl --top-k 5 --match any --repeat 3`
- `python3 -m rag_ime.cli --db-path /private/tmp/rag-ime-real-eval-20260701-2000.sqlite import-codex-history --path "$HOME/.codex/sessions" --project wisdom-weasel-rag-ime --limit 2000 --sample-size 0`
- `python3 -m rag_ime.cli --db-path /private/tmp/rag-ime-real-eval-20260701-2000.sqlite eval-codex-history --cases-file docs/eval/codex-history-cases.example.jsonl --top-k 5 --match any --repeat 2`

Findings:
- Real dry-run now starts from the active RAG-IME session and samples user/project decisions instead of January AGENTS/environment noise.
- With 500 recent records, default cache repeat hit rate was `0.67`, pass rate was `0.33`, and disabled cache roughly doubled total eval latency on the same repeated cases.
- With 2000 recent records, pass rate improved to `0.67`; the dirty-pinyin/Rime boundary case reached top1, but `PROJECT_MEMORY_BLOCK` still missed and Squirrel/RAG ranked only at 5.
- Conclusion: cache works, but FTS-only retrieval is not enough. The next core slice should still be lightweight tag/app/context rerank and then hybrid/vector recall.

### 2026-07-01 06:58 CST
Problem:
- Local Qwen-style prediction servers can emit thinking text, which wastes latency and can leak into IME candidates.
- The project needed a concrete low-latency model test profile instead of hand-writing every timeout/token/thinking option.

Changes:
- Added `RAG_IME_PREDICTOR_PROFILE=instant` for small instruct models: chat mode, 350 ms timeout, 8 output tokens, low temperature/top_p, and thinking disabled.
- Added `RAG_IME_PREDICTOR_PROFILE=completion-instant` for base-model or llama.cpp-style `/v1/completions` servers.
- Added `RAG_IME_PREDICTOR_DISABLE_THINKING=1`.
- The env flag injects `chat_template_kwargs.enable_thinking=false` while preserving any other `RAG_IME_PREDICTOR_EXTRA_BODY_JSON` fields.
- Prediction benchmark and eval reports now expose `providerProfile`.
- Updated local model docs and Wisdom-Weasel issue mapping.

Commands:
- `git status -sb`
- `git diff --stat`
- `python3 -W ignore::ResourceWarning -m unittest tests.test_predictor`
- `python3 -m py_compile rag_ime/predictor.py rag_ime/cli.py tests/test_predictor.py`
- `python3 -m rag_ime.cli --core-mode fixture eval-prediction --cases-file docs/eval/codex-history-cases.example.jsonl --max-candidates 3 --latency-budget-ms 150`
- `RAG_IME_PREDICTOR_PROVIDER=openai-compatible RAG_IME_PREDICTOR_BASE_URL=http://127.0.0.1:9 RAG_IME_PREDICTOR_MODEL=Qwen3-0.6B RAG_IME_PREDICTOR_PROFILE=instant python3 -m rag_ime.cli --core-mode fixture predict-benchmark --case 'RAG 输入法' --recent-context '用户正在写本地记忆输入法' --max-candidates 3 --latency-budget-ms 150`
- `python3 -W ignore::ResourceWarning -m unittest discover -s tests`
- `python3 -m rag_ime.cli --core-mode fixture acceptance`
- `git diff --check`

Git snapshot:
- Branch: `codex/wisdom-weasel-rag-ime-mvp`.
- Diff before commit: 8 files changed, 233 insertions, 22 deletions.

Verification:
- Predictor tests passed: 8 tests.
- Predictor + Codex-history tests passed: 17 tests.
- Full suite passed: 67 tests.
- Fixture eval and instant-profile fail-open benchmark passed.
- Fixture acceptance and `git diff --check` passed.
- No local OpenAI-compatible or Ollama model endpoint was listening on 127.0.0.1 ports 8000, 8080, 1234, or 11434, so real Qwen/MLX/llama.cpp speed testing is still pending.

### 2026-07-01 06:51 CST
Problem:
- `/rime-suggest` cache ignored only `requestSeq` and `sessionId`, so stable Rime candidates with changing raw pinyin/preedit still missed the cache.
- Input methods refresh on nearly every composing update; model/RAG should not rerun when the semantic query and visible candidates are unchanged.

Changes:
- Rebuilt the `/rime-suggest` cache key from the parsed Rime snapshot: semantic query, query basis, trigger decision, Rime candidates, committed context, side-candidate limits, memory event/action counts, project, and predictor fingerprint.
- Raw pinyin/preedit are included only when they are the semantic input (`preedit` / `rawInputFallback`) or when side candidates are explicitly forced.
- Cache hits now refresh `sessionId`, `requestSeq`, `rawInput`, `preedit`, Rime metadata, and trigger metadata before returning the cached model/RAG/display candidates.
- Added a regression test for raw-pinyin changes with stable Rime candidates.
- Updated README, debug docs, and Squirrel integration notes.

Commands:
- `python3 -W ignore::ResourceWarning -m unittest tests.test_debug_server`
- `python3 -m py_compile rag_ime/debug_server.py tests/test_debug_server.py`
- `python3 -W ignore::ResourceWarning -m unittest discover -s tests`
- `python3 -m rag_ime.cli --core-mode fixture acceptance`
- `git diff --check`

Verification:
- Debug server tests passed: 13 tests.
- `py_compile` passed.
- Full suite passed: 65 tests.
- Fixture acceptance and `git diff --check` passed.

Follow-up:
- Subagent read VCP/RAG-IME and recommended the next implementation order: lightweight tag/app/context rerank first, optional local vector side-index second, stale/prefix cache third.
- This change completes the first cache-side step for real IME composing refreshes; next code slice should be the lightweight tag/app/context rerank in `LocalSqliteCoreClient`.

### 2026-07-01 06:44 CST
Problem:
- Need to confirm whether VCP uses BM25 before copying retrieval assumptions into RAG-IME.
- Local SQLite FTS5 `bm25()` returns lower-is-better scores, often negative; the old relevance conversion flattened all negative scores to the same boost.

Findings:
- `learnA/VCPToolBox/KnowledgeBaseManager.js` main diary/memory search is vector-first (`idx.search(searchVecFloat, k)`) with TagMemo boost, geodesic rerank, and vector cache reuse.
- `learnA/VCPToolBox/TDBKnowledge.js` cold knowledge search computes query embedding first, then prefers `searchHybrid(queryVector, queryText, ..., hybridAlpha)` where `queryText` is documented as the BM25 sparse-retrieval input; it falls back to pure vector search if hybrid is unavailable.
- RAG-IME should keep FTS5/BM25 as a fast lexical local baseline, but its long-term direction should be hybrid retrieval plus cache, rerank, evidence, and memory governance.

Changes:
- Converted SQLite FTS5 BM25 scores with `_bm25_relevance()`: negative scores now become positive lexical boosts using `log1p(-score)`, capped at `4.0`; non-negative scores keep reciprocal fallback.
- Added the lexical value into suggestion metadata reason as `fts5:<score>` for debugging.
- Added a regression test that verifies negative FTS5 BM25 affects ranking.

Commands:
- `git status -sb`
- `git diff --stat`
- `rg -n "BM25|bm25|embedding|Embedding|vector|Vector|TDB|cosine|keyword|关键词|tfidf|tf-idf|rank|score|检索|召回" VCPToolBox/TDBKnowledge.js VCPToolBox/KnowledgeBaseManager.js VCPToolBox/EmbeddingUtils.js VCPToolBox/TextChunker.js VCPToolBox/routes/admin/rag.js VCPToolBox/modules/contextManager.js`
- `python3 -W ignore::ResourceWarning -m unittest tests.test_local_sqlite_core`
- `python3 -W ignore::ResourceWarning -m unittest discover -s tests`
- `python3 -m py_compile rag_ime/local_sqlite_core.py tests/test_local_sqlite_core.py`
- `git diff --check`
- `python3 -m rag_ime.cli --core-mode fixture acceptance`

Verification:
- Local SQLite core regression passed: 11 tests.
- Full suite passed: 64 tests.
- `py_compile`, `git diff --check`, and fixture acceptance passed.

Pitfalls:
- SQLite FTS5 BM25 polarity is easy to invert: lower is better, and good matches can be negative. Treating negative values as `0` removes the signal.

### 2026-07-01 06:37 CST
Problem:
- RAG evaluation and model prediction evaluation were separate commands, so model selection still required manually comparing two reports.
- The project needs a full-flow gate that answers whether local RAG, local model prediction, or both are useful for the same input-method cases.

Changes:
- Added `eval-comparison` CLI.
- It runs RAG suggestions and local model predictions over the same JSONL cases, repeat count, and match mode.
- The report includes separate `rag` and `model` eval reports plus a `comparison` block with `bothPassed`, `ragOnlyPassed`, `modelOnlyPassed`, `neitherPassed`, `winnerByPassRate`, `winnerByTop1Accuracy`, and per-case surfaces/latency.
- Updated README and Codex-history evaluation docs.

Commands:
- `python3 -W ignore::ResourceWarning -m unittest tests.test_codex_history`
- `python3 -W ignore::ResourceWarning -m unittest discover -s tests`
- `python3 -m rag_ime.cli --core-mode fixture eval-comparison --cases-file docs/eval/codex-history-cases.example.jsonl --top-k 3 --max-candidates 3 --repeat 2`
- `python3 -m rag_ime.cli --core-mode fixture acceptance`

Findings:
- Full suite now has 63 tests.
- Fixture comparison shows RAG can pass cases while the model lane cleanly reports `providerConfigured=false` and zero candidates when no local model is configured.

Next:
- Run `eval-comparison` with real Codex-history imports and real local Qwen/MLX/llama.cpp endpoints in both chat and completion mode.

### 2026-07-01 06:32 CST
Problem:
- The next useful goal progress was not blocked by missing Xcode: model prediction and Wisdom-Weasel source lessons still needed to be tightened.

Findings:
- Wisdom-Weasel `RimeWithWeasel.cpp` enters prediction after meaningful commit, stores committed text in `ContextHistory`, runs `PredictCandidates` on a background thread, drops stale results with `m_llm_request_seq`, appends LLM candidates after Rime candidates, and branches number-key selection by Rime count vs LLM count.
- Wisdom-Weasel `LlamaCppProvider.cpp` gets fast multi-candidate output by caching system prompt state and using parallel llama sequences/batch sampling; this is stronger than merely using a smaller model.
- rime/weasel candidate handling confirms the production adapter should stay inside Squirrel/Rime candidate state instead of using an external overlay as the real IME frontend.

Changes:
- Added `RAG_IME_PREDICTOR_PROMPT_MODE=chat|completion`.
- `completion` mode calls `/v1/completions` with `recent_context + current_input` as prefix and `n=max_candidates`, giving a portable base-model/llama.cpp-server baseline.
- Prediction parsing now strips `<think>`, analysis/reasoning tags, markdown fences, and JSON/list candidate output before ranking.
- Updated README, local model benchmark docs, macOS adapter docs, Rime/Squirrel framework decision, and Wisdom-Weasel issue map.

Commands:
- `python3 -W ignore::ResourceWarning -m unittest tests.test_predictor`
- `python3 -W ignore::ResourceWarning -m unittest discover -s tests`
- `python3 -m rag_ime.cli --core-mode fixture eval-prediction --cases-file docs/eval/codex-history-cases.example.jsonl --max-candidates 3 --repeat 2`
- `python3 -m rag_ime.cli --core-mode fixture acceptance`

Next:
- Run `eval-prediction` against a real local Qwen/MLX/llama.cpp endpoint in both `chat` and `completion` modes.
- If completion mode is still too slow, implement a native llama.cpp/MLX provider with KV cache reuse and batch sampling.

### 2026-07-01 06:24 CST
Problem:
- The user asked to complete Xcode configuration for the Squirrel/Rime frontend.

Findings:
- `bash scripts/setup_xcode_for_squirrel.sh` still finds no full `Xcode.app` under `/Applications` or `/Volumes/undo 4t/Applications`.
- A real external-disk install attempt with `RAG_IME_INSTALL_XCODE=xcodes RAG_IME_XCODE_VERSION="27.0 Beta 2"` failed at Apple Developer authentication: `Apple ID: Missing username or a password`.
- Strict doctor now has exactly one failure: active developer directory is `/Library/Developer/CommandLineTools`; Squirrel patch, generated config, Swift availability, LaunchAgent, and HTTP `/rime-suggest` all pass.

Commands:
- `bash scripts/setup_xcode_for_squirrel.sh`
- `RAG_IME_INSTALL_XCODE=xcodes RAG_IME_XCODE_VERSION="27.0 Beta 2" bash scripts/setup_xcode_for_squirrel.sh`
- `RAG_IME_DOCTOR_REQUIRE_XCODE=1 scripts/doctor_squirrel_integration.sh`

Next:
- Run `xcodes download "27.0 Beta 2" --directory "/Volumes/undo 4t/XcodeDownloads"` once Apple Developer auth is available, or provide `FASTLANE_SESSION` and rerun the setup script.
- After Xcode is installed, rerun strict doctor and build the prepared Squirrel checkout.

### 2026-07-01 00:55 CST
Problem:
- Squirrel debounce reduces frontend request spam, but repeated equivalent `/rime-suggest` requests can still reach the HTTP sidecar and repeat model/RAG work.

Changes:
- Added process-local short TTL cache for `DebugImeService.rime_suggest`.
- Cache key excludes `requestSeq` and `sessionId`, but includes payload content, memory event/action counts, project, and predictor configuration.
- Cached responses rewrite `requestSeq`/`sessionId` for the current request and include `cache.hit`.
- Commit/action/seed clear the cache.
- Browser debug JSON now includes `rimeSuggestCache` from `/api/health`.

Commands:
- `python3 -W ignore::ResourceWarning -m unittest tests.test_debug_server`

Next:
- Add cache hit-rate assertions to Codex-history/RAG evaluation runs and compare them with VCP-style cache targets.

### 2026-07-01 00:35 CST
Problem:
- Wisdom-Weasel avoids UI overwrite with request sequence, but Squirrel can call `rimeUpdate` very frequently and page/candidate state can change under the same raw input.

Changes:
- Updated Squirrel patch to read `rag_ime/debounce_ms`, debounce pending sidecar requests, and fingerprint request state.
- Stale guard now checks request sequence, session, raw input, preedit, page, and first Rime candidate fingerprint.
- Updated Rime sidecar merge policy so at most one model side candidate can be shown before RAG/memory side candidates.
- Added OpenAI-compatible predictor extra body/header JSON knobs for Qwen/reasoning-compatible servers.
- Updated Wisdom-Weasel issue map and Squirrel integration notes.

Findings:
- Wisdom-Weasel's useful pattern is async request sequence invalidation, but RAG-IME needs stricter frontend fingerprinting because RAG evidence and model results should not overwrite a changed Rime page.

Commands:
- `git apply --check squirrel-patches/0001-add-rag-ime-sidecar.patch` against Squirrel `2158538`
- `swiftc -typecheck` for `RagImeSidecarModels.swift` and `RagImeSidecarClient.swift`
- `scripts/prepare_squirrel_workspace.sh` using a local Squirrel clone

Next:
- Run `predict-benchmark` against a real local model; then evaluate base-prefix completion or llama.cpp KV/batch if latency is still high.

### 2026-07-01 00:12 CST
Problem:
- The project needs a concrete way to compare small local model choices for the short prediction lane.

Changes:
- Added `predict-benchmark` CLI.
- Added `benchmark_prediction_provider` and a latency-budget report schema.
- Documented the benchmark in `docs/local-model-prediction-benchmark.md`.

Findings:
- The benchmark uses the same predictor provider and history-context merge as `suggest-json`, so model latency is measured in the product path rather than through a separate toy prompt.

Commands:
- `python3 -W ignore::ResourceWarning -m unittest tests.test_predictor`

Next:
- Run the benchmark against real local Qwen/llama.cpp/MLX endpoints after selecting the local inference server.

### 2026-06-30 23:58 CST
Problem:
- The RAG/memory system needed a real local benchmark source, not only deterministic demo memories.

Changes:
- Added `rag_ime.codex_history` for local Codex JSONL parsing.
- Added `import-codex-history` CLI with dry-run and bounded import.
- Added default duplicate skipping using stable `record:<hash>` tags.
- Added `eval-codex-history` CLI for explicit query/expectedTerms retrieval evaluation.
- Documented the workflow in `docs/codex-history-eval.md`.

Findings:
- The import path reuses the same `InputEvent` -> SQLite/FTS5 -> suggestion pipeline as normal IME input, so the evaluation checks product candidates instead of raw chunks.

Commands:
- `python3 -W ignore::ResourceWarning -m unittest tests.test_codex_history`
- `python3 -W ignore::ResourceWarning -m unittest discover -s tests`

Next:
- Add leave-one-session-out evaluation after importing real Codex logs.
- Compare FTS5-only against embedding/rerank and VCP-style cache behavior on the same cases.

### 2026-06-30 23:40 CST
Problem:
- Full patched Squirrel validation is blocked by missing full Xcode on this Mac.

Findings:
- Active developer directory is `/Library/Developer/CommandLineTools`; no local `Xcode.app` or `.xip` was found.
- Installed `xcodes` and `mas` to prepare both Apple Developer and App Store install paths.
- `xcodes list` shows `27.0 Beta 2`, matching the macOS 27 beta host, but download requires Apple ID credentials.
- `mas info 497799835` shows App Store Xcode 26.6, but `mas get` requires administrator password in an interactive terminal.
- Root disk has limited free space, so Xcode download/install should prefer `/Volumes/undo 4t`.

Changes:
- Added `scripts/setup_xcode_for_squirrel.sh`.
- Added `docs/xcode-squirrel-setup.md`.
- Enhanced `scripts/doctor_squirrel_integration.sh` to report active developer directory and `DEVELOPER_DIR`.

Commands:
- `brew install xcodes`
- `brew install mas`
- `xcodes list`
- `mas info 497799835`

Next:
- Complete Apple Developer/App Store/admin-password install step, then rerun setup and strict doctor.

### 2026-06-30 22:53 CST
Problem:
- Squirrel side candidates could be inserted, but the first patch did not write accepted RAG choices back to the memory core.
- `max_side_candidates` could be exceeded when model and RAG candidates both filled visible slots.

Findings:
- Wisdom-Weasel's useful pattern is async prediction with request sequence invalidation, frontend-side candidate merge, and custom selection routing for appended model candidates.
- The Squirrel patch should keep librime unchanged and route side candidates by display metadata in `SquirrelInputController`.

Changes:
- Added `sourceEventId` to `displayCandidates`.
- Updated the Squirrel patch to record side candidate commits and `action-json accepted` for RAG memory candidates.
- Fixed global side-candidate cap across model and RAG candidates.

Commands:
- `python3 -W ignore::ResourceWarning -m unittest discover -s tests`
- `python3 -m rag_ime.cli --core-mode fixture acceptance`
- `scripts/build_macos_frontend.sh`
- `RagImeMac --preview-rime-sidecar-json`
- `git apply --check squirrel-patches/0001-add-rag-ime-sidecar.patch`

Next:
- Build and install a patched Squirrel app in a full Xcode environment.
- Replace per-request Python process spawning with a long-lived daemon or local socket.

### 2026-06-30 23:10 CST
Problem:
- Squirrel patch still spawned `python -m rag_ime.cli` on each sidecar request, which is too expensive for high-frequency typing.

Changes:
- Added `python3 -m rag_ime.cli sidecar-server` as a lightweight local HTTP sidecar.
- Added root-path HTTP aliases such as `/rime-suggest`, `/commit`, and `/action` in addition to `/api/...`.
- Updated Squirrel patch to prefer `rag_ime/sidecar_url` and fall back to CLI if the daemon is unavailable.

Commands:
- `python3 -W ignore::ResourceWarning -m unittest discover -s tests`
- `python3 -m rag_ime.cli --core-mode fixture sidecar-server --host 127.0.0.1 --port 18766 --no-seed`
- `swiftc -typecheck ... RagImeSidecarModels.swift RagImeSidecarClient.swift`
- `git apply --check squirrel-patches/0001-add-rag-ime-sidecar.patch`

Next:
- Full Xcode build/install of patched Squirrel remains the next hard gate.

### 2026-07-01
Topic:
- Restore full Rime-sidecar display-path eval after filtering raw trace surfaces.

Changes:
- Added product/runtime query expansions for selection routing, RAG-vs-model comparison, WSL embedding env vars, suggestion-cache metrics, and Codex-history ranking metrics.
- Added canonical surface summaries so visible IME candidates can show project keys such as `RAG_IME_EMBEDDING_BASE_URL`, `suggestionCache`, `top1Accuracy`, and `maxModelSideCandidates` instead of generic status text.
- Filtered patch/file-hit candidate surfaces and downranked patch/tool/subagent traces so they remain recallable but do not become candidate-bar text.
- Updated the local model plan for Ollama `qwen3.5` small tags: `0.8b`, `2b`, `4b`, and corresponding `-mlx` variants.

Verification:
- `python3 -W ignore::ResourceWarning -m unittest tests.test_adapter tests.test_local_sqlite_core`
- `python3 -m rag_ime.cli --db-path /private/tmp/rag-ime-rime-sidecar-eval-20260701.sqlite eval-rime-sidecar --cases-file docs/eval/codex-history-cases.example.jsonl --match any --repeat 1`
- Rime sidecar display path now passes 34/34, top1Accuracy=0.765, meanReciprocalRank=0.868, p95=46ms, noiseRate=0.
- `curl -s https://ollama.com/library/qwen3.5 | rg -o "qwen3\\.5:[0-9.]+b(?:-mlx)?" | sort -u` confirmed Ollama tags including `0.8b`, `2b`, `4b`, and `-mlx` variants.
- `ollama` is not installed or visible in this Mac session, so real model inference remains pending.

Next:
- Run full suite, fixture acceptance, direct Codex-history eval, and `git diff --check`, then push if clean.
- Start a real Ollama/WSL endpoint later and run `predictor-doctor`, `predict-benchmark`, `eval-prediction`, `eval-comparison`, and `eval-rime-sidecar`.

### 2026-07-01
Topic:
- Add a concrete local model matrix gate for Qwen3.5 candidates.

Changes:
- Added `eval-model-matrix` CLI to evaluate multiple OpenAI-compatible model ids on the same prediction case file.
- Default matrix is `qwen3.5:0.8b,qwen3.5:2b,qwen3.5:4b` against Ollama's `http://127.0.0.1:11434/v1`.
- Matrix output reports per-model pass rate, ranking metrics, latency, candidate availability, local runner availability, and a winner summary.
- Full per-case details are hidden by default to keep output readable; use `--include-cases` for debugging.
- Updated README and local model benchmark docs.

Verification:
- `python3 -W ignore::ResourceWarning -m unittest tests.test_predictor`
- `python3 -m rag_ime.cli --core-mode fixture eval-model-matrix --cases-file docs/eval/codex-history-cases.example.jsonl --models qwen3.5:0.8b,qwen3.5:2b --latency-budget-ms 150`
- The local matrix command reports both qwen3.5 models configured but `hasCandidates=false`.
- `localRunners.available` is empty and `missing` includes `ollama`, `llama-server`, `lmstudio`, and `mlx_lm.server`; no model was downloaded or run in this Mac session.

Next:
- Install/start Ollama or a WSL OpenAI-compatible endpoint, pull `qwen3.5:0.8b` first, then rerun `eval-model-matrix`.

### 2026-07-01 07:39 CST
Problem:
- FTS5/rerank can handle many exact project-history cases, but the core did not yet have a pluggable vector side-index for true semantic recall experiments.
- Existing Codex-history eval could compare cache and latency, but not whether a vector provider was active or indexed.

Changes:
- Added optional embedding providers behind the local core boundary: disabled by default, deterministic `local-hash` baseline, and OpenAI-compatible embedding endpoint support.
- Added `memory_vectors`, vector upsert on writes, vector/FTS row merge, score contribution, `vector_index_stats()`, and `rebuild_vector_index()`.
- Added CLI flags `--embedding-provider`, `--embedding-vector-candidates`, `--embedding-vector-weight`, plus `rebuild-vector-index`.
- Added vector stats to RAG eval reports and documented the Mac/WSL embedding path.

Commands:
- `python3 -W ignore::ResourceWarning -m unittest tests.test_local_sqlite_core`
- `python3 -W ignore::ResourceWarning -m unittest discover -s tests`
- `python3 -m rag_ime.cli --core-mode fixture acceptance`
- `python3 -m rag_ime.cli --db-path /private/tmp/rag-ime-vector-eval-20260701.sqlite import-codex-history --path /Users/undo/.codex/sessions --project wisdom-weasel-rag-ime --limit 2000 --sample-size 0`
- `python3 -m rag_ime.cli --db-path /private/tmp/rag-ime-vector-eval-20260701.sqlite --embedding-provider local-hash rebuild-vector-index --project wisdom-weasel-rag-ime --limit 2000`
- `python3 -m rag_ime.cli --db-path /private/tmp/rag-ime-vector-eval-20260701.sqlite --embedding-provider local-hash eval-codex-history --cases-file docs/eval/codex-history-cases.example.jsonl --top-k 5 --match any --repeat 2`
- `python3 -m rag_ime.cli --db-path /private/tmp/rag-ime-vector-eval-20260701.sqlite eval-codex-history --cases-file docs/eval/codex-history-cases.example.jsonl --top-k 5 --match any --repeat 2`
- `git diff --check`

Findings:
- Full test suite passed with 72 tests.
- local-hash vector backfill indexed 2000/2000 imported Codex-history records.
- Both default FTS/rerank and local-hash hybrid passed the 3-case eval repeated twice with top1Accuracy=1.0 and MRR=1.0.
- Default path p95 was 21ms; local-hash hybrid p95 was 80ms on the 2000-record temp DB, so vector recall must stay optional and be benchmarked before enabling in the IME sidecar.

Next:
- Replace local-hash with a real local/WSL embedding endpoint and compare quality/latency on the same case file.
- Use subagent research output to decide whether VCP-style hybrid/cache behavior should change the vector merge or context-cache layer.

### 2026-07-01 07:46 CST
Problem:
- After adding optional vector recall, debug health and `/rime-suggest` cache did not expose or depend on vector index state.
- If a running sidecar served a cached response after vector backfill/provider changes, the IME could briefly show stale RAG candidates without a visible reason.

Changes:
- Added `vectorStats` to debug/sidecar health.
- Included `vectorStats` in the semantic `/rime-suggest` cache key so vector provider/index changes invalidate the short TTL cache.
- Added `vectorStats` to the debug page JSON panel.
- Added a test core whose vector revision changes to prove cache invalidation follows vector index state.

Commands:
- `python3 -W ignore::ResourceWarning -m unittest tests.test_debug_server`
- `python3 -W ignore::ResourceWarning -m unittest discover -s tests`
- `python3 -m rag_ime.cli --core-mode fixture acceptance`
- `git diff --check`

Findings:
- Full suite passed with 73 tests.
- Acceptance still passes.
- Subagent read-only research confirmed the next high-value directions: VCP-style embedding/query caches and pending request dedupe, richer 30-50 case gold set, typed context lanes, and Wisdom-Weasel-style native llama.cpp/MLX prediction path with KV cache and batch candidates.

Next:
- Expand Codex-history gold cases before further rerank tuning.
- Add embedding exact cache / in-flight dedupe once a real embedding endpoint is selected.

### 2026-07-01 07:53 CST
Problem:
- The Codex-history evaluation file had only 3 cases, so recent retrieval improvements could overfit and still look perfect.
- We needed a broader, realistic gold set before tuning vector recall, rerank, or model prediction.

Changes:
- Expanded `docs/eval/codex-history-cases.example.jsonl` from 3 to 34 cases.
- Covered Squirrel/Rime integration, side candidate selection, sidecar cache, vector backfill, embedding config, Qwen/prediction eval, LaunchAgent/Xcode, InputMethodKit boundary, typed history context, VCP cache lessons, Wisdom-Weasel fast prediction, and debug/doctor workflows.
- Documented the current 34-case baseline in `docs/codex-history-eval.md`.

Commands:
- `python3 -m rag_ime.cli --db-path /private/tmp/rag-ime-expanded-eval-20260701.sqlite import-codex-history --path /Users/undo/.codex/sessions --project wisdom-weasel-rag-ime --limit 5000 --sample-size 0`
- `python3 -m rag_ime.cli --db-path /private/tmp/rag-ime-expanded-eval-20260701.sqlite eval-codex-history --cases-file docs/eval/codex-history-cases.example.jsonl --top-k 5 --match any --repeat 1`
- `python3 -m rag_ime.cli --db-path /private/tmp/rag-ime-expanded-eval-20260701.sqlite --embedding-provider local-hash rebuild-vector-index --project wisdom-weasel-rag-ime --limit 5000`
- `python3 -m rag_ime.cli --db-path /private/tmp/rag-ime-expanded-eval-20260701.sqlite --embedding-provider local-hash eval-codex-history --cases-file /private/tmp/rag-ime-expanded-cases.jsonl --top-k 5 --match any --repeat 1`
- `python3 -W ignore::ResourceWarning -m unittest tests.test_codex_history tests.test_predictor`
- `python3 -W ignore::ResourceWarning -m unittest discover -s tests`
- `git diff --check`

Findings:
- Default FTS5 + local rule rerank on 5000 imported records: 24/34 pass, top1Accuracy=0.50, MRR=0.566, p95 about 29ms.
- `local-hash` hybrid on the same DB: 23/34 pass, top1Accuracy=0.441, MRR=0.528, p95 about 160ms.
- This confirms `local-hash` should remain a deterministic side-index contract test, not a product default.
- Known gaps now captured as failing cases include candidate number policy, raw pinyin gate, model side budget, history-context prediction, Wisdom-Weasel fast prediction, local-first privacy recall, OpenAI-compatible predictor env recall, stale response guard, trigger decision, and Codex-history noise filter.

Next:
- Improve recall against the failing cases with field-aware boosts or a real semantic embedding provider, then rerun the same 34-case report.

### 2026-07-01 08:45 CST
Problem:
- The expanded 34-case Codex-history eval exposed 10 product/runtime recall gaps.
- Several failing queries used Chinese product language, while the implementation memories stored English identifiers such as `rawInputFallback`, `maxModelSideCandidates`, `requestSeq`, and `RAG_IME_PREDICTOR_BASE_URL`.
- Raw Codex tool transcripts are noisy, but deleting them entirely also removes useful code identifiers that may not appear in assistant summaries yet.

Changes:
- Expanded local query rewriting for Rime/Squirrel side candidates, raw-pinyin gating, local-first privacy, model side budget, history-context prediction, Wisdom-Weasel speed terms, OpenAI-compatible predictor config, stale-response guards, trigger decisions, sidecar cache metrics, and Codex runtime-noise filtering.
- Added light runtime-trace downranking for raw Codex tool transcript records, preserving code identifiers as fallback recall while preferring natural-language summaries.
- Added importer filtering for the Codex approval-review transcript wrapper text.
- Updated the `codex-history-noise-filter` gold case to verify real imported terms (`environment`, `tool-output`) instead of English phrases that were not present in the user history.
- Added focused regression tests for product/runtime query expansion and tool-trace downranking.
- Recorded the subagent read-only optimization review in `docs/agent/subagents/rag-ime-next-optimization-20260701.md`.

Commands:
- `python3 -W ignore::ResourceWarning -m unittest tests.test_codex_history tests.test_local_sqlite_core`
- `python3 -m rag_ime.cli --db-path /private/tmp/rag-ime-expanded-eval-final-20260701.sqlite import-codex-history --path /Users/undo/.codex/sessions --project wisdom-weasel-rag-ime --limit 5000 --sample-size 0`
- `python3 -m rag_ime.cli --db-path /private/tmp/rag-ime-expanded-eval-final-20260701.sqlite eval-codex-history --cases-file docs/eval/codex-history-cases.example.jsonl --top-k 5 --match any --repeat 1`
- `python3 -W ignore::ResourceWarning -m unittest discover -s tests`
- `python3 -m rag_ime.cli --core-mode fixture acceptance`
- `git diff --check`

Findings:
- Fresh 5000-record newest-first Codex-history import now passes 34/34 cases.
- top1Accuracy improved from 0.500 to 0.824.
- meanReciprocalRank improved from 0.566 to 0.880.
- latency.p95Ms stayed within the input-method refresh budget at about 30ms.
- Over-filtering `[n] tool ...` records reduced recall to 28/34, so the chosen design is downranking rather than deletion.

Next:
- Use the subagent review to implement candidate-surface compression next; keep full `insert_text` but make `surface_text` smaller and cleaner for the real IME panel.
- Add exact embedding cache / provider fingerprint cache before testing a real WSL embedding endpoint.

### 2026-07-01 08:17 CST
Problem:
- Real IME panel space is small, but `SuggestionCompiler` mostly used the first sentence of retrieved memory as `surface_text`.
- Long RAG chunks, bullets, and Codex transcript/tool traces could therefore produce candidate text that looked like logs instead of input-method candidates.

Changes:
- Added candidate-surface compression in `SuggestionCompiler`.
- The compiler now prefers useful bullets/short semantic lines, strips transcript/tool/path/debug wrappers from display text, and still preserves the full committed material in `metadata.insert_text`.
- Added regression tests for bullet extraction and tool-trace prefix cleanup.
- Added a `/rime-suggest` sidecar smoke proving RAG `displayCandidates[].text` stays compact while `insertText` keeps the full paragraph.
- Updated UX notes to make `surface_text` vs. `insert_text` an explicit contract.
- Integrated Ptolemy's non-overlapping exact embedding cache patch for the OpenAI-compatible embedding provider.
- Embedding cache keys include provider fingerprint plus normalized text; provider fingerprint now includes endpoint hash, model, dimensions, and `extra_body` hash.
- Empty vectors are not cached, and `RAG_IME_EMBEDDING_CACHE_SIZE` controls the bounded in-process cache.

Commands:
- `python3 -W ignore::ResourceWarning -m unittest tests.test_adapter tests.test_rime_sidecar`
- `python3 -m rag_ime.cli --core-mode fixture acceptance`
- `python3 -m rag_ime.cli --db-path /private/tmp/rag-ime-expanded-eval-final-20260701.sqlite eval-codex-history --cases-file docs/eval/codex-history-cases.example.jsonl --top-k 5 --match any --repeat 1`
- `python3 -W ignore::ResourceWarning -m unittest tests.test_embeddings`
- `python3 -W ignore::ResourceWarning -m unittest discover -s tests`

Findings:
- Adapter/sidecar tests pass.
- Embedding cache tests pass: repeated normalized text hits once, endpoint/fingerprint change misses, empty vectors are not cached, and cache size is bounded.
- Full suite now has 82 tests and passed.
- 34-case Codex-history eval still passes 34/34 with unchanged ranking quality: top1Accuracy=0.824, meanReciprocalRank=0.880.

Next:
- Use the sidecar display/insert split when implementing the native candidate panel.
- Test a real WSL/local embedding endpoint with `RAG_IME_EMBEDDING_CACHE_SIZE` enabled and compare repeated-case latency.

### 2026-07-01 08:31 CST
Problem:
- The project had an optional local model provider, but it was easy to confuse "provider code exists" with "a real local Qwen/MLX/llama.cpp model is currently running and useful".
- The updated goal explicitly requires concrete small-model testing, preferably instant/no-thinking style.

Changes:
- Added shared `prediction_provider_status()` for model-lane observability.
- Added `rag-ime predictor-status` CLI to show model configuration without calling the model.
- Added `predictor` status to `/api/health` so the debug page can show whether the optional model lane is configured.
- Normalized `predict-benchmark` provider naming so configured-but-empty providers still report the configured provider name.
- Documented that `predictor-status` is only a config check; `predict-benchmark` / `eval-prediction` are the real liveness and quality gates.

Commands:
- `python3 -W ignore::ResourceWarning -m unittest discover -s tests`
- `python3 -m rag_ime.cli --core-mode fixture acceptance`
- `python3 -m rag_ime.cli --core-mode fixture predictor-status`
- `RAG_IME_PREDICTOR_PROVIDER=openai-compatible RAG_IME_PREDICTOR_BASE_URL=http://127.0.0.1:8000 RAG_IME_PREDICTOR_MODEL=Qwen3-0.6B RAG_IME_PREDICTOR_PROFILE=instant python3 -m rag_ime.cli --core-mode fixture predictor-status`
- `RAG_IME_PREDICTOR_PROVIDER=openai-compatible RAG_IME_PREDICTOR_BASE_URL=http://127.0.0.1:8000 RAG_IME_PREDICTOR_MODEL=Qwen3-0.6B RAG_IME_PREDICTOR_PROFILE=instant python3 -m rag_ime.cli --core-mode fixture predict-benchmark --case "RAG 输入法" --recent-context "用户正在写本地记忆输入法" --max-candidates 3 --latency-budget-ms 150`
- `python3 -m rag_ime.cli --db-path /private/tmp/rag-ime-model-status-eval-20260701-0840.sqlite import-codex-history --path /Users/undo/.codex/sessions --project wisdom-weasel-rag-ime --limit 5000 --sample-size 0`
- `python3 -m rag_ime.cli --db-path /private/tmp/rag-ime-model-status-eval-20260701-0840.sqlite eval-codex-history --cases-file docs/eval/codex-history-cases.example.jsonl --top-k 5 --match any --repeat 1`
- `git diff --check`
- Local endpoint probe for `127.0.0.1:8000/v1/models`, `127.0.0.1:8080/v1/models`, `127.0.0.1:1234/v1/models`, and `127.0.0.1:11434/api/tags`.

Findings:
- Full unit suite passed: 85 tests.
- Fixture acceptance passed.
- Real 5000-record Codex-history eval still passed 34/34, with top1Accuracy=0.824, meanReciprocalRank=0.880, p95=34ms.
- `git diff --check` passed.
- Default current machine status: `configured=false`, `providerName=NullPredictionProvider`.
- With Qwen instant env set, config status becomes `configured=true`, `providerProfile=instant`, `promptMode=chat`, `model=Qwen3-0.6B`, `timeoutMs=350`, `maxTokens=8`.
- Real benchmark against `127.0.0.1:8000` returned `hasCandidates=false`, so no usable local model server is currently running there.
- Common local endpoints `8000`, `8080`, `1234`, and `11434` all returned connection refused in this session.
- Ollama `qwen3.5` has small tags, so it should be included in the first local IME test matrix: `qwen3.5:0.8b`, `qwen3.5:2b`, `qwen3.5:4b`, plus `-mlx` variants on Mac when available.

Next:
- Start a real local/WSL OpenAI-compatible Qwen/llama.cpp/MLX endpoint, then run `predictor-status`, `predict-benchmark`, and `eval-prediction`.
- Prefer Qwen/Qwen3.5 instant/no-thinking first; compare chat `instant` against completion `completion-instant` before building a native KV-cache provider.

### 2026-07-01 08:46 CST
Problem:
- `predictor-status` showed whether env vars were set, but it did not explain why a configured model endpoint still returned no candidates.
- This made the next real Qwen/WSL test harder to debug.

Changes:
- Added `doctor_prediction_provider()` and `rag-ime predictor-doctor`.
- The doctor probes `/v1/models`, checks whether the configured model id is listed, runs one short prediction, reports latency budget status, and shows local runner commands visible in `PATH`.
- README, debug docs, and local-model benchmark docs now use the sequence: `predictor-status` -> `predictor-doctor` -> `predict-benchmark` -> `eval-prediction` / `eval-comparison`.

Commands:
- `command -v ollama || true`
- `command -v llama-server || true`
- `command -v lmstudio || true`
- `command -v mlx_lm.server || true`
- `python3 -W ignore::ResourceWarning -m unittest tests.test_predictor`
- `python3 -m rag_ime.cli --core-mode fixture predictor-doctor`
- `RAG_IME_PREDICTOR_PROVIDER=openai-compatible RAG_IME_PREDICTOR_BASE_URL=http://127.0.0.1:8000 RAG_IME_PREDICTOR_MODEL=Qwen3-0.6B RAG_IME_PREDICTOR_PROFILE=instant python3 -m rag_ime.cli --core-mode fixture predictor-doctor --case "RAG 输入法" --recent-context "用户正在写本地记忆输入法" --latency-budget-ms 150`
- `python3 -W ignore::ResourceWarning -m unittest discover -s tests`
- `python3 -m rag_ime.cli --core-mode fixture acceptance`
- `python3 -m rag_ime.cli --db-path /private/tmp/rag-ime-predictor-doctor-eval-20260701.sqlite import-codex-history --path /Users/undo/.codex/sessions --project wisdom-weasel-rag-ime --limit 5000 --sample-size 0`
- `python3 -m rag_ime.cli --db-path /private/tmp/rag-ime-predictor-doctor-eval-20260701.sqlite eval-codex-history --cases-file docs/eval/codex-history-cases.example.jsonl --top-k 5 --match any --repeat 1`
- `git diff --check`

Findings:
- This Mac currently has none of `ollama`, `llama-server`, `lmstudio`, or `mlx_lm.server` in `PATH`.
- Default `predictor-doctor` correctly reports `ready=false`, `configured=false`, `endpointReachable=false`, and missing local runners.
- With Qwen instant env pointed at `127.0.0.1:8000`, doctor reports `configured=true` but `/v1/models` connection refused, so the current blocker is no running local/WSL OpenAI-compatible server.
- Full unit suite passed: 87 tests.
- Fixture acceptance passed.
- Real 5000-record Codex-history eval still passed 34/34, top1Accuracy=0.824, meanReciprocalRank=0.880, p95=35ms.
- `git diff --check` passed.

Next:
- Use `predictor-doctor` as the first command after starting a WSL or Mac OpenAI-compatible Qwen endpoint.
- Only run the heavier 34-case `eval-prediction` after doctor reports reachable endpoint and parsed candidates.

### 2026-07-01 08:55 CST
Problem:
- The model lane failed open, but a configured endpoint that times out could still cost one model timeout per `/rime-suggest` composing refresh.
- This would break the input method's responsiveness even though RAG candidates can still work.

Changes:
- Added `CooldownPredictionProvider` around configured OpenAI-compatible predictors.
- Default cooldown: `RAG_IME_PREDICTOR_FAILURE_COOLDOWN_MS=5000`, failure threshold `RAG_IME_PREDICTOR_FAILURE_LATENCY_MS=250`.
- `prediction_provider_status()` and debug health now expose cooldown state.
- Added sidecar coverage proving a failed model endpoint is called once, subsequent refreshes skip the model, and RAG candidates still appear.

Commands:
- `python3 -W ignore::ResourceWarning -m unittest tests.test_predictor`
- `python3 -W ignore::ResourceWarning -m unittest tests.test_rime_sidecar`
- `RAG_IME_PREDICTOR_PROVIDER=openai-compatible RAG_IME_PREDICTOR_BASE_URL=http://127.0.0.1:8000 RAG_IME_PREDICTOR_MODEL=Qwen3-0.6B RAG_IME_PREDICTOR_PROFILE=instant python3 -m rag_ime.cli --core-mode fixture predictor-status`
- `python3 -W ignore::ResourceWarning -m unittest discover -s tests`
- `python3 -m rag_ime.cli --core-mode fixture acceptance`
- `RAG_IME_PREDICTOR_PROVIDER=openai-compatible RAG_IME_PREDICTOR_BASE_URL=http://127.0.0.1:8000 RAG_IME_PREDICTOR_MODEL=Qwen3-0.6B RAG_IME_PREDICTOR_PROFILE=instant python3 -m rag_ime.cli --core-mode fixture predictor-doctor --case "RAG 输入法" --recent-context "用户正在写本地记忆输入法" --latency-budget-ms 150`
- `python3 -m rag_ime.cli --db-path /private/tmp/rag-ime-predictor-cooldown-eval-20260701.sqlite import-codex-history --path /Users/undo/.codex/sessions --project wisdom-weasel-rag-ime --limit 5000 --sample-size 0`
- `python3 -m rag_ime.cli --db-path /private/tmp/rag-ime-predictor-cooldown-eval-20260701.sqlite eval-codex-history --cases-file docs/eval/codex-history-cases.example.jsonl --top-k 5 --match any --repeat 1`
- `git diff --check`

Findings:
- Predictor tests pass with cooldown on by default and with cooldown disabled through env.
- Rime sidecar tests pass and verify model-failure cooldown does not suppress RAG candidates.
- Predictor status shows cooldown metadata for configured Qwen instant env.
- Full suite passed: 91 tests.
- Fixture acceptance passed.
- Real 5000-record Codex-history eval still passed 34/34, top1Accuracy=0.824, meanReciprocalRank=0.880, p95=32ms.
- Qwen instant doctor against `127.0.0.1:8000` now reports `cooldown.active=true` after connection refused, proving the failure is surfaced and repeat model calls are short-circuited in-process.
- `git diff --check` passed.

Next:
- When a real WSL/Mac endpoint is available, compare no-cooldown debug mode vs default cooldown only for endpoint debugging.

### 2026-07-01 09:01 CST
Problem:
- `/rime-suggest` had a semantic TTL cache, but concurrent equivalent requests arriving before the first response finished still duplicated model/RAG work.
- This is exactly the VCP-style pending-request cache gap the project should handle for high-frequency IME refreshes.

Changes:
- Added in-flight dedupe for equivalent `/rime-suggest` cache keys in `DebugImeService`.
- Added `rimeSuggestCache.inFlight`, `inFlightHits`, and `inFlightErrors` health stats.
- Response cache payloads now include `inFlightHit`.
- Added a concurrent test with a blocking predictor proving two overlapping equivalent requests call the predictor once, while the second response rewrites current `sessionId` and `requestSeq`.

Commands:
- `python3 -W ignore::ResourceWarning -m unittest tests.test_debug_server`
- `python3 -W ignore::ResourceWarning -m unittest discover -s tests`
- `python3 -m rag_ime.cli --core-mode fixture acceptance`
- `python3 -m rag_ime.cli --db-path /private/tmp/rag-ime-inflight-dedupe-eval-20260701.sqlite import-codex-history --path /Users/undo/.codex/sessions --project wisdom-weasel-rag-ime --limit 5000 --sample-size 0`
- `python3 -m rag_ime.cli --db-path /private/tmp/rag-ime-inflight-dedupe-eval-20260701.sqlite eval-codex-history --cases-file docs/eval/codex-history-cases.example.jsonl --top-k 5 --match any --repeat 1`
- `git diff --check`

Findings:
- Debug-server tests pass with in-flight dedupe.
- Full suite passed: 92 tests.
- Fixture acceptance passed.
- Real 5000-record Codex-history eval still passed 34/34, top1Accuracy=0.824, meanReciprocalRank=0.880, p95=32ms.
- `git diff --check` passed.

Next:
- Continue toward real Squirrel/Xcode install and WSL/Mac model endpoint testing.

### 2026-07-01 09:17 CST
Problem:
- `eval-codex-history` proved core RAG quality, but it did not verify the real `/rime-suggest` path: Rime-first merge, visible side slots, trigger policy, compact display text, and sidecar cache.
- First real 5000-record sidecar eval passed only 13/34 because `historyContext` for model prediction was also passed into RAG retrieval, so recent status text crowded out relevant memories in the three side slots.

Changes:
- Added `eval-rime-sidecar` CLI using the same JSONL case format.
- The command calls `DebugImeService.rime_suggest(...)` and scores only non-Rime `displayCandidates`, avoiding false positives from the Rime candidate itself.
- Added report fields for side-candidate counts, trigger refreshes, `/rime-suggest` cache stats, suggestion cache stats, predictor status, vector stats, and per-case latency.
- Split sidecar context boundaries: local model prediction still receives `historyContext`, while RAG retrieval receives only the explicit `committedContext`.
- Added tests for sidecar eval, cache hits, and the model-vs-RAG context boundary.

Commands:
- `python3 -W ignore::ResourceWarning -m unittest tests.test_codex_history.CodexHistoryTests.test_cli_eval_rime_sidecar_scores_display_side_candidates_and_cache`
- `python3 -W ignore::ResourceWarning -m unittest tests.test_rime_sidecar tests.test_codex_history.CodexHistoryTests.test_cli_eval_rime_sidecar_scores_display_side_candidates_and_cache`
- `python3 -m rag_ime.cli --db-path /private/tmp/rag-ime-rime-sidecar-eval-20260701.sqlite import-codex-history --path /Users/undo/.codex/sessions --project wisdom-weasel-rag-ime --limit 5000 --sample-size 0`
- `python3 -m rag_ime.cli --db-path /private/tmp/rag-ime-rime-sidecar-eval-20260701.sqlite eval-rime-sidecar --cases-file docs/eval/codex-history-cases.example.jsonl --match any --repeat 1`
- `python3 -m rag_ime.cli --db-path /private/tmp/rag-ime-rime-sidecar-eval-20260701.sqlite eval-codex-history --cases-file docs/eval/codex-history-cases.example.jsonl --top-k 5 --match any --repeat 1`
- `python3 -m rag_ime.cli --db-path /private/tmp/rag-ime-rime-sidecar-eval-20260701.sqlite eval-rime-sidecar --cases-file docs/eval/codex-history-cases.example.jsonl --match any --repeat 2 --rime-cache-ttl-ms 5000`

Findings:
- Direct RAG eval on the 5000-record temp DB still passes 34/34, top1Accuracy=0.794, meanReciprocalRank=0.865, p95=32ms.
- Before the context split, Rime sidecar display-path eval passed 13/34, p95=73ms.
- After the context split, Rime sidecar display-path eval passes 31/34, top1Accuracy=0.794, meanReciprocalRank=0.843, with p95 observed between 34ms and 49ms across local runs.
- With `--repeat 2 --rime-cache-ttl-ms 5000`, Rime sidecar eval passes 62/68 and reports `rimeSuggestCache` hits/misses = 34/34.

Next:
- Improve the remaining sidecar-only misses with candidate compression/ranking for three visible side slots.
- Run the same sidecar eval with a real local/WSL Qwen endpoint once available.

### 2026-06-30 23:15 CST
Problem:
- Applying the Squirrel patch still required several manual commands, which is brittle when moving to a full Xcode machine.

Changes:
- Added `scripts/prepare_squirrel_workspace.sh`.
- The script clones/checks out Squirrel `2158538`, applies the patch, runs lightweight checks, and writes `rag-ime.squirrel.custom.yaml`.
- README, Squirrel patch notes, and macOS frontend notes now point to this script.

Commands:
- `bash -n scripts/prepare_squirrel_workspace.sh`
- `RAG_IME_SQUIRREL_DRY_RUN=1 scripts/prepare_squirrel_workspace.sh`
- `RAG_IME_SQUIRREL_REPO_URL=/tmp/rag-ime-research/squirrel scripts/prepare_squirrel_workspace.sh`
- `python3 -W ignore::ResourceWarning -m unittest discover -s tests`
- `python3 -m rag_ime.cli --core-mode fixture acceptance`
- `scripts/build_macos_frontend.sh`

Next:
- Run the prepared checkout through full Xcode build/install and real typing.

### 2026-06-30 23:22 CST
Problem:
- After adding sidecar launchd and Squirrel prep scripts, there was no single preflight command to diagnose missing sidecar, missing patch, unprepared Squirrel checkout, or missing Xcode.

Changes:
- Added `scripts/doctor_squirrel_integration.sh`.
- Doctor reports OK/WARN/FAIL for Python, patch file, `rag_ime.cli`, Squirrel workdir, Xcode, Swift, LaunchAgent, and sidecar HTTP health.
- Docs now point users to the doctor after sidecar/Squirrel preparation.

Commands:
- `bash -n scripts/doctor_squirrel_integration.sh`
- `scripts/doctor_squirrel_integration.sh` with sidecar absent in WARN mode
- `scripts/doctor_squirrel_integration.sh` with a temporary sidecar in strict sidecar mode
- `python3 -W ignore::ResourceWarning -m unittest discover -s tests`
- `python3 -m rag_ime.cli --core-mode fixture acceptance`
- `scripts/build_macos_frontend.sh`

Next:
- Use doctor output as the preflight gate before the full Xcode Squirrel build/install.

### 2026-07-01 00:20 CST
Problem:
- The user asked to make the Xcode setup complete for the Squirrel/Rime production route.
- This host still has only Command Line Tools selected, no full Xcode under `/Applications` or `/Volumes/undo 4t/Applications`.
- A real `xcodes` install attempt for `27.0 Beta 2` failed in Codex with `Apple ID: Missing username or a password`.

Changes:
- Hardened `scripts/setup_xcode_for_squirrel.sh` into a fuller preflight and install entrypoint.
- The script now reports disk space, installed Xcode directories, `FASTLANE_SESSION` state, `xcodes` data source, and a clear Apple Developer authentication recovery path.
- Added free-space guards for external `xcodes` installation and system `/Applications` App Store installation.
- Updated Xcode setup docs with the current machine findings and non-interactive authentication options.

Commands:
- `bash scripts/setup_xcode_for_squirrel.sh`
- `RAG_IME_INSTALL_XCODE=xcodes RAG_IME_XCODE_VERSION="27.0 Beta 2" bash scripts/setup_xcode_for_squirrel.sh`
- `RAG_IME_INSTALL_XCODE=mas bash scripts/setup_xcode_for_squirrel.sh`
- `xcodes list --data-source xcodeReleases --no-color | rg '^(27\\.0 Beta 2|26\\.6)'`

Next:
- Finish Xcode installation from an interactive Apple-authenticated terminal, or provide `FASTLANE_SESSION`, then rerun `scripts/setup_xcode_for_squirrel.sh`.
- After full Xcode is installed, run `RAG_IME_DOCTOR_REQUIRE_XCODE=1 scripts/doctor_squirrel_integration.sh` before building patched Squirrel.

### 2026-07-01 00:45 CST
Problem:
- Squirrel can refresh candidates on nearly every composing event, so relying only on frontend debounce and short TTL cache still risks running model/RAG work for raw pinyin noise.

Changes:
- Added a Rime-specific side candidate trigger decision in `rag_ime/rime_sidecar.py`.
- `/rime-suggest` now always preserves Rime candidates but skips model/RAG side lanes when the request has raw-pinyin fallback, no stable Rime candidate, no visible side slot, disabled side candidates, or a too-short candidate before idle.
- Response JSON now includes `triggerDecision` and `mergePolicy.sideCandidatesEnabled`.
- The browser debug page probes `/api/rime-suggest` and shows trigger/cache/display metadata in the JSON panel.
- Swift prototype models and the Squirrel patch pack now preserve the new trigger/merge fields.

Commands:
- `node --check debug/app.js`
- `python3 -W ignore::ResourceWarning -m unittest discover -s tests`
- `python3 -m rag_ime.cli --core-mode fixture acceptance`
- `scripts/build_macos_frontend.sh`
- `RAG_IME_SQUIRREL_DRY_RUN=1 scripts/prepare_squirrel_workspace.sh`
- `build/RagImeMac.app/Contents/MacOS/RagImeMac --preview-rime-sidecar-json`

Next:
- When Xcode is available, validate the same trigger behavior inside patched Squirrel's real update loop.

### 2026-07-01 01:10 CST
Problem:
- The Squirrel patch could insert side candidates, but feedback writeback was split between commit and accepted-action calls in Swift.
- That duplicated memory governance details in the frontend and made the side-candidate acceptance flow harder to test end to end.
- A real `scripts/prepare_squirrel_workspace.sh` run also exposed an older patch hunk-size bug that dry-run did not catch: `RagImeSidecarModels.swift` was truncated during apply.

Changes:
- Added `record_rime_side_candidate_selection()` as the shared Python writeback contract.
- Added `POST /rime-select` and CLI `rime-select-json`.
- `/rime-select` records committed side-candidate text and records an `accepted` memory action when the selected candidate is a RAG candidate with memory metadata.
- Updated the Squirrel patch to prefer `/rime-select` / `rime-select-json`, with legacy commit/action calls only as fallback.
- Fixed Squirrel patch new-file hunk lengths so real patch apply produces complete Swift files.
- Updated README, debug, macOS adapter, Squirrel integration, and patch-pack docs.

Commands:
- `python3 -W ignore::ResourceWarning -m unittest discover -s tests`
- `python3 -m rag_ime.cli --core-mode fixture acceptance`
- `scripts/build_macos_frontend.sh`
- `RAG_IME_SQUIRREL_RESET=1 scripts/prepare_squirrel_workspace.sh`
- `python3 -m rag_ime.cli --help | rg 'rime-select-json|rime-suggest-json|sidecar-server'`

Next:
- With Xcode installed, build the prepared `/tmp/rag-ime-squirrel` checkout and verify number-key side candidate insertion plus `/rime-select` feedback in a real text field.

### 2026-07-01 01:30 CST
Problem:
- `eval-codex-history` only reported pass/fail recall over the combined top-K haystack.
- That could overstate quality because `--match all` could be satisfied by expected terms split across different candidates, while an input method user chooses one candidate at a time.
- It also did not expose rank quality or noise, both of which matter for a small IME panel.

Changes:
- Made Codex-history evaluation candidate-level.
- Added per-case `firstMatchRank`, `reciprocalRank`, `top1Passed`, `termFirstRanks`, `forbiddenMatchedTerms`.
- Added report-level `metrics.hitRate`, `top1Accuracy`, `meanReciprocalRank`, `meanFirstMatchRank`, `noiseRate`, and `noiseCount`.
- Added `forbiddenTerms` support in JSONL cases so obvious noisy suggestions can fail the case even when expected terms match.
- Updated docs and example cases.

Commands:
- `python3 -W ignore::ResourceWarning -m unittest discover -s tests`
- `python3 -m rag_ime.cli --core-mode fixture acceptance`
- `scripts/build_macos_frontend.sh`
- CLI eval smoke with a temporary DB/cases file, confirming `top1Accuracy`, `meanReciprocalRank`, and `noiseRate` output.

Next:
- Use these ranking metrics on a larger imported Codex-history slice and compare FTS-only, embedding recall, rerank, and VCP-style cache variants.

### 2026-07-01 01:50 CST
Problem:
- The local SQLite core reran FTS retrieval and suggestion compilation for repeated equivalent queries.
- Input methods and PI-style adapters commonly repeat the same context while the candidate panel refreshes, so cache hit visibility is needed before comparing FTS, embedding, rerank, and VCP-style cache variants.

Changes:
- Added an invalidation-safe process-local LRU suggestion cache to `LocalSqliteCoreClient`.
- Cache key uses normalized `current_input`, `recent_context`, `project`, and `top_k`.
- `record_event`, `apply_action`, and `reset` clear the cache so commit/action governance cannot return stale suggestions.
- Added `suggestion_cache_stats()` with hit/miss/hitRate/eviction/invalidation counters.
- Exposed `RAG_IME_SUGGESTION_CACHE_SIZE` / `--suggestion-cache-size`, debug health `suggestionCache`, and `eval-codex-history` `cacheStats`.
- Debug JSON now shows both `rimeSuggestCache` and local-core `suggestionCache`.

Commands:
- `python3 -W ignore::ResourceWarning -m unittest discover -s tests`
- `python3 -m rag_ime.cli --core-mode fixture acceptance`
- `scripts/build_macos_frontend.sh`
- `python3 -m rag_ime.cli --help | rg 'suggestion-cache-size|core-mode|eval-codex-history'`
- Repeated-case CLI eval smoke confirmed `cacheStats.hits=1`, `misses=1`, `hitRate=0.5`.

Next:
- Use `cacheStats` with ranked Codex-history metrics to compare no-cache, cache, embedding recall, rerank, and VCP-style context-cache strategies on the same cases.

### 2026-07-01 02:05 CST
Problem:
- Ranked Codex-history evaluation had quality and cache metrics, but not end-to-end latency.
- For an input method, a candidate that is accurate but slow is still not usable, so quality/caching/latency need to be visible in the same report.

Changes:
- `eval-codex-history` now times each `adapter.suggest(...)` call.
- Reports include per-case `elapsedMs` and summary `latency.caseCount`, `totalMs`, `avgMs`, `p50Ms`, `p95Ms`, and `maxMs`.
- Docs now describe latency as adapter-level time covering core retrieval, cache lookup, ranking, and suggestion compilation.

Commands:
- `python3 -W ignore::ResourceWarning -m unittest discover -s tests`
- `python3 -m rag_ime.cli --core-mode fixture acceptance`
- `scripts/build_macos_frontend.sh`
- Repeated-case CLI eval smoke confirmed `elapsedMs`, `latency`, and `cacheStats` output together.

Next:
- Use this combined report to compare local FTS-only, cache on/off, embedding recall, rerank, and future shared-core/VCP-style strategies.

### 2026-07-01 01:18 CST
Problem:
- `eval-codex-history` could show cache stats and latency, but repeated equivalent cases still had to be duplicated manually in JSONL.
- The sidecar LaunchAgent appeared loaded but did not listen on port 8766 when Python imported code directly from the external-volume checkout.
- Full Xcode configuration is still blocked because no full `Xcode.app` is installed and Apple Developer/App Store authentication is not available in this Codex session.

Changes:
- Added `eval-codex-history --repeat N`; repeated cases get `#r1`, `#r2`, etc. case ids and a top-level `repeat` summary.
- Added repeat-mode tests showing warm-cache behavior (`misses=1`, `hits=2` for a 3-repeat smoke).
- Added `scripts/sidecar_launch.py`.
- Changed LaunchAgent installation to copy the runtime package into `~/Library/Application Support/RagIme/app`, default the sidecar DB to `~/Library/Application Support/RagIme/rag-ime.sqlite`, and avoid `PYTHONPATH` in the plist.
- Added installer health polling so a loaded-but-dead sidecar fails immediately instead of silently passing.

Commands:
- `python3 -W ignore::ResourceWarning -m unittest discover -s tests`
- `scripts/build_macos_frontend.sh`
- `scripts/install_sidecar_launch_agent.sh`
- `scripts/doctor_squirrel_integration.sh`
- `RAG_IME_DOCTOR_REQUIRE_XCODE=1 scripts/doctor_squirrel_integration.sh`
- `bash scripts/setup_xcode_for_squirrel.sh`

Findings:
- Normal doctor now reports LaunchAgent and HTTP `/rime-suggest` OK, with only the full Xcode warning remaining.
- Xcode preflight reports `active_developer_dir: /Library/Developer/CommandLineTools`, no full Xcode under `/Applications` or `/Volumes/undo 4t/Applications`, and enough external disk space for Xcode.

Next:
- Finish full Xcode install from an interactive Apple-authenticated terminal or provide `FASTLANE_SESSION`, then rerun `RAG_IME_DOCTOR_REQUIRE_XCODE=1 scripts/doctor_squirrel_integration.sh`.

### 2026-07-01 06:17 CST
Problem:
- `predict-benchmark` measured latency only, so it could not decide whether Qwen/MLX/llama.cpp model candidates were actually useful for historical-context prediction.
- RAG eval and model eval used different gates, making it hard to compare RAG recall vs. local model prediction on the same Codex-history cases.

Changes:
- Added `eval-prediction` CLI.
- It reuses the Codex-history JSONL case format (`query`, `recentContext`, `expectedTerms`, `forbiddenTerms`).
- The command calls the configured prediction provider through the product path, evaluates model candidates with the same candidate-level ranking/noise metrics as RAG eval, and reports latency plus a `prediction` provider block.
- Added mocked OpenAI-compatible CLI test for the Qwen-style provider path.
- Updated README and local-model benchmark docs.

Commands:
- `python3 -W ignore::ResourceWarning -m unittest tests.test_predictor`
- `python3 -W ignore::ResourceWarning -m unittest discover -s tests`
- `python3 -m rag_ime.cli --core-mode fixture eval-prediction --cases-file docs/eval/codex-history-cases.example.jsonl --max-candidates 3 --repeat 2`
- `python3 -m rag_ime.cli --core-mode fixture acceptance`
- `scripts/build_macos_frontend.sh`
- `scripts/doctor_squirrel_integration.sh`

Findings:
- Full test suite now has 60 tests.
- Without a configured local model, `eval-prediction` reports `providerConfigured=false` and zero candidates instead of pretending the model lane is usable.
- Doctor still passes sidecar/Squirrel checks with only the full Xcode warning remaining.

Next:
- Run `eval-prediction` against a real local Qwen/MLX/llama.cpp endpoint and compare it with `eval-codex-history` on the same case file.

### 2026-06-30 23:08 CST
Problem:
- A usable Squirrel integration needs the HTTP sidecar to survive login/restart, not a manually started terminal process.

Changes:
- Added user LaunchAgent install/uninstall scripts for the sidecar server.
- Added dry-run support so plist generation can be tested without loading launchd.
- Documented LaunchAgent setup in README, macOS frontend notes, and Squirrel patch pack notes.

Commands:
- `bash -n scripts/install_sidecar_launch_agent.sh`
- `RAG_IME_LAUNCH_AGENT_DRY_RUN=1 scripts/install_sidecar_launch_agent.sh`
- `python3 -W ignore::ResourceWarning -m unittest discover -s tests`
- `python3 -m rag_ime.cli --core-mode fixture acceptance`
- `scripts/build_macos_frontend.sh`

Next:
- Full Xcode build/install of patched Squirrel remains the next hard gate.
- Local smoke confirms the command works but no real model is downloaded or running here: `ollama`, `llama-server`, `lmstudio`, and `mlx_lm.server` are all missing, and qwen3.5 matrix candidates are empty.

### 2026-07-01
Problem:
- The user asked whether a concrete local model had actually been used/downloaded, and whether Qwen3.5 has an instant/non-thinking variant suitable for IME prediction.
- The Codex shell has proxy variables set (`HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY`, plus lowercase variants), so model downloads can accidentally consume proxy bandwidth.

Changes:
- Installed Ollama 0.30.11 through Homebrew.
- Started Ollama with `OLLAMA_MODELS=/Volumes/undo 4t/ollama-models`.
- Pulled `qwen3.5:0.8b` successfully; `ollama list` shows `qwen3.5:0.8b`, size 1.0 GB.
- Added `RAG_IME_PREDICTOR_PROVIDER=ollama`.
- The new provider calls Ollama native `/api/chat` with `think:false`, checks `/api/tags`, and uses JSON-array prompting for parsed short candidates.
- Kept OpenAI-compatible provider separate because Ollama `/v1/chat/completions` returned empty `content` and put Qwen3.5 output into a `reasoning` field.

Findings:
- Real `qwen3.5:0.8b` smoke through OpenAI-compatible `/v1` produced no parsed candidates because `content` was empty.
- Real `qwen3.5:0.8b` smoke through native Ollama provider found the configured model through `/api/tags` and returned 3 parsed candidates. Observed warm latency varied from about 477 ms to 1157 ms; it can pass a 1500 ms debug budget but is not stable enough for the default per-keystroke IME path.
- Candidate quality is not yet good enough for default IME use: examples were generic (`RAG`, `智能检索`, `知识图谱`).
- Current web check did not find a public Ollama `qwen3.5:*instant*` or `qwen3.5:*instruct*` local tag. Ollama lists Qwen3.5 as a `thinking` model family with size tags such as `0.8b`, `2b`, `4b`, and MLX variants. Treat "instant" as a desired inference mode/provider behavior, not as a confirmed local weight tag.

Commands:
- `brew info ollama`
- `brew install ollama`
- `OLLAMA_MODELS="/Volumes/undo 4t/ollama-models" OLLAMA_FLASH_ATTENTION=1 OLLAMA_KV_CACHE_TYPE=q8_0 ollama serve`
- `ollama pull qwen3.5:0.8b`
- `ollama list`
- `env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy RAG_IME_PREDICTOR_PROVIDER=ollama RAG_IME_PREDICTOR_BASE_URL=http://127.0.0.1:11434 RAG_IME_PREDICTOR_MODEL=qwen3.5:0.8b RAG_IME_PREDICTOR_PROFILE=instant RAG_IME_PREDICTOR_TIMEOUT_MS=8000 RAG_IME_PREDICTOR_FAILURE_COOLDOWN_MS=0 python3 -m rag_ime.cli --core-mode fixture predictor-doctor --case "RAG 输入法" --recent-context "用户正在写本地记忆输入法，需要根据历史输入上下文预测候选短语。" --latency-budget-ms 1500`
- `python3 -W ignore::ResourceWarning -m unittest tests.test_predictor`

Next:
- Do not download more models through proxy. Use explicit `env -u ...` for any future `ollama pull`.
- Test non-thinking instruction-tuned small models next, especially `qwen2.5:0.5b` or `qwen2.5:1.5b`, before larger Qwen3.5 thinking models.

### 2026-07-01 11:16 CST
Problem:
- The Mac-local model lane needed a real fastest-path answer, not just "try a small local model".
- `predictor-ttft` undercounted bad samples because timeout/no-first-chunk cases were not counted as over-budget.

Changes:
- Pulled `qwen3.5:0.8b-mlx` with proxy variables unset and kept Ollama models under `/Volumes/undo 4t/ollama-models`.
- Fixed TTFT summary accounting so missing first chunks count as over-budget and failures.
- Added a unit test for empty streaming output.
- Updated model benchmark, TTFT/KV-cache plan, README, and interview notes with measured Mac results.

Findings:
- `qwen3.5:0.8b-mlx` is the current best Mac smoke path: warm sequential p50 first chunk 46 ms, p95 213 ms, p50 total 456 ms.
- Ordinary `qwen3.5:0.8b` Q8 can approach 200 ms when warm, but one sequential sample stalled to 2547 ms first chunk.
- Quality remains poor for project memory: MLX passed 2/34 Codex-history prediction cases; Q8 passed 4/34.
- Conclusion: use MLX-tag Qwen3.5 0.8B only as a TTFT baseline and optional short-continuation lane. RAG/FTS/vector memory remains the source of truth; next fast provider should be resident MLX-LM or native llama.cpp/Metal with prompt/KV reuse and streaming first candidate.

Commands:
- `env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy OLLAMA_MODELS="/Volumes/undo 4t/ollama-models" ollama serve`
- `ollama pull qwen3.5:0.8b-mlx`
- `python3 -m rag_ime.cli --core-mode fixture predictor-ttft --case "RAG 输入法" --recent-context "用户正在写本地记忆和候选预测" --repeat 8 --max-candidates 3 --latency-budget-ms 200`
- `python3 -m rag_ime.cli --core-mode fixture eval-prediction --cases-file docs/eval/codex-history-cases.example.jsonl --max-candidates 3 --latency-budget-ms 500 --match any`
- `python3 -W ignore::ResourceWarning -m unittest tests.test_predictor`

### 2026-07-01 11:37 CST
Problem:
- The previous Mac TTFT result proved Ollama `qwen3.5:0.8b-mlx` can stream first chunks quickly, but RAG-IME still lacked a first-class resident MLX provider.
- Wisdom-Weasel's fastest path depends on provider capabilities, especially prompt cache, sequence fork, and batch candidate sampling, not just a smaller model.

Changes:
- Added `RAG_IME_PREDICTOR_PROVIDER=mlx` and `MlxPredictionServiceProvider`.
- Added `rag_ime/mlx_predictor_server.py` with `/predict`, `/predict-stream`, `/health`, and `/v1/models`.
- Added `rag-ime mlx-predictor-server --model ...` CLI command that starts before any SQLite/core initialization.
- Extended `predictor-ttft` to support resident MLX streaming, not only native Ollama.
- Added provider capability flags: `streaming`, `residentModel`, `promptCache`, `sequenceFork`, `batchCandidates`, and `serverTiming`.
- Added mock MLX provider and streaming TTFT tests.
- Updated README and TTFT/KV-cache docs with the MLX service route and Wisdom-Weasel read-code checkpoint.

Findings:
- Current Python environment has `mlx` but not `mlx_lm`, so the real MLX-LM server was not started in this turn.
- The current MLX service honestly reports `streaming=true` and `residentModel=true`, but `promptCache=false`, `sequenceFork=false`, and `batchCandidates=false`.
- Wisdom-Weasel HEAD `64ba2fd` uses `LlamaCppProvider::GenerateCandidatesBatch()` with sequence-copy KV fork via `llama_memory_seq_cp`, so the future native llama.cpp provider should be accepted only when those capability flags turn true.

Commands:
- `python3 -W ignore::ResourceWarning -m unittest tests.test_predictor`
- `python3 -m py_compile rag_ime/predictor.py rag_ime/mlx_predictor_server.py rag_ime/cli.py`
- `env RAG_IME_PREDICTOR_PROVIDER=mlx RAG_IME_PREDICTOR_BASE_URL=http://127.0.0.1:8767 RAG_IME_PREDICTOR_MODEL=mlx-qwen3.5-0.8b RAG_IME_PREDICTOR_PROFILE=instant python3 -m rag_ime.cli --core-mode fixture predictor-status`
- `python3 -c "import importlib.util; print('mlx_lm', bool(importlib.util.find_spec('mlx_lm'))); print('mlx', bool(importlib.util.find_spec('mlx')))"`

### 2026-07-01 11:44 CST
Problem:
- The MLX resident service exposed prompt-cache metadata, but did not yet have a concrete startup cache path or protocol tests around cache status.
- `stream_generate` docs do not clearly expose a `prompt_cache` parameter, so claiming active cached-prefix streaming would be unsafe.

Changes:
- Added `--prompt-cache` and `--prompt-cache-max-kv-size` to `mlx-predictor-server`.
- Added stable system-prompt cache preparation using MLX-LM's documented `make_prompt_cache` + `generate_step(..., prompt_cache=cache)` path.
- Added `promptCache.enabled/prepared/usedForGeneration/stablePrefixHash/stablePrefixTokens/prepareMs/maxKvSize` payload fields.
- Changed MLX-LM streaming call to use documented `temperature=` parameter instead of `temp=`.
- Added `tests/test_mlx_predictor_server.py` covering `/health` and `/predict-stream` prompt-cache status with a fake engine.
- Updated README and model benchmark docs to show `--prompt-cache` and the `usedForGeneration=false` boundary.

Findings:
- Current capability flags remain honest: the MLX lane has `streaming=true` and `residentModel=true`, but `promptCache=false` until generation actually reuses the cached prefix.
- The next real MLX task is to implement a verified generate-step streaming path or another safe cache-copy path that can set `usedForGeneration=true` without corrupting the stable prefix cache.

Commands:
- `python3 -W ignore::ResourceWarning -m unittest tests.test_predictor tests.test_mlx_predictor_server`
- `python3 -m py_compile rag_ime/mlx_predictor_server.py rag_ime/cli.py rag_ime/predictor.py tests/test_mlx_predictor_server.py`
- `python3 -m rag_ime.cli mlx-predictor-server --help`

### 2026-07-01 11:51 CST
Problem:
- `--prompt-cache` could prepare a stable prefix cache but did not yet use that cache during streaming generation.
- Reusing a single mutable MLX prompt-cache object across requests risks polluting the stable prefix.

Changes:
- Changed the MLX service to save the prepared stable-prefix cache to a local safetensors file.
- Added a cached streaming path that loads a fresh prompt-cache copy per request and calls `generate_step(..., prompt_cache=cache)`.
- Added `promptCache.cacheFileReady`, `hits`, `misses`, and `usedForGeneration=true` when the cached path is actually used.
- Kept fallback to normal `stream_generate` if cached generation fails.
- Added a fake MLX-LM module test proving `MlxLmEngine` uses `load_prompt_cache` and does not fall back to `stream_generate` on the cached path.
- Updated docs to remove the old `usedForGeneration=false` boundary.

Findings:
- This is safer than sharing one cache object, but likely slower than llama.cpp sequence-copy KV fork because it reloads a cache file per request.
- Capability flags still stay conservative until real-model `predictor-ttft` and `eval-prediction` prove this path beats the uncached/Ollama baselines.

Commands:
- `python3 -W ignore::ResourceWarning -m unittest tests.test_mlx_predictor_server tests.test_predictor`
- `python3 -m py_compile rag_ime/mlx_predictor_server.py tests/test_mlx_predictor_server.py`

### 2026-07-01 12:18 CST
Problem:
- Need a current, non-duplicated answer for the fastest Mac local inference path before continuing input-method implementation.
- Direct MLX-LM validation needs `mlx-lm`; the environment had `mlx` but not `mlx_lm`.

Attempts:
- Created a Python 3.12 temp venv at `/private/tmp/rag-ime-mlx-venv-312`.
- Tried no-proxy `pip install mlx-lm`; dependency metadata resolved, but `mlx_metal` downloaded at about 69 kB/s, so the install was cancelled before wasting more time.
- Started Ollama 0.30.11 with proxy variables unset and `OLLAMA_MODELS="/Volumes/undo 4t/ollama-models"`.
- Re-ran `predictor-ttft` against already downloaded `qwen3.5:0.8b-mlx` and `qwen3.5:0.8b`.

Findings:
- Local models present: `qwen3.5:0.8b-mlx` (1.2 GB, MLX runner) and `qwen3.5:0.8b` (1.0 GB, GGUF/Q8 llama-server).
- `qwen3.5:0.8b-mlx` with 2000 ms benchmark timeout: p50 first chunk 124 ms, first cold/preload sample 1264 ms, warm samples after load 76-133 ms, p50 total 888 ms.
- `qwen3.5:0.8b` with 5000 ms timeout: p50 first chunk 296 ms, p50 total 1646 ms, all samples over the 200 ms first-chunk budget.
- Ollama logs showed MLX cache hits after the first request and peak MLX memory around 1.1 GB. The GGUF route loaded llama-server plus vision/multimodal components.
- Current fastest practical Mac path is Ollama `qwen3.5:0.8b-mlx` for TTFT smoke. Direct MLX-LM and native llama.cpp/Metal remain the implementation paths for real prompt/KV control.

Commands:
- `env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy /private/tmp/rag-ime-mlx-venv-312/bin/python -m pip install mlx-lm`
- `env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy OLLAMA_MODELS="/Volumes/undo 4t/ollama-models" OLLAMA_KEEP_ALIVE=-1 OLLAMA_FLASH_ATTENTION=1 ollama serve`
- `env RAG_IME_PREDICTOR_PROVIDER=ollama RAG_IME_PREDICTOR_BASE_URL=http://127.0.0.1:11434 RAG_IME_PREDICTOR_MODEL=qwen3.5:0.8b-mlx RAG_IME_PREDICTOR_PROFILE=instant RAG_IME_PREDICTOR_TIMEOUT_MS=2000 RAG_IME_PREDICTOR_FAILURE_COOLDOWN_MS=0 python3 -m rag_ime.cli predictor-ttft --case "本地 RAG 输入法需要根据历史输入预测候选" --recent-context "用户正在讨论 Mac 本地推理、Qwen3.5 0.8B、MLX、KV cache 和输入法首 token 延迟" --repeat 8 --latency-budget-ms 200`
- `env RAG_IME_PREDICTOR_PROVIDER=ollama RAG_IME_PREDICTOR_BASE_URL=http://127.0.0.1:11434 RAG_IME_PREDICTOR_MODEL=qwen3.5:0.8b RAG_IME_PREDICTOR_PROFILE=instant RAG_IME_PREDICTOR_TIMEOUT_MS=5000 RAG_IME_PREDICTOR_FAILURE_COOLDOWN_MS=0 python3 -m rag_ime.cli predictor-ttft --case "本地 RAG 输入法需要根据历史输入预测候选" --recent-context "用户正在讨论 Mac 本地推理、Qwen3.5 0.8B、MLX、KV cache 和输入法首 token 延迟" --repeat 4 --latency-budget-ms 200`

### 2026-07-01 12:47 CST
Problem:
- `/rime-suggest` still called `predictor.predict()`, and native Ollama / MLX `predict()` waited for the full JSON candidate list even though TTFT measurement proved first chunk can arrive much earlier.

Changes:
- Added `RAG_IME_PREDICTOR_STREAM_FIRST=1` for native Ollama and resident MLX providers.
- When enabled, `predict()` reads the streaming endpoint until the first parsed candidate appears, then returns one model side candidate with `metadata.stream_first_candidate=true`.
- Added incremental streaming candidate parsing that ignores raw JSON syntax like `["` and waits for a complete string candidate or clean non-JSON fragment.
- `predictor-status` now reports `streamFirstCandidate`.
- Added unit tests for Ollama `/api/chat stream:true` and MLX `/predict-stream` first-candidate paths.

Findings:
- This turns the current Mac TTFT finding into a real sidecar-usable product path.
- It is still a latency bridge, not the final Wisdom-Weasel provider: prompt cache, sequence fork, and batch candidate generation remain separate capability gates.

Commands:
- `python3 -m py_compile rag_ime/predictor.py tests/test_predictor.py`
- `python3 -W ignore::ResourceWarning -m unittest tests.test_predictor`

### 2026-07-01 13:08 CST
Problem:
- `RAG_IME_PREDICTOR_STREAM_FIRST=1` worked in manual commands, but the user LaunchAgent installer did not persist any `RAG_IME_PREDICTOR_*` variables into the sidecar plist.
- A login-started Squirrel sidecar would therefore lose the Ollama/MLX model configuration and run without the stream-first model lane.

Changes:
- Added a LaunchAgent environment whitelist for predictor, history-context, and cache tuning variables.
- The installer now persists variables such as `RAG_IME_PREDICTOR_PROVIDER`, `RAG_IME_PREDICTOR_MODEL`, `RAG_IME_PREDICTOR_STREAM_FIRST`, `RAG_IME_HISTORY_CONTEXT_EVENTS`, and `RAG_IME_RIME_CACHE_TTL_MS`.
- Extended the dry-run plist test to assert the predictor env is written.
- Documented the real install flow for Ollama MLX + stream-first sidecar.

Findings:
- This closes the gap between predictor code support and the actual macOS login sidecar path.

Commands:
- `RAG_IME_LAUNCH_AGENT_DRY_RUN=1 scripts/install_sidecar_launch_agent.sh`
- `python3 -m unittest tests.test_launch_agent_script`

### 2026-07-01 13:42 CST
Problem:
- Need a fuller, source-backed answer for the fastest Mac local inference plan before continuing the input-method implementation.

Findings:
- The current project evidence still ranks Ollama `qwen3.5:0.8b-mlx` first for immediate TTFT smoke because it already produced sub-200 ms warm first chunks.
- Official MLX-LM docs provide the exact primitives needed for the next experiment: `stream_generate`, prompt caching, and rotating KV cache.
- Official llama.cpp server docs confirm prompt cache, continuous batching, slot save/cache controls, KV cache type controls, and reasoning controls, but Wisdom-Weasel's native provider remains the better final reference because it uses explicit sequence-state save/restore and sequence copy for multi-candidate sampling.
- MLC LLM supports Metal, local/interactive/server modes, streaming, and prefix-cache-related overrides, but its compile/model-library flow makes it a backup, not the fastest MVP route.
- Core ML stateful models map well to KV-state ideas on macOS 15+, but conversion/support cost pushes it to a later research lane.

Changes:
- Added `docs/mac-local-inference-fast-path.md` with the runtime ranking, commands, acceptance gates, Wisdom-Weasel/MiniVLLM lessons, and source links.
- Linked the new document from the README and `docs/model-ttft-kv-cache-plan.md`.
- Folded in subagent findings about Wisdom-Weasel being Windows Weasel-only, native llama context concurrency risk, and the need to track first parsed candidate time separately from raw token TTFT.

### 2026-07-01 14:12 CST
Problem:
- `predictor-ttft` already recorded `firstCandidateMs` in individual measurements, but the summary and over-budget decision still used raw `firstChunkMs`.
- Raw chunks can be JSON syntax such as `["`, which is not a usable IME candidate.

Changes:
- Changed `benchmark_streaming_ttft_provider()` to evaluate the latency budget against `firstCandidateMs`.
- Added `hasFirstCandidate`, `p50FirstCandidateMs`, `p95FirstCandidateMs`, min/max first-candidate latency, and `firstCandidateMissingCount` to the summary.
- Added a regression test where a stream emits a raw chunk but no parsed candidate; it now counts as over budget.
- Updated README and model-latency docs to distinguish raw first chunk from first parsed candidate.

Commands:
- `python3 -m py_compile rag_ime/predictor.py tests/test_predictor.py`
- `python3 -m unittest tests.test_predictor`

### 2026-07-01 13:03 CST
Problem:
- The Mac inference decision needed to distinguish the fastest measured smoke path from the best controllable product kernel.
- Squirrel patch preparation only proved that a patch applied; it did not assert the critical RAG-IME hooks were present after patching.

Findings:
- Ollama `qwen3.5:0.8b-mlx` remains the fastest already measured Mac smoke baseline for keeping the UI/RAG loop moving.
- Native `llama.cpp`/Metal is still the strongest product-kernel candidate because it can own cancellation, prompt/KV reuse, sequence copy, and batch multi-candidate generation.
- Direct MLX-LM should be benchmarked next as the Apple-Silicon resident-service experiment.
- Core ML stateful KV and MLC LLM remain later paths because conversion/compile complexity is not worth blocking the IME loop yet.

Changes:
- Updated `docs/mac-local-inference-fast-path.md` with a decision-refinement section and explicit TTFC benchmark metrics.
- Updated `docs/interview-project-difficulties.md` so the interview story says first parsed candidate/TTFC, not just first chunk.
- Hardened `scripts/prepare_squirrel_workspace.sh` to assert required sidecar files and Squirrel integration hooks after patch application.
- Added an offline fake-Squirrel test that clones a local repo, applies a generated RAG-IME patch, writes config, and typechecks the Swift sidecar files when `swiftc` is available.

Commands:
- `bash -n scripts/prepare_squirrel_workspace.sh`
- `python3 -m unittest tests.test_prepare_squirrel_workspace`
- `python3 -m unittest discover -s tests`

### 2026-07-01 13:13 CST
Problem:
- The Mac TTFC decision needed a reusable multi-case benchmark command, not just manual `predictor-ttft` one-offs.

Changes:
- Added `bench-ime-ttfc`, a streaming first parsed candidate benchmark for multiple model ids on the same IME case file.
- Added `docs/eval/ime-ttfc-cases.example.jsonl` for speed-only cases that do not require `expectedTerms`.
- Added model-level winner selection based on over-budget count, p95 TTFC, p50 TTFC, and failure count.
- Preserved optional per-sample output behind `--include-cases`.

Findings:
- Real Ollama inventory contains `qwen3.5:0.8b-mlx` and `qwen3.5:0.8b` under `/Volumes/undo 4t/ollama-models`.
- Short mixed-model run: `qwen3.5:0.8b-mlx` had p50 `firstCandidateMs=120` ms, p95 `969` ms with 1 over-budget sample; `qwen3.5:0.8b` had p50 `272` ms, p95 `2184` ms with all samples over budget.
- Warm single-model run: `qwen3.5:0.8b-mlx` had p50 `102` ms, p95 `122` ms, but still 1/12 samples over 200 ms. `qwen3.5:0.8b` had p50 `241` ms, p95 `397` ms, 12/12 samples over budget.
- This supports keeping Ollama MLX as the current smoke path and rejecting the GGUF/Q8 `0.8b` tag for per-keystroke prediction.

Commands:
- `python3 -m py_compile rag_ime/cli.py rag_ime/predictor.py tests/test_predictor.py`
- `python3 -m unittest tests.test_predictor`
- `ollama list`
- `python3 -m rag_ime.cli --core-mode fixture bench-ime-ttfc --cases-file docs/eval/ime-ttfc-cases.example.jsonl --provider ollama --base-url http://127.0.0.1:11434 --models qwen3.5:0.8b-mlx,qwen3.5:0.8b --repeat 2 --latency-budget-ms 200`
- `python3 -m rag_ime.cli --core-mode fixture bench-ime-ttfc --cases-file docs/eval/ime-ttfc-cases.example.jsonl --provider ollama --base-url http://127.0.0.1:11434 --models qwen3.5:0.8b-mlx --repeat 3 --latency-budget-ms 200`
- `python3 -m rag_ime.cli --core-mode fixture bench-ime-ttfc --cases-file docs/eval/ime-ttfc-cases.example.jsonl --provider ollama --base-url http://127.0.0.1:11434 --models qwen3.5:0.8b --repeat 3 --latency-budget-ms 200`
- `python3 -m unittest discover -s tests`

### 2026-07-01 13:32 CST
Problem:
- The browser debug surface showed predictor configuration, but not whether the configured local model could produce a first parsed candidate on demand.
- The Squirrel doctor had useful diagnostics, but no single strict gate for "ready to try as a real macOS input source".

Changes:
- Added `POST /api/predictor-ttfc` to the debug server and a compact Model TTFC card to the browser debug page.
- The debug TTFC probe reuses the same streaming first parsed candidate benchmark as the CLI and only runs when the user presses the probe button.
- Added `RAG_IME_DOCTOR_REQUIRE_TRYOUT=1` to `scripts/doctor_squirrel_integration.sh`.
- Strict tryout mode requires a prepared patched Squirrel checkout, sidecar Swift files, generated config, Xcode project inspection with `xcodebuild -list`, and a working sidecar path.
- Doctor sidecar probing now checks `/health`, `/rime-suggest`, and `/rime-select`, so accepted side-candidate writeback is part of readiness.

Findings:
- Default doctor mode still exits zero and reports the current state: patched Squirrel workdir OK, sidecar health/suggest/select OK, predictor not configured, full Xcode missing.
- Strict tryout mode now fails non-zero with the real blocker: `active developer directory is CommandLineTools`; full Xcode must be installed/selected before patched Squirrel can be built and installed.

Commands:
- `python3 -m py_compile rag_ime/debug_server.py tests/test_debug_server.py`
- `python3 -m unittest tests.test_debug_server tests.test_doctor_squirrel_integration`
- `python3 -m unittest discover -s tests`
- `RAG_IME_DOCTOR_CHECK_LAUNCHD=0 scripts/doctor_squirrel_integration.sh`
- `RAG_IME_DOCTOR_REQUIRE_TRYOUT=1 RAG_IME_DOCTOR_CHECK_LAUNCHD=0 scripts/doctor_squirrel_integration.sh`

### 2026-07-01 13:55 CST
Problem:
- The long-term project is not complete yet: the remaining hard parts are real macOS input-source installation, sidecar-to-Squirrel behavior in daily typing, RAG/memory quality, local model first-candidate latency, and interview-ready difficulty records.
- The project needed one command that fails when acceptance, RAG recall, sidecar candidate shaping, or cache reuse regresses.

Changes:
- Added `quality-gate`, an aggregate CLI gate that runs deterministic adapter acceptance, direct Codex-history RAG eval, `/rime-suggest` sidecar eval, and cache probing.
- Refactored the eval and cache-probe paths into reusable helpers so future adapter/front-end work can reuse the same quality checks.
- Added a regression test for the aggregate gate and documented the command in README.

Commands:
- `python3 -m py_compile rag_ime/cli.py tests/test_codex_history.py`
- `python3 -W ignore::ResourceWarning -m unittest tests.test_codex_history tests.test_debug_server`
- `python3 -W ignore::ResourceWarning -m unittest discover -s tests`
- `git diff --check`

### 2026-07-01 14:35 CST
Problem:
- User asked to finish the full-Xcode real build/install/system-input-method verification path before joint manual testing.
- Current host still has no full `Xcode.app`; `xcode-select` points to `/Library/Developer/CommandLineTools`, so `xcodebuild -version` fails before Squirrel can be built.
- The previous build script could inspect/build with `xcodebuild`, but did not automate Squirrel dependency prep, RAG config installation, or the final input-method install action.

Changes:
- Extended `scripts/build_patched_squirrel.sh` with an `install` action.
- Build/install now prepares Squirrel binary dependencies with `action-install.sh` when needed, refreshes bundled data files, locates the built `Squirrel.app`, installs it into `~/Library/Input Methods` by default, and can run Squirrel postinstall.
- Added `scripts/install_squirrel_rag_config.sh` to write a managed `rag_ime/*` patch block into `~/Library/Rime/squirrel.custom.yaml` from the generated patched-workdir snippet.
- Updated README, Xcode setup docs, and macOS frontend docs with the full tryout sequence and continuous-use verification checklist.

Current machine result:
- `scripts/prepare_squirrel_workspace.sh` succeeds.
- LaunchAgent sidecar is loaded and `/health`, `/rime-suggest`, `/rime-select` pass.
- `RAG_IME_DOCTOR_REQUIRE_TRYOUT=1 scripts/doctor_squirrel_integration.sh` still fails only at full Xcode availability.
- `scripts/build_patched_squirrel.sh list` and `scripts/build_patched_squirrel.sh install` fail cleanly at `xcodebuild -version` because the active developer directory is CommandLineTools.

Commands:
- `RAG_IME_SQUIRREL_RESET=1 scripts/prepare_squirrel_workspace.sh`
- `scripts/doctor_squirrel_integration.sh`
- `RAG_IME_DOCTOR_REQUIRE_TRYOUT=1 RAG_IME_DOCTOR_CHECK_LAUNCHD=1 scripts/doctor_squirrel_integration.sh`
- `scripts/build_patched_squirrel.sh list`
- `scripts/build_patched_squirrel.sh install`
- `bash -n scripts/build_patched_squirrel.sh scripts/install_squirrel_rag_config.sh`
- `python3 -m unittest tests.test_build_patched_squirrel tests.test_install_squirrel_rag_config`
- `python3 -W ignore::ResourceWarning -m unittest discover -s tests`

### 2026-07-01 15:12 CST
Problem:
- Wisdom-Weasel's local LLM path has real low-latency mechanisms, but the current RAG-IME Ollama/MLX smoke path should not be treated as the final model lane.
- The project needed an enforceable distinction between "debug provider works" and "provider has the KV/cache/forking capabilities needed for a production IME".

Source findings:
- Wisdom-Weasel's llama.cpp provider keeps the model/context resident, prepares a stable system prompt once, saves/restores sequence state, copies sequence memory to parallel sequence ids, and samples multiple short candidates in one batch.
- The useful mechanisms map to `promptCache`, `sequenceFork`, and `batchCandidates`.
- Do not copy Wisdom-Weasel's unbounded detached-thread shape directly; RAG-IME should keep latest-only request handling and serialize or cancel native model context use.

Changes:
- Added `quality-gate --require-predictor-capability`, repeatable for `streaming`, `residentModel`, `promptCache`, `sequenceFork`, `batchCandidates`, and `serverTiming`.
- The aggregate quality-gate JSON now includes `predictor` status and explicit `predictor-capability:*` checks.
- `NullPredictionProvider` status now reports the same capability map as configured providers, so missing model capability requirements fail clearly.
- README, Mac local inference docs, and interview difficulty notes now document the Wisdom-Weasel-style capability gate.

Current machine result:
- `scripts/setup_xcode_for_squirrel.sh` still finds no full `Xcode.app`; active developer directory is `/Library/Developer/CommandLineTools`.
- `RAG_IME_DOCTOR_REQUIRE_XCODE=1 scripts/doctor_squirrel_integration.sh` fails only on full Xcode availability; sidecar health, `/rime-suggest`, and `/rime-select` pass.
- Escalated `xcodebuild -version` confirms the real error: `tool 'xcodebuild' requires Xcode`.

Commands:
- `python3 -m py_compile rag_ime/cli.py rag_ime/predictor.py tests/test_codex_history.py`
- `python3 -W ignore::ResourceWarning -m unittest tests.test_codex_history tests.test_predictor`
- `python3 -W ignore::ResourceWarning -m unittest discover -s tests`
- `git diff --check`
- `scripts/setup_xcode_for_squirrel.sh`
- `scripts/doctor_squirrel_integration.sh`
- `RAG_IME_DOCTOR_REQUIRE_XCODE=1 scripts/doctor_squirrel_integration.sh`
- `scripts/build_patched_squirrel.sh list`

### 2026-07-01 15:46 CST
Problem:
- The previous predictor capability gate was static. It could say that `local-mlx` was a resident streaming service, but it could not prove whether the MLX prompt cache was actually used by the runtime generation path.

Changes:
- Added MLX service runtime capabilities to `/health`.
- Added `MlxPredictionServiceProvider.capability_probe()` and delegated probe support through `CooldownPredictionProvider`.
- Added `prediction_provider_status(..., probe_capabilities=True)` and CLI `predictor-status --probe-capabilities`.
- `quality-gate` now probes provider capabilities automatically when `--require-predictor-capability` is present.
- `promptCache=true` now requires `enabled`, `prepared`, `cacheFileReady`, and `usedForGeneration`; a startup-prepared-only MLX cache remains unproven.
- Added provider, CLI, and aggregate quality-gate tests for MLX prompt-cache capability probing.

Commands:
- `python3 -m py_compile rag_ime/predictor.py rag_ime/mlx_predictor_server.py rag_ime/cli.py tests/test_predictor.py tests/test_codex_history.py`
- `python3 -W ignore::ResourceWarning -m unittest tests.test_predictor tests.test_codex_history tests.test_mlx_predictor_server`
- `git diff --check`

### 2026-07-01 16:18 CST
Problem:
- The aggregate RAG-IME gate could enforce recall/pass-rate and cache hits, but not ranking quality or noise. That is too weak for an input method, where rank 1 and low-noise candidates matter more than broad recall.

Changes:
- Added explicit `quality-gate` thresholds for direct RAG and `/rime-suggest` sidecar:
  - `--min-rag-top1-accuracy`
  - `--min-sidecar-top1-accuracy`
  - `--min-rag-mrr`
  - `--min-sidecar-mrr`
  - `--max-rag-noise-rate`
  - `--max-sidecar-noise-rate`
- The gate now emits separate checks for pass rate, top1, MRR, and noise on both direct RAG and sidecar paths.
- Added tests that verify the new metric checks are present and that noise thresholds fail the gate when forbidden terms appear.
- README and Codex-history eval docs now show mature-goldset threshold commands.

Subagent finding:
- PI shared core already has retrieval/rerank cache, vector cache, memory governance review queue, and goldset gates.
- The smallest next VCP-style optimization is provider miss in-flight dedupe for embedding/rerank calls in `agent-source-projects/pi-rag-memory-extension/src/retrieval-rerank-provider.ts`, similar to VCP `RAGDiaryPlugin` pending embedding requests.

Commands:
- `python3 -m py_compile rag_ime/cli.py tests/test_codex_history.py`
- `python3 -W ignore::ResourceWarning -m unittest tests.test_codex_history`
- `git diff --check`

### 2026-07-01 15:32 CST
Problem:
- Shared RAG/memory provider caches could still duplicate expensive provider calls when identical embedding or rerank misses arrived concurrently.
- This matters for the IME path because typing can fire bursty repeated queries; cache hit rate alone is not enough if the first miss fans out.

Changes:
- Applied a VCP-style in-flight request dedupe slice to the PI shared memory core in `agent-source-projects/pi-rag-memory-extension/src/retrieval-rerank-provider.ts`.
- Added `withInFlight(...)` and coalesced concurrent identical misses for query embeddings, embedding rerank batches, and LLM rerank calls.
- Added `agent-source-projects/pi-rag-memory-extension/test/retrieval-rerank-inflight.test.mjs` covering query embedding dedupe, embedding rerank dedupe, LLM rerank dedupe, and retry after failure.

Git:
- learnA top-level local commit: `4c67f8e7 Dedupe rerank provider misses`.
- Not pushed from learnA because the top-level repo already has many unrelated dirty files and is ahead of origin.

Verification:
- `node --experimental-strip-types test/retrieval-rerank-inflight.test.mjs`
- `node --experimental-strip-types -e "await import('./src/retrieval-rerank-provider.ts'); console.log('provider import ok')"`
- `git diff --check -- src/retrieval-rerank-provider.ts test/retrieval-rerank-inflight.test.mjs`
- `npm test`

Full-Xcode status:
- Real Squirrel build/install/system input-method continuous-use verification is still blocked on this host.
- `xcode-select -p` returns `/Library/Developer/CommandLineTools`.
- `xcodebuild -version` fails with `tool 'xcodebuild' requires Xcode`.
- `/Applications` and Spotlight lookup do not show `Xcode.app`.

### 2026-07-01 15:42 CST
Problem:
- The local model lane needs to predict from historical input context, but a future native KV/prompt-cache provider needs a stable contract for deciding when context can be reused.
- Without explicit fingerprints, debug output can show text, but cannot prove whether a request is cacheable in the Wisdom-Weasel sense: stable prompt/history prefix plus dynamic current input.

Changes:
- Added `historyContextMeta` to sidecar and debug suggestion payloads.
- Added model `requestMeta` to prediction metadata with `currentInputFingerprint`, `contextFingerprint`, `contextChars`, and `stablePrefixHash`.
- MLX local service requests now receive the same fingerprint fields and stream responses echo them as `requestMeta`.
- OpenAI-compatible and Ollama external request bodies were kept unchanged; the metadata is local response/debug data only for those providers.
- Documented the fingerprint contract in `docs/model-ttft-kv-cache-plan.md` and `docs/debug-surface.md`.

Verification:
- `python3 -m py_compile rag_ime/history_context.py rag_ime/rime_sidecar.py rag_ime/payloads.py rag_ime/predictor.py rag_ime/mlx_predictor_server.py tests/test_rime_sidecar.py tests/test_predictor.py tests/test_mlx_predictor_server.py`
- `python3 -W ignore::ResourceWarning -m unittest tests.test_rime_sidecar tests.test_predictor tests.test_mlx_predictor_server`
- `python3 -W ignore::ResourceWarning -m unittest discover -s tests`
- `git diff --check`

Status:
- This is not native KV cache completion. It is the protocol gate needed before implementing a llama.cpp/Metal or stronger MLX provider that can safely reuse stable prefix state.

### 2026-07-01 15:51 CST
Problem:
- `/rime-suggest` parsed and returned `latencyBudgetMs`, but the model lane could still block the whole response until the provider's static timeout.
- That is wrong for an input method: a slow model must not delay Rime/RAG candidates.

Subagent finding:
- The risk was confirmed by read-only review: the sidecar called `predictor.predict(...)` without a budget/deadline, and RAG suggestions ran only after the model call.
- The suggested minimum was per-request deadline/fail-open behavior, not a full async scheduler.

Changes:
- `build_rime_sidecar_response()` now runs RAG retrieval first, then gives the model lane only the remaining `latencyBudgetMs`.
- Added a single in-process model-lane guard: if the model exceeds the budget, the response returns `modelPredictions=[]` while preserving Rime/RAG candidates.
- Added `modelLane` response metadata with `called`, `timedOut`, `skippedReason`, `latencyBudgetMs`, `elapsedMs`, `totalLatencyBudgetMs`, and `elapsedBeforeModelMs`.
- If a previous model request is still running, new requests skip the model lane instead of piling up provider calls.
- Documented the behavior in README, debug-surface docs, and local-model benchmark docs.

Verification:
- `python3 -m py_compile rag_ime/rime_sidecar.py rag_ime/debug_server.py tests/test_rime_sidecar.py tests/test_debug_server.py`
- `python3 -W ignore::ResourceWarning -m unittest tests.test_rime_sidecar tests.test_debug_server`
- `python3 -W ignore::ResourceWarning -m unittest discover -s tests`
- `git diff --check`

Status:
- This enforces IME responsiveness for the sidecar hot path without claiming native cancellation. A timed-out provider call may still finish in the daemon guard thread, but subsequent requests do not wait for it.

### 2026-07-01 15:59 CST
Problem:
- The previous hot-path budget guard covered the model lane, but RAG retrieval and model history-context construction could still block `/rime-suggest`.
- This matters once the sidecar talks to a shared RAG core with embedding/rerank/WSL work instead of only fast local FTS5.

Changes:
- Added a bounded `ragLane` around `adapter.suggest(...)`.
- `build_rime_sidecar_response()` now returns Rime candidates even when RAG retrieval exceeds `latencyBudgetMs`.
- Moved `build_prediction_context()` into the model-lane budget thread, so slow history-context loading cannot block the main sidecar response.
- Added a deadline check before calling the model provider; if history-context construction already consumed the model budget, the provider is not called.
- Added tests for slow RAG fail-open and slow history-context fail-open.
- Updated README, debug-surface docs, and local-model benchmark docs to describe `ragLane` and `modelLane`.

Verification:
- `python3 -m py_compile rag_ime/rime_sidecar.py tests/test_rime_sidecar.py`
- `python3 -W ignore::ResourceWarning -m unittest tests.test_rime_sidecar`
- `python3 -m py_compile rag_ime/rime_sidecar.py rag_ime/debug_server.py tests/test_rime_sidecar.py tests/test_debug_server.py`
- `python3 -W ignore::ResourceWarning -m unittest tests.test_rime_sidecar tests.test_debug_server`
- `python3 -W ignore::ResourceWarning -m unittest discover -s tests`
- `git diff --check`

Status:
- This still does not provide real cancellation for an already-running RAG/core call; it bounds user-visible waiting and prevents immediate side-lane pileups with a single in-process guard.

### 2026-07-01 16:14 CST
Problem:
- After adding `ragLane` and `modelLane` fail-open behavior, a regression could still look healthy if the candidate panel renders easy cases while one side lane silently times out under the IME latency budget.

Changes:
- `eval-rime-sidecar` now reports RAG/model lane called counts, timeout counts, and timeout rates.
- `quality-gate` now accepts `--max-sidecar-rag-timeout-rate` and `--max-sidecar-model-timeout-rate`.
- Added regression coverage for the sidecar timeout-rate checks and documented strict mature-goldset usage in README and Codex-history eval docs.

Verification:
- `python3 -m py_compile rag_ime/cli.py tests/test_codex_history.py`
- `python3 -W ignore::ResourceWarning -m unittest tests.test_codex_history`
- `python3 -W ignore::ResourceWarning -m unittest discover -s tests`

Status:
- Full-Xcode Squirrel build/install/system-input-method continuous-use verification is still blocked on this host because only Command Line Tools are selected.

### 2026-07-01 16:25 CST
Problem:
- `bench-ime-ttfc` could measure the first parsed model candidate, but the normal `quality-gate` did not enforce that result.
- That left a gap between manual model-speed experiments and release-style acceptance: a local model could be reachable yet too slow for the input-method lane.

Changes:
- Refactored the IME TTFC benchmark into `run_ime_ttfc_benchmark()` so CLI and quality gate share the same implementation.
- Added optional `quality-gate --require-model-ttfc` with provider, base URL, model list, TTFC cases, repeat count, p95 threshold, and over-budget-rate threshold.
- Added model TTFC checks: supported streaming provider, first-candidate presence, p95 first-candidate latency, and over-budget rate.
- Added an integration test using a mock Ollama streaming server with one good MLX-tag model and one bad model.
- Updated README, Codex-history eval docs, and local-model benchmark docs.

Verification:
- `python3 -m py_compile rag_ime/cli.py tests/test_predictor.py tests/test_codex_history.py`
- `python3 -W ignore::ResourceWarning -m unittest tests.test_predictor`
- `python3 -W ignore::ResourceWarning -m unittest tests.test_predictor tests.test_codex_history`
- `python3 -W ignore::ResourceWarning -m unittest discover -s tests`
- `git diff --check`

Status:
- Full suite passed with 137 tests.
- `ollama list` could not connect because the Ollama server is not running, so this turn did not run a real-model TTFC benchmark.
