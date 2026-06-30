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

## Current Commands

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

Show memory action effects:

```bash
python3 -m rag_ime.cli action-demo
```

Build the Agent first-run memory block:

```bash
python3 -m rag_ime.cli agent-hook --top-k 3
```

Use a future shared-core JSON command:

```bash
RAG_MEMORY_CORE_COMMAND="node /path/to/shared-core-cli.mjs" python3 -m rag_ime.cli demo
```

## Current Status

Implemented in this repo:

- adapter data models;
- shared-core client boundary;
- fixture core for adapter/UI acceptance only;
- short candidate rendering;
- evidence preview and expanded evidence panel text;
- pin/downrank/delete action wiring;
- Agent first-run hook wrapper;
- three realistic UI scenarios;
- unittest and acceptance script.

Not implemented in this repo by design:

- SQLite/FTS5 memory store;
- vector recall;
- shared ranking/governance persistence;
- PI runtime integration.

Those belong to the shared RAG/memory core. This repo should call that core once it exposes a stable CLI or importable adapter API.

## macOS Frontend Route

1. Keep this CLI adapter as the product contract and test harness.
2. Add a small local daemon or JSON command that wraps the shared RAG/memory core.
3. Build a macOS InputMethodKit prototype that captures committed text and calls:
   - `record_event` after commit;
   - `suggest_for_input` while preedit/current context changes;
   - `apply_action` when the user accepts, pins, downranks, or deletes a suggestion.
4. Render a normal candidate bar for short suggestions.
5. Render evidence preview in an expanded panel or WebView-style overlay.
6. Keep Rime/Squirrel/Wisdom-Weasel integration as the next bridge after the adapter contract is stable.
