# RAG IME

Experimental local-first RAG input method for macOS, built around Rime/Squirrel,
local model prediction, and local memory retrieval.

## Status

This repository is an active prototype. It is suitable for code review,
experimentation, and local development, but it is not a packaged production IME
release yet.

The product route is not the independent native `RagImeMac` app. The product
route is the macOS Rime/Squirrel candidate-layer adapter plus the local sidecar.
`macos/RagImeMac/` is a native InputMethodKit debug harness for bridge and panel
experiments.

The current product path is:

```text
Squirrel / Rime frontend
  -> sidecar request with structured input context
  -> local model prediction
  -> local RAG and memory retrieval
  -> merged candidate list with source metadata
  -> side-candidate selection feedback
```

## Features

- macOS Squirrel patch pack for sidecar-backed candidates.
- Local sidecar API for Rime context parsing, candidate merge, selection
  feedback, and debug checks.
- Local SQLite memory store with FTS and optional vector retrieval.
- Local predictor clients, including a resident MLX service for Apple Silicon.
- Source-aware candidates for dictionary, model, RAG, memory, and raw input
  lanes.
- Foreground trace and readiness scripts for real Squirrel integration checks.
- Test coverage for candidate merge policy, stale-result guards, RAG governance,
  memory cleanup, and frontend trace contracts.

## Repository Map

| Path | Purpose |
| --- | --- |
| `rag_ime/` | Python sidecar, local memory core, predictor clients, CLI, and debug server. |
| `squirrel-patches/` | Patch pack that adds the sidecar lane to Squirrel. |
| `macos/RagImeMac/` | InputMethodKit debug harness and native UI experiments. |
| `scripts/` | Runtime install, health check, Squirrel readiness, and evaluation helpers. |
| `tests/` | Unit and integration-style regression tests. |
| `docs/` | Design notes, runtime guide, status, and evaluation cases. |

## Quick Start

Run the test suite:

```bash
python3 -m unittest discover -s tests
```

Initialize a local demo database:

```bash
python3 -m rag_ime.cli init-db
python3 -m rag_ime.cli seed-demo --reset
```

Start the sidecar manually:

```bash
python3 -m rag_ime.cli sidecar-server --host 127.0.0.1 --port 8766
```

Restart the local MLX predictor and sidecar launch agents:

```bash
scripts/restart_rag_ime_runtime.sh
```

Run Squirrel readiness checks:

```bash
scripts/doctor_squirrel_integration.sh
scripts/verify_squirrel_foreground_trace.sh
```

More operational details are in `docs/runtime-and-debug.md`.

## Candidate Sources

The sidecar keeps candidate sources explicit so the frontend can render and
route them consistently.

| Source | Meaning |
| --- | --- |
| `rime` | Normal Rime dictionary/composition candidate. |
| `model` | Local LLM prediction candidate. |
| `rag` | Retrieval result from local documents or history-derived memory. |
| `memory` | Stable local memory or lexicon candidate. |
| `raw_english` | Direct commit candidate for code-like raw input. |

Realtime prediction is local by default. Cloud or OpenAI-compatible providers,
when configured, are intended for offline memory, RAG, or lexicon maintenance
rather than per-keystroke prediction.

## References

This project studies or integrates with the following open-source projects:

| Project | How it is used |
| --- | --- |
| [Felix3322/Wisdom-Weasel](https://github.com/Felix3322/Wisdom-Weasel) | Prediction-flow and candidate-lifecycle reference. |
| [rime/squirrel](https://github.com/rime/squirrel) | macOS Rime frontend and candidate-panel base. |
| [rime/librime](https://github.com/rime/librime) | Rime engine for schemas, dictionaries, composition, and candidate generation. |
| [ml-explore/mlx](https://github.com/ml-explore/mlx) | Apple Silicon runtime used by the local model service. |
| [ml-explore/mlx-lm](https://github.com/ml-explore/mlx-lm) | Local language-model loading and generation on MLX. |

## Development Notes

- Do not commit model weights, built `.app` bundles, local SQLite databases,
  personal input history, API keys, or machine-specific caches.
- Keep normal Rime/Squirrel behavior as the fallback path. Sidecar, predictor,
  RAG, and debug UI failures should fail closed to ordinary IME behavior.
- Keep raw input text out of default traces unless an explicit debug flag is
  enabled.
- Choose and document a final license before inviting broad reuse.
