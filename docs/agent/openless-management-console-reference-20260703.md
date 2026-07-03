# OpenLess Management Console Reference

Snapshot:
- Reference repo: `/tmp/rag-ime-openless`
- Reference commit: `28a52e949bd3b533dfcb2c8d36dad4ddc58467af`
- Reference upstream: `https://github.com/Open-Less/openless.git`
- Date: 2026-07-03

Status:
- Deferred. This is a later management-console reference only.
- Current architecture work must first follow `Felix3322/Wisdom-Weasel`.
- Do not spend implementation time on OpenLess-style UI until the Felix/Squirrel/Wanxiang foreground IME route is usable.

## Decision

OpenLess is useful as a reference for the future RAG-IME management console, not for the foreground IME candidate window.

The product split should stay:

```text
Foreground typing path:
  Squirrel/Rime/Wanxiang -> RAG-IME sidecar -> compact candidate list

Management and observability path:
  local sidecar APIs / SQLite traces -> desktop console -> history, memory, RAG, model, settings
```

The management console must never sit on the keystroke critical path. If it is slow or closed, typing must still work.

## OpenLess Architecture Observed

OpenLess is a Tauri 2 desktop app:

```text
React/TypeScript UI
  -> typed IPC wrapper modules under src/lib/ipc/
  -> Tauri commands under src-tauri/src/commands/
  -> Rust coordinator/state/persistence/provider modules
```

Useful source paths:

- `openless-all/app/src-tauri/src/lib.rs`: backend module map and Tauri command registration.
- `openless-all/app/src-tauri/src/coordinator.rs`: single coordinator that owns session state and wires hotkeys, ASR, polish, insertion, persistence, and events.
- `openless-all/app/src-tauri/src/coordinator_state.rs`: pure state-transition layer, independent from Tauri and system IO.
- `openless-all/app/src-tauri/src/persistence/history.rs`: history store with newest-first list, retention, update, delete, and clear.
- `openless-all/app/src-tauri/src/persistence/dictionary.rs`: dictionary store with enabled flags and hit counting.
- `openless-all/app/src-tauri/src/commands/history.rs`: small IPC command surface for history.
- `openless-all/app/src-tauri/src/commands/dictionary.rs`: small IPC command surface for vocabulary/corrections.
- `openless-all/app/src/lib/ipc/`: frontend IPC wrappers split by domain.
- `openless-all/app/src/pages/History.tsx`: searchable history UI with detail pane and resilient error handling.
- `openless-all/app/src/pages/Vocab.tsx`: vocabulary/correction management UI.
- `openless-all/app/src/pages/Overview.tsx`: operational summary derived from history and provider status.
- `openless-all/app/src/components/FloatingShell.tsx`: desktop shell with navigation, settings modal, and page tabs.

## Reuse For RAG-IME

### 1. Keep A Separate Desktop Console

Do not turn the IME candidate panel into a debug dashboard. The candidate panel should stay small and fast.

RAG-IME should add a separate local management app later:

```text
RAG-IME Console
  Overview
  Live Session Timeline
  Candidate Trace
  Memory Store
  RAG Sources
  Model / MLX Status
  Ranking / Feedback
  Settings
  Evaluation
```

This console can be built with Tauri + React/TypeScript or SwiftUI. Tauri is attractive because it matches OpenLess's proven shape: native desktop shell, local files, events, and typed IPC.

### 2. Make The Sidecar The Observable Backend

OpenLess has one coordinator that owns the live session. RAG-IME should mirror that idea in the sidecar:

```text
Squirrel frontend event
  -> sidecar request
  -> PredictionManager
  -> CandidatePool
  -> Memory/RAG/MLX lanes
  -> Ranker
  -> trace event + candidate response
```

The console should observe this backend through local APIs, not by scraping candidate UI.

Suggested local APIs:

```text
GET  /api/health
GET  /api/live-session
GET  /api/timeline?limit=200
GET  /api/candidates?session_id=...
GET  /api/memories?q=...
GET  /api/rag-sources?candidate_id=...
GET  /api/model/status
GET  /api/ranking/explain?candidate_id=...
POST /api/settings
POST /api/eval/run
```

### 3. Split Pure State From IO

OpenLess keeps `coordinator_state.rs` as a pure state-transition layer. RAG-IME should keep the following modules pure and testable:

