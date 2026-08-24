# Cloud model start here

You only have this GitHub repository. That is enough. Do **not** clone, fetch,
or request Tutti, CodingTo, local Downloads HTML, or ignored `/docs/` paths.

**Status of the product work:** partial reconstruction on `main`. Continue it.
Do not restart from a blank UI. Do not treat this file as install/foreground proof.

## Read in this order (all in-repo)

1. This file.
2. [docs/pawos/PAWOS_REQUIREMENTS.md](docs/pawos/PAWOS_REQUIREMENTS.md) — complete user ledger `UR-001`–`UR-132`. Newest explicit user correction wins.
3. [PAWOS_FRONTEND_CLOUD_MODEL_BRIEF.md](PAWOS_FRONTEND_CLOUD_MODEL_BRIEF.md) — current `PF-CM-001`–`023`, eleven-App design, completion gate, receipt template.
4. [PAWOS_FRONTEND_CONTINUATION_HANDOFF.md](PAWOS_FRONTEND_CONTINUATION_HANDOFF.md) — what already landed on `main` and what is unfinished.
5. [docs/references/pawos-conversation-baseline.html](docs/references/pawos-conversation-baseline.html) — Agent conversation craft baseline. Reference only; do not replace the App with this static page.
6. [docs/pawos/PAWOS_FRONTEND_HANDOFF.md](docs/pawos/PAWOS_FRONTEND_HANDOFF.md) — earlier receipts. Progress context, not current proof.
7. [docs/handoffs/](docs/handoffs/) — function inventory, per-App function map, privacy-safe fixtures.

Repo-root `PROJECT.md`, `OUTCOMES.md`, `CONTEXT.md`, `DECISIONS.md`, `ARCHITECTURE.md` are already on GitHub. Load them only when the change crosses product vision or owners.

## Do not use

- Tutti, CodingTo, or any other local frontend repo. They are **not** in this repository and must not be downloaded.
- `file:///Volumes/.../pawos-conversation-baseline.html` — the tracked copy is `docs/references/pawos-conversation-baseline.html`.
- Repo-root `/docs/` — gitignored; not on GitHub.
- `integrations/ego-browser/` if present untracked — do not commit it.
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
   **Room satellites** (compact projection, cross-window flow, focus). Keep the
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

Work on `main`. Path-qualified frontend commits. Preserve unrelated dirty work.
Ignore CI billing failures when merging unless the user asks otherwise.
