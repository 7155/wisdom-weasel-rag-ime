# PAW Trace And Evaluation

This document is the source-grounded contract and status map for Trace and
Eval. It describes the paths that exist in the current working tree; it is not
a claim that every path has passed installed foreground acceptance. A source
file, fixture, generated contract, or unit test is evidence at its own level
only. Runtime records, fresh checks, and foreground receipts remain the
authority for runtime and product claims.

## Product boundary

Trace is an inspectable execution record. Eval is a versioned judgment over
one or more immutable Trace references. Both are metadata-first and must keep
their authority explicit:

1. What public input, binding, and configuration entered the operation?
2. Which stages actually ran, in what order, and with what measured timing?
3. Which candidates or evidence were included, omitted, filtered, or redacted?
4. What later evaluation judged the result, with what truth source and
   evaluator?

Trace and Eval do not silently mutate production Memory, Knowledge, an index, a
threshold, or an Agent answer. An Eval score is advisory and cannot become its
own training or retrieval input through this surface.

## Current implementation map

The current data flow has three deliberate read branches. A journal projection
is used for ordinary Agent, Room, RAG, Memory, and Knowledge observations. A
source adapter is used when another owner has the authoritative lifecycle row
or bounded diagnostic frame. `TraceStore` retains an exact, validated terminal
envelope only when a producer creates the canonical Trace directly and its
temporary execution workspace will disappear.

```text
Session / Tool / Provider request / Room / Active RAG / Memory / Knowledge
Input generation lifecycle
        -> ObservationHub -> ObservationStore (metadata journal)
        -> envelope_from_observations()
        -> AgentService.observation_trace()
        -> observability.trace.get -> Trace UI

BrowserControl command row ------------------------------┐
Input prediction live frame -----------------------------┤
        -> source-owned adapter -> AgentService resolver -┘
        -> observability.trace.get (projectionSource=source_adapter)

Direct terminal Trace -> TraceStore (append-only)
        -> AgentService resolver
        -> observability.trace.get (projectionSource=trace_store)

Trace IDs -> evidence Eval -> EvalRunStore (append-only EvalRun records)

EvalScheduleStore -> AgentWakeScheduler's existing poll/tick executor
                   -> injected evaluator or built-in fixture evaluator
                   -> persisted EvalRun ID -> schedule lease settlement
```

The main implementation owners are:

| Concern | Current owner | Evidence anchor |
| --- | --- | --- |
| Common Trace, Eval, and Sandbox contracts | `rag_ime/trace_runtime.py` | `rag_ime/contracts/json/trace-envelope.v1.json`, `eval-run.v1.json`, `sandbox-run.v1.json` |
| Metadata journal and live observation projection | `rag_ime/observability.py` | `tests/test_observability.py` |
| Journal/source projections | `rag_ime/trace_adapters.py` | `tests/test_trace_adapters.py` |
| Trace API and source-authority selection | `rag_ime/agent_service.py`, `rag_ime/debug_server.py` | `tests/test_observability_trace_api.py` |
| Durable direct terminal Trace records | `rag_ime/trace_store.py` | `tests/test_trace_store.py`, `tests/test_database_migrations.py` |
| Durable EvalRun records | `rag_ime/eval_run_store.py` | `tests/test_eval_run_store.py`, `tests/test_observability_eval_api.py` |
| Manual evidence Eval | `rag_ime/evidence_eval.py` | `tests/test_evidence_eval.py`, `tests/test_observability_eval_api.py` |
| Periodic Eval lease and fencing | `rag_ime/eval_schedule_store.py` | `tests/test_eval_schedule_store.py`, `tests/test_eval_schedule_runtime.py` |
| Shared wake-loop execution | `rag_ime/agent_wake_scheduler.py`, `rag_ime/agent_service.py` | `tests/test_agent_wake_scheduler.py`, `tests/test_eval_schedule_runtime.py` |
| Vertical fixture manifests and checks | `rag_ime/vertical_agent_harness.py`, `rag_ime/vertical_agent_suite.py` | `tests/test_vertical_agent_harness.py`, `tests/test_vertical_agent_suite.py` |
| Isolated fixture RAG/Sandbox | `rag_ime/vertical_agent_sandbox.py`, `rag_ime/rag_benchmark_sandbox.py` | `tests/test_vertical_agent_sandbox.py`, `tests/test_rag_benchmark_sandbox.py` |
| External vertical-Agent Trace evaluation | `rag_ime/vertical_agent_suite.py` — `evaluate_vertical_agent_case_trace()` verifies a caller-produced terminal Trace, optionally persists it exactly through `TraceStore`, and persists its deterministic EvalRun through `EvalRunStore` | `tests/test_vertical_agent_suite.py`, `tests/test_eval_schedule_runtime.py` |

