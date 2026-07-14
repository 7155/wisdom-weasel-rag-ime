# Agent Workbench Design QA

- Date: 2026-07-14
- Scope: native macOS Agent conversation workspace, compact composer, transcript, session rail, activity state, and navigation responsiveness
- Reference: Hermes single-flow TUI hierarchy and VCPChat role/session/tool presentation
- Installed direct-chat build: `/Users/undo/Applications/RagImeControl.app`
- Current Room source build: `/Volumes/undo 4t/git/learnA/wisdom-weasel-rag-ime/build/RagImeControl.app` (not copied over the installed build in this pass)
- Captures: `/tmp/rag-ime-agent-redesign-final.png`, `/tmp/rag-ime-agent-active-qa.png`, `/tmp/rag-ime-agent-activity-final.png`, `/tmp/rag-ime-agent-room.png`

## Comparison

The implementation intentionally does not copy VCPChat's dark cyber wallpaper or dense always-open docks. It keeps the native macOS shell, then adopts the transferable parts: a compact session header, optional session list, role identity, inline tool/source activity, a persistent bottom composer, and structured media/approval blocks. Hermes contributes the short information path: one transcript flow, small inline activity, keyboard-first composer, and no separate dashboard card around every message.

## Findings

- P0: none. No clipped primary controls, unreadable text, overlapping surfaces, or blocked send/attachment actions were found in the installed static state.
- P1: none. The duplicate status band and permanent three-column layout were removed; the assistant response is document-like instead of a gray nested card; the composer is a single visual anchor.
- P2: none. The 780 x 260 activity fixture confirms the running spinner, completed step, waiting step, reference chips, connector line, count, and labels fit without reflow or overlap.
- P3: resolved. The live DeepSeek 400 came from stale Pi Provider compatibility metadata; DeepSeek and GPT Luna now each complete a real governed Tool Loop. The production Activity fixture remains a deterministic layout gate, not a substitute for mixed-load frame-time measurement.
- P3: resolved for the first persistent Room slice. Versioned personas, 2-4 independent participant Sessions, manual `@`/moderator routing, shared transcript rendering, and the native Room workbench are present. Bounded task subagents, participant intercom, signed extensions, and generated-media tools remain P10/later work.
- P3: the prior session list only accepted clicks over painted children such as the avatar. The installed build now switches both rows when clicking their far-right empty area; selected state changes before async history loading.

## Performance Evidence

- 520 transcript rows instantiate 12 visible rows initially and 7 after streaming updates.
- 120 streamed visible-row updates average 5.41 ms, under the 12 ms gate.
- A post-provider-fix rerun averaged 6.72 ms for the same 120 visible-row updates, still under the 12 ms gate; macOS emitted TIS/keyboard-layout service warnings during that run.
- A post-Room shared-renderer rerun averaged 4.15 ms for 120 visible-row updates with 12 initial and 7 final row instances. The benchmark produced valid JSON, then returned 1 only because the sandbox denied `sysctl kern.clockrate`.
- Rapid page-switch sampling found no sustained main-thread compute stack; physical footprint was 54.8 MB with a 56.9 MB peak during that sample.
- Navigation is isolated from the large settings model, and companion art is downsampled off the main thread before entering the bounded cache.
- Agent activity uses display-paced delta publication plus short semantic states such as `翻工具书中…` and `查近期对话中…`; completed steps freeze and only the live tail continues updating.

## Room Slice

- The production `AgentNewRoomSheet` capture at 556 x 650 has no clipped role rows, overlapping policy controls, or truncated actions.
- Direct Chat and Room use the same AppKit transcript surface; the Room does not introduce a second `LazyVStack` hot path.
- Whole-row Room selection, exact member mention insertion, path paste/drop, and member-specific approval handoff are wired in source.
- This capture is a deterministic production-component fixture. The current Room build was not installed and no live three-provider Room run was available, so it is not recorded as foreground model acceptance.

final result: passed
