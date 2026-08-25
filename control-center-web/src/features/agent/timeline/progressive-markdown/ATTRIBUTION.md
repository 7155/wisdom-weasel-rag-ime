# Progressive Markdown — Vendored Cleanroom Modules

The modules in this directory are vendored from the clean-room streaming
Markdown renderer reference at
[`docs/references/claude_streaming_renderer_cleanroom/`](../../../../../docs/references/claude_streaming_renderer_cleanroom/)
(repository-relative:
`control-center-web/docs/references/claude_streaming_renderer_cleanroom/`,
added in commit `8c903107`). The reference is an independent TypeScript/React
reimplementation of the observable behavior of Claude's progressive Markdown
renderer — **stable-prefix freezing + active-tail-only updates** — licensed
under MIT (see the `LICENSE` file next to the reference).

## Vendored files

| File here | Reference source |
| --- | --- |
| `types.ts` | `src/core/types.ts` |
| `blockScanner.ts` | `src/core/blockScanner.ts` |
| `openFence.ts` | `src/core/openFence.ts` |
| `normalizeStreamingMarkdown.ts` | `src/core/normalizeStreamingMarkdown.ts` |
| `safeInlineBoundary.ts` | `src/core/safeInlineBoundary.ts` |
| `useProgressiveChunks.ts` | `src/react/useProgressiveChunks.ts` |
| `useDeferredStreaming.ts` | `src/react/useDeferredStreaming.ts` |
| `useSafeTextRelease.ts` | `src/react/useSafeTextRelease.ts` |
| `ProgressiveMarkdown.tsx` | `src/react/ProgressiveMarkdown.tsx` |

## Local adaptations

- Import specifiers only: the reference uses NodeNext-style `"./x.js"`
  specifiers and a `core/` / `react/` split; this vendored copy is flattened
  into one directory with extensionless specifiers to match this app's
  `moduleResolution: "Bundler"` setup.
- `index.ts` (the barrel) and this file are local additions.
- `useSafeTextRelease.ts` diverges from the reference in two documented ways:
  it starts fully flushed on mount (a Virtuoso item remount or a restored
  mid-stream snapshot must never replay the reveal — only text appended after
  mount animates), and it flushes instantly when the user asked for reduced
  motion (`prefers-reduced-motion` or the app's `data-reduce-motion` switch)
  or the document is hidden. Delivered text is never withheld from a reader
  who opted out of the courtesy animation.
- `safeInlineBoundary.ts` skips the trailing-word hold-back when the tail is
  CJK text: ideographs and kana are complete display units with no space
  delimiters, so the "do not show half a Latin word" space-seek would
  otherwise pin the reveal to the last ASCII space far behind the tail.
- `safeInlineBoundary.ts` also carries two items adopted from
  `paw-agent-chat-ui-kit`'s `src/core/markdown/reveal.ts`
  (`paw-agent-chat-ui-kit-source.zip` at the repository root, MIT): the
  adaptive catch-up step in `advanceToSafeBoundary`, which scales to a quarter
  of the backlog instead of stepping a fixed 40 characters per tick, and
  `remapVisibleOffsetAfterEdit`, which keeps the reveal position across a
  retry/edit/rewrite that replaces a leading region. `useSafeTextRelease.ts`
  previously collapsed to the common prefix on any non-append change and
  replayed the whole reveal from there.

## Deliberately not vendored

- `ReactMarkdownAdapter.tsx` — the transcript keeps its own hardened
  `MarkdownFragment` (literal-HTML rewrite, link policy, blocked media,
  `CodeContentBlock`); `ProgressiveMarkdown` is wired to it via `renderChunk`
  in `../MarkdownRenderer.tsx` instead.
- `incrementalTokenizer.ts`, `IncrementalCodeBlock.tsx`, `shikiAdapter.ts` —
  streaming code stays on the deliberate plain-text reader
  (`CodeContentBlock`); Shiki highlighting remains a settled-read affordance.
- `positionedTree.ts` (settled whole-document AST backfill) and
  `telemetry/longFrameObserver.ts` — not needed by the current wiring; the
  transcript re-parses the whole body once at settle, exactly as before.

## Integration notes

- `MarkdownBody` engages `ProgressiveMarkdown` on the live streaming path and
  keeps it mounted for one extra deferred render after the stream ends
  (`useDeferredStreaming` latch in `../MarkdownRenderer.tsx`), so the final
  whole-document parse never swaps render modes inside the urgent settle
  commit.
- `holdBack` is enabled: the safe-text release scheduler paces batched
  live-store commits into a Markdown-safe token reveal — the visible typing
  motion. The mount-flush and reduced-motion adaptations above keep the
  transcript truthful for restores, remounts, hidden tabs, and readers who
  disabled motion.
