# Wisdom-Weasel RAG IME

Local-first RAG input method MVP inspired by Wisdom-Weasel.

This repository is a standalone product repo, not a fork/PR branch of `scukeqi/Wisdom-Weasel`.
Wisdom-Weasel remains an upstream reference for the existing LLM input method flow.

## Current Boundary

The RAG/memory layer is being extracted into a shared core so PI and this input method do not build duplicate databases or ranking logic.

This repo should focus on:

- input-method adapter contracts;
- committed input event capture;
- short candidate generation from shared-core retrieval results;
- evidence preview / expanded evidence UI prototype;
- pin / downrank / delete action wiring;
- Agent first-run context hook;
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
macOS input adapter / CLI prototype
  -> shared rag-memory core API or JSON CLI
  -> RetrievedMemory[]
  -> InputSuggestion[]
  -> short candidate list + evidence preview
  -> user action
  -> shared core governance action
```

