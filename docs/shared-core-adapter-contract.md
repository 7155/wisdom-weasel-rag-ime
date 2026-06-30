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

## Current MVP Backend

Until the shared core exposes stable write/action APIs, this product repo uses `LocalSqliteCoreClient` as the Mac MVP backend.

It implements the same adapter-facing contract:

```text
record_event
suggest_for_input
apply_action
build_agent_context
```

This keeps the UI/adapter code stable while still proving the full local loop:

```text
committed text
  -> SQLite input_events
  -> FTS5 memory_fts
  -> SuggestionCompiler
  -> InputSuggestion
  -> apply_action
  -> later ranking change
```
