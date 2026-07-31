# 澄 — Personal Agent Workbench

> A local-first macOS workspace for persistent agents, Rooms, tools, governed
> memory, and optional input, voice, and browser assistance.

**Platform:** macOS 14+ | **Python:** 3.12+ | **License:** [GPL-3.0-only](LICENSE) | **Status:** public-source local prototype

Personal Agent Workbench combines private Agent Sessions, structured
multi-Agent Rooms, auditable Tool and Skill execution, Provider adapters,
governed local memory, and a native Control Center. `澄` is the user-facing
assistant identity. Input-method, voice, and browser integrations are optional
interaction surfaces around the same Agent runtime rather than the center of
the product.

The input path remains deliberately conservative: ordinary Pinyin composition
is still Rime's job, and remote generation is never used for passive
per-keystroke prediction.

> [!WARNING]
> The tracked source repository can be audited and built locally, but the
> project does **not** yet publish a release-ready macOS binary. Foreground
> input/voice/Accessibility acceptance, Developer ID signing, notarization,
> stapling, and the final release manifest remain open. Treat local builds as
> development installations.

## What It Does

| Capability | Current boundary |
| --- | --- |
| Agent Sessions and Providers | Each companion keeps a private, resumable Session. Pi adapters normalize configured Providers and models without exposing one protocol's private implementation to another. |
| Structured Rooms | A Room coordinates explicit participants, Tasks, Dispatches, handoffs, evidence, approvals, and terminal receipts while preserving each Session's private history. |
| Tools and Skills | Tools are progressively disclosed, policy-checked, approval-aware, and recorded as typed receipts. Skills are loaded for the current work stage instead of being dumped into every prompt. |
| Control Center | The native macOS workspace exposes conversations, projects, companions, memory, knowledge, planning, diagnostics, Provider settings, and bounded context inspection. |
| Governed memory | SQLite evidence, Atoms, Books, tags, projections, revision fences, and retrieval keep long-term context reviewable and reversible rather than silently rewriting chat history. |
| Optional interaction adapters | Patched Squirrel, push-to-talk voice, and Browser Co-pilot feed the same local workspace without owning Agent or memory semantics. |
| Pinyin composition | Rime/librime owns schemas, fuzzy Pinyin, paging, native candidates, and user-dictionary ranking. The sidecar must never replace its composition path. |
| Local completion | After a commit, a local MLX, Ollama, or loopback OpenAI-compatible runtime may offer short, source-marked continuations. `Tab` accepts the first suggestion and `Option+number` selects an ordinal; ordinary number keys stay with Rime or the host. |
| Explicit knowledge work | Selected-text assistance, long-form answers, memory organization, and configured remote generation are explicit Control Center workflows, not background typing behavior. |

## System Capabilities

The status labels below deliberately distinguish code presence from real macOS
foreground acceptance. "Implemented" does not mean that signing, notarization,
or every host application's text field has passed manual testing.

### Agent Workspace And Control Center

**Status: implemented for local development; signed distribution remains a
separate gate.**

The native Control Center is the composition surface for Agent Sessions,
Provider-qualified model selection, project-grouped conversations, companions,
Rooms, memory, knowledge, planning, voice, input assistance, and diagnostics.
Session history remains private; Room posts, Task handoffs, approval receipts,
and accepted evidence are projected into shared collaboration state. Managed
file and Diff results expand inline so the work stays in context instead of
opening an unrelated modal workflow.

### Rime Input

**Status: implemented; real foreground acceptance remains required.**

The optional input frontend is a single patched Squirrel/InputMethodKit route.
Rime continues to own Pinyin parsing, fuzzy Pinyin, paging, native candidates,
and the user dictionary. 澄 adds a source-aware assistant surface rather than
replacing Rime's decoder. Ordinary number keys stay with Rime/the host; `Tab`
and `Option+number` select assistant candidates. The Control Center can set
post-commit enablement, trigger/cooldown limits, candidate count, Tab policy,
and Option+number policy. Candidate count and trigger delay are projected only
into the application-owned Rime YAML block before an attended Squirrel reload;
user dictionaries and user-owned YAML remain outside that write boundary.

### Local LLM Prediction

**Status: in development; runtime integration and automated tests are present,
but candidate quality and foreground stability are still release gates.**

