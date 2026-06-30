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
default focus: short candidates
  1-0   choose top-layer short candidate
  Tab   accept selected short candidate
  ↓     move focus to RAG/memory layer

RAG focus:
  1-0   choose RAG/memory paragraph candidate
  ↑     return to short candidate layer
  Esc   collapse back to short layer

direct access:
  Opt+1..0 choose RAG/memory candidate without switching focus
```

Reason:

- traditional number-key muscle memory stays stable;
- paragraph candidates do not steal half the number row;
- the same model can scale from compact overlay to expanded evidence mode;
- experienced users still get a direct memory shortcut through `Opt+number`.

## Small-Area Constraint

The native input method panel should not cover the document.

Current browser prototype constraints:

- compact max height: about 214 px;
- expanded max height: about 356 px;
- compact state shows one short-candidate row and at most two memory summaries;
- evidence text is hidden until the user switches to the RAG layer or presses the evidence debug control.

The native `RagCandidatePanel` should keep the strict version of this behavior: compact by default, no pipeline text, no model labels, no debug JSON, and evidence only as a one-line hint unless the user explicitly expands elsewhere.

## Local API

The debug page calls `rag_ime.debug_server.DebugImeService`.

Endpoints:

```text
GET  /api/health
POST /api/seed
POST /api/suggest
POST /api/action
POST /api/commit
```

`/api/suggest` returns the same stable frontend payload as:

```bash
python3 -m rag_ime.cli suggest-json ...
```

The page falls back to local mock suggestions if the API is unavailable, so visual iteration can continue while backend work is in progress.

## Native Porting Notes

Port in this order:

1. Copy the focus-layer state machine into `RagCandidatePanel`.
2. Keep `RagBridgeClient` unchanged unless the JSON contract changes.
3. Render compact evidence summaries first.
4. Add expanded evidence after number-key selection is stable.
5. Keep `Opt+number` as the direct paragraph shortcut.
