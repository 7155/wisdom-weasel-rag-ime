# Notes

## Run prefs (persistent)

- Do not maintain the learnA study site while implementing this product repo.
- Keep production macOS input method work on the Rime/Squirrel route; the InputMethodKit app is a prototype/debug harness.

## Log

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
