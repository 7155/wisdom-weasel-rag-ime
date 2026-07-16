# Wisdom Weasel RAG IME

> A local-first macOS input-method research project built on Rime/Squirrel.

**Platform:** macOS 14+ | **Python:** 3.10+ | **License:** [GPL-3.0-only](LICENSE) | **Status:** research prototype

Wisdom Weasel RAG IME preserves ordinary Pinyin composition in Rime and adds
post-commit local completion, curated local retrieval and memory, and optional
explicit knowledge workflows. It is intentionally conservative about the
typing path: ordinary composition remains Rime's job, and remote generation is
never used for passive per-keystroke prediction.

> [!WARNING]
> This repository is licensed under GPL-3.0-only, but it is **not a
> release-ready IME**. The foreground acceptance, completion-quality, signing,
> notarization, and final release-manifest gates remain open. Do not install it
> as a daily input method until those gates have been completed.

## What It Does

| Capability | Current boundary |
| --- | --- |
| Pinyin composition | Rime/librime owns schemas, fuzzy Pinyin, paging, native candidates, and user-dictionary ranking. The sidecar must never replace its composition path. |
| Local completion | After a commit, a local MLX, Ollama, or loopback OpenAI-compatible runtime may offer short, source-marked continuations. `Tab` accepts the first suggestion and `Option+number` selects an ordinal; ordinary number keys stay with Rime or the host. |
| Hybrid RAG and memory | Local SQLite FTS5 BM25, precomputed vector scoring, tags, time, feedback, and weighted reciprocal-rank fusion produce traceable local evidence. The current vector lane is an exact scan, not ANN/HNSW/FAISS or a learned cross-encoder reranker. |
| Explicit knowledge work | Selected-text assistance, long-form answers, memory organization, and optional DeepSeek-compatible generation are explicit Control Center workflows, not background typing behavior. |
| Voice input | An optional headless macOS agent provides push-to-talk streaming ASR. It is isolated from Squirrel's keystroke path and requires explicit permissions and provider configuration. |

## Core Features

The status labels below deliberately distinguish code presence from real macOS
foreground acceptance. "Implemented" does not mean that signing, notarization,
or every host application's text field has passed manual testing.

### Rime Input

**Status: implemented; real foreground acceptance remains required.**

The product frontend is a single patched Squirrel/InputMethodKit route. Rime
continues to own Pinyin parsing, fuzzy Pinyin, paging, native candidates, and
the user dictionary. Wisdom Weasel adds a source-aware assistant surface rather
than replacing Rime's decoder. Ordinary number keys stay with Rime/the host;
`Tab` and `Option+number` select assistant candidates.

### Local LLM Prediction

**Status: in development; runtime integration and automated tests are present,
but candidate quality and foreground stability are still release gates.**

Passive post-commit prediction uses a local runtime such as MLX, Ollama, or a
loopback OpenAI-compatible server. It emits short continuations without sending
every keystroke to a remote model. The final prompt prioritizes the live input,
today's plan, complete recent inputs, and then budgeted RAG evidence; it asks for
bare continuation instead of an explanation or a copy of retrieved text.

Current development-machine timing is split into two different measurements:

| Measurement | Current observation |
| --- | ---: |
| Prefill / first token | about **54 ms** |
| Three complete candidates | about **206 ms** |

These are one local development measurement, not a service-level guarantee.
Hardware, model, quantization, cache state, input length, and runtime all affect
the result. In particular, this README does **not** claim that prediction is
"finished in 50 ms".

### Hybrid RAG

**Status: implemented in the local core and sidecar; foreground relevance still
needs continued evaluation.**

Retrieval combines SQLite FTS5 BM25, vector similarity, tags and tag relations,
time, feedback, and weighted reciprocal-rank fusion. A configurable soft
context budget defaults to 4096 tokens with 1024 tokens reserved for output.
Recent input starts from a 10-20 complete-event baseline and can exceed 20 when
the budget allows. Diagnostics report the number and estimated tokens actually
injected for recent inputs, plans/Todos, timeline notes, and RAG evidence.

Explicit queries such as "yesterday", "last week", "before", or "the original
requirement" can retrieve the corresponding time window and bypass ordinary
age decay. Old material is preserved, not silently treated as current truth.

### AI Memory

**Status: in development; draft generation, replacement links, decay, and
rollback contracts are implemented and await prolonged real-data validation.**

