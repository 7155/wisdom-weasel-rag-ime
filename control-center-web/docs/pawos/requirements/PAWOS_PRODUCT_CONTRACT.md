# PAWOS 产品契约

> 导航：[用户逐字证据](PAWOS_REQUIREMENT_EVIDENCE.md) · [总索引](../PAWOS_REQUIREMENTS.md) · 下一份：[实施状态](../PAWOS_REQUIREMENT_STATUS.md)
>
> 本文件承载跨需求的产品定义、所有权边界、App/Room/Browser/动效契约和验收边界。

## Requirement Ownership And Source Order

- The active Session or Room Agent records accepted user requirements and
  corrections here before planning or implementation when they materially
  change product scope, behavior, authority, or acceptance. The
  `organize-work-documents` Skill builds and audits the lossless source-linked
  ledger, but it does not invent product meaning or become the requirement
  owner.
- Source priority is: the user's latest explicit correction, the current Goal
  objective, prior accepted user statements, then attached design or migration
  material. Attachments are references and proposals unless the user explicitly
  adopts them. They never override a later direct correction.
- Preserve corrections rather than silently rewriting history. A disputed or
  inferred decision remains marked as such in `docs/project/DECISIONS.md` until replaced by
  an explicit accepted decision.
- The current accepted correction exposes one top-level **Agent** App. Its
  creation and discovery entry lets the user select Session or Room. Their
  Runtime identity, history, controls, views, windows, and ownership remain
  separate after selection; the single entry does not merge their state.
- The current accepted repository boundary is
  `7155/personal-agent-workbench`. Tutti is a private reference repository;
  PAWOS implementation, documentation, installation, and pushes remain here.
- Default task delivery is concise Markdown and direct file links. Do not load
  or recreate a Skill that turns every result or handoff into a generated HTML
  webpage. Generate an HTML report only when the user explicitly requests one.

## Product Definition

- PAWOS is the primary product surface of Personal Agent Workbench, built and
  released from `7155/personal-agent-workbench`.
- The existing Control Center remains a selectable legacy fallback only until
  the PAWOS replacement passes installed foreground acceptance.
- ChromeOS, Tutti, and other supplied frontends are interaction references.
  PAWOS may migrate and improve useful browser-first workspace, window,
  launcher, Dock, search, Files, Browser, Terminal, rendering, and interaction
  mechanisms behind PAW-owned seams, but it must not copy their Runtime
  ownership, product identity, or architecture or modify an upstream checkout.
- Project Field / Wayfinder is the OS home. It is not another windowed App.
- The supported top-level Apps are Project Workbench, Agent, Memory, Knowledge,
  Input Studio, App Center, System Monitor, System Settings, Files, Browser,
  and Terminal. Session and Room work both begin inside Agent.

The accepted App map is:

| Surface | Product responsibility |
| --- | --- |
| Project Field / Wayfinder | OS home and project selection; never an ordinary App |
| Project Workbench | project overview, Tasks, WorkItems, and WorkDocuments; projects and documents may open in independent windows |
| Agent | one work entry and mode chooser; Session discovery/conversation/roles and Room discovery/collaboration/Workflow remain complete mode-specific workspaces; each Session or Room may open independently and Room partners may use bounded satellite windows |
| Memory | governed personal memory |
| Knowledge | governed knowledge bases and retrieval |
| Input Studio | voice input, input method and lexicon, and input history |
| App Center | Pi Package management and future `paw.appSurface` Apps |
| System Monitor | context inspection, Runtime records, diagnostics, and problem investigation |
| System Settings | configuration, security/governance, models, Providers, and Appearance |
| Files | PAWOS system file workspace adapted from Tutti mechanisms |
| Browser | isolated PAW Browser directly shared by the human and authorized Agent |
| Terminal | real system terminal/PTY, not a simulated terminal panel |

## OS-Native App Surfaces

- Every PAWOS App must be redesigned for an OS interaction model. Wrapping,
  embedding, or restyling an existing Control Center page is not an accepted
  migration.
