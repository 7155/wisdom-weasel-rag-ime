# Chat Summary

### 2026-07-02
Topic:
- Align native macOS candidate appearance with Wisdom-Weasel's short-lived LLM candidate flow.

Findings:
- Wisdom-Weasel's natural demo comes from candidate-flow integration: commit text enters LLM prediction mode, async prediction is request-seq guarded, LLM candidates are injected into Weasel candidate info, and exiting prediction clears the candidates.
- A persistent detached panel feels like clipboard/history, which is not the target interaction.

Changes:
- `RagImeMac` now consumes `/rime-suggest` `displayCandidates` and `predictionSession` instead of keeping the old `/suggest-json` panel open.
- Native post-commit prediction expires after 1.15s and clears when the user starts new composition, so stale AI candidates stop intercepting number keys.
- Side-candidate selection now has a Swift `/rime-select` bridge; the panel renders inline/model candidates horizontally and RAG/memory rows vertically from one display payload.
- `--preview-panel` now shows the same sidecar payload as the real adapter.

Verification:
- Swift frontend build passed.
- Prediction/session sidecar tests passed: 79 focused tests.
- Native JSON preview decoded `predictionSession` and returned visible prediction candidates.

Next:
- Keep the real production typing path on Squirrel/Rime, because the AppKit harness still does not own true Wanxiang/Rime composition.

### 2026-07-02
Topic:
- Make Prediction-first RAG IME demo usable after user reported clipboard-like candidates and stale panels.

Changes:
- Codex history import now defaults to true user input only; assistant/event/tool/system records are skipped.
- SQLite retrieval and candidate compiler now filter old runtime pollution and low-value instruction/complaint fragments.
- Candidate source labeling now distinguishes `model`, `rag`, and `memory`.
- Empty-input post-commit panel holdover is capped to 0.85-0.9s and clears when stale or when Rime fallback exists.
- Added `tests/test_demo_quality.py` and documented feedback issues in `docs/agent/feedback-issues-20260702.md`.

Verification:
- Demo quality tests passed: 11 tests.
- Live sidecar returned `rag`, `memory`, and `model` candidates with `commit_side_candidate`.
- Patched Squirrel built and installed to `/Users/undo/Library/Input Methods/Squirrel.app`.
- Doctor passed with 0 failures and 2 warnings: stale system Squirrel duplicate, and doctor model diagnostic mismatch.

Next:
- Replace or remove stale `/Library/Input Methods/Squirrel.app` with admin credentials, then manually test in TextEdit/Edge/Codex App that empty panels clear and number keys commit side candidates.

### 2026-07-02
Topic:
- Tighten foreground trace side-first visible ordering.

Changes:
- `check_squirrel_frontend_trace.py` now validates candidate summaries when present.
- The foreground mixed-panel gate requires model inline candidates before RAG block rows, with Rime fallback only after side candidates.
- Added a regression case for Rime appearing at visible label 2.

Verification:
- Focused frontend trace tests passed: 8 tests.
- Full test suite passed: 191 tests.

Next:
- Replace the stale system Squirrel, then rerun strict doctor and foreground manual trace.

### 2026-07-02
Topic:
- Tighten foreground number-key side-candidate trace verification.

Changes:
- `check_squirrel_frontend_trace.py --require-side-commit` now requires a matching `number_key_route` plus valid model/RAG `side_candidate_commit`.
- Strict doctor frontend trace summary now reports the matched number key.
- Added tests for missing route and Rime-route false positives.

Verification:
- Focused frontend/doctor trace tests passed: 18 tests.
- Full test suite passed: 190 tests.

Next:
- After replacing the stale system Squirrel, rerun strict doctor with frontend trace and manually press 6/7/8 in a real editor.

### 2026-07-02
Topic:
- Add a read-only default Rime contract gate for real Squirrel tryout.

Changes:
- `squirrel-tryout-gate` now reports `installedRimeDefaults`.
- The gate checks both `default.custom.yaml` and compiled `build/default.yaml` for `luna_pinyin_simp` and page size 8.
- Added a regression case where `luna_pinyin` and page size 5 fail before the quality gate.

Verification:
- Focused tryout-gate tests passed.
- Full test suite passed: 188 tests.
- Local Rime files already contain the expected simplified schema and page size.

Next:
- The remaining real doctor blocker is still stale `/Library/Input Methods/Squirrel.app`; run `scripts/replace_system_squirrel_app.sh` with administrator password, then rerun strict doctor and foreground trace.

### 2026-07-02
Topic:
- Add optional foreground auto-typing and record macOS permission blocker.

Changes:
- Added `--auto-type`, `--auto-query`, and `--auto-key` to `scripts/verify_squirrel_foreground_trace.sh`.
- The wrapper now explains the macOS Accessibility permission path when simulated keystrokes are blocked.
- README and debug-surface docs now state that auto-typing failure is a UI automation permission issue, not proof that Squirrel/RAG-IME/MLX failed.

Verification:
- Manual automation attempt failed with `osascript` keystroke permission error.
- Frontend trace tests passed.
- Full test suite passed: 186 tests.

Next:
- User still needs to perform the foreground typing step manually or grant Accessibility permission to Codex/terminal before `--auto-type` can complete the trace gate.

### 2026-07-02
Topic:
- Add one-command foreground AppKit trace validation.

Changes:
- Added `scripts/verify_squirrel_foreground_trace.sh`.
- The wrapper selects Squirrel, clears frontend trace, opens a TextEdit test file, and waits for mixed-panel plus number-key side-commit evidence.
- Updated README, Xcode setup, and debug-surface docs to make this the foreground validation path.

Verification:
- Wrapper dry-run and shell syntax passed.
- Frontend trace tests passed.
- Full test suite passed: 186 tests.

Next:
- User can run `scripts/verify_squirrel_foreground_trace.sh`, type `er qi`, and press `6`, `7`, or `8` to produce the remaining real AppKit evidence.

### 2026-07-02
Topic:
- Reinstall real Squirrel frontend and lock mixed candidate layout.

Changes:
- Rebuilt `/tmp/rag-ime-squirrel` from the current patch and installed the new `~/Library/Input Methods/Squirrel.app`.
- Confirmed the patched workdir now contains `ragImePanelLinear`, `ragImePanelVertical`, `traceRagImePanelTextLayout`, and mixed separators.
- Added strict doctor coverage for MLX `next-token-logits` candidates with `candidate_scores`, no JSON fallback, and prepared prompt cache.
- Documented the compact layout: labels 1-5 horizontal MLX/LLM short candidates, labels 6-8 vertical RAG/memory sentence candidates.

Verification:
- `scripts/build_patched_squirrel.sh install` succeeded with Xcode 26.6.
- Strict doctor passed with 5 model inline candidates, 3 RAG block candidates, MLX `next-token-logits`, and `failures=0 warnings=0`.
- Focused doctor integration tests passed.

Next:
- Do one manual foreground typing pass in a normal editor, accept a side candidate by number, then run the frontend trace gate to prove AppKit rendered the horizontal/vertical split.

### 2026-07-01
Topic:
- Full Xcode/Squirrel build and strict local-model TTFC validation.

Changes:
- Prepared Squirrel binary dependencies without proxy variables and built patched `Squirrel.app` successfully with full Xcode CLI.
- Added stricter stream-first candidate handling: warmup runs are separate, TTFC stops on the first usable candidate, half tokens are ignored, and current-input echoes are filtered.
- Changed Ollama stream-first prompt to continuation-style single-candidate output.
- Updated TTFC example cases to be composing prefixes, not complete topic labels.
- Documented that `qwen3.5:0.8b-mlx` is a fast smoke path but not yet a production-quality candidate source.

Verification:
- Patched Squirrel Release build succeeded at `/tmp/rag-ime-squirrel-derived-data/Build/Products/Release/Squirrel.app`.
- Focused predictor tests for stream-first, warmup, and repeated-input filtering passed.
- Real local Ollama benchmark showed `qwen3.5:0.8b-mlx` valid samples at `p50=44 ms`, `p95=62 ms`, but 14/20 samples had no valid candidate after strict filtering.

Next:
- Install/select Xcode 27 beta 2 for GUI compatibility on macOS 27, then do install + system input-method continuous-use validation.
- Test larger or completion-oriented local models before enabling model side candidates by default.

### 2026-07-01
Topic:
- Filter remaining Codex runtime context from imported RAG-IME memories.

Changes:
- Extended Codex-history import filtering for `skills_instructions`, `apps_instructions`, `plugins_instructions`, and `collaboration_mode` blocks.
- Added regression fixtures proving those user-role runtime-injection blocks are skipped.
- Updated the Codex-history evaluation doc to mention app/skill/collaboration context filtering.

Verification:
- Focused Codex-history tests passed.
- 500-record real Codex import/eval reported `10/34` pass rate and `noiseRate=0.0`.

Next:
- Keep the 34-case gold set intact; improve recall with hybrid/vector search and larger-window evaluation rather than shrinking the benchmark.
- Full Squirrel build/install/system input-method continuous use still waits for full Xcode.

### 2026-07-01
Topic:
- Refresh Mac local inference fast-path research.

Decisions:
- Keep Ollama `qwen3.5:0.8b-mlx` as the current fastest measured Mac smoke/debug route.
- Product metric is `firstCandidateMs` / TTFC, not raw first chunk or full JSON completion.
- Do not wait for an `Instant`-named Qwen3.5 model; use small + non-thinking + streaming + resident runner.
- Final product kernel still needs direct MLX-LM or native `llama.cpp`/Metal with explicit prompt/KV cache, sequence fork, batch candidates, and stale cancellation.

Changes:
- Updated `docs/mac-local-inference-fast-path.md` with source-refresh decisions, Qwen3.5 small-model rules, verified TTFC numbers, and extra upstream sources.
- Updated `docs/agent/notes.md` with the research findings and next implementation direction.

Next:
- Run direct MLX-LM cached/uncached TTFC when dependencies are available.
- If MLX-LM does not beat Ollama MLX consistently, spike native `llama.cpp`/Metal `predict_many_short_candidates()`.

### 2026-07-01
Topic:
- Promote cache probe to a CLI gate.

Changes:
- Added `python3 -m rag_ime.cli cache-probe` using the same backend as `POST /api/cache-probe`.
- CLI output includes suggestion-cache and Rime semantic-cache warm-hit deltas and pass flags.
- Added an end-to-end CLI test and documented the command in README/debug docs.

Verification:
- Focused debug tests passed.
- Manual temporary-DB probe showed `suggestionCache.hitsDelta=2` and `rimeSuggestCache.hitsDelta=2` for `repeat=3`.

### 2026-07-01
Topic:
- Add debug cache-hit probe for IME refresh behavior.

Changes:
- Added `POST /api/cache-probe` to repeat the same semantic input through `/api/suggest` and `/api/rime-suggest`.
- The report includes local/shared core suggestion-cache deltas, Rime semantic-cache deltas, pass flags, and compact samples.
- Added a small Cache card to the browser debug page; the real IME panel remains unchanged.
- Updated debug-surface docs and debug-server tests.

Verification:
- `python3 -m unittest tests.test_debug_server`
- `python3 -m py_compile rag_ime/debug_server.py`
- `node --check debug/app.js`
- `git diff --check`

### 2026-07-01
Topic:
- Add a real patched Squirrel build gate.

