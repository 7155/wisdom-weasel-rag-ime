# Notes

## Run prefs (persistent)

- Do not maintain the learnA study site while implementing this product repo.
- Keep production macOS input method work on the Rime/Squirrel route; the InputMethodKit app is a prototype/debug harness.

## Log

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
