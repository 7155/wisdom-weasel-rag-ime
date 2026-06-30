# Chat Summary

### 2026-07-01
Topic:
- Add lightweight local rerank for real Codex-history RAG quality.

Changes:
- Boyle subagent returned no patch, so main thread implemented the rerank.
- Added query expansion for agent first-run injection, Squirrel/Rime, dirty pinyin, and local RAG memory concepts.
- Added field-aware boosts for committed text, recent context, tags, source/app/schema/provider, and raw ASCII project terms.
- Increased internal candidate pool before compiling visible top-K suggestions.
- Preserved explicit user governance by raising pinned-memory priority.

Verification:
- Local SQLite core tests passed: 13 tests.
- Full suite passed: 70 tests; fixture acceptance and `git diff --check` passed.
- Real 2000-record Codex-history eval reached `passRate=1.0`, `top1Accuracy=1.0`, `MRR=1.0`.
- Real 500-record eval reached `passRate=0.67`; Squirrel/RAG and Agent-hook became top1.

Next:
- Continue toward hybrid/vector recall and compare against VCP-style memory/cache behavior on the same benchmark.

### 2026-07-01
Topic:
- Make real Codex-history import usable as a RAG-IME benchmark.

Changes:
- Added newest-first directory import for Codex JSONL sessions via `--path-order mtime-desc`.
- Filtered common runtime noise before importing records: developer/system prompts, `AGENTS.md`, environment/sandbox blocks, tool output, and token-count style events.
- Preserved legacy Codex JSONL parsing compatibility and updated evaluation docs.

Verification:
- Codex-history tests passed: 10 tests.
- Real dry-run now samples the active RAG-IME session instead of old environment context.
- Real 2000-record eval passed 2 of 3 base cases; cache hit rate reached 0.5 on repeat, and the dirty-pinyin/Rime case was top1.

Next:
- Use this benchmark to verify the lightweight tag/app/context rerank and later hybrid/vector recall.

### 2026-07-01
Topic:
- Add instant local-model prediction profiles.

Changes:
- Added `RAG_IME_PREDICTOR_PROFILE=instant` for small instruct models: chat mode, 350 ms timeout, 8 output tokens, low sampling, and thinking disabled.
- Added `RAG_IME_PREDICTOR_PROFILE=completion-instant` for base-model or llama.cpp-style completion servers.
- Added `RAG_IME_PREDICTOR_DISABLE_THINKING=1`.
- The setting injects `chat_template_kwargs.enable_thinking=false` while preserving extra request-body fields.
- Prediction benchmark and eval reports now expose `providerProfile`.
- Updated local model docs and Wisdom-Weasel issue mapping.

Verification:
- Predictor tests passed: 8 tests.
- Predictor + Codex-history tests passed: 17 tests.
- Full suite passed: 67 tests.
- Fixture eval, fixture acceptance, instant-profile fail-open benchmark, `py_compile`, and `git diff --check` passed.
- Real local-model speed testing is still pending because no model endpoint was listening on 127.0.0.1 ports 8000, 8080, 1234, or 11434.

### 2026-07-01
Topic:
- Improve `/rime-suggest` cache hits for real IME composing refreshes.

Changes:
- Replaced raw-payload hashing with a semantic Rime snapshot cache key.
- The key now ignores raw pinyin/preedit changes when the semantic query is already commit preview or stable Rime candidates.
- Cached responses rewrite current request metadata before returning so debug output stays accurate.
- Added a debug-server regression test.

Verification:
- Debug server tests passed: 13 tests.
- `py_compile` passed.
- Full suite passed: 65 tests.
- Fixture acceptance and `git diff --check` passed.

### 2026-07-01
Topic:
- Confirm VCP BM25 usage and fix RAG-IME SQLite FTS5 ranking.

Decisions:
- VCP should be treated as hybrid/vector-first inspiration, not a pure BM25 reference: main memory uses vector search plus TagMemo/rerank/cache; cold TDB knowledge can use hybrid search with BM25 sparse input and vector fallback.
- RAG-IME keeps local FTS5/BM25 as a fast lexical baseline, then evolves toward hybrid retrieval and VCP-style memory governance.

Changes:
- Added `_bm25_relevance()` so negative SQLite FTS5 BM25 scores increase lexical ranking instead of being flattened.
- Exposed the lexical contribution in suggestion reasons and added a regression test.

Verification:
- Local SQLite core regression passed: 11 tests.
- Full suite passed: 64 tests.
- `py_compile`, `git diff --check`, and fixture acceptance passed.

