# Squirrel Integration Spike

- Date: 2026-06-30
- Status: first patch pack generated
- Goal: move the proven `rime-suggest-json` contract into a Squirrel/Rime frontend without replacing librime composition.

Patch pack:

```text
squirrel-patches/0001-add-rag-ime-sidecar.patch
```

It applies to Squirrel `2158538` and keeps the integration fail-closed behind `rag_ime/enabled`.

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
  -> record action/commit through sidecar or follow-up CLI call
  -> clear composition if needed
```

Do not mutate librime's internal candidate menu for the first integration. Build a frontend display list and route selection by display metadata.

Keyboard routing needs one extra guard because normal number-key selection goes through librime before the panel's click handler. The first patch only intercepts labels that currently point to side candidates; all normal Rime candidate keys continue through `process_key(...)`.

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

## Not In First Spike

- No custom librime plugin.
- No mutation of librime candidate internals.
- No model/RAG result blocking on the main key event path.
- No large evidence UI inside the default candidate panel.
- No direct raw-pinyin decoding by LLM.