`AgentService.observation_trace()` first asks registered external resolvers
for a source-owned envelope. If none answers, it checks `TraceStore`, then
reads a bounded `ObservationStore` snapshot and projects it. The response
contract makes this choice explicit as `projectionSource: "source_adapter"`,
`"trace_store"`, or `"observation_journal"`; the UI must not infer authority
from styling or category labels.

`agent_context_runtime` and `control-center-web/src/paw-os/apps/PawContextTrace.tsx`
remain the context-assembly surface. They are linked by identifiers and are
not replaced by the observation journal projection.

## Authority and retention

`ObservationStore` is a durable SQLite journal of bounded, privacy-safe
metadata in `agent_observation_events`. It stores lifecycle identifiers,
status, names, summaries, timings when supplied, metrics, attributes, and
references. It does not store raw prompts, raw Memory/Knowledge text, hidden
reasoning, credentials, or unrestricted Tool results. The store prunes by a
configured age/count bound; the public snapshot is also limited to 500 items.

`ObservationHub` owns the projection queue, replay subscription, and fan-out.
Its projection queue is bounded and fail-open: if diagnostic backpressure
fills the queue, the primary Agent, Room, or Active RAG operation is allowed to
continue. Therefore the journal is authoritative for observations that it
accepted, but it is not a claim that every process-local diagnostic event was
captured.

`TraceStore` is a separate, narrow terminal authority in
`trace_envelopes`. It validates the canonical JSON shape, stores its SHA-256
and immutable payload, treats an identical replay as idempotent, and rejects a
reused identity with different content. Database guards forbid replacement,
update, and delete, and both code and schema reject `building`: an immutable
live Trace could otherwise never advance. The store has no Eval foreign key
and no retention/delete path. It does not copy source-owned Browser/Input rows
or replace the bounded Observation journal.

Source ownership is different from projection ownership:

- `BrowserControlService.trace()` and `.traces()` read the authoritative
  Browser command rows. `envelope_from_browser_trace()` ignores URL, page
  text, snapshot IDs, and result payloads, and projects only the redacted
  command lifecycle.
- `DebugServer` keeps a bounded process-local `_prediction_live_trace` ring
  (the newest 500 frames). `envelope_from_prediction_frame()` projects safe
  lane metadata only; it cannot recover a missing frame after process restart
  and does not fabricate a start/end duration.
- `AgentService.bind_external_trace_resolver()` is the seam for additional
  source owners. A resolver must return a canonical `TraceEnvelope` whose ID
  matches the request; it must not copy the source database into the journal.
- A journal row that happens to use a Browser or Input trace ID does not win
  over the source owner. The source adapter is selected first and the response
  says so explicitly.

## Common Trace envelope

`rag_ime/trace_runtime.py` defines `rag-ime.trace-envelope.v1`. Its required
shape is:

- `traceId`, `sourceKind`, terminal/building `status`, and immutable timestamps;
- `binding` for the strongest available `sessionId`, `turnId`, `roomId`,
  `runId`, or `sourceLoopId`;
- `input.fingerprint`, `input.contentPolicy`, and
  `input.normalization`;
- bounded `spans`, `evidence`, and `artifacts`.

The schema bounds a Trace at 256 spans, 2,048 evidence references, and 256
artifacts. `fingerprint_text()` uses SHA-256. The default input policy is
`hash_only`; `redacted` and `owner_local` are explicit alternatives, not
implicit permission to expose content.

Each span carries `spanId`, `parentSpanId`, `name`, status, start/end fields,
`durationMs`, `recorded`, `unavailableReason`, metrics, and safe attributes.
When `recorded` is true, duration must equal `endedAtMs - startedAtMs`. When it
is false, `durationMs` remains null and a reason is required. A measured zero
is `0`; it must not be converted to unknown. Parent IDs must refer to spans in
the same envelope.