- This applies to every route and subordinate surface, not only the twelve
  launcher entries. Overview, Planning, Work Documents, Session, Room, Roles,
  Memory, Knowledge, Input, Voice, History, App Center, Observability, Context
  Debug, Diagnostics, Appearance, Configuration, Governance, Approvals, Files,
  Browser, and Terminal each require a new PAWOS information architecture and
  interaction treatment. A shared window frame around an old route does not
  satisfy this requirement.
- Existing feature code may supply typed transports, reducers, controllers,
  and business behavior. It must not dictate the new App's information
  architecture or visual composition.
- "From scratch" applies to the frontend composition and interaction model:
  replacing colors, adding a wallpaper, or placing a legacy feature inside a
  new window is explicitly insufficient. Mature Agent frontends such as Tutti
  or Codex may be used as structural references, but PAWOS must reconnect the
  borrowed presentation grammar to PAW's own authoritative contracts.
- Each App must expose its own primary objects and actions through appropriate
  window layouts, toolbars, inspectors, split views, context menus, shortcuts,
  drag/drop, and cross-App handoffs where those interactions are useful.
- Desktop and object interaction is owned by PAWOS rather than the browser's
  default webpage behavior. Right-click opens a PAWOS context menu specialized
  for the desktop, App, window, file, Session, Room, or selected object.
  Dragging an empty desktop region creates a selection lasso and a real OS
  selection set instead of selecting webpage text. Text selection remains
  available only inside content regions where selecting text is the intended
  action.
- Context menus support focus return, Escape, arrow keys, Enter, edge-aware
  placement, disabled/destructive states, and coarse-pointer alternatives.
  Lasso selection supports additive selection, drag threshold, pointer capture,
  cancellation, and visible selected state without mutating business data.
- Window, Dock, launcher, Mission Control, focus, deep-link, restoration, and
  multi-window behavior must feel like one coherent OS. Layout state remains
  presentation state and never becomes Session, Room, Memory, Knowledge, or
  Package truth.
- Every visible state uses real PAW/Pi data. Mock data is allowed only in tests
  and explicit previews, never as evidence that an installed App works.
- User-facing copy states only the current object, state, available action,
  result, or recovery step. Product vision and architecture rationale stay in
  project documents.
- UI copy must not expose the Agent's design reasoning, internal slogans,
  migration rationale, or phrases such as a product "flywheel" or "starting
  point". Empty states contain only information and actions the user needs.
- Rendering and direct manipulation must remain stable under live Session and
  Room updates. Window dragging, resizing, scrolling, streaming, and timeline
  projection must avoid layout thrash, visible jumping, unnecessary rerenders,
  and main-thread-heavy effects. Tutti's rendering mechanisms may be adapted
  where measured evidence shows they improve PAWOS.

## Agent Is The Single Session And Room Entry

- PAWOS exposes one Agent launcher, Dock, and top-level navigation identity.
  Its new-work surface first distinguishes Session from Room, rather than
  presenting two unrelated creation entries or hiding the choice in a generic
  “new” button.
- Session mode has a quiet, content-first creation surface and one primary
  composer. Before sending, the user selects project or workspace,
  model/thinking profile, permissions, and capabilities without navigating a
  generic dashboard form.
- Room mode has its own Room discovery and creation fields, then opens each
  Room in one complete main window. Optional participant satellite windows may
  expose a Partner's local slice, but the main Room always retains the
  objective, chronological public loops, Workflow, peer relationships,
  approvals, Root convergence, and final answer.
- The shared entry may present combined recent work with a visible type, or
  switch between Session and Room lists. Once a type is selected, list rows,
  filters, creation fields, lifecycle actions, detail views, and windows remain
  attached to that object's authoritative Runtime owner.
- Rooms progressively reveals participants, WorkItems, Workflow, peer traffic,
  approvals, and Root convergence only when those facts exist. Agent never
  displays empty Room chrome, and Rooms never masquerades as an ordinary
  Session list.
