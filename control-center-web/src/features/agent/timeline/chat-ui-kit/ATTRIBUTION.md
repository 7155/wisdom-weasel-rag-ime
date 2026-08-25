# Chat UI Kit — Vendored Cores

Modules here are vendored from `paw-agent-chat-ui-kit`
(`paw-agent-chat-ui-kit-source.zip` at the repository root, MIT, see the
`LICENSE` inside the archive). Ops judgment: borrow pure core only; never
replace AgentTimeline, ConversationSurface, or PAWOS chrome with kit React/CSS.

| File here | Kit source | Kit gap item |
| --- | --- | --- |
| `message-anchor.ts` | `src/core/interaction/messageAnchor.ts` | P0-C row anchor scroll memory |
| `telemetry.ts` | `src/core/performance/telemetry.ts` | P0-A content-free telemetry seam |

Related (outside this folder): `../../composer/composer-action-model.ts`
adapts `projectComposerActionModel` only — never `buildComposerCommand`.

## Local adaptations

- `layoutRevision` is dropped. Nothing in PAWOS mints a monotonic layout
  revision, and storing an always-`0` field would have been decoration.
- `resolveAnchorRowIndex` is a local addition. react-virtuoso owns row
  geometry and exposes `scrollToIndex` and `initialTopMostItemIndex`, not a
  scroll-content coordinate space, so the Session path needs an index+offset
  restore. `resolveAnchorScrollTop` is the kit's original geometry restore,
  kept for the plain scroller the Room transcript uses.
- `TranscriptRowGeometry.index` is a local addition: a virtualizer only hands
  out geometry for its rendered window, so the position within the supplied
  rows is not the position the anchor has to remember.
- Every telemetry entry point defaults to a sink that writes the sample *name*
  as a `performance.mark` and drops the fields. The kit requires an explicit
  sink, which makes each call site decide again where samples go; defaulting to
  a field-free mark means instrumentation added in passing cannot carry prompt
  text or identifiers out of the client. A host that wants the fields installs
  its own sink and owns that decision.
- Telemetry marks are wired only where a transition is rare and worth naming:
  `../AgentTimeline.tsx` marks follow/detach mode changes. `messageLengthBucket`
  and `observeAgentChatLongTasks` are seams for hosts, not live call sites, so
  a long read cannot flood the performance buffer.

## Deliberately not vendored

- `src/core/interaction/followEnd.ts` — `../transcript-follow.ts` already owns
  follow/detached mode and the unseen-content count for both the Session
  timeline and the composer's jump control. A second reducer over the same
  question would give the transcript two owners, which is the ambiguity this
  kind of state exists to remove. The anchor here is deliberately orthogonal:
  it answers *where* the reader was, never *who* moved the transcript.
- `src/react/useTranscriptScrollController.ts` — it installs its own scroll,
  wheel, touch, keyboard and `ResizeObserver` listeners on the scroller. The
  Session already owns those and drives `transcript-follow.ts` from them.
- `queue.ts`, `operation.ts`, `runtime.ts`, `sideChat.ts`, `draft.ts`,
  `timeline.ts` — the PAW Engine owns canonical send/queue/steer lifecycle, and
  the gap analysis rules out rewriting the queue engine. Each of these questions
  already has a PAW owner: `features/conversation-ui/model/queue.ts` plus
  `QueueTray` for the held-draft queue and its one-line next-item preview,
  `SteerReceipt` for delivery state, `contracts/batching.ts` for transport
  delta coalescing (`performance/rafBuffer.ts`), `state/use-session-composer-inputs.ts`
  for per-Session drafts, and `AgentTurn`'s per-turn store selectors for the
  stable-history memo boundary `timeline.ts` reaches with a revision string.
  One thing `queue.ts` did surface: its `previewFallback: 'attachment'` names a
  queued item with no text. PAW's queue holds a string, so instead of modelling
  that row, `../../composer/composer-action-model.ts` refuses to offer 排队 for
  an attachment-only draft and says which delivery does carry it.
- `composer.ts` is adapted in part only. `projectComposerActionModel` is a pure
  projection over composer state, so it moved to
  `../../composer/composer-action-model.ts` in PAW's own delivery vocabulary.
  `buildComposerCommand`, `projectComposerFromRuntime` and the kit's
  `ChatRuntimeSnapshot` stay out: they mint provider-neutral commands over a
  runtime shape PAW does not have, which would put a second author next to the
  Runtime transport the composer already calls.
- The kit's `guide-current-turn` and `interrupt-and-send` actions are dropped.
  PAW exposes 干预 as a Runtime steer delivery and stop as its own control; an
  interrupt-then-resend action would claim a cancel/resend sequence the GUI
  does not own.
- `src/core/markdown/*` — the transcript already runs the clean-room
  progressive renderer; see `../progressive-markdown/ATTRIBUTION.md`.
