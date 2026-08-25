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
  `moduleResolution: "Bundler"` setup. No logic was changed.
- `index.ts` (the barrel) and this file are local additions.

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

- `MarkdownBody` engages `ProgressiveMarkdown` only on the live streaming
  path (`streamingTail`), with `holdBack` disabled: PAWOS already batches
  live-store commits upstream, and the transcript must reflect delivered text
  synchronously (deterministic tests, honest foreground behavior). The
  rAF-paced `useSafeTextRelease` scheduler is vendored with the component but
  inert until a caller opts in.
