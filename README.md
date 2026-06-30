# Wisdom-Weasel RAG IME

Local-first RAG input method MVP inspired by Wisdom-Weasel.

This repository is a standalone product repo, not a fork/PR branch of `scukeqi/Wisdom-Weasel`.
Wisdom-Weasel remains an upstream reference for the existing LLM input method flow.

## Current Boundary

The RAG/memory layer is being extracted into a shared core so PI and this input method do not build duplicate databases or ranking logic.

This repo should focus on:

- input-method adapter contracts;
- committed input event capture;
- local SQLite/FTS5 MVP backend until the shared core exposes stable write/action APIs;
- short candidate generation from shared-core retrieval results;
- evidence preview / expanded evidence UI prototype;
- pin / downrank / delete action wiring;
- Agent first-run context hook;
- macOS InputMethodKit frontend adapter;
- Mac-local acceptance scenarios.

This repo should not duplicate:

- SQLite memory store;
- FTS5 index implementation;
- accepted/skipped/pinned/downranked/delete governance state;
- PI-specific runtime/tool registration;
- cloud GPT/Claude default prediction;
- model fine-tuning.

See `docs/shared-core-adapter-contract.md` for the shared-core requirements.

## Privacy Defaults

- Personal input history stays local by default.
- Generated SQLite databases, traces, and reports are ignored by Git.
- Cloud model calls are not part of the default prediction chain.
- Fine-tuning is out of scope for the Mac MVP.

## Planned Runtime Shape

```text
macOS InputMethodKit adapter / CLI prototype
  -> Swift RagBridgeClient JSON command
  -> LocalSqliteCoreClient or shared rag-memory core API/JSON CLI
  -> SQLite/FTS5 personal memory
  -> RetrievedMemory[]
  -> InputSuggestion[]
  -> short candidate list + evidence preview
  -> user action
  -> shared core governance action
```

## Current Commands

Initialize the local SQLite/FTS5 database:

```bash
python3 -m rag_ime.cli init-db
```

Seed deterministic demo memories:

```bash
python3 -m rag_ime.cli seed-demo --reset
```

Record a committed input event:

```bash
python3 -m rag_ime.cli commit "默认本地完成, 不上传个人输入历史" \
  --recent-context "隐私边界" \
  --tag privacy
```

Run the adapter tests:

```bash
python3 -m unittest discover -s tests
```

Render the three UI scenarios:

```bash
python3 -m rag_ime.cli demo --top-k 3
```

Run deterministic adapter acceptance:

```bash
python3 scripts/acceptance.py
```

Run the browser debug surface:

```bash
python3 -m rag_ime.cli seed-demo --reset
python3 -m rag_ime.cli debug-server
```

Then open:

```text
http://127.0.0.1:8765/
```

Show memory action effects:

```bash
python3 -m rag_ime.cli action-demo
```

Build the Agent first-run memory block:

```bash
python3 -m rag_ime.cli agent-hook --top-k 3
```

Inspect trigger policy:

```bash
python3 -m rag_ime.cli trigger-demo "这个项目" --idle-ms 300
```

Build the macOS frontend adapter:

```bash
scripts/build_macos_frontend.sh
```

Verify the Swift frontend can call the Python RAG backend:

```bash
build/RagImeMac.app/Contents/MacOS/RagImeMac --preview-json
```

Open the native AppKit candidate panel preview:

```bash
build/RagImeMac.app/Contents/MacOS/RagImeMac --preview-panel
```

Install the local input method app:

```bash
scripts/install_macos_frontend.sh
```

Use the shared-core JSON command from `pi-rag-memory-extension`:

```bash
python3 -m rag_ime.cli --core-mode json \
  --core-command "node --experimental-strip-types /path/to/pi-rag-memory-extension/scripts/ime-json-core.mjs --cwd /path/to/workspace --namespace wisdom-weasel-ime --db-path /path/to/session-history.sqlite" \
  suggest-json "输入法 个人记忆" --recent-context "local-first RAG" --top-k 3
```

Run the browser debug surface against the same shared core:

```bash
python3 -m rag_ime.cli --core-mode json \
  --core-command "node --experimental-strip-types /path/to/pi-rag-memory-extension/scripts/ime-json-core.mjs --cwd /path/to/workspace --namespace wisdom-weasel-ime --db-path /path/to/session-history.sqlite" \
  debug-server --no-seed
```

## Current Status

Implemented in this repo:

- adapter data models;
- shared-core client boundary;
- local SQLite/FTS5 CoreClient;
- committed input event recording;
- durable memory actions for accepted/skipped/pin/downrank/delete/restore;
- SuggestionCompiler for `RetrievedMemory -> InputSuggestion`;
- conservative RAG refresh trigger policy;
- fixture core for adapter/UI unit tests only;
- short candidate rendering;
- evidence preview and expanded evidence panel text;
- pin/downrank/delete action wiring;
- Agent first-run hook wrapper;
- macOS InputMethodKit shell;
- AppKit `NSPanel` candidate/evidence overlay;
- Swift-to-Python JSON bridge;
- browser debug page with the same local backend contract;
- shared-core JSON command integration for CLI/debug-server;
- three realistic UI scenarios;
- unittest and acceptance script.

Not implemented in this repo by design:

- vector recall;
- PI runtime integration.

The local SQLite client is still the easiest Mac MVP backend. The shared RAG/memory core can now be selected through `--core-mode json` when the PI memory extension checkout is available.

## macOS Frontend Route

Implemented route:

1. Keep this CLI adapter as the product contract and test harness.
2. Add `suggest-json` and `action-json` as the native frontend protocol.
3. Build a macOS InputMethodKit prototype that captures committed text and calls:
   - `record_event` after commit;
   - `suggest_for_input` while preedit/current context changes;
   - `apply_action` when the user accepts, pins, downranks, or deletes a suggestion.
4. Render a normal candidate bar for short suggestions.
5. Render evidence preview in an expanded panel or WebView-style overlay.

Next route:

1. Package the Python backend or replace it with a local daemon.
2. Anchor the panel to the target app caret instead of mouse-position fallback.
3. Port the compact debug overlay behavior into `RagCandidatePanel`.
4. Keep Rime/Squirrel/Wisdom-Weasel integration as the next bridge after the adapter contract is stable.

See `docs/macos-frontend-adapter.md` for the macOS frontend research and implementation notes.
