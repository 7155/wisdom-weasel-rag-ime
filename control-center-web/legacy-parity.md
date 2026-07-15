# Web control center migration status

Current snapshot: 2026-07-15 on `codex/control-center-web-migration`.

- The TypeScript catalog currently contains 92 allowlisted `pathId` entries.
- Production builds are native-only and reject HTTP/mock/preview modules at bundle time.
- Agent conversations, Pi model selection, Rooms, user-created Personas, planning tasks,
  Memory Book/Group/Tag reads, stable-ID memory edits, history tombstones, knowledge
  runs, configuration changes, provider credentials, voice settings and diagnostics
  are connected to real local routes with focused regression coverage.
- Writes that can change local state use an explicit preview, confirmation, receipt and
  rollback boundary where the backend supports one. Legacy import/restore endpoints
  remain intentionally excluded until they accept bridge-owned file tokens and a bound
  rollback contract.

The remainder of this document is the original Lane D contract audit. It is retained as
historical design evidence; statements about mock receipts or missing routes describe
that earlier baseline, not the current production bundle.

## Historical Lane D baseline

Baseline: `f6c42d93c02e6e97b6b95b0fb64cb2ca07e2e8bd` on `codex/control-web-pages`.

This document compares the ten Lane D routes with the legacy Swift control center. The current TypeScript route catalog contains 51 `pathId` entries. Lane D uses the existing allowlisted reads directly through `useControlTransport()` and TanStack Query. It does not assemble URLs.

## Read wiring

| Web route | Existing read `pathId` used now | 8766 endpoint | Loading / empty / error / success |
| --- | --- | --- | --- |
| `/overview` | `overview.get`, `system.health`, `agent.runtime.get`, `diagnostics.models`, `knowledge.routeStatus` | `/api/overview`, `/api/health`, `/api/agent/runtime`, `/api/models/status`, `/api/knowledge/route-status` | Yes |
| `/input` | `input.source.get`, `overview.get`, `configuration.settings`, `configuration.schema` | `/api/input-source`, `/api/overview`, `/api/settings`, `/api/settings/schema` | Yes |
| `/plugins` | `agent.tools.list` | `/api/agent/tools` | Yes |
| `/voice` | `configuration.settings`, `configuration.schema`, `diagnostics.runtime` plus platform capabilities | `/api/settings`, `/api/settings/schema`, `/api/runtime/status` | Yes |
| `/planning` | `planning.dashboard` | `/api/planning/dashboard?date&project` | Yes |
| `/memory` | `memory.summary`, `memory.pages` | `/api/memory/summary`, `/api/memory/{books,atoms,tags,phrases,groups,negative}` | Yes; cursor pagination |
| `/knowledge` | `knowledge.routeStatus`, `knowledge.status` | `/api/knowledge/route-status`, `/api/knowledge/status?sessionId` | Yes |
| `/history` | `history.page` | `/api/history/page?limit&cursor&query&filter` | Yes; cursor pagination |
| `/diagnostics` | `diagnostics.runtime`, `diagnostics.predictor`, `diagnostics.models`, `input.source.get` plus platform capabilities | `/api/runtime/status`, `/api/predictor/status`, `/api/models/status`, `/api/input-source` | Yes |
| `/configuration` | `configuration.settings`, `configuration.schema` plus platform capabilities | `/api/settings`, `/api/settings/schema` | Yes |

## Page and user-action parity