### 2026-07-01
Topic:
- Add full-flow RAG vs model evaluation.

Changes:
- Added `eval-comparison`.
- The command runs local RAG suggestions and local model predictions on the same JSONL cases and emits `rag`, `model`, and `comparison` blocks.
- `comparison` reports `bothPassed`, `ragOnlyPassed`, `modelOnlyPassed`, `neitherPassed`, metric winners, per-case surfaces, and latency.
- README and Codex-history eval docs now describe when to use it for local model selection.

Verification:
- Codex-history tests passed.
- Full suite now has 63 tests and passed.
- Fixture CLI comparison works with no model configured, showing RAG results and model fail-open state.

Next:
- Use `eval-comparison` against real imported Codex history and real local model endpoints.

### 2026-07-01
Topic:
- Add a Wisdom-Weasel-inspired completion-mode local predictor baseline.

Findings:
- Wisdom-Weasel's fast path is not just a small model: it combines committed-text context, async prediction, stale request dropping, side-candidate selection routing, system-prompt state cache, and batched multi-candidate sampling.
- rime/weasel candidate handling reinforces the Squirrel/Rime patch route over a detached overlay for real IME selection.

Changes:
- Added `RAG_IME_PREDICTOR_PROMPT_MODE=chat|completion`.
- Completion mode uses `/v1/completions` with `recent_context + current_input` prefix and `n=max_candidates`.
- Prediction parsing now strips thinking/reasoning tags and accepts JSON/list candidate output.
- Updated local model benchmark and Wisdom-Weasel issue docs.

Verification:
- Predictor tests now cover chat mode, completion mode, thinking cleanup, and eval-prediction.
- Full suite has 62 tests and passed.

Next:
- Compare real Qwen/MLX/llama.cpp endpoints in chat vs completion mode, then decide whether to build a native KV-cache/batch provider.

### 2026-07-01
Topic:
- Recheck full Xcode setup for the Squirrel/Rime frontend.

Findings:
- No full `Xcode.app` is installed under `/Applications` or `/Volumes/undo 4t/Applications`.
- The external-disk `xcodes` install path has enough space but fails before download because Apple Developer credentials are unavailable in this non-interactive session.
- Strict Squirrel doctor has one failure only: `xcode-select` still points at Command Line Tools; sidecar, LaunchAgent, patch, generated config, and Swift checks pass.

Next steps:
- Authenticate Apple Developer for `xcodes` or provide `FASTLANE_SESSION`, then rerun the setup script and strict doctor.

### 2026-07-01
Topic:
- Add server-side cache for repeated Rime sidecar suggestions.

Decisions:
- Cache only `/rime-suggest`, not commit/action writes.
- Exclude request sequence and session from the cache key, then rewrite them on cache hit.
- Invalidate cache on commit/action/seed and by event/action counts.

Changes:
- Added short TTL cache and cache metrics in `DebugImeService`.
- Added CLI/env TTL configuration via `RAG_IME_RIME_CACHE_TTL_MS`.
- Documented cache behavior in debug and Squirrel integration docs.

Next steps:
- Surface cache hit rate in the browser debug page and later compare against VCP-style cache targets.

### 2026-07-01
Topic:
- Convert Wisdom-Weasel/Squirrel research into stricter sidecar behavior.

Decisions:
- Keep Rime candidates first and do not mutate librime candidate internals.
- Use debounce + request fingerprints in Squirrel because request sequence alone does not cover page/candidate changes.
- Reserve side slots for RAG/memory by limiting model side candidates to one.

Changes:
- Updated Squirrel patch with `rag_ime/debounce_ms`, pending request cancellation, and stronger stale response guards.
- Updated Python Rime sidecar merge policy and tests.
- Added predictor extra body/header JSON knobs for OpenAI-compatible servers.
- Updated Wisdom-Weasel issue map and Squirrel integration docs.

Next steps:
- Run benchmark against real local Qwen/llama.cpp/MLX endpoint and compare p50/max latency under the sidecar budget.

### 2026-07-01
Topic:
- Add a repeatable local model prediction latency benchmark.

Decisions:
- Model choice should be gated by the same provider/history-context path used by the input method, not by an isolated demo call.

Changes:
- Added `predict-benchmark` CLI.
- Added predictor benchmark schema and tests.
- Added `docs/local-model-prediction-benchmark.md`.

Next steps:
- Run against a real local Qwen/llama.cpp/MLX endpoint and compare p50/max latency under the 150 ms sidecar budget.