Changes:
- Added `scripts/build_patched_squirrel.sh` with `list`/`build` actions, dry-run output, patched-file checks, and `CODE_SIGNING_ALLOWED=NO` default build.
- Added offline tests with fake `xcodebuild` for dry-run, project inspection, build invocation, and missing-workdir failure.
- Updated README, Squirrel patch pack, Xcode setup, and macOS adapter docs with the new validation path.

Findings:
- `/tmp/rag-ime-squirrel` is prepared and patched.
- Current host still points `xcode-select` at `/Library/Developer/CommandLineTools`, so the real Squirrel build remains blocked until full Xcode is installed/selected.

Next:
- After full Xcode is available, run `scripts/build_patched_squirrel.sh list` and then `scripts/build_patched_squirrel.sh`.

### 2026-07-01
Topic:
- Mac 本地推理最快路线专项调研。

Decisions:
- 短期用 Ollama `qwen3.5:0.8b-mlx` 作为已测最快 debug/smoke 路线；最终产品路线仍要走 resident MLX-LM 实测和 native llama.cpp/Metal KV/seq-copy provider。
- 输入法指标统一为 `firstCandidateMs` / TTFC；`firstChunkMs` 只用于诊断。
- MiniVLLM/vLLM 借鉴缓存和调度思想，不作为 Mac 运行时依赖。

Changes:
- 更新 `docs/mac-local-inference-fast-path.md`，明确 smoke 路线与最终内核边界，并补充 MLX prompt cache 隔离 caveat。
- 更新 `docs/model-ttft-kv-cache-plan.md`，修正过时的 Ollama-only TTFT 描述。

Next:
- 在 Ollama server 可用时重新跑 `bench-ime-ttfc` / `predictor-ttft`。
- 实测 resident MLX-LM cached/uncached TTFC；随后决定是否实现 native llama.cpp/Metal provider。

### 2026-07-01
Topic:
- Research the fastest Mac local inference path for RAG-IME TTFT.

Findings:
- The current Ollama `qwen3.5:0.8b` path proves local integration but not the <200 ms first-candidate target.
- Short-term Mac testing should try Ollama `qwen3.5:0.8b-mlx`, then direct MLX-LM with `stream_generate` and prompt cache.
- The final low-latency provider should likely be native llama.cpp/Metal or resident MLX, because it must own stable prompt KV cache and multi-candidate sampling.
- Core ML stateful KV and MLC LLM are useful later research paths; MiniVLLM/vLLM contribute scheduler/prefix-cache concepts but are not direct Mac IME runtimes.

Changes:
- Added `docs/model-ttft-kv-cache-plan.md` backend decision table and recommendation tiers.
- Updated local model benchmark docs, README, Wisdom-Weasel issue map, and interview difficulty notes.

Next:
- Run `predictor-ttft` against `qwen3.5:0.8b-mlx` without proxy download.
- If it misses the 200 ms p50 first-chunk target, prototype resident MLX-LM or native llama.cpp/Metal provider.

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

### 2026-07-01
Topic:
- Expose vector index state to debug/sidecar cache.

Changes:
- Debug/sidecar health now includes `vectorStats`.
- `/rime-suggest` short TTL cache key now includes vector index/provider stats, so vector backfill/provider changes do not reuse stale side-candidate responses.
- Debug JSON panel shows `vectorStats`.

Verification:
- Debug-server tests passed.
- Full suite now has 73 tests and passed.
- Acceptance passed.

Research:
- Subagent confirmed VCP's hot memory path is vector-first with strong caching/dedup/rerank failover, while Wisdom-Weasel's speed comes from Rime-first integration, stale request guards, native llama.cpp KV cache, and batch candidate sampling.

Next:
- Build a larger 30-50 case gold set, then add real embedding/provider cache and in-flight dedupe.

### 2026-07-01
Topic:
- Expand Codex-history retrieval gold set.

Changes:
- `docs/eval/codex-history-cases.example.jsonl` now has 34 cases instead of 3.
- Cases cover Squirrel/Rime side candidates, RAG/model comparison, vector backfill, embedding config, local-first privacy, Qwen prediction eval, Wisdom-Weasel fast prediction, cache/doctor/debug workflows, and known weak spots.
- `docs/codex-history-eval.md` records the current baseline and warns not to shrink the file for a prettier pass rate.

Verification:
- Imported 5000 newest Codex-history records into a temp DB.
- Default FTS5 + local rerank: 24/34 pass, top1Accuracy=0.50, MRR=0.566, p95 about 29ms.
- local-hash hybrid: 23/34 pass, top1Accuracy=0.441, MRR=0.528, p95 about 160ms.
- Full test suite passed with 73 tests.

Next:
- Use the failing 10 cases as the next retrieval/rerank target; do not enable local-hash by default.

### 2026-07-01
Topic:
- Improve 34-case Codex-history retrieval quality.

Changes:
- Added product/runtime query expansion for side-candidate numbering, raw-pinyin fallback gating, local-first privacy, model side budget, history-context prediction, Wisdom-Weasel fast prediction, OpenAI-compatible predictor config, stale response guards, trigger decision, sidecar cache metrics, and runtime-noise filtering.
- Added a light rerank penalty for raw Codex tool transcripts. Tool traces remain recallable for exact code identifiers, but natural-language summaries win when both are relevant.
- Filtered the Codex approval-review transcript wrapper phrase during import.
- Updated the runtime-noise eval case to match real imported evidence terms.
- Added the read-only subagent optimization review under `docs/agent/subagents/`.

Verification:
- Fresh 5000-record Codex-history import passed 34/34 eval cases.
- top1Accuracy improved from 0.500 to 0.824; meanReciprocalRank improved from 0.566 to 0.880; p95 latency was about 30ms.
- Full suite now has 75 tests and passed.
- Acceptance and `git diff --check` passed.

Decision:
- Do not delete all tool transcript memories yet. A trial hard filter dropped recall to 28/34 because several implementation identifiers currently exist only in tool traces. Keep them as downranked fallback until project docs/summaries cover those identifiers.

### 2026-07-01
Topic:
- Make RAG candidates fit the real IME panel.

Changes:
- `SuggestionCompiler` now compresses candidate-bar `surface_text` separately from full `insert_text`.
- It prefers useful bullets and short semantic lines, strips Codex transcript/tool/debug/path wrappers from display text, and keeps full source material for commit/expand.
- Rime sidecar tests now prove RAG `displayCandidates[].text` can be compact while `insertText` keeps the full source paragraph.
- UX docs now state the `surface_text` vs. `insert_text` contract explicitly.
- Ptolemy's exact embedding cache patch was integrated for the OpenAI-compatible embedding provider.
- Embedding cache keys use provider fingerprint plus normalized text; fingerprint now includes endpoint hash, model, dimensions, and `extra_body` hash.
- `RAG_IME_EMBEDDING_CACHE_SIZE` controls the bounded cache and empty vectors are not cached.

Verification:
- Adapter and Rime sidecar tests passed.
- Embedding cache tests passed.
- Full suite now has 82 tests and passed.
- Acceptance passed.
- 34-case Codex-history eval stayed at 34/34 with top1Accuracy=0.824 and MRR=0.880.

Next:
- Use the sidecar display/insert split when implementing the native candidate panel.
- Test a real WSL/local embedding endpoint with cache enabled and compare repeated-case latency.

### 2026-07-01
Topic:
- Make local model lane status explicit.

Changes:
- Added `prediction_provider_status()` and `rag-ime predictor-status`.
- `/api/health` now includes `predictor` status for the debug page.
- `predict-benchmark` now reports configured provider names even when the endpoint returns no candidates.
- README, debug docs, and local-model benchmark docs clarify that `predictor-status` checks config only; `predict-benchmark` / `eval-prediction` prove liveness and quality.

Verification:
- Full unit suite passed: 85 tests.
- Fixture acceptance passed.
- `git diff --check` passed.
- Default status on this machine: `configured=false`, `providerName=NullPredictionProvider`.
- With Qwen instant env set, status reports `configured=true`, `model=Qwen3-0.6B`, `profile=instant`, `timeoutMs=350`, `maxTokens=8`.
- Actual benchmark against `127.0.0.1:8000` returned no candidates, so no real model is currently running there.
- Probed common local endpoints `8000`, `8080`, `1234`, and `11434`; all refused connection.
- Real 5000-record Codex-history eval still passed 34/34 with top1Accuracy=0.824, meanReciprocalRank=0.880, p95=34ms.
- Model choice note: Ollama `qwen3.5` has small local tags (`0.8b`, `2b`, `4b`, plus `-mlx` variants), so include them in the first IME latency/quality matrix.

Next:
- Start a real local or WSL OpenAI-compatible model endpoint, then run `predictor-status`, `predict-benchmark`, `eval-prediction`, and `eval-comparison`.

### 2026-07-01
Topic:
- Add local model endpoint doctor.

Changes:
- Added `doctor_prediction_provider()` and `rag-ime predictor-doctor`.
- Doctor checks config, `/v1/models`, configured model id presence, one short prediction, latency budget, and local runner commands in `PATH`.
- Docs now separate config check, endpoint doctor, benchmark, and quality eval.

Verification:
- Predictor tests pass.
- Full unit suite passed: 87 tests.
- Fixture acceptance passed.
- Real 5000-record Codex-history eval still passed 34/34 with top1Accuracy=0.824, meanReciprocalRank=0.880, p95=35ms.
- `git diff --check` passed.
- This Mac has no visible `ollama`, `llama-server`, `lmstudio`, or `mlx_lm.server`.
- Default doctor reports not configured and not ready, which matches the current machine state.
- With Qwen instant env pointed at `127.0.0.1:8000`, doctor reports env configured but `/v1/models` connection refused.

Next:
- Start a WSL or Mac OpenAI-compatible Qwen endpoint and run `predictor-doctor` before `predict-benchmark` / `eval-prediction`.

### 2026-07-01
Topic:
- Protect IME refreshes from repeated model endpoint failures.

Changes:
- Added `CooldownPredictionProvider` for configured OpenAI-compatible predictors.
- Default failure cooldown is 5000 ms after transport errors or slow empty predictions.
- Predictor status/debug health now expose cooldown state.
- Rime sidecar test proves failed model predictions are skipped on the next refresh while RAG candidates still appear.

Verification:
- Full suite passed: 91 tests.
- Fixture acceptance passed.
- Real 5000-record Codex-history eval still passed 34/34 with top1Accuracy=0.824, meanReciprocalRank=0.880, p95=32ms.
- Qwen instant doctor against `127.0.0.1:8000` reports connection refused and `cooldown.active=true`.
- `git diff --check` passed.

Next:
- When a real WSL/Mac endpoint is available, compare no-cooldown endpoint debugging with default cooldown sidecar behavior.

### 2026-07-01
Topic:
- Add VCP-style pending request dedupe for `/rime-suggest`.

Changes:
- Added in-flight dedupe for equivalent Rime sidecar cache keys.
- Health now exposes `rimeSuggestCache.inFlight`, `inFlightHits`, and `inFlightErrors`.
- Cache payloads expose `inFlightHit` separately from TTL `hit`.
- Concurrent debug-server test proves overlapping equivalent requests call the predictor once.

