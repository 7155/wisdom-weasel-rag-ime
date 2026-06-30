# Chat Summary

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