Short one- or two-character commits do not automatically become facts. Nearby
Rime fragments are assembled using punctuation, pauses, focus changes, and
context groups before they receive normal memory weight. New explicit facts,
preferences, decisions, and requirements may supersede older memory without
deleting its source. Temporary plans decay quickly, project state decays at a
medium rate, and stable preferences decay slowly.

### Personal Knowledge Base

**Status: in development; local review workflow is implemented.**

The knowledge workbench combines local memory with optional explicit knowledge
generation. AI organization produces an editable draft first. Only an explicit
review action applies selected changes to formal memory, indexes, or the Rime
lexicon. It is not a background remote upload path.

### Document Knowledge Libraries

**Status: in development; document management, parsing, indexing, retrieval,
source review, and an independent document graph are implemented.**

Large external documents live in a separate Knowledge Worker domain rather
than being mixed into personal memory. The Control Center manages libraries,
imports, parser and chunking settings, retrieval settings, source/Markdown/
chunk/asset review, index jobs, retrieval tests, and a document knowledge
graph. Built-in parsing is always available; MinerU can be installed as an
optional local parser for layout-heavy PDFs and OCR. The graph projects
document structure, topics, entities, terms, and evidence-bearing chunks into
its own SQLite tables, with source navigation and rebuild status, without
touching the personal-memory relationship graph.

Agent access remains one explicit, read-only `ime_knowledge` tool. The graph is
currently a Knowledge Worker retrieval and control-plane feature, not a second
agent tool, so graph expansion cannot silently increase the agent's authority.

### Memory And Knowledge Management

**Status: in development; management APIs and native views are implemented.**

The Control Center can inspect full content, source events, tags, relationships,
timestamps, confidence, and supersession state. Management operations include
edit, merge, archive, suppress, restore, and rollback. Tag exploration supports
both a list and a relationship graph. Topic books are reused instead of being
created after every organization run; after a configurable inactive period
(60 days by default) they become archive candidates. Archived books remain
searchable with lower ordinary weight and can reactivate when an old project is
explicitly requested or relevant content appears again.

### Voice Input

**Status: in development; recording, streaming ASR, overlay, and insertion are
implemented, while host-specific focus behavior still requires manual tests.**

The optional `RagImeVoice.app` agent shows a foreground recording overlay and
an audio-reactive waveform, streams speech to the configured ASR provider, and
inserts the final text at the active cursor. It runs outside Squirrel's
keystroke path so a microphone/network failure cannot block ordinary typing.
Microphone and Accessibility permissions belong to the stable installed app,
not a temporary derived-build identity.

### Daily Planning And Assistant

**Status: in development; database, API, context injection, completion-event
recognition, undo, and the native page are implemented.**

The Planning page keeps long-term goals, today's plan, prioritized Todos,
deadlines, completion state, and daily notes together. The assistant summarizes
what was completed, what remains, and a sensible next action. Explicit phrases
such as "completed task X" can complete a matching Todo and provide undo;
ambiguous language only creates a confirmation suggestion. Open tasks, goals,
and daily notes are eligible for the model context under the shared token
budget.

### Structured Agent Rooms

**Status: implemented in the local Agent runtime and Web Control Center.**

Rooms support two explicit kinds: project collaboration and roleplay chat.
They share one event contract, but keep different authority boundaries:
collaboration Rooms require an authorized workspace, while roleplay Rooms can
run without filesystem access. Routing is stored as structured configuration
(`manual_mentions`, `moderator`, `sequential`, `natural`, or `invite_only`);
the selected participant is recorded by stable ID rather than by inserting a
fake `[speaker]` prefix into message text.

Each Room owns a versioned common scenario, independent topics, and
workspace-scoped shared artifacts. Topic changes only alter subsequent working
context: participant identity, private Agent memory, global user memory, Room
history, and shared files remain separate objects. The first implementation
selects one visible speaker per user turn, while the existing coordinator and
intercom path can delegate parallel research without turning every delegated
worker into another public conversation.

### Diagnostics And Repair

**Status: implemented; doctor output is necessary but not sufficient evidence.**

The diagnostics surface separates process health, model readiness, retrieval,
permissions, context capture, and final model injection. It records the exact
source counts and token estimates used by a request, while raw trace text stays
behind an explicit debug option. Repair commands cover the sidecar, launch
agents, patched Squirrel registration, voice agent, and local model runtime.

### Configuration, Backup, And Restore

**Status: in development; YAML preview/apply and portable backup/rollback are
implemented and tested.**

`config/rag-ime.config.example.yaml` documents every importable setting and the
instant, knowledge, and voice provider slots. A user may create the ignored
`config/rag-ime.config.yaml`; import changes it to mode `0600`, previews all
changes, and moves supplied secrets into macOS Keychain without echoing them in
the response. Existing keys are preserved when a slot omits its secret.