Verification:
- Full suite passed: 92 tests.
- Fixture acceptance passed.
- Real 5000-record Codex-history eval still passed 34/34 with top1Accuracy=0.824, meanReciprocalRank=0.880, p95=32ms.
- `git diff --check` passed.

Next:
- Continue toward real Squirrel/Xcode install and WSL/Mac model endpoint testing.

### 2026-07-01
Topic:
- Add real Rime sidecar display-path evaluation.

Changes:
- Added `eval-rime-sidecar` CLI.
- It uses the same JSONL cases as `eval-codex-history`, calls `DebugImeService.rime_suggest(...)`, and scores only model/RAG side candidates from merged `displayCandidates`.
- Sidecar eval report includes trigger refresh counts, side/model/RAG candidate counts, `/rime-suggest` cache stats, suggestion cache stats, predictor status, vector stats, and latency.
- Fixed a sidecar context-boundary bug: model prediction still receives `historyContext`, but RAG retrieval now receives only explicit `committedContext`.

Verification:
- Sidecar eval test covers repeat/cache behavior.
- Rime sidecar context-boundary test proves historical input context does not pollute RAG retrieval.
- Direct 5000-record RAG eval still passes 34/34 with top1Accuracy=0.794, meanReciprocalRank=0.865, p95=32ms.
- Real Rime sidecar eval improved from 13/34, p95=73ms before the split to 31/34, top1Accuracy=0.794, meanReciprocalRank=0.843, with p95 observed between 34ms and 49ms after the split.
- Repeat sidecar eval with `--rime-cache-ttl-ms 5000` reports `rimeSuggestCache` hits/misses = 34/34.

Next:
- Improve remaining sidecar-only misses with candidate compression/ranking for three visible side slots.
- Test a real local/WSL Qwen endpoint when available.

### 2026-07-01
- Added technical identifier surface summaries and canonical project-key mapping for visible IME candidates.
- Filtered patch/file-hit surfaces and downranked patch/tool/subagent traces while keeping useful code identifiers recallable.
- Expanded local rerank mappings for selection routing, RAG/model comparison, WSL embedding env vars, suggestion-cache metrics, and Codex-history ranking metrics.
- Rime sidecar display-path eval on the same temp DB now passes 34/34 with top1Accuracy=0.765, meanReciprocalRank=0.868, p95=46ms, and noiseRate=0.
- Updated README and model benchmark docs for Ollama `qwen3.5:0.8b`, `2b`, `4b`, and MLX variants; this Mac still has no visible `ollama`, so real inference is pending.

### 2026-07-01
- Added `eval-model-matrix` for concrete small-model comparison across multiple OpenAI-compatible model ids.
- Default model matrix is `qwen3.5:0.8b,qwen3.5:2b,qwen3.5:4b` against Ollama `/v1`.
- The command reports per-model pass rate, ranking metrics, p95 latency, candidate availability, local runner availability, and a winner summary; full per-case output is opt-in via `--include-cases`.
- Local smoke confirms the command works but no real model is downloaded or running here: `ollama`, `llama-server`, `lmstudio`, and `mlx_lm.server` are all missing, and qwen3.5 matrix candidates are empty.

### 2026-07-01
- Installed Ollama 0.30.11 and downloaded `qwen3.5:0.8b` to the external Ollama model directory (`/Volumes/undo 4t/ollama-models`); `ollama list` shows 1.0 GB.
- Found a proxy-risk issue: this Codex shell exports `HTTP_PROXY/HTTPS_PROXY/ALL_PROXY=127.0.0.1:7897`, so future model downloads should explicitly unset proxy vars unless intentionally using the proxy.
- Added native `RAG_IME_PREDICTOR_PROVIDER=ollama` because Ollama's OpenAI-compatible `/v1` Qwen3.5 response returned empty `content` and reasoning-only output.
- Real native Ollama smoke found `qwen3.5:0.8b` through `/api/tags` and produced 3 parsed candidates. Observed warm latency varied from about 477 ms to 1157 ms, so it can pass a 1500 ms debug budget but is not stable enough for the default per-keystroke IME path.
- Caveat: candidate quality is still generic, so Qwen3.5 0.8B proves the adapter path but should not become the default IME model yet. No public Ollama `qwen3.5:*instant*` tag was found; next model tests should prefer non-thinking instruction-tuned small models such as `qwen2.5:0.5b` or `qwen2.5:1.5b`.

### 2026-07-01
Topic:
- Mac fastest local inference path for the IME model lane.

Changes:
- Downloaded and tested `qwen3.5:0.8b-mlx` through no-proxy Ollama.
- Fixed `predictor-ttft` so timeout/no-first-chunk samples count as over-budget.
- Documented the backend order: Ollama MLX smoke, direct MLX-LM resident service, native llama.cpp/Metal provider, then Core ML/MLC as later research.

Findings:
- `qwen3.5:0.8b-mlx` reached 46 ms p50 first chunk on the short warm IME prompt, which is the current best Mac TTFT evidence.
- Full candidate response and project-memory prediction quality are still not good enough: MLX passed 2/34 cases, Q8 passed 4/34.
- The implementation direction is streaming first side candidate plus resident prompt/KV cache; RAG remains the factual memory source.

Next:
- Add resident MLX-LM or native llama.cpp/Metal provider experiments after the Squirrel/Rime product loop remains stable.

### 2026-07-01
Topic:
- Add resident MLX predictor service interface.

Changes:
- Added `local-mlx` predictor provider selected by `RAG_IME_PREDICTOR_PROVIDER=mlx`.
- Added `rag-ime mlx-predictor-server` with `/predict`, `/predict-stream`, `/health`, and `/v1/models`.
- `predictor-ttft` now supports resident MLX streaming in addition to native Ollama.
- Predictor status now reports capability flags so prompt cache / sequence fork / batch candidates are not overclaimed.
- Documented Wisdom-Weasel's relevant llama.cpp mechanism: cached system prompt state, sequence-copy KV fork, and batch candidate decode.

Findings:
- Current environment has `mlx` but not `mlx_lm`; real MLX server startup is pending dependency install and a concrete MLX model id.
- The new MLX provider is a resident streaming adapter, not yet a prompt-cache or sequence-fork implementation.

Next:
- Install/verify `mlx-lm`, run `mlx-predictor-server` against a concrete small Qwen-compatible MLX model, then compare `predictor-ttft` and `eval-prediction` with the Ollama MLX baseline.

### 2026-07-01
Topic:
- Add MLX stable-prefix prompt-cache preparation and observability.

Changes:
- Added `--prompt-cache` and `--prompt-cache-max-kv-size` to the resident MLX predictor service.
- The service now prepares the stable system prompt through MLX-LM's documented `make_prompt_cache` / `generate_step(..., prompt_cache=cache)` path when enabled.
- `/health`, `/predict`, and `/predict-stream` include prompt-cache status fields.
- Added server protocol tests with a fake engine.

Boundary:
- `promptCache.prepared=true` means the stable prefix cache was built at startup.
- `promptCache.usedForGeneration=false` means streaming generation is not yet reusing that cache.
- `capabilities.promptCache` remains false until a verified cached-generation path exists.

Next:
- With `mlx-lm` installed, validate cache preparation on a real Qwen-compatible MLX model, then implement a safe cached streaming path before changing the capability flag.

### 2026-07-01
Topic:
- Add conservative MLX cached streaming path.

Changes:
- `mlx-predictor-server --prompt-cache` now saves the prepared stable prefix cache to a local safetensors file.
- Streaming generation loads a fresh cache copy per request and uses `generate_step(..., prompt_cache=cache)`.
- Prompt-cache status now reports `cacheFileReady`, `usedForGeneration`, `hits`, and `misses`.
- Added fake MLX-LM tests so the cached path is covered without installing `mlx_lm`.

Boundary:
- This avoids mutating the shared stable-prefix cache, but still needs real-model TTFT and quality evaluation.
- It is not a replacement for Wisdom-Weasel-style llama.cpp sequence-copy candidate batching.

Next:
- Install/verify `mlx-lm`, run cached vs uncached MLX TTFT on a concrete Qwen-compatible model, then decide whether `capabilities.promptCache` can be set true.

### 2026-07-01
Topic:
- Mac fastest local inference validation rerun.

Changes:
- Reconfirmed local Ollama model inventory under `/Volumes/undo 4t/ollama-models`.
- Attempted direct `mlx-lm` install in a temporary Python 3.12 venv with proxy variables unset; cancelled because `mlx_metal` downloaded at about 69 kB/s.
- Re-ran `predictor-ttft` for Ollama `qwen3.5:0.8b-mlx` and `qwen3.5:0.8b`.
- Updated local model benchmark and TTFT/KV-cache docs with the current Mac ranking.

Findings:
- `qwen3.5:0.8b-mlx` remains the fastest usable Mac smoke path: p50 first chunk 124 ms in the rerun, with warm post-load samples at 76-133 ms.
- `qwen3.5:0.8b` GGUF/Q8 was slower: p50 first chunk 296 ms, all samples over the 200 ms budget.
- Full completion still costs roughly 800-900 ms on the MLX tag, so the UI should stream the first parsed useful candidate and let RAG remain the factual memory source.

Next:
- Keep Ollama MLX as the current TTFT baseline; continue toward direct MLX-LM or native llama.cpp/Metal only when we can control prompt/KV cache and multi-candidate generation directly.

### 2026-07-01
Topic:
- Convert streaming TTFT into a usable model side-candidate path.

Changes:
- Added `RAG_IME_PREDICTOR_STREAM_FIRST=1` for native Ollama and resident MLX providers.
- With the flag enabled, `predict()` returns after the first parsed streaming candidate instead of waiting for the full JSON list.
- Added incremental parsing so JSON prefix chunks like `["` are ignored until a real candidate is available.
- `predictor-status` exposes `streamFirstCandidate`.

Findings:
- This lets `/rime-suggest` use the fast first-visible model behavior without changing the existing sidecar contract.
- The mode should be disabled for quality evals that need all model candidates.

### 2026-07-01
Topic:
- Persist model-lane configuration into the macOS sidecar LaunchAgent.

Changes:
- `scripts/install_sidecar_launch_agent.sh` now writes a whitelist of predictor, history-context, and cache tuning env vars into the generated plist.
- Dry-run LaunchAgent test now verifies `RAG_IME_PREDICTOR_PROVIDER`, `RAG_IME_PREDICTOR_MODEL`, `RAG_IME_PREDICTOR_STREAM_FIRST`, and related variables are persisted.
- README and macOS frontend docs now show the install flow for Ollama MLX + stream-first sidecar.

Findings:
- This fixes the practical gap where manual shell commands could use the fast model lane, but a login-started sidecar would not inherit the same predictor configuration.

### 2026-07-01
Topic:
- Source-backed Mac local inference fast-path decision.

Changes:
- Added `docs/mac-local-inference-fast-path.md`.
- Updated README and TTFT/KV-cache docs to point to the new decision note.

Conclusion:
- Keep Ollama `qwen3.5:0.8b-mlx` as the current fastest Mac TTFT smoke baseline.
- Next validate a direct resident MLX-LM service with streaming and prompt cache.
- Keep native llama.cpp/Metal as the final Wisdom-Weasel parity route because it can own prompt KV reuse, sequence fork, and batch candidate generation.

