# macOS Frontend Adapter

## Research Conclusion

The current macOS MVP uses a two-layer prototype frontend:

```text
InputMethodKit shell
  -> RagBridgeClient JSON command
  -> Python LocalSqliteCoreClient
  -> custom NSPanel candidate/evidence UI
```

This is more suitable than using only `IMKCandidates` for early RAG/debug work.

- Apple `InputMethodKit` provides the system input method process, `IMKServer`, `IMKInputController`, marked text, committed text, and basic candidate windows.
- `IMKCandidates` supports simple candidates and annotations, but RAG needs action-rich evidence cards: pin, downrank, delete, expand, confidence, memory id, and source preview.
- Open-source input methods such as Rime Squirrel and McBopomofo show that candidate layout is an independent product layer, not only an input engine concern.
- fcitx5-style candidate abstractions are useful because they separate candidate text, comments, actions, and expanded panels.

Therefore the first Mac frontend keeps the system IME shell minimal and puts the RAG-specific experience in `RagCandidatePanel`.

The production macOS frontend should move to Squirrel/Rime instead of growing this prototype into a full Chinese input engine. Rime should own raw pinyin parsing, schemes, dictionaries, spelling correction, candidate paging, labels, and comments. The local LLM and RAG/memory layer should only add side candidates after Rime has produced structured context.

See `docs/rime-squirrel-framework-decision.md` for the accepted framework route.

Official `rime/weasel` should remain the composition-engine reference, while Wisdom-Weasel is the LLM-prediction reference:

```text
rime/weasel:
  key event -> librime session -> Context / CandidateInfo -> candidate UI

Wisdom-Weasel:
  commit/recent context -> async LLM provider -> extra candidates -> candidate UI

RAG-IME:
  composition event -> RAG/memory candidate source -> model candidate source
  -> unified InputSuggestion payload -> compact native panel
```

The macOS implementation should keep this separation. RAG suggestions should not be hard-wired into the key event loop or panel drawing code; they should be one candidate source behind the same adapter contract.

After the framework decision, the hard rule is:

```text
raw key stream / noisy pinyin
  -> Rime/Squirrel composition first
  -> structured Rime candidates and constraints
  -> LLM rerank / continuation and RAG/memory side candidates
```

The LLM must not be asked to freely decode dirty raw pinyin. It can use committed context, Rime candidates, and explicit pinyin constraints, but it is not the spelling engine.

References used for this adapter:

- Apple InputMethodKit: <https://developer.apple.com/documentation/inputmethodkit>
- macOS IMKit Swift sample: <https://github.com/ensan-hcl/macOS_IMKitSample_2021>
- Rime Weasel: <https://github.com/rime/weasel>
- Rime Squirrel: <https://github.com/rime/squirrel>
- McBopomofo CandidateUI: <https://github.com/openvanilla/McBopomofo>
- fcitx5-macos: <https://github.com/fcitx-contrib/fcitx5-macos>

## Implemented Files

```text
macos/RagImeMac/Info.plist
macos/RagImeMac/Sources/RagImeMacApp.swift
macos/RagImeMac/Sources/RagInputController.swift
macos/RagImeMac/Sources/RagCandidatePanel.swift
macos/RagImeMac/Sources/RagBridgeClient.swift
macos/RagImeMac/Sources/RagModels.swift
rag_ime/payloads.py
scripts/build_macos_frontend.sh
scripts/install_macos_frontend.sh
```

## Runtime Flow

```text
key input
  -> RagInputController.inputText
  -> marked text update
  -> async RagBridgeClient.suggest
  -> python3 -m rag_ime.cli suggest-json
  -> optional local model prediction provider
  -> LocalSqliteCoreClient SQLite/FTS5 retrieval or shared-core JSON command
  -> modelPredictions + InputSuggestion JSON
  -> RagCandidatePanel NSPanel
  -> number key or click candidate
  -> insertText
  -> side selection feedback
  -> commit event and optional accepted action recorded locally
```

The bridge uses the same local backend as the CLI MVP. It does not call GPT, Claude, or any cloud service by default. The optional model lane only runs when `RAG_IME_PREDICTOR_*` points at a local or user-owned OpenAI-compatible endpoint.