A portable backup contains management settings, provider metadata without
secrets, the SQLite database (including memory, knowledge, plans, and Todos),
and safe Rime YAML/dictionary files. It deliberately excludes API keys, access
tokens, model weights, caches, logs/traces, and Rime binary user databases.
Restore validates every manifest entry, previews counts, snapshots current
state, applies migrations, and rolls the database, Rime files, and provider
metadata back if any step fails. The backup itself is not password encrypted.

## Architecture

```text
Pinyin composition
  -> Rime/librime
  -> patched Squirrel
  -> native composition panel and native commit

Post-commit assistance
  -> trusted foreground snapshot
  -> Python sidecar (/rime-suggest)
  -> local completion + local Hybrid RAG / memory
  -> source-aware Squirrel overlay
  -> Tab or Option+number
  -> feedback (/rime-select)

Explicit workflows
  -> RagImeControl.app
  -> local evidence and optional configured remote provider
  -> reviewed result, draft, or explicit insertion
```

Squirrel is the only real input-method frontend in this repository. The
versioned frontend gateway exists to isolate shared backend contracts, but this
project does not claim a Linux, Fcitx5, IBus, or second InputMethodKit runtime.
`RagImeControl.app` is the supported settings and diagnostics surface;
`RagImeVoice.app` is a headless voice agent rather than a second control center.

## Privacy And Safety

- Passive completion and retrieval are local by default.
- Secure Input, password fields, account-like fields, unknown privacy state,
  and stale focus fail closed before recording, retrieval, or model inference.
- Remote generation is limited to explicit workflows. Selected text or context
  leaves the Mac only after a user-configured action invokes that provider.
- Raw typing history is not silently promoted into searchable memory. Memory
  organization creates a validated draft that the user reviews, applies, or
  rolls back.
- Model weights, local databases, personal input history, API keys, build
  artifacts, and machine-local configuration must never be committed.

Review the source and the Web Control Center privacy settings before using
the project with sensitive material.

## Quick Start

### Requirements

- macOS 14 or newer for the native build and foreground verification route.
- Python 3.10 or newer.
- Xcode command-line tools; full Xcode is required to build patched Squirrel.
- Apple Silicon plus `mlx` / `mlx-lm` only when using the resident MLX
  predictor.
- A separately obtained local model checkpoint. Model weights are not included.

### Run The Core Locally

Run the test suite first:

```bash
python3 -m unittest discover -s tests
```

Initialize a local database and start the sidecar:

```bash
python3 -m rag_ime.cli init-db
python3 -m rag_ime.cli sidecar-server --host 127.0.0.1 --port 8766
```

For a deterministic demonstration that does not touch personal history:

```bash
python3 scripts/ime_first_demo.py seed --reset
python3 scripts/ime_first_demo.py verify --report output/ime-first-demo-report.json
python3 scripts/ime_first_demo.py reset
```

### Build The macOS Frontend

Prepare the pinned Squirrel checkout and build it with the project patch:

```bash
scripts/prepare_squirrel_workspace.sh
scripts/build_patched_squirrel.sh build
```

Build or install the only supported Control Center, the React app hosted by the
minimal WebKit shell:

```bash
scripts/build_control_center.sh
scripts/build_control_center.sh install
```

`build_control_center.sh install` updates only the Control Center app. For an
existing full installation, use the generation-checked stack installer so the
Sidecar, Agent gateway, MLX worker, voice agent, maintenance job, and visible
app cannot silently remain on different commits:

```bash
scripts/build_control_center.sh install-stack --include-squirrel
scripts/check_installed_product_components.py --require-current
```

The stack installer isolates each worker's copied Python package, records its
source commit, refuses dirty tracked source by default, and audits the complete
installed generation before returning success.

Installing an input method changes user-level macOS state. Use an attended
foreground session and verify the actual UI rather than trusting an HTTP
response:

```bash
scripts/doctor_squirrel_integration.sh
scripts/verify_squirrel_foreground_trace.sh
```

The optional voice lane, Active RAG provider, and Notion Worker each have
separate setup in the Web Control Center; none is required for the local
core.

## Validation And Release Gates

The project distinguishes backend evidence from real foreground behavior.
Passing tests or a health probe does not prove a visible, selectable candidate
in a foreground application.