- The conversation message flow is itself a new PAWOS surface. User prompts,
  Agent answers, tool execution, progress, approvals, failures, and Room partner
  outputs have distinct hierarchy and state treatment. Repeated tool events are
  collapsed by turn and participant in the reading flow; full evidence remains
  available in a work inspector. Long answers keep a bounded reading measure,
  and the composer remains the single visible next-action entry.
- The PAWOS Agent App must never render the legacy Agent or Rooms page as its
  selected detail. It may reuse reducers, typed command seams, and mature
  content renderers only.
- Frontend replacement is not permission to remove capability. Every
  user-visible Session and Room behavior available in the current Control
  Center remains a parity requirement until it is deliberately superseded by
  an accepted product decision. A visually cleaner page that cannot perform or
  inspect the same work is a regression.
- Session parity includes rich Markdown, code, diff, file, HTML, image,
  terminal, Browser, Tool, reasoning, plan, approval, user-input, error, usage,
  Provider, and cache result rendering; prompt, Steer, Follow-up, Stop, retry,
  continue, rename, compact, history jump, history rewrite, and conversation
  fork; model, thinking, permission, workspace, attachment, Tool, and
  capability controls; Todo/Goal, context, queues, telemetry, background jobs,
  artifacts, workspace files, code intelligence, and private child-Agent
  execution/results.
- Room parity includes the complete public conversation and per-participant
  execution lanes; Root and partner results, Tool evidence, approvals,
  questions, retry, live steer, Stop fan-out, mentions, and attachments;
  participant identity/role/status, topics, WorkItems, dependencies, task graph,
  artifacts, workspace, routing, permissions, Room settings, archive/history,
  and one visible Root convergence result. Compact cards may summarize repeated
  activity, but the complete evidence must remain inspectable.
- Capability controls use progressive disclosure. The primary reading and
  composing path stays calm; Files, task/runtime status, child Agents, Room
  progress, governance, and detailed evidence open as purpose-built panels or
  views without permanently crushing the message column in a normal App window.
- Pi remains the sole Session and Tool loop. Room remains a lightweight
  composition of ordinary Pi Sessions. The single Agent entry does not create
  merged Runtime state, a second Runtime, or a duplicate reducer.

### Session User Experience Contract

From the user's perspective, opening an existing Session must restore a usable
workplace rather than a simplified chat transcript:

1. In Session mode, the Agent rail groups Sessions by project/workspace and
   keeps Room rows visibly separate through the mode chooser. A Session row
   shows title, last useful result or message preview,
   updated time, current/terminal state, and pinned/archived state. Search
   includes the project path and preview. Filters cover Session and archived
   state. Pinning is PAWOS presentation state; archive, restore, and delete act
   on the real Session through owned routes.
2. Clicking, keyboard-opening, or resuming a Session restores the recent
   presentable conversation immediately and then the complete durable context.
   The UI says when complete context is still restoring or only recent context
   is available. It must not label a partial snapshot as fully synchronized.
3. Right-clicking a Session row opens the PAWOS object menu, not the browser
   menu. The same operations remain available through a visible overflow
   control for touch, keyboard, and discoverability. Destructive deletion
   requires an explicit confirmation and leaves the Session intact on failure.
4. The Session header identifies the Session and workspace, shows truthful
   Runtime/recovery state, and offers the small set of global views: results,
   workspace files, private child Agents, and task/runtime status. Rename,
   branch, compact, archive, and other object actions live in one secondary
   action surface rather than permanent toolbar noise.
5. The message column remains the visual center. It restores user prompts,
   assistant answers, public thinking summaries, Tools and operations,
   approvals, questions, failures, plans, diffs, files, HTML, images, terminal
   and Browser results with their current rich renderers. Repeated activity may
   collapse, but every receipt and full result remains inspectable.
6. Per-turn controls include safe retry, continue from the latest interrupted
   turn, jump, edit/rewrite, and fork where the Runtime advertises support.
   Retry reuses the original attachment receipts and idempotency relationship;
   an unresolved or ambiguous admission is never blindly duplicated.