### 2026-07-01
Topic:
- Make predictor TTFT budget use first parsed candidate latency.

Changes:
- `predictor-ttft` summary now includes `firstCandidateMs` aggregate metrics.
- Over-budget decisions now use first parsed candidate latency instead of raw first chunk latency.
- Added a regression test for streams that emit raw JSON prefix chunks without a usable candidate.

Conclusion:
- This aligns the latency gate with the actual input-method UI: raw streamed bytes are diagnostic only; the product budget is for a candidate the user could select.

### 2026-07-01
Topic:
- Refine the Mac fastest-inference plan and harden Squirrel patch preparation.

Changes:
- Clarified that Ollama `qwen3.5:0.8b-mlx` is the fastest measured smoke baseline, while native `llama.cpp`/Metal is the strongest controllable product-kernel candidate.
- Added TTFC-oriented benchmark metrics to the Mac inference decision note and tightened the interview material around first parsed candidate latency.
- Made `prepare_squirrel_workspace.sh` fail if patched Squirrel is missing required RAG-IME sidecar files or hooks.
- Added an offline fake-Squirrel integration test for clone/apply/config/typecheck preparation.

Verification:
- `bash -n scripts/prepare_squirrel_workspace.sh`
- `python3 -m unittest tests.test_prepare_squirrel_workspace`
- `python3 -m unittest discover -s tests`

### 2026-07-01
Topic:
- Add a reusable IME TTFC matrix benchmark and run real local Qwen checks.

Changes:
- Added `bench-ime-ttfc` for streaming first parsed candidate benchmarking across model ids.
- Added `docs/eval/ime-ttfc-cases.example.jsonl` as the speed-only IME case file.
- README and Mac inference docs now show the model matrix command separately from quality evals.

Findings:
- Real Ollama models available: `qwen3.5:0.8b-mlx` and `qwen3.5:0.8b`.
- Warm `qwen3.5:0.8b-mlx` short run: p50 first candidate 102 ms, p95 122 ms, with one over-budget sample out of 12.
- Warm `qwen3.5:0.8b` short run: p50 first candidate 241 ms, p95 397 ms, all 12 samples over budget.
- The MLX tag remains the usable smoke baseline; ordinary `0.8b` should not be used for per-keystroke prediction.

### 2026-07-01
Topic:
- Add debug TTFC probe and strict Squirrel tryout readiness doctor.

Changes:
- Debug server now exposes `POST /api/predictor-ttfc`.
- Browser debug page has a compact Model TTFC card showing p50, p95, and over-budget samples.
- `scripts/doctor_squirrel_integration.sh` now supports `RAG_IME_DOCTOR_REQUIRE_TRYOUT=1`.
- Strict doctor mode checks prepared patched Squirrel files, generated config, `xcodebuild -list`, sidecar `/health`, `/rime-suggest`, and `/rime-select`.

Findings:
- Current default doctor path passes sidecar health/suggest/select and prepared Squirrel checks.
- Strict tryout readiness fails only because the active developer directory is still CommandLineTools, so full Xcode remains the real blocker before patched Squirrel can be built and tried as an input source.

### 2026-07-01
Topic:
- Add one aggregate local quality gate before moving deeper into full Xcode/Squirrel tryout work.

Changes:
- Added `quality-gate`, which combines deterministic acceptance, direct Codex-history RAG eval, `/rime-suggest` sidecar eval, and cache probing.
- Refactored the CLI eval paths into reusable helpers.
- Added a regression test and README command for the aggregate gate.

Status:
- The overall RAG-IME project is not done. Remaining acceptance requires real full-Xcode Squirrel build/install, system input-method use, RAG/memory quality tuning, local model latency work, and interview material updates.

### 2026-07-01
Topic:
- Finish the automated full-Xcode Squirrel tryout path as far as this host allows.

Changes:
- `scripts/build_patched_squirrel.sh` now supports `install`, dependency preinstall, bundled-data refresh, user-local `Squirrel.app` install, and managed RAG-IME config installation.
- Added `scripts/install_squirrel_rag_config.sh` to write the `rag_ime/*` patch block into `squirrel.custom.yaml` without requiring manual YAML copying.
- README and Xcode/macOS frontend docs now include the full prepare -> doctor -> list -> build -> install -> continuous-use verification path.

Status:
- Patched Squirrel workspace, LaunchAgent sidecar, `/rime-suggest`, and `/rime-select` are ready.
- Real build/install/system input-method verification is still blocked on the host because no full `Xcode.app` is installed and `xcode-select` points to CommandLineTools.

### 2026-07-01
Topic:
- Convert Wisdom-Weasel fast-path source lessons into model-lane quality gates.

Changes:
- Added repeatable `quality-gate --require-predictor-capability`.
- Aggregate gate reports predictor status and fails explicit capability checks such as `promptCache`, `sequenceFork`, and `batchCandidates`.
- `NullPredictionProvider` now exposes the same capability-map shape, so strict model-lane gates fail with a readable `actual=false` instead of a missing field.
- README, Mac local inference docs, and interview difficulty notes now explain that Ollama/MLX smoke providers are useful for debugging, but the final Wisdom-Weasel-style local model lane must prove KV prompt cache, sequence fork, and batch candidate generation.

Findings:
- Wisdom-Weasel's useful local-model mechanisms are resident llama.cpp, stable system prompt state save/restore, `llama_memory_seq_cp` sequence copy, and batched short candidate sampling.
- Do not copy its unbounded detached-thread provider shape directly; RAG-IME should keep latest-only guards and serialize or cancel native model context use.
- Full Xcode remains the hard external blocker on this host. `xcodebuild -version` reports that the active developer directory is CommandLineTools and requires a full Xcode installation.

### 2026-07-01
Topic:
- Make predictor capability gates probe the MLX runtime instead of only static config.

Changes:
- MLX `/health` now reports runtime capabilities.
- `prediction_provider_status(..., probe_capabilities=True)` and `predictor-status --probe-capabilities` can read runtime capability facts.
- `quality-gate` automatically probes capabilities whenever `--require-predictor-capability` is used.
- `promptCache=true` requires the MLX cache to be prepared, present on disk, and already used by generation.

Status:
- This advances the local model lane toward a real Wisdom-Weasel-style acceptance gate, but `sequenceFork` and `batchCandidates` still remain false until a native llama.cpp/Metal or stronger MLX provider exists.

### 2026-07-01
Topic:
- Strengthen RAG/memory quality gates beyond pass-rate.

Changes:
- `quality-gate` now supports top1, MRR, and noise thresholds separately for direct RAG and `/rime-suggest` sidecar eval.
- Added regression tests for metric-check presence and forbidden-term noise gate failures.
- README and Codex-history eval docs now show stricter mature-goldset commands.

Next:
- Subagent read-only research points to VCP-style in-flight provider dedupe as the next shared-core slice: add pending request coalescing around embedding/rerank provider cache misses in the PI shared memory core.

### 2026-07-01
Topic:
- Add VCP-style in-flight provider dedupe to the shared RAG/memory core.

Changes:
- Implemented coalescing for concurrent identical query embedding, embedding rerank, and LLM rerank provider misses in the PI shared core.
- Added a standalone in-flight regression test for dedupe and retry-after-failure behavior.
- learnA top-level has local commit `4c67f8e7`; it was not pushed because that repo already contains unrelated dirty/ahead state.

Verification:
- The focused in-flight test, provider import smoke test, `git diff --check`, and PI extension `npm test` all passed.

Status:
- RAG-IME product branch remains the main pushed branch for this work.
- Full-Xcode Squirrel build/install/system-input-method continuous-use verification remains blocked until a real `Xcode.app` is installed and selected; current host only has Command Line Tools active.

### 2026-07-01
Topic:
- Add stable history/context fingerprints for the local model lane.

Changes:
- Sidecar/debug responses now expose `historyContextMeta`.
- Model predictions now include local `requestMeta` with current-input, context, and stable-prefix fingerprints.
- The MLX service protocol receives and echoes these fingerprints so cached-prefix experiments can prove when the stable history prefix is reusable.
- External OpenAI-compatible and Ollama request bodies were not changed.

Verification:
- Focused sidecar/predictor/MLX tests, `py_compile`, full 132-test suite, and `git diff --check` passed.

Next:
- Use these fields in the native llama.cpp/Metal or stronger MLX provider to guard prompt/KV cache reuse and later sequence-forked multi-candidate sampling.

### 2026-07-01
Topic:
- Enforce `latencyBudgetMs` on the `/rime-suggest` model lane.

Changes:
- RAG retrieval now runs before the optional model lane in the sidecar.
- The model lane only waits for the remaining request budget; timeout returns Rime/RAG candidates with `modelPredictions=[]`.
- Added `modelLane` observability to sidecar responses.
- Added regression coverage for a slow model timing out while RAG candidates remain responsive.

Verification:
- Sidecar/debug-server focused tests passed.
- Full suite passed with 133 tests.

Next:
- Later native llama.cpp/Metal or stronger MLX provider should use real cancellation/sequence state, but the hot path now has fail-open behavior even before that provider exists.

### 2026-07-01
Topic:
- Extend sidecar latency-budget enforcement to RAG and history-context loading.

Changes:
- Added `ragLane` budget/timeout observability around `adapter.suggest(...)`.
- Slow RAG retrieval now fails open to the existing Rime candidates instead of blocking `/rime-suggest`.
- Model history-context construction now happens inside the model budget thread; if it consumes the budget, the provider is not called.

Verification:
- Sidecar focused tests passed after adding slow-RAG and slow-history regressions.
- Debug-server focused tests and full 135-test suite passed.

Next:
- Run debug-server/full-suite verification, then keep iterating toward shared-core latency gates and real native-provider cancellation.

### 2026-07-01
Topic:
- Add quality gates for sidecar RAG/model lane timeouts.

Changes:
- `eval-rime-sidecar` records `ragLane` and `modelLane` called/timeout counts and timeout rates.
- `quality-gate` can now fail when RAG or model side lanes exceed configured timeout-rate thresholds.
- README and Codex-history eval docs show strict mature-goldset flags for zero tolerated side-lane timeouts.

Verification:
- `py_compile`, focused Codex-history tests, and full 136-test suite passed.

Status:
- Product repo work is ready to commit/push.
- Full Xcode real build/install/system input-method verification remains a separate blocker until `Xcode.app` is installed and selected.

### 2026-07-01
Topic:
- Make local model TTFC part of the quality gate.

Changes:
- Added `quality-gate --require-model-ttfc`.
- The gate reuses the `bench-ime-ttfc` implementation and checks the winning model's first parsed candidate behavior.
- New checks cover streaming support, missing first candidates, p95 first-candidate latency, and over-budget rate.
- Documentation now shows how to enforce `qwen3.5:0.8b-mlx` as the current Ollama MLX smoke model.

Verification:
- Predictor-focused tests, Codex-history quality-gate tests, full 137-test suite, and `git diff --check` passed.

Status:
- Real Ollama model benchmark was not run in this turn because the Ollama server was not running.

### 2026-07-01
Topic:
- Install patched Squirrel as the first real macOS input-method App bundle.