Each evidence reference carries a stable ID, source kind/ref, source lane,
stage, disposition, named scores, rank-before/rank-after, and omission reason.
Evidence identity is unique within a stage. An omitted, filtered, or redacted
item must explain why. The envelope validator rejects silent loss of these
facts.

The envelope is the common contract. Usually it is an adapter output whose
lifecycle facts remain in the journal or source owner. A producer that owns a
complete direct terminal envelope may persist that exact envelope through
`TraceStore`; this exception does not authorize storing live/building
projections or copying another owner's database.

## Producer coverage

The following producer seams exist in the current source. “Covered” here means
that a producer-to-projection path and focused tests exist; it does not mean a
real installed user operation has been observed.

| Producer | Current path and payload boundary | Trace source authority |
| --- | --- | --- |
| Agent Session / Tool | `AgentEventProjectionService` calls `ObservationHub.enqueue_agent_event()`; `observe_agent_event()` maps turn, message, compaction, Tool, approval, and memory lifecycle events to bounded rows. Text deltas and hidden/raw fields are excluded. | `ObservationStore` journal |
| Provider request | Pi v1/v2 publish one content-free `provider_request_completed` or `provider_request_failed` receipt for each assistant Provider response, including intermediate Tool-call responses. The receipt carries the existing request identity plus reported provider/model, usage, and measured timing when available; prompt, completion, and error text are excluded. `observe_agent_event()` maps it to `provider.request`, and the Room projection deliberately does not create another task row. | Pi public Agent event projected into the `ObservationStore` journal |
| Room | `AgentRoomEventHub` is observed by `ObservationHub.enqueue_room_event()`; Room lifecycle, real dispatch/intercom/review/receipt/result relations, stable WorkItem identity, and terminal facts remain linked by `roomId`/`turnId`/refs. WorkItem evidence reuses safe opaque public refs; filesystem paths and URLs are omitted rather than transformed into replacement evidence. | `ObservationStore` journal plus Room stores for their own lifecycle truth |
| Active RAG | `DebugServer` binds `ActiveRagService` to `enqueue_active_rag_record()`; the producer publishes explicit context/retrieval/generation timing and stage outcome through a bounded whitelist. UI fallback status is separate from Trace outcome: cancellation emits only stages that actually started, retrieval/Provider failures remain failed, and a visible timeout stays running until the worker settles. Raw text and private monotonic anchors are excluded. | `ObservationStore` journal; retrieval refs remain source-owned |
| Session Memory recall | `AgentMemoryContextService._emit_recall_observation()` sends the bounded recall projection; `observe_memory_recall_record()` records recall identity, safe metrics, evidence stage, and fallback metadata. Empty success is explicit. A recall exception emits a metadata-only failed receipt and preserves the original error control flow. | `ObservationStore` journal; Memory stores remain Memory authority |
| Knowledge retrieval | The production Pi `knowledge.search` result carries a metadata-only `public_knowledge_tool_activity`; Pi v1/v2 merge it into the public Tool result and `observe_agent_event()` emits `knowledge.retrieval` with safe evidence refs. `KnowledgePromotionStore` receipts also enter through `observe_knowledge_retrieval_record()`. | Live Knowledge Tool result or Knowledge retrieval receipt/store; journal is the bounded observation projection |
| Memory maintenance | `ObservationHub.emit_memory_event()` records point observations for curation phases and keeps timing unavailable when no measured end exists. Agent memory lifecycle events also enter through `observe_agent_event()`. | Memory maintenance/curation stores; journal is a bounded projection |
| Input generation | `AgentSurfaceRuntime` emits a bounded start/terminal lifecycle through `enqueue_input_generation_record()`; the journal fences contradictory terminal states and the adapter preserves the real lifecycle phase if wall-clock time moves backward. Raw input and generated content are excluded. | `ObservationStore` journal |
| Browser | `BrowserControlService` publishes metadata-only lifecycle facts through its observer; `DebugServer._resolve_external_common_trace()` reads the command row and calls `envelope_from_browser_trace()`. | Browser command row, `projectionSource=source_adapter` |
| Input prediction | `DebugServer._record_prediction_live_trace()` maintains the local bounded ring; `/api/prediction/live-trace` and the external resolver call `envelope_from_prediction_frame()`. Raw input, preedit, candidates, and reason text are excluded. | Process-local prediction frame, `projectionSource=source_adapter` |
| Vertical fixture | `run_vertical_agent_self_test()` creates a common Trace directly from fixture retrieval and memory receipts; when the Runtime injects `TraceStore`, it persists that exact terminal envelope before the temporary workspace is removed. It does not pretend to be a production producer. | `TraceStore` for the injected scheduled/runtime path; otherwise caller-owned sandbox artifacts |

