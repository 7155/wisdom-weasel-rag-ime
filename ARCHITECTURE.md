# Architecture

Personal Agent Workbench is a local-first macOS Agent workspace with governed
memory, retrieval, Tools, multi-Agent Rooms, and optional input, voice, and
browser assistance.

This document describes source ownership and dependency direction. It does not
claim that an unsigned development build has passed foreground, notarization,
or clean-machine distribution gates.

## Design Principles

- Explicit Agent work is the product center; input assistance is one adapter.
- Rime owns Pinyin composition, native candidates, paging, and fallback.
- Passive prediction and retrieval stay local by default.
- Remote Providers are used only by explicit, configured workflows.
- Transport parses and projects; application services own use cases.
- Session, Room, Tool, Provider, and persistence state have explicit owners.
- Durable events and receipts are evidence; model prose is not execution proof.
- New abstractions must hide a real dependency, localize a real extension, or
  make a real failure easier to diagnose.

## System Map

```text
explicit control path
  React Control Center
    -> HTTP or allowlisted WKWebView native bridge
    -> route policy + route adapter
    -> application service
    -> memory / knowledge / planning / Agent owner
    -> SQLite, local runtime, or explicitly configured Provider

Agent path
  Session prompt
    -> bounded memory and task context
    -> runtime-neutral AgentRuntimeDriver
    -> Pi protocol adapter
    -> Provider and Tool calls
    -> durable observations, receipts, and Session history

Room path
  opening user bytes
    -> immutable RequirementAnchor + explicit-user RequirementItem with source span
    -> default or opening-@ Facilitator -> align Dispatch
    -> stage-resident alignment-and-decision Skill
    -> no clarification: direct definition/action intent
    -> clarification needed: one question/user-message resume at a time
       -> aligned summary -> chronological 开始行动
    -> room_define atomically fences intake and binds one catalog revision
    -> new Facilitator ExecuteDispatch + implementation-execution Skill
  -> Facilitator decomposition/assignment -> bounded peer Worker Dispatches
  -> Facilitator integration -> optional distinct review -> Kernel settlement
  -> one ReportDispatch -> facilitator/reporter-only public summary
  -> reporter receipt + runtime quiescence -> completed

Participant Session/Dispatch ownership is separate from filesystem roots. Each
participant acts only through its bound workspace harness and evidence receipts.

optional input path
  keyboard
    -> Rime/librime
    -> patched Squirrel
    -> local sidecar /api/rime-suggest
    -> local completion + governed retrieval
    -> source-aware assistant overlay

The Facilitator decides whether review is warranted; the Kernel owns any review
handoff and delivery settlement. Model prose, a filesystem path, or a
participant's private Session cannot settle a Root.
```

### Room Collaboration

```text
opening user bytes
  -> RequirementAnchor + explicit-user RequirementItem with source span
  -> default/opening-@ Facilitator + align Dispatch
  -> required alignment-and-decision Skill
  -> no material choice: define directly
  -> material choice: room_commit(wait) -> chronological user answer(s)
     -> aligned summary -> 开始行动
  -> room_define (idempotent catalog/work binding + intake fence)
  -> new Facilitator ExecuteDispatch + implementation-execution Skill
  -> Facilitator chooses one Worker or independent bounded children
  -> Worker evidence -> Facilitator-owned integration workspace
  -> optional distinct Reviewer handoff after integration
  -> work quiescence -> one ReportDispatch -> facilitator-only final
  -> reporter receipt + runtime quiescence -> completed
```

Personal Agent Workbench is the authority for this sequence: its Room Kernel,
Room contracts, durable snapshots/events, and managed Pi Skills define the
state transitions and public/private boundary. The sequence is intentionally
not a model-only checklist. The opening user bytes remain immutable evidence,
and later user answers append anchors/items under the same Root.