| Route | Legacy user action | React state | Success / failure state |
| --- | --- | --- | --- |
| `/overview` | View component, memory, last prediction, Pi/model/RAG state | Real reads, compact status rows and metrics | Query boundary shows retry; refresh preserves the last Query cache |
| `/overview` | Pause/resume AI; apply profile; repair components | Preview -> approval -> explicit mock receipt -> rollback rehearsal until route entries below exist | Mock receipt says no local service was changed; no unknown request is sent |
| `/input` | View input source and schema settings | Real input-source/settings reads | Foreground readiness is separate from backend health |
| `/input` | Profile and Rime lexicon review/apply/rollback | Profile diff workflow is present; lexicon workflow is blocked on missing route entries | Receipt/rollback states present; backend mutation is not faked |
| `/plugins` | Tool catalog/status/permissions extension point | Real `agent.tools.list`, search and risk filters | Empty catalog and filtered-empty are distinct |
| `/plugins` | Change tool permission | Full workflow rehearsal | R2/R3 per-call approval cannot be bypassed by a catalog toggle |
| `/voice` | Provider, hotkey, agent status, TCC, hotwords, Keychain credential state | Existing settings/runtime reads where available; platform capability gate | Stored secrets are rendered only as `configured` / `not configured` |
| `/voice` | Save provider/credential/hotkey and start/stop agent | Full workflow rehearsal; native-only interfaces requested below | Browser/PWA fails closed when native capability is absent |
| `/planning` | Date navigation, plan, tasks, goals, completion suggestions | Real dashboard by date; compact task/goal lists | Date changes have independent Query keys |
| `/planning` | Save plan/task/goal, task action, resolve suggestion, undo, assistant | Each write has preview/approval/receipt/rollback UI | Current receipt is marked mock until allowlist is extended |
| `/memory` | Kind switch, list/detail, load more, edit, merge, archive/restore/forget | Real summary/page reads, query/status filters and cursor pagination | Pages remain bounded at 50 rows per request |
| `/memory` | Apply maintenance draft and rollback | Diff-oriented workflow present | No direct SQLite mutation from React |
| `/knowledge` | Route status, query lab/workbench, status polling, evidence/citations | Existing route/status reads, mode-aware request preview, evidence table | Local/RAG/Notion/model sources stay distinguishable |
| `/knowledge` | Start/cancel; edit/apply/rollback database draft | Full workflow UI; missing path entries requested below | `runId` remains the rollback authority |
| `/history` | Redacted history table and load more | Real cursor-paged history read with source filters | Raw personal input is not requested |
| `/history` | Feedback and tombstone extension | Preview/approval/receipt/rollback workflow | No physical delete; tombstone route requested below |
| `/diagnostics` | Component/probe/model/source state and copyable report | Four existing reads plus secret-redacted export | Read failure has retry; report redacts secret-like keys recursively |
| `/diagnostics` | Restart Sidecar/predictor, redeploy Rime, register source, pause/resume AI | Five risk-labelled workflows | Native Harness remains required for external actions |
| `/configuration` | Schema settings and expert mode | Existing schema/settings reads; one section rendered at a time | Secret fields never reuse the stored value in an input |
| `/configuration` | Import, export, restore | Native file capability plus preview/apply/receipt/rollback UI | Restore is R3; backup explicitly excludes secrets |

## Missing ControlTransport route requests

The following entries are requested from the contract/API coordinator. “Existing” means the 8766 handler already exists but is not represented by a `pathId`; “NEW” means 8766/native facade work is also required. Body names are the proposed strict allowlist. Pages must continue returning mock receipts until both the route catalog and backend/bridge enforcement land.

### Runtime, overview, input and diagnostics

| Suggested `pathId` | Method | 8766 endpoint | Query/body allowlist | Availability |
| --- | --- | --- | --- | --- |
| `runtime.action.preview` | POST | NEW `/api/runtime/action-preview` | body: `action`, `expectedRuntimeRevision`; `action` enum = `restart_sidecar`, `restart_predictor`, `redeploy_rime`, `register_input_source`, `repair_launch_agents`, `open_accessibility_settings`, `stop_ai`, `resume_ai` | NEW; must return payload/command hashes and impact |
| `runtime.action.start` | POST | `/api/runtime/action` | body: `action`, `previewToken`, `payloadSha256`, `commandSha256`, `expectedRuntimeRevision` | Existing handler accepts `action`; hash/revision enforcement needed |
| `runtime.job.get` | GET | `/api/runtime/job/:jobId` | param: `jobId` | Existing |
| `input.lexicon.review` | GET | `/api/rime-lexicon/review` | query: `limit`, `project` | Existing |
| `input.lexicon.apply` | POST | `/api/rime-lexicon/apply` | body: `reviewToken`, `selectedKeys`, `confirmText`, `project`, `limit` | Existing |
| `input.lexicon.rollback` | POST | `/api/rime-lexicon/rollback` | body: `rollbackId` | Existing |

