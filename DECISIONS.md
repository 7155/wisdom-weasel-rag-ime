# Project Decisions

Updated: 2026-08-20

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
- **Decision:** a Room is led by one Facilitator Session and may dispatch
  visible Partner Sessions. It adds only collaboration identity, explicit
  dispatch, ordered public events, cancellation fan-out, and one terminal Root.
- **Why:** Partners already need the same Pi execution capabilities as an
  ordinary Session; a second Room Agent loop and hard Kernel stages add failure
  modes without useful work.
- **Consequence:** Partners use ordinary task Skills. Review, worktree isolation,
  and fan-out are conditional decisions by the responsible Agent.

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
- **Decision:** documents own vision, intent, decisions, work meaning,
  results, explanations, and risks. Runtime, workspace, Git, and event stores
  own running/terminal state, ownership, revisions, dirty/head, Tools,
  approvals, sequence, and cancellation.
- **Why:** parsing Markdown as lifecycle authority would recreate the heavy
  Kernel as a fragile document state machine.
- **Consequence:** Project Field and document renderers may combine both sources
  for display but never write inferred Runtime state back into the domain.

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
- **Decision:** tracked root files hold the bounded Agent guide, Project
  context, Outcome focus set, cross-outcome decisions, glossary, and
  architecture. The ignored `docs/` tree remains local evidence/history.
- **Why:** Pi discovers the root Agent guide automatically, while local review
  packs are too large, private, and unstable to be an automatic prompt source.
- **Consequence:** current semantic progress is condensed into root files;
  historical bundles load only by exact reference. A lightweight checker
  guards links, budgets, and retired workflow names without interpreting
  completion.

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
- **Decision:** model-specific operating advice belongs to a versioned Model
  Card, while identity, tone, and social behavior belong to a Persona. A role or
  responsibility selects work ownership and applicable Skills.
- **Why:** advice such as avoiding defensive overengineering may be correct for
  one model and harmful as a permanent character or permission rule.
- **Consequence:** Runtime support and UX still need verification; until then,
  do not claim uniform Provider thinking controls or that persona changes
  execution authority.

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
- **Decision:** installable extensions, Skills, prompts, and themes use Pi's
  Package resolver and resource loader. PAW provides a product market for npm,
  Git, local, and catalog sources, staged confirmation, installed-version
  receipts, update, and rollback. The project `plugin-creator` Skill searches
  and reuses before creating a minimal missing Package.
- **Why:** self-hosting needs discoverable and creatable capabilities, but a
  PAW-specific loader would fork Pi's Session bootstrap and resource semantics.
- **Consequence:** source preparation and inspection never invoke Luna. The
  product asks for confirmation only before installation-state mutation. New
  Sessions receive the active Package resources; running Sessions keep their
  stable snapshot. An Extension App frontend may compile with PAWOS, but only
  its installed-and-enabled Pi Package exposes the App and Skill; disable or
  uninstall removes both. Frontend rollback follows PAWOS, resources follow
  Pi, and surface-less Packages stay background capabilities.

## D-012 — PAW OS Frontend Stays In The PAW Product Repository

- **Status:** accepted
- **Decision:** `7155/personal-agent-workbench` owns PAW Runtime and PAW OS
  frontend. `control-center-web` remains a selectable legacy fallback
  while the PAW OS shell is implemented in the same repository. `7155/tutti` and upstream Tutti are reference sources only, not
  PAW product or release repositories.
- **Why:** one product repository keeps contracts, generated types, reducers,
  Runtime adapters, installation, and frontend acceptance at one revision while
  PAW learns from proven Tutti window, Dock, Mission Control, and App Center
  patterns.
- **Consequence:** PAW OS frontend code and product pushes go only to
  `7155/personal-agent-workbench`. Tutti mechanisms are reimplemented or
  adapted behind PAW-owned seams; no absolute-path dependency,
  cross-repository Runtime state, or wholesale Tutti fork becomes a release
  dependency. Migrated Apps use `paw.*` identities, layout persistence stores
  presentation only, and themes switch only in System Settings -> Appearance.
  Project Field / Wayfinder is the OS home, not an App; route identity stays
  distinct from App identity so Overview, Tasks, and WorkDocuments share
  Project Workbench while other Apps keep bounded surfaces. Browser chrome may
  follow Tutti's interaction grammar, but `deviceId + tabId` selection, the
  command queue, permissions, traces, and Stop stay PAW-owned so human and
  Agent operate one visible page.

## D-013 — Extension App Conversations Are App-Owned Pi Sessions

- **Status:** accepted
- **Decision:** a conversation started inside an Extension App remains an
  ordinary Pi Session for execution, transcript, Stop, recovery, approval, and
  audit, but carries durable App surface ownership. Agent's ordinary list and
  history search exclude it; only its owning App restores and presents it.
- **Why:** vertical Apps need their own information architecture and visual
  language without duplicating Pi or filling Agent with implementation-facing
  App conversations.
- **Consequence:** App ownership is persisted and queried explicitly rather
  than inferred from titles or browser storage. Diagnostics and evaluations
  may inspect it only through explicit App/Session references, and disabling
  the App removes its surface without deleting the underlying audit record.