7. The composer restores drafts per Session and exposes attachment/clipboard,
   Tool, workspace, permission, model, thinking, Steer, Follow-up, Stop, and
   advertised Pi/product commands. Busy work changes the delivery choice; it
   does not replace the composer with a second interaction path.
8. Files, task center, and child-Agent workspaces are first-class Session
   views. They include complete child execution/results, Goal/Todo, context and
   compaction, queues, telemetry, jobs, artifacts, workspace tree/preview, and
   code intelligence. At narrow window widths they overlay or replace the
   secondary pane so the reading column is not squeezed into unusability.
9. History navigation, panel changes, menus, state transitions, and result
   disclosure use interruptible PAWOS motion and preserve scroll/focus. Reduced
   motion removes travel/scale while keeping state feedback.
10. Capability parity is checked against the current legacy Session surface
    before cutover. A clean screenshot, mock, or partial historical Session is
    not acceptance; one newly created real Session must exercise the critical
    controls and representative rich results in the installed foreground App.

## Room Collaboration And Workflow

- Every active Room participant is an equal peer. A Partner that needs another
  Partner's information or response contacts that Partner directly with peer
  `@`, ask, reply, or send operations. The Facilitator integrates the final Root
  result; it must not relay, copy, rewrite, or summarize Partner wording to
  simulate direct communication.
- Real division of work requires real WorkItems and accepted dispatches. Merely
  adding participants, a Todo label, an activity card, or prose saying that
  work was assigned is not evidence of delegation. A Room with several workers
  and `workItems=0` has not divided the work.
- The primary Room visualization is the current task Workflow: objective,
  WorkItems, owners, dependencies, parallel branches, handoffs, review only
  when actually requested, failure on the owning node or edge, convergence,
  and the Root result. A communication graph, participant list, stage counter,
  fixed pipeline, or activity count is not a substitute for the Workflow.
- Direct peer communication remains inspectable as a secondary relation layer
  with real source and target. It must not displace or masquerade as the task
  Workflow.
- Public Room content is strictly chronological. One actual model/Tool loop is
  one visible turn card. If a Partner or Facilitator performs another wrap-up,
  repair, review, or finalization loop, it appears as a new card at its real
  chronological position rather than being merged into an older card.
- The user prompt, Partner output, Tool evidence, approvals/questions, and Root
  final answer remain visible in order. The final answer must be easy to find
  without switching to another Session or searching participant lanes.
- A completed Pi turn without a structured Room post must not produce a fake
  "运行结论", "这轮回复已结束", or missing-structured-receipt warning card.
  Truthful participant and turn state remains visible without inventing a
  product conclusion.
- Review is optional and risk-shaped, never an automatic universal gate. If a
  real approval or user decision is required, it appears and can be resolved
  inside the Room that owns it; the user must not be sent to an empty review
  page. Ordinary document synchronization has no human review step and must not
  block finalization.

## Requirements, Context, And WorkDocument Synchronization

- Do not create a second context or document state system. Use the existing
  canonical requirements document, WorkDocument registry, WorkItem authority,
  Session/Room identity, and referenced loading paths.
- Before substantive implementation, the active Agent records new accepted
  requirements or corrections in this file, then updates its owned brief or
  workboard with objective, scope, acceptance, dependencies, references, and
  the next executable frontier. Trivial local changes do not require document
  ceremony.
- Every delegated Room WorkItem has one registered worker WorkDocument. Before
  implementation, its owner writes objective, scope, plan, acceptance, and
  exact references. During work, material discoveries and changed decisions are
  appended. Before finalization, the same document records result, evidence,
  changed files, verification, and residual risk, then emits a revision receipt.
- A new Agent discovers only its own relevant context through
  `AGENTS.md -> PROJECT/Outcome -> TaskBrief/WorkItem -> exact ContextRefs and
  SkillRefs`. It does not preload all docs or scan unrelated Session transcripts.
- The WorkDocument index must expose which documents are active and how to
  resolve the responsible execution identity through
  `WorkDocument -> authorityKey -> WorkItem/session_goal -> participant/Session`.
  Missing peer context is requested directly from that Room participant.