Passive post-commit prediction uses a local runtime such as MLX, Ollama, or a
loopback OpenAI-compatible server. It emits short continuations without sending
every keystroke to a remote model. The final prompt prioritizes the live input,
today's plan, complete recent inputs, and then budgeted RAG evidence; it asks for
bare continuation instead of an explanation or a copy of retrieved text.

The Control Center input page exposes the governed local-prediction settings:
registered hot model, local path, runtime profile, prompt mode, token cap,
sampling values, and post-commit latency budget. Saving records desired state;
the installed native host must then run the fixed `restart_predictor` action,
which updates the model registry, reinstalls MLX and Sidecar, and accepts the
change only after both health payloads agree. A browser build can edit through
the approved settings contract but cannot execute this local helper.

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
Each consumer owns a bounded projection instead of receiving one shared text
dump. Explicit generation prioritizes the current field, up to six planning
items, two approved Timeline tasks, four recent complete inputs, and six
governed Atom/Book grounding items. A new Agent Session receives one compact
bootstrap; later turns rely on Session history and on-demand `memory` calls.
Diagnostics report the number and estimated tokens actually injected for each
source.

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

Memory curation starts from an immutable evidence ledger rather than from the
retrieval index. Eligible evidence is limited to final user input, explicit
remember actions, applied tool receipts, and role-session compaction summaries.
Generated side candidates, assistant turns, screenshots, fixtures, and model
output are not memory sources. Once per day, each user, shared scope, or role is
curated independently within its project. Deterministic noise rules run first;
the configured organizer classifies the rest and can only create a review
draft. Apply and rollback move every covered source together, including all
low-level commits reconstructed into one Rime utterance.

Forgetting is a reversible evidence disposition, not source deletion. Restoring
rewinds the owner cursor so the evidence is classified again. Automatically
excluded sensitive input remains non-restorable; create a separate, redacted
explicit memory instead.

The maintenance runner uses this owner-scoped path by default. The previous
global compiler is retained only for compatibility and requires
`RAG_IME_LEGACY_MEMORY_BOOK_MAINTENANCE=1`.

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

Agent access remains one explicit, read-only `knowledge` tool. The graph is
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

### Session-Scoped Agent Context

**Status: implemented in the local Agent runtime; long-running policy and
review UX validation remain in development.**

Each Agent role has a versioned Role Book containing approved collaboration
style, evidence-backed capabilities, recent work with expiry, lessons, limits,
and commitments. A Session pins one approved revision, so the role cannot
silently change halfway through a conversation. Identity, permissions, safety
rules, tool allowlists, and approval levels remain outside the Role Book.

A new Session receives one query-free, budgeted bootstrap that can contain
stable preferences, current project tasks and goals, active Memory Books and
Atoms, recent cross-application timeline Books, and a small One Ring
conversation tail.
One-shot context is reserved before Runtime dispatch and is not reinjected on a
retry. Later turns use Pi's native Session history; long-term memory is read
only when the Agent explicitly calls `memory` in `current`, `historical`,
or `change` mode.

Chats, applied tool receipts, and accepted Room work are recorded as Evidence,
not facts. Daily maintenance produces a conversation digest plus separate user
memory and Role Book drafts. Explicit remember, correct, forget, and rollback
operations are hash-bound, approval-gated, lineage-aware, and projected
asynchronously through the durable outbox. Cross-application typing activity
continues through the separate `input_events` to daily Memory Book timeline,
so raw dialogue or typing history is never silently promoted into a system
prompt.

The bundled `rag-ime-memory-curator` skill follows the same authority boundary:
Evidence can support a Current Atom, Atoms can be organized into Topic Books,
and cross-App activity can become a reviewed Task Timeline. The skill may
prepare and apply governed memory proposals, but it cannot bypass native
approval or activate a Role Book revision.

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

Daily memory curation
  -> immutable final-input / receipt / compaction evidence
  -> owner + project cursor
  -> deterministic noise filter
  -> bounded organizer classification
  -> review draft
  -> apply or rollback
  -> owner-scoped retrieval documents
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
  evidence is classified daily, and semantic organization creates a validated
  draft that the user reviews, applies, or rolls back. Evidence can be forgotten
  and restored without deleting its audit trail.
