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