The align Dispatch requires the governed `alignment-and-decision` Skill. It
first inspects reachable facts and may conclude that no material user choice is
missing; in that branch the opening request authorizes action without another
confirmation. During material clarification, `room_commit(wait,
waitingFor=user)` publishes one structured question (and optional choices).
While that wait is pending, the next ordinary user Room message is the answer:
it appends one source anchor/item revision, publishes the chronological user
post, and resumes at most once for `(rootId, questionId, answerRevision)`. The
same Root may resume for later questions. After the final answer, the
Facilitator summarizes the result and waits for the chronological user message
`开始行动`. `room_post` is not a second clarification channel.

Only the active align authority may call `room_define`, after the existing Tool
discovery path has disclosed and loaded it. The call is atomic and idempotent:
it creates or confirms the immutable RequirementCatalog revision, binds final
requirements and observable acceptance criteria to the existing Root/Task,
creates or confirms one facilitator-accountable root WorkItem, completes and
fences the intake Dispatch, and records the transition receipt. The Kernel then
creates a new Facilitator ExecuteDispatch with a new lease/capability epoch. Its
managed Pi Session requires `implementation-execution`; the old align Dispatch
never gains execute Tools and late calls fail closed.

After that definition/ExecuteDispatch transition, the Facilitator owns decomposition, assignment,
reassignment, dependency handling, integration, and the final report:

- Keep a small coherent change with one Implementer. Create multiple child
  WorkItems only when at least two slices are genuinely independent, have no
  unmet prerequisite, and parallel execution materially reduces waiting.
  Dependencies remain explicit; dependent slices stay serial.
- Use directed Kernel Dispatches for assignments to existing Room members.
  Do not use round-robin selection, free-text `@` mentions, or an unannounced
  roster expansion as assignment authority. A Worker may reject an assignment
  with a structured reason; the Facilitator repairs or reassigns it.
- `room_collaborate` is only the bounded, non-overlapping implementation-child
  path after definition and handoff. It is never intake fanout, assignment
  by mention, review, or a substitute for a Kernel handoff.
- Read-only work may share a Root baseline. Concurrent writable Workers need
  separately receipted isolated workspaces based on that baseline, while one
  Facilitator-owned workspace is the authoritative integration point. Do not
  infer isolation or automatic Git worktree cloning from a path.
- Workers return artifacts and evidence to the Facilitator. The Facilitator
  integrates accepted results before any review decision. Review is risk-based:
  if warranted, the Kernel hands the existing WorkItem to a distinct
  participant after integration; the reviewer cannot review its own or the
  Integrator's work, and failure returns the WorkItem for repair. Review is not
  mandatory for every task.
- The Kernel validates evidence, permissions, terminal receipts, and work
  quiescence before reporting. Integration evidence satisfies the delivery
  gate when review is not chosen; a chosen review additionally requires the
  distinct Reviewer's fresh evidence. The Kernel creates one read-only
  ReportDispatch; only the facilitator/reporter emits the final public summary.
  A reporter receipt and runtime quiescence are required before completion.

Root quiescence includes more than native Room Dispatches. The application
aggregates every causal child keyed by `rootId`, `generation`, and optional
`dispatchId`: nested delegation runs and governed `workspace_job` processes
must both be terminal before finalization. An active or unknown child fails the
terminal fence closed. Root cancellation fans out one idempotent request to
each owner, preserves pending/unknown surfaces in the cancellation receipt, and
generation-fences late output so it cannot revive stopped work.

Managed Pi exposes the minimum responsibility loop (`room_state`, `room_post`,
and `room_commit`) before the first Room model call. The Kernel Dispatch intent
also selects exactly one required stage-resident Skill: alignment for align,
implementation for execute/resume, independent review for review, quality gate
for close, and structured handoff for handoff. The exact Skill hash and
Root/Task/Dispatch/Session/capability epoch are pinned in a load receipt; an idle
Session reopens when the required Skill changes, and compaction recovery verifies
the same pin. Other product Tools,
including `room_define`, `room_collaborate`, workspace operations, and
`workspace_job`, stay behind the shared `tool_search`/`tool_load` registry and
its policy receipts. Tool cards and Provider schemas are a source union:
loading a Tool changes disclosure state but must not make sibling built-ins
disappear.