```text
InputStateManager
PredictionManager
CandidatePool
SuggestionCompiler
CandidateRanker
FeedbackModel
PinyinConstraintMatcher
```

Squirrel, MLX, SQLite, and future Tauri UI should be adapters around those modules.

### 4. Use Domain IPC Clients

OpenLess frontend does not call raw `invoke()` from every page. It wraps domains under `src/lib/ipc/`.

RAG-IME console should mirror that:

```text
src/lib/api/health.ts
src/lib/api/sessions.ts
src/lib/api/candidates.ts
src/lib/api/memory.ts
src/lib/api/rag.ts
src/lib/api/model.ts
src/lib/api/settings.ts
src/lib/api/evals.ts
```

This matters because the console will grow quickly. A single mixed `api.ts` will become unmaintainable.

### 5. Make History And Feedback First-Class

OpenLess history is visible, searchable, deletable, and exportable. RAG-IME needs the same visibility for typed text and prediction decisions:

```text
input_context
composition / anchor
visible candidates
candidate source: rime / llm / rag / memory
score breakdown
accepted candidate
skipped candidates above the accepted row
latency by lane
RAG evidence ids
model prompt hash / output hash
```

This is how we explain why a candidate appeared and why repeated phrases become higher-ranked.

### 6. Use Events For Live Status

OpenLess emits events such as state, credentials, vocab updates, local model progress, and device changes.

RAG-IME should emit sidecar events or stream trace records:

```text
candidate_request_started
memory_query_started
rag_query_finished
mlx_first_candidate
ranking_finished
frontend_response_applied
candidate_selected
candidate_rejected_or_skipped
stale_response_dropped
```

The management console can subscribe and render a live timeline without touching the IME panel.

### 7. Keep Local Model Management Visible

OpenLess exposes local ASR model status in settings. RAG-IME should expose:

```text
MLX model path
loaded / unloaded
first-token latency
tokens per second
prompt-cache support
candidate batch size
embedding provider status
SQLite / FTS / vector index status
last indexing time
```

This directly supports the project's interview story: local-first privacy, low-latency MLX, and debuggable RAG.

## Do Not Reuse Directly

Do not migrate these OpenLess parts into the IME core:

- ASR-specific recorder/coordinator code.
- Speech polishing modes as-is.
- Mobile/Android overlay code.
- Cloud provider setup UX as the default path.
- A Tauri webview as the foreground IME candidate window.
- Streaming insertion logic for our candidate panel. RAG-IME foreground still belongs to Squirrel/Rime.

## Proposed RAG-IME Architecture With Console

```text
                         +------------------------------+
                         | RAG-IME Management Console   |
                         | Tauri/React or SwiftUI       |
                         | - Overview                   |
                         | - Live timeline              |
                         | - Candidate trace            |
                         | - Memory/RAG explorer        |
                         | - Model/settings/evals       |
                         +---------------^--------------+
                                         |
                                  local API/events
                                         |
+-----------------+      +--------------+---------------+
| Squirrel/Rime   | ---> | RAG-IME sidecar/core         |
| Wanxiang schema |      | - InputStateManager          |
| candidate panel | <--- | - PredictionManager          |
+-----------------+      | - CandidatePool              |
                         | - SuggestionCompiler         |
                         | - Ranker/FeedbackModel       |
                         +-------+----------+-----------+
                                 |          |
                         +-------v--+   +---v-----------+
                         | SQLite   |   | MLX worker    |
                         | memory   |   | Qwen small LM |
                         | FTS/RAG  |   | candidate gen |
                         +----------+   +---------------+
```

Foreground constraints:

- Candidate window only shows directly selectable text.
- No paragraphs or evidence dumps in the IME panel.
- No always-on stale panel.
- Numeric keys are consumed only when a live displayed candidate maps to the current session.

Console constraints:

- May show paragraphs, evidence, traces, prompts, latencies, and failure reasons.
- May be slow, reloadable, or closed without affecting typing.
- Must not be required for normal IME use.

## Near-Term Implementation Boundary

Current P0 still remains:

```text
Build/install branded Squirrel route
Verify real foreground trace
Make LLM/RAG/memory candidates selectable and non-stale
```

The OpenLess-inspired console is a P2/P3 layer after the foreground IME is usable.

When we add it, start with a read-only console against existing sidecar trace APIs before building any setting mutators.