`runtime.action.start` must return `jobId`; `runtime.job.get` supplies the final receipt. External-supervisor actions remain native-approved and cannot accept a page-supplied command.

### Settings and configuration

| Suggested `pathId` | Method | 8766 endpoint | Query/body allowlist | Availability |
| --- | --- | --- | --- | --- |
| `configuration.settings.preview` | POST | NEW facade over `/api/settings/update` | body: `changes`, `expectedSettingsRevision`, `updatedBy`; `changes` keys must be validated against settings schema | NEW adapter; returns normalized diff, risk, apply modes and `previewToken` |
| `configuration.settings.apply` | POST | `/api/settings/update` | body facade: `changes`, `expectedSettingsRevision`, `updatedBy`, `confirmText`, `previewToken`, `payloadSha256` | Existing handler currently expects changed setting keys at top level; facade must unpack allowlisted schema keys |
| `configuration.section.reset.preview` | POST | NEW facade over `/api/settings/reset-section` | body: `section`, `expectedSettingsRevision` | NEW preview adapter |
| `configuration.section.reset.apply` | POST | `/api/settings/reset-section` | body: `section`, `updatedBy`, `previewToken`, `payloadSha256` | Existing |
| `configuration.import.preview` | POST | `/api/configuration/import-preview` | body: exactly one of `path` or `config`; WebView should pass a bridge-owned file token instead of an arbitrary path | Existing |
| `configuration.import.apply` | POST | `/api/configuration/import-apply` | body: `path`, `config`, `confirmRemoteModel`, `previewToken`, `payloadSha256` | Existing; apply must bind to preview |
| `configuration.backup.export` | POST | `/api/configuration/backup-export` | body: `destination` bridge token | Existing |
| `configuration.restore.preview` | POST | `/api/configuration/restore-preview` | body: `path` or `archivePath` bridge token | Existing |
| `configuration.restore.apply` | POST | `/api/configuration/restore-apply` | body: `path`, `archivePath`, `restoreToken`, `confirmText`, `payloadSha256`; fixed confirm text `RESTORE RAG-IME` | Existing |
| `configuration.restore.rollback` | POST | NEW `/api/configuration/restore-rollback` | body: `rollbackPath` bridge token, `receiptId`, `confirmText`, `payloadSha256` | NEW; required for the web rollback state |

### Voice

Voice currently reads and writes local Swift stores/Keychain and Distributed Notifications; there is no 8766 management API. Secret material must remain native-only. The HTTP/native route must carry only a `secretRef` minted by the host, never a token or header value.

| Suggested `pathId` | Method | 8766 endpoint | Query/body allowlist | Availability |
| --- | --- | --- | --- | --- |
| `voice.status.get` | GET | NEW `/api/voice/status` | none | NEW; remote-safe redacted status only |
| `voice.configuration.preview` | POST | NEW `/api/voice/configuration/preview` | body: `provider`, `appId`, `resourceId`, `endpoint`, `model`, `hotkey`, `hotwordsEnabled`, `hotwords`, `secretRef`, `expectedConfigurationHash` | NEW; `remote_safe=false` when `secretRef` is present |
| `voice.configuration.apply` | POST | NEW `/api/voice/configuration/apply` | body: previous non-secret fields plus `secretRef`, `previewToken`, `payloadSha256`, `expectedConfigurationHash` | NEW; Keychain resolution in NativeBridge |
| `voice.configuration.rollback` | POST | NEW `/api/voice/configuration/rollback` | body: `receiptId`, `rollbackToken`, `payloadSha256` | NEW |
| `voice.agent.action.preview` | POST | NEW `/api/voice/agent/action-preview` | body: `action`; enum `start`, `stop`, `request_microphone`, `request_accessibility` | NEW/native-only |
| `voice.agent.action.apply` | POST | NEW `/api/voice/agent/action` | body: `action`, `previewToken`, `payloadSha256`, `commandSha256` | NEW/native-only |