The same common envelope therefore supports the user-facing areas without
making Memory and Knowledge interchangeable. A Memory evidence ref must not be
rendered as a Knowledge document, and a Knowledge trace must state when
personal Memory was not queried.

## Installable vertical sandbox Connector

The first showcase keeps Package lifecycle and execution authority separate:

```text
vertical-agent-sandbox Pi extension
  -> session-scoped agent-tool-call: sandbox.run
  -> VerticalSandboxConnectorService in PAW Host
  -> WorkspaceHarness / macOS Seatbelt process receipt
  -> verify_vertical_trace
  -> TraceStore.persist
  -> EvalRunStore.persist
  -> SandboxRun linking both identities
```

`rag_ime/bundled_plugins/vertical-agent-sandbox/0.1.0/` contains only the
model-facing Tool registration and Gateway call. It has no process or database
access. `rag_ime/vertical_sandbox_connector.py` exposes only the checked-in
`sgg / fixture-v2` showcase; `examples/vertical_agents/sgg/agent.py` performs a
small local ledger lookup and emits one canonical Trace JSON object. PAW Host
then validates and persists the Trace/Eval chain, stores the linking
`SandboxRun`, and returns a bounded process receipt projection plus
`SandboxRun`, `traceId`, and `evalRunId`. Observability reads that Host ledger
through `GET /api/observability/sandbox-runs` and renders the compact
`SandboxRun → Trace → EvalRun` chain; only the existing Trace destination is a
link, so the UI does not invent an Eval route.

Focused source tests cover the Package catalog, Gateway routing, connector
assembly, SandboxRun persistence, Trace/Eval persistence, the read projection,
and the Observability chain. The current
Codex process cannot apply a nested Seatbelt profile (`sandbox_apply` exits 71),
so this checkout does not claim an installed Package, a successful foreground
Seatbelt run, Docker isolation, arbitrary third-party code, or production
Memory/Knowledge quality. Those remain Runtime/foreground acceptance work.

Bindings aggregate only unambiguous safe identifiers. A Trace may carry
`workItemId` and `caseId` when every contributing observation agrees. Room turn
relations are emitted only from explicit `acceptedTurnId` or `sourceTurnId`
evidence; participant proximity and matching prose never invent a related
Trace edge.

## Trace adapters and observation windows

`envelope_from_observations()` is a pure adapter over a bounded journal list.
It orders observations by explicit sequence where available, aggregates
parented spans/evidence/artifacts, and preserves unavailable timing instead of
spreading a terminal timestamp across invented stages. Memory maintenance and
Room root reducers may derive a terminal status from known lifecycle children;
they mark that derivation and do not turn it into measured latency.

`observation.trace.get` returns the canonical envelope plus an observation
window. For a journal projection, the window contains sequence bounds,
`resumeToken=observation:<sequence>`, and a next-before cursor when truncated.
A truncated window forces the projected Trace to `building`; it cannot be
evaluated as a completed Trace. For a source adapter, the window is explicit
with `resumeToken=source:<traceId>` and zero journal sequences. A durable
terminal row uses `resumeToken=trace-store:<traceId>`, zero journal sequences,
and `truncated=false`.

Current backend routes are declared in
`rag_ime/control_api/route_policy.py` and `route_table.py`:

- `GET /api/observability/traces/{traceId}` (and the read-scoped gateway route)
  is read-only and remote-safe under the Agent read scope;
- `GET /api/observability/snapshot` and the observation subscription expose
  bounded journal navigation;
- `GET /api/prediction/live-trace` is local Input diagnostics, not a durable
  user-input archive.

The frontend transport and feature use the canonical route IDs and generated
contracts in `control-center-web/src/features/observability/api.ts`,
`control-center-web/src/features/observability/index.tsx`, and
`control-center-web/src/contracts/generated/`. The current Observability
surface can display a Trace and its Eval records. Room consumes the same stable
identity vocabulary for its task sheets, satellites, and relation projection;
Trace remains the inspection surface rather than a second Room conversation.

## Eval contract and truth boundary

