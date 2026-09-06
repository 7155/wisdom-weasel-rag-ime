# Project Context

Updated: 2026-09-06

This is the durable Project Context Pack for Personal Agent Workbench. It is
small on purpose. It preserves direction and boundaries; it does not mirror
Session transcripts, Room events, worktree state, or release evidence.

## Original Vision

The user-owned conversation remains the source record. These explicit user
statements anchor the current direction:

> 以后我就要用 Session 来开发本项目，自举，就像 DeepSeek Harness 那种。

> 一个 Agent，然后调用几个 Session 实例。这些读 docs 和传过来的上下文，自己 loop；事件型地响应，再由一个 Agent 检查汇总。

The durable interpretation is a local-first personal Agent workspace that can
develop and improve itself through reliable Pi Sessions. A Room should be a
simple composition of those Sessions, not a second Agent Runtime or a document
governance engine.

## Current Destination

PAW should support long-running self-hosted development with:

1. a reliable ordinary Session whose streaming, thinking summaries, Tools,
   Steer, Stop, refresh, compaction, and recovery remain truthful over time;
2. private Tool Agents controlled by their parent Session and returning bounded
   events/results;
3. a lightweight Room whose Facilitator composes visible Partner Sessions,
   integrates their evidence, optionally requests review, and emits one final;
4. progressively disclosed context and task Skills that help Agents work
   without duplicating Pi or turning checklists into lifecycle gates;
5. a Pi Package market that can discover, inspect, install, update, roll back,
   or create a missing reusable Skill without turning PAW into a second package
   loader;
6. a Control Center that projects the same authoritative Runtime facts instead
   of maintaining a parallel frontend state machine; and
7. governed local memory, knowledge, input, voice, and browser adapters that
   remain separate from Session/Room ownership.

Agent Lab should become an Agent-led, general SaaS optimization product for developers and small
teams. Skill templates help the Agent produce project-specific artifacts and interfaces;
the platform must not require every project to fill one business schema or fixed workflow.
Users provide a business description or project/material path; Lab guides
real evaluation and improvement, delivering a PAW App and an independently
runnable application with suitable task quality and execution cost.
The [overall product design](control-center-web/docs/pawos/LAB_PRODUCT_DESIGN.md)
links the 2026-09-06 user sources and accepted first-release choices. Lab's PAW
orchestration retains Pi ownership; cloud hosting is a later design frontier.

## Users And Core Jobs

- The primary user develops PAW through PAW itself, continues long tasks across
  Session compaction, and can inspect what is real, pending, stopped, or failed.
- A parent Agent may keep work local, delegate bounded private Tool Agents, or
  enter a Room when several accountable Partners are useful.
- The user can understand results and evidence without reading private
  reasoning or unbounded Tool output.
- Project direction survives individual Sessions without injecting the entire
  project history into every model call.

## Hard Boundaries

- Pi owns the Agent loop, Tool loop, Session transcript, provider interaction,
  context/compaction, Steer, follow-up, Stop/cancel, and Session recovery.
- PAW owns product identity, configured capabilities, durable product events,
  projections, governed local data, and the small amount of composition needed
  between Sessions.
- Room does not introduce a second Provider loop, second Event Bus, mandatory
  quality gate, mandatory reviewer, or natural-language Kernel validator.
- Skills describe conditional methods. They do not grant authority, prove
  completion, or own Runtime state.
- Pi owns Package resolution and the resource loader for extensions, Skills,
  prompts, and themes. PAW owns discovery UX, staged product confirmation,
  installed-version receipts, update, and rollback.
- Documents store accepted semantic meaning. Runtime and workspace services
  store mechanical facts.
- Model cards describe model-specific operating guidance; personas describe
  identity and style. Neither silently changes permissions.
- Memory and Knowledge remain separate governed systems with separate sources,
  stores, retrieval behavior, and evaluation claims.
- Rime/Squirrel remains the sole macOS input frontend and native Pinyin owner.

## Explicit Non-Goals For The Current Destination

- Rebuilding Pi's existing Session, Tool, Steer, cancellation, context, or
  compaction semantics inside PAW.
- A free-form decentralized swarm with implicit ownership.
- Requiring an isolated worktree, reviewer, checklist, or document suite for
  every small task.
- Making Project Field, interactive Markdown, Boundary Revision, shared-resource
  leases, or automatic ChangeManifest prerequisites for Session or Room.
- Loading every project document, Room history, Session summary, or Skill into
  every prompt.
- Claiming native or release acceptance from tests, preview pages, staged
  canaries, or prose.

## Self-Hosting Reading Contract

Pi automatically reads `AGENTS.md`; that file routes a Session here and then to
one active Outcome. Load `CONTEXT.md`, relevant decisions, architecture, source,
and tests only when the task needs them. The normal information path is:

```text
root bootstrap -> current Outcome -> bounded TaskBrief
-> exact ContextRefs and SkillRefs -> source/runtime evidence on demand
```

Results move upward only when accepted:

```text
Session process -> AgentResult -> Room/Outcome result
-> cross-outcome Project fact or decision
```

Every upward step reduces information. No root `PROJECT_SUMMARY.md` should grow
by replaying all lower-level history.

## Evidence Freshness

`OUTCOMES.md` is the human focus set. `release/product-status.json` is the
machine-readable release snapshot and records its own source commit and date.
Current Git state, Runtime events, and fresh verification override stale prose.