### 2026-06-30
Topic:
- Add a local Codex-history benchmark path for RAG/memory quality.

Decisions:
- Treat Codex history as local committed-text evidence and route it through the same shared core boundary as IME commits.
- Evaluate final suggestions, not only raw retrieval rows, because input-method quality is candidate quality.

Changes:
- Added `rag_ime.codex_history`.
- Added `import-codex-history` and `eval-codex-history` CLI commands.
- Added stable `record:<hash>` duplicate skipping for repeated imports.
- Added tests and `docs/codex-history-eval.md`.

Verification:
- Codex JSONL parser skips invalid lines and extracts `content[].text` / message fields.
- Dry-run import does not write a DB.
- Imported records are retrievable and pass explicit JSONL eval cases.

Next steps:
- Run this against real Codex history after selecting a bounded path.
- Add session split evaluation and VCP/cache-hit comparisons.

### 2026-06-30
Topic:
- Make full Xcode setup explicit for patched Squirrel validation.

Decisions:
- Keep Squirrel/Rime as the production frontend and treat full Xcode as a first-class local prerequisite.
- Prefer external-disk Xcode download/install on this host because root disk free space is limited.

Changes:
- Added `scripts/setup_xcode_for_squirrel.sh`.
- Added `docs/xcode-squirrel-setup.md`.
- Enhanced the Squirrel doctor to show `xcode-select` and `DEVELOPER_DIR` state.

Verification:
- Local machine currently has only Command Line Tools selected.
- `xcodes` and `mas` are installed, but actual Xcode install is blocked by Apple ID/admin-password UI.

Next steps:
- Install full Xcode through Apple Developer `xcodes` or App Store UI, then run `RAG_IME_DOCTOR_REQUIRE_XCODE=1 scripts/doctor_squirrel_integration.sh`.

### 2026-06-30
Topic:
- Continue RAG-IME toward a usable Squirrel/Rime macOS input method.

Decisions:
- Keep Rime/Squirrel as the production frontend and preserve librime ownership of raw pinyin parsing.
- Treat accepted side candidates as memory feedback, not only text insertion.

Changes:
- Added side-candidate `sourceEventId` to the Rime sidecar JSON contract.
- Updated the Squirrel patch pack so accepted RAG side candidates record both a commit event and an `accepted` action.
- Fixed side-candidate cap so model and RAG candidates share the same `max_side_candidates` budget.

Verification:
- 33 Python unit tests passed.
- Fixture acceptance passed.
- macOS prototype app built successfully.
- Rime sidecar preview shows Rime candidates first and RAG side candidates with `sourceEventId`.
- Squirrel patch applies cleanly to upstream commit `2158538`.

Next steps:
- Run full Squirrel Xcode build/install/signing on a machine with Xcode.
- Convert the Python CLI sidecar into a long-lived daemon to avoid spawning a process per key update.

### 2026-06-30
Topic:
- Reduce Squirrel sidecar latency by avoiding per-request Python process startup.

Decisions:
- Reuse the existing local HTTP facade instead of creating a separate protocol.
- Squirrel should prefer `rag_ime/sidecar_url` and keep CLI fallback for fail-closed behavior.

Changes:
- Added `sidecar-server` CLI command on port `8766` by default.
- Added `/health`, `/rime-suggest`, `/commit`, `/action` root aliases in addition to `/api/...`.
- Updated the Squirrel patch pack to POST JSON to the long-running sidecar when configured.

Verification:
- 35 Python unit tests passed.
- CLI sidecar server smoke returned a valid `rag-ime.rime-sidecar.v1` response.
- Squirrel sidecar Swift files typechecked with a temporary config stub.
- Patch still applies cleanly to Squirrel `2158538`.

Next steps:
- Build/install patched Squirrel with Xcode and test real typing.

### 2026-06-30
Topic:
- Make the HTTP sidecar usable as a persistent local service.

Changes:
- Added `scripts/install_sidecar_launch_agent.sh`.
- Added `scripts/uninstall_sidecar_launch_agent.sh`.
- Added dry-run plist generation and a unit test for the LaunchAgent script.
- Documented sidecar launchd setup in README, Squirrel patch notes, and macOS frontend notes.

Verification:
- 36 Python unit tests passed.
- LaunchAgent dry-run generated a valid plist.
- Fixture acceptance passed.
- macOS prototype app still builds.

Next steps:
- Build/install patched Squirrel with Xcode and test real typing against `http://127.0.0.1:8766/api`.

### 2026-06-30
Topic:
- Make patched Squirrel checkout preparation repeatable.

