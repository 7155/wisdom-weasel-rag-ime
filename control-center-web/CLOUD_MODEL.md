# Cloud Model 起点（本地归档合并后的只读入口）

You only have this GitHub repository. That is enough. Do **not** clone, fetch,
or request Tutti, CodingTo, local Downloads HTML, or ignored `/docs/` paths.

**交接状态：** 本地 Session 会在整理相关文件、跑新鲜检查、创建提交并把最终
结果合并到 `main` 后，把这一版作为外部前端模型的只读起点。此文件本身不是
安装、Runtime 或前台验收收据；外部模型必须以实际合并提交、检查输出和状态账本
为准。不要因为旧 handoff、截图、diff 或本文件中的摘要把未验证范围当成完成。
在合并收据出现前，`main` 基线仍是待确认的本地交付边界。

合并收据至少要记录最终提交、`main` 合并结果、实际检查输出和仍未验证的 E1–E6
边界。没有对应 Git/Runtime/安装/前台收据的状态，继续标为 pending 或 unverified。

## Read in this order (all in-repo)

1. This file.
2. [docs/handoffs/PAWOS_REAL_FRONTEND_SOURCE_MAP.md](docs/handoffs/PAWOS_REAL_FRONTEND_SOURCE_MAP.md) — current product-entry, 11-App dispatch, leaf render owners, native build-selected surfaces, and explicit exclusions. Its [JSON manifest](docs/handoffs/PAWOS_REAL_FRONTEND_SOURCE_MAP.v1.json) is machine-checked by the tracked `scripts/check_pawos_frontend_source_map.py`; use the manifest before any filename or web search.
3. [docs/pawos/PAWOS_REQUIREMENTS.md](docs/pawos/PAWOS_REQUIREMENTS.md) — complete, append-only user ledger (`UR-001`–`UR-195` in thirteen volumes). Do not trust a hard-coded terminal `UR-*` count in an older handoff; read the current file, and let the newest explicit user correction win.
4. [PAWOS_FRONTEND_CLOUD_MODEL_BRIEF.md](PAWOS_FRONTEND_CLOUD_MODEL_BRIEF.md) — `PF-CM-*`, eleven-App design, completion gate, receipt template. Reconcile it with the newer requirement ledger rather than treating its snapshot counts as current.
5. [PAWOS_FRONTEND_CONTINUATION.md](PAWOS_FRONTEND_CONTINUATION.md) — what already landed on `main` and what is unfinished.
6. [docs/references/pawos-conversation-baseline.html](docs/references/pawos-conversation-baseline.html) — Agent conversation craft baseline. Reference only; do not replace the App with this static page.
7. [docs/pawos/PAWOS_FRONTEND_HISTORY.md](docs/pawos/PAWOS_FRONTEND_HISTORY.md) — earlier receipts. Progress context, not current proof.
8. [docs/handoffs/](docs/handoffs/) — function inventory, per-App function map, privacy-safe fixtures.

Before naming any file as the frontend for a feature, return its exact
`selectionChain`, `renderOwners`, and proof level from the source map. A file
that merely looks relevant is not an owner.

## 外部模型接手边界

接手顺序是：先确认本地最终提交已经合并到 `main`，再从本文件进入需求总索引、
分卷、逐字证据、实施状态和 handoff。先按 `UR-192`–`UR-195` 检查插件市场、
整理归档和交接入口，再对照其余最近需求做前端复核与优化。外部模型不得回到
旧版前端或 ignored 的本机 `/docs/` 猜测当前状态，也不得把源代码/测试/构建
证明升级成安装、Runtime 或前台证明。

Repo-root `PROJECT.md`, `OUTCOMES.md`, `CONTEXT.md`, `DECISIONS.md`, `ARCHITECTURE.md` are already on GitHub. Load them only when the change crosses product vision or owners.

## Do not use

- Tutti, CodingTo, or any other local frontend repo. They are **not** in this repository and must not be downloaded.
- Any machine-local `file://` copy of `pawos-conversation-baseline.html` — the tracked copy is `docs/references/pawos-conversation-baseline.html`.
- Repo-root `/docs/` — gitignored; not on GitHub.
- `integrations/ego-browser/` and Browser-owned surfaces — they are outside this handoff; do not edit them unless the user explicitly opens that scope.
- `rag_ime/`, migrations, Pi Runtime, backend contracts — another owner.

Historical user quotes that mention Tutti remain in the ledger as **intent** (mature disclosure, density, motion). For this GitHub-only Session, implement that intent from the brief's interaction contracts plus the in-repo baseline HTML.

## What to do

**User mandate (2026-08-24, newest wins):** the whole PAWOS desktop may be
optimized. Surfaces that look wrong, feel sticky, or fight the vision may be
**torn down and redesigned**. Agents may invent better interaction and visual
craft within the in-repo UR / PF-CM ledger and product boundaries—do not wait for
a colour pass. Every App may be polished for interaction and UI once its owning
vertical slice is clear.

Suggested order (parallel only with hard file ownership):

1. Finish / deepen **Agent App** (conversation, composer, trace, rich results) and
   **Room planet windows** (compact projection, cross-window flow, focus). Keep the
   code-surface colour pair and its regression test.
2. **OS shell** — windows, Dock, Wayfinder, chrome uniqueness, drag/resize,
   motion/flicker, one visual language. Redesign freely when the current shell
   fails the brand/purpose tests.
3. **Remaining Apps one vertical slice at a time** (Files, Terminal, Memory,
   Knowledge, Browser, Workbench, Input Studio, App Center, Monitor, Settings).
   Each App may be redesigned for human purpose; preserve real Runtime contracts.
4. Keep fixing streaming reflow, layout jump, and flicker wherever they appear.
5. Run focused vitest, `pnpm typecheck`, production `pnpm build` from
   `control-center-web/`. Do not claim install/foreground completion unless the
   user asks to install.

After the local merge receipt is confirmed, work on that `main` baseline. Use
path-qualified frontend commits and preserve unrelated dirty work.
Ignore CI billing failures when merging unless the user asks otherwise.

## Reusable conversation disclosure (Agent lane → Room lane)

The Session conversation-depth lane exposes these modules for reuse by the
Room flow lane (and any surface that renders collaboration receipts). Do not
fork a second projection of the same payloads:

- `src/features/agent/timeline/public-tool-result.ts` —
  `publicToolResultView` projects settled `room_partner` / `agents` / file /
  shell receipts into concrete public payloads (sent messages, TaskBriefs,
  written bodies); `publicToolOutputText` masks and bounds free text.
- `src/features/agent/timeline/route-decision-plan.ts` —
  `routeDecisionPlanView` turns a `rag-ime.room-route-decision.v1` event into
  a dispatch plan (target, reason, wave, candidate scores/signals); rendered
  by `RouteDecisionPlan.tsx` with `.agent-route-plan` styles in `agent.css`.
- `src/features/agent/timeline/ActivitySummary.tsx` — `FxActivityStack`
  collapsible rows plus `PublicToolFields` / `PublicToolRequest` /
  `PublicToolOutput` detail blocks; `SmoothDisclosureReveal.tsx` owns the
  baseline 220ms bounded-spring disclosure motion (`DISCLOSURE_MOTION`).
- `src/features/agent/tool-presentation.ts` — `publicToolName` readable
  labels and `publicToolFamily` one-glyph-per-tool identity for small frames
  (replaces raw “工具 agents” text).

Real-event coverage lives in `src/features/agent/timeline/harness-*.test.tsx`
against `e2e/fixtures/minecraft-harness-20260825`.