### Plugins

| Suggested `pathId` | Method | 8766 endpoint | Query/body allowlist | Availability |
| --- | --- | --- | --- | --- |
| `plugins.permissions.get` | GET | NEW `/api/agent/tools/permissions` | query: `roleId`, `sessionMode` | NEW |
| `plugins.permissions.preview` | POST | NEW `/api/agent/tools/permissions/preview` | body: `toolId`, `operations`, `sessionModes`, `enabled`, `expectedRevision` | NEW |
| `plugins.permissions.apply` | POST | NEW `/api/agent/tools/permissions/apply` | body: prior fields plus `previewToken`, `payloadSha256`, `expectedRevision` | NEW |
| `plugins.permissions.rollback` | POST | NEW `/api/agent/tools/permissions/rollback` | body: `receiptId`, `rollbackToken`, `payloadSha256` | NEW |

The backend must validate `toolId` and `operations` against `agent.tools.list`; enabling a tool must not waive R2/R3 per-call approval.

### Planning

| Suggested `pathId` | Method | 8766 endpoint | Body allowlist | Availability |
| --- | --- | --- | --- | --- |
| `planning.plan.save` | POST | `/api/planning/plan/save` | `date`, `project`, `intention`, `notes`, `reflection`, `assistantSummary`, `previewToken`, `payloadSha256` | Existing, preview binding needed |
| `planning.goal.save` | POST | `/api/planning/goal/save` | `goalId`, `title`, `detail`, `horizon`, `status`, `priority`, `targetDate`, `project`, `previewToken`, `payloadSha256` | Existing |
| `planning.task.save` | POST | `/api/planning/task/save` | `taskId`, `date`, `title`, `detail`, `priority`, `status`, `dueAtMs`, `goalId`, `project`, `previewToken`, `payloadSha256` | Existing |
| `planning.task.action` | POST | `/api/planning/task/action` | `taskId`, `action`, `previewToken`, `payloadSha256`; action enum `start`, `complete`, `reopen`, `cancel` | Existing |
| `planning.taskEvent.undo` | POST | `/api/planning/task-event/undo` | `eventId` | Existing rollback for task actions |
| `planning.completion.resolve` | POST | `/api/planning/completion/resolve` | `suggestionId`, `taskId`, `dismiss`, `previewToken`, `payloadSha256` | Existing |
| `planning.assistant.send` | POST | `/api/planning/assistant` | `message`, `date`, `project` | Existing |
| `planning.mutation.preview` | POST | NEW `/api/planning/mutation/preview` | `kind`, `payload`, `expectedRuntimeRevision` with nested payload validated by kind | NEW shared preview |
| `planning.mutation.rollback` | POST | NEW `/api/planning/mutation/rollback` | `receiptId`, `eventId`, `payloadSha256` | NEW for plan/goal/save rollback |

### Memory and history

