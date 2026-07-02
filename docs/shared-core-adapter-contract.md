# Shared Core Adapter Contract

The full working note lives in the learning workspace at:

```text
docs/learning/wisdom-weasel-rag-ime/shared-core-adapter-contract.md
```

This product repo follows the same boundary:

- shared RAG/memory core owns SQLite, FTS5, ranking, governance, profiles, trace paths, and context block generation;
- this input method repo owns adapter behavior, candidateization, evidence preview, UI prototype, and acceptance scenarios;
- the input method must call the shared core instead of creating a second memory database.

## Required Core APIs

```ts
recordMemoryEvent(event)
searchMemories(query)
applyMemoryAction(action)
buildContextBlock(request)
recentInputContext(request)
```

Neutral environment variables should be preferred:

```text
RAG_MEMORY_DB_PATH
RAG_MEMORY_DB_PROFILE
RAG_MEMORY_TRACE_PATH
```

`PI_RAG_MEMORY_*` names can remain compatibility aliases, but this repo must not depend on PI naming.

## Input Method Adapter Output

```ts
{
  suggestionId: string,
  surfaceText: string,
  suggestionType: "phrase" | "sentence" | "structure" | "style_hint" | "evidence_preview",
  sourceMemoryId: string,
  evidencePreview: string,
  confidence: number,
  actions: ["commit", "expand", "pin", "downrank", "delete"]
}
```

The traditional candidate list should show short candidates. Full RAG evidence belongs in preview or expanded panels.

## Prediction Session Output

Prediction-first adapters must distinguish the normal candidate panel from the
AI prediction session. Rime/wanxiang can have visible candidates while the AI
prediction panel should still be cleared.

`/rime-suggest` and other frontend adapters should expose:

```ts
{
  phase: "hidden" | "raw_passthrough" | "anchor_composing" | "post_commit" | "prefix_constrained",
  inputMode: "raw_input" | "anchor_composing" | "post_commit_predicting" | "prefix_constrained_composing",
  candidatePanelVisible: boolean,
  predictionPanelVisible: boolean,
  shouldClearPredictionPanel: boolean,
  clearReason: string,
  selectionScope: "none" | "raw" | "rime" | "prediction" | "mixed_prediction_first",
  rimeCompositionOwnedByRime: boolean
}
```

This is the frontend-neutral lifecycle contract:

- first-word pinyin: `anchor_composing`, Rime/wanxiang owns composition, AI panel cleared;
- post-commit: `post_commit`, AI candidates own the small prediction panel;
- continued pinyin: `prefix_constrained`, Rime owns composition while matching prediction candidates can be inserted before fallback;
- raw English/code/path/command: `raw_passthrough`, do not show stale prediction candidates;
- empty/stale response: `hidden`, frontend clears the AI prediction layer.

## Suggestion Compiler Boundary

`SuggestionCompiler` belongs to the input-method adapter, not the shared memory core.

Reason:

- PI/Agent adapters need retrieved evidence and context blocks, not input-method candidate bars.
- IME adapters need short surface text, insert text, preview text, source cards, and keyboard actions.
- Keeping this layer outside the shared DB core avoids coupling every RAG consumer to IME-specific UX.

Expected flow:

```text
shared core search/suggest
  -> RetrievedMemory[]
  -> IME SuggestionCompiler
  -> InputSuggestion[]
```

The compiler decides whether a memory becomes `phrase`, `sentence`, `structure`, `style_hint`, `paragraph`, `quote`, `rewrite`, `continue`, or `template`.

## Current Backend Options

The product repo has two backend paths:

- `LocalSqliteCoreClient`: standalone Mac MVP backend for development and packaging tests.
- `JsonCommandCoreClient`: production-facing bridge into the shared RAG/memory core.

Both implement the same adapter-facing contract:

```text
record_event
suggest_for_input
apply_action
build_agent_context
recent_input_context
```

The shared-core command lives in `pi-rag-memory-extension`:

```bash
node --experimental-strip-types scripts/ime-json-core.mjs \
  --cwd /path/to/workspace \
  --namespace wisdom-weasel-ime \
  --db-path /path/to/session-history.sqlite
```

The command reads one JSON request from stdin and returns one JSON response to stdout. This is intentionally process-based for the first integration so the macOS input method does not need a long-running daemon or port allocation while the adapter contract is still settling.

This keeps the UI/adapter code stable while proving the full local loop:

```text
committed text
  -> shared core input_events
  -> recent_input_context for history-aware local prediction
  -> FTS/vector/rerank retrieval
  -> SuggestionCompiler
  -> InputSuggestion
  -> apply_action
  -> shared memory_actions governance
```

`recent_input_context` should return a bounded, privacy-local text block built from the user's recent committed input events. It is consumed by the IME model prediction lane and may also improve RAG recall for continuation-style typing.

Expected JSON request:

```json
{
  "method": "recent_input_context",
  "params": {
    "project": "wisdom-weasel-rag-ime",
    "limit": 6,
    "max_chars": 420
  }
}
```

Expected JSON response:

```json
{
  "result": {
    "context": "最近输入历史..."
  }
}
```
