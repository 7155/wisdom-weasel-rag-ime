# Conversation UI — vendored clean-room package

The modules in this directory are vendored from the clean-room conversation
package delivered as `conversation_ui_standalone.zip` at the repository root
(added on `main` in commit `5241e914`; the archive expands to
`claude_conversation_ui_standalone/`).

That package is an independent React + TypeScript reimplementation of the
*observable interaction behaviour* of a long-running agent conversation UI. It
is not vendor source, contains no proprietary bundle, and by construction
imports nothing from any host repository. Its stated host boundary is a single
`ConversationTransport` interface.

## Vendored files

| File here | Package source |
| --- | --- |
| `model/types.ts` | `src/model/types.ts` |
| `model/queue.ts` | `src/model/queue.ts` |
| `hooks/usePinnedTranscript.ts` | `src/hooks/usePinnedTranscript.ts` |
| `hooks/useVirtualTranscript.ts` | `src/hooks/useVirtualTranscript.ts` |
| `hooks/useSessionScrollMemory.ts` | `src/hooks/useSessionScrollMemory.ts` |
| `components/VirtualTranscript.tsx` | `src/components/VirtualTranscript.tsx` |
| `components/TranscriptRow.tsx` | `src/components/TranscriptRow.tsx` |
| `components/UserTurn.tsx` | `src/components/UserTurn.tsx` |
| `components/AssistantTurn.tsx` | `src/components/AssistantTurn.tsx` |
| `components/ThinkingBlock.tsx` | `src/components/ThinkingBlock.tsx` |
| `components/ToolCard.tsx` | `src/components/ToolCard.tsx` |
| `components/SteerReceipt.tsx` | `src/components/SteerReceipt.tsx` |
| `components/MessageActions.tsx` | `src/components/MessageActions.tsx` |
| `components/QueueTray.tsx` | `src/components/QueueTray.tsx` |
| `components/JumpToBottom.tsx` | `src/components/JumpToBottom.tsx` |
| `components/ConversationSurface.tsx` | `src/components/ConversationSurface.tsx` |
| `conversation-ui.css` | `src/styles.css` |

`ConversationSurfaceContext.tsx`, `use-conversation-queue.ts`, `adapters/**`,
`index.ts` and this file are PAWOS additions.

## Local adaptations

- **State ownership is inverted.** The package ships a `ConversationProvider`
  that owns a reducer and drives `transport.send()` itself. PAWOS already
  reduces authoritative Runtime SSE into `useRoomLiveStore` /
  `useAgentLiveStore`, and those stores own optimistic append, admission
  state, snapshot recovery and resume tokens. Re-homing that in the package
  reducer would fork the source of truth, so the vendored components read a
  `ConversationSurfaceController` supplied by the host instead of
  `useConversation()`. The transcript craft is unchanged; only where the
  transcript comes from changed.
- **Markdown.** `AssistantTurn` renders text blocks through this app's
  `MarkdownBody`, which already wraps the sibling vendored clean-room
  progressive renderer (`features/agent/timeline/progressive-markdown/`) plus
  PAWOS link/HTML/code policy. The package's bare demo Markdown renderer is
  not vendored.
- **Copy is Simplified Chinese** to match the rest of the desktop.
- **Colour.** `conversation-ui.css` keeps the `ccui-*` class namespace but
  resolves every `--ccui-*` variable from PAWOS `--paw-*` desktop tokens.
- **Host slots.** `renderBlock` / `renderBlockDetail` / `renderBlockAction` /
  `renderMessageFooter` let a host keep Runtime-specific presentation (pending
  approvals, structured tool evidence, background process links) inside the
  shared card without forking the card.
- **The steer receipt states delivery, not reading.** The package times
  `unread → read` from its own reducer. PAWOS derives them from the Room
  projection instead — the reducer's optimistic flag, then the Root's own
  published events — so the copy says 尚未送达伙伴 / 已送达伙伴 rather than
  claiming a partner has read the message. `settling` and `done` fade back to a
  plain timestamp exactly as the package does.
- **Pinning is instant.** The package re-pins from a `ResizeObserver`
  observation. That is right for later growth of a mounted row (streamed text,
  an opened disclosure) but a frame late for the transcript itself, so
  `VirtualTranscript` also pins when the message list changes, and only the
  reader's explicit jump animates.
- `ResizeObserver` guards were added to the two scroll hooks so the surface
  also mounts in the jsdom test environment.

## Where each PAWOS surface stands

- **Room main timeline** and **partner satellite** render `ConversationSurface`
  directly, through `PawRoomConversation` and the `roomTranscript` adapter.
- **Session** keeps `AgentTimeline`. It is not a legacy stack: it already
  satisfies the package's reading contracts with its own mature implementation
  — `react-virtuoso` variable-height virtualization with follow-output pinning,
  and a Runtime-driven steer receipt (`sending → accepted → applied`) that is
  strictly richer than the package's timed `unread → read → settling → done`.
  Replacing it would trade real capability (approvals, per-turn recovery,
  edit/fork/rewind, subagent links, day separators, conversation navigation)
  for surface uniformity. What Session genuinely lacked was the *front-end*
  queue, so it now shares `useConversationQueue` and `QueueTray`.
- The Session queue is deliberately distinct from Runtime `followUp` delivery.
  干预/接续 hand a message to Pi immediately and Pi owns the ordering; 排队 holds
  the draft in the client, which is the only reason it can still be edited,
  reordered, sent ahead of its turn, dropped, or handed back on stop.

## Deliberately not vendored

- `context/ConversationProvider.tsx`, `model/reducer.ts`, `transport.ts` — the
  package's host boundary is a `ConversationTransport` that its own reducer
  drives. PAWOS inverted that (see above), so `ConversationSurfaceController`
  *is* the host boundary here and the transport interface had no implementation
  and no caller. A vendored interface nobody satisfies invites someone to build
  against a seam that does not exist, so it is not carried.
- `model/sideChat.ts`, `components/SideChatPanel.tsx` — no Pi Runtime contract
  backs a per-conversation side chat today, and wiring the panel to anything
  else would put invented data on a real transcript.
- `components/Composer.tsx`, `hooks/useAutoGrowTextarea.ts` — input stays with
  the PAWOS composers (`RoomComposer`, `AgentComposer`), which own attachments,
  mentions, model/permission pickers and command palettes. Only the queue tray
  is shared.
- `rendering/**` — already vendored under
  `features/agent/timeline/progressive-markdown/`.
- `demo/`, `examples/`, `tools/`, `analysis/` — reference material, not product
  code.