- When a project-bound Session finds no root `AGENTS.md`, the bounded bootstrap
  creates a minimal root guide with `resourceRevision=missing`, indexes the
  canonical requirements and active-doc discovery rules, and never overwrites
  an existing guide. It must not write live Runtime status into `AGENTS.md`.
- Explicit user-selected workspace roots and absolute paths are valid Workspace
  Bindings even when they are outside the process working directory. Tools must
  not reject such a path merely because it is absolute or outside the initial
  cwd. Access remains limited to the exact user-authorized binding; this is not
  blanket filesystem authority.
- Markdown is semantic context, not Runtime truth. Running, stopped, completed,
  approval, WorkItem, Session, workspace, and Git facts remain owned by their
  Runtime projections.

## Files, Browser, And Terminal

- Files, Browser, and Terminal are first-class PAWOS system Apps. Tutti
  mechanisms may be migrated and improved, but each is integrated through
  PAW-owned product identity, capability, lifecycle, and state seams.
- Files exposes real authorized workspace roots, file navigation, previews,
  drag/drop, and cross-App handoff. It does not duplicate WorkDocument or Git
  truth.
- Terminal is a real host system PTY with truthful process lifecycle, resize,
  input, output, Stop, and recovery. A static command card or fake terminal is
  not accepted.

## PAW Browser

- Browser is built into PAWOS and exists primarily for Agents to use. It is not
  a plug-in attached to the user's everyday Chrome and requires no extension,
  pairing code, or extension command queue.
- PAW launches and owns an isolated browser profile. That isolation is the
  Browser sandbox; ordinary personal browser profiles and tabs are outside the
  control boundary.
- Once a Session has the Browser capability, the Agent may directly control the
  PAW Browser without per-site prompts or per-action approval. Capability
  grants, Stop/cancellation, bounded results, secret redaction, downloads, and
  execution traces remain product controls.
- Human and Agent operate the same visible tabs and page state. Both can create,
  select, reorder, navigate, reload, go back/forward, close, click, type, press
  keys, scroll, wait, inspect structured content, capture screenshots, upload,
  and download within the isolated profile.
- Browser is a first-class OS workspace: its tabs, address bar, page viewport,
  downloads, and Agent activity are visible in one App surface. It must not
  expose extension setup or managed/daily-browser modes.

## Interaction And Motion

- Every App requires deliberate interaction polish and motion; static feature
  wiring is not visual acceptance.
- ChromeOS Flex is an explicit system-motion reference. Because ChromeOS Flex
  and ChromeOS share the same underlying system technology, Chromium Ash's
  launcher, overview, window, and gesture behavior is the source reference:
  transform/opacity transitions preserve spatial continuity, gesture-driven
  motion remains interruptible, and the compositor is treated as a performance
  boundary.
- Motion has a named purpose: spatial continuity for windows and App changes,
  state indication for live work, feedback for direct manipulation, and gentle
  bridging for loading or structural changes. Decorative motion must not move
  data the user is reading or acting on.
- Pointer-driven hover/press feedback is subtle and gated to fine pointers.
  Frequently used keyboard actions remain immediate and do not animate.
- Standard UI motion uses shared PAWOS tokens, transform/opacity where possible,
  strong ease-out entrances, ease-in-out movement, short durations, clean
  interruption, symmetric exits, and stagger only when it clarifies hierarchy.
- Rare OS-scale transitions such as launcher-to-overview may use a longer
  approximately 350 ms scale/opacity composition. Ordinary App, panel, list,
  and control transitions stay below 300 ms so motion never becomes waiting.
- `prefers-reduced-motion` is a required behavior, not a later enhancement.
  Reduced motion preserves feedback and fades while removing unnecessary
  travel, parallax, and scale.

## Visual Direction

- The interface is content-first, calm, and spatial. It uses neutral paper-like
  surfaces, progressive disclosure, strong typography, restrained color, and
  clear focus instead of a dashboard landing page or a grid of generic cards.