```bash
python3 -m compileall -q rag_ime scripts tests
python3 scripts/check_import_boundaries.py
python3 scripts/check_product_status.py --json
python3 scripts/check_public_release.py --allow-blocked
python3 scripts/evaluate_deployed_rime_lexicon.py
python3 -m unittest discover -s tests
```

`check_public_release.py --allow-blocked` is intentionally a report while the
prototype is unfinished. A real release additionally needs a clean source
commit, foreground acceptance, Developer ID signing, notarization, stapling,
and a hash-bound `rag-ime.release-manifest.v2` that verifies the project
`LICENSE`, third-party notices, and exact patched Squirrel corresponding source.
See the [release-manifest template](release/release-manifest.example.json).

## Repository Map

| Path | Purpose |
| --- | --- |
| `rag_ime/` | Python sidecar, local RAG/memory core, model runtime adapters, management API, and release audit. |
| `squirrel-patches/` | Pinned Squirrel patch, Swift overlay, and patch application checks. |
| `control-center-web/` | React settings, diagnostics, knowledge, planning, and Agent UI. |
| `macos/RagImeControlWebHost/` | Minimal AppKit/WebKit host and allowlisted native bridge for the Web Control Center. |
| `macos/RagImeVoice/` | Headless push-to-talk agent, microphone pipeline, and cursor insertion. |
| `macos/Shared/` | Shared native Keychain and streaming-ASR protocol code. |
| `scripts/` | Build, install, runtime, evaluation, release, and foreground-verification commands. |
| `tests/` | Unit, contract, privacy, patch, release, and integration-style tests. |
| `eval/` | Synthetic public evaluation fixtures with no personal input history. |
| `release/` | Public-safe feature registry, product status, and release-manifest template. |
| `dataset/` | Public-safe demonstration and regression fixtures, not a production training corpus. |

## Scope And Non-Goals

- This is a macOS Rime/Squirrel experiment, not a general cross-platform IME.
- Rime remains authoritative during Pinyin composition; model and RAG output
  does not reorder native candidates or train the Rime user dictionary.
- Remote models are not permitted in passive per-keystroke completion.
- The repository does not redistribute trained model weights, personal typing
  history, or a production-scale training corpus.
- A public source repository and an unsigned engineering build are not proof of
  a distributable production input method.

## Contributing

Keep changes narrow, preserve the Rime/Squirrel foreground boundary, and add
tests for behavior, privacy, contracts, or patch application. Do not submit
credentials, personal typing history, local databases, model weights, generated
app bundles, or machine-specific defaults.

Before opening a pull request, run the validation commands above and verify UI
changes through the real Squirrel foreground path, not only preview fixtures.
When a change distributes or packages patched Squirrel, preserve the required
notices and corresponding source.

## License

Unless a file says otherwise, project-authored source is Copyright (C) 2026 7155 and
licensed under [GPL-3.0-only](LICENSE). GPL is a deliberate choice for
this project because its distributable macOS route includes a modified GPL-3.0
Squirrel app.

Third-party code, model weights, datasets, and remote services retain their own
terms. A patched Squirrel binary or source distribution must include the
applicable notices and exact corresponding source; see
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Acknowledgements

- [Squirrel](https://github.com/rime/squirrel) and
  [librime](https://github.com/rime/librime) provide the macOS frontend and
  Rime engine foundations.
- [Felix3322/Wisdom-Weasel](https://github.com/Felix3322/Wisdom-Weasel)
  informed the prediction lifecycle and candidate-panel direction; its
  implementation source is not copied into this repository without a separate
  provenance review.
- [MiniMind](https://github.com/jingyaogong/minimind),
  [MLX](https://github.com/ml-explore/mlx),
  [Ollama](https://github.com/ollama/ollama), and
  [llama.cpp](https://github.com/ggml-org/llama.cpp) inform or provide optional
  local model runtime boundaries.
- [OpenLess](https://github.com/Open-Less/openless) and
  [LazyTyper](https://github.com/oldcai/LazyTyper-releases) informed the voice
  interaction study. [Volcengine Doubao streaming ASR 2.0](https://docs.volcengine.com/docs/6561/1354869?lang=zh)
  is an optional configured provider.
- [Yuxi](https://github.com/xerrors/Yuxi) informed the document knowledge-base
  and knowledge-graph management workflow. The reference review used tag
  `v0.7.1.beta1` (`c765d904`), released under the MIT License. This project
  adapts the workflow to its existing local worker, SQLite storage, and Control
  Center design; it does not copy or redistribute Yuxi source code or import
  Yuxi's Neo4j/PostgreSQL/Milvus runtime stack.
