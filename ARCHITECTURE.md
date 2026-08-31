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
    -> Electron-hosted loopback HTTP transport
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
  user Room message -> coordinator Pi Session
  -> optional room_partner -> partner Pi Session
  -> optional agents -> private Tool Agent Session
  -> child/partner event result -> coordinator integration
  -> one coordinator final + Root terminal event

optional input path
  keyboard
    -> Rime/librime
    -> patched Squirrel
    -> local sidecar /api/rime-suggest
    -> local completion + governed retrieval
    -> source-aware assistant overlay
```

### Light Room Collaboration

Room composes existing Pi Sessions; it is not a second Agent loop and it does
not put a document or Kernel quality gate between a participant and Pi.

```text
user Room message
  -> durable Room user event + one public Root
  -> coordinator participant's Pi Session
  -> optional room_partner dispatch
     -> partner participant's Pi Session
     -> optional agents Tool child Session
        -> bounded child event/result back to the parent Session
     -> partner terminal event back to the same Root
  -> coordinator integrates the returned evidence
  -> one coordinator final + one Root terminal event
```

Pi continues to own transcript persistence, model and Tool loops, context
compaction, Steer, Stop, and Session recovery. Room adds only the collaboration
facts that Pi does not own: Room and participant identity, topic, explicit
dispatches, ordered public events, cancellation fan-out, and one terminal Root.
`RoomTurnRegistry` is the small causal bridge between a private Pi turn and
its public Room Root. It buffers events until the Pi turn id is acknowledged
and rejects every participant Session event that has no accepted Room dispatch.
Membership alone never makes an ordinary Session turn public.

#### Participant and child boundaries

- **Coordinator:** a normal Room participant Session. It decides whether to
  delegate, integrates partner results, decides whether review is useful, and
  produces the user-facing final.
- **Partner:** another normal Room participant Session reached through
  `room_partner`. It can read or write according to its Session/workspace
  configuration and returns progress and a terminal result as Room events.
- **Tool Agent:** a private child Session reached through `agents`. The parent
  chooses read-only or write access, model profile, thinking level, tool
  allowlist, and whether Pi/Codex skills are enabled. The child result returns
  to the parent; it does not become a second Room participant.
- **Optional reviewer:** either a Partner or Tool Agent selected by the
  coordinator when risk warrants it. Review is not a mandatory Kernel gate.

Live children in the same delegation tree may call each other directly. The
delegation coordinator verifies that both runs share the same tree and delivers
the message through Pi Steer. Maximum child depth remains two. Child status,
timeout, output budget, cancellation, and retained terminal result belong to
`AgentDelegationCoordinator` and remain separate from Room terminal state.

#### Context harness and skills

A Tool Agent receives a bounded one-time brief, not the entire Room history:

```text
task + expected output + acceptance criteria
+ optional output schema
+ selected project/Room facts
+ access and allowed tools
+ model/thinking profile
+ contextMode=fresh|fork
+ Pi/Codex skill enablement
```

`fresh` starts with the brief and selected facts. `fork` reuses the exact
managed parent transcript prefix and appends the same bounded brief. Skills may
shape how a child works, but their checklists are not Room terminal gates. The
parent decides which requirements apply, verifies the returned evidence, and
owns any real integration.

Shared writable workspaces are allowed when the parent selects ordinary write
access. An isolated worktree is optional for genuinely concurrent conflicting
writes, not a requirement for every child. Tracked Project/Outcome/Decision
documents provide bounded semantic context, but they do not own Runtime state
or block Room completion. Per-run interactive documents, Boundary Revision,
shared-resource leases, and automatic ChangeManifest remain deferred.

#### Public projection

The public Room stream contains the user Root, route/dispatch receipts, bounded
participant progress, public messages, and terminal events. Private reasoning,
child transcripts, Tool arguments, raw Tool results, and direct participant
Session turns stay in their owning Session.

The Control Center conversation and task views reduce the same ordered Room
snapshot/SSE stream. The task view projects real public Roots and their
participants/tool steps; explicit `workItems` are optional additive records.
It must not show an empty task page while a Root is running, and it must not
infer a running Root from an unrelated participant Session.

Historical `room_kernel_*` SQLite migrations remain append-only so existing
local databases can still upgrade. They are compatibility history, not the
current Room runtime or UI owner.

| Layer | Primary source | Owns | Must not own |
| --- | --- | --- | --- |
| Native adapters | `squirrel-patches/`, `macos/` | input integration, foreground context, Keychain, voice, allowlisted native calls | memory ranking, Room state, Provider payloads |
| Realtime sidecar | `rag_ime/rime_sidecar.py`, `rag_ime/mlx_predictor_server.py` | privacy/staleness/latency gates, local candidates, source labels, feedback | Rime decoding, remote passive generation |
| Control transport | `rag_ime/debug_server.py`, `rag_ime/control_api/`, `control-center-web/src/platform/` | method/path matching, exposure policy, parsing, contracts, response projection | direct business-state mutation |
| Application services | `rag_ime/management_service.py`, `rag_ime/*_application.py` | complete user use cases, preview/apply/rollback, revisions, receipts | HTTP presentation or UI state |
| Pi Session runtime | `rag_ime/agent_service.py`, `rag_ime/agent_sessions.py`, `rag_ime/pi_runtime*.py` | transcript, Agent/Tool loop, compaction, Steer, Stop, recovery | Room or Project semantics |
| Delegation | `rag_ime/agent_delegation.py` | child Sessions, bounded context, A2A calls, child cancellation and results | Room membership or Root final |
| Tool execution | `rag_ime/agent_tools.py` | tool schemas, policy, approval, execution, terminal receipts | model-authored authority |
| Ability market | `rag_ime/agent_extensions.py`, `integrations/pi/skills/plugin-creator/`, Pi `rag-ime-runtime-host` package manager | discovery, Package preparation, product confirmation, version receipts, update/rollback, active resource paths | a second extension/Skill loader or Session bootstrap |
| Light Room | `rag_ime/agent_rooms.py`, `rag_ime/agent_room_turn_registry.py`, Room methods in `agent_service.py` | Room identity, participants, topics, explicit dispatch mapping, public event order, cancellation fan-out, one Root terminal | Pi loop, document quality gates, mandatory review |
| Persistence | `rag_ime/local_sqlite_core.py` and focused stores | schema, transactions, authoritative local state | Provider or presentation policy |
| UI projection | `control-center-web/src/contracts/room-reducer.ts`, `control-center-web/src/features/rooms/` | deterministic read model, rendering, user intent | runtime ownership or inferred completion |
| PAW OS product frontend | PAW-owned product composition in `7155/personal-agent-workbench` plus the existing versioned transport and reducers | App composition, windows, Dock, Mission Control, layout snapshots, PAW surface rendering | Session/Room/Package/WorkDocument/Memory/Knowledge lifecycle or copied Runtime state |

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

#### Control Center Room Execution Projection

```text
Room snapshot + ordered SSE events
  -> reduceRoomEvent
  -> public Root, participant lanes, tools, messages and terminal fence
  -> selectRoomExecutionOverview
  -> conversation timeline + bounded task cards
```

`control-center-web/src/contracts/room-reducer.ts` is the sole Web Room read
model. It advances one sequence at a time, requests a snapshot on a gap,
coalesces streaming deltas, fences late execution after the Root terminal, and
ignores historical participant Session events that lack a Room dispatch.
`selectRoomExecutionOverview` derives the task cards from those public Roots;
it does not create or mutate lifecycle state.

Running, stopping, completed, failed, and aborted labels come from the same
Root projection used by the composer. Refresh therefore cannot show an empty
task page or a busy composer when only an unrelated participant Session is
active.

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

### PAW OS Frontend Projection

```text
PAW snapshot / ordered SSE / typed command
  -> versioned PAW transport adapter
  -> PAW OS product composition in 7155/personal-agent-workbench
  -> paw.* App or window surface
  -> PAW-owned window / Dock / Mission Control / snapshot mechanics
```

PAW OS is built and released from `7155/personal-agent-workbench`. The existing
`control-center-web` shell remains a selectable legacy fallback until cutover;
the new shell shares PAW contracts, generated types, reducers, and Gateway
adapters instead of copying them. `7155/tutti` and `tutti-os/tutti` are
reference sources only. PAW may adapt their proven interaction mechanics, but
no Tutti repository, absolute local path, or Tutti Runtime state is a product
dependency.

A PAW OS shell snapshot may retain product identity, node identity, frame,
focus, z-order, and other presentation state. It must not persist or reconstruct
Room, Session, WorkItem, approval, Package, WorkDocument, Memory, Knowledge, or
terminal state. Those facts continue to come from their existing PAW/Pi owners
after refresh. Legacy and PAW OS layout state use separate namespaces so a
staged migration or rollback cannot overwrite the other shell's layout.

Feature migration keeps the PAW reducer/store/contract owner intact and adds a
narrow PAW OS surface around it. Closing a window removes or hides that view;
Stop and Cancel remain explicit PAW/Pi commands. Tutti-inspired behavior is
implemented behind PAW-owned interfaces and verified inside this repository.

Related Web routes converge into PAW OS Apps instead of becoming one App per
sidebar item. Project Field / Wayfinder is the windowless OS home and project
selector, not an ordinary App. Project Workbench owns Overview, WorkItems, and
WorkDocuments; Agent owns Conversations, Sessions, and Roles; Rooms owns the
Room list, collaboration timeline, and Workflow graph; Memory and Knowledge
retain separate context authorities; Input Studio owns voice, Squirrel/Rime,
lexicon, and input history. App Center, System Monitor, and System Settings own
capability installation, operational evidence, and policy respectively. Files,
Browser, and Terminal adapt Tutti's proven presentation mechanics behind
PAW-owned contracts rather than importing Tutti Runtime ownership.

The Browser App deliberately gives the human and Agent one visible page
identity:

```text
Browser App tab + address bar
  -> selected PAW deviceId + tabId
  -> browser.command / snapshot / permission / trace
  -> connected or managed browser
  -> ordered receipt and refreshed snapshot in the same App surface
```

Human navigation and Agent actions therefore converge on the same tab and page
snapshot. PAW remains authoritative for command admission, permission prompts,
execution traces, cancellation, and Stop. Window chrome, tab presentation, and
address-bar interaction do not become a second browser state machine.

A Room always has one complete main window plus bounded optional participant
satellites. The main window retains objective, ordered loops, Workflow, direct
peer relationships, approvals, Root convergence, and final answer. Satellites
project one participant's local slice and share the same Room snapshot/reducer/
event owner; window layout never becomes collaboration truth.

### Pi Package Market And Skill Creation

```text
npm / Git / local / catalog source
  -> Control Center ability market
  -> PAW draft + validation + proposal receipt
  -> managed Pi plugins.package.prepare
  -> Pi DefaultPackageManager resolution in a temporary inbox
  -> resource inventory: extensions / Skills / prompts / themes
  -> explicit product confirmation
  -> versioned managed install + active pointer
  -> new Pi Session DefaultResourceLoader
```

Preparation, validation, and resource inspection are deterministic package
operations and do not use an approval model. Installation, update, and rollback
are product state changes and therefore require the normal product confirmation
receipt. The project `plugin-creator` is itself a Pi Skill: it searches first,
creates only a missing reusable capability, validates the resulting Package,
and stops before confirmation. Pi remains the sole resource loader, and an
already-running Session never has its prompt prefix silently rewritten.

### Source-Isolated Extension Apps

```text
control-center-web/extension-apps/<slug>/
  -> validated pawos-app.json + lazy React entry + App icon
  -> co-versioned pi-package with App Skill
  -> managed Pi Package prepare / confirm / install
  -> installed+enabled inventory projects extension:<slug>
  -> desktop / Launchpad / Dock / generic ExtensionAppHost
  -> App-owned Pi Session + reusable transcript and Composer primitives
  -> registered sandbox suite -> Trace -> frozen Eval
```

Business-specific frontend code, prompts, Skill, and Package source stay in the
Extension App owner directory. PAWOS core owns only manifest discovery,
validation, generic hosting, icon rendering, lifecycle projection, and window
cleanup. It never branches on one vertical App id. A compiled frontend is only
a candidate: the Package inventory owns whether the App and its Skill are
available. Disable or uninstall removes the visible identity and closes its
windows; whole-product rollback owns the compiled frontend chunk.

Conversation-mode Apps may select a mode, shape the first-turn contract, and
format domain results. Their conversations are absent from Agent's ordinary
conversation index and are restored only by the owning App. They still reuse
Pi's Session, Tool loop, ordered transcript, Markdown, Stop, recovery, model
and approval semantics rather than creating a second Runtime. Registered
vertical fixtures are offline test references only; they never become
production data merely because a sandbox Eval passed.

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
- **New installable Agent capability:** a Pi Package declaring extensions,
  Skills, prompts, or themes; discovery and receipts live in PAW, while source
  resolution and Session resource loading remain in Pi.

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
3. real Provider Session/Room canaries with Tool and receipt evidence (the
   installed Luna development Runtime passed the bounded Session and two-Partner
   Room canaries on 2026-08-16);
4. installed macOS foreground acceptance;
5. signed, notarized, stapled distribution with a hash-bound release manifest.

Public source readiness does not imply levels 4 or 5. The machine-readable state
is in `release/product-status.json`.