- The supplied Agent reference is interpreted as: one low-noise Session
  sidebar, one prominent new-Session entry, a centered composer,
  workspace/model/capability selection attached to that entry, and secondary
  controls attached to the composer rather than scattered across the page.
- The three signature themes are **Blueprint**, **Glacier**, and **Ink Paper**.
  They remain available only in System Settings -> Appearance. Theme
  differences must preserve hierarchy, contrast, motion, and App identity
  rather than merely swapping accent colors.
- The final visual-production pass uses GPT Image 2 through the project image
  generation workflow to create the selected raster art system, including
  wallpaper and any accepted onboarding, empty-state, or ambient illustrations.
  Generated art is curated, visually checked, optimized, copied into tracked
  project assets, and wired to real states; it is not used to hide unfinished
  layout, weak typography, or generic interaction design.
- PAWOS visual acceptance targets the finish and cohesion of ChromeOS: one
  deliberate palette and material system, crisp iconography, high-quality
  wallpaper and illustration assets, consistent density, polished focus and
  selection states, and no placeholder or AI-slop imagery. This is a quality
  bar, not permission to copy Google or ChromeOS trademarks or artwork.

## App Center And Packages

- App Center is the visual management surface for Pi Packages and future
  `paw.appSurface` contributions. Package discovery, install, update, enable,
  disable, uninstall, and rollback remain Pi-owned operations.
- Packages without a visual surface remain background capabilities rather than
  fake windowed Apps. A Package surface must declare a bounded App identity,
  permissions, lifecycle, and recovery behavior before it appears in PAWOS.
- PAWOS and Pi must support install, update, enable, disable, uninstall, and
  rollback without creating a second package loader. Newly active Package
  resources apply to new Sessions; an already-running Session keeps its stable
  resource snapshot until its owned lifecycle changes.
- GPT Image 2 art generation is the final visual-production phase after App
  information architecture, interaction, motion, real data, and capability
  parity are accepted. Art generation must not become a substitute for frontend
  implementation, and PAWOS development must not install an `openai` package
  merely to invoke image generation available through Codex.

## Acceptance

Each App is accepted only when all applicable checks pass:

1. real transport and authoritative reducer/service ownership;
2. loading, empty, populated, streaming, error, Stop, and recovery states;
3. App-specific wide and narrow layouts, keyboard navigation, focus, and
   accessibility;
4. window, Dock, launcher, deep-link, restoration, and cross-App behavior;
5. PAWOS right-click menus, desktop lasso/multi-selection, and intentional text
   selection inside content surfaces;
6. purposeful motion plus reduced-motion and coarse-pointer behavior;
7. final GPT Image 2 art assets pass, including visual review at all installed
   target sizes and proof that assets serve real product states;
8. production build, installed native foreground behavior, and a current
   revision receipt.

The full PAWOS cutover additionally requires:

- the reviewed PAW-managed Pi 0.84-compatible Runtime and the matching PAWOS
  frontend installed from one identified revision;
- one real Session and one real Room both started from the single Agent entry;
- a real Room with nonzero WorkItems, direct peer communication, synchronized
  worker WorkDocuments, a truthful Workflow, ordered loop cards, and one visible
  Root final answer;
- direct Agent operation of the isolated PAW Browser without an extension;
- Files and real system Terminal acceptance, multi-window and participant
  satellite acceptance, drag/streaming performance checks, and no visible page
  jumping;
- Package install and uninstall acceptance, three-theme switching in Settings,
  and a verified rollback to a last-known-good Electron release; Swift/WebKit
  Control Center hosts are not a supported fallback.

Pi owning Provider and model interaction does not guarantee that every model
call succeeds. Provider failure, timeout, cancellation, malformed output, and
recovery must remain truthful and must not leave a Session or Room in a false
completed or permanently active state.
## 继续阅读 / 编辑

- 下一份：[PAWOS 需求实施状态](../PAWOS_REQUIREMENT_STATUS.md)
- 返回：[需求总索引](../PAWOS_REQUIREMENTS.md)