Changes:
- Added `scripts/prepare_squirrel_workspace.sh`.
- Added a dry-run unit test for the prepare script.
- Updated README, Squirrel patch notes, and macOS frontend notes to use the prepare script.

Verification:
- 37 Python unit tests passed.
- Prepare script dry-run passed.
- Real prepare was tested against local Squirrel source and generated `rag-ime.squirrel.custom.yaml`.
- Fixture acceptance and macOS prototype build passed.

Next steps:
- Use `/tmp/rag-ime-squirrel` on an Xcode machine to build/install patched Squirrel and test real typing.

### 2026-06-30
Topic:
- Add a preflight check for patched Squirrel integration.

Changes:
- Added `scripts/doctor_squirrel_integration.sh`.
- Added a unit test for default WARN-mode doctor behavior.
- Documented the doctor in README, macOS frontend notes, and Squirrel patch notes.

Verification:
- Doctor WARN-mode works without a running sidecar.
- Doctor strict sidecar mode passed against a temporary `sidecar-server`.
- 38 Python unit tests passed.
- Fixture acceptance and macOS prototype build passed.

Next steps:
- Run doctor on the Xcode machine before building/installing patched Squirrel.

### 2026-07-01
Topic:
- Complete the Xcode setup path for Squirrel validation.

Findings:
- The Mac is still using Command Line Tools at `/Library/Developer/CommandLineTools`.
- No full Xcode exists under `/Applications` or `/Volumes/undo 4t/Applications`.
- `xcodes` and `mas` are installed, and `xcodes` lists both `27.0 Beta 2` and `26.6`.
- A real `RAG_IME_INSTALL_XCODE=xcodes` attempt failed because this non-interactive Codex session has no Apple Developer credentials: `Apple ID: Missing username or a password`.

Changes:
- `scripts/setup_xcode_for_squirrel.sh` now reports disk space, installed Xcodes, `FASTLANE_SESSION`, and clearer authentication recovery commands.
- The setup doc now records the current host state and the external-disk install route.

Next steps:
- Install Xcode from an Apple-authenticated terminal or provide `FASTLANE_SESSION`, then rerun the setup script and Squirrel doctor.

### 2026-07-01
Topic:
- Add backend trigger gating for Squirrel `/rime-suggest`.

Changes:
- `/rime-suggest` now returns `triggerDecision`.
- Rime candidates are still returned on every response, but model/RAG side candidates are skipped for raw pinyin fallback, unstable composing updates, full visible Rime pages, or too-short candidate signals.
- Debug page JSON now shows the Rime sidecar decision and cache metadata.
- Swift prototype models and the Squirrel patch pack preserve the new trigger/merge fields.

Verification:
- 51 Python tests passed.
- Acceptance passed.
- macOS prototype build passed.
- Swift Rime sidecar preview prints `triggerDecision.shouldRefresh`.

### 2026-07-01
Topic:
- Unify side-candidate selection feedback.

Changes:
- Added `POST /rime-select` and CLI `rime-select-json`.
- The endpoint records accepted side-candidate text and, for RAG candidates, records the accepted memory action in the same local call.
- Squirrel patch now prefers `/rime-select` / `rime-select-json`; the old commit/action split remains only as fallback.
- Real `scripts/prepare_squirrel_workspace.sh` was run and now passes after fixing patch hunk lengths that previously truncated `RagImeSidecarModels.swift`.

Verification:
- 54 Python tests passed.
- Acceptance passed.
- macOS prototype build passed.
- Patched Squirrel checkout prepared and sidecar Swift files typechecked.

### 2026-07-01
Topic:
- Improve Codex-history RAG evaluation quality metrics.

Changes:
- `eval-codex-history` now evaluates expected terms at candidate level instead of merging all top-K suggestions into one haystack.
- Added `firstMatchRank`, `reciprocalRank`, `top1Passed`, `termFirstRanks`, and forbidden-term noise checks.
- Report-level metrics now include `top1Accuracy`, `meanReciprocalRank`, `meanFirstMatchRank`, `noiseRate`, and `noiseCount`.

Verification:
- 56 Python tests passed.
- Acceptance passed.
- macOS prototype build passed.
- Temporary CLI eval smoke printed the new ranking/noise metrics.

### 2026-07-01
Topic:
- Add observable local-core suggestion cache.