For the Squirrel/Rime path, side selection feedback should use the unified `/rime-select` contract. It records the inserted side candidate and, for RAG candidates, the accepted memory action in one local request. The prototype AppKit harness may still issue separate action/commit calls while it remains a debug surface.

## UI Shape

Default native view:

```text
RAG      SQLite 和 FTS5 第一版          3
1 本地记忆   2 输入法候选   3 RAG上下文
4 先用 FTS5 证明召回收益
5 第一步先验证 FTS5...
6 默认本地完成, 不上传个人输入历史

RAG · input_event:4
先用 FTS5 证明召回收益 | context: ...
```

Design rules:

- short candidate rows stay fast and number-selectable;
- the native IME panel stays small: short LLM predictions share one inline row when possible, while RAG/memory snippets use compact block rows;
- model predictions and RAG suggestions share the same number-key sequence;
- do not show pipeline status, model names, debug JSON, confidence scores, or governance buttons in the IME panel;
- governance actions and full pipeline detail belong in `debug/` or a future preferences/debug window;
- full evidence expansion should avoid focus-stealing modal behavior inside the input method process;
- the panel is a translucent AppKit `NSPanel`, so it can later be replaced by WebView without changing the backend contract.

## Build And Preview

Build the `.app` bundle with Command Line Tools:

```bash
scripts/build_macos_frontend.sh
```

This writes a real runtime config into:

```text
build/RagImeMac.app/Contents/Resources/bridge-config.json
```

Inspect the runtime config used by the app:

```bash
build/RagImeMac.app/Contents/MacOS/RagImeMac --print-config
```

Run the Swift-to-Python preview contract:

```bash
build/RagImeMac.app/Contents/MacOS/RagImeMac --preview-json
```

This initializes the local DB, seeds deterministic demo memories, calls `suggest-json`, and prints the native frontend JSON payload.

Run the Swift-to-Python Rime/Squirrel side-candidate preview:

```bash
build/RagImeMac.app/Contents/MacOS/RagImeMac --preview-rime-sidecar-json
```

This initializes the local DB, seeds deterministic demo memories, calls `rime-suggest-json`, and verifies that Swift can decode the merged `displayCandidates` payload. The preview intentionally includes dirty raw pinyin plus Rime candidates; the response should use `queryBasis: "rimeCandidates"` instead of asking the model to decode raw input.

Open the native panel preview:

```bash
build/RagImeMac.app/Contents/MacOS/RagImeMac --preview-panel
```

This uses the same seeded backend and shows the actual AppKit candidate/evidence panel for six seconds.

Install locally:

```bash
scripts/install_macos_frontend.sh
```

The installer copies the app to `~/Library/Input Methods/RagImeMac.app` and syncs the bridge config to:

```text
~/Library/Application Support/RagImeMac/bridge-config.json
```

If an older user config exists, the installer saves `bridge-config.json.bak` before replacing it. The user config lets the installed input method find this repository, the SQLite DB, and the Python executable without relying on shell working directory or interactive environment variables.

Then open:

```text
System Settings -> Keyboard -> Input Sources
```

Add `RAG IME` manually. If macOS does not refresh input methods immediately, kill the old `RagImeMac` process or log out/in.

## Sidecar LaunchAgent

Patched Squirrel should call the long-running HTTP sidecar through `rag_ime/sidecar_url` instead of spawning Python for every candidate refresh. Start it manually while debugging:

```bash
python3 -m rag_ime.cli sidecar-server --host 127.0.0.1 --port 8766
```

For normal local use, install the user LaunchAgent:

```bash
scripts/install_sidecar_launch_agent.sh
```

This writes:

```text
~/Library/LaunchAgents/com.rag-ime.sidecar.plist
~/Library/Logs/RagIme/sidecar.out.log
~/Library/Logs/RagIme/sidecar.err.log
~/Library/Application Support/RagIme/app/
~/Library/Application Support/RagIme/rag-ime.sqlite
```

The installer copies the sidecar runtime package into the user Application Support directory and points launchd at that local copy. This avoids a macOS beta launchd/Python startup failure observed when the service tried to import code directly from an external-volume repository path. Override `RAG_IME_DB_PATH` if you intentionally want the sidecar to use another database.

The installer is configurable with:

```text
RAG_IME_PYTHON
RAG_IME_APP_SUPPORT_DIR
RAG_IME_DB_PATH
RAG_IME_PROJECT
RAG_IME_SIDECAR_HOST
RAG_IME_SIDECAR_PORT
RAG_IME_CORE_MODE
RAG_MEMORY_CORE_COMMAND
RAG_IME_SIDECAR_NO_SEED
```

It also persists a whitelist of runtime tuning variables into the LaunchAgent
plist when they are present in the installer environment. This matters for the
actual Squirrel path because launchd does not inherit your interactive shell
exports after login.

```bash
export RAG_IME_PREDICTOR_PROVIDER=ollama
export RAG_IME_PREDICTOR_BASE_URL=http://127.0.0.1:11434
export RAG_IME_PREDICTOR_MODEL=qwen3.5:0.8b-mlx
export RAG_IME_PREDICTOR_PROFILE=instant
export RAG_IME_PREDICTOR_STREAM_FIRST=1
export RAG_IME_HISTORY_CONTEXT_EVENTS=6
scripts/install_sidecar_launch_agent.sh
```

Whitelisted variables include `RAG_IME_PREDICTOR_*`,
`RAG_IME_HISTORY_CONTEXT_*`, `RAG_IME_RIME_CACHE_TTL_MS`, and
`RAG_IME_SUGGESTION_CACHE_SIZE`.

### Text-Only MLX Model Lane

For the active input-method model lane, prefer text-only MLX-LM models over
Qwen3.5 VLM models. If Hugging Face is reachable, a direct text-generation MLX
folder such as `mlx-community/Qwen3.5-0.8B-OptiQ-4bit` is the cleanest route.
On this Mac, HF download was blocked from the shell, so the current verified
route derives a text-only local directory from the already downloaded
Qwen3.5 MLX-VLM package by keeping only `language_model.*` weights.

Install the Python runtime with proxy variables unset and a repo-local pip
cache:

```bash
scripts/setup_mlx_predictor_env.sh
```

Derive the local text-only Qwen3.5 directory:

```bash
.venv-mlx314sys/bin/python scripts/derive_text_mlx_model.py \
  --source-dir "/Volumes/undo 4t/models/mlx-community-Qwen3.5-0.8B-4bit" \
  --target-dir "/Volumes/undo 4t/models/mlx-community-Qwen3.5-0.8B-text-4bit-local" \
  --overwrite
```

Then install the resident MLX predictor LaunchAgent:

```bash
RAG_IME_MLX_PYTHON="$PWD/.venv-mlx314sys/bin/python" \
RAG_IME_MLX_MODEL="/Volumes/undo 4t/models/mlx-community-Qwen3.5-0.8B-text-4bit-local" \
scripts/install_mlx_predictor_launch_agent.sh
```

Finally point the RAG/Rime sidecar at the MLX service:

```bash
RAG_IME_PREDICTOR_PROVIDER=mlx \
RAG_IME_PREDICTOR_BASE_URL=http://127.0.0.1:8767 \
RAG_IME_PREDICTOR_MODEL="/Volumes/undo 4t/models/mlx-community-Qwen3.5-0.8B-text-4bit-local" \
RAG_IME_PREDICTOR_PROFILE=instant \
RAG_IME_PREDICTOR_STREAM_FIRST=0 \
RAG_IME_PREDICTOR_TIMEOUT_MS=350 \
RAG_IME_HISTORY_CONTEXT_EVENTS=6 \
scripts/install_sidecar_launch_agent.sh
```

The MLX predictor LaunchAgent clears common proxy environment variables so the
first Hugging Face model download does not accidentally use a shell proxy.
Set `RAG_IME_HF_HOME` to an external-drive cache path if you do not want model
weights under the default Hugging Face cache.
The current local derived directory reports `textOnly=true`, `hasVisionConfig=false`,
and about 424 MB of safetensors weights through `/health`.

Dry-run without loading launchd:

```bash
RAG_IME_LAUNCH_AGENT_DRY_RUN=1 scripts/install_sidecar_launch_agent.sh
```

Uninstall:

```bash
scripts/uninstall_sidecar_launch_agent.sh
```

Check the current Squirrel/sidecar state:

```bash
scripts/doctor_squirrel_integration.sh
```