Participant Sessions and Dispatches are ownership records, not filesystem
roots. Each participant may act only through its own bound workspace harness
and disclosed workspace Tools, with accepted evidence receipts proving effects.
Private Session reasoning, internal references, and participant details remain
private; only eligible public receipts, material progress, and the final
reporter summary enter the public Room timeline. A failed, stale, foreign,
unauthorized, or duplicate Tool request must fail closed and must not create
replacement Roots, Tasks, WorkItems, catalogs, or routes.

#### Three-tier delegation boundaries

The product has three deliberately different execution tiers:

- **Facilitator/reporter:** a Room participant Session that coordinates the
  current Root, keeps assignment, integration, review, and final-report
  responsibility, and is the only Room owner of a user-facing question.
- **Room partner Session:** a durable participant owned by the Room lifecycle
  and Kernel Dispatch binding. It owns an accountable public subtask and may
  publish eligible progress, evidence, and handoffs, but its Session transcript
  and reasoning remain private.
- **Nested subagent:** a bounded private child Session owned by the parent
  delegation batch/run. It is not a Room participant, cannot own or settle a
  Root/Task, and cannot publish private history. Its terminal result is handed
  back to the parent as evidence; the parent must verify and integrate it.

The bounded three-tier route is Facilitator -> Room partner (slice lead) ->
a bounded nested batch when a smaller check is useful. Each batch accepts one
or two tasks and depth is at most two; the selected role/profile determines
read-only versus Worker capabilities, with Worker writes still subject to
existing approval and workspace-isolation rules. This is distinct from the
Room's own WorkItem graph: a partner can be reassigned or cancelled by the
Kernel, whereas a child run is aborted through the delegation coordinator or
its parent lifecycle. Late child output is fenced and cannot revive cancelled
Room work; a retained stopped child can only be controlled by its parent
Session.

| Boundary | Authoritative owner | State exposed to the Room |
| --- | --- | --- |
| Facilitator/reporter Session | Room Kernel lifecycle plus the facilitator participant | Coordination decisions, accepted evidence, integration, review decision, and one final report |
| Room partner Session | Room participant lifecycle, bound Dispatch, and the partner's workspace harness | Eligible progress, accepted evidence, handoffs, and terminal outcome; private transcript remains private |
| Nested child Session | `AgentDelegationCoordinator`/`AgentDelegationStore` and the child runtime | Bounded task/result/error state returned to the parent; no private transcript or Room lifecycle authority |

The delegation data flow is:

```text
parent Session
  -> POST /api/agent/subagents/runs
  -> AgentDelegationCoordinator
  -> durable batch/run records + private child Session
  -> managed Pi runtime
  -> terminal result (inline or next-turn context)
  -> AgentContextRuntime -> parent Session
  -> explicit parent verification/integration
  -> Room causal task projection when roomBound=true
```
`GET /api/agent/subagents/runs?sessionId=...` is a bounded status/list
projection for the parent Session; it is not the delegation creation path.

`fresh` is the independent-context choice, including an independent review.
`fork` is permitted only when the parent's managed Pi transcript prefix
materially helps and prefix/cache reuse is valuable. It uses the exact managed
prefix and appends a bounded child brief; it must not reorder system, model, or
Tool prompt layers merely to personalize a branch. Both modes preserve the
private child boundary.

Room partners and nested children do not open competing native Ask prompts. A
Room partner uses `room_commit(wait)` for its assigned Room work; a nested
child has no Room authority and returns only a structured blocker to its
parent. The Facilitator/Reporter decides whether to publish a Room wait. A
standalone parent Session outside a Room may merge one to four independent
material questions into native Ask; dependent questions remain separate.

`workspace_lsp` is constrained by Session role/profile and authorized
workspace roots. Read-only templates may use status, symbols, hover,
definition, references, and diagnostics. A writable Worker may request
`rename` or `code_action_apply` only through the existing hash-bound approval
path; the Worker must inspect references before an exported-symbol change. A
read-only child profile does not acquire write operations.