Changes:
- Added LaunchAgent bootstrap retry/backoff so sidecar reinstall survives transient `launchctl` I/O errors.
- Unified the generated Squirrel fallback DB path with the LaunchAgent sidecar DB under `~/Library/Application Support/RagIme/rag-ime.sqlite`.
- Built and installed patched `Squirrel.app` into `~/Library/Input Methods`.
- Re-deployed the Rime `squirrel.custom.yaml` RAG-IME block with `sidecar_url=http://127.0.0.1:8766/api`.

Verification:
- Sidecar LaunchAgent reinstall reported `health: OK`.
- Strict Squirrel doctor passed with `failures=0 warnings=0`.
- Full test suite passed with 140 tests.

Next:
- Enable Squirrel/Rime in macOS System Settings and do continuous real typing validation with the installed input source.

### 2026-07-01
Topic:
- Make user-level Squirrel registration verifiable through macOS TIS.

Changes:
- Patched Squirrel to register `Bundle.main.bundleURL` instead of the upstream hardcoded `/Library/Input Library/Squirrel.app`.
- Added default ad-hoc deep signing after copying `Squirrel.app` into the user input-method directory.
- Added a shared TIS probe and install-time register/enable retry loop.
- Strict doctor now verifies `im.rime.inputmethod.Squirrel.Hans enabled=true selectable=true`.

Verification:
- Reinstall registered `file:///Users/undo/Library/Input%20Methods/Squirrel.app/`.
- Install script itself confirmed `macOS input source enabled`.
- Strict doctor passed with the macOS input-source check enabled.

Next:
- Use the macOS input menu to switch to Squirrel and run continuous typing validation in a normal text app.

### 2026-07-01
Topic:
- Make Squirrel visible in macOS System Settings and tighten install verification.

Changes:
- Added HIToolbox enabled-source verification on top of TIS registration.
- Added a local helper to back up and update `com.apple.HIToolbox` for Squirrel, then re-register the input source.
- Added selected-source/wait scripts for the final real typing gate.
- Updated README and setup docs so install readiness requires `hitoolboxEnabled=true`.

Verification:
- System Settings shows `鼠须管`.
- Strict doctor with HIToolbox requirement passed with no failures or warnings.
- Full 142-test suite passed in non-sandbox mode.

Next:
- User must switch from the menu bar input menu to `鼠须管` / Squirrel, then rerun `scripts/wait_squirrel_typing_ready.sh` and type in a normal editor.

### 2026-07-01
Topic:
- Add macOS input-source status to the browser debug page.

Changes:
- Added `/api/input-source` to the debug server.
- Added an Input Source card to the debug UI showing installed-list state, selected state, and compact current source.
- README now documents that the debug page separates System Settings visibility from active Squirrel typing.

Verification:
- Browser page rendered the new card with `list=ok`, `selected=no`, `current=Doubao`, matching the current machine state.
- Browser console had no warnings/errors.
- Full 144-test suite passed.

Next:
- Switch active input source to `鼠须管`, rerun `scripts/wait_squirrel_typing_ready.sh`, and then perform continuous editor typing validation.

### 2026-07-01
Topic:
- Add active Squirrel selection to the aggregate quality gate.

Changes:
- Added `quality-gate --require-input-source-ready`.
- Added `input-source-installed` and `input-source-selected` checks using the same input-source status logic as the debug page.
- README mature-goldset command now includes the real macOS typing gate.

Verification:
- Focused quality-gate tests cover selected and unselected input-source states.
- Current-machine smoke fails specifically on `input-source-selected` until the menu bar is switched to `鼠须管`.
- Full 146-test suite passed.

Next:
- Use the gate after switching to `鼠须管`; until then it should fail specifically on `input-source-selected`.

### 2026-07-01
Topic:
- Make the debug input-source card live and readiness-oriented.

Changes:
- `/api/input-source` now returns `readinessState`, `readinessMessage`, and `nextAction`.
- Debug UI polls input-source status every 2.5 seconds and shows `ready`, `switch`, `install`, or `error`.
- README/debug docs now state that `switch` means Squirrel is visible/enabled but not the current active input source; `ready` is required before real typing validation.

Verification:
- Tests cover ready, switch, and install-needed states.
- Current machine still reports installed/HIToolbox-enabled but selected=false with current ABC.

Next:
- After the user switches the macOS menu-bar input source to `鼠须管`, rerun `scripts/wait_squirrel_typing_ready.sh` and then the quality gate with `--require-input-source-ready`.

### 2026-07-01
Topic:
- Add one-command Squirrel tryout machine gate.

Changes:
- Added `python3 -m rag_ime.cli squirrel-tryout-gate`.
- The gate checks input-source readiness, sidecar health, and then the existing backend `quality-gate` with input-source readiness enabled.
- It fails fast on `readinessState=switch` and can write a report with `--report-path`.
- README and Xcode setup docs now point to this command after `scripts/wait_squirrel_typing_ready.sh`.

Verification:
- Tests cover not-selected fast-fail and selected fake-source quality-gate continuation.
- Real local smoke shows sidecar healthy with `local-ollama qwen3.5:0.8b-mlx`, but input source remains `ABC`, so the tryout gate correctly fails before quality-gate.

Next:
- Switch active macOS input source to `鼠须管`, then run `squirrel-tryout-gate` and continue with manual 20-prompt typing validation.

### 2026-07-01
Topic:
- Extend Squirrel tryout gate with installed bundle/config checks.

Changes:
- `squirrel-tryout-gate` now checks the installed `Squirrel.app` executable and bundle id.
- It parses the real `~/Library/Rime/squirrel.custom.yaml` RAG-IME managed block and compares `enabled`, `sidecar_url`, `db_path`, and `project`.
- It treats `/api` sidecar config as equivalent to the base sidecar health URL.

Verification:
- Tests use fake app bundles and fake managed configs for not-selected and selected input-source paths.
- Real local smoke passes installed bundle, installed Rime config, and sidecar health; it still fails only because current input source is ABC, not Squirrel.

Next:
- Switch active input source to `鼠须管`; then the same gate can proceed into backend `quality-gate`.

### 2026-07-01
Topic:
- Add sidecar candidate-payload probe to Squirrel tryout gate.

Changes:
- `squirrel-tryout-gate` now checks sidecar `/health` and also POSTs a safe `/rime-suggest` probe.
- The report includes `sidecar.rimeSuggest.schemaVersion`, `displayCandidateCount`, `queryBasis`, and cache metadata.
- It still does not call `/rime-select` by default, so real side-candidate commit remains manual/GUI evidence.

Verification:
- Added a mock sidecar test for the `/rime-suggest` probe.
- Real local smoke reports `rag-ime.rime-sidecar.v1`, `displayCandidateCount=2`, and `queryBasis=rimeCandidates`; the only failing gate remains active input source `ABC`.

Next:
- Switch active input source to `鼠须管`, then rerun the same tryout gate so it can proceed into backend `quality-gate`.

### 2026-07-01
Topic:
- Add LaunchAgent persistence check to Squirrel tryout gate.

Changes:
- `squirrel-tryout-gate` now checks `launchctl print gui/<uid>/com.rag-ime.sidecar` and reports the LaunchAgent `state`, `pid`, `path`, and `program`.
- Backend `quality-gate` only runs after installed bundle, real Rime config, LaunchAgent, selected input source, and sidecar checks all pass.
- Tests can pass `--skip-launch-agent` to avoid depending on the host launchd service.

Verification:
- Full 151-test suite passed.
- Real local smoke passes installed bundle, real Rime config, LaunchAgent `state=running`, sidecar health, and `/rime-suggest`; it still stops at `current=com.apple.keylayout.ABC`.

Next:
- Click "完成", switch the macOS input menu from ABC to `鼠须管`, then rerun `squirrel-tryout-gate` for the first full selected-source smoke.

### 2026-07-01
Topic:
- Fix Squirrel installed-but-no-output failure.

Changes:
- Added `scripts/bootstrap_squirrel_user_data.sh` to populate `~/Library/Rime` from Squirrel `SharedSupport` and Plum output, run `Squirrel --build`/`--reload`, and verify compiled Rime artifacts.
- Integrated the bootstrap into `scripts/build_patched_squirrel.sh install`.
- Updated docs to make user Rime data build a required install condition, separate from TIS/HIToolbox registration.

Verification:
- New bootstrap tests cover successful user-data build and silent `missing input schema` failure detection.
- Install-flow test now asserts `~/Library/Rime/build/luna_pinyin.table.bin` exists.

Next:
- Run the bootstrap against the real installed app, then switch to `鼠须管` from the input menu and test normal `nihao` typing before continuing RAG/model validation.

### 2026-07-01
Topic:
- Tighten macOS input-source visibility check for third-party IMEs.

Changes:
- `scripts/check_macos_input_source.sh` now checks `com.apple.inputsources` for third-party IMEs and prints `thirdPartyEnabled`.
- `scripts/enable_squirrel_hitoolbox_input_source.sh` now attempts both HIToolbox and inputsources updates and warns when System Settings UI Add is required.
- Docs now explain that TIS registration/selectability is not enough on macOS 27.

Verification:
- Real local check now reports Squirrel as TIS enabled/selectable but `hitoolboxEnabled=false thirdPartyEnabled=false` until System Settings adds it to the third-party input-source list.

Next:
- Confirm or manually perform System Settings -> Keyboard -> Input Sources -> Add -> Chinese, Simplified -> Squirrel, then rerun `scripts/check_macos_input_source.sh`.

### 2026-07-01
Topic:
- Remove false-positive input-source readiness after macOS 27 third-party-source finding.

Changes:
- Install postcheck now requires `check_macos_input_source.sh --require-hitoolbox-enabled`.
- Debug readiness parses `thirdPartyEnabled`; missing HIToolbox or third-party source now returns `install`, not `switch`.
- Quality-gate input-source checks include `thirdPartyEnabled`.
- Added isolated shell-script tests for third-party input-source preference handling.

Verification:
- Full 156-test suite passed.

Next:
- Use System Settings UI to add `鼠须管`, then rerun the strict input-source check and foreground typing test.

### 2026-07-01
Topic:
- Add compiled Rime build artifacts to Squirrel tryout evidence.

Changes:
- `squirrel-tryout-gate` now reports `installedRimeBuild` and checks `build/default.yaml`, `build/luna_pinyin.schema.yaml`, and `build/luna_pinyin.table.bin`.
- Quality-gate only runs after the Squirrel bundle, managed config, compiled Rime data, input-source readiness, LaunchAgent, and sidecar checks all pass.

Verification:
- Added a missing-build tryout test that fails fast and skips quality-gate.

Next:
- After adding `鼠须管` in System Settings, rerun `squirrel-tryout-gate`; it will now also prove the local Rime build is usable.

### 2026-07-01
Topic:
- Add a wait gate for System Settings input-source addition.

Changes:
- Added `scripts/wait_squirrel_input_source_added.sh`.
- `scripts/wait_squirrel_typing_ready.sh` now fails fast when Squirrel is not fully added to current-user input-source lists.
- Docs split the flow into source-list add, menu-bar switch, tryout gate, and foreground typing.

Verification:
- Added wait-script tests for success and fast failure.

Next:
- Run `scripts/wait_squirrel_input_source_added.sh` while adding Squirrel in System Settings, then switch the input menu and run `scripts/wait_squirrel_typing_ready.sh`.

### 2026-07-01
Topic:
- Make the debug page show the real macOS third-party input-source blocker.

