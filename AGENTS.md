# Agent Guide

This repository is being prepared for public inspection at
`https://github.com/7155/wisdom-weasel-rag-ime`.

## Product Boundary

- Product route: patched macOS Squirrel/Rime plus the local Python sidecar.
- Do not reintroduce an independent InputMethodKit frontend; use the patched
  Squirrel sources and engine-neutral frontend contracts as the single route.
- Base IME responsibility stays with Rime/Wanxiang: pinyin parsing, fuzzy pinyin,
  dictionary candidates, paging, and fallback.
- RAG-IME adds side candidates from local model prediction and local
  RAG/memory. It should not replace Rime's decoder.

## User Requirements

- Real foreground behavior matters more than backend JSON. A change is not done
  until the actual input source can show and select the candidates.
- LLM, RAG/memory, and Rime dictionary candidates must remain distinguishable.
- Number keys select live side candidates instead of inserting literal digits.
- Backspace/Delete and app/context switches must invalidate stale context.
- Selecting an LLM/RAG side candidate should immediately schedule the next
  prediction opportunity.
- Realtime prediction uses a local small model. `x1api.top` is only for offline
  memory, RAG, and lexicon cleanup.

## Main Files

- `docs/project-status.md`: current goal, user feedback, remaining work.
- `docs/design-decisions.md`: stable architecture choices.
- `docs/runtime-and-debug.md`: run, install, doctor, and evaluation commands.
- `squirrel-patches/0001-add-rag-ime-sidecar.patch`: product frontend patch.
- `rag_ime/rime_sidecar.py`: sidecar API and candidate merge path.
- `rag_ime/mlx_predictor_server.py`: resident local MLX predictor.
- `rag_ime/local_sqlite_core.py`: local RAG/memory storage and ranking.
- `rag_ime/memory_generator.py`: offline x1api-compatible distillation.

## Current Priorities

1. Verify the real foreground Squirrel install and avoid duplicate stale input
   sources.
2. Keep foreground context correct after Backspace/Delete.
3. Deduplicate and reorganize RAG memory so old input does not dominate.
4. Improve local multi-word prediction toward top-3 logits seed branching with
   prompt/KV-cache reuse.
5. Keep docs short: update existing root docs before adding new long notes.

## Safety

- Do not commit API keys, local databases, model weights, built apps, logs, or
  personal input history.
- `.rag-ime-data/`, `.env*`, SQLite files, model files, build outputs, and
  archives are intentionally ignored.
- Tests may use fake fixture keys such as `secret-value`; do not replace them
  with real credentials.

## Verification

Use narrow checks while editing, then run the broad unit suite before publishing
substantial changes:

```bash
python3 -m unittest discover -s tests
scripts/doctor_squirrel_integration.sh
scripts/verify_squirrel_foreground_trace.sh
```

Foreground automation can be flaky on macOS. Treat doctor output as necessary
but not sufficient; manual foreground typing is still the strongest acceptance
signal.