Managed nested delegation accepts one or two tasks per batch and enforces
delegation depth at most two. Per-run budget, timeout, output, and cancellation
state remain separate from Room settlement. These limits apply to the
delegation batch, not to the number of Room participants or WorkItems.

Room-bound delegated batches are not a second Room lifecycle. Their
`causalMetadata` carries `roomBound`, `roomId`, `rootId`, `taskId`, and
`dispatchId`; `taskId` is the grouping key for a nested-run projection under
the existing Room task. A normal task view may expose template, ordinal, task,
state, budget, result/error, and timing, but not protocol IDs, child transcript
content, or private reasoning. The Web view contract names each row
`RoomTaskSubagentRun` and groups rows under `subagentsByTaskId`.
The Room Kernel snapshot/event stream remains
authoritative for Room task and settlement state; the
`AgentDelegationStore`/status API remains authoritative for nested run state.
The UI joins the two read models by `taskId` and cannot infer, settle, or
cancel Room lifecycle from a child result.

#### Reference-only mechanism comparison: local Cat Cafe

The local `clowder-ai` Cat Cafe reference checkout is a reference for
mechanism-level lessons only. Personal Agent Workbench remains the authority.
Cat Cafe is not a dependency, and none of its protocol names, IDs,
reducer/source code, schemas, or routes are copied into this project.

| Cat Cafe mechanism inspected | Useful lesson for Workbench | Explicit non-copy boundary |
| --- | --- | --- |
| `packages/api/src/domains/cats/services/agents/invocation/InvocationQueue.ts`: per-thread/per-user queue ownership, FIFO/priority ordering, replay idempotency, capacity and stale-processing handling | Make the Room wait/resume owner explicit, deduplicate a repeated answer or handoff by receipt, and keep bounded work from being mistaken for active work merely because text exists | Do not import its queue keys, entry IDs, source categories, limits, or queue implementation |
| `packages/web/src/stores/bubble-reducer.ts`: event validation, stable semantic identity, deterministic fallback, monotonic upgrades, and quarantine when identity is ambiguous | Derive the Control Center from authoritative snapshots/events, preserve deterministic projection, and reject ambiguous or stale events instead of guessing a merge | Do not copy its reducer, bubble IDs, event schema, message kinds, or frontend source |
| `docs/features/F123-bubble-runtime-correctness.md` and `F173-frontend-message-pipeline-unification.md`: one thread-runtime writer/truth source, replay fixtures, and explicit liveness reconciliation | Keep Room lifecycle state in the Kernel and make documentation fixtures exercise source/order/ownership invariants rather than model prose or duplicated client state | Do not transplant its thread protocol, dual-ID scheme, reducer helpers, or store architecture |
| `docs/features/F225-cat-initiated-session-handoff.md`: typed handoff evidence before an irreversible seal, commit-point recovery-forward, idempotent continuation, and stale-note isolation | Treat handoff as a receipt-backed ownership transfer; preserve evidence before transfer, recover forward after accepted irreversible effects, and keep stale evidence from becoming current | Do not reuse its proposal shape, seal reasons, session IDs, continuation keys, or recovery code |
| `docs/SOP.md` reviewer pairing and merge-gate rules: non-author reviewer, explicit availability/role checks, and review before close | When the Facilitator judges review warranted, require a distinct participant, route review through the Kernel after integration, and accept a delivery recommendation only from that reviewer's evidence; otherwise use integration evidence plus Kernel gates | Do not copy Cat Cafe family names, roster IDs, GitHub/PR workflow, or merge commands |

These comparisons inform boundaries and fixtures only. They do not authorize
Cat Cafe-derived lifecycle behavior, automatic worktree creation, or a second
Room protocol.

`rag_ime/agent_room_kernel.py` and its focused application services own the
durable Root, Task, Dispatch, requirement-anchor/catalog, WorkItem, lease,
dependency, generation, and settlement state. `RoomTurnRegistry` owns
bookkeeping mutations and shares its turn-exclusion lock with lifecycle
operations that must remain atomic with “no new turn may start.” Pi Runtime
executes a leased Dispatch and reports bounded events and receipts; it does not
decide that the Root is complete. Participant text is evidence for settlement,
not a terminal-state write.

