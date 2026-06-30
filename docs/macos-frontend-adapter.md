# macOS Frontend Adapter

## Research Conclusion

The macOS MVP should use a two-layer frontend:

```text
InputMethodKit shell
  -> RagBridgeClient JSON command
  -> Python LocalSqliteCoreClient
  -> custom NSPanel candidate/evidence UI
```

This is more suitable than using only `IMKCandidates`.

- Apple `InputMethodKit` provides the system input method process, `IMKServer`, `IMKInputController`, marked text, committed text, and basic candidate windows.
- `IMKCandidates` supports simple candidates and annotations, but RAG needs action-rich evidence cards: pin, downrank, delete, expand, confidence, memory id, and source preview.
- Open-source input methods such as Rime Squirrel and McBopomofo show that candidate layout is an independent product layer, not only an input engine concern.
- fcitx5-style candidate abstractions are useful because they separate candidate text, comments, actions, and expanded panels.

Therefore the first Mac frontend keeps the system IME shell minimal and puts the RAG-specific experience in `RagCandidatePanel`.

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
  -> action-json accepted
  -> commit event recorded locally
```

The bridge uses the same local backend as the CLI MVP. It does not call GPT, Claude, or any cloud service by default. The optional model lane only runs when `RAG_IME_PREDICTOR_*` points at a local or user-owned OpenAI-compatible endpoint.

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
- the native IME panel stays small: at most one model-prediction row, three RAG rows, and one evidence hint;
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

Run the Swift-to-Python preview contract:

```bash
build/RagImeMac.app/Contents/MacOS/RagImeMac --preview-json
```

This initializes the local DB, seeds deterministic demo memories, calls `suggest-json`, and prints the native frontend JSON payload.

Open the native panel preview:

```bash
build/RagImeMac.app/Contents/MacOS/RagImeMac --preview-panel
```

This uses the same seeded backend and shows the actual AppKit candidate/evidence panel for six seconds.

Install locally:

```bash
scripts/install_macos_frontend.sh
```

Then open:

```text
System Settings -> Keyboard -> Input Sources
```

Add `RAG IME` manually. If macOS does not refresh input methods immediately, kill the old `RagImeMac` process or log out/in.

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
RAG_IME_PREDICTOR_TIMEOUT_MS
RAG_IME_PREDICTOR_MAX_TOKENS
RAG_IME_PREDICTOR_TEMPERATURE
RAG_IME_PREDICTOR_TOP_P
RAG_IME_HISTORY_CONTEXT_EVENTS
RAG_IME_HISTORY_CONTEXT_CHARS
```

Default development values:

```text
repoRoot: current working directory
dbPath: .rag-ime-data/rag-ime.sqlite
pythonExecutable: /usr/bin/python3
project: wisdom-weasel-rag-ime
topK: 5
```

For a real installed input method, `RAG_IME_REPO_ROOT` should point to this repository checkout until the Python backend is packaged into a standalone daemon or bundle resource.

Model prediction is disabled unless all required provider variables are set. A local small model server can be tested with:

```text
RAG_IME_PREDICTOR_PROVIDER=openai-compatible
RAG_IME_PREDICTOR_BASE_URL=http://127.0.0.1:8000
RAG_IME_PREDICTOR_MODEL=Qwen3-0.6B
RAG_IME_PREDICTOR_TIMEOUT_MS=800
RAG_IME_PREDICTOR_MAX_TOKENS=12
RAG_IME_HISTORY_CONTEXT_EVENTS=6
RAG_IME_HISTORY_CONTEXT_CHARS=420
```

The history context variables control how many committed input events are merged into prediction context. Set `RAG_IME_HISTORY_CONTEXT_EVENTS=0` when debugging current-input-only model behavior.

## Current Limitations

- This is a frontend adapter MVP, not a full Chinese input engine.
- It handles simple printable composition, number-key candidate selection, return-to-commit, and escape-to-cancel.
- It does not embed Rime/Squirrel yet.
- It does not ship a packaged Python runtime yet.
- Candidate panel positioning currently uses mouse location as a practical fallback; the next version should anchor to the client caret rectangle when available.
- `expand` copies full evidence to clipboard instead of opening a rich source browser.
- The optional local model provider asks for several candidates in one non-streaming response; llama.cpp-style batch sampling and KV cache reuse are still future optimization work.

## Next Engineering Steps

1. Add caret-anchored panel positioning from the active `IMKTextInput` client when the target app supports document access.
2. Package the Python backend or replace it with a small local daemon so installed input methods do not depend on shell working directory.
3. Add a preferences window for DB path, recording toggle, app blacklist, and panel theme.
4. Integrate with Squirrel/Rime for mature Chinese composition while keeping RAG suggestions as a side candidate source.
5. Add a WebView evidence browser for paragraph-level source inspection.
6. Optimize Wisdom-Weasel-style local prediction beyond the current OpenAI-compatible provider: llama.cpp batch sampling with KV reuse if latency requires it.
