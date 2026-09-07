# Project Decisions

Updated: 2026-08-31

This file records decisions that stay relevant across Outcomes, not
implementation choices or live status.

## D-001 — Pi Owns Session Runtime

- **Status:** accepted
- **Decision:** Pi remains the only owner of the Agent loop, Tool loop,
  transcript, provider interaction, context/compaction, Steer, follow-up,
  Stop/cancel, and Session recovery. PAW adapts and projects those capabilities.
- **Why:** duplicating them caused divergent ordering, cancellation, context,
  Tool, and terminal semantics.
- **Consequence:** fixes start at the real Pi/adapter boundary. PAW may add typed
  product contracts and receipts but not a second Session engine.

## D-002 — Room Is Session Composition

- **Status:** accepted
- **Decision:** a Room composes one Facilitator and visible Partner Sessions. It
  owns collaboration identity, dispatch, ordered public events, cancellation
  fan-out, and one terminal Root—not a second Agent loop.
- **Why:** Partners already use ordinary Pi Session capabilities.
- **Consequence:** Partners use normal task Skills; review, isolation, and
  fan-out remain risk-shaped choices.

## D-003 — Tool Agents Are Private Child Sessions

- **Status:** accepted
- **Decision:** a parent Session creates Tool Agents for bounded supporting
  work and chooses their context, model guidance, thinking level, persona,
  access, tools, Skills, workspace, peer-call access, and child-spawn ability
  within granted capabilities.
- **Why:** the parent needs useful hands, while responsibility and public Room
  membership must remain explicit.
- **Consequence:** child events/results return to the parent with evidence-only
  authority. Same-tree peer calls are allowed; private transcripts never
  become public Room history.

## D-004 — Skills Are Conditional Methods, Not A Pipeline

- **Status:** accepted
- **Decision:** the core reusable methods are `alignment-and-decision`,
  `implementation-planning`, `systematic-debugging`,
  `test-driven-implementation`, `orchestrate-session`, `facilitate-room`,
  `independent-review`, and `organize-work-documents`.
- **Why:** the retired execution/quality/review/handoff/archive chain repeated
  Runtime and Agent responsibility and forced ceremony onto simple tasks.
- **Consequence:** simple work may use no workflow Skill. A Session selects the
  smallest matching method; review is optional; a missing checkbox cannot
  create a repair turn or prevent completion.

## D-005 — Semantic Documents And Mechanical State Stay Separate

- **Status:** accepted
- **Decision:** documents own meaning and risks; Runtime, workspace, Git, and
  event stores own lifecycle, revisions, Tools, approvals, and cancellation.
- **Why:** Markdown is not lifecycle authority.
- **Consequence:** views may combine both sources but never persist inferred
  Runtime state as fact.

## D-006 — Context Is Bounded And Progressively Disclosed

- **Status:** accepted
- **Decision:** every delegation starts with a bounded TaskBrief plus exact
  ContextRefs and SkillRefs. Stable summaries are loaded before bodies; full
  transcripts, all docs, all Skills, and raw Tool history are excluded by
  default.
- **Why:** long-running work needs stable prompt prefixes, predictable context
  budgets, cache locality, and explicit provenance.
- **Consequence:** information is promoted only through accepted results and
  reduced at each Project/Outcome/Room/Session boundary.

## D-007 — The Git Root Is The Self-Hosting Bootstrap

- **Status:** accepted
- **Decision:** tracked root files hold bounded guidance, project context,
  Outcomes, decisions, glossary, and architecture. Ignored `docs/` remains
  local evidence/history.
- **Why:** Pi auto-loads the root guide; private review packs are not prompt
  sources.
- **Consequence:** root files condense current meaning; history loads by exact
  reference, and checks guard links and budgets without inferring completion.

## D-008 — Workspaces And Review Are Risk-Shaped

- **Status:** accepted
- **Decision:** one sequential writer may use the current authorized workspace;
  shared writes are allowed when the owner accepts conflict risk; isolated
  worktrees serve genuinely concurrent writes. Independent review is selected
  by user request or material risk.
- **Why:** mandatory isolation and review made small work expensive without
  solving semantic conflicts automatically.
- **Consequence:** workspace mode and review evidence are explicit in the
  TaskBrief/result, but neither is a universal gate.