The Facilitator may keep one coherent implementation path or decompose the
governed WorkItem into child WorkItems. Parallel children are allowed only
when their responsibilities are non-overlapping, no dependency is unfinished,
and parallelism materially reduces waiting; this is the sole bounded
`room_collaborate` use. One Facilitator-owned workspace integrates accepted
Worker results. A Dispatch with `dependsOnDispatchIds` remains fenced until
every required predecessor has an accepted result. The Facilitator decides
whether post-integration review is warranted; if selected, the Kernel hands
off to a distinct Reviewer and a failed review returns to repair. Generation,
attempt, cancellation, stale receipt, and late-result fences prevent an old
participant response from reviving a failed or cancelled Root.

| Layer | Primary source | Owns | Must not own |
| --- | --- | --- | --- |
| Native adapters | `squirrel-patches/`, `macos/` | input integration, foreground context, Keychain, voice, allowlisted native calls | memory ranking, Room state, Provider payloads |
| Realtime sidecar | `rag_ime/rime_sidecar.py`, `rag_ime/mlx_predictor_server.py` | privacy/staleness/latency gates, local candidates, source labels, feedback | Rime decoding, remote passive generation |
| Control transport | `rag_ime/debug_server.py`, `rag_ime/control_api/`, `control-center-web/src/platform/` | method/path matching, exposure policy, parsing, contracts, response projection | direct business-state mutation |
| Application services | `rag_ime/management_service.py`, `rag_ime/*_application.py` | complete user use cases, preview/apply/rollback, revisions, receipts | HTTP presentation or UI state |
| Agent runtime | `rag_ime/agent_service.py`, `rag_ime/agent_sessions.py`, `rag_ime/agent_runtime_driver.py` | Session history, prompt delivery, runtime-neutral execution | Pi private implementation details |
| Pi adapters | `rag_ime/pi_runtime*.py` | protocol selection, Provider message projection, Pi process/host lifecycle | Room persistence or HTTP ownership |
| Tool execution | `rag_ime/agent_tools.py`, `rag_ime/agent_room_capabilities.py` | schemas, disclosure, policy, approval, execution, terminal receipts | model-authored authority |
| Room orchestration | `rag_ime/agent_room_kernel*.py`, `rag_ime/agent_room_turn_registry.py` | Root/Task/Dispatch, leases, settlement, evidence, turn exclusion | arbitrary transport or UI mutation |
| Persistence | `rag_ime/local_sqlite_core.py` and focused stores | schema, transactions, outbox, authoritative local state | Provider or presentation policy |
| UI projection | `control-center-web/src/` | queries, reducers, rendering, user intent | direct SQLite, filesystem, or Provider access |

## Primary Flows

### Agent Session

```text
prompt
  -> AgentPromptApplicationService
  -> current bounded memory/task context
  -> AgentRuntimeDriver
  -> pi_runtime_protocols.resolve_protocol_manager
  -> Pi v1 manager or v2 host manager
  -> Provider / Tool loop
  -> AgentEventHub + Session store + observations
  -> SSE projection
```

The public Pi contract is owned by `pi_runtime_public.py` and
`pi_runtime_values.py`. Import checks prevent protocol implementations from
reaching into each other's private helpers.

#### Control Center Room Task Projection

```text
Room snapshot + ordered SSE events
  -> createRoomKernelProjection
  -> RootProjection + RoomTaskV3 + RoomDispatchEnvelopeV2
  -> RoomTaskFlowGraph
  -> Created -> Work item -> Participant execution -> Shared result
```

The reducer in
`control-center-web/src/contracts/room-kernel-reducer.ts` is the sole Web read
model. `RoomTaskFlowGraph.tsx` groups Dispatches by `taskId`, orders them by
alignment ordinal, intent, attempt, and stable ID, and renders one lane per
Task. An unlinked Dispatch is retained in a visible fallback lane rather than
being dropped. Long public progress, review, receipt, and optional private
Session details remain in disclosures below the graph.

