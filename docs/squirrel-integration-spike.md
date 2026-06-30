# Squirrel Integration Spike

- Date: 2026-06-30
- Status: first patch pack generated
- Goal: move the proven `rime-suggest-json` contract into a Squirrel/Rime frontend without replacing librime composition.

Patch pack:

```text
squirrel-patches/0001-add-rag-ime-sidecar.patch
```

It applies to Squirrel `2158538` and keeps the integration fail-closed behind `rag_ime/enabled`. Use the helper script to prepare a disposable patched checkout:

```bash
scripts/prepare_squirrel_workspace.sh
```

## Source Boundary

Checked Squirrel `2158538`.

The integration point is `sources/SquirrelInputController.swift` inside `rimeUpdate(clearReservedComments:)`:

```text
rimeAPI.get_context(session, &ctx)
  -> preedit
  -> ctx.commit_text_preview
  -> ctx.menu.candidates / comments
  -> labels / highlighted / page / is_last_page
  -> showPanel(...)
```

RAG-IME should request side candidates after the arrays are built and before `showPanel(...)` receives the final display list.

## Minimal Patch Shape

### 1. Add Swift Contract Types

Move or copy the current prototype types from:

```text
macos/RagImeMac/Sources/RimeSidecarModels.swift
```

into Squirrel:

```text
sources/RagImeSidecarModels.swift
```

These are plain `Codable` models, so they do not depend on the prototype input method.

### 2. Add Sidecar Client

Create:

```text
sources/RagImeSidecarClient.swift
```

Minimum behavior:

- read `rag_ime/enabled`, `rag_ime/python`, `rag_ime/repo_root`, `rag_ime/db_path`, `rag_ime/max_side_candidates`, and `rag_ime/max_visible_candidates` from Squirrel config;
- prefer `rag_ime/sidecar_url` for long-running HTTP sidecar calls;
- debounce high-frequency `rimeUpdate` refreshes with `rag_ime/debounce_ms`;
- write one `RimeSidecarRequest` to a temporary JSON file;
- call:

```bash
python3 -m rag_ime.cli rime-suggest-json --payload-file <file>
```

- decode `RimeSidecarResponse`;
- fail closed: return no side candidates on timeout, bad JSON, or non-zero exit.

### 3. Build Request In `rimeUpdate`

Use data that Squirrel already extracts:

```swift
let request = RimeSidecarRequest(
  sessionId: "\(session)",
  requestSeq: nextRequestSeq(),
  rawInput: rimeAPI.get_input(session).map { String(cString: $0) } ?? "",
  preedit: preedit,
  committedContext: recentCommittedText,
  maxVisibleCandidates: configuredMaxVisible,
  maxSideCandidates: configuredMaxSide,
  rimeContext: RimeContextPayload(
    candidates: zip(candidates, comments).enumerated().map { ... },
    highlightedIndex: Int(ctx.menu.highlighted_candidate_index),
    page: Int(ctx.menu.page_no),
    isLastPage: ctx.menu.is_last_page
  )
)
```

Do not send raw pinyin alone when Rime candidates are available. The Python side already chooses `commitTextPreview` or Rime candidates before falling back to raw input.

### 4. Async Request Guard

Mirror Wisdom-Weasel's `m_llm_request_seq` idea:

```text
latestSidecarRequestSeq += 1
capture seq
run sidecar in background
if seq != latestSidecarRequestSeq: drop result
dispatch main: update side candidates and redraw panel
```

This prevents old retrieval/model results from overwriting the current Rime page.

The patch also adds a request fingerprint:

```text
rawInput + preedit + commitTextPreview + page + highlighted + first Rime candidates
```

Only the latest debounced fingerprint is sent. Responses are dropped if request sequence, session, raw input, preedit, page, or first candidate fingerprint no longer match. This is stricter than Wisdom-Weasel's request sequence alone and matters because Squirrel can refresh the same raw input across pages/candidate lists.

The Python sidecar also keeps a short TTL cache for equivalent `/rime-suggest` payloads. The cache is process-local, excludes `requestSeq` and `sessionId`, and is invalidated by memory event/action counts plus commit/action/seed calls. This catches repeated Squirrel refreshes that survive frontend debounce.

The Python sidecar now has a second guard before model/RAG work:

```text
Rime context -> semantic query -> triggerDecision
```

It returns Rime candidates on every response, but skips model/RAG side lanes when the request is still raw pinyin fallback, has no stable Rime candidate, has no visible side slot, or has only a one-character candidate before idle. The response exposes:

```json
{
  "triggerDecision": {
    "shouldRefresh": false,
    "reason": "skip: composing without stable Rime candidate"
  },
  "mergePolicy": {
    "sideCandidatesEnabled": false
  }
}
```

This keeps the real Squirrel key path cheap even when Rime fires many panel refreshes. Frontend debounce and the server TTL cache still matter, but they are no longer the only protection against calling retrieval/model code on every composing update.

### 5. Candidate Display Merge

Short-term path:

- let Python return `displayCandidates`;
- pass only `.text`, `.comment`, `.label` to `SquirrelPanel.update(...)`;
- keep `displayCandidates` cached in `SquirrelInputController` for selection routing.

Selection routing:

```text
display item action == select_rime_candidate
  -> rimeAPI.select_candidate_on_current_page(session, rimeIndex)

display item action == commit_side_candidate
  -> client.insertText(insertText, replacementRange: .empty)
  -> background HTTP/CLI /rime-select
  -> /rime-select records commit and accepted action when memory metadata exists
  -> clear composition if needed
```

Do not mutate librime's internal candidate menu for the first integration. Build a frontend display list and route selection by display metadata.

Keyboard routing needs one extra guard because normal number-key selection goes through librime before the panel's click handler. The first patch only intercepts labels that currently point to side candidates; all normal Rime candidate keys continue through `process_key(...)`.

The patch also records accepted side candidates after insertion. This is required for the input method to become a memory feedback surface instead of a one-way suggestion renderer.

The preferred writeback path is now one request:

```text
POST /rime-select
  candidate: displayCandidates[n]
  query / recentContext / preedit
  -> commit input event
  -> accepted action if sourceType == rag and memory metadata exists
```

The Squirrel client keeps the older `commit` + `action-json accepted` flow only as a compatibility fallback.

## Current Prototype Evidence

The prototype now proves the backend and Swift contract:

```bash
scripts/build_macos_frontend.sh
build/RagImeMac.app/Contents/MacOS/RagImeMac --preview-rime-sidecar-json
python3 -W ignore::ResourceWarning -m unittest tests.test_rime_sidecar tests.test_debug_server
```

Expected properties:

- response `schemaVersion` is `rag-ime.rime-sidecar.v1`;
- response `queryBasis` is `rimeCandidates` when Rime candidates exist;
- `displayCandidates[0]` keeps `selectionAction: select_rime_candidate`;
- model/RAG side candidates use `selectionAction: commit_side_candidate`;
- `mergePolicy.rawPinyinFallback` is `false` for dirty-pinyin requests with Rime candidates.
- `mergePolicy.maxModelSideCandidates` is `1`, so model predictions do not consume every side slot before RAG/memory candidates.

## Not In First Spike

- No custom librime plugin.
- No mutation of librime candidate internals.
- No model/RAG result blocking on the main key event path.
- No large evidence UI inside the default candidate panel.
- No direct raw-pinyin decoding by LLM.