| Suggested `pathId` | Method | 8766 endpoint | Query/body allowlist | Availability |
| --- | --- | --- | --- | --- |
| `memory.edit.preview` | POST | NEW facade over `/api/memory/edit` | body: `kind`, `id`, `title`, `text`, `summary`, `note`, `tags`, `aliases`, `type`, `color`, `active`, `mergeIntoId`, `expectedRuntimeRevision` | NEW diff adapter |
| `memory.edit.apply` | POST | `/api/memory/edit` | prior fields plus `previewToken`, `payloadSha256`, `expectedRuntimeRevision` | Existing handler, preview binding needed |
| `memory.action.preview` | POST | NEW facade over `/api/memory/action` | `memoryId`, `itemType`, `action`, `reason`, `updatedBy`, `expectedRuntimeRevision` | NEW |
| `memory.action.apply` | POST | `/api/memory/action` | prior fields plus `previewToken`, `payloadSha256`, `expectedRuntimeRevision`; action enum validated per item type | Existing |
| `memory.book.archiveStatus` | POST | `/api/memory/book/archive-status` | `bookId`, `archived`, `reason`, `updatedBy`, `previewToken`, `payloadSha256` | Existing |
| `memory.book.archiveMaintenance` | POST | `/api/memory/book/archive-maintenance` | `apply`, `inactiveDays`, `project`, `previewToken`, `payloadSha256`; `apply=false` is preview | Existing |
| `memory.cleanupRuns.list` | GET | `/api/memory/cleanup-runs` | query: `limit`, `runId`, `status`, `reviewStatus`, `diffIds`, `diffIndexes` | Existing handler, missing pathId |
| `memory.cleanupDiff.apply` | POST | `/api/memory/cleanup-diff/:diffId/apply` | param: `diffId`; body: `previewToken`, `payloadSha256` | Existing |
| `memory.cleanupDiff.rollback` | POST | `/api/memory/cleanup-diff/:diffId/rollback` | param: `diffId`; body: `receiptId`, `payloadSha256` | Existing |
| `memory.mutation.rollback` | POST | NEW `/api/memory/mutation/rollback` | body: `receiptId`, `auditId`, `payloadSha256` | NEW for edit/action rollback |
| `history.tombstone` | POST | `/api/history/tombstone` | body: `eventId` or `memoryId`, `reason`, `previewToken`, `payloadSha256` | Existing |
| `history.tombstone.rollback` | POST | NEW `/api/history/tombstone/rollback` | body: `receiptId`, `eventId`, `memoryId`, `payloadSha256` | NEW |

### Knowledge

| Suggested `pathId` | Method | 8766 endpoint | Body allowlist | Availability |
| --- | --- | --- | --- | --- |
| `knowledge.query.preview` | POST | `/api/rag-core-v3/query-preview` | `query`, `recentContext`, `project`, `topK` | Existing |
| `knowledge.start` | POST | `/api/knowledge/start` | `question`, `context`, `mode`, `includeNotion`, `generation`, `contextHash`, `clientId`, `project`, `app`, `maxChars`, `latencyBudgetMs` | Existing |
| `knowledge.cancel` | POST | `/api/knowledge/cancel` | `sessionId` or `id` | Existing |
| `knowledge.database.draftEdit` | POST | `/api/knowledge/database/draft-edit` | `runId`, `diffId`, `payload`, `selected` | Existing |
| `knowledge.database.apply` | POST | `/api/knowledge/database/apply` | `runId`, `confirm`, `previewToken`, `payloadSha256`; fixed confirm `apply` | Existing |
| `knowledge.database.rollback` | POST | `/api/knowledge/database/rollback` | `runId`, `confirm`, `payloadSha256`; fixed confirm `rollback` | Existing |

## Required receipt contract

All management mutations should converge on one response envelope in addition to domain data:

```json
{
  "ok": true,
  "receiptId": "...",
  "pathId": "planning.task.save",
  "payloadSha256": "sha256:...",
  "appliedAtMs": 0,
  "auditId": 0,
  "rollbackAvailable": true,
  "rollbackToken": "...",
  "restartComponents": []
}
```

Failure must return a stable error code, user-safe message, and the unchanged revision. A stale preview/revision or hash mismatch must fail closed. The React pages already model preview, approval, receipt, error and rollback states; replacing a mock receipt with the real mutation only requires adding these allowlisted `pathId` entries.
