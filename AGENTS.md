# Agent Guide

This repository is being prepared for public inspection at
`https://github.com/7155/personal-agent-workbench`.

## Product Boundary

- Product center: explicit Agent Sessions, multi-Agent Rooms, Tools, governed
  memory, and the Control Center.
- Patched macOS Squirrel/Rime, voice, browser, and desktop bridges are optional
  adapters around that core.
- Do not reintroduce an independent InputMethodKit frontend; use the patched
  Squirrel sources and engine-neutral frontend contracts as the single route.
- Base IME responsibility stays with Rime/Wanxiang: pinyin parsing, fuzzy pinyin,
  dictionary candidates, paging, and fallback.
- The input adapter adds side candidates from local prediction and governed
  retrieval. It must not replace Rime's decoder.

## User Requirements

- Real foreground behavior matters more than backend JSON. A change is not done
  until the actual input source can show and select the candidates.
- LLM, RAG/memory, and Rime dictionary candidates must remain distinguishable.
- Ordinary number keys stay with Rime/the host; Tab and Option+number select
  assistant candidates.
- Backspace/Delete and app/context switches must invalidate stale context.
- Selecting an LLM/RAG side candidate should immediately schedule the next
  prediction opportunity.
- Feature model choices must resolve through their owned runtime boundary.
  Passive input prediction stays local; explicit Agent, Active RAG, voice, and
  offline workflows may use configured Providers.

## Main Files

- `README.md`: public product boundary, setup, and validation entry points.
- `ARCHITECTURE.md`: ownership, dependency direction, and extension boundaries.
- `release/`: public-safe machine-readable feature and release metadata.
- `eval/`: synthetic public evaluation fixtures; never copy private input here.
- `squirrel-patches/0001-add-rag-ime-sidecar.patch`: product frontend patch.
- `rag_ime/rime_sidecar.py`: sidecar API and candidate merge path.
- `rag_ime/mlx_predictor_server.py`: resident local MLX predictor.
- `rag_ime/local_sqlite_core.py`: local RAG/memory storage and ranking.
- `rag_ime/memory_generator.py`: offline DeepSeek V4 distillation.

## Current Priorities

1. Keep Session, Room, Tool, Provider, and persistence ownership explicit.
2. Preserve model-selection locality and runtime-neutral Provider boundaries.
3. Keep foreground input context correct after Backspace/Delete and app changes.
4. Keep public guidance concise in root files; `docs/` is local-only and must
   never be committed.

## Safety

- Do not commit API keys, local databases, model weights, built apps, logs, or
  personal input history.
- `docs/` contains private local notes and screenshots and is intentionally
  ignored in its entirety.
- `.rag-ime-data/`, `.env*`, SQLite files, model files, build outputs, and
  archives are intentionally ignored.
- Tests may use fake fixture keys such as `secret-value`; do not replace them
  with real credentials.

## Verification

Use narrow checks while editing, then run the broad unit suite before publishing
substantial changes:

```bash
python3 -m unittest discover -s tests
python3 scripts/check_import_boundaries.py
python3 scripts/check_route_ownership.py
python3 scripts/check_public_release.py --repository-only
scripts/doctor_squirrel_integration.sh
scripts/verify_squirrel_foreground_trace.sh
```

Foreground automation can be flaky on macOS. Treat doctor output as necessary
but not sufficient; manual foreground typing is still the strongest acceptance
signal.
