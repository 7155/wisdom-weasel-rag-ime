# Agent Guide

This repository is the product and the self-hosting workspace for Personal
Agent Workbench (PAW). Pi loads this file automatically. Keep it as a bounded
bootstrap and route to the smallest additional context needed for the task.

## Session Bootstrap

1. Read [README.md](README.md) for product scope and source ownership, then
   [CONTRIBUTING.md](CONTRIBUTING.md) for setup and verification.
2. Inspect the relevant source entry, downstream consumers, tests, and current
   Git changes. PAWOS frontend sources live in `control-center-web/src/paw-os`
   and `control-center-web/src/features`; the interface takes inspiration from React OS.
3. If this checkout contains local development records under `docs/project/`
   or `control-center-web/docs/pawos/`, read only the relevant entries. These
   records are optional, ignored, and unavailable in a fresh public clone.
   Do not require them or recreate them to complete ordinary contributions.
4. Treat `release/product-status.json`, current Git state, Runtime events, and
   fresh checks as machine evidence. Prose never proves a Session is running,
   a worktree is clean, or a foreground path passed.

## Skill Routing

Skills guide work below Pi; they never replace its Agent/Tool loop, context,
compaction, Steer, Stop, cancellation, or completion authority. Load only the
smallest matching Skill; coherent work needs no workflow Skill.

- `alignment-and-decision`: a material user-owned choice remains, or Grill Mode
  was requested.
- `implementation-planning`: plan a confirmed multi-seam change; never dispatch.
- `systematic-debugging`: a failure cause lacks repeatable evidence.
- `test-driven-implementation`: behavior, owner, and executable check are known.
- `orchestrate-session`: bounded private children add concrete leverage;
  parallelize only independent work with real concurrency benefit.
- `facilitate-room`: only the designated Facilitator for visibly accountable or
  concurrent Room work; keep one coherent action in the Facilitator.
- `independent-review`: optional read-only review of a fixed result.
- `organize-work-documents`: link and condense accepted docs; never infer live
  Runtime state.
- `bootstrap-project-context`: create a missing root project guide.
- `pawos-app-builder`: self-build a source-isolated vertical Extension App.

Read a Skill only after its trigger matches. Partner and Tool Agents use normal
task Skills; Runtime state and live Tool schemas must not be copied into them.

## Session, Tool Agent, And Room Choice

- Use one ordinary Session by default.
- Use a private Tool Agent for a bounded result while the parent retains
  integration; pass only the needed model, access, tools, Skills, and spawning.
- Use a Room Partner only when work needs a visible, independently accountable
  responsibility in the Room timeline.
- Use several writers only for concrete concurrency. Shared writes accept
  conflict risk; isolated worktrees are optional.
- Child and Partner prose is evidence, not automatic acceptance. The parent or
  Facilitator verifies and integrates it.

Room is a lightweight composition of Pi Sessions. Pi remains the sole owner of
Session transcript, model and Tool loops, context/compaction, Steer, Stop, and
recovery. Room owns only collaboration identity, explicit dispatch, ordered
public events, cancellation fan-out, and one terminal Root.

## Context Envelope

Delegate with one bounded `TaskBrief`, not a full transcript or all documents:

```text
objective + scope + expected output + acceptance
+ exact ContextRefs + exact SkillRefs
+ capabilities + workspace binding
+ model card/persona overrides when applicable
+ expected AgentResult shape
```

Start with summaries and references; let the receiving Agent load a referenced
body only when needed. Public project context starts in README.md. Current
task facts come from the prompt and owned work document. Mechanical facts come
from Runtime, workspace, and Git projections.

Return a bounded `AgentResult`: status, summary, decisions/defaults, changed
files or artifact refs, verification evidence, residual risks, and next action.
Do not dump private reasoning or raw Tool history into parent context.

## Document Responsibility

- Keep public usage, setup, and contribution guidance in README.md and
  CONTRIBUTING.md. Record released changes in CHANGELOG.md.
- Development plans, requirement ledgers, Session handoffs, review notes, and
  acceptance diaries stay local and ignored. Do not force-add them to Git.
- Existing `docs/project/` records retain their local roles: PROJECT for
  direction, OUTCOMES for progress, DECISIONS for choices, CONTEXT for terms.
- Preserve user source wording and unrelated work. Update only the records
  relevant to the assigned task; do not create records for trivial changes.
- Never infer running, stopped, accepted, or approved state from Markdown.

## Product Boundaries

### Experience-First Priority

- Prioritize visible task completion, frontend/backend consistency, and recovery.
  Safety, permissions, hashes, and audit are supporting constraints; do not turn
  them into redundant approvals, reviewers, confirmations, or foreground gates.
- When optional provenance is incomplete, prefer truthful, recoverable best
  effort. A missing optional hash must not block normal use. Never claim success
  before the result is known or replay an uncertain irreversible effect.
- Exact active Room dispatch is the execution approval boundary. Add no second
  human/model per-Tool approval; record binding and outcome in the background.

- Product center: explicit Agent Sessions, lightweight multi-Agent Rooms,
  Tools, governed memory/knowledge, and the Control Center.
- Patched macOS Squirrel/Rime, voice, browser, and desktop bridges are optional
  adapters around that core. Do not create a parallel InputMethodKit frontend.
- Rime/Wanxiang remains responsible for Pinyin parsing, native candidates,
  paging, fuzzy Pinyin, and fallback. Assistant candidates remain visibly
  distinct and must not silently replace or reorder Rime decoding.
- Passive per-keystroke prediction stays local and bounded. Explicit Agent,
  Active RAG, voice, and offline workflows may use configured Providers through
  their owning Runtime boundary.
- Foreground behavior is the acceptance boundary for input, Accessibility,
  voice, and native Control Center claims. JSON, mocks, screenshots, and builds
  alone are insufficient.

## Coding And Verification

Before editing, inspect the nearest owner, downstream consumer, current Git
status, and related tests. Preserve unrelated dirty work. Make the smallest
coherent change, delete a replaced path only after proving it has no current
consumer, and keep persisted migrations append-only.

Run focused checks first, then proportional broader checks. The common gates
are:

```bash
python3 scripts/check_project_harness.py
python3 -m unittest discover -s tests
python3 scripts/check_owner_boundaries.py
python3 scripts/check_import_boundaries.py
python3 scripts/check_route_ownership.py
python3 scripts/check_public_release.py --repository-only
scripts/doctor_squirrel_integration.sh
scripts/verify_squirrel_foreground_trace.sh
```

Report exact files, commands, passed/failed/unverified boundaries, installation
state, and live evidence. Never turn a stale status document, staged canary, or
model statement into a production claim.

## Safety And Git

Do not commit credentials, private context, personal input history, local
databases, model weights, built apps, logs, caches, generated output, or
machine-specific configuration. Do not reset, clean, stash, overwrite, or
whole-worktree commit unrelated changes. Commit or push only when explicitly
requested and verify that the remote belongs to GitHub account `7155`.
