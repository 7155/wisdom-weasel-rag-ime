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
  confirmed Room requirement
    -> Root -> Task -> Dispatch
    -> participant Session
    -> Tool capability manifest and execution receipts
    -> quality gate and commit
    -> public Room timeline projection

optional input path
  keyboard
    -> Rime/librime
    -> patched Squirrel
    -> local sidecar /api/rime-suggest
    -> local completion + governed retrieval
    -> source-aware assistant overlay
```

## Ownership By Layer

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

### Room Collaboration

```text
confirmed requirement
  -> Root execution
  -> bounded participant Tasks and Dispatches
  -> independent participant Sessions
  -> capability-bound Tool calls
  -> execution and quality-gate receipts
  -> commit / handoff / settlement
  -> public timeline
```

Room bookkeeping mutations belong to `RoomTurnRegistry`. Room lifecycle
operations share its turn-exclusion lock when a Session/Room transaction must
remain atomic with “no new turn may start.”

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
- An identical failed Tool command cannot replay under the same Dispatch
  without new successful Tool evidence.
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
