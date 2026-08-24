# PAWOS Frontend Continuation Handoff

**Date:** 2026-08-24  
**Audience:** next GitHub-only cloud model on `main`  
**Status:** partial — checkpoint pushed so work is not trapped in a dirty tree  
**This file is progress context, not proof of install, foreground acceptance, or all-App completion.**

## Objective the user owns

Thoroughly reconstruct PAWOS frontend from the user's design, not a colour pass.

- Every App and the OS shell must understand the human purpose in `PAWOS_FRONTEND_CLOUD_MODEL_BRIEF.md`, then **refactor**. Quality bar is very high.
- **Agent App is the most important surface.** Use the in-repo baseline `control-center-web/docs/references/pawos-conversation-baseline.html` plus BRIEF §2 and the interaction contracts. Do **not** fetch Tutti or CodingTo.
- Also inspect performance, flicker, layout jump, and streaming reflow (user: 频闪 / 跳动抽搐 / 拖动卡顿).
- Frontend-only. Do not edit `rag_ime/`, migrations, Pi Runtime, or backend contracts. Do not install unless the user asks.

## Git snapshot (verify at takeover)

```text
branch: main
remote: git@github.com:7155/personal-agent-workbench.git  (account 7155)
base production frontend: e6cca756  (brief + code-reader contrast fix)
```

This checkpoint commit sits on top of two local backend WIP commits that were required so `main` could rebase onto `origin/main`:

1. `771f53ae` `test(room): assert facilitator delegation requires active root work document`
2. `51a2c083` `feat(room): gate facilitator delegation on active root work document`

Do not revert those unless the backend owner says so. Do not commit `integrations/ego-browser/` (vendor tree / `node_modules`).

## Requirement authority (all on GitHub `main`)

Root `/docs/` is gitignored. A cloud model must read the tracked copies:

1. `control-center-web/docs/README.md` — index
2. `control-center-web/docs/pawos/PAWOS_REQUIREMENTS.md` — complete `UR-001`–`UR-132`
3. `control-center-web/PAWOS_FRONTEND_CLOUD_MODEL_BRIEF.md` — `PF-CM-001`–`023` and App specs
4. this file — latest checkpoint
5. `control-center-web/docs/pawos/PAWOS_FRONTEND_HANDOFF.md` — earlier receipts
6. `control-center-web/docs/handoffs/` — function map and privacy-safe fixtures
7. `control-center-web/docs/references/pawos-conversation-baseline.html` — Agent conversation baseline HTML (craft reference, not the App)

Newest explicit user correction wins. Do not silently drop a `UR-*` that the brief only links.

## What this checkpoint contains

In-progress reconstruction from parallel lanes. Capabilities are preserved; none of these Apps is complete against the per-App gate.

| Surface | Files in this checkpoint | What changed |
| --- | --- | --- |
| Files | `src/features/files/PawOsFilesApp.tsx`, `paw-os-files-app.css` | Tree/preview hierarchy, bounded readers, narrow-width back path |
| Terminal | `src/features/terminal/PawOsTerminalApp.tsx`, `paw-os-terminal-app.css` | Tab identity, local overflow, error dismiss, reduced-motion |
| Memory | `src/features/memory/*` (small) | Disclosure/focus/provenance tweaks; not a full six-page rebuild |
| Knowledge | `src/features/knowledge/index.tsx`, `document-workspace.tsx` | Viewer/settings draft-diff direction; ingestion pipeline not finished |
| Room | `PawRoomWorkspace.tsx`, `PawRoomFocusOverview.tsx`, `paw-os-room-migrated-v1.css` | Status language (review vs running colour), compact focus chrome |
| Browser | `paw-browser-host.ts`, **new** `paw-browser-model.ts` | Host types / guest model split started; App UI not rebuilt |
| Brief | `PAWOS_FRONTEND_CLOUD_MODEL_BRIEF.md` | Pointers to recovered `UR-*` Git objects and Codex source tasks |

## What is not in this checkpoint (do these next)

Priority order is the user's:

1. **Agent App (P0).** No files changed yet. Owners: `PawAgentApp.tsx`, `PawAgentHome.tsx`, `PawSessionWorkspace.tsx`, `PawContextTrace.tsx`, `src/features/agent/**`, `paw-os-agent-*.css`. Must keep the code-surface pair in `paw-os-agent-migrated-v1.css` (`--color-code-bg` / `--color-code-text`) and the test `keeps installed Agent raw, code, and terminal readers on a readable code colour pair`.
2. **OS shell.** No files changed yet. Owners: `src/paw-os/shell/**`, `runtime/**`, `paw-os.css`, `paw-os-motion.css`, `paw-os-shell-migrated-v1.css`, `paw-os-polish.css` (warm-paper leftovers).
3. **Project Workbench.** No files changed yet.
4. **Input Studio / App Center / Monitor / Settings.** No files changed yet.
5. Finish Files / Terminal / Memory / Knowledge / Room / Browser against the completion gate.
6. Performance / flicker: streaming reflow, `transition: all`, layout-property animation, backdrop-filter stacks, FOUC. Prior audit lane did not return a receipt.

## Constraints that still bind

- Develop on `main`. Path-qualified frontend commits. No reset/stash of unrelated dirty work.
- One visual language: bright cool rounded desktop; no Composition-8 / warm paper / second chrome.
- 760 / 560 / 375: no document-level overflow, no traffic-light collision.
- Tests from `control-center-web/`: focused vitest `--maxWorkers=1`, `pnpm typecheck`, production `pnpm build`. Screenshots and build are not install/foreground proof.
- User has not asked to install the App in this session.

## Suggested next Session

```text
1. git fetch && git log -1 && git status
2. Read CLOUD_MODEL.md, REQUIREMENTS, BRIEF §2 (Agent), in-repo baseline HTML. Do not fetch Tutti/CodingTo.
3. Reconstruct Agent conversation (tree, composer, rich results, trace)
4. Then shell, then remaining Apps one vertical slice at a time if serial;
   parallel only with hard file-ownership partitions
5. Focused tests + typecheck + production build
6. Honest receipt (template at the end of the brief)
```

## Unverified boundary

- No full vitest suite, typecheck, or production build was run on this mixed checkpoint.
- No installed Electron / foreground check.
- Parallel lanes were interrupted by a model-quota switch; Agent/shell/workbench/system Apps never landed code.
- `integrations/ego-browser/` remains untracked and must stay out of git.