Visual state is derived, never written back:

| Visual state | Task states | Dispatch states |
| --- | --- | --- |
| Waiting | `pending`, `waiting` | `pending`, `retry_wait`, `timer_wait` |
| Active | `active`, `review` | `leased`, `running` |
| Complete | `completed` | `committed` |
| Needs attention | `blocked`, `failed` | `unknown`, `dead_letter`, `failed` |
| Stopped | `cancelled` | `cancelled` |

The shared-result node is complete only when the projected Root is both
`completed` and final. Blocked, failed, cancelled, cancelling, and
`cancelled_with_unknowns` Roots keep their distinct user-visible outcome; the
graph cannot infer success from a post count or participant prose. Active
connectors may animate to show real progress, while `prefers-reduced-motion`
removes that motion. Icons and labels duplicate every color signal. Container
and viewport breakpoints convert the four-stage graph to a vertical flow
without horizontal scrolling.

### Control Center Request

```text
React feature
  -> ControlTransport
  -> local HTTP or NativeTransport
  -> ControlRoutePolicy
  -> RouteDescriptor or dedicated special-route adapter
  -> application handler
  -> store / runtime / native adapter
  -> typed JSON, SSE, or binary projection
```

Simple route families use descriptors. Streaming, path-parameter, binary, and
special-authorization routes keep dedicated adapters when a generic descriptor
would hide behavior.

### Rime Suggestion

```text
Squirrel snapshot
  -> POST /api/rime-suggest
  -> DebugRequestHandler
  -> DebugImeService.rime_suggest
  -> build_rime_sidecar_response
       -> local predictor
       -> Hybrid RAG / governed memory
       -> stale, privacy, and latency checks
  -> candidate response with source and fingerprint
  -> overlay
  -> /rime-select feedback
```

The Python sidecar can fail without taking ordinary Rime composition down.
Late results are rejected using request/context identity.

## Data And Evidence

SQLite is the authoritative local store:

- raw final input and applied receipts are immutable evidence;
- curated Atoms and Books are reviewed memory;
- retrieval documents and vectors are projections;
- Provider context is a bounded, cache-aware view;
- Room public posts are projections of durable Room events;
- private participant Session histories are not copied into the public Room
  transcript.

Generated candidates, assistant prose, screenshots, and failed Tool output do
not become durable personal memory merely because they appeared in a Session.

## Extension Boundaries

- **New HTTP family:** route contract, one application owner, focused contract
  tests. Special behavior stays in a dedicated adapter.
- **New Pi protocol:** one adapter plus one registry entry; no imports from
  another protocol's private implementation.
- **New Provider:** configuration and Provider adapter; Session, Room, and HTTP
  persistence should not change.
- **New Tool:** schema/definition, implementation, policy classification, and
  focused receipt tests. Approval semantics remain explicit.
- **New Session projection:** event/read-model adapter; authoritative history
  and Provider payload construction remain unchanged.

The project intentionally avoids a service locator, universal base service,
second event bus, and generic dependency-injection framework.

## Trust And Failure Boundaries

- Secure or unknown foreground fields fail closed.
- Provider credentials belong in Keychain or ignored local configuration.
- Remote Agent Gateway access is allowlisted and excludes local-only mutations.
- Tool authorization is bound to Session, Dispatch, capability epoch, schema,
  arguments, and terminal receipts.
- An identical failed Tool command cannot replay as an authorized lifecycle
  transition without new successful Tool evidence.
- A waiter, model statement, or HTTP 200 is not a substitute for the downstream
  receipt or visible foreground effect.

See [SECURITY.md](SECURITY.md) for reporting and the supported threat model.

## Verification Levels

1. static contracts, import boundaries, route ownership, lint, and typing;
2. deterministic Python, TypeScript, and native tests;
3. real Provider Room canaries with Tool and receipt evidence;
4. installed macOS foreground acceptance;
5. signed, notarized, stapled distribution with a hash-bound release manifest.

Public source readiness does not imply levels 4 or 5. The machine-readable state
is in `release/product-status.json`.
