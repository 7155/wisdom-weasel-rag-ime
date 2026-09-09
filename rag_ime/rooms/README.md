# Room collaboration owners

A Room composes ordinary Pi Sessions. It owns collaboration identities, explicit
dispatch, ordered public events and cancellation fan-out. It does not own a
second model loop or transcript. Import concrete modules; `__init__` starts nothing.

| Capability | Modules |
| --- | --- |
| Room data, participants, topics and resources | `store`, `participants`, `routing`, `resources`, `lifecycle`, `management` |
| Responsibility and review | `work`, `work_application` |
| Explicit Session dispatch and cancellation | `session_dispatch`, `session_cancellation`, `cancellation_proofs`, `turn_registry` |
| Partner collaboration and recovery | `partner_application`, `partner_dispatch_store` |
| Intercom | `intercom`, `intercom_application` |
| Bounded context and workspace projections | `prompt_context`, `prompt_support`, `workspace_ledger` |
| Start-gate records and compatibility APIs | `start_gate` (existing state and recovery semantics retained) |

`work_application` receives the actual stores, router, event hub and Session
validation callback. Its notification helpers do not round-trip through
AgentService. Dispatch/cancellation share the existing `turn_registry`; stores,
locks and event hubs are not copied. External acceptance callbacks retain the
buffered event projection required to publish a Session turn into its Room.

`agent_composition` constructs the existing Room stores and Session services.
AgentService still owns process lifetime and shutdown order. Internal flat import
paths have been migrated together; persisted identifiers, event schemas and
append-only database migrations retain their previous names.
