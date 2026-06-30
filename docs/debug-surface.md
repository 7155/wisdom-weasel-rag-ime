# Debug Surface

## Goal

`debug/` is the browser test surface for inspecting the backend pipeline and candidate payloads.

It is not the product input method UI. The real input method UI is the native macOS `InputMethodKit` + AppKit panel under `macos/RagImeMac/`.

It is intentionally small:

- no build step;
- no frontend framework dependency;
- no cloud API;
- same local adapter contract as the Python CLI and Swift preview.

Run it with:

```bash
python3 -m rag_ime.cli seed-demo --reset
python3 -m rag_ime.cli debug-server
```

Tune or disable the short `/rime-suggest` cache:

```bash
RAG_IME_RIME_CACHE_TTL_MS=400 python3 -m rag_ime.cli debug-server
RAG_IME_RIME_CACHE_TTL_MS=0 python3 -m rag_ime.cli debug-server
```

Run it against the shared RAG/memory core instead of the local MVP database:

```bash
python3 -m rag_ime.cli --core-mode json \
  --core-command "node --experimental-strip-types /path/to/pi-rag-memory-extension/scripts/ime-json-core.mjs --cwd /path/to/workspace --namespace wisdom-weasel-ime --db-path /path/to/session-history.sqlite" \
  debug-server --no-seed
```

Use `--no-seed` for shared-core debugging when you want to inspect an existing memory database without adding demo events.

Open:

```text
http://127.0.0.1:8765/
```

## Interaction Model

The native input method uses one shared number-key set instead of splitting numbers between word candidates and paragraph candidates.

```text
1-3   choose top-layer model prediction
4-6   choose lower RAG/memory candidate
Esc   cancel current composition
Enter commit the current composition
```

Reason:

- traditional number-key muscle memory stays stable;
- paragraph candidates do not need a separate key mode;
- the same payload can drive the debug page and native AppKit panel;
- the IME panel stays small because it only shows one prediction row and up to three memory rows.

## Small-Area Constraint

The native input method panel should not cover the document.

Current browser prototype constraints:

- compact max height: about 214 px;
- expanded max height: about 356 px;
- compact state shows one short-candidate row and at most two memory summaries;
- evidence text is hidden until the user switches to the RAG layer or presses the evidence debug control.

The native `RagCandidatePanel` keeps the strict version of this behavior: compact by default, no pipeline text, no model labels, no debug JSON, and evidence only as a one-line hint unless the user explicitly expands elsewhere.

## Local API

The debug page calls `rag_ime.debug_server.DebugImeService`.

Endpoints:

```text
GET  /api/health
POST /api/seed
POST /api/suggest
POST /api/rime-suggest
POST /api/action
POST /api/commit
```

`/api/suggest` returns the same stable frontend payload as:

```bash
python3 -m rag_ime.cli suggest-json ...
```

`/api/rime-suggest` returns the Squirrel/Rime side-candidate payload. It accepts structured Rime context:

```json
{
  "sessionId": "squirrel-debug",
  "requestSeq": 1,
  "rawInput": "ragshurufa",
  "preedit": "ragshurufa",
  "committedContext": "正在设计 RAG 输入法",
  "rimeContext": {
    "candidates": [
      {"label": "1", "text": "RAG 输入法", "comment": "rime"},
      {"label": "2", "text": "RAG 是", "comment": "rime"}
    ]
  }
}
```

The response includes `displayCandidates` where Rime candidates keep `selectionAction: select_rime_candidate`, while model/RAG side candidates use `selectionAction: commit_side_candidate`. The semantic query is built from commit preview or Rime candidates before falling back to raw input.

The response also includes `triggerDecision`. This is the backend guard that keeps the input method small and responsive:

- Rime candidates are always returned.
- Model/RAG side lanes are skipped for raw pinyin fallback, empty input, no side slot, or composing updates without stable Rime candidates.
- `forceSideCandidates: true` can be used by debug tooling to force a refresh.
- Skipped refreshes return empty `modelPredictions` / `ragCandidates` and `mergePolicy.sideCandidatesEnabled: false`.

The debug page probes `/api/rime-suggest` alongside `/api/suggest` and shows `queryBasis`, `triggerDecision`, `displayCandidates`, and cache metadata in the JSON panel. This is only for backend inspection; it does not change the browser prototype's visible candidate layout.

The local HTTP server keeps a short TTL cache for repeated equivalent `/rime-suggest` payloads. The cache key excludes `requestSeq` and `sessionId`, but includes payload content, memory event/action counts, project, and predictor configuration. Cached responses rewrite `requestSeq` and `sessionId` to the current request and include:

```json
{
  "cache": {
    "hit": true,
    "ttlMs": 400
  }
}
```

`POST /api/commit`, `POST /api/action`, and `POST /api/seed` clear this cache.

The page falls back to local mock suggestions if the API is unavailable, so visual iteration can continue while backend work is in progress.

## Native Porting Notes

Port in this order:

1. Keep `RagBridgeClient` unchanged unless the JSON contract changes.
2. Render compact evidence summaries first.
3. Add expanded evidence after number-key selection is stable.
4. Add richer action controls in a non-IME debug/preferences surface, not in the default candidate panel.