`rag_ime/trace_runtime.py` defines `rag-ime.eval-run.v1`. An EvalRun records:

- `evalRunId` and one or more unique `traceIds`;
- optional `suiteBinding { suiteId, suiteRevision }`; scheduled built-in runs
  must carry the exact claimed binding, while manual evidence Eval remains
  compatible without one;
- `mode`: `ground_truth` or `ai_judge`;
- `metricAuthority`, truth status/dataset/label revision;
- evaluator provider/model/thinking/display identity;
- metrics, status, and creation/update timestamps.

The constructor and validator enforce the following separation:

| Mode | Truth | Allowed metrics | Authority |
| --- | --- | --- | --- |
| `ground_truth` | `human` or `frozen`, with dataset and label revision | deterministic metrics such as precision, recall, F1, Recall@K, MRR, and nDCG@K | `ground_truth` |
| `ai_judge` | `none` | relevance, coverage, groundedness, contradiction, and confidence estimates | `ai_judge_estimate` |

An unlabelled result cannot be called accuracy, precision, recall, or F1. A
failed/unavailable Judge does not receive an estimated score. AI Judge runs
must carry an explicit, complete evaluator identity (`provider`, `model`,
`thinking`, and `displayName`); the contract does not fabricate a default and
an evaluator record alone is still not evidence that a Provider was called.

`rag_ime/evidence_eval.py` currently implements the deterministic evidence-set
path. It validates completed Trace envelopes, requires an exact Trace/label
set, computes precision/recall/F1 over included evidence IDs with an explicit
zero-denominator policy, and derives a content-based idempotent EvalRun ID.
It intentionally has no AI Judge call.

## Durable EvalRun persistence

`EvalRunStore` is append-only local SQLite persistence. `persist()` validates
the full EvalRun, stores its canonical JSON and payload hash, and indexes each
Trace ID in `eval_run_trace_refs`. Repeating the same `evalRunId` and content
returns the existing record; rebinding that identity to different content
raises `EvalRunConflict`. `get()`, `list()`, `for_trace()`, and
`recent_for_trace()` return validated records, not UI-only summaries.

`AgentService.observation_evals()` exposes bounded privacy-safe summaries for
one Trace. `evaluate_observation_evidence()` first obtains the authoritative
Trace, rejects a truncated/building window, runs the deterministic evaluator,
and persists the actual EvalRun. The frontend lists those records and can
submit the human-label request through
`observability.evals.evidence.run`. The POST route is deliberately local-only;
the read list is Agent-read scoped and remote-safe.

## Periodic fixture Eval through the shared wake loop

The current periodic path is intentionally small but real at the source/test
level:

1. `EvalScheduleStore` validates `suiteId`, required `suiteRevision`, daily or
   weekly recurrence, due time, run bounds, and lease bounds.
2. An atomic `claim_due()` creates a schedule run ID and lease token. The store
   fences stale tokens, recovers expired leases as structured
   `lease_expired`, and advances the next due state only on a valid settlement.
3. `AgentService` connects `EvalScheduleRunner.run_due_once()` to the existing
   `AgentWakeScheduler` `on_tick` callback. No second daemon or Eval poller is
   created.
4. The wake scheduler submits maintenance to its existing
   `ThreadPoolExecutor` and does not wait inside `run_due_once()`. It permits
   at most one in-flight maintenance future; `close()` waits for the same
   executor. A slow Eval callback therefore does not block wake claim/dispatch
   and is not duplicated by subsequent polls.
5. The injected executor must return a mapping containing only a real,
   already-persisted `evalRunId` for success. `EvalScheduleRunner` loads that
   EvalRun and requires its `suiteBinding` to equal the claimed `suiteId` and
   `suiteRevision`; a missing run, missing binding, wrong suite, or wrong
   revision settles as a structured error and never fabricates success.
6. The built-in bridge scopes Trace/Eval identity and timestamps to the
   scheduler-owned `runId` and `dueAtMs`. Different claims therefore retain
   independent history, while replaying the same claim after a recoverable
   boundary is idempotent.
7. `bind_eval_schedule_executor()` remains available for a Runtime-owned
   evaluator. The seam does not grant implicit Provider, Memory, or Knowledge
   write authority.