Changes:
- `/api/input-source` now includes `readinessChecks`, `manualAction`, and `verificationCommand`.
- The debug Input Source card now shows `TIS`, `3rd`, `selected`, and `current` instead of hiding `thirdPartyEnabled` in JSON.
- The card hint shows the next action and wait script, so `thirdPartyEnabled=false` leads to the System Settings Add flow.

Verification:
- Targeted input-source debug tests passed.
- Playwright opened the real debug page; console had 0 errors after reload.
- Real local visual state showed `TIS=yes`, `3rd=no`, `selected=no`, `current=ABC`, readiness `install`.

Next:
- Add Squirrel in System Settings, then run `scripts/wait_squirrel_input_source_added.sh` and `scripts/wait_squirrel_typing_ready.sh`.

### 2026-07-01
Topic:
- Add a System Settings helper for the remaining Squirrel input-source blocker.

Changes:
- Added `scripts/open_squirrel_input_source_settings.sh`.
- The helper opens the Keyboard settings pane, prints the exact Add flow, and supports `--wait` to run the strict source-list gate.
- `/api/input-source` now includes `helperCommand=scripts/open_squirrel_input_source_settings.sh --wait` for install-state readiness.
- README, Xcode setup, macOS adapter docs, debug surface docs, and wait-script errors now point to the helper.

Verification:
- Targeted wait/debug tests passed.
- Real local smoke still reports `thirdPartyEnabled=false`, and the helper prints the expected Add flow.
- Playwright verified the debug card shows `TIS=yes`, `3rd=no`, `selected=no`, `current=ABC`, and the helper command with 0 console errors.

Next:
- Run `scripts/open_squirrel_input_source_settings.sh --wait`, add Squirrel in System Settings, then run `scripts/wait_squirrel_typing_ready.sh`.

### 2026-07-01
Topic:
- Lock down direct MLX multi-candidate output and mixed candidate-panel layout.

Changes:
- Resident MLX `/predict` now tries `candidateMode: next-token-logits` before JSON generation and reports `logitsTopK=true`, `batchCandidates=true`, `sequenceFork=false`.
- Sidecar merge keeps RAG block-row reserve, so an 8-slot response can show short `model/inline` candidates in a horizontal lane followed by `rag/block` memory rows.
- Updated the active Goal and Mac inference docs to reflect direct MLX as the current product path, with Ollama MLX kept as a debug baseline.

Verification:
- Focused sidecar/MLX/predictor tests passed, plus `py_compile` and `git diff --check`.
- Real Squirrel integration doctor passed with `failures=0 warnings=0`.
- Manual `/rime-suggest` returned 5 `model/inline` candidates and 3 `rag/block` candidates with model lane elapsed 145 ms.

Next:
- Finish identifying and comparing the three downloaded safetensors models, then run continuous foreground typing verification with the user.

### 2026-07-01
Topic:
- Add safe raw-input continuation behavior for `asdioj`-style noisy composition.

Changes:
- Patched Squirrel now stores sidecar `queryBasis` and display timestamp.
- When raw/preedit changes and Rime has no candidates, Squirrel can briefly hold the previous `committedContext`-based side candidates for 1.2s.
- Raw input with no Rime candidates and no committed context still fails closed; the model is not allowed to decode raw key sequences directly.
- Docs and the Wisdom-Weasel issue map now describe this boundary.

Verification:
- Patch/prepare/sidecar tests passed, `git diff --check` passed.
- Re-prepared, rebuilt, installed, and re-registered patched Squirrel.
- Doctor passed with `failures=0 warnings=0`.
- Manual sidecar payloads showed `asdioj` without context skips side lanes, while `asdioj` with recent committed context returns model/RAG candidates through `queryBasis=committedContext`.

Next:
- Switch to Squirrel in the menu bar and do foreground continuous typing verification; then continue the 3 downloaded safetensors model comparison.

### 2026-07-02
Topic:
- Enforce real-panel layout: horizontal LLM lane, vertical sentence/RAG rows.

Changes:
- Squirrel patch now tracks whether the current panel is actually using sidecar display candidates before applying sidecar layout or number-key routing.
- Active `model/inline` candidates force local panel linear/horizontal behavior; `rag/block` candidates still use newline-separated rows.
- Rebuilt and installed patched Squirrel.app from `/tmp/rag-ime-squirrel-verify`.

Verification:
- `/rime-suggest` for `erq` returned 5 `model/inline` candidates and 3 `rag/block` candidates, model lane elapsed 158 ms.
- Focused tests passed: 66 tests.
- `py_compile`, `git diff --check`, patch prepare, Xcode Release install, input-source selection, and doctor all passed.
- Current input source is `im.rime.inputmethod.Squirrel.Hans`; doctor summary is `failures=0 warnings=0`.

Next:
- User should try foreground typing; if the first frame briefly shows Rime fallback, wait ~200 ms for the sidecar refresh and check whether the panel updates to horizontal LLM + vertical RAG.

### 2026-07-02
Topic:
- Reinstall and verify horizontal LLM lane plus vertical sentence rows in the real Squirrel/MLX runtime.

Changes:
- Added build/preparation guards for the mixed panel patch so old Squirrel workdirs cannot pass without `ragImePanelForcesHorizontalLayout`, `ragImePanelLinear`, and `candidateSeparator`.
- Added MLX local model metadata to `/health` and propagated it through sidecar predictor status and doctor.
- Reinstalled patched Squirrel.app, restarted the resident MLX predictor, and reinstalled the sidecar with `RAG_IME_PREDICTOR_PROVIDER=mlx`.

Verification:
- 95 focused tests passed, plus syntax/check scripts.
- Installed `/rime-suggest` now returns labels 1-5 as `model/inline` and 6-8 as `rag/block`.
- Doctor passes with `failures=0 warnings=1`; the warning correctly flags the current Qwen3.5 MLX package as vision-language rather than pure text.

Next:
- Foreground typing should be tested again. The next model task is replacing the active Qwen3.5 VLM directory with a complete pure-text MLX model directory.

### 2026-07-02
Topic:
- Replace the active Qwen3.5 VLM runtime with a text-only local MLX model directory.

Changes:
- Added `scripts/derive_text_mlx_model.py`.
- Derived `/Volumes/undo 4t/models/mlx-community-Qwen3.5-0.8B-text-4bit-local` from the existing Qwen3.5 MLX-VLM directory by keeping only `language_model.*` weights.
- Reinstalled MLX predictor and sidecar LaunchAgents to use the derived text-only directory.
- Updated docs with repeatable derivation/install commands.

Verification:
- Direct `MlxLmEngine` load/predict succeeded; next-token logits returned 5 candidates in about 135 ms.
- Runtime `/health` now reports `textOnly=true`, `hasVisionConfig=false`, and `textOnlyModel=true`.
- `/rime-suggest` still returns `model/inline` first and `rag/block` rows after it.
- Doctor now passes with `failures=0 warnings=0`.

Next:
- Test live foreground typing and number-key commit behavior in the actual macOS panel.

### 2026-07-02
Topic:
- Keep native Squirrel sidecar requests aligned with recent committed input context.

Changes:
- Added `committedContext` to the native Squirrel sidecar request fingerprint.
- Added stale-response guards so old sidecar responses cannot overwrite the panel after the user commits new text.
- Rebuilt and reinstalled patched Squirrel.app with the updated patch.

Verification:
- Real patch apply, Xcode Release build/install, focused tests, input-source re-registration, and doctor all passed.
- Current selected source is `im.rime.inputmethod.Squirrel.Hans`.
- Sidecar still uses the text-only MLX model at `/Volumes/undo 4t/models/mlx-community-Qwen3.5-0.8B-text-4bit-local`.

Next:
- Foreground typing and number-key commit validation are still required before marking the whole goal complete.

### 2026-07-02
Topic:
- Promote mixed candidate layout and numeric selection routing into strict doctor.

Changes:
- `scripts/doctor_squirrel_integration.sh` now checks the mixed candidate contract when `RAG_IME_DOCTOR_REQUIRE_TRYOUT=1`.
- The strict check requires shared `selectionKey` / `selectionRank`, side-first merge policy, model `inline/model` candidates before RAG `block/memory` rows, and at least one model plus one RAG candidate.
- Debug/Xcode docs now distinguish this backend/native-payload gate from real foreground AppKit panel validation.

Verification:
- Doctor unit tests passed.
- Real strict doctor passed with `display=8 model=5 rag=3 rime=0` and candidate contract OK.

Next:
- Remaining final validation is still foreground typing and real number-key side-candidate commit in a normal editor.

### 2026-07-02
Topic:
- Fix real Squirrel panel path for horizontal LLM candidates and vertical sentence/RAG rows.

Changes:
- Added pending-request fingerprint suppression in the Squirrel frontend patch so repeated equivalent UI refreshes do not invalidate valid sidecar responses.
- Changed response freshness checks to compare against the original request and current input/context fingerprint, preventing the global `requestSeq` from dropping live model/RAG responses.
- Made Squirrel panel measurement and placement use `ragImePanelVertical` consistently, so `model/inline` candidates can render in the horizontal lane while `rag/block` candidates remain row-based.
- Rebuilt and reinstalled patched Squirrel.app.

Verification:
- Real Xcode Release install succeeded.
- Current selected input source is `im.rime.inputmethod.Squirrel.Hans`.
- Strict doctor passed with `failures=0 warnings=0`, `display=8 model=5 rag=3 rime=0`.
- Manual `/rime-suggest` confirmed 1-5 are `model/inline`, 6-8 are `rag/block`.
- Focused tests passed: 57 tests.

Next:
- User should visually test in a normal editor. If a first native Rime frame appears, wait for the sidecar refresh and check whether it updates to one horizontal LLM row plus vertical RAG rows.

### 2026-07-02
Topic:
- Add restart-drift validation for sidecar and MLX LaunchAgents.

Changes:
- Strict Squirrel doctor now reads sidecar and MLX predictor LaunchAgent plists.
- It verifies launchd will restart the same source root, MLX provider/model/base URL, stream-first setting, empty proxy vars, and prompt-cache-backed `mlx-predictor-server`.
- Added tests for matching plist configuration and stale model-path drift.

Verification:
- Focused doctor tests passed: 12 tests.
- Full suite passed: 192 tests.
- Real strict doctor shows LaunchAgent plist checks are OK; only stale `/Library/Input Methods/Squirrel.app` still fails.

Next:
- User must run `scripts/replace_system_squirrel_app.sh` with admin password, then rerun foreground trace validation for horizontal LLM row plus vertical RAG rows.

### 2026-07-02
Topic:
- Make system Squirrel replacement self-verifying.

Changes:
- `scripts/replace_system_squirrel_app.sh` now checks the copied target app for mixed-layout patch markers.
- The script runs strict doctor without foreground trace by default after registering/selecting the input source.
- Added tests for post-copy doctor wiring and copied-target patch-marker failure.

Verification:
- Replacement script syntax check passed.
- Focused replacement-script tests passed: 2 tests.

Next:
- User can run `scripts/replace_system_squirrel_app.sh` once with admin password; the script will now perform the non-foreground strict gate automatically.

### 2026-07-02
Topic:
- Align strict doctor model-lane budget with real Squirrel config.

