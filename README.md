# Wisdom-Weasel RAG IME

Local-first RAG input method prototype inspired by
`Felix3322/Wisdom-Weasel`, with Rime/Squirrel as the real IME base, a local
small-model prediction lane, and local memory/RAG candidates.

This repo is not a fork of Wisdom-Weasel. Wisdom-Weasel is the main reference
for prediction flow, candidate lifecycle, and UI behavior.

## Start Here

- `AGENTS.md`: concise instructions for AI/code agents reviewing this public repo.
- `docs/project-status.md`: product goal, user requirements, current state, and next priorities.
- `docs/design-decisions.md`: architecture decisions and boundaries.
- `docs/runtime-and-debug.md`: commands for local run, install, checks, and evaluation.
- `squirrel-patches/README.md`: patch-pack details for the Squirrel frontend.
- `docs/eval/*.jsonl`: small regression/evaluation cases.

For a Pro model or external reviewer, read `AGENTS.md` first, then
`docs/project-status.md`, then `docs/runtime-and-debug.md`. The current public
branch is `codex/wisdom-weasel-rag-ime-mvp`.

## Product Goal

Build an input method where normal typing still feels like a mature Rime/Wanxiang
IME, while extra candidates come from:

- local LLM prediction;
- local RAG / long-term memory;
- normal Rime dictionary candidates.

The three sources must be visually distinct. LLM candidates should appear as a
compact prediction row, RAG/memory as evidence-backed longer candidates, and
Rime candidates as the stable fallback dictionary layer.

## Current Boundary

The product route is not the independent native `RagImeMac` app. It is the
macOS Rime/Squirrel candidate-layer adapter plus a local sidecar. The
`macos/RagImeMac` app is the native InputMethodKit debug harness, used only for
bridge, panel rendering, and JSON contract checks.

Cloud APIs are not used for realtime prediction. The high-intelligence
`x1top` GPT-series lane, currently wired through `x1api.top`-compatible
settings, is reserved for offline memory/RAG/database/lexicon distillation,
not for per-keystroke completion.
Realtime prediction should come from a local small model with a loopback
predictor URL, leaving room for KV-cache and native inference optimization.

## Current Runtime Shape

```text
macOS Squirrel / Rime
  -> Rime schema, pinyin parsing, dictionary candidates
  -> patched Squirrel sends structured context to sidecar
  -> local sidecar merges local model + RAG/memory + Rime candidates
  -> candidate panel shows source colors and labels
  -> number keys select side candidates instead of literal numbers
  -> selection feedback updates local memory/frequency state
```

## Implemented

- Local SQLite/FTS5 memory core and suggestion compiler.
- Committed-input event recording and bounded recent history context.
- Prediction-first merge logic for model, RAG/memory, and Rime candidates.
- HTTP sidecar endpoints for `/rime-suggest`, `/rime-select`, health, and debug checks.
- Local predictor clients, including Ollama/OpenAI-compatible baselines and resident MLX service.
- Memory/RAG optimization command intended for x1top / x1api-compatible
  offline distillation.
- Squirrel patch pack for sidecar integration and side-candidate selection.
- Native macOS debug harness and AppKit candidate panel preview.
- Sichuan fuzzy-pinyin install helper enabled by default in the Rime bootstrap path.
- Unit tests and small JSONL evaluation cases.

## Still Open

- Foreground candidate UX must be tuned so LLM/RAG results appear continuously and predictably.
- RAG results still need better dedupe and context freshness after delete/backspace.
- Local model quality is not yet good enough; the fast path needs a stronger local model or native provider.
- Consecutive LLM selection should immediately trigger the next prediction instead of waiting for idle refresh.
- The final Wisdom-Weasel-style provider should support stable prompt/KV cache, multi-candidate generation, and stale-result discard.

## Basic Commands

```bash
python3 -m unittest discover -s tests
python3 -m rag_ime.cli init-db
python3 -m rag_ime.cli seed-demo --reset
python3 -m rag_ime.cli sidecar-server --host 127.0.0.1 --port 8766
scripts/restart_rag_ime_runtime.sh
scripts/doctor_squirrel_integration.sh
scripts/verify_squirrel_foreground_trace.sh
```

More commands live in `docs/runtime-and-debug.md`.

## Public Repo Notes

- No model weights, local SQLite databases, built `.app` bundles, API keys, or
  personal input history should be committed.
- `x1api.top` examples are placeholders for offline memory/RAG/lexicon cleanup
  only; the realtime predictor must stay local.
- The repo currently has no final production license decision. Choose one before
  inviting broad reuse beyond code review and model analysis.
