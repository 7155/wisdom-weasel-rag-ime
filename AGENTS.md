# Agent Guide

This repository is the product and the self-hosting workspace for Personal
Agent Workbench (PAW). Pi loads this file automatically. Keep it as a bounded
bootstrap and route to the smallest additional context needed for the task.

## Session Bootstrap

1. Read [PROJECT.md](PROJECT.md) for the durable vision, destination, boundaries,
   and non-goals.
2. Read the relevant active entry in [OUTCOMES.md](OUTCOMES.md). Do not preload
   completed history or every product area.
3. Read [CONTEXT.md](CONTEXT.md) only when domain terms or ownership are involved.
4. Read only the related entries in [DECISIONS.md](DECISIONS.md). Use
   [ARCHITECTURE.md](ARCHITECTURE.md) when a change crosses owners, processes, or
   persistence boundaries.
5. Treat `release/product-status.json`, current Git state, Runtime events, and
   fresh checks as machine evidence. Root prose never proves that a Session is
   running, a worktree is clean, or a foreground path passed.

`docs/` is ignored local history. It may be inspected when an exact file is
named as evidence, but it is not the current project index and must not be
loaded wholesale. Design prototypes are references, not current Runtime
contracts.

## Skill Routing

Skills sit below Pi and guide how an Agent works. They do not replace Pi's
Agent loop, Tool loop, context, compaction, Steer, Stop, or cancellation, and
they never become Kernel completion gates. Load the smallest applicable Skill;
simple coherent work needs no workflow Skill.

- `alignment-and-decision`: a material user-owned choice remains after facts
  have been inspected, or the user explicitly asks for Grill Mode.
- `implementation-planning`: the confirmed change has multiple dependent
  steps, owners, shared contracts, integration points, or rollback boundaries.
- `systematic-debugging`: the cause of a failure or regression is not yet
  supported by repeatable evidence.
- `test-driven-implementation`: the desired behavior, owning seam, and a
  meaningful executable check are already known.
- `orchestrate-session`: private child Sessions provide a concrete benefit for
  bounded investigation, implementation, or review.
- `facilitate-room`: only the designated Room Facilitator coordinating visible
  Partner responsibilities, integration, optional review, and one final result.
- `independent-review`: the user asks for a distinct fixed-scope review or the
  change has enough risk to justify one. It is optional, read-only, and not a
  default quality gate.
- `organize-work-documents`: the background organizer or an explicit cleanup
  request links and condenses accepted document updates. It does not perform
  active work or infer Runtime state.

Read a Skill body only after its trigger matches. A Partner or Tool Agent uses
the same task Skills as a standalone Session; Room does not define a second
workflow suite.

## Session, Tool Agent, And Room Choice

- Use one ordinary Session by default.
- Use a private Tool Agent when the parent needs a bounded result and can retain
  responsibility for integration. The parent chooses model/model card,
  thinking level, persona, access, tools, SkillRefs, peer-call access, and
  child-spawn permission within its granted capabilities.
- Use a Room Partner only when work needs a visible, independently accountable
  responsibility in the Room timeline.
- Use several writers only when concurrency has a concrete benefit. Shared
  write access is allowed when the owner accepts conflict risk; an isolated
  worktree is an explicit option, not mandatory ceremony.
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
body only when needed. Stable project meaning comes from root docs. Current
task facts come from the prompt and owned work document. Mechanical facts come
from Runtime, workspace, and Git projections.

Return a bounded `AgentResult`: status, summary, decisions/defaults, changed
files or artifact refs, verification evidence, residual risks, and next action.
Do not dump private reasoning or raw Tool history into parent context.

## Document Responsibility

- `PROJECT.md` changes only when the durable vision, destination, boundary, or
  non-goal is accepted.
- `OUTCOMES.md` is the bounded project focus set. Update it for an accepted
  result, material blocker, or changed next frontier—not every Tool call.
- `DECISIONS.md` stores cross-outcome decisions and their consequences.
- `CONTEXT.md` is a glossary only; it must not become an implementation guide.
- Active Session and Room Agents update only their assigned brief, workboard,
  result, or review document when one exists. Do not create documents for
  trivial work merely to satisfy a process.
- The background organizer consumes document receipts and accepted results,
  fixes links/indexes, and condenses closed material. It must propose rather
  than overwrite ambiguous active meaning.
- Never parse Markdown checkboxes to decide running, stopped, completed,
  accepted, worktree, approval, or Tool state.

## Product Boundaries

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