Changes:
- Strict doctor now sends `latencyBudgetMs=180` by default instead of relying on the sidecar's 150 ms fallback.
- Added `RAG_IME_DOCTOR_LATENCY_BUDGET_MS` override and test coverage for the default budget.
- Docs now state that doctor budget matches managed Squirrel config.

Verification:
- Doctor tests passed: 12 tests.
- Real strict doctor returns `display=8 model=5 rag=3 rime=0` again under the 180 ms probe budget.

Next:
- Remaining runtime blocker is still the stale root-owned system Squirrel app; run the replacement script with admin password.

### 2026-07-02
Topic:
- Continue real macOS foreground run audit after candidate-layout commit.

Findings:
- `RAG-IME - Simplified` is registered in TIS but cannot be selected because `com.apple.inputsources.plist` does not persist its third-party whitelist entry; `TISSelectInputSource` returns `-50`.
- The accepted/selected source remains `im.rime.inputmethod.Squirrel.Hans`.
- User-local `~/Library/Input Methods/Squirrel.app` contains the RAG-IME mixed-layout patch, but `/Library/Input Methods/Squirrel.app` has the same bundle id and is stale.
- Automatic foreground trace was blocked by macOS permissions: `osascript` cannot send keystrokes and screenshot capture is black.

Changes:
- Doctor stale duplicate message now tells the user to run `scripts/replace_system_squirrel_app.sh`.
- `scripts/replace_system_squirrel_app.sh --preflight` now reports no-op source/target patch status; current machine shows `replacement_required=true` and `sudo_cached=false`.

Next:
- Replace the root-owned system Squirrel with the patched app using admin credentials, then rerun foreground trace and number-key commit validation.

### 2026-07-02
Topic:
- Run through the Prediction-first service flow after user reported that LLM/RAG/memory candidates were not visible.

Findings:
- Live `/rime-suggest` showed the post-commit state existed but side lanes were skipped when only `committedContext` was present and idle was below 300 ms.
- This made the post-commit continuation panel empty even though prefix-constrained cases could show model/memory.

Changes:
- Post-commit committed-context refresh now fires immediately when there is no active composition.
- Prediction modes now filter weak low-value wanxiang fallback terms and short model noise like `测试流程`.
- Live verifier now covers post-commit continuation plus raw command/code/path protection.

Verification:
- 88 focused tests passed.
- MLX predictor and sidecar LaunchAgents were restarted and health-checked.
- Live sidecar verifier passed all seven flow cases.

Next:
- Continue with native foreground validation in Codex App, Edge, and TextEdit; if the front panel still shows old candidates, inspect whether the patched Squirrel frontend is sending fresh context and applying the sidecar response.

### 2026-07-02
Topic:
- Align LLM/RAG/memory candidate display with Wisdom-Weasel's short-lived prediction session.

Decisions:
- Prediction UI should not be a persistent clipboard/history panel.
- Show candidates only while there is active Rime composition or an active prediction session with live candidates.
- Empty response, stale request, Esc/focus loss, or normal raw input must hide the prediction layer so digits, English, paths, and code stay usable.

Changes:
- Added `predictionFirst.policy.panelVisible / hideWhenEmpty / sessionBound`.
- Added 1.2s TTL for post-commit continuation holdover.
- Bound model holdover reuse to the current semantic input state, so changing pinyin prefix clears the old model row instead of making it look persistent.
- Kept `rag`, `memory`, and `model` as separate visible lanes before score-only fill.
- Added short pinyin-prefix lookup for RAG/memory filtering and avoided long raw pinyin as semantic query.
- Updated Squirrel patch marker from `sidecar_empty_response_ignored` to `sidecar_empty_response_cleared`.
- Updated framework/frontend docs and feedback issue log.

Verification:
- Focused prediction/debug/RAG tests passed: 121 tests.
- Red full-suite regressions around Squirrel trace marker and MLX phrase-like logits were fixed with focused regression tests passing.
- Full test suite passed: 264 tests.

Next:
- Commit and push this lifecycle fix, then reinstall/reload the patched frontend before real editor validation.

### 2026-07-02
Topic:
- Extract frontend-neutral PredictionSession lifecycle for the next non-patched-Squirrel adapter path.

Decisions:
- Do not let future macOS frontend code infer AI overlay state from generic candidate visibility.
- Treat Rime/wanxiang candidate visibility and AI prediction-panel visibility as separate concepts.

Changes:
- Added `PredictionSessionState`, `PredictionSessionPhase`, `resolve_prediction_session()`, and `prediction_session_to_payload()`.
- `/rime-suggest` now returns `predictionSession` with `phase`, `candidatePanelVisible`, `predictionPanelVisible`, `shouldClearPredictionPanel`, and `selectionScope`.
- Docs now define the shared adapter lifecycle contract for `anchor_composing`, `post_commit`, `prefix_constrained`, `raw_passthrough`, and `hidden`.

Verification:
- `py_compile` passed for prediction/session modules.
- Focused Prediction-first and sidecar tests passed: 12 tests.
- Broader debug/sidecar/core/model regression passed: 129 tests.
- Full suite passed: 265 tests.

Next:
- Commit/push this adapter-neutral contract.

### 2026-07-02
Topic:
- Add reusable PredictionManager above the frontend-neutral PredictionSession contract.

Changes:
- Added `rag_ime/prediction_manager.py`.
- `PredictionManager` keeps the active LLM/RAG/memory candidate pool bound to committed context and TTL.
- Continued pinyin can reuse the candidate pool and filter by prefix; raw passthrough clears the AI panel and does not reuse stale predictions.
- Added tests for post-commit render, prefix reuse, stale expiry, context isolation, and raw input protection.
- Updated shared contract and redesign plan with the manager entrypoint.

Verification:
- `py_compile` passed for prediction manager/core.
- Prediction-manager and prediction-first tests passed: 15 tests.
- Broader prediction/debug/sidecar tests passed: 95 tests.
- Full suite passed: 270 tests.

Next:
- Commit/push this manager layer.

### 2026-07-02
Topic:
- Align LLM/RAG/memory candidate appearance with Wisdom-Weasel's natural candidate-flow lifecycle.

Findings:
- Wisdom-Weasel's demo and code show LLM candidates as part of the Rime candidate flow, not as a persistent history popup.
- It enters prediction after meaningful commit, predicts asynchronously, drops stale results, appends LLM candidates to the structured candidate list, and uses llama.cpp system-prompt KV cache plus batch candidate sampling.
- RAG-IME should preserve the short-lived session model but keep continued pinyin as a prediction constraint instead of exiting prediction mode on letters.

Changes:
- `/rime-suggest` now uses `PredictionManager` in `predictionFirstMerge`.
- The candidate pool is session/project/app scoped and cleared on stale post-commit, raw passthrough, raw pinyin fallback, empty signal, or missing committed context.
- Debug policy now exposes candidate-pool active/reused/stale fields.
- Docs now state that passive post-commit prediction should live only around 0.8-1.2s unless the user keeps constraining or a fresh result arrives.

Verification:
- `py_compile` passed for sidecar/prediction modules.
- Focused sidecar + prediction-manager tests passed: 8 tests.
- Full suite passed: 271 tests.

### 2026-07-02
Topic:
- Native candidate panel lifecycle aligned with Wisdom-Weasel-style candidate flow.

Decisions:
- Keep LLM/RAG/memory candidates as short-lived IME sessions, not a persistent clipboard/history popup.
- A visible native panel can route number keys only when it belongs to the current valid requestSeq/context/composition session.
- Post-commit prediction uses a 0.85s frontend expiry; continued pinyin keeps Rime/Wanxiang composition in charge.

Changes:
- Added native `ActivePanelSession` and stricter stale-response rejection.
- Native panel hides on raw passthrough/hidden sessions, stale request, expired post-commit session, or resumed typing.
- Added `RimeDictionaryCandidateProvider` for local debug previews from Rime/Wanxiang dictionaries plus `essay.txt` weights.
- Updated macOS frontend and Rime/Squirrel decision docs.

Verification:
- macOS frontend build passed.
- Rime dictionary preview passed: `ni -> 你`, `wo -> 我`, code/path return no candidates.
- Rime sidecar preview decoded `displayCandidates` and `predictionSession`.
- Focused tests passed: 84.
- Full suite passed: 271.

Open issue:
- Candidate quality still needs a separate pass: short prefixes like `ni` can recall long RAG history snippets instead of concise, prefix-constrained continuation candidates.

### 2026-07-02
Topic:
- Tighten Prediction-first candidate appearance and commit contract after user feedback.

User feedback captured:
- The panel should feel like Wisdom-Weasel's natural IME candidate flow, not a persistent clipboard/history popup.
- Short active pinyin such as `ni` must not show unrelated RAG/memory history snippets.
- RAG/memory candidates should be selectable short spans; full retrieved material is evidence for expansion, not direct committed text.

Changes:
- Prefix-constrained mode now hard-filters side candidates by pinyin metadata. If no LLM/RAG/memory candidate matches, Wanxiang/Rime fallback is shown and the prediction panel is marked clearable.
- `SuggestionCompiler` now sets `insert_text` to the compact candidate surface and keeps original material in expanded evidence / preview metadata.
- Tests now cover the no-match `ni -> 你/呢` fallback and the short-candidate insert contract.

Verification:
- Focused prefix/insert tests passed.
- Runtime-term and demo-quality tests passed.
- macOS frontend build passed.
- Full test suite passed: 272 tests.

### 2026-07-02
Topic:
- Tighten candidate-panel lifetime against the Wisdom-Weasel reference behavior.

Decision:
- Active pinyin composition can keep the panel because it is normal IME state.
- Passive post-commit continuation is only a short visual bridge: 0.85s in native RagImeMac and 0.9s in patched Squirrel.
- Expired/hidden/no-session AI candidates must not capture number keys.

Changes:
- Patched Squirrel now validates the current raw input before routing a side-candidate number key and clears expired post-commit candidates.
- Native RagImeMac removed the legacy hidden model/RAG number-selection path and only selects visible `displayCandidates` tied to a valid `ActivePanelSession`.
- Sidecar now carries `expandedEvidence` through display payloads and records accepted feedback for real memory candidates as well as RAG candidates.

Verification:
- macOS frontend build passed.
- Focused lifecycle/selection tests passed: 104.
- Full suite passed: 274.

### 2026-07-02
Topic:
- Strengthen the native Wanxiang/Rime dictionary bridge used by RagImeMac debug previews.

Changes:
- `RimeDictionaryCandidateProvider` now accepts `RAG_IME_RIME_DICT_PATHS`, `RAG_IME_RIME_DICT_PATH`, and `RAG_IME_RIME_DICT_DIR`.
- Wanxiang `import_tables` are expanded so a real `7155/rime-wanxiang` checkout loads child dictionaries under `dicts/`.
- Tone-marked pinyin is folded, so rows like `nǐ` match normal `ni`.
- The provider uses a small pinyin/initials bucket index to avoid full-table scanning per key.
- Added a compile-level Swift test with a temporary Wanxiang-style fixture.

Verification:
- macOS frontend build passed.
- Wanxiang fixture preview passed for `ni`, `shijie`, `sj`, and rejected command/path input.
- Real `7155/rime-wanxiang` smoke passed via `RAG_IME_RIME_DICT_DIR=/tmp/rime-wanxiang-inspect`; cold YAML load was about 16s, so this stays a debug bridge until a real librime/native index path replaces it.
- Full suite passed: 275.