Changes:
- `LocalSqliteCoreClient` now has a process-local LRU suggestion cache keyed by normalized input/context/project/top_k.
- Commit, action, and reset invalidate the cache.
- `suggestion_cache_stats()` exposes size, hits, misses, hit rate, evictions, and invalidations.
- CLI accepts `--suggestion-cache-size` / `RAG_IME_SUGGESTION_CACHE_SIZE`.
- Debug health and `eval-codex-history` now include cache stats.

Verification:
- 58 Python tests passed.
- Acceptance passed.
- macOS prototype build passed.
- Repeated-case eval smoke showed one cache hit and one miss.

### 2026-07-01
Topic:
- Add latency to Codex-history eval.

Changes:
- `eval-codex-history` now records per-case `elapsedMs` around `adapter.suggest(...)`.
- Reports include `latency.caseCount`, `totalMs`, `avgMs`, `p50Ms`, `p95Ms`, and `maxMs`.
- Docs describe latency as adapter-level time covering cache lookup, retrieval, ranking, and suggestion compilation.

Verification:
- 58 Python tests passed.
- Acceptance passed.
- macOS prototype build passed.
- Repeated-case eval smoke printed `elapsedMs`, `latency`, and `cacheStats`.

### 2026-07-01
Topic:
- Add repeat-mode eval and make the sidecar LaunchAgent actually usable.

Changes:
- `eval-codex-history` now supports `--repeat N`, suffixing repeated case ids as `#r1`, `#r2`, etc. and reporting `repeat.requested/baseCaseCount/effectiveCaseCount`.
- LaunchAgent installation now copies the runtime into `~/Library/Application Support/RagIme/app`, defaults the sidecar DB to `~/Library/Application Support/RagIme/rag-ime.sqlite`, removes plist `PYTHONPATH`, and health-checks after bootstrap.
- Added `scripts/sidecar_launch.py` for launchd-safe startup.

Verification:
- 59 Python tests passed.
- macOS prototype build passed.
- Repeat eval smoke showed `misses=1`, `hits=2`, `hitRate=0.67` for 3 repeats.
- `scripts/install_sidecar_launch_agent.sh` installed and health-checked OK.
- `scripts/doctor_squirrel_integration.sh` now reports LaunchAgent and HTTP sidecar OK; only full Xcode remains a warning.

Open:
- `RAG_IME_DOCTOR_REQUIRE_XCODE=1 scripts/doctor_squirrel_integration.sh` still fails because full `Xcode.app` is not installed; Apple Developer/App Store authentication is required outside this non-interactive Codex session.

### 2026-07-01
Topic:
- Add model prediction quality evaluation for local Qwen/MLX/llama.cpp selection.

Changes:
- Added `eval-prediction` CLI.
- It uses the same JSONL case format and candidate-level metrics as `eval-codex-history`, but evaluates configured local model predictions.
- Reports include `repeat`, `latency`, and a `prediction` block with provider status, max candidates, latency budget, over-budget count, and total candidates.
- README and `docs/local-model-prediction-benchmark.md` now describe the quality gate, not only latency benchmarking.

Verification:
- Predictor tests passed.
- Full suite now has 60 tests and passed.
- Fixture `eval-prediction` smoke showed `providerConfigured=false` when no local model is configured.
- Acceptance, macOS prototype build, and Squirrel doctor still pass; doctor only warns about missing full Xcode.

Next:
- Run `eval-prediction` and `eval-codex-history` on the same cases against a real local model endpoint, then compare model/RAG quality and latency.

### 2026-07-01
Topic:
- Add optional vector side-index for local RAG memory.

Changes:
- Added local-core embedding provider boundary with disabled default, deterministic `local-hash` baseline, and OpenAI-compatible embedding endpoint support.
- Added `memory_vectors`, write-time vector upsert, vector backfill, vector/FTS merge, vector score reason, and `vectorStats` in eval reports.
- CLI now supports `--embedding-provider`, `--embedding-vector-candidates`, `--embedding-vector-weight`, and `rebuild-vector-index`.
- README and Codex-history eval docs explain local-hash vs real semantic embedding and the Mac/WSL endpoint path.

Verification:
- Full suite now has 72 tests and passed.
- Acceptance passed.
- Imported 2000 Codex-history records into a temp DB, backfilled 2000 local-hash vectors, and ran repeated eval.
- Default FTS/rerank and local-hash hybrid both passed 6/6 repeated cases with top1Accuracy=1.0 and MRR=1.0.
- Default p95 was 21ms; local-hash hybrid p95 was 80ms, so vector recall remains opt-in.

Next:
- Test a real local/WSL embedding provider and use the subagent VCP/Wisdom-Weasel research to choose the next ranking/cache optimization.
