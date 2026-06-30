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
- macOS InputMethodKit frontend adapter prototype;
- Rime/Squirrel production frontend integration plan;
- optional local OpenAI-compatible model prediction lane;
- history-input context for local model prediction;
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

The production macOS frontend should not remain a custom pinyin engine. The accepted framework route is Rime/Squirrel:

```text
Squirrel / InputMethodKit
  -> librime handles raw key input, schemes, dictionaries, spelling, paging
  -> Rime candidates + labels + comments
  -> RAG-IME side candidates from local model and local memory
  -> compact shared candidate panel
```

The current InputMethodKit app is kept as the fast prototype and debug harness. See `docs/rime-squirrel-framework-decision.md` for the framework decision.

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

Run the lightweight HTTP sidecar for patched Squirrel:

```bash
python3 -m rag_ime.cli sidecar-server --host 127.0.0.1 --port 8766
```

The sidecar uses a short `/rime-suggest` cache to absorb repeated equivalent Squirrel refreshes:

```bash
export RAG_IME_RIME_CACHE_TTL_MS=400
```

Set it to `0` while debugging cache behavior.

Install it as a user LaunchAgent so it starts at login:

```bash
scripts/install_sidecar_launch_agent.sh
```

Remove the LaunchAgent:

```bash
scripts/uninstall_sidecar_launch_agent.sh
```

Check the Squirrel/sidecar integration state:

```bash
scripts/doctor_squirrel_integration.sh
```

Check and configure the full Xcode requirement for patched Squirrel:

```bash
scripts/setup_xcode_for_squirrel.sh
```

See `docs/xcode-squirrel-setup.md` for the external-disk install route and the `DEVELOPER_DIR`/`xcode-select` commands.

Show memory action effects:

```bash
python3 -m rag_ime.cli action-demo
```

Build the Agent first-run memory block:

```bash
python3 -m rag_ime.cli agent-hook --top-k 3
```

Preview and import local Codex history for memory/RAG evaluation:

```bash
python3 -m rag_ime.cli import-codex-history \
  --path "$HOME/.codex/session_index.jsonl" \
  --dry-run \
  --limit 20
```

Evaluate retrieval quality against explicit cases:

```bash
python3 -m rag_ime.cli --db-path .rag-ime-data/rag-ime.sqlite \
  eval-codex-history \
  --cases-file docs/eval/codex-history-cases.example.jsonl \
  --top-k 5
```

See `docs/codex-history-eval.md`.

Inspect trigger policy:

```bash
python3 -m rag_ime.cli trigger-demo "这个项目" --idle-ms 300
```

Use a local OpenAI-compatible small model for the short prediction lane:

```bash
export RAG_IME_PREDICTOR_PROVIDER=openai-compatible
export RAG_IME_PREDICTOR_BASE_URL=http://127.0.0.1:8000
export RAG_IME_PREDICTOR_MODEL=Qwen3-0.6B
export RAG_IME_PREDICTOR_TIMEOUT_MS=800
export RAG_IME_PREDICTOR_MAX_TOKENS=12
export RAG_IME_PREDICTOR_EXTRA_BODY_JSON='{"seed":7,"chat_template_kwargs":{"enable_thinking":false}}'
export RAG_IME_HISTORY_CONTEXT_EVENTS=6
export RAG_IME_HISTORY_CONTEXT_CHARS=420

python3 -m rag_ime.cli suggest-json "输入法 个人记忆" --recent-context "local-first RAG" --top-k 3
```

`suggest-json` merges the explicit `--recent-context` with recent committed input history before calling the local model. Set `RAG_IME_HISTORY_CONTEXT_EVENTS=0` to disable this history lane.

Benchmark local model prediction latency before using it in the input-method lane:

```bash
python3 -m rag_ime.cli predict-benchmark \
  --case "RAG 输入法" \
  --case "Squirrel 候选" \
  --recent-context "用户正在写本地记忆和候选预测" \
  --latency-budget-ms 150
```

Build the macOS frontend adapter:

```bash
scripts/build_macos_frontend.sh
```

Inspect the runtime bridge config:

```bash
build/RagImeMac.app/Contents/MacOS/RagImeMac --print-config
```

Verify the Swift frontend can call the Python RAG backend:

```bash
build/RagImeMac.app/Contents/MacOS/RagImeMac --preview-json
```

Verify the Swift frontend can call and decode the Squirrel/Rime side-candidate contract:

```bash
build/RagImeMac.app/Contents/MacOS/RagImeMac --preview-rime-sidecar-json
```

Prepare a patched Squirrel checkout:

```bash
scripts/prepare_squirrel_workspace.sh
```

This creates `/tmp/rag-ime-squirrel`, applies the Squirrel patch, runs local checks, and writes `rag-ime.squirrel.custom.yaml` with the `rag_ime` config block to copy into Squirrel's `squirrel.yaml`.

Preview the Squirrel/Rime side-candidate contract:

```bash
cat > /tmp/rime-sidecar-request.json <<'JSON'
{
  "sessionId": "squirrel-demo",
  "requestSeq": 1,
  "rawInput": "ragshurufa",
  "preedit": "ragshurufa",
  "committedContext": "正在设计 RAG 输入法",
  "maxVisibleCandidates": 6,
  "maxSideCandidates": 3,
  "rimeContext": {
    "candidates": [
      {"label": "1", "text": "RAG 输入法", "comment": "rime"},
      {"label": "2", "text": "RAG 是", "comment": "rime"}
    ],
    "highlightedIndex": 0,
    "page": 0,
    "isLastPage": true
  }
}
JSON

python3 -m rag_ime.cli --core-mode fixture rime-suggest-json \
  --payload-file /tmp/rime-sidecar-request.json
```

This command keeps Rime candidates first, appends model/RAG side candidates only if visible slots remain, reserves side slots for RAG/memory after at most one model prediction, and uses Rime candidates or commit preview as the semantic query instead of asking the model to decode raw pinyin.

Open the native AppKit candidate panel preview:

```bash
build/RagImeMac.app/Contents/MacOS/RagImeMac --preview-panel
```

Install the local input method app:

```bash
scripts/install_macos_frontend.sh
```

The installer writes a user-level bridge config at `~/Library/Application Support/RagImeMac/bridge-config.json` so the installed input method can find this checkout, the local SQLite DB, and the Python executable.

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
- Squirrel/Rime-aware side-candidate JSON contract;
- Swift bridge models and preview command for the Rime side-candidate contract;
- Squirrel patch pack for a fail-closed Rime sidecar frontend integration with HTTP sidecar and side-candidate commit/action recording;
- optional local OpenAI-compatible model prediction lane;
- bounded history-input context for model/RAG prediction;
- shared number-key selection for top model predictions and lower RAG/memory candidates;
- three realistic UI scenarios;
- unittest and acceptance script.

Not implemented in this repo by design:

- vector recall;
- PI runtime integration.

The local SQLite client is still the easiest Mac MVP backend. The shared RAG/memory core can now be selected through `--core-mode json` when the PI memory extension checkout is available.

## macOS Frontend Route

Implemented prototype route:

1. Keep this CLI adapter as the product contract and test harness.
2. Add `suggest-json` and `action-json` as the native frontend protocol.
3. Build a macOS InputMethodKit prototype that captures committed text and calls:
   - `record_event` after commit;
   - `suggest_for_input` while preedit/current context changes;
   - `apply_action` when the user accepts, pins, downranks, or deletes a suggestion.
4. Render a normal candidate bar for short suggestions.
5. Render compact model predictions above RAG/memory candidates, using one shared number-key sequence.
6. Render evidence preview in an expanded panel or WebView-style overlay.

Production route:

1. Base the real macOS IME on Squirrel/Rime rather than extending the prototype into a full pinyin engine.
2. Preserve Rime schemes, dictionaries, spelling correction, paging, labels, and comments.
3. Add RAG/model candidates after librime has produced structured composition state.
4. Follow Wisdom-Weasel's proven constraints: async prediction, stale-result guard, side-candidate merge, local provider, and pinyin constraints only when supplied by the engine.
5. Keep the current InputMethodKit prototype as the debug/contract harness while the Squirrel integration is developed.

See `docs/interview-project-difficulties.md` for the Chinese interview material that records the project difficulties and engineering choices.

See `docs/macos-frontend-adapter.md` for the macOS frontend research and implementation notes.

See `docs/rime-squirrel-framework-decision.md` for the accepted Rime/Squirrel framework route.

See `squirrel-patches/README.md` for the patch-pack base commit, config keys, and validation commands.

See `docs/wisdom-weasel-issues-map.md` for the Wisdom-Weasel open-issues compatibility map.