An external vertical Agent can use the same seam after it has produced its own
completed canonical Trace. `evaluate_vertical_agent_case_trace()` verifies the
manifest-declared span and evidence requirements without running the fixture
sandbox, optionally persists that exact terminal Trace through `TraceStore`,
and persists the deterministic EvalRun with the exact `suiteBinding` through
`EvalRunStore`. The custom schedule executor returns only the persisted
`evalRunId`; `EvalScheduleRunner` then applies the existing exact-binding
check. The focused schedule test exercises this callback wiring through one
due claim in the current process. It does not prove an external Agent ran,
that a resident schedule fired, or that installed Runtime/foreground paths
are active.

When no custom executor is bound, the current `AgentService` default is the
allowlisted fixture bridge in `rag_ime/vertical_agent_suite.py`. It resolves
only checked-in registered manifests (currently `sgg` and
`zhanggui-wenshu`) and requires each manifest's exact declared revision
(currently `fixture-v2`). It runs inside a caller-owned temporary workspace,
persists the fixture's terminal Trace through `TraceStore` and its real EvalRun
through `EvalRunStore`, then returns only `{"evalRunId": "..."}` to the
schedule runner. Unknown suite IDs, missing revisions, revision mismatches,
fixture failures, and persistence failures map to stable error codes.

The schedule-run read projection resolves a succeeded run's persisted EvalRun
and returns at most 64 `traceIds`, with an explicit truncation bit. The Control
Center renders those IDs as links back to the canonical Trace instead of
leaving the EvalRun receipt as unresolvable text.

This establishes a shared-loop source seam and lease behavior. It is not proof
that the installed resident Gateway has fired a due schedule; that requires a
live Runtime receipt with the schedule claim, lease settlement, and persisted
EvalRun ID.

## Vertical Agent sandbox: sgg and 掌柜问数

The checked-in examples are:

- `examples/vertical_agents/sgg.json` and its public sales fixture;
- `examples/vertical_agents/zhanggui-wenshu.json` and its public orders-ledger
  fixture.

`validate_vertical_manifest()` requires a suite revision, declared Trace span
and evidence checks, deterministic truth, a fixture-contained document path,
fixture Memory identity, and a sandbox policy with blocked network and
`productionWriteBlocked=true`.

`run_vertical_agent_self_test()` executes real local lexical retrieval through
`RagBenchmarkSandbox`, builds a common Trace with RAG and fixture-memory
evidence, runs deterministic ground-truth evaluation, builds a
`rag-ime.sandbox-run.v1`, and writes bounded artifacts below the provided
workspace. `RagBenchmarkSandbox` uses inline checked-in fixture text only; it
does not open arbitrary host paths, the production Knowledge root, or the
production Memory store. The fixture memory item is a receipt, not a production
Memory write. The sandbox policy is local/staged with network blocked.

`run_vertical_agent_self_test_suite()` keeps each example in an isolated child
workspace and reports identifiers, metrics, `providerCalls`, and the truthful
`productionWriteBlocked` flag. The scheduled bridge uses a managed temporary
workspace, so its report and fixture artifacts are temporary. Before that
workspace is removed, the bridge persists the exact terminal Trace through
`TraceStore`; `EvalRunStore` independently retains the EvalRun, and the
schedule retains its real EvalRun ID. Each scheduler claim gets a bounded
run-scoped identity; a replay of the same claim remains idempotent, while the
next recurrence creates a distinct Trace/Eval pair.

This fixture path is separate from `evaluate_vertical_agent_case_trace()`: the
latter accepts a completed Trace produced by an external vertical Agent,
verifies it against the selected manifest, optionally retains the exact
terminal envelope in `TraceStore`, and creates the manifest-bound EvalRun in
`EvalRunStore`. It does not execute the Agent, call the fixture runner, or
open production RAG, Memory, or Knowledge stores.

This is a builder-facing fixture self-test. It is not production RAG
acceptance, production Memory/Knowledge acceptance, Provider acceptance,
AI-Judge acceptance, or foreground acceptance. Passing fixture metrics do not
authorize a production write or establish that a vertical Agent can build and
ship an application by itself.

## UI and Room boundary

The current Trace UI has one bounded detail surface: identity/status/binding,
parented stage rows, public span attributes and metrics, evidence disclosure,
and Eval list/manual evidence submission. Eval summaries preserve an optional
exact `suiteBinding`, so a result can show the vertical suite and revision that
actually produced it. Long values remain collapsed/redacted and source
authority is labelled as journal, source adapter, or persisted terminal Trace.
Local text search filters the left event timeline without deleting other
already-loaded steps from the selected Trace. Periodic run receipts link their
bounded persisted Trace IDs back into the same surface.