Before switching to a patched Squirrel input source for real typing, use the
strict readiness gate:

```bash
RAG_IME_DOCTOR_REQUIRE_TRYOUT=1 scripts/doctor_squirrel_integration.sh
```

This requires a prepared patched Squirrel checkout, `xcodebuild -list` support
for `Squirrel.xcodeproj`, and a healthy sidecar path that can handle health,
suggest, and select/writeback requests.

Check the full Xcode requirement:

```bash
scripts/setup_xcode_for_squirrel.sh
```

On macOS beta hosts, prefer installing the matching beta Xcode with `xcodes` to an external disk, then export `DEVELOPER_DIR` or run the setup script with `RAG_IME_USE_SUDO=1`. See `docs/xcode-squirrel-setup.md`.

## Prepare Patched Squirrel

Prepare a disposable Squirrel checkout with the RAG-IME patch applied:

```bash
scripts/prepare_squirrel_workspace.sh
```

The script checks out Squirrel `2158538`, applies `squirrel-patches/0001-add-rag-ime-sidecar.patch`, runs lightweight checks, and writes:

```text
/tmp/rag-ime-squirrel/rag-ime.squirrel.custom.yaml
```

The generated config points `rag_ime/sidecar_url` at the default LaunchAgent URL:

```text
http://127.0.0.1:8766/api
```

Inspect, build, and install the patched checkout with full Xcode:

```bash
scripts/build_patched_squirrel.sh list
scripts/build_patched_squirrel.sh
scripts/build_patched_squirrel.sh install
```

The install action copies `Squirrel.app` into `~/Library/Input Methods` by
default, ad-hoc signs the copied bundle for local Text Input Services
registration, and writes the managed RAG-IME patch block into:

```text
~/Library/Rime/squirrel.custom.yaml
```

It also runs `scripts/bootstrap_squirrel_user_data.sh`. This matters because a
Squirrel bundle can be registered and visible in System Settings while the user
Rime directory still has no compiled schema data. The bootstrap step copies
bundled Rime data and Plum output into `~/Library/Rime`, runs `Squirrel --build`
and `--reload` there, and verifies the expected `build/` artifacts before the
first typing test.

Use `RAG_IME_SQUIRREL_INSTALL_DIR="/Library/Input Methods"` only when a
machine-wide install is required.

The strict doctor verifies that the installed macOS input source
`im.rime.inputmethod.Squirrel.Hans` is registered, enabled, and selectable. That
is the TIS registration check. For the state visible in System Settings, require
the current user's HIToolbox enabled-source list as well:

```bash
RAG_IME_REQUIRE_HITOOLBOX_ENABLED=1 \
  scripts/check_macos_input_source.sh im.rime.inputmethod.Squirrel.Hans
```

If this reports `hitoolboxEnabled=false`, the bundle is registered but not in
all user input-source preference lists macOS uses. For a local debug machine,
run:

```bash
scripts/enable_squirrel_hitoolbox_input_source.sh
```

The helper creates Desktop backups of `com.apple.HIToolbox` and
`com.apple.inputsources`, tries to add Squirrel's bundle/mode entries to both,
restarts `cfprefsd`, and re-registers the source. Prefer the normal System
Settings "+" flow for a distributable product; on macOS 27 the
`com.apple.inputsources` third-party list may still require that UI route. If
the check prints `thirdPartyEnabled=false`, add Squirrel from System Settings.

The active selected source still needs to be changed from the macOS input menu
before the real continuous typing test. Use the settings helper or add gate
first, then the selected source gate after switching from the input menu:

```bash
scripts/open_squirrel_input_source_settings.sh --wait
# or, if System Settings is already open:
scripts/wait_squirrel_input_source_added.sh
scripts/wait_squirrel_typing_ready.sh
```

## Environment

The app reads these optional environment variables:

```text
RAG_IME_REPO_ROOT
RAG_IME_DB_PATH
RAG_IME_PYTHON
RAG_IME_PROJECT
RAG_IME_TOP_K
RAG_IME_PREDICTOR_PROVIDER
RAG_IME_PREDICTOR_BASE_URL
RAG_IME_PREDICTOR_MODEL
RAG_IME_PREDICTOR_API_KEY
RAG_IME_PREDICTOR_PROMPT_MODE
RAG_IME_PREDICTOR_TIMEOUT_MS
RAG_IME_PREDICTOR_MAX_TOKENS
RAG_IME_PREDICTOR_TEMPERATURE
RAG_IME_PREDICTOR_TOP_P
RAG_IME_HISTORY_CONTEXT_EVENTS
RAG_IME_HISTORY_CONTEXT_CHARS
```