### 2026-07-02
Topic:
- Compact native panel and live-verifier correction for Prediction-first RAG IME.

User question:
- The branch name `codex/wisdom-weasel-rag-ime-mvp` is just a Git branch namespace prefix; GitHub's `default` badge means this branch is currently the default branch, not that the repo is under a Codex folder.

Changes:
- Native candidate popup is smaller and no longer renders evidence cards by default.
- Candidate-pool TTL now matches the short post-commit panel behavior at 900ms.
- LaunchAgent installer now preserves embedding/vector env vars for future local/remote embedding setup.
- Live sidecar verifier now treats unmatched pinyin as a valid Rime fallback path, while still requiring AI/RAG/memory to take priority when a prefix-matching side candidate exists.

Verification:
- Focused tests passed: 29.
- Live `verify_prediction_first_sidecar.py --latency-budget-ms 350` passed.
- macOS frontend build and user install passed.
- Full suite passed: 275.
- Health check shows local MLX Qwen3.5 0.8B text 4bit is active; vector retrieval is still disabled until embedding config/indexing is enabled.

### 2026-07-02
Topic:
- Enable installed-sidecar vector RAG baseline and backfill flow.

Decisions:
- Vector recall remains opt-in. `local-hash` is used only as a deterministic local baseline for proving the vector side-index path, not as a semantic embedding quality claim.
- The installed sidecar can be given `RAG_IME_ENABLE_LOCAL_VECTOR=1` for the local baseline, or explicit `RAG_IME_EMBEDDING_*` settings for a real local/WSL embedding endpoint.

Changes:
- `DebugImeService` gained `vectorAutoRebuild` health metadata, startup vector backfill, and a manual `/rebuild-vector-index` endpoint.
- CLI sidecar/debug servers now accept `--vector-auto-rebuild-limit` / `RAG_IME_VECTOR_AUTO_REBUILD_LIMIT`.
- LaunchAgent installer now preserves vector auto-rebuild config and can derive a local-hash baseline from `RAG_IME_ENABLE_LOCAL_VECTOR=1`.
- Local SQLite initialization now prunes orphan memory state/vector rows.
- README documents installed-sidecar vector setup and HTTP rebuild.

Verification:
- Live sidecar reinstalled with MLX Qwen3.5 0.8B text 4bit and local-hash vector baseline.
- Health now reports `vectorStats.enabled=true` and `activeProviderVectors=124`.
- Manual `/rebuild-vector-index` indexed 124 active vectors.
- Live Prediction-first verifier passed with RAG, memory, model, raw English/code/path protection, and Rime fallback.
- Full suite passed: 279.

### 2026-07-02
Topic:
- Make Prediction-first RAG IME use real Codex user history and stop mixing Rime into AI-hit candidates.

User feedback captured:
- Candidates must predict what the user is trying to say, not show Codex tool/status fragments.
- RAG and memory should use the user's long Codex/input history, not recent clipboard-like context.
- If an AI/RAG/memory candidate is available, Rime should not fill the panel; Rime is only first-word/no-match fallback.
- Weak/noisy contexts should not leave a panel full of generic words like `根据` / `基于` / `和` / `测试`.
- The branch prefix `codex/...` is only a Git branch namespace on the `7155/wisdom-weasel-rag-ime` repo.

Changes:
- `import-codex-history` now defaults to `--roles user`; a new `prune-codex-history-noise` command hides previously imported non-user roles.
- Live DB was backed up, then re-imported from `$HOME/.codex`, adding 4896 user records and rebuilding a 5023-row local vector side-index.
- `SuggestionCompiler` filters Codex status/tool-log surfaces and extracts usable short IME candidates from numbered design examples.
- Prefix matching now uses primary pinyin keys only, so a prefix like `sj` no longer matches unrelated middle words.
- Prediction-first merge now hides Rime/Wanxiang when a prefix-matching side candidate exists, and filters low-value Rime fallback in weak context.

Verification:
- Full Python suite passed: 285 tests.
- Live sidecar verifier passed with 650ms budget.
- macOS frontend build passed.

### 2026-07-02
Topic:
- Fix doctor model-path false warning for live MLX sidecar.

Change:
- `doctor_squirrel_integration.sh` now validates model generation with a post-commit Prediction-first payload instead of active raw pinyin.
- The doctor model probe always requests enough visible/side slots for model candidates, and retries once with a wider budget if the model lane is already running or timed out.
- Added a regression test for the busy-model-lane retry path.

Verification:
- Doctor unit tests passed: 15.
- Live doctor now reports `model generation path: MLX model candidates available`.
- Full suite passed: 286.

### 2026-07-02
Topic:
- Move readiness work from patched Squirrel toward native RagImeMac.

Decision:
- Treat native `RagImeMac` InputMethodKit as the current product route.
- Treat Rime/Wanxiang as dictionary/behavior reference and first-word fallback source.
- Keep patched Squirrel as an integration spike and comparison path, not the primary route.

Changes:
- Added `scripts/doctor_macos_frontend.sh` for native app/sidecar readiness.
- Native doctor validates app bundle, InputMethodKit plist, bridge config, Swift sidecar decoding, live Prediction-first side candidates, and raw command protection.
- README now points local validation to native doctor first.
- Sidecar verifier now retries transient post-commit model-lane busy states with a wider validation budget.

Verification:
- Native doctor passed against live build and sidecar.
- Full suite passed: 288.

### 2026-07-02
Topic:
- Fix native RagImeMac Space/English behavior.

Changes:
- Space in native `RagImeMac` now accepts the first active Prediction-first candidate, or the top Wanxiang/Rime dictionary candidate when composing pinyin.
- Raw English/code/path-like composition with no dictionary candidate commits directly with the trailing Space and does not trigger post-commit AI prediction.
- Native rendering now obeys `predictionSession.shouldClearPredictionPanel`, so weak/empty/stale responses clear the panel instead of keeping a stale overlay alive.
- Added native input-controller contract tests for these behaviors.

Verification:
- Native build passed.
- Native doctor passed against live sidecar.
- Sidecar verifier passed with weak-context clear and raw English/code/path cases.

### 2026-07-02
Topic:
- Close native install and input-source selection loop.

Changes:
- `install_macos_frontend.sh` now has `--select`, `--check`, `--no-check`, and `--require-input-source`.
- Shared TIS scripts default to native `dev.local.inputmethod.RagImeMac`.
- `select_macos_input_source.sh` treats the final current-input-source state as authoritative when `TISSelectInputSource` returns `-50` but the system already switched.
- README now documents `scripts/install_macos_frontend.sh --select` plus strict doctor.

Verification:
- Live `scripts/install_macos_frontend.sh --select` installed and selected `RAG IME`.
- Strict native doctor passed with selected-input-source requirements enabled.

### 2026-07-02
Topic:
- Repair Prediction-first IME flow after user reported LLM/RAG were still not usable.

Findings:
- MLX local `Qwen3.5-0.8B` service is healthy and can stream short candidates, but the sidecar/non-streaming path had an interface crash and the prompt could make the small model copy meta words.
- The imported Codex history DB is real (`10018` events, `5023` vectors), but it is stored under `wisdom-weasel-rag-ime`; requests with `project=learnA` caused RAG to silently return zero.
- Real-time vector scanning was too slow for a 100ms RAG lane; FTS-only is the right immediate candidate path, with vector/deep RAG reserved for later refresh.
- Native panel display and numeric selection could diverge because the UI regrouped rows but selection still used local indexes.

Changes:
- Added project fallback retrieval, real-time FTS-only RAG path, MLX low-value/meta-word filtering, MLX `/predict` compatibility, and backend `selectionRank/selectionKey` selection in the native panel.

Verification:
- Core tests passed: 137.
- Native build passed.
- Live sidecar now returns both MLX model and RAG candidates for the embedding/RAG debugging context.
- Current machine still needs manual Keyboard Input Sources selection; install succeeds but `TISSelectInputSource` returns `-50` and active source remains 豆包.

### 2026-07-02
Topic:
- Continue native macOS input-source registration repair after Add panel did not show RAG IME.

Findings:
- `RagImeMac.Hans` is visible to TIS and has healthy MLX/RAG sidecar candidates, but it is not in macOS `AppleEnabledThirdPartyInputSources`; current input source remains 豆包.
- System Settings Add not showing the app is likely due to registration split-brain: duplicate user/system installs, stale HIToolbox entries, missing app icon/platform metadata, and system app ownership not matching mature input methods.

Changes:
- Added visible `.Hans` input mode metadata, app icon metadata, supported platform declaration, localized mode names, generated `.icns`, and version bump.
- Added system installer and reset scripts to canonicalize `/Library/Input Methods/RagImeMac.app`, remove stale HIToolbox records, and make selected-source verification stricter.
- Fixed selected-source checks so `selected=true` only means the current TIS source actually equals `RagImeMac.Hans`.

Verification:
- Native build and focused tests passed.
- Native doctor passes app/bridge/sidecar checks.
- Selected-source doctor correctly fails until macOS actually selects `RAG IME`.

### 2026-07-02
Topic:
- Add LaunchServices refresh for native RagImeMac registration.

Findings:
- System install now leaves `/Library/Input Methods/RagImeMac.app` as `root:wheel` and LaunchServices has a valid canonical record.
- Add/select still fails because `AppleEnabledThirdPartyInputSources` does not include RagIme; current input source remains 豆包.
- Old temporary LS records existed from prior test installs, so refresh now targets only stale paths ending in `/RagImeMac.app`.

Changes:
- Added `scripts/refresh_macos_input_sources.sh`.
- System installer now invokes the refresh after installing the canonical system app.
- Added a test guard to prevent broad LS unregister matching.

Verification:
- Focused tests passed.
- Native doctor passes sidecar checks; selected-source doctor still fails until macOS allow-lists/selects RAG IME.

### 2026-07-02
Topic:
- Project-management reset after native RagImeMac still did not appear in System Settings.

Decisions:
- `RagImeMac` is debug harness only, not the product route.
- Product route returns to branded Squirrel/Rime candidate-layer integration with unique bundle id, Wanxiang/Rime composition, and Prediction-first sidecar candidates.
- Same-bundle system Squirrel replacement and direct HIToolbox/inputsource plist writes are emergency/debug repair paths only.

Changes:
- Native install scripts now require `RAG_IME_ALLOW_NATIVE_HARNESS_INSTALL=1`.
- README, route decision docs, debug-surface docs, and feedback issue log were updated to prevent future route confusion.

Next steps:
- Implement and verify the independent branded `RAG-IME.app` Squirrel/Rime foreground path with sidecar trace and `/rime-select` feedback.

### 2026-07-02
Topic:
- Make branded Squirrel install safer and easier to reason about.

Changes:
- `build_patched_squirrel.sh` now defaults direct preference repair and auto-selection to off.
- `RAG_IME_SQUIRREL_ENABLE_PREF_REPAIR=1` and `RAG_IME_SQUIRREL_AUTO_SELECT=1` are explicit debug opt-ins.
- Docs now describe System Settings Add + input menu switch as the normal route for `RAG-IME - Simplified`.

Verification:
- Branded dry-run shows `enable_pref_repair=0` and `auto_select=0`.
- Focused Squirrel/install tests passed.