The same Eval panel also exposes a one-shot vertical-Agent self-test. It selects
one registered suite and its registry-owned revision, then creates a normal
`maxRuns=1` due schedule for the existing Runtime wake loop. This is deliberately
the same execution path as periodic Eval rather than a second UI-only runner;
the selected schedule shows its state, persisted EvalRun ID, and associated
Trace links. The Preview transport includes a stateful `sgg`/
`zhanggui-wenshu` fixture projection so this interaction and the full
Trace/Eval information hierarchy can be reviewed as showcase UI. Preview data
is demonstration data, not evidence that the installed Runtime executed the
suite.

The Room source now projects each top-level user turn as one stable,
scrollable/collapsible task sheet whose planet rows update in place. A row
opens the canonical Partner satellite; the satellite is read-only and sends a
continuation back to the Room composer prefilled for that Partner. The second
top-right collaboration mode opens all Runtime-active planets, and the
relation view uses only explicit dispatch, handoff, review, receipt, result,
and `@` evidence. Retries retain their logical sheet identity instead of
creating another interleaved message stream. These paths have focused source
tests, but no installed foreground visual acceptance is claimed.

The PAWOS desktop source also projects real Session and Room objects into
expandable project folders keyed by `workspaceRoots`. Folder rows show public
Session preview or real Room WorkItem progress and open the canonical object;
missing Room records are not synthesized. This is an OS-style visual
projection only: it does not create transcript files, Finder entries, or Git
content. Control-island and project-island settings art remains future design
work.

## Evidence commands and interpretation

Keep verification proportional to the changed seam. Useful small checks are:

```bash
python3 -m unittest <one-focused-test-name>
python3 scripts/run_vertical_agent_self_tests.py --app sgg --output-root <new-empty-directory>
node scripts/generate_control_center_contracts.mjs --check
git diff --check
```

The frontend source/test anchors are
`control-center-web/src/features/observability/observability-feature.test.tsx`,
`control-center-web/src/platform/routes.test.ts`, and
`control-center-web/src/platform/http-transport.test.ts`. Generated TypeScript
contracts must be checked against the JSON contracts; a source-level frontend
test or typecheck is not an installed foreground result. A broad matrix is not
the default gate for each small change.

On 2026-08-28, the CLI product path above was run once for `sgg` and once for
`zhanggui-wenshu` in separate temporary output roots. Each run completed 1/1
with precision/recall/F1 of 1.0, `providerCalls=0`, and
`productionWriteBlocked=true`. This is execution evidence for the checked-in
fixture harness only; it is not a production Provider or installed-app result.

## Uncovered acceptance boundaries

The following remain explicit verification work, not implied by the paths
above:

- a real production Provider request and its truthful provider/model receipt;
- complete production RAG retrieval stages, production Memory recall/curation,
  and production Knowledge retrieval all emitting their intended spans and
  evidence on a live operation;
- an AI Judge execution with an actual configured provider, independently
  labelled as an estimate;
- a live resident due schedule firing from the installed Agent Gateway,
  including restart recovery and the final persisted EvalRun ID;
- installed-runtime proof that a due fixture schedule survives its temporary
  workspace and the exact persisted Trace/EvalRun pair remains readable after
  a service restart;
- installed foreground navigation from Agent/Memory/Knowledge/Room to Trace and
  back;
- installed foreground Room acceptance for task-sheet scrolling/folding,
  in-place updates, all-active collaboration satellites, canonical Partner
  navigation, and explicit-relation gravity;
- installed foreground acceptance for the PAWOS-only project-folder desktop;
  Finder/Git mirroring is explicitly not part of this requirement;
- control-island/project-island settings art and the remaining Room visual
  polish.

The external vertical-Agent Trace helper and its injected schedule callback
are source/test seams only. No external Agent execution, production
RAG/Memory/Knowledge operation, resident schedule firing, installed Runtime,
or foreground Trace/Eval interaction is claimed here.

Do not convert fixture/source/test evidence into a claim of production
Provider, production RAG/Memory/Knowledge, installed schedule, or foreground
acceptance. The next acceptance receipt should identify the exact producer,
Trace ID, EvalRun ID, source authority, runtime process, and UI path that was
actually exercised.