Runtime config precedence:

```text
environment variables
  -> ~/Library/Application Support/RagImeMac/bridge-config.json
  -> app bundle Resources/bridge-config.json
  -> Info.plist defaults
  -> process current working directory fallback
```

Default development values:

```text
repoRoot: current working directory
dbPath: .rag-ime-data/rag-ime.sqlite
pythonExecutable: /usr/bin/python3
project: wisdom-weasel-rag-ime
topK: 5
```

For a real installed input method, `bridge-config.json` should point to this repository checkout until the Python backend is packaged into a standalone daemon or bundle resource.

Model prediction is disabled unless all required provider variables are set. A local small model server can be tested with:

```text
RAG_IME_PREDICTOR_PROVIDER=openai-compatible
RAG_IME_PREDICTOR_BASE_URL=http://127.0.0.1:8000
RAG_IME_PREDICTOR_MODEL=Qwen3-0.6B
RAG_IME_PREDICTOR_PROMPT_MODE=chat
RAG_IME_PREDICTOR_TIMEOUT_MS=800
RAG_IME_PREDICTOR_MAX_TOKENS=12
RAG_IME_HISTORY_CONTEXT_EVENTS=6
RAG_IME_HISTORY_CONTEXT_CHARS=420
```

The history context variables control how many committed input events are merged into prediction context. Set `RAG_IME_HISTORY_CONTEXT_EVENTS=0` when debugging current-input-only model behavior.

Set `RAG_IME_PREDICTOR_PROMPT_MODE=completion` when testing a local base model or llama.cpp-compatible `/v1/completions` endpoint. That path is closer to Wisdom-Weasel's base-model prefix completion route than chat prompting, while the production IME still keeps Rime responsible for raw pinyin parsing.

## Current Limitations

- This is a frontend adapter MVP, not a full Chinese input engine.
- It handles simple printable composition, number-key candidate selection, return-to-commit, and escape-to-cancel.
- It does not embed Rime/Squirrel yet; this is acceptable only for the prototype/debug phase.
- It does not ship a packaged Python runtime yet; installed development builds read `bridge-config.json` to find the repo checkout and Python executable.
- Candidate panel positioning now prefers the active `IMKTextInput` caret rectangle and falls back to mouse location when the target app does not expose a valid text rect.
- `expand` copies full evidence to clipboard instead of opening a rich source browser.
- The optional local model provider can either ask for several candidates in one complete response or, with `RAG_IME_PREDICTOR_STREAM_FIRST=1`, return the first parsed streaming candidate for the side lane. llama.cpp-style batch sampling and KV cache reuse are still future optimization work.
- The Squirrel patch debounces sidecar refreshes and fingerprints request state so stale model/RAG results cannot overwrite a newer Rime page.
- The sidecar merge policy lets model/RAG lanes fill the visible 1-8 slots first; Rime candidates remain deterministic fallback rows.
- The local HTTP sidecar caches repeated equivalent `/rime-suggest` payloads for a short TTL and reports `cache.hit` in debug payloads.
- Accepted side candidates write back through `/rime-select`, so Swift does not need to duplicate commit/action governance rules.

## Next Engineering Steps

1. Keep the current InputMethodKit adapter as the JSON contract and debug harness.
2. Start a Squirrel/Rime integration branch and verify a clean local Squirrel build/install.
3. Insert the side candidate request after `rimeAPI.get_context()` has produced preedit, candidates, labels, comments, and page state.
4. Merge RAG/model candidates into the panel as side candidates without blocking normal Rime key handling.
5. Preserve Wisdom-Weasel's production lessons: async prediction, stale-result guard, local provider, side-candidate selection branch, context history, and pinyin constraints only when explicit.
6. Optimize Wisdom-Weasel-style local prediction beyond the current OpenAI-compatible provider: llama.cpp batch sampling with KV reuse if latency requires it.