## D-009 — Model Guidance And Persona Are Separate

- **Status:** proposed
- **Decision:** versioned Model Cards hold model advice; Personas hold identity
  and tone; roles select ownership and Skills.
- **Why:** model advice must not become a permanent personality or permission.
- **Consequence:** until Runtime support is verified, do not claim uniform
  thinking controls or Persona-based execution authority.

## D-010 — Adopt Harness Mechanisms Selectively

- **Status:** accepted
- **Decision:** borrow bounded replayable context, model-visible attribution,
  package-owned invariants, quiescent cancellation, and narrow capability seams
  from mature harnesses. Do not copy everything-is-a-plugin topology, a
  second event bus, or an unbounded package/doc graph.
- **Why:** self-hosting requires reliable context and ownership, not the source
  project's entire architecture.
- **Consequence:** every borrowed mechanism must replace a concrete PAW failure
  and fit the existing Pi Session boundary.

## D-011 — Pi Packages Own Installable Agent Capabilities

- **Status:** accepted
- **Decision:** installable Skills, prompts, themes, and extensions use Pi's
  Package resolver; PAW owns discovery, confirmed lifecycle actions, and
  receipts.
- **Why:** a PAW loader would fork Pi bootstrap semantics.
- **Consequence:** new Sessions load active resources; running Sessions keep
  their snapshot. PAWOS and Pi roll back their respective layers.
- **Authorized lifecycle:** the exact user-authorized package change may be
  applied through the current Session's existing execution authority and its
  bound product preview. Do not require a second App Center confirmation for
  the same authority; package content never supplies that authorization.

## D-012 — PAW OS Frontend Stays In The PAW Product Repository

- **Status:** accepted
- **Decision:** React OS names PAWOS’s frontend in `control-center-web`;
  legacy fallback and upstream attribution remain.
- **Why:** contracts, adapters, installation, and acceptance need one revision.
- **Consequence:** PAW owns App identity, presentation state, Browser control,
  permissions, Trace, and Stop without external Runtime dependencies.

## D-013 — Extension App Conversations Are App-Owned Pi Sessions

- **Status:** accepted
- **Decision:** Extension App conversations remain ordinary Pi Sessions but
  carry durable App ownership. Agent lists exclude them; the owning App
  restores and presents them.
- **Why:** vertical Apps need distinct information architecture without
  duplicating Pi or crowding Agent history.
- **Consequence:** ownership is explicit, diagnostics require App/Session
  references, and disabling the surface preserves the audit record.

## D-014 — Explicit Agent Permission Profiles Are System-Wide

- **Status:** accepted
- **Decision:** Sessions retain Read Only (`read_only`), Full
  Access (`per_action`), Workspace Managed (`workspace_managed`), and Full Auto
  (`full_trust`) profiles. Read Only blocks effects; Workspace Managed needs a
  confirmed project; both full-system modes expose `/` and all available
  Tools/Skills by default, with per-action versus automatic effect approval.
  Conversation Tool switches override defaults next turn, preserving permissions.
- **Why:** saved permissions must stay visible and exact.
- **Consequence:** creation, Settings, persistence, and Runtime preserve
  selected profiles and confirmations. Schemas, applicability, atomicity,
  availability, TCC, and Unix permissions remain boundaries.

## D-015 — Experience Leads Runtime Tradeoffs

- **Status:** accepted
- **Decision:** Runtime UX and continuity lead. Only the owner of a concrete
  integrity boundary may block first paint, polling, prompt admission, or
  recovery.
- **Consequence:** one owner per fact; consumers project it. Move duplicate
  guards offline. Privacy, credentials, destructive authority, database
  atomicity, macOS permissions, and immutable artifacts remain hard.

## D-016 — A Room Dispatch Is The Approval Boundary

- **Status:** accepted
- **Decision:** explicit Room dispatch uses `room_unrestricted`; it starts no
  approval Agent and never pauses for a second per-Tool confirmation.
- **Why:** dispatch is already the user's execution action.
- **Consequence:** the gateway durably binds automatic policy and its receipt to
  the exact Room dispatch. Ordinary Sessions keep their selected profile;
  read-only, workspace, applicability, OS, failure, Stop, and cancellation
  boundaries still apply.
