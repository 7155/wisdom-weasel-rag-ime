# Chat UI Kit — Vendored Row Anchor Core

`message-anchor.ts` is vendored from `paw-agent-chat-ui-kit`
(`paw-agent-chat-ui-kit-source.zip` at the repository root, MIT, see the
`LICENSE` inside the archive), covering the row-anchor half of the kit's
**P0-C row anchor scroll memory** item in `docs/spec/03-GAP-ANALYSIS.md`.

| File here | Kit source |
| --- | --- |
| `message-anchor.ts` | `src/core/interaction/messageAnchor.ts` |

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
- `queue.ts`, `composer.ts`, `operation.ts`, `runtime.ts`, `sideChat.ts`,
  `draft.ts`, `timeline.ts` — the PAW Engine owns canonical send/queue/steer
  lifecycle, and the gap analysis rules out rewriting the queue engine.
- `src/core/markdown/*` — the transcript already runs the clean-room
  progressive renderer; see `../progressive-markdown/ATTRIBUTION.md`.