- Model weights, local databases, personal input history, API keys, build
  artifacts, and machine-local configuration must never be committed.

Review the source and the Web Control Center privacy settings before using
the project with sensitive material.

## Quick Start

### Requirements

- macOS 14 or newer for the native build and foreground verification route.
- Python 3.12 or newer. The source uses PEP 701 f-string syntax that does not
  parse on Python 3.10 or 3.11.
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

Build or install the supported Control Center. The same React application runs
inside the minimal WebKit shell on the Mac and as a same-origin HTTP build on
the isolated Agent Gateway:

```bash
scripts/build_control_center.sh
scripts/build_control_center.sh install
```

`build_control_center.sh install` updates only the Control Center app. For an
existing full installation, use the generation-checked stack installer so the
Sidecar, Agent gateway, MLX worker, voice agent, maintenance job, and visible
app cannot silently remain on different commits:

```bash
scripts/build_control_center.sh install-stack --include-squirrel --include-pi
scripts/check_installed_product_components.py --require-current
```

The stack installer isolates each worker's copied Python package, records its
source commit, refuses dirty tracked source by default, and audits the complete
installed generation before returning success.

For the pinned Pi checkout, non-destructive native build walkthrough, local
installation variants, rollback command, and the separate source-public versus
signed-distribution gates, see [Build, Install, And Release](release/README.md).

### Review And Migrate A Legacy Memory Database

Historical curation is manual, copy-first, and fail-closed. Do not let a local
large model rewrite the production database. First export an immutable private
snapshot, make an explicit decision for every logical input and every existing
Atom, Book, and Phrase, and validate the complete manifest. Questions without a
durable assertion, workflow noise, failed receipts, duplicates, and one-turn
commands stay in Evidence/audit storage as `not_for_memory`; they do not become
Atoms, Books, Timelines, Phrases, or retrieval documents.

A production candidate additionally requires the configured embedding provider,
complete document/vector parity, caught-up projection checkpoints, an empty
failed/dead Outbox, and exact source fingerprints. No Timeline or Role Book draft
is auto-approved.

The `wisdom-weasel-rag-ime` value in the migration command below is a legacy
persisted project scope, not the current product name. Existing databases,
schema identifiers, `rag_ime` imports, and `RAG_IME_*` environment variables
retain compatibility until a separately versioned data migration can update
them without losing memory provenance.

```bash
DB="$HOME/Library/Application Support/RagIme/rag-ime.sqlite"
SNAPSHOT="/private/path/rag-ime-reviewed-source.sqlite"
EXPORT="/private/path/rag-ime-review-export.json"
MANIFEST="/private/path/rag-ime-review-manifest.json"
CANDIDATE="/private/path/rag-ime-reviewed-candidate.sqlite"
ROLLBACK="/path/to/rag-ime-before-semantic-v2.sqlite"

python3 scripts/review_memory_history.py export \
  --source "$DB" --snapshot "$SNAPSHOT" --output "$EXPORT" \
  --project wisdom-weasel-rag-ime --timezone Asia/Shanghai

# Review every exported logical input and existing memory item. Then assemble
# the reviewed parts and catalog audit into one complete manifest.
python3 scripts/review_memory_history.py assemble \
  --export "$EXPORT" --part /private/path/review-part-01.json \
  --existing-audit /private/path/existing-memory-audit.json \
  --output "$MANIFEST"
python3 scripts/review_memory_history.py validate \
  --export "$EXPORT" --manifest "$MANIFEST"

python3 scripts/apply_manual_memory_review.py \
  --source "$SNAPSHOT" --export "$EXPORT" --manifest "$MANIFEST" \
  --output "$CANDIDATE" --embedding-from-env

scripts/stop_rag_ime_runtime.sh
python3 scripts/activate_semantic_memory_candidate.py \
  --target "$DB" --candidate "$CANDIDATE" \
  --report "${CANDIDATE}.manual-review-report.json" --rollback "$ROLLBACK" \
  --confirm ACTIVATE_SEMANTIC_MEMORY_V2
scripts/build_control_center.sh install-stack --include-squirrel --include-pi --include-mlx
```

The activation report is bound to the candidate SHA-256 and all four reviewed
source fingerprints. They are revalidated immediately before the atomic
replacement, and the activated database is verified again afterward. Keep all
writers stopped from the final drift check through activation.

### Multi-Device Agent Gateway

The Agent Gateway remains a control-plane process on loopback `127.0.0.1:8768`.
It serves the production HTTP Control Center and the existing REST/SSE API from
one origin. Squirrel and the foreground typing path continue to use the
separate `127.0.0.1:8766` Sidecar; remote devices never enter that hot path.

For local development:

```bash
RAG_IME_CONTROL_TRANSPORT=http \
RAG_IME_CONTROL_BUILD_CHANNEL=production \
  scripts/build_control_center_web.sh
python3 -m rag_ime.cli agent-gateway \
  --host 127.0.0.1 \
  --port 8768 \
  --web-dist control-center-web/dist
```

To expose the already installed gateway to phones, tablets, and other Macs on
the same tailnet:

```bash
scripts/configure_agent_gateway_tailscale.sh enable --login you@example.com
scripts/configure_agent_gateway_tailscale.sh status
scripts/configure_agent_gateway_tailscale.sh disable
```

This route uses tailnet-only Tailscale Serve, never public Funnel. The gateway
accepts remote requests only when Serve supplies an allowlisted
`Tailscale-User-Login`; it then applies the canonical remote-safe route and
scope policy. Provider credentials, plugin installation, arbitrary files,
database apply operations, and input-method configuration remain local-only.
Session prompts and Room messages use durable `clientMessageId` receipts, so a
network retry cannot silently start the same Agent turn twice.

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

## Browser Co-pilot

The optional Chrome extension under `integrations/browser-copilot/` adds a
local, auditable browser lane without putting full pages into every Agent
prompt:

- the extension keeps compact multi-frame page snapshots in the existing local
  SQLite control plane;
- `browser` reads snapshots or screenshots on demand and sends write
  actions through the existing Agent approval flow;
- the Control Center exposes browser selection, visual and structured page
  views, site permissions, execution traces, pairing, and an isolated managed
  Chrome profile;
- first-time cross-origin navigation requests a site decision and asks the
  Agent to retry after approval; passwords are never included in snapshots.

The product installer copies the unpacked extension to
`~/Library/Application Support/RagIme/BrowserCopilot/extension`. Load that
directory once from `chrome://extensions` with Developer mode enabled.

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
| `integrations/browser-copilot/` | Local Chrome extension for compact page snapshots, screenshots, approved actions, and site-permission prompts. |
| `macos/RagImeControlWebHost/` | Minimal AppKit/WebKit host and allowlisted native bridge for the Web Control Center. |
| `macos/RagImeVoice/` | Headless push-to-talk agent, microphone pipeline, and cursor insertion. |
| `macos/Shared/` | Shared native Keychain and streaming-ASR protocol code. |
| `scripts/` | Build, install, runtime, evaluation, release, and foreground-verification commands. |
| `tests/` | Unit, contract, privacy, patch, release, and integration-style tests. |
| `eval/` | Synthetic public evaluation fixtures with no personal input history. |
| `release/` | Public-safe feature registry, product status, and release-manifest template. |
| `dataset/` | Public-safe demonstration and regression fixtures, not a production training corpus. |

## Scope And Non-Goals

- This is a local-first personal Agent workbench, not a hosted autonomous
  workforce, enterprise control plane, or general cloud Agent service.
- The native product currently targets macOS. The optional input adapter is a
  Rime/Squirrel experiment, not a general cross-platform IME.
- Rime remains authoritative during Pinyin composition; model and RAG output
  does not reorder native candidates or train the Rime user dictionary.
- Remote models are not permitted in passive per-keystroke completion.
- Room collaboration does not merge private Session histories. Only explicit
  Room posts, evidence, Tasks, handoffs, and receipts become shared state.
- The repository does not redistribute trained model weights, personal typing
  history, or a production-scale training corpus.
- A public source repository and an ad-hoc signed engineering build are not
  proof of a distributable macOS product.

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
- [VCPToolBox](https://github.com/lioensky/VCPToolBox) informed the live browser
  perception and human-Agent co-browsing direction. Browser Co-pilot is a
  project-native implementation built on this repository's existing approval,
  SQLite, Agent Tool, and Control Center contracts rather than copied VCP
  extension source.
