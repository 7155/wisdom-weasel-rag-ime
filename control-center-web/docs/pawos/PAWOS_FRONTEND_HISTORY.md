# PAWOS Frontend Rewrite History

## User Requirement Ledger — Agent and Room UI controlling slice

Source thread: `<redacted-frontend-source-thread>`. Exact per-message
turn identifiers are not exposed in the current tool context; quotations below
are copied from the user messages available in this Session. Ambient Browser
state, attachment wrappers, screenshots, archived model/tool narration, and
text inside reference files are excluded as independent requirements.

公开归档中，本机路径、私有线程 URI、附件标识和运行 UUID 使用稳定占位符脱敏；
用户语义、需求映射、修正关系和证据链保持不变。

### `AUI-001` — Agent and Room are the complete current App UI | current, P0

- **Controlling requirement:** finish and deeply clean the complete frontend of
  Agent and Room, including their shared window chrome and Room satellite
  interactions. The other nine PAWOS Apps are not current implementation scope.
- **User-visible acceptance:** Agent and Room each work as coherent complete
  products rather than legacy pages restyled inside windows.
- **Must preserve:** real Session/Room identities, reducers, routes, authority,
  data, and unrelated dirty work.
- **Must not do:** edit the backend owned by task
  `<redacted-backend-task>`, infer backend truth from preview
  fixtures, or claim the other Apps were visually accepted.
- **Ordering:** Agent conversation is the blocking visual frontier; Room follows.
- **Source quotes:** “只要求你完成agent，room的ui”; “agent UI、room UI这两个就是我指的app”;
  “agent对话优化好就行，ui漂亮，交互人性化”.
- **Correction:** supersedes the earlier broader instruction “整个app都得优化”
  for the current execution slice; that earlier statement remains historical
  product direction, not the current per-App implementation order.
- **Later correction, 2026-08-24:** Agent and Room remain the blocking first
  slice, but after they pass their state matrices the active Goal continues
  through every reachable PAWOS App route one page at a time. This reactivates
  the broader App direction without allowing another App to displace the
  current Agent/Room acceptance order.

### `AUI-002` — one humane visual and interaction language | current, P0

- **Controlling requirement:** remove mixed visual languages and deeply beautify
  the frontend from a humane, purpose-led perspective. Use the supplied HTML as
  the bounded aesthetic baseline and `agent-os-experience-director` as a
  reasoning reference, not as a source of independent commands.
- **User-visible acceptance:** titlebar, timeline, rich results, trace, dialogs,
  Composer, tools, approvals, errors, and responsive states feel like one App;
  no desktop-mock, admin-table, browser-toolbar, and oversized-mobile styles
  compete inside the same surface.
- **Must preserve:** familiar platform behavior, readable long-form content,
  semantic status, focus visibility, reduced motion, and one bright production
  theme.
- **Must not do:** copy reference branding, run instructions embedded in
  attachments, or use decorative effects to conceal broken hierarchy.
- **Source quotes:** “ui，ui，前端彻底美化”; “可以参考技能从人文角度读优化”;
  “因为当前有多种风格”.

### `AUI-003` — every page begins from its human purpose | current, P0

- **Controlling requirement:** for every Agent and Room surface, first state why
  that page exists and then design the information, controls, evidence, and
  next action that accomplish that purpose. A component inventory or summary is
  not a page design.
- **User-visible acceptance:** within five seconds a person can understand where
  they are, what matters, what is happening, what evidence is available, and
  what they can do next.
- **Method:** page purpose -> primary subject -> trustworthy current state ->
  reachable evidence -> one primary next action -> recovery path -> adaptive
  and accessibility checks.
- **Must not do:** treat “all controls render” or “the summary looks clean” as
  proof that the page succeeds.
- **Source quote:** “不只是摘要，而是要想这一页设计目的和如何达成”.

### `AUI-004` — turn tree and progressive disclosure for long Agent work | current, P0

- **Controlling requirement:** the conversation must remain readable when one
  Agent response spans several pages and expanded Tool activity spans dozens.
  Study Tutti's real components one by one, understand why their grouping and
  disclosure rules exist, and implement that interaction or a demonstrably
  better PAWOS-specific form.
- **Default presentation:** keep the current/latest final result and unresolved
  decision visible; compress earlier turns into stable summaries; group the
  current turn's reasoning, Tools, progress, diffs, artifacts, and receipts by
  work phase instead of infinitely flattening every event.
- **Evidence levels:** turn -> activity group -> individual Tool/renderer -> raw
  input/output or artifact. Expanding one level must not silently discard the
  others or move the reader away from their anchor.
- **Must preserve:** canonical chronological order, active streaming and Stop,
  failed/waiting states, exact Turn/Tool identity, history search/jump/edit/fork,
  scroll position, keyboard operation, narrow layout, and reduced motion.
- **Must not do:** hide evidence permanently, auto-collapse an item the user is
  reading, infer state from DOM position, or copy Tutti's brand styling without
  its behavioral reasoning.
- **Source quote:** “比如对话用树状多次折叠平时只显示最后一条结果，前面叠一起，是因为agent输出一条消息会几页篇幅，展开工具调用可能几十页。这些你都要看，都要参考tutti这些。他们这样做的原因。然后我们如何实现这种交互，或者更好的交互”.

### `AUI-005` — summaries must reach concrete evidence | current, P0

- **Controlling requirement:** every visual disclosure affordance must actually
  open, and context assembly must expose the concrete content it claims to
  summarize. The rule applies to every Agent/Room interface, not only trace.
- **User-visible acceptance:** system prompt, Tool schemas, ordered context
  messages, and current input can be opened and read in trace; the same path
  exists for claimed diffs, Tool results, artifacts, approval scope, errors,
  recovery evidence, and other summarized content.
- **Interaction acceptance:** pointer and keyboard open/close, visible focus,
  truthful `aria-expanded`/native disclosure state, long-content scrolling,
  stable reading position, and a clear static treatment for rows with no detail.
- **Must not do:** render invalid `<summary>` markup, use a chevron or hover state
  on a static row, or substitute token counts and labels for actual evidence.
- **Source quotes:** “这些无法点击展开，很多都要检查是否能够点击展开”;
  “提示词要展开看具体的呀，不然上下文装配看什么？？。所有每一个界面都要这样做想想”.

### `AUI-006` — page-by-page, state-by-state visual acceptance | current, P0

- **Controlling requirement:** inspect Agent conversation one page/state at a
  time with no visible contamination before claiming it complete.
- **Required state coverage:** empty/welcome, default conversation, very long
  history, streaming/Steer/Follow-up/Stop, Markdown, tables, code, unified diff,
  HTML, Tool calls/results, artifacts/files/media, approval/rejection, grouped
  questions, error/retry/continue, interrupted/aborted, model changes, trace,
  Session tools, capability/permission/model controls, Composer, focus,
  reduced motion, and regular/narrow windows.
- **Evidence levels:** focused behavior tests, typecheck, production build,
  visible 1080/560/375 Browser interaction passes, then separately installed
  native foreground and real transport proof.
- **Must not do:** convert fixtures, tests, a screenshot, or a build into installed
  product acceptance.
- **Source quotes:** “agent对话，一页一页检查，不允许任何玷污”;
  “渲染要美观，你要生成各种格式的数据检验渲染，就是ai的各种结果，md，diff，html，工具调用。每个按钮的位置现在都得打磨好了”.

### `APP-001` — continue the same strict inspection through every PAWOS App | current, P1 after Agent/Room

- **Controlling requirement:** after Agent and Room, open every reachable App
  route and inspect it page by page rather than declaring the shell complete.
- **User-visible acceptance:** no titlebar overlap, clipped first row, doubled
  scroll reserve, checkbox/label collision, pill crowding, control overflow, or
  unpolished intermediate width remains on any checked page. `/input` is the
  first explicit downstream defect fixture.
- **Method:** for each route record its human purpose, production component and
  CSS owner, real state fixture, 1080/560/375 or applicable window widths,
  pointer/keyboard path, visible geometry, recovery state, focused tests, and
  Browser evidence before moving to the next route.
- **Ordering:** finish the active Agent P0s, then Room including satellites,
  then proceed through the remaining App route matrix. Independent defects may
  be diagnosed in parallel when they do not conflict with the blocking owner.
- **Source quote:** “后续app一个一个页面检查，这种错位还有不精致严格检查”.

### `RUI-001` — meaningful Room solar hierarchy | current, P1 after Agent

- **Controlling requirement:** Room is `Sol`; Partners use stable planet names;
  each Partner's subagents use moons or another subordinate celestial identity.
  Room and partner satellites must be beautiful, meaningful, and interactive.
- **User-visible acceptance:** the solar metaphor clarifies collaboration
  ownership and hierarchy; main Room, Partner, and child-Agent states remain
  readable and controllable rather than becoming decorative geometry.
- **Must preserve:** backend IDs and authority; celestial names are presentation
  identities only.
- **Must not do:** restore retired persona labels or invent spatial relations
  with no collaboration meaning.
- **Source quote:** “我们就用太阳系，room为sol，伙伴为各个行星的名称，伙伴的subagent为卫星或者其他有意思的”.

### `DOC-001` — lossless requirement and method continuity | current, P0

- **Controlling requirement:** record all of these requirements and methods and
  apply the same purpose/evidence/interaction reasoning to every interface.
- **Acceptance:** this ledger preserves controlling meaning, quotations,
  corrections, ordering, prohibitions, and acceptance boundaries; progress and
  terminal receipts remain separate later revisions.
- **Must not do:** silently condense a concrete requirement into “polish UI”,
  delete superseded history, or mark work complete from document prose.
- **Source quotes:** “这些要求和方法全部记录，每个界面都这样做”;
  “Tutti 的真实组件去一个一个读，”.

### Source coverage audit

| Available user source | Mapping |
|---|---|
| Agent/Room-only corrections | `AUI-001` |
| full frontend beautification, humane reference, mixed styles | `AUI-002` |
| page-purpose correction | `AUI-003` |
| tree/multi-level folding and Tutti reasoning | `AUI-004` |
| broken disclosures and concrete prompt evidence | `AUI-005` |
| page-by-page/rich-format/deep interaction inspection | `AUI-006` |
| later all-App route-by-route strict inspection and `/input` misalignment | `APP-001` |
| Sol/planet/moon Room presentation | `RUI-001` |
| record all requirements/methods; read real Tutti components | `DOC-001` |
| ambient Browser URLs and attachment wrapper prose | excluded: non-requirement |
| screenshots | reference-only visual evidence, mapped where cited |
| exact per-message turn identifiers | unavailable evidence gap |

Updated: 2026-08-23

- **Document role:** active Session Goal workboard
- **Owner:** active PAWOS frontend implementation Session
- **Status:** active frontend cleanup and per-App completion; Agent first
- **Revision:** `pawos-frontend-workboard.r79-frontend-cleanup-agent-first`
- **Canonical requirements:** [PAWOS_REQUIREMENTS.md](PAWOS_REQUIREMENTS.md)
- **Current outcome:** [O9](../../../OUTCOMES.md#current-focus)
- **Relevant accepted decisions:** [D-012, D-013, D-014, D-016, D-017, D-018](../../../DECISIONS.md)
- **Runtime status:** query Pi/PAW projections; this Markdown does not own it
- **Registry receipt:** intended `session_goal` WorkDocument; binding and
  revision receipt remain unverified because the current Codex environment
  does not expose the PAW WorkDocument registry operation

## Source Priority And Repository Boundary

The user's latest explicit correction and the current Goal take precedence over
earlier summaries and attached migration proposals. This handoff records a
source/document snapshot; whether it is committed, merged, installed, running,
or foreground-accepted must be read from current Git, Runtime, and E1–E6
receipts. It does not claim those states. Tutti is the primary
functional and interaction baseline: corresponding UI mechanisms may be copied
or adapted directly under its Apache-2.0 terms, with applicable source-change,
license, and NOTICE attribution retained. Copied components terminate at
PAW-owned contracts; Tutti Runtime ownership, product identity, trademarks, and
cross-repository state do not enter PAWOS.

Preserve the dirty worktree. Do not reset, stash, clean, overwrite unrelated
changes, or restart from the retired `components/paw-os` shell or separate
`paw-os` experiments.

Default delivery is Markdown with direct file links. Do not load or recreate a
generic Skill that turns results or handoffs into generated HTML pages. HTML is
produced only when the user explicitly requests an HTML artifact.

## Accepted Product Shape

Project Field / Wayfinder is the OS home and project selector, not an ordinary
App. The top-level Apps are:

1. Project Workbench
2. Agent
3. Memory
4. Knowledge
5. Input Studio
6. App Center
7. System Monitor
8. System Settings
9. Files
10. Browser
11. Terminal

Agent is the one work entry. Its new-work and discovery surface explicitly
selects Session or Room, then opens a complete mode-specific workspace. Session
owns ordinary conversation, roles, controls, results, and independent Session
windows. Room owns collaboration, real task Workflow, participant views, one
complete main Room window, and the current active participant satellite windows
that form the Room's actual focus presentation. Wide layouts place the
constellation around the main Room; narrow 5/7-partner layouts use one
horizontally accessible rail instead of crushing or stacking unreadable windows. They may
share typed transports, reducers, result renderers, timeline/composer
primitives, inspectors, and motion, but their Runtime identities and lifecycle
actions stay distinct.

The existing Control Center remains a selectable fallback until the PAWOS
frontend passes installed foreground acceptance. The target is a complete
frontend rewrite of information architecture, composition, interaction,
windowing, motion, and visual system—not legacy pages restyled or placed inside
window frames.

## User-Facing Rules

- Show only information and actions the user needs. Do not put product vision,
  design reasoning, migration rationale, internal slogans, “flywheel”, or
  “starting point” language in the UI.
- Keep every App visually and verbally clean. Implementation protocols,
  capability declarations, sandbox/profile explanations, and architecture
  labels stay out of the interface. Browser in particular presents only normal
  browser chrome and page content; an empty tab is completely blank and a
  missing snapshot on that empty tab is not a user-facing error.
- The installed macOS host uses one top bar. Extend PAWOS content into the
  native titlebar, retain the traffic-light controls in that same row, and do
  not stack a separate native title strip above the PAWOS status bar.
- Remove the `澄` name and the visible role/Persona product area. Agent copies
  Tutti's Composer settings shape: model, reasoning, permission, project, and
  the one Session/Room conversation-type control live in the Composer footer.
  Quick Prompt controls are removed from PAWOS. Legacy role identity
  may remain internal during Runtime migration but is not a PAWOS navigation,
  setup, or settings concept.
- Keep primary content readable. Inspectors and secondary panels use progressive
  disclosure and must not permanently crush the central reading column.
- Window dragging, resizing, scrolling, live streaming, Room event projection,
  and timeline updates must avoid layout thrash, visible jumping, unnecessary
  rerenders, and main-thread-heavy effects.
- The current implementation ships one bright, light, youthful default theme.
  Multi-theme work is explicitly deferred until this single production path is
  installed and accepted. Dark surfaces remain only where function requires
  them, such as Terminal, code, or media.
- Missing curated art may be requested from the user with an exact image
  generation prompt after layout, interaction, real data, and motion are sound.

## Session Acceptance Contract

The Agent App must retain the complete existing Session capability set while
redesigning its presentation: rich result renderers; prompt, Steer, Follow-up,
Stop, retry, continue, approvals, questions, attachments; model, thinking,
permissions, workspaces, Tools; rename, compact, history jump/rewrite/fork,
archive/restore/delete; Goal/Todo, context, compaction, queues, telemetry, jobs,
artifacts, workspace files, code intelligence, and private child-Agent
execution/results.

One new real Session in the installed App must prove recent/full restoration,
truthful partial/recovery state, safe retry identity and attachment reuse,
streaming, representative rich results, Stop, window restoration, and narrow
layout. A historical screenshot or development preview is not acceptance.

## Room Acceptance Contract

- Room is a desktop window constellation, not an internal participant-card
  graph: one centered main Room window automatically opens up to five active
  Partner Agent satellite windows around it. The main window retains focus;
  explicit Partner activation raises only that satellite.
- Partner satellite content is that Partner's chronological public conversation
  plus its real Tool/progress trajectory. A concise identity/purpose header states
  the partner, collaboration responsibility, current WorkItem, and latest activity;
  it does not grow into duplicate navigation, settings, Composer, raw receipt panel,
  or a second main Room task surface. Trajectory entries stay inline and compact.
- Cross-window request, question, answer, plan, document, ContextRef, WorkItem,
  and result paths are projected from authoritative Room events. The Room
  timeline/ledger remains the readable chronological projection; an internal
  duplicate set of participant nodes is removed.

- Every active participant is a peer. A Partner contacts another Partner
  directly through peer `@` ask/reply/send; the Facilitator must not relay or
  rewrite wording to simulate peer communication.
- Real division requires accepted WorkItems and dispatches. Multiple
  participants with `workItems=0` is not division.
- The primary graph is the real task Workflow: objective, WorkItems, owners,
  dependencies, parallel branches, handoffs, optional review only when
  requested, failure on its owning node/edge, convergence, and Root result.
  Communication relationships are a secondary layer, never the Workflow.
- Public content is strictly chronological. One real Pi model/Tool loop is one
  visible card. A later repair, review, wrap-up, or finalization loop creates a
  later card instead of rewriting an earlier one.
- The Root final answer is visible in the Room reading flow. Do not invent the
  “运行结论 / 这轮回复已结束 / 未提交结构化交付回执” card for a completed
  Pi turn without a Room post.
- Review is optional and risk-shaped, not an automatic gate. A real approval or
  user decision appears and is resolved inside the owning Room; no empty
  external review page blocks collaboration.
- Every delegated WorkItem opens and updates its worker WorkDocument before,
  during, and after implementation, then returns a revision receipt before Root
  integration.

- Session subagent runs can leave the side panel and open as PAWOS satellite
  windows. Their compact content prioritizes public conversation, Tool progress,
  questions/answers, and final output; launch configuration and panel statistics
  stay in the main Session. This same satellite identity participates in
  Overview and source-to-child event motion.

## Context And WorkDocument Contract

Do not create a second context system. The bounded reading path is:

```text
AGENTS.md -> PROJECT/Outcome -> TaskBrief or WorkItem
-> exact ContextRefs and SkillRefs -> source/runtime evidence on demand
```

The active owner records accepted material requirements before planning or
implementation. A substantive Goal or delegated WorkItem then maintains one
owned WorkDocument:

1. **Opening revision:** objective, scope, plan, acceptance, dependencies,
   exact source/document references, and authority key.
2. **Progress revisions:** material discoveries, user corrections, changed
   decisions, and current next executable frontier.
3. **Closing revision:** result, changed files/artifacts, verification evidence,
   residual risk, and revision receipt.

Discovery follows
`WorkDocument -> authorityKey -> WorkItem/session_goal -> participant/Session`.
The background organizer may link, index, and condense accepted receipts; it
does not author active meaning or infer Runtime state. A missing root
`AGENTS.md` gets a minimal bounded bootstrap with
`resourceRevision=missing`; an existing guide is never overwritten. Exact
user-bound absolute workspace paths are valid even outside the process cwd and
must not be rejected merely for that reason.

## Current Source Inventory And Known Gaps

The active PAWOS frontend is under `control-center-web/src/paw-os/` and
`control-center-web/src/features/paw-os/`. Existing typed reducers, transports,
and mature result renderers remain the capability owners; PAWOS is their window
and interaction projection rather than a second Runtime.

The source now has one Agent App identity with an explicit Session/Room choice,
mode-correct shared rail, optimistic first-message admission, dedicated Session
and Room workspaces, same-Session conversation/trajectory switching, Room and
subagent satellites, real Files/PTY/Browser surfaces, and existing feature Apps
adapted through their current route and transport owners. Session recent/full
recovery, retry identity, attachments, rich timeline/composer controls, status,
files, and subagents are connected through the existing Agent reducer and Pi
routes. Room uses the existing Room reducer, live event session, Workflow,
governance, approvals, artifacts, direct participant controls, and cancellation
routes.

Source presence is still not installed foreground acceptance. The remaining
open boundary is one concentrated type/test/build gate, Preview installation,
and real foreground proof for Pi first-delta latency, Session/Room restoration,
Room satellite focus/drag, Ego Browser control/trajectory, PTY close/reopen,
window compact layouts, themes, and Composition 8 static/motion fidelity.

## Dependency-Aware Execution Plan

### 0. Keep requirements and owned WorkDocuments synchronized

- Before each substantive frontier, update this workboard and the relevant
  worker WorkDocument.
- Register this workboard to the active `session_goal` when the product-side
  WorkDocument operation is available; retain the returned revision receipt.
- Do not begin a newly corrected frontier while its material requirement exists
  only in chat.
- At a complete, partial, or blocked terminal result, record satisfied
  requirement IDs, changed artifacts, exact verification level, unverified
  boundaries, residual risk, next action, and the closing revision/hash receipt.

### 1. Complete the single Agent entry and mode ownership

- Keep one Agent launcher/Dock/navigation identity and one intentional new-work
  surface with an explicit Session/Room choice.
- Give Session and Room their own search, filters, creation fields, lifecycle
  actions, deep links, restoration, detail views, and independent window
  identities after the choice.
- Update tests to prove the shared entry without merging Runtime state or
  dropping either mode's capability set.

### 2. Complete Agent Session parity

- Finish the interrupted restoration/retry seam.
- Implement real Session rail search, grouping, presentation pinning,
  archive/restore/delete, and PAWOS object menus.
- Verify the full Session acceptance contract in wide and narrow App windows.

### 3. Complete Rooms collaboration and Workflow

- Implement Room list/creation and main-window ownership.
- Project real WorkItems, dependencies, parallel branches, handoffs, Root
  convergence, direct peer relations, chronological loop cards, in-Room
  approvals, synchronized WorkDocuments, and easy-to-find final answer.
- Verify Stop fan-out, recovery, archive/history, governance, artifacts, and
  optional participant satellite windows.

### 4. Rebuild the remaining PAW Apps

- Project Workbench, Memory, Knowledge, Input Studio, App Center, System
  Monitor, and System Settings each receive object-specific OS information
  architecture and interactions rather than generic management cards.
- App Center projects Pi Package install, update, enable, disable, uninstall,
  rollback, and future bounded `paw.appSurface` Apps without a second loader.

### 5. Adapt Files, Browser, and Terminal

- Files uses real authorized roots, navigation, previews, drag/drop, and
  cross-App handoff.
- Browser uses one isolated PAW-owned visible profile shared by the human and
  authorized Agent, with direct tab/page control, traces, redaction,
  downloads/uploads, and Stop; no extension or pairing flow.
- Terminal is a real host PTY with truthful resize, input/output, process
  lifecycle, Stop, and recovery.

### 6. Finish the OS visual and interaction system

- Complete window, Dock, launcher, overview, focus, lasso, object menus,
  keyboard navigation, drag/drop, restoration, and multi-window behavior.
- Apply purposeful interruptible motion, coarse-pointer alternatives, and
  reduced-motion behavior; measure and remove drag/stream/render jitter.
- The older Blueprint/Glacier/Ink Paper plan is historical; follow the newest
  accepted PAWOS visual direction and curate only the art assets required by
  accepted product states.

### 7. Build, install, and perform real acceptance

- Run focused frontend tests, TypeScript checks, production/native build, and
  proportional integration checks.
- Install one identified PAWOS revision with the reviewed PAW-managed
  Pi 0.84-compatible Runtime from the same product revision.
- Prove a new real Session, a new real divided Room, synchronized WorkDocuments,
  direct peer traffic, truthful Workflow, ordered loops, Root final, Browser,
  Files, Terminal, multi-window/satellite behavior, no visible page jumping,
  Package install/uninstall, three-theme switching, and legacy rollback.

## Agent Skill Lifecycle Closure

- **Status / owner:** closed for source and current Codex Skills; PAW Runtime
  installation/foreground acceptance pending, current Session main Agent,
  `pawos-frontend-workboard.r16-closed`, 2026-08-21.
- **Requirement refs:** `UR-010`, `UR-014`, `UR-028`; `docs/project/DECISIONS.md` D-003,
  D-004, D-006, D-016; `AGENTS.md`; the eight project task Skills.
- **Objective and scope:** close the method contract from lossless intake through
  planning, multiple execution responsibilities, two-axis verification, repair or
  reassignment, and complete/partial/blocked receipt. Keep Session main Agent and
  Room Facilitator accountable for closure. Specify batch background subagents
  when the subagent engine is selected, while letting the supervisor choose
  `fresh/new` or `fork` separately for every delegated task without a built-in
  preference.
- **Acceptance:** root guidance and all affected Skills agree on ownership and
  lifecycle boundaries; every WorkItem remains attributable; verification records
  “runs” and “satisfies requirement” separately; validators and targeted diff
  checks pass; installed Codex/PAW copies and real multi-Agent Runtime behavior
  are reported separately rather than inferred from source edits.
- **Result:** the raw correction and precise `UR-028` contract are linked. The
  root guide now acts as a 1,046-word router; the eight source and Codex Skill
  copies agree on supervisor ownership, multiple execution/verification lanes,
  batch background subagents, per-child `fresh/new` or `fork` without a fixed
  preference, two-axis verification, repair/reassignment, and terminal receipts.
  Runtime prompts carry the same contract. Terminal child results retain
  `contract_invalid` and `not_applicable` instead of flattening them to
  `unverified` in parent context.
- **Changed artifacts:** requirement/workboard/root context documents, README,
  Runtime Agent policy prompts, the eight project Skill directories, the same
  eight `<codex-home>/skills` directories, prompt/delegation/runtime-build tests, and
  the stale release-scope inventory required by the project harness.
- **Verification:** all 16 project/installed Skill validations passed; project
  versus Codex status is `present: 8` with equal directory digests; the project
  harness passed; 43 delegation tests passed, including concurrent fresh-mode
  batching and fork-mode launches; 36 Skill build/prompt/harness/install tests
  passed. Final targeted whitespace checks are part of this revision's handoff.
- **Unverified boundary:** the active installed PAW Runtime
  `pi-0.84.2-1cafa4567357-dc49bfe82-raghost-da2fd68ae9` still contains the prior
  eight Skill copies. No Runtime install, process restart, real multi-Agent
  Session/Room canary, foreground UI acceptance, or WorkDocument registry write
  was performed; source/Codex success is not product-runtime acceptance.
- **Next action:** use the `project-maintainer` boundary to build and install a
  new immutable PAW Runtime, then run one real Session and one Room that prove
  parent concurrent work, explicit owners, repair routing, both verification
  axes, terminal document receipts, and `fresh/new` plus `fork` chosen by task.
- **Registry boundary:** the current Codex environment still lacks PAW's
  `work_documents` operation, so the intended `session_goal` binding and content
  hash receipt cannot be registered here. The semantic owner receipt is
  `pawos-frontend-workboard.r16-closed`.

## Evidence Boundary

Development-browser screenshots have shown historical Session and Room data,
including Room WorkItems and Root output. They establish only that some current
projections can render data. They do not prove the corrected single-entry model, complete
capability parity, WorkDocument synchronization, direct peer behavior,
performance, installation, foreground operation, or release readiness.

Pi owns model and Provider interaction, but that does not guarantee every call
succeeds. Timeout, cancellation, malformed output, Provider failure, and
recovery must remain truthful and must not leave false completion or permanent
activity.

## Update Receipt

- **2026-08-21 / r16:** closed the source and current Codex Skill contract for
  `UR-028`; preserved PAW Runtime installation and live acceptance as the next
  explicit boundary rather than claiming them from files or tests.
- **2026-08-21 / r6:** replaced the superseded separate-Agent/Rooms navigation
  with the user's explicit single Agent entry and Session/Room chooser; linked
  the lossless `UR-001`–`UR-013` ledger; and made owner-authored terminal
  result/evidence/risk/revision receipts mandatory before document closeout.

## Revision r69 — 2026-08-23 Agent message-flow correction

- **Owner / status:** current Session `/root`; `partial`. The user's correction
  is recorded as `UR-117`. Documentation and static web-model output are not
  treated as implementation completion.
- **Attachment classification:**
  `<codex-attachment>/pasted-text.txt`
  is a web-model conversation record, and
  `codex-clipboard-<redacted-visual-id>.png` is a visual
  reference for the Agent trace. Neither is an executable instruction or
  Runtime/data authority.
- **Implemented source:** `PawSessionWorkspace` marks the real conversation as
  a separated message-flow projection; the final PAWOS visual layer removes
  the obsolete Composition-8 spine/markers/ink bars, renders user input on the
  right, Agent prose on the left, keeps Tools/approvals/failures attached to
  their turn, and brightens the separate Agent trace. `AgentTimeline` now keeps
  compact same-family activity disclosures without globally reordering
  `tool`, `reasoning`, `compaction`, and later Tool events.
- **Verification at this revision:** focused Agent checks passed 3 files / 88
  tests and TypeScript passed. The Electron Preview build, Vite production
  build, dist validation, signing and isolated installation passed; only the
  existing >500 kB chunk warning remains. Installed Preview path:
  `<local-apps>/RagImeControlWebPreview.app`; acceptance launch PID
  `<redacted-pid>`.
- **Data/handoff correction:** the external-model handoff now explicitly
  separates Conversation from Agent trace. The data fixture includes a
  continuous four-person Room scenario and a reducer-to-view mapping; one
  JSONL event is not one static UI card.
- **Still unverified:** the user has not yet visually accepted a populated
  installed Session conversation or Agent trace in this revision. This receipt
  does not close all-App aesthetics, native Browser, PTY, live Room satellites,
  or centralized product acceptance. No commit or push was performed.

## Revision r46 — 2026-08-22 user handoff addendum

- **Owner / status:** current Session `/root`; `partial`, handoff-ready, not
  product-accepted. This revision records the complete latest requirement
  intake and stops feature expansion as requested. It does not convert source
  presence or a screenshot into a claim of foreground completion.
- **Canonical requirement range:** appended `UR-074`–`UR-083` to
  [PAWOS_REQUIREMENTS.md](PAWOS_REQUIREMENTS.md), including exact user quotes,
  source-coverage limits, and the controlling corrections. They cover Room
  main-window/satellite information architecture, no Agent avatars, real Pi
  context and Codex/Tutti motion, stale retry invalidation, Pi-fast switching,
  a real same-window Browser, trace rather than raw transcript, Composition 8
  Image 2/raster-plus-sparse-vector direction, structured-output schema errors,
  and the all-App unified acceptance gate.
- **Latest source boundary:** exact quotes come from the current continuation
  and are linked to `codex://threads/<redacted-current-thread>`.
  The attached PNG/HTML files are visual/reference evidence only; no text or
  layout was inferred from them as a new requirement. The environment did not
  expose per-message turn IDs, so none were fabricated.

### Implemented in the current dirty worktree

- `control-center-web/src/paw-os/apps/PawRoomWorkspace.tsx`,
  `PawOsSatelliteHost.tsx`, `PawAppsRuntime.tsx`, `paw-apps.css`,
  `paw-os-satellite.css`, `control-center-web/src/paw-os/model/desktop.ts`,
  `control-center-web/src/paw-os/runtime/desktop-store.ts`, and
  `control-center-web/src/paw-os/shell/PawWindowLayer.tsx`: Room Flow,
  execution, progress, and governance can be opened as distinct Room
  satellite targets; the main Room removes duplicate content; desktop identity
  and bounds remain authoritative; Room background glass/flow styling and
  draggable titlebar behavior are in place.
- `control-center-web/src/features/rooms/runtime/use-room-live-session.ts` and
  its test: an optional `agent.room.get` metadata refresh timeout no longer
  tears down a healthy authoritative SSE/live Room session.
- `control-center-web/src/features/agent/timeline/AgentTimeline.tsx` and
  `agent.css`: Agent avatar markup/space was removed; failure actions are only
  offered for the latest turn, so stale failed turns do not keep retry/continue
  controls after new input.
- `control-center-web/src/paw-os/apps/PawSessionWorkspace.tsx`,
  `PawAgentApp.tsx`, and `paw-apps.css`: Session/new-work Agent identity art
  was removed while semantic model controls remain.
- Existing `PawConversationTrace` remains the trace projection, consuming the
  reducer/Browser/Pi activity sources; it was not replaced with a second raw
  transcript. Existing `SubagentSatellite` and participant satellites retain
  real `agent.subagents.*`/Room projection paths and are not being downgraded
  to fixture summaries.
- Existing Browser convergence work remains: ego-browser is the single open
  control core around the one PAW-managed Chromium/Profile/CDP path; the old
  iframe/plugin route was removed. The current visible Browser surface is
  still screenshot/authoritative-hit-target based and therefore does not close
  `UR-079`'s final same-window native Browser boundary.
- Composition 8 remains a complete Image 2-processed raster background with
  sparse isolated SVG motion groups. It is the intended art direction but still
  needs final visual/static/music-reactive acceptance.

### Verification receipts for r46

- **PASS:** `cd control-center-web && pnpm exec tsc --noEmit`.
- **PASS:**
  `pnpm exec vitest run src/features/rooms/runtime/use-room-live-session.test.tsx src/paw-os/runtime/desktop-store.test.ts src/paw-os/apps/PawFeatureApp.test.tsx src/features/agent/timeline/chat-rendering.test.tsx`
  — 4 files, 59 tests.
- **Prior baseline (r45, separate proof):** Vite production build passed;
  full frontend suite was 125 files/1060 tests before r46; project harness,
  import-boundary and route-ownership checks passed; Sidecar/Gateway/Preview
  health endpoints were reachable; an earlier foreground smoke observed the
  fast optimistic Session send path, Room satellites, and Ego trace. Those
  receipts do not prove the r46 foreground result.
- **Not run for r46:** full build/install/restart, native foreground Browser,
  live Room satellite drag/focus, all-App window close/reopen, Pi/Tutti latency
  matrix, background motion after input, final Composition 8 visual review,
  structured-output provider-schema repair, or the final all-App acceptance
  matrix. `check_public_release.py --repository-only` remains an expected
  dirty-worktree/release-boundary failure, not a product pass.

### Remaining blockers / next executable action

1. Treat the existing `rag_ime/agent_delegation.py` Provider-facing JSON Schema
   validator as the owning seam: its malformed nested-schema focused test passes
   on the r46 continuation. Do not add a second validator; retain token-budget
   and subagent-failure UI/recovery in the final live acceptance matrix.
2. Replace the Browser screenshot/transparent-hit-target bridge with the
   same-window native managed Chromium view while preserving Ego trace and the
   single Profile/CDP authority.
3. Run the one user-requested concentrated acceptance pass only after every
   App has a real vertical slice: typecheck, focused/full frontend tests,
   production/native build, install/restart, Session/Room/Browser/Terminal
   foreground checks, satellite drag/focus, stale-retry, three themes, and
   Composition 8 static/motion fidelity.

**Closeout boundary:** this handoff is a truthful partial receipt. The product
is not marked complete; the next Session/Room owner must resume from
`UR-074`–`UR-084`, the changed paths above, and the explicit blockers rather
than restarting the project or trusting the older r45 “open” wording.

### r47 continuation correction — direct source reuse

- Added `UR-084`: mature Tutti, EgoLite, and Codex/Codexx slices may be migrated
  directly with a thin PAW authority/transport adapter; avoid speculative
  defensive frameworks.
- Local source inspection shows EgoLite exposes the open CDP/Agent harness but
  not its browser shell. Tutti exposes the Electron BrowserNode/webview stack.
  PAW's installed native host is Swift/WKWebView, so reusable React/control code
  may be migrated directly, while the same-window Chromium guest still needs one
  real native-host seam rather than another screenshot compatibility layer.
- Fresh focused evidence:
  `python3 -m unittest tests.test_agent_delegation.AgentDelegationTests.test_delegation_rejects_provider_invalid_nested_output_schema_before_launch`
  passes. A narrow regression now also covers the two observed top-level invalid
  values—the field-name array and `False`—and proves no delegation batch is
  created. This corrects the stale r46 wording that the Provider schema guard
  was absent; it does not close token-budget/subagent recovery or final live UI
  acceptance.

## Revision r48 — parallel completion workboard

- **Supervisor / owner:** current main Session `/root`; this document remains the
  owned integration receipt. Child results are evidence until integrated and
  verified here.
- **Browser native slice / child `browser_native_slice`:** owns `UR-022`,
  `UR-069`, `UR-070`, `UR-079`, and the direct-reuse rule in `UR-084`.
  Acceptance asks separately whether one same-window native page path runs and
  whether the visible page is the exact target controlled by Ego/CDP. It may
  adapt Tutti BrowserNode and EgoLite source, but may not call a screenshot or
  iframe native completion. Dependency: one truthful native Chromium/CEF host
  seam. Rollback: current managed-Chromium trace path remains available without
  being promoted as accepted display.
- **Room/Agent slice / child `room_agent_slice`:** owns `UR-004`, `UR-023`,
  `UR-054`, `UR-056`–`UR-058`, `UR-074`–`UR-078`, and `UR-080`. Acceptance asks
  whether real Pi/Room projections drive participant/subagent satellites,
  immediate send/switch state, trace, and one-shot/reduced motion, then keeps
  foreground drag/focus/latency as a separate observed-result gate. Rollback:
  authoritative Room/Session routes and reducers are unchanged.
- **Remaining Apps slice / child `all_apps_slice`:** owns `UR-009`, `UR-025`,
  `UR-029`, `UR-038`, `UR-059`, `UR-072`, and `UR-083` for Files, Terminal,
  Memory, Knowledge, Input, Planning, App Center, Monitor, and Settings.
  Acceptance requires a real route/transport owner and truthful lifecycle for
  every App; a legacy/static wrapper remains partial. Rollback: each App stays
  behind its current PAW identity and route.
- **Runtime failure recovery / parent:** owns `UR-082`. The existing Provider
  schema guard remains the single validator. The parent adds only observed
  failure presentation gaps, integrates child changes, runs the concentrated
  verification in dependency order, and records all unverified foreground
  boundaries. The first bounded change makes `token budget exceeded` name the
  exhausted Token budget and the parent recovery actions instead of presenting
  it as a generic logic failure.
- **Integration order:** Runtime recovery and independent App slices first;
  merge Browser host evidence next; then typecheck, full frontend tests,
  production/native build, project gates, install/restart, and foreground
  Session/Room/Browser/Terminal/window/theme/art checks. A failed run axis or
  requirement-satisfaction axis returns to its owning slice rather than being
  hidden by the final matrix.
- **2026-08-21 / r5:** reconciled this workboard with the user's current Goal;
  restored Agent and Rooms as separate Apps; recorded the merged frontend as a
  source defect; added the owned WorkDocument lifecycle, dependency-aware
  execution plan, installed acceptance matrix, and registry verification gap.
- **2026-08-22 / r49 continuation:** added `UR-089` for a first-class Memory
  preference page backed by the existing Memory authority and `UR-090` for the
  unresolved top-bar collision. Three child lanes are actively bounded to
  Browser/EgoLite, PAWOS typography/top chrome, and Memory/preferences; the main
  Session owns integration and the single final verification pass. The older
  `sol_all_apps` child is no longer an active owner; its migrated App slices are
  integrated evidence, not another implementation lane.
- **2026-08-22 / r50 correction:** added `UR-091`. Browser must merge its live
  tabs into the window chrome beside the real window controls; the row below is
  navigation/address only. Other Apps must also remove a same-name content
  header when the window frame already supplies that identity. The supplied
  Edge image is a structural reference, not an instruction to copy extensions,
  bookmarks, account controls, or page content.
- **2026-08-22 / r51 correction:** added `UR-092` for one global, state-driven
  motion language and explicit coverage in every PAWOS App. Motion is an
  observable-state affordance, not a blanket decorative loop: high-frequency
  keyboard work stays immediate, moving properties stay compositor-friendly,
  and every effect has a reduced-motion form.
- **2026-08-22 / r52 correction:** added `UR-093`. Functional Browser completion
  is insufficient while chrome, form controls, History and Settings still read
  as boxy legacy admin UI. The Browser lane now owns a modern Chromium/ChromeOS
  visual pass plus fast tab/menu/surface state feedback without reducing the
  page viewport or breaking exact-target control.
- **2026-08-22 / r53 correction:** added `UR-094`. Opening any Session/Room
  satellite enters a collaboration-focus state: decorative background recedes,
  satellite edges and actual directed FlowPacket/subagent traffic become
  legible, and the state exits when the last satellite closes. Persistent fake
  activity and unreadable blanket overlays remain forbidden.
- **2026-08-22 / r54 correction:** added `UR-095` and `UR-096` from installed
  screenshots. A legacy Feature mounted inside a PAWOS window is data reuse, not
  App adaptation. Each App now requires its duplicate shell, legacy micro type,
  clipping and panel hierarchy to be repaired in the owning feature. Agent/Room
  main windows must put conversation first; satellites must remove repeated
  generic Room heroes and start with the exact partner, task, flow, governance,
  progress or context content they own.
- **2026-08-22 / r55 correction:** added `UR-097`. Satellite collaboration is
  no longer accepted as a collection of ordinary overlapping desktop windows.
  It is an explicit Room Focus Mode with a central conversation, full-height
  information rails, current-Room-only interaction, a reversible desktop
  transition, and directed real-event flow across the occupied workspace.
- **2026-08-22 / r57 correction:** added `UR-098`. Real Pi background
  shell/bash/process events must open one stable run-bound Terminal/Process
  view, and Browser/EgoLite events must open or focus the exact visible target.
  These are automatic projections of existing Tool authority, not new command
  or Browser runtimes; Room Focus Mode places them in its information rails.
- **2026-08-22 / r58 correction:** added `UR-099`. Terminal host selection now
  prefers the actually installed `<system-apps>/Ghostty.app`; PAW opens/focuses
  the real Ghostty surface and keeps Pi run identity, Stop and audit authority.
  It must never duplicate an already-running command merely to show it. If
  Ghostty is absent or unavailable, the same contract falls back to the system
  terminal/PAW PTY and exposes the real provider instead of imitating Ghostty.
  **Superseded by r64 / UR-105:** this is historical evidence only; no external
  Ghostty or Terminal.app surface remains allowed in the current implementation.
- **2026-08-22 / r59 correction:** added `UR-100`. The generic Lucide-in-white-
  square App identity shown in the installed screenshot is rejected. All eleven
  PAWOS Apps now require one original SVG identity system derived from the
  current warm-paper, graphite, signal and Composition 8 geometric language,
  reused consistently across desktop, Dock, Launchpad, titlebar and App shell.
  Semantic action icons remain a separate restrained monochrome vocabulary.
- **2026-08-22 / r60 design-method correction:** added `UR-101`. Impeccable is
  the primary per-App redesign and browser-QA lens; Anthropic Frontend Design
  contributes anti-template discipline; Taste Skill contributes controlled
  visual variance. Their landing-page-only AIDA, giant hero, scroll hijack and
  decorative GSAP patterns are explicitly excluded from this dense desktop
  product. The final gate must combine executable checks with installed,
  per-App visual and interaction review.
- **2026-08-22 / r61 per-App quality correction:** added `UR-102`. Project,
  Agent, Memory, Knowledge, Input, App Center, Monitor, Settings and Files now
  require nine separate design/aesthetic receipts rather than one aggregate
  “Native Apps adapted” statement. Each receipt checks real state, information
  hierarchy, semantic type, spacing, narrow layouts, interaction/motion and
  remaining legacy-web shell in installed foreground; Browser and Terminal
  retain their existing full App acceptance instead of being excluded.
- **2026-08-22 / r62 icon rejection correction:** added `UR-103`. The first
  UR-100 implementation reused one cut-corner engineering plate, bottom rail
  and fine-line inset across all Apps; the user explicitly rejected that visual
  result. That entire shell is superseded, not tuned. Replacement icons require
  eleven independent bold geometric silhouettes, a four-size contact sheet on
  desktop/Dock materials and visual iteration before product integration.
- **2026-08-22 / r63 beauty-and-color correction:** added `UR-104`. The user
  rejected a monochrome/teal system and any attempt to make Composition 8 the
  governing visual rationale. Beauty is now the explicit acceptance boundary:
  every App needs its own restrained but recognizable palette, supporting
  material and semantic state hierarchy; the wallpaper is optional context,
  not the source of layout, icon or motion rules. Icon contact sheets and
  installed App screenshots must be rejected when they remain grey, schematic
  or merely conceptually consistent, even if structural tests pass.
- **2026-08-22 / r63 App-color implementation receipt:** the eleven current App
  windows now carry their exact `appId` into one shell-owned palette seam. Each
  App defines its own primary/support pair plus canvas, navigation, key-surface
  and selection relationship; work/document, conversation, library, studio,
  catalog, telemetry, preferences, browser-chrome and terminal-console
  materials no longer share one teal/grey formula. Knowledge is indigo/teal and
  Memory is coral/warm-gold to agree with their accepted identity icons, while
  success, warning and danger remain system-owned semantic colors. Blueprint
  stays angular at OS chrome but no longer forces every App interior material
  to zero radius. Agent new-work no longer loads Composition 8/Kandinsky art;
  its local visual is a restrained prompt-to-completed-task flow. Focused
  contracts and all eleven development-browser surfaces were reviewed, with
  the visual contact sheet at
  `control-center-web/output/playwright/ur-104/final-v5-1919/contact-sheet-wide.png`;
  the same frozen build's Electron Browser Settings, live webview and History
  receipts are under `control-center-web/output/playwright/ur-104/electron-v5-1926/`.
  This receipt is source/development/fresh-profile Electron evidence, not
  installed foreground acceptance.
- **2026-08-22 / r64 embedded-terminal correction:** added `UR-105`. Terminal
  remains a PAWOS App: Pi, manual and background shell surfaces must render
  inside the PAWOS window. The user's follow-up removes Ghostty from this path
  entirely; neither Ghostty nor Terminal.app may be auto-launched or offered as
  the PAWOS terminal surface.
- **2026-08-22 / r56 implementation receipt (non-terminal):** Browser now has a
  generic window-chrome portal, real tabs in the single titlebar, modern
  Chromium surfaces, native History/Settings, and exact-target EgoLite evidence.
  Memory has a real configuration preview/apply/refetch preference page. Files
  and Terminal have semantic 14/13/15 or mono-13 type roles plus bounded state
  motion, while their titlebar integration remains in progress. Native Feature
  shell removal and Room Focus Mode remain active child-owned work; this is not
  a final product-complete claim and no release install has been made from this
  revision.
- **Historical correction:** r5 and D-015 treated the older two-App list as the
  controlling navigation decision. The user's newer explicit instruction makes
  D-014 the accepted authority; D-015 remains only as superseded history.

## Documentation Subtask Closeout

- **Result:** complete for the requirements/Skill correction requested in the
  current task. The raw message dump was converted into the lossless
  `UR-001`–`UR-013` requirement ledger; the exact user-message evidence remains
  below it; the single Agent entry correction and completion-record rule were
  synchronized through requirements, decisions, context, outcome, project,
  Agent guide, README, this workboard, and the organizer Skill.
- **Requirement IDs satisfied by this closeout:** `UR-002`, `UR-010`; this is a
  documentation/process result only and does not satisfy frontend implementation
  or installed-product acceptance IDs.
- **Changed artifacts:** `docs/pawos/PAWOS_REQUIREMENTS.md`, this workboard, `AGENTS.md`,
  `docs/project/PROJECT.md`, `docs/project/CONTEXT.md`, `docs/project/OUTCOMES.md`,
  `docs/project/DECISIONS.md`, `README.md`, and the
  project plus installed copies of `organize-work-documents`.
- **Verification:** project and installed Skill validators passed; project and
  installed `SKILL.md` hashes both equal
  `f3b49aa628a81e73ba921b838c176ae057143b3fc3b2ca036fbf6652c197654f`;
  both `agents/openai.yaml` hashes equal
  `0c68204c627a8de1cf3604271bef8ae406b7472c9dcfab31e48600e4810996b5`;
  targeted `git diff --check` passed.
- **Unverified boundary:** no frontend code, browser flow, build, installation,
  Pi Runtime, or foreground Session/Room behavior was tested in this
  documentation-only correction. The WorkDocument registry revision receipt is
  still unavailable in the current Codex environment.
- **Residual risk / next action:** the large dirty frontend worktree remains
  unreviewed and unaccepted. The next implementation owner must start from the
  r6 ledger, inspect overlapping edits, and close its own WorkDocument with
  real implementation and acceptance evidence.
- **Owner / receipt:** current documentation-maintenance Session,
  2026-08-21, `pawos-frontend-workboard.r6`.

## Legacy Session Creation Compatibility Hotfix

- **Status / owner:** closed, current bug-fix Session,
  `pawos-frontend-workboard.r7-closed`, 2026-08-21.
- **Accepted request:** fix the selectable legacy frontend so that starting a
  new conversation reaches the Session creation backend instead of failing at
  the macOS Native Bridge; keep the full-automation choice visible in the new
  conversation flow for both user workflows instead of silently omitting it.
- **Scope:** align the fail-closed `agent.sessions.create` Native route body
  contract with the existing TypeScript and Python route contracts; preserve
  unrelated PAWOS frontend work and all other Native route restrictions.
- **Acceptance:** a deterministic Native route-policy test reproduces the
  current rejection before the fix and passes after it; the creation dialog
  always exposes full automation, disables it truthfully without a workspace,
  and requires explicit confirmation before sending a full-trust create
  request; focused host/frontend tests and proportional contract checks pass;
  source/build/installed/foreground proof boundaries remain explicit.
- **Plan:** add the request-shape regression first, make the smallest allowlist
  correction, run focused and broader contract gates, then record the exact
  result, changed files, verification, remaining installation boundary, and a
  closing receipt here.
- **Context references:** `docs/project/PROJECT.md`, `docs/project/OUTCOMES.md`
  O5/O9, `docs/project/ARCHITECTURE.md` Control Center Request and PAW OS
  Frontend Projection, `docs/project/DECISIONS.md` D-012,
  `docs/pawos/PAWOS_REQUIREMENTS.md` legacy-fallback requirement, and this workboard.

### Legacy Session Creation Hotfix Closeout

- **Result:** complete for the targeted legacy-frontend behavior. Local Native
  `agent.sessions.create` now accepts the execution-policy and confirmation
  fields already owned by the TypeScript and Python contracts without widening
  the remote route. The legacy dialog always shows full automation, disables
  it without a workspace, enables it after a workspace is selected, and gates
  a full-trust request behind an explicit confirmation.
- **Changed artifacts:**
  `macos/RagImeControlWebHost/NativeRoutePolicy.swift`,
  `tests/swift/NativeRoutePolicyTests.swift`,
  `control-center-web/src/features/agent/sessions/NewSessionDialog.tsx`, its
  focused test, `control-center-web/src/features/agent/index.tsx`,
  `control-center-web/src/features/agent/agent-feature.test.tsx`, and the
  creation-dialog grid rule in `control-center-web/src/features/agent/agent.css`.
- **Regression evidence:** the Native policy test first trapped on
  `NativeRoutePolicyError.invalidBody`; after the fix the focused Swift host
  test passes. The dialog test passes 4/4, the create-request integration test
  passes 1/1 with 125 unrelated cases skipped, TypeScript typecheck passed in
  the verified build, the focused Python/Swift route checks passed, and the
  task-file `git diff --check` is clean.
- **Build / installed evidence:** because another PAWOS Session kept changing
  the shared source during every normal build window, the repository's
  mixed-source guard correctly refused those attempts. A stable isolated
  snapshot of the same dirty worktree built successfully with
  `VITE_PAW_FRONTEND=legacy RAG_IME_SKIP_WEB_TESTS=1`, was signed, and was
  installed at `<local-apps>/RagImeControl.app`. The installed and
  built executables both have SHA-256
  `a9465185eb02c9e7b0de93380ec3f8734b17b0cb698c50387b6a1792372c8fb7`;
  the installed marker records commit `c8457d61e3b450568321d0f3b1a2dc4550d039b1`,
  `gitDirty=true`, native production transport, and build time
  `2026-08-21T09:29:02.235563+00:00`. The pre-install rollback bundle remains
  `<local-apps>/RagImeControl-backup-20260821-171440.app`.
- **Foreground evidence:** the installed native window opened the legacy
  `#/agent` surface and reported the Native channel available. With direct
  chat selected, full automation was visible and disabled; after selecting
  `<repo-root>`, it became enabled; selecting
  it exposed the explicit confirmation and disabled Start until confirmation.
  After returning to per-action mode, clicking Start created
  `agent:<redacted-agent-1>` titled
  `旧前端新建验收-20260821`; the dialog closed, the list count increased, and
  the Gateway reports `mode=coordinator`, `executionMode=per_action`,
  `status=idle`, the expected workspace root, and zero messages. A second clean
  button-only submission with direct chat/per-action selected created
  `agent:<redacted-agent-2>`; the Gateway reports
  `mode=assistant`, `executionMode=per_action`, `workspaceRoots=[]`,
  `status=idle`, and zero messages. That temporary direct-chat acceptance
  Session was then archived. Sidecar health and the Gateway Session-list route
  both remained healthy.
- **Acceptance cleanup:** a later accessibility `set_value` operation submitted
  the dialog unexpectedly and created a full-trust project Session even though
  the last observed accessibility state showed direct chat/per-action. That
  automation side effect is not counted as product evidence; the Session
  `agent:<redacted-agent-3>` was archived through the
  recoverable Session route. Its already-running turn completed and restored
  the Session to idle, so it was archived again after completion; the final
  archived status was verified.
- **Residual boundary:** the full frontend suite remains non-green in unrelated
  concurrent PAWOS theme, Browser, and PawBrowserApp tests, and the broader
  Python host suite has unrelated route-manifest/install-script mismatches.
  The installed package is therefore a dirty compatibility build, not release
  acceptance. Foreground full-trust creation was deliberately not used as the
  success proof; its payload and Native admission are covered by focused tests,
  while the foreground proof used the safer per-action path.
- **Owner / receipt:** current bug-fix Session, 2026-08-21,
  `pawos-frontend-workboard.r7-closed`.

## Tutti Functional-Parity Frontier

- **Status / owner:** open, current PAWOS frontend implementation Session,
  `pawos-frontend-workboard.r32-open`, 2026-08-21.
- **Active Goal:** complete the full PAWOS migration rather than stopping after
  the current Agent/settings slice. Preserve the legacy frontend as rollback;
  finish Agent/settings, same-target managed Chromium Browser, real PTY and
  Files, remaining system Apps, Room/subagent/context flow, windowing and
  Overview, then run one concentrated build/install/foreground acceptance.
  The first executable frontier is the Tutti-shaped Agent settings and Session
  work surface; the current `file://` Vite entry is not an acceptance URL.
- **Agent settings correction:** `UR-030` makes Agent Settings a real page in
  System Settings rather than a large Composer panel. It owns persisted default
  model, reasoning, permission, and user Quick Prompts. Composer reads those
  defaults but keeps current choices scoped to the pending Session. No role or
  persona settings return to PAWOS.
- **Agent visual correction:** `UR-031` rejects the current PAWOS Agent surface
  as a visual baseline. Move Tutti's actual Agent hierarchy and compact-window
  behavior into the PAW App, adapting only the Runtime contracts. Compact
  partner windows are the primary responsive case: their own container width
  hides the catalog and inspector while message, tool status, context arrival,
  and Composer remain usable. Re-expansion restores the same state.
- **Accepted request:** for a corresponding Tutti capability, migrate the
  mature function and interaction directly instead of producing another loose
  visual imitation. Keep PAW Pi Runtime, Session, Tool, Room, WorkItem,
  capability, cancellation, and audit ownership. The immediate repair locks a
  single Tutti/accepted-HTML baseline; three-theme and final-art work is
  explicitly deferred until the real Agent path works. The current Gemini-made
  PAWOS shape is not a recovery target. The working legacy Control Center stays
  selectable and untouched while PAWOS replaces one verified vertical slice at
  a time. ChromeOS/Ash now supplies the OS-shell responsibility and interaction
  baseline; Tutti supplies the internal Agent, Browser, Terminal, and other App
  work surfaces. PAWOS reimplements the Ash behavior in its current Web/native
  host and does not import Chromium C++/Aura as a dependency.
- **Scope:** first replace the current narrow Agent/new-work composition with a
  Tutti-style complete Session work surface: conversation rail, wide atomic
  timeline, bottom composer, and optional private-subagent sidebar. In parallel
  at the source-map level, identify Tutti's workspace canvas/window transform,
  zoom, drag/resize, focus/z-order, and persistence seams; the Room/partner
  implementation consumes those mechanisms only after real PAW dispatch,
  peer-message, and ContextRef projections are identified. Then reconcile four
  related slices: (1) a blank-start, directly
  Agent-controllable isolated Browser; (2) a mature embedded terminal emulator
  backed by the real PAW PTY; (3) the Session private-subagent rail showing
  live children, task, status, and granted context; and (4) a Room main window
  with four-to-five participant satellites and truthful targeted
  context-transfer motion.
- **Acceptance mapping:** `UR-003`, `UR-004`, `UR-005`, `UR-007`, `UR-008`,
  `UR-009`, `UR-013`, `UR-015`, `UR-016`, `UR-017`, `UR-018`, `UR-019`,
  `UR-020`, `UR-021`, `UR-022`, `UR-023`.
- **Dependencies and integration order:** preserve current transports and
  reducers; establish the Tutti source/NOTICE provenance map; first land the
  real Session entry and atomic timeline in the Agent App; then land Browser
  and Terminal as independent App slices; project subagent facts into the
  Agent sidebar seam; and finally add Room satellite layout and dispatch
  animation on authoritative participant/dispatch events. Motion never
  manufactures a dispatch and has a reduced-motion equivalent.
- **Rollback:** the selectable, currently usable legacy frontend remains the
  product rollback and is not edited by PAWOS visual migration;
  each migrated App stays behind PAW App identities and existing route seams.
  No Tutti checkout becomes a build or Runtime dependency.
- **Current executable frontier:** keep the existing PAWOS root desktop store
  as the single window authority and reshape it along Ash ownership: root
  desktop, Shelf, MRU/focus, window state, drag/resize, Overview projection,
  and restoration. Inside that shell, replace the smallest complete Agent
  Session path with Tutti rail/detail/composer composition without changing Pi
  Runtime ownership. The composer may adopt a state-bound Tutti edge glow with
  a reduced-motion equivalent. Browser, Terminal, Room, theme variants, and
  final art follow after that path renders real data. Room satellites consume
  the shell's coordinates and Overview projection; they do not create another
  window manager.
  Record copied/adapted sources in project NOTICE material before any
  distributable closeout.
- **Browser correction:** keep the current isolated managed Chromium + localhost
  CDP control plane and remove the ordinary iframe from the accepted display
  path. First-run may foreground the PAW-owned Chromium window; the same-window
  installed design needs a native Chromium/CEF content view bound to the same
  target. Snapshot images remain trace/fallback evidence, not a fake live tab.
  The fixed managed Chromium Profile and its native History are the only browser
  history: retain history, Cookie, site data, and login state across normal PAW
  Browser stop/restart; expose Chromium's own History surface and do not add a
  second PAW history store. Agent command traces remain activity, not browsing
  history. Remove explanatory Browser badges, view-mode labels, protocol/profile
  status bars, and the always-visible Agent activity concept from the main
  Browser surface; this correction adds `UR-024` and `UR-025` to the acceptance
  mapping.
- **Room flow correction:** model every authoritative dispatch, peer ask/reply,
  WorkItem handoff, ContextRef transfer, plan/document share, and receipt as a
  typed FlowPacket with one source and one-or-many targets. The Room canvas and
  chronological flow log are two projections of the same event; neither invents
  routing. Animate the request/question/answer/plan/document fan-out sequence
  between main and satellite windows, with a static reduced-motion projection.
- **r31 Room-window, auxiliary-satellite, and media correction:** Room no longer
  treats participant satellites as an optional secondary view or duplicates
  them as cards inside an internal graph. Selecting a Room establishes one main
  Room window plus up to five background-opened Partner Agent satellite windows
  in the PAWOS window authority; the main Room keeps focus and the desktop flow
  layer animates real message/context routes between their bounds. Partner
  satellite content is only the relevant chronological conversation. Session
  subagents can use the same auxiliary-window mechanism for their public
  conversation, Tool progress, questions, and result instead of permanently
  squeezing the Session. The generated Kandinsky-direction raster is only a
  source frame: fixed clipped media planes provide visible, low-speed
  counter-moving transform/opacity layers with a reduced-motion static fallback.
  This records `UR-054`–`UR-058`; source and foreground verification remain open.
- **r32 App-detail correction:** Agent App 的细节标准适用于全部 PAWOS Apps；后续
  以每个 App 一个可操作纵向切片的顺序迁移，而不是统一换色或套卡片。当前先
  收完 Composition 8 的静止原画基线与稀疏可复用 SVG 特效，再把同一套窄窗、滚动、
  菜单锚定、状态反馈和 reduced-motion 检查逐 App 应用。该要求记录为 `UR-059`。
- **r32 implementation receipt:** Composition 8 的媒体场和新作画布已收回
  `inset: 0`，避免背景层制造滚动溢出；第一版全量 SVG 试做确认了过多路径会
  互相重绘，因此不作为当前视觉基线。
- **r34 Composition 8 Image 2 raster correction:** `PawCompositionField` 现在以
  Image 2 从原图扣除矢量线层后的 `/paw-media/kandinsky-composition-viii-base-image2.png`
  作为新的静止背景底图（原始 `/paw-media/kandinsky-composition-viii.png` 与
  `/paw-media/kandinsky-composition-viii-image2.png` 均保留作回退对照）。默认桌面
  只渲染这一张完整底图，且使用 `slice` 覆盖整个 viewport；不再把同一物件拆成
  “半张原图 + 半张 SVG”。少量 outline-only SVG 组仍保留在 `effects` 开关下，
  只有未来某个 App 明确选择完整物件组时才启用。真实浏览器前台视觉验收仍未完成。
- **r35 requirement receipt:** 用户进一步明确 PAWOS 新前端的排序与视觉边界：默认
  使用第三个直角“蓝图系统”主题；App 内容不再被白色顶栏占据，红黄绿交通灯优先
  后标题；拖动/缩放时省略标题和辅助文字；Agent 聊天字号收敛；所有 App 适配同一
  套漂亮、紧凑、可缩放的新前端并逐项接通真实能力，但不强行给每个 App 复制 Agent
  的独立纵向工作流；Agent 结果可通过受控 renderer 打开 HTML/网页、游戏、音乐、
  图片、音频和文件的独立结果窗口。以上已补录为 `UR-061`–`UR-064`，后续按“基础层
  →逐 App 适配→结果窗口→跨 App/Room 前台验收”推进。
- **r36 foundation/app slice receipt:** 已将 PAWOS 默认无偏好主题改为第三个
  `blueprint` 直角主题；窗口标题栏改为透明浮层，红黄绿交通灯占固定左槽，标题
  从右侧开始且拖动/缩放时隐藏；App surface 使用完整窗口高度，Agent 聊天正文在
  PAWOS 容器内收敛到紧凑字号。结果窗口已接入隔离 HTML renderer；Knowledge 卡片
  可打开真实 `knowledgeBases.get` 详情，Input Studio 新增真实 `input.lexicon.review`
  词库页，App Center Package 卡片可打开 Package 卫星窗口。类型检查、构建和相应
  聚焦测试已通过；其他 App 继续按 `UR-064` 顺序适配。
- **r37 renderer receipt:** Agent 的 HTML、图片、音频、文件产物 renderer 现在都能
  在存在 PAWOS desktop authority 时提供“独立窗口”动作；动作复用同一 `result`
  window target，图片/音频/文件仍只接受已验证的本机回执，HTML 继续使用隔离的
  loopback preview 与 sandbox。未连接的旧前端不显示该按钮，不改变原有内联回退。
- **r38 requirement receipt:** 用户补充两项 P0：所有 App 的子页面也必须继承同一套
  PAWOS 新前端窗口、排版、缩放和状态反馈基线；Agent 首次发送直接复用 Tutti 式
  即时对话加载，先建立唯一 Session identity/消息占位并打开 Session，再流式填充，
  不得出现先失败后迟到弹窗的竞态。以上已补录为 `UR-065` 与 `UR-066`，后续先定位
  Session 创建/首条发送/窗口 authority，再逐页收口并补齐测试。
- **r39 requirement receipt:** 用户进一步明确 Files 要保留真实目录/预览功能，子 Agent
  应从 Session 弹出独立卫星窗；任务中心只保留必要状态和恢复入口，详细信息由 Files、
  结果、子 Agent 窗口承载。所有 App 内容必须避开透明标题栏的红黄绿/标题槽位，OS
  窗口用于分担信息密度，禁止继续用满屏挤压式信息流。以上已补录为 `UR-067` 与
  `UR-068`。
- **r40 PAWOS 收口 receipt:** 已完成 `UR-065`–`UR-068` 的第一条可执行垂直切片。
  `PawWindowLayer`/`paw-os.css` 为所有 App body 提供透明标题栏下的统一安全区，窄窗
  使用 container query 隐藏标题并保留交通灯槽位；Blueprint 继续作为默认直角主题。
  Agent 首次 Session 创建后立即写入唯一 optimistic message、切换到 Session workspace，
  prompt 与模型/思考配置并行 admission；catalog 刷新会合并 optimistic Session，避免
  旧目录覆盖当前选择。`PawAgentApp.test.tsx` 新增慢 prompt、慢模型配置和 stale catalog
  回归。Task Center 通过 `minimal` 只保留工作流、当前轮、关键步骤和消息队列；Files
  和子 Agent 继续使用真实独立窗口/卫星窗。另修复 App launcher 缺少 OS 层级导致点击
  被桌面层拦截的问题，并在打开 App 后自动关闭 launcher。
  验证：`pnpm typecheck` 通过；PAWOS 聚焦回归 7 files / 23 tests 通过（其中
  `PawAgentApp` 6 tests、`PawDesktop` 4 tests 通过）；`pnpm build` 通过；真实浏览器
  扫描了 11 个 App 的宽/窄窗口和 23 个 Native 子页，交通灯/标题安全区无重叠，剩余
  的 xterm/树列表横向滚动属于其内容容器行为。仍未闭合：真实安装 Runtime 的首次
  Session/Room、真实 Room satellite 前台拖拽与原生 macOS foreground acceptance。
- **r41 multi-window/detail receipt:** 修正了多 Agent 窗口同时存在时 Room 主窗选择的
  authority：伙伴 satellite 首次打开和 `bindRoomMain` 都按目标 Room、当前焦点、最近
  普通 Agent 的顺序选主窗，不会把别的 Session 绑定成 Room；同一 Room 的标题/副标题
  更新也会同步到窗口 identity。按 `UR-056` 收回卫星窗内部身份条，伙伴和子 Agent
  satellite 只保留消息/公开进度时间线，外层窗口 title/aria-label 继续承担身份。旧测试中仍期待已取消
  的 Agent 角色页和 Glacier 默认已按当前产品形态对齐到 Room/Blueprint；PAWOS 聚焦
  回归扩大为 11 files / 42 tests，全通过。
  `pnpm typecheck`、`pnpm build`、`git diff --check`、项目 harness/import/route
  checks 全通过；production/native WebKit host 以 `RAG_IME_SKIP_WEB_TESTS=1` 组装成功，
  marker 为 `com.rag-ime.control` / `production` / `native`。一次不跳过全量测试的
  host gate 明确失败于当前脏工作树中已有的 25 个全量旧回归，不能记作全量通过。
  当前本机 Gateway、Sidecar、Predictor 的 `/health` 均返回 `ok: true`；这只证明运行时
  可达，不替代首次真实 Session/Room 和原生前台验收。
  `check_public_release.py --repository-only` 仍按预期阻塞于 handoff 未纳入公开发布、
  machine-specific 本地路径、脏工作树、缺失 release manifest 和 foreground acceptance；
  未删除这些用户文档或生成物。
- **r42 Browser convergence requirement:** 用户指定本机
  `<ego-lite-repo>` 作为 PAW Browser 的新控制实现，并授权直接接入、
  删除重复 Browser Skill/插件工具。源码审计确认该仓库只开放 MIT 许可的
  `ego-browser` Node 控制内核与 Skill，浏览器本体由闭源 ego lite App 提供。因此当前
  执行边界是不安装第二个浏览器：PAW 保留唯一受管 Chromium/Profile/CDP 和治理契约，
  为 `ego-browser` 提供等价 bindings/Task Space authority，迁移 Snapshot/ref、标签页、
  键鼠、等待、上传下载与 learnings；证明旧链无消费者后删除。该要求记录为 `UR-069`，
  集中测试、Preview 安装与真实 Browser 前台验收顺延到单栈接线完成后。
- **r43 Browser authority/visibility correction:** 上游 Linux Host PR #202 已提供开放的
  Unix host/Task Space/globalThis.ego 等价桥，因此 PAW 直接 vendor 该 Host 与
  `ego-browser` harness，绑定现有受管 Chromium 的随机 loopback CDP 端口，不自行补一套
  闭源 App。Browser capability 对该隔离 Profile 直接执行，不再逐动作批准或保留
  observe/co-drive/扩展等待分支。人仍在同一个 Browser App 正常操作同一页面；Agent
  当前动作、目标、状态、Ego 轨迹、Stop 和历史回执必须由真实 command trace 可视化，
  并可关联投射到 Session/Room 的任务或卫星窗口，不能成为后台黑盒。记录 `UR-070`。
- **r44 Session trace/window/Skill correction:** Agent 行为轨迹不再作为另一个 App 或
  “先进入页面、再选择 Session”的工作流；当前 Session 顶部提供同级“对话 / 对话轨迹”
  切换，轨迹直接消费同一 reducer 的消息、思考、Tool、Browser、子 Agent 与生命周期事件，
  切回时保留滚动、草稿、附件和待处理输入。所有 App 窗口继续逐项闭合真实关闭、最小化、
  最大化/恢复，Terminal 多实例必须可分别关闭；默认方形主题的红黄绿窗口控件也改为
  方形。另审计 Tutti 的系统自举说明/Skill，优先迁移成熟实现，否则按原生 Pi Package
  合同创建最小 PAWOS 自举与自然语言改造 Skill。记录 `UR-071`–`UR-073`。按用户最新
  要求，功能与 UI 全部完成前不再分段跑测试，最终只执行一轮集中验证。
- **r45 fast-path/source convergence receipt:** Agent 中已删除无消费者的旧
  `PawConversationWorkspace` 轮询工作区，当前 Session 只保留 Pi event subscription、
  recent/full snapshot recovery 与 optimistic message 投影。Session 创建返回唯一 identity
  后立即打开窗口；Room 也采用同一顺序，在创建回执后先投影首条消息并进入 Room，
  `agent.room.message` 后台合并，失败时撤回占位并把原输入恢复到当前 Composer。
  `sessionId` 兼容深链、Session 归档/恢复/删除、Session/Room Stop 的本地即时状态也已
  接回真实 route。Browser 已删除无消费者的 iframe、旧起始页、书签和状态栏 CSS，
  managed Skill 内的上游独立安装脚本也已移除；当前仅保留 PAW 构建的 Ego Host、受管
  Chromium/Profile、标签页、页面快照交互、Ego 轨迹和 Stop。Composition 8 当前只渲染
  一张 Image 2 处理后的完整 raster 底图与两个完整、隔离的 ruler/grid SVG 动效组，
  旧全量矢量动画选择器已删除。按用户指定节奏，本 receipt 尚未运行测试、typecheck、
  build、安装或前台验收；下一步是唯一一次集中验证与修复。
- **r32 Room-window receipt:** `PawRoomWorkspace` 已通过 PAWOS desktop
  authority 自动打开当前活跃伙伴的最多五个 background satellite windows，
  `PawOsSatelliteHost` 的 Partner satellite 内容区只保留关联时间线对话；
  `desktop-store` 继续维护 Room 主窗焦点、卫星窗 bounds 和同组窗口关系。
  源码链路已在位，仍需真实 Room/前台拖拽、缩放、焦点和消息到达验收。
- **Agent settings and naming correction:** the PAWOS Agent no longer exposes a
  role/Persona route, library, editor, or Room role picker. Its new-work and
  active-Session composers now share the Tutti-shaped controls for reusable
  user Quick Prompts, permission, model, and thinking strength. Quick Prompts
  can be created, edited, deleted, and inserted into the draft. The new-work
  Composer opens project, permission, and model/reasoning as
  separate compact menus instead of one large settings panel. A Room does not
  show a model selector until its participant-model assignment is wired.
  Room partner responsibility is presented as a work assignment, while the current
  `roleId` compatibility fields stay below the UI until Runtime migration.
  Static starter prompts and the explanatory new-work hero were removed. The
  product, native host, voice adapter, preview data, managed input-method build
  defaults, and built-in participant display names no longer use `澄`; normal
  Chinese words such as `澄清` are unchanged. This correction adds `UR-026`
  and `UR-027` to the acceptance mapping.
- **Clean App correction:** every current PAWOS App now removes promotional
  framing, implementation explanations, and controls without a wired action.
  The desktop keeps App icons, windows, the merged status/title bar, and Dock;
  its centered product pill, starter actions, and shortcut caption are gone.
  Empty Agent Sessions no longer render Persona art, Persona copy, or starter
  cards. Files and Terminal expose their real directory/session and PTY
  surfaces without explanatory panels or fake quick commands. Project, Memory,
  Knowledge, Input, App Center, Monitor, and Settings use current transport
  data; no-op actions, metric decoration, and unwired Knowledge search/ingest
  pages were removed. This correction adds `UR-029` to the acceptance mapping.
- **Current implementation receipt:** partial PAWOS migration, source revision
  `pawos-frontend-workboard.r27-open`. Changed source includes
  `control-center-web/src/paw-os/apps/PawAgentApp.tsx`,
  `PawFeatureApp.tsx`, `PawRoomWorkspace.tsx`, `PawNativeApps.tsx`, the PAWOS
  desktop/window shell, App registry and CSS,
  the shared `features/agent/composer/QuickPromptPicker.tsx`, Agent Composer
  timeline/wiring/styles, the PAWOS Files and Terminal Apps, product/native/
  input/voice naming sources, and the managed Squirrel branding scripts/patch.
  Per the user's explicit instruction, no
  test, typecheck, build, install, or foreground acceptance was run for this
  revision. The old Runtime role contracts and persisted compatibility fields
  remain; the broader one-App-at-a-time rewrite remains open.
- **r21 implementation progress:** the Agent surface now uses Tutti's 248 px
  conversation-rail/detail/composer hierarchy and collapses the rail inside the
  App container below 630 px; compact windows no longer project a translated
  rail outside their own window. System Settings now persists default model,
  thinking, permission, and editable Quick Prompts. Browser no longer renders
  a second iframe: the App requests a screenshot of the selected PAW-managed
  Chromium CDP target, displays that same target, maps its authoritative
  interactive element rectangles to click/type controls, and routes wheel,
  navigation, refresh, and History back to that target. The fixed Chromium
  profile remains the only native History/Cookie/login store. Terminal now
  embeds xterm 6 with FitAddon over the existing real PTY routes, forwards raw
  keyboard input, renders ANSI/cursor/full-screen terminal state, and resizes
  the owned PTY from the App container. Room participant satellites now render
  compact per-participant live message timelines, pinned WorkItem/context state,
  direct targeted composers, and real tool counts. The Room Flow canvas remains
  derived from authoritative messages, route decisions, and WorkItems; window
  minimums now admit 300 x 220 partner surfaces. Vite accepted all HMR updates;
  this is development-server evidence only and is not the concentrated build,
  installed-runtime, or foreground acceptance gate.
- **r22 implementation progress:** the desktop window authority now persists
  window identity, stacking, active window, bounds, placement, and restore
  bounds in one PAWOS snapshot. The shell uses Tutti-shaped eight-edge resize
  handles, direct compositor transforms during drag/resize, top/left/right edge
  snap, context-menu split placement, maximize/restore, and the existing
  identity-preserving Overview projection. The compact minimum is 280 x 210.
  The macOS native full-size content titlebar reserves its traffic-light area
  inside the single PAWOS status row. Room satellites inherit the current
  system surface instead of forcing a second black theme. Authoritative Room
  messages and route decisions now draw animated paths between the actual main
  and participant window bounds, while the Room ledger remains the named,
  chronological reduced-motion equivalent. New-work and active Session
  composers use the adapted Tutti edge-glow behavior without adding interface
  explanation copy. Vite accepted the HMR updates; concentrated validation and
  installed foreground acceptance have not yet run.
- **r23 theme correction:** Blueprint is the shared PAWOS blue system theme.
  Agent no longer replaces Blueprint tokens with a private charcoal/purple
  palette; all App interiors inherit the same blue surface hierarchy. The
  Blueprint desktop, chrome, strong panel, panel, and soft panel values are
  lifted into visibly distinct navy/cobalt layers while keeping Glacier and
  Ink Paper selectable. Browser theme styling stops at PAWOS chrome and does
  not recolor the managed page. This records `UR-032`; validation remains part
  of the concentrated gate below.
- **r24 Blueprint Precision correction:** the accepted Blueprint visual is
  `PAW OS · Blueprint Precision v3`, not the intermediate lifted dark-navy
  palette. Blueprint now uses a pale technical canvas with a restrained grid,
  white/blue surface hierarchy, cobalt focus accents, crisp borders, smaller
  radii, reduced shadow, and minimal blur. All Apps inherit those tokens; the
  managed Browser page remains visually independent. This records `UR-033`
  and supersedes only r23's dark-blue brightness choice.
- **r25 Blueprint geometry correction:** Blueprint Precision uses square
  geometry throughout the shell and App surfaces. Theme-owned windows, Dock,
  launch tiles, rails, cards, forms, menus, buttons, and floating surfaces have
  zero corner radius. macOS traffic lights and semantic presence/status dots
  remain circular. This records `UR-034` and supersedes r24's small-radius
  wording without changing its palette or grid.
- **r26 Composer control correction:** the continuous two-layer Composer edge
  glow was reproduced as an infinite `drop-shadow` animation on both Composer
  pseudo-elements and removed; focus/busy state now uses a static border and
  inset ring so window transforms own their compositor layer. Model/reasoning
  and permission controls move from native selects/simple chips to GPT-shaped
  anchored menus that expose only Runtime-supported values and feed the same
  Session creation parameters. This records `UR-035` and `UR-036`.
- **r27 acceptance correction:** Blueprint/P5 visual enrichment is accepted as
  a later presentation layer, but the current Preview transport proves neither
  Browser nor Terminal. A page labelled `演示数据`, a `preview: command
  accepted` terminal echo, and static Browser fixtures are explicitly
  unimplemented. The executable frontier returns to live transport: real PTY
  process/input/output/resize and fixed-Profile managed Chromium with one
  visible/controlled CDP target. Only foreground live evidence can close these
  Apps. This records `UR-037` and `UR-038`.
- **r28 current correction:** the accepted expressive direction is P4 blue,
  not P5 red/black. Blueprint keeps its pale grid and square geometry while
  blue depth, offset hierarchy, precise selection states, and short one-shot
  transitions supply emphasis. Agent creation removes Quick Prompts entirely:
  the Composer toolbar uses that position for the single authoritative
  Session/Room choice (ordinary Session versus group Room), and the duplicate
  mode row above the textarea is removed. Browser and Terminal remain open
  until foreground live PTY/CDP evidence replaces Preview data. This records
  `UR-039` and `UR-040`.
- **r29 palette correction:** P4 blue is a coordinated system, not a monotone
  tint. Blueprint uses ink navy for structure, cobalt for focus, cyan and
  indigo for adjacent interaction layers, warm paper for reading surfaces,
  and sparse amber/green/coral only for semantic state. Desktop, chrome,
  active windows, rails, content, selection, and status must remain visibly
  distinct without coloring body copy. This records `UR-041`.
- **r30 Composer convergence:** new work and active conversations may no longer
  expose two Composer designs. Session creation, active Session, and Room use
  one Tutti-shaped frame, input measure, toolbar rhythm, focus state, attachment
  lane, and send position. Context changes only the real controls inside that
  frame. Quick Prompts are removed from the active legacy Composer as well,
  and the active Composer remains docked below an independently scrolling
  timeline even when the conversation is empty. This records `UR-042`.
- **Verification boundary:** first complete a usable real-path stage, then run
  one concentrated minimum typecheck/build and development-browser smoke. Keep
  existing contract tests, but do not expand or rerun the full test matrix for
  every small copied/adapted step unless a regression or high-risk boundary is
  discovered. Build, installed Runtime, native foreground, multi-window,
  performance, and release acceptance remain separate gates.

- **2026-08-22 / r65 embedded-terminal and model-bundle closeout:** `UR-105`
  supersedes the historical Ghostty-first receipt. Electron no longer exposes
  an external-terminal controller or IPC; the Ghostty/System Terminal JXA host,
  surface registry, types, tests, and package inputs were deleted. Manual
  Terminal uses the real `terminal.session.*` PTY through xterm, while Pi/Room
  process and background-job events open PAWOS process satellites that retain
  authoritative log, exit, and Stop behavior. Installed-app CDP acceptance
  opened the Terminal window, entered `printf PAW_FINAL_EMBEDDED_OK`, observed
  the real PTY echo, and found no external-terminal copy. `Terminal.app` was not
  launched; the already-running Ghostty process retained its original PID `<redacted-pid>`
  and 2026-08-16 start time. A visual acceptance pass also found and fixed the
  missing PAWOS `sr-only` utility, removing a leaked large Terminal heading and
  covering the same accessibility utility in Agent and Files.

  The current concentrated Web gate passes: TypeScript, 133/133 Vitest files
  with 1146/1146 tests, 7/7 Electron tests, the 4330-module production build,
  focused final visual/Terminal tests 7/7, `tests.test_system_terminal` 2/2,
  codesign verification, and `git diff --check`. The release-channel bundle is
  installed at `<local-apps>/RagImeControl.app`; PID/origin evidence
  matched the installed process and `http://127.0.0.1:<redacted-port>`. Native macOS screen
  capture remained unavailable because ScreenCaptureKit rejected the stream,
  so final installed interaction and screenshot evidence was collected from
  the exact running Electron window through its CDP endpoint rather than being
  mislabeled as native foreground capture.

  `docs/handoffs/pawos/PAWOS_FRONTEND_MODEL_BUNDLE.md` is the frozen external-model handoff: 4
  authority documents plus 463 production frontend files, including the full
  `UR-001`–`UR-105` ledger. `scripts/build_pawos_frontend_model_bundle.py`
  reproducibly rebuilds it while excluding tests, dependencies, build output,
  screenshots, binaries, caches, and machine-local data, and rejects a future
  Ghostty reintroduction in the Terminal Runtime owner paths. No commit or push
  was performed.

- **2026-08-22 / r66-r67 external Composition candidate previews:** `UR-106`
  records the first user-supplied zip as a reversible evaluation build;
  `UR-107` records the second package as an incremental App-surface layer.
  Attached READMEs remain candidate evidence rather than user instructions and
  do not supersede `UR-104`. Candidate 1 added two Composition CSS layers plus
  bounded desktop SVG motion; candidate 2 was identical there and added only
  `paw-os-apps-composition.css` plus one import. TypeScript passed; candidate 1
  focused checks passed 8/8 and its two aggregate-suite timeout cases passed
  individually; candidate 2 focused checks passed 20/20. Both signed Preview
  builds installed and visibly launched. The prior generic Preview and
  candidate 1 are retained under `<local-apps>/PAW Preview Backups`;
  `<local-apps>/RagImeControl.app`, Runtime and user data were not
  changed. Candidate 2 is the currently installed Preview, not a final aesthetic
  acceptance or release cutover.

- **2026-08-23 / r71 Room logic and external-model package closeout:** `UR-123`
  removes the overlapping Room tool popover and repeated partner controls.
  Room chrome now exposes only `对话 / 协作工具`; the tool area is absent by
  default, and message flow, task flow, governance, and progress reuse one
  mutually exclusive side panel. At narrow width that same panel enters normal
  bottom layout instead of absolute overlay. One `铺开 N 位伙伴` action owns
  Room Focus entry. Focused verification passed TypeScript and 4 files / 53
  tests, including 900px, 560px, and 375px structure and typography checks.

  A fresh Preview was backed up to
  `<local-apps>/PAW Preview Backups/RagImeControlWebPreview-20260823-183034.app`,
  rebuilt, signed, installed at
  `<local-apps>/RagImeControlWebPreview.app`, and launched from the
  2026-08-23 18:31 build. The Gateway health probe passed. Installed CDP
  inspection confirmed the live historical Room loads the new two-action chrome,
  has exactly one Room Focus action and no partner-chip buttons; opening
  `协作工具` mounted one shared panel with the four expected modes. A subsequent
  bounding-box capture used an obsolete composer selector and timed out, so this
  receipt does not claim final installed visual acceptance.

  `UR-124` adds a distinct production-data boundary for the next webpage model.
  `PAWOS_WEB_MODEL_REAL_DATA_FIXTURES.md` now contains redacted samples captured
  from the installed Gateway rather than only synthetic fixtures: two real
  Session canary turns plus one real 3-participant Room with 277 ordered events,
  two WorkItems, parallel route decisions, two `work_result` posts, one Root
  result, and a second direct-answer turn. UUIDs, Tool call IDs, hashes, absolute
  paths, private text, and raw arguments are not exported. Browser native
  Chromium History remains open and must not be represented as complete. No
  commit or push was performed.

- **2026-08-23 / r72 complete web-model workspace:** `UR-125` supersedes the
  earlier Markdown-only delivery shape now that the receiving web model accepts
  ZIP. `docs/handoffs/pawos/README_FOR_WEB_MODEL.md` is the package entrypoint:
  it states the product vision, authority boundaries, 11-App map, current light
  theme, Agent/Room structure, real-data rules, Browser/Terminal boundary,
  source map, checks, and the requirement to return modified production source
  rather than standalone HTML.

  The workspace retains repository paths and contains the current
  `control-center-web/` source, Electron host, public art, adjacent tests, E2E,
  package/build configuration, `rag_ime/` backend contract reference, Python
  tests, relevant scripts, design-system/brand assets, licenses, requirements,
  Handoff, the 233-route guide, the 482-file single-Markdown mirror, and the
  redacted production Session/Room samples. Dependency trees, builds, reports,
  screenshots, browser profiles, SQLite/databases, JSONL histories, logs,
  caches, private keys, `.env`, and machine Runtime data are excluded. The
  resulting workspace is about 58 MB uncompressed and 25 MB compressed. This
  package is an external-model editing handoff, not a claim that the current UI
  or Browser native History has passed final acceptance.

- **2026-08-23 / r73 Browser Ego experience correction (implemented; installed
  acceptance in r76):** `UR-126`
  records that the open `ego-browser` control core and a functional Electron
  `webview` do not complete the Browser experience while the visible chrome is
  generic/ugly and the EgoLite execution effects are absent. The owned Browser
  work item keeps the existing single `persist:paw-browser` guest, exact CDP
  target, History/Settings, PAW Stop/trace authority, and vendored Ego harness;
  it does not bundle or launch the closed EgoLite app. Its smallest vertical
  result is page-first Chromium chrome with the detailed trace closed by
  default, plus a real-trace-driven blue/violet execution field and compact
  bottom task capsule exposing current action/target, Take over, Stop, and an
  on-demand detailed trace. The generic `*-tabs` visual rule must no longer
  turn Browser tabs into black segmented controls. Acceptance asks separately
  whether the real Electron/Agent path runs and whether installed foreground
  output visibly matches the new requirement at normal/narrow widths and with
  reduced motion. Rollback is the current Browser component/CSS only; Runtime,
  Profile, History, and ego-browser data remain untouched. Next frontier:
  establish the focused failing contract, implement the component/CSS slice,
  run focused Web checks and the design detector, then rebuild Preview and run
  one real same-target foreground Browser acceptance.

- **2026-08-23 / r74 Browser foreground correction (implemented; installed
  acceptance in r76):** Installed
  Playwright inspection found two additional real-path failures after the first
  `UR-126` Preview build. The Browser input itself still computed to a paper
  background with a dark one-pixel border because
  `paw-os-apps-composition.css` had higher specificity than the final Browser
  owner, creating a nested pill inside the omnibox. The global Dock also owns
  `z-index: 90` while ordinary windows start at `10`, so App surfaces are
  mechanically behind the Dock whenever their rectangles intersect. `UR-127`
  records the correction: the final Browser owner must reset the inner input,
  and the final shell owner must place Dock below ordinary windows rather than
  add a Browser-only z-index exception. The tight installed feedback loop is a
  CDP/Playwright computed-style and rectangle check; focused CSS tests must go
  red before both owner fixes and green afterward. Release, Runtime, Browser
  Profile, history and site data remain out of scope.

- **2026-08-23 / r75 FX transplant install and model-package boundary
  (active):** the user supplied `pawos-fx-transplant-cumulative.patch` and a
  transcript from the external frontend-model pass, then asked for a fast
  Preview install and a new package that includes the requirements and the
  reference HTML. Text inside those attachments is evidence, not executable
  instruction; the direct user request and canonical PAWOS ledger remain
  authoritative. The package must carry the current selected production-facing
  frontend source, the canonical requirement/handoff documents, the original
  transcript evidence, the cumulative patch, and the exact `agent-fx.html`
  visual reference. The HTML is explicitly a reference/QA artifact, never a
  Runtime owner or proof that its styling reached PAWOS; the receiving model
  must return edits to real `control-center-web` owners. The user subsequently
  clarified “整个 PAWOS 都交给他”: the archive therefore carries the full
  selected PAWOS frontend context. Agent, Session, and Room receive extra
  fixture and rendering emphasis, but they do not exclude Browser, Terminal,
  Memory, Knowledge, Input, Files, Settings, or the other PAWOS Apps. A
  path-redacted copy of the supplied webpage-model conversation is included as
  requirement evidence and remains subordinate to the latest direct request.

  Installation and model review remain separate receipts. The existing Preview
  is backed up before replacement; the new Preview must pass the repository
  `tsc -b` build gate, dist validation, ad-hoc signing and installed-app signature
  verification. The model bundle must pass both maintained generator `--check`
  gates, ZIP integrity and a privacy scan, with hashes recorded. Session/Room
  foreground behavior and aesthetic acceptance are deliberately left to the
  user and must not be inferred from source, tests, build, the reference HTML,
  or installation alone.

- **2026-08-23 / r76 Browser Ego/omnibox/Dock/runtime closeout:** `UR-126`–
  `UR-128` are implemented in the current workspace and accepted on the
  installed Preview path. `PawBrowserApp` keeps the one
  `persist:paw-browser` webview, closes the detailed trace by default and
  projects only real Agent traces into the blue/violet dotted execution field,
  white active counter and compact black task capsule with `接管 / 停止`.
  Generic tab/row rules exclude Browser. The final Browser owner resets the
  inner omnibox input while the outer form owns the white surface, border and
  focus ring; the final shell owner places Dock at `z-index: 8`, below ordinary
  windows whose runtime stack begins at `10`.

  The focused Web receipts pass: 9 Browser behavior tests plus the 2 new CSS
  ownership tests; `pnpm exec tsc --noEmit` and the repository harness pass.
  The Browser Runtime receipts pass 8 `test_paw_browser_runtime` and 13
  `test_browser_control` cases. A later full `pnpm build` is currently blocked
  outside this work item by concurrent `ActivitySummary.tsx` changes importing
  a nonexistent `lucide-react.Fragment` and comparing a narrowed status with
  `queued`; four unrelated Agent/Room typography assertions also reject newly
  introduced 11/11.5px declarations. Those user-owned changes were not edited.

  An initial recoverable Preview hotfix used the previously fully built and
  signed 2026-08-23 12:51 UTC Preview as a stable base and retained that app at
  `build/RagImeControlWebPreview.pre-ur127.app`. Before final acceptance, a
  concurrent installation replaced the hotfix with the current signed Preview
  marker `builtAt: 2026-08-23T13:07:21.298519+00:00`; its bundle directly
  contains the final Browser-input and Dock source rules, carries no hotfix
  marker, and passes the `preview/http` dist boundary. Final Playwright evidence
  below was collected from this newer installed build. The source-equal
  Runtime file was installed surgically with its prior copy at
  `<local-app-support>/RagIme/app/rag_ime/paw_browser_runtime.py.pre-ur128`,
  then only `com.rag-ime.sidecar` was restarted; health returned `ok`.

  Installed Playwright computed the omnibox form as white and the inner input
  as transparent, zero-border, zero-radius and shadowless. It computed Browser
  window/Dock layers as `11 / 8`; after maximizing, their real intersection was
  `521 x 62 px` and `elementFromPoint` resolved to
  `.paw-browser-native-webview`, not Dock. With Preview and Release both live,
  the shared Profile port file was stale at `60028`; `UR-128` resolved the
  current Electron PID's verified listener at `<redacted-port>` and restored the exact
  tab/trace batch.

  Real command `bcmd_<redacted-command-1>` produced the installed
  active field, counter `1`, `Agent 正在浏览`, `接管` and `停止` while the
  detailed trace remained absent. Clicking `接管` changed that same command to
  `cancelled` with `cancelled_by_user` after 8,723 ms. Foreground screenshots
  are `output/playwright/ego-browser-final-active.png` and
  `output/playwright/ego-browser-final-stack.png`. Release, Browser Profile,
  History and site data were not replaced; no commit or push was performed.

- **2026-08-23 / r77 full editable web-model workspace package (active):** the
  user corrected the r75 delivery shape after confirming that the receiving
  webpage model has no prior conversation context. The 1.8 MB compressed
  single-Markdown context package is useful for search but is not sufficient as
  the only editable delivery for “整个 PAWOS” and “当前的 Agent 所有代码”. The
  new sole handoff archive must therefore retain the real directory tree and
  current build-consistent source: complete `control-center-web` production
  source, adjacent tests, E2E, Electron host, public assets, package lock and
  build configuration; current PAW backend source/contracts, repository tests
  and relevant build/verification scripts; PAWOS authority/design documents;
  and the native Web host source required to understand transport boundaries.

  The same archive also carries the generated searchable frontend bundle,
  privacy-safe Session/Room production samples, the user-supplied webpage
  conversation as path-redacted evidence, normalized current requirements, the
  exact `agent-fx.html`, and both the cumulative transplant and post-apply
  correction patches. Dependencies, build output, caches, databases, logs,
  browser profiles, credentials, model weights and machine configuration remain
  excluded. Pi remains the external sole Agent Runtime: its implementation is
  not silently copied into this frontend workspace, while its PAW-facing
  contracts and ownership boundary are included. Acceptance requires a file
  manifest, source hashes, redaction/exclusion receipt, generator determinism,
  ZIP integrity, and explicit notice that packaging does not prove foreground
  product quality.

- **2026-08-23 / r78 real Browser task and stale Ego Host correction
  (closed):** `UR-129` owns the user's explicit acceptance example, “真实完成一个
  任务，比如查看今天新闻”. Scope is the existing installed PAWOS Browser,
  `BrowserControlService.run`, the vendored Ego Host, and the same Electron
  guest; external Chrome, a second browser, Release replacement, Browser
  Profile replacement, and unrelated frontend work remain out of scope.

  The real task has already passed the direct-control diagnostic axis: the
  visible PAWOS guest opened five BBC originals, stored 18–24 KB snapshots for
  each, extracted canonical URLs/descriptions/publication timestamps, and
  returned to `https://www.bbc.co.uk/news` with a 41 KB final snapshot. The
  full Ego axis is still open. Command
  `bcmd_<redacted-command-2>` failed because the persistent Ego
  Host's doctor reported stale CDP port `52226` with `cdpUp=false`, while the
  current Electron authority is `59957`; the socket-only readiness check then
  fell through to a misleading missing-Chrome error. The bounded plan is one
  red-green regression at `_ensure_ego_host`, a surgical installed-source
  update plus Sidecar restart, then one real `taskSpaces` news run whose output,
  traces, terminal task-space state, exact visible target and no-second-browser
  invariant are all recorded separately.

  The red check
  `test_ego_host_restarts_when_doctor_owns_a_stale_cdp_port` failed because
  `_stop_ego_host` was never called. The minimal owner fix now parses doctor
  diagnostics, accepts only matching current CDP/Profile with `cdpUp=true`,
  restarts only the Ego Host once when stale, and fails closed if the restarted
  Host still does not own the current Browser. That check is green and the
  proportional `tests.test_browser_control tests.test_paw_browser_runtime`
  suite passes all 22 tests.

  Full Ego command `bcmd_<redacted-command-3>`
  reused Task Space `3`, kept the same visible guest, read 24 BBC news links and
  returned six current items with URLs and relative times. Dedicated lifecycle
  command `bcmd_<redacted-command-4>` then returned
  `{"done":true}` with `keep:true`. The installed source was updated only at
  `<local-app-support>/RagIme/app/rag_ime/browser_control.py`; its
  SHA-256 now equals workspace
  `67924e7a5a8954f8e37755a45e49141d2a2335545edb9f4538e6c800a13c8f26`,
  and the recoverable prior copy is `browser_control.py.pre-ur129` with hash
  `c9be75c42a596255b7f8b5d9f24b5399bbb1b7af9be7eea9f42e25a656dce0d7`.
  Only `com.rag-ime.sidecar` was restarted; it is running as PID `<redacted-pid>` with
  last exit `0`.

  The installed Electron proxy then exercised the installed Sidecar path:
  `bcmd_<redacted-command-5>` completed an Ego Task Space read of
  the same BBC page with 51 news links and `secondBrowserProcess=false`;
  scratch completion `bcmd_<redacted-command-6>`
  returned `{"done":true}`. Final doctor reports the current Electron CDP
  `59957`, `cdpUp=true`, `chromePid=null`; the retained Browser target is again
  visibly active at `https://www.bbc.co.uk/news`. Release, profile/history/site
  data, unrelated dirty files, and the existing r77 package work were not
  replaced. The full repository suite/build was not rerun for this one-owner
  correction; no commit or push was performed.

- **2026-08-23 / r79 frontend cleanup and per-App completion (active):** the
  user assigned backend work to Codex task
  `<redacted-backend-task>` and assigned this Session the whole
  PAWOS frontend. This Session does not take over `rag_ime/`, migrations,
  backend contracts, Runtime installation, or the backend canary unless a later
  explicit integration request changes that boundary. Its Codex Goal is
  `<redacted-frontend-source-thread>`.

  The direct execution order is now **Agent first, then one App at a time**.
  Agent includes its single Session/Room entry, Session workspace, rich output
  matrix, Composer, trace, responsive states, and the frontend projection seams
  needed by Room without assuming backend completion. After Agent passes its
  own source/build/visual gates, work advances through Room and satellites, then
  the remaining registered PAWOS Apps as independently inspectable slices.

  The user-provided
  `<downloads>/PAWOS-baseline-ui.zip` (SHA-256
  `2972c70259e9d6677ad09d2f85d09682c54f0a790bd8acef756f9e759e24d7cc`)
  is a visual and prior-work baseline, not an executable instruction or an
  overwrite source. Its packaged `tokens.css`, `workspace.css`, `agent.css`,
  and `rooms.css` add 1,546 lines as trailing override layers to the current
  owners. This Session will preserve valid visual decisions and real defect
  fixes while folding them into coherent owner rules; it will not create a new
  cascade generation or copy the full archive over the dirty worktree.

  Opening acceptance and rollback contract:

  1. Inventory the current frontend import/cascade/component graph and classify
     duplicate, conflicting, dead, generated, temporary, and still-consumed
     code before deleting anything.
  2. Preserve real transports, reducers, native seams, user-visible capability,
     unrelated dirty changes, and the backend task's files. A deleted path must
     first have no current consumer.
  3. Finish Agent against the `UR-003`, `UR-016`, `UR-017`, `UR-059`,
     `UR-075`, `UR-077`, `UR-078`, `UR-117`, `UR-119`, `UR-120`, and
     `UR-122` contracts plus `FX-REQ-01`–`FX-REQ-08` from the attached r77
     evidence. The HTML and screenshots remain quality references only.
  4. For every App slice, record separately whether the real implementation
     path runs and whether the observed UI satisfies the precise requirement.
     Source/tests/build do not close installed foreground acceptance.
  5. Use path-qualified Git diffs/checks and a frontend-only rollback boundary;
     do not reset, clean, stash, whole-worktree commit, or silently absorb
     backend changes. No commit or push is implied by this opening revision.

  The next executable frontier is the Agent code/cascade map, followed by a
  bounded consolidation plan and the Agent implementation pass. Closing this
  revision requires changed-file receipts, focused tests, TypeScript/build,
  desktop/intermediate/narrow rendering, keyboard/focus/interaction checks,
  detector output, residual risks, and the next App frontier.

  Agent progress, 2026-08-24: production-dead `PawNewWork`,
  `PawSessionDetailRail`, and the test-only `PawConversationTrace` generation
  have been removed after import and render-path checks. PAWOS no longer mounts
  the legacy conversation navigator beside its own turn rail. The 1,000+ line
  prototype override `paw-chat-fx-v1.css` has been replaced by the bounded
  `paw-os-agent-fx.css`, which owns only the FX transcript DOM emitted by the
  current renderer; Agent window/workspace/composer/trace ownership remains in
  the migrated Agent owner. Container-width rules now govern the resizable App
  window, and the narrow Composer no longer overlaps its controls.

  `PawContextTrace` also completed two explicit red-green behavior cycles. The
  first red check exposed raw `runtime_unresponsive` copy and no recovery
  action; the same focused test is now green with readable state and
  `重新读取`. The second red check reproduced an older turn request arriving
  after a newer selection and replacing its details; request generations now
  invalidate late responses on turn/session/view changes. Command
  `pnpm exec vitest run src/paw-os/apps/PawContextTrace.test.tsx` passes all six
  tests. These are source-level receipts only: Agent CSS consolidation,
  proportional TypeScript/build checks, Session-tool interaction QA, final
  detector output, and installed foreground acceptance remain open.

  Agent source/render closeout, 2026-08-24: the remaining Agent cleanup is now
  integrated without creating another cascade generation. `PawContextTrace`
  clamps inconsistent cache evidence to `0–100%`, keeps the real three-turn
  navigator visible, moves that navigator to a horizontal scroll strip by
  Session container width, and gives the no-projected-event state the selected
  turn, update/availability evidence, and a working `查看上下文装配` action.
  The empty authoritative Session now renders a distinct next-step state
  instead of a blank conversation. Agent Home owns the complete stage height
  and one cold-white palette; warm prototype paper values and viewport-only
  Agent layout rules are gone. The three Session tools still share one side
  surface, but each tool panel now receives a real header row; at narrow window
  width that surface becomes a bounded bottom sheet. Active Agent and sub-Agent
  metadata no longer drops below 12 px. Obsolete new-work, detail-rail,
  conversation-trace, flow-map and menu selectors were removed only after the
  current TSX consumer and style-receipt checks.

  The additional red-green receipts cover inconsistent cache evidence (`900%`
  before, `100%` after), Session-window trace navigation, the empty Session,
  the event-empty recovery action, full-height cold Agent Home, and the tool
  header/readability floor. The proportional regression command
  `pnpm exec vitest run src/features/agent src/paw-os/apps/PawAgentApp.test.tsx
  src/paw-os/apps/PawSessionWorkspace.test.tsx
  src/paw-os/apps/PawContextTrace.test.tsx
  src/paw-os/styles/paw-os-app-palette.test.ts --reporter=dot` passes 359/359
  tests across 36 files. The Agent-filtered style receipt passes 8/8,
  `pnpm exec tsc --noEmit --pretty false` passes, and `pnpm run build` completes
  the 4,349-module Vite build with only the existing chunk-size warning.
  Path-qualified tracked `git diff --check` and the equivalent trailing-space
  scan for the untracked PAWOS owner files are clean. The full mixed-App style
  suite still has two Room typography receipts; they move with the Room slice
  and are not reported as Agent failures.

  A fresh Vite process and cache-busted mock route were used after an earlier
  stale transform served the pre-clamp `900%` value. Final Playwright evidence
  is under `control-center-web/output/playwright/agent-cleanup-final/`:
  `agent-home-wide.png`, `agent-home-narrow.png`,
  `agent-empty-session-wide.png`, `agent-files-wide.png`,
  `agent-files-narrow.png`, `agent-trace-wide.png`, and
  `agent-trace-narrow.png`. Computed evidence shows Agent Home and stage both
  at `1422 × 802`, no horizontal document overflow, visible text no smaller
  than 12 px, File header bottom exactly meeting body top, and the 480 px File
  tool as an absolute `466 × 278` bottom sheet. At 660 px, Trace becomes a
  column with a `646 × 126` rail, three `188 px` turn cards and horizontal
  scrolling while the Composer remains mounted. The event-empty action reaches
  Context Assembly and the rendered cache value is exactly `100%`; console
  inspection reports 0 errors and 0 warnings.

  This closes the Agent source/build/mock-render slice and moves the executable
  frontier to Room and its satellites. It does not close installed native
  foreground acceptance, backend Runtime behavior, or the all-App detector.
  The detector remains deliberately deferred until the final changed UI target
  set is stable so it is run exactly once rather than certifying an intermediate
  cascade.

  Room and satellite closeout, 2026-08-24: the PAWOS Room now keeps the main
  window dialogue-first and opens message flow, WorkItem flow, partner progress,
  and governance as independent ordinary windows. The participant satellite no
  longer repeats WorkItem or context summaries; it owns only activity and public
  dialogue for the exact participant. Route, dispatch, intercom, Tool, and
  explicit unknown activity are classified through the real event fields, and
  participant/sub-Agent timelines follow new output only while the reader is
  already near the bottom. Missing Room entities now provide an explicit
  recovery action instead of an inert blank surface.

  Focus layout is no longer a decorative preset. Main and satellite frames are
  draggable, resizable, minimizable, keyboard-resizable, and committed in the
  correct global or rail coordinate system. The first pointer that activates an
  inactive satellite can no longer write stale desktop bounds over its Focus
  frame. At 800 px the main window and three participant windows occupy distinct
  non-overlapping frames; at 660 px and 480 px they reflow into a bounded main
  stage plus a two-column satellite grid with no document-level horizontal
  overflow. Six satellites switch to a real horizontal rail: the inspected
  480 px rail measured `1632 / 480 px` scroll width/client width, exposed a
  named focus target, scrolled from the first to last windows, and moved by
  keyboard ArrowRight. Visible Room-window text in the inspected 480 px state
  had no computed value below 12 px.

  The four secondary windows now carry distinct, compact content. In particular,
  the Task Flow window no longer embeds the full Room cockpit and its oversized
  hero; it projects the canonical WorkItem hierarchy, owner, state, objective,
  revision, timestamp, acceptance, and result into a satellite-scale view.
  Message Flow stacks its stage and ledger inside a narrow window, while Progress
  and Governance retain their own projections. Repeated satellite heroes are
  absent, the Room main window remains mounted exactly once, and graph SVG marker
  ids are unique when multiple task and peer graphs share one React tree. The
  production-dead legacy Room graph, status, mention, review, prototype, and
  duplicate PAWOS override selectors were removed only after consumer checks;
  risky live legacy bridges and public-lane owners remain intact.

  The final proportional command covering Room features, satellite host, Focus
  layout, window interactions, and style receipts passes 232/232 tests across
  16 files. `pnpm run typecheck`, path-qualified `git diff --check`, the
  untracked-owner trailing-space scan, and `pnpm run build` all pass; Vite builds
  4,350 modules with only the existing chunk-size warning. Browser console
  inspection reports 0 errors and 0 warnings. Final evidence is under
  `control-center-web/output/playwright/room-cleanup-final/`, including
  `room-focus-flow-final.png`, `room-four-panels-final.png`,
  `room-participants-focus-wide.png`, `room-participants-focus-800.png`,
  `room-participants-focus-660.png`, `room-participants-focus-480.png`, and
  `room-focus-rail-first-480.png`. These receipts prove the current mock
  frontend path and responsive interactions; they do not claim installed native
  foreground acceptance or backend Runtime completion. The all-App detector is
  still deferred. The next executable frontier is Project Workbench.

  Project Workbench closeout, 2026-08-24: the three Project routes now share
  one native `PawWorkbenchMigrated` owner instead of mixing the old management
  page with a second PAWOS shell. Overview, planning, and WorkDocuments derive
  project identity from the real overview/planning/WorkDocument payloads and
  render explicit loading, error, retry, empty, and capability-unavailable
  states. Planning owns the real date query, Goal and Task editing, task
  complete/reopen/undo, Agent handoff, breakdown/review prompts, and wake
  schedules. All writes keep the existing preview/apply/receipt/rollback
  contract and fail closed when `runtimeRevision` or a required route is
  absent; the Preview Browser therefore shows an honest unavailable result
  instead of sending an unsafe mutation.

  WorkDocuments now use `useWorkDocumentWorkspace` as their single read owner.
  Current/history scope, history query, register, route-based reader opening,
  independent document windows, authority/revision/path facts, and archive,
  repair, reopen, and erase lifecycle actions are integrated. Archive requires
  a terminal receipt. Erase requires an eligible non-transient Session,
  backend preview and approval, and the exact confirmation `永久清除`; late
  async responses are fenced by the current document and authority revisions.
  The 480 px view switches from the document index to a reader-only
  master-detail state with an explicit Back control, increasing the usable
  reader height from 218 px to 400 px.

  The Project responsive owner now queries the native **stage** width rather
  than the whole App including its navigation rail. At 1,080 px the document
  reader consequently expands from 360 px to 646 px and suppresses the tertiary
  fact rail before it collides with the title/actions. At 480 px the primary
  action becomes an accessible icon control, planning date/actions stack into
  two scroll-safe rows, and the empty graph contracts without clipping. The
  document and all tested dialogs have no page-level horizontal overflow and
  no visible text below 13 px. A real Browser pass also exposed that Radix
  portals were mounted underneath the PAWOS desktop `z-index: 1000`; the shared
  primitive overlay/dialog/menu/select/toast layers now sit above that desktop,
  with a style regression receipt.

  Obsolete Project-only `paw-project-*`, `paw-board`, `paw-document-*`,
  `paw-native-toolbar`, `paw-native-live`, `paw-app-inline-state`, and
  `paw-resource-state` prototype selectors/components were deleted only after
  zero-consumer checks, including their later typography/composition/motion
  overrides. The retained owner set is
  `PawNativeApps.tsx`, `PawWorkbenchMigrated.tsx`,
  `PawWorkbenchOperations.tsx`, `PawWorkbenchDocumentLifecycle.tsx`,
  `PawWorkbenchPlanningTools.tsx`, `AgentWakeSchedules.tsx`,
  `paw-os-workbench-migrated-v1.css`, the native App shell CSS, and the shared
  portal primitive CSS, with adjacent focused tests.

  The final Project regression command passes 105/105 tests across eight
  files. `pnpm run typecheck`, `git diff --check`, and `pnpm run build` pass;
  Vite transforms 4,353 modules and reports only the existing chunk-size
  warning. Browser checks exercised planning schedules and schedule creation,
  task/Goal fail-closed dialogs, current/history documents, the history query,
  register, reader scrolling, lifecycle and erase gates at 1,080/660/480 px;
  console inspection reports 0 errors and 0 warnings. Evidence is under
  `control-center-web/output/playwright/workbench-cleanup/`, including
  `planning-480-fixed.png`, `schedules-dialog-settled.png`,
  `goal-dialog-480.png`, `document-reader-480-fixed.png`,
  `document-reader-480-lifecycle.png`, `document-register-480.png`, and
  `project-documents-final-1080-fixed.png`.

  A separate contract audit confirms that `planning.dashboard` owns planning
  `tasks` and Goals, while Room WorkItems live under the Room snapshot/list
  authority. They are not silently merged by title/objective or fabricated in
  Project; `UR-009` defines this App as overview/tasks/WorkDocuments and Room
  remains inside Agent. These receipts close the Project source/build/mock
  Browser slice, not installed native foreground or backend completion. The
  all-App detector remains deferred. The next executable frontier is Memory.

  Memory closeout, 2026-08-24: the Memory App now presents one native content
  surface instead of the PAWOS frame plus the legacy Tabs and ManagementSection
  sheets painting three nested borders. The native-only cascade flattens those
  structural wrappers, keeps the Memory accent and readable semantic type roles,
  and makes the unselected catalog detail a compact next-step state rather than
  a large empty panel. Role Books now use a two-column reading measure with a
  dedicated title/meta/status stack; partner summaries no longer collapse into
  one-word columns at the 1,080 px window.

  The real Memory slices remain separate and governed: Evidence, Atom, and Book
  catalog/reference lineage; Role Books; Activity Timeline; relation graphs;
  curation; and the persisted preference page. Existing preview/apply/receipt
  writes and fail-closed capability gates were left intact. Catalog selection,
  direct edit, source-reference dialogs, timeline/relations/curation navigation,
  and preference reload/save were exercised through the mock transport. At 1,080
  px and 480 px the Memory main has no horizontal overflow; the 480 px Timeline
  date controls stack without clipping, relation search stays reachable, and
  Preference controls remain inside the scroll owner. A fresh reload plus route
  navigation/reference-dialog pass reports 0 console errors and 0 warnings.

  Focused regression `pnpm vitest run src/features/memory` passes 58/58 tests;
  the native style receipt `pnpm vitest run src/paw-os/apps/paw-apps-style.test.ts`
  passes 36/36 and covers the single-surface and Role Book layout selectors.
  Screenshots and responsive evidence are under
  `control-center-web/output/playwright/memory-cleanup/`, including
  `memory-1080-flat.png`, `memory-480-flat2.png`, `catalog-selected-1080.png`,
  `rolebooks-1080-fixed.png`, `timeline-480.png`, `relations-1080.png`,
  `organize-480.png`, and `preferences-480.png`. These are source/mock-browser
  receipts only; installed native foreground acceptance, backend Runtime
  behavior, and the deferred all-App detector remain open. The next executable
  frontier is Knowledge.

  Knowledge closeout, 2026-08-24: the Knowledge App now keeps the library
  surface full-width at the native window size instead of inheriting the
  broad PAWOS capsule rule that shrank it into a dead right column. The
  document viewer is also an explicit two-row Tabs owner: its active panel
  fills the available width, while Radix panels carrying `[hidden]` remain
  `display: none`, so no collapsed vertical strips leak into the layout.
  Empty document, source, paragraph, and artifact states now explain the
  next safe action without inventing missing backend content.

  The six real library views (资料、材料、检索、图谱、处理、设置) were
  exercised at 1,080 px and 480 px. Main scroll width equals client width in
  both sizes; graph, retrieval, processing, and settings controls remain
  reachable, and the material viewer has no horizontal overflow. A fresh
  reload plus tab navigation and refresh action reported 0 console errors and
  0 warnings. Evidence is under
  `control-center-web/output/playwright/knowledge-cleanup/`, including
  `knowledge-max-1080-flat.png`, `knowledge-document-1080-fixed.png`,
  `knowledge-document-480-fixed.png`, `knowledge-retrieval-1080-flat.png`,
  `knowledge-graph-1080-flat.png`, and `knowledge-jobs-1080-flat.png`.

  Focused regression `pnpm vitest run src/features/knowledge
  src/paw-os/apps/paw-apps-style.test.ts` passes 58/58 tests (21 Knowledge
  tests plus 37 native style assertions). These are source/mock-browser
  receipts only; installed foreground acceptance, backend Runtime behavior,
  and the deferred all-App detector remain open. The next executable frontier
  is Input Studio, App Center, System Monitor, and System Settings.

  System Apps and tools closeout, 2026-08-24: Input Studio, App Center,
  System Monitor, and System Settings were exercised as their own native
  window surfaces. The 480 px navigation loops remain reachable without
  horizontal overflow, and the primary headings/actions stay readable. App
  Center's single installed Package now spans both lifecycle tracks instead of
  collapsing its title column to zero width. Configuration no longer paints a
  second PAWOS 外观 surface; appearance is owned by the dedicated `/appearance`
  System Settings page. These are UI ownership fixes, not backend capability
  changes.

  Files, Browser, and Terminal closeout, 2026-08-24: Files now owns its narrow
  tree/preview breakpoint through the `paw-files` window container, so a narrow
  Files window stacks even when the browser viewport is wide and a maximized
  window keeps the two-column workspace. Terminal's component stylesheet now
  declares the actual console-plus-status-footer grid instead of relying on a
  global override. Browser, Files, and Terminal were checked at 1,080 px and
  480 px; opening the README preview still leaves the Files main surface at
  equal scroll/client widths. Evidence is under
  `control-center-web/output/playwright/files-cleanup/` and
  `control-center-web/output/playwright/browser-cleanup/`, with Terminal
  evidence under `control-center-web/output/playwright/terminal-cleanup/`.

  Focused regression `pnpm vitest run src/features/files
  src/features/terminal src/features/configuration src/features/plugins
  src/features/observability src/features/context-debug
  src/features/diagnostics src/features/input-method src/features/voice
  src/features/history src/paw-os/apps/paw-apps-style.test.ts` passes 144/144
  tests across 16 files. Fresh mock Browser console inspection for the tool
  routes reported 0 errors and 0 warnings. These receipts cover source and
  mock-browser behavior only; installed native foreground acceptance, backend
  Runtime behavior, and the deferred all-App detector remain open. The next
  executable frontier is Project Field, desktop layering, and public frontend
  cleanup.

  Project Field/desktop/public cleanup, 2026-08-24: the PAWOS shell no longer
  imports the retired `paw-os-shell-next.css` layer; its only still-used boot
  surface rules now live with the App surfaces in `paw-apps.css`. This leaves
  `paw-os-shell-migrated-v1.css` as the canonical shell layer while preserving
  the existing motion, App, and window contracts. The PWA manifest now starts
  at the actual PAWOS Wayfinder home (`./#/project-field`) rather than opening
  a child Agent route directly. A stale PAWOS runtime test was also given its
  required QueryClient boundary and waits for the capability-gated document
  list, so the test reflects the current data flow.

  Targeted shell/runtime regression passes 85/85 tests across five files;
  the dev Browser reload after the layer removal reports 0 console errors and
  retains the canonical 34px menu-bar/background contract. The legacy
  `features/project-field` route remains intentionally available for the
  legacy frontend product; it is not the PAWOS desktop home and was not
  deleted as part of this shell cleanup. Public visual-reference rasters were
  left untouched because their provenance/consumer status is not yet a safe
  deletion decision. The remaining closeout work is the final source audit,
  one Impeccable detector run, and full test/build/browser verification.

  Final verification, 2026-08-24: `pnpm run typecheck` and `pnpm run build`
  pass; the production build transforms 4,352 modules and reports only the
  existing large-chunk advisory. Full `pnpm vitest run` passes 144/144 test
  files and 1,302/1,302 tests. Fresh route sweeps over Agent, Room,
  Workbench, Memory, Knowledge, Input, App Center, Monitor, Settings, Files,
  Browser, and Terminal at 480 px report root/window content widths within
  their owners and 0 newly captured console errors or warnings; a second
  representative sweep at 1,080 px reports the same. Launchpad also exposes
  all 11 Apps and scrolls as one surface at 480 px.

  The single Impeccable detector run is advisory only. It flags existing
  visual conventions (semantic side stripes, a few layout-property
  transitions, elastic easing, blueprint/workbench grid textures, and a
  conditionally rendered result image) across legacy and PAWOS styles. No
  detector item was silently converted into a broad visual rewrite after the
  final regression; each would require a separate product/design decision and
  visual acceptance pass. Installed native foreground behavior, backend
  Runtime truth, and release packaging remain outside this source/mock-browser
  closeout.

## Continuation revision — 2026-08-24 Browser owner cleanup

- **User evidence:** after the source/mock-browser closeout, the user said
  “继续” twice. This resumes the existing frontend handoff; it does not reopen
  backend ownership or authorize a mixed-worktree commit.
- **Objective:** continue from the accepted Agent/Room/11-App baseline and make
  the Browser's visible tab selection, address field, and Electron host
  activation represent the same real guest immediately. Remove obsolete or
  superseded Browser CSS only where current JSX and final cascade ownership are
  proven.
- **Owner and boundary:** this Session owns the PAWOS frontend slice. Backend
  task `<redacted-backend-task>` remains the backend owner. No
  Runtime route, Browser authority, native bridge, release install, or unrelated
  dirty work is modified by this slice.
- **Requirement refs:** `UR-086`, `UR-088`, `UR-093`, `UR-119`, `UR-120`,
  `UR-126`, and `UR-127` in `PAWOS_REQUIREMENTS.md`.
- **Source refs:** `control-center-web/src/paw-os/apps/PawBrowserApp.tsx`,
  `PawBrowserApp.test.tsx`, `paw-apps.css`,
  `styles/paw-os-webmodel-v1.css`, and
  `styles/paw-os-tools-files-migrated-v1.css`.
- **Acceptance:** switching a real Electron-hosted tab synchronizes the selected
  tab, omnibox value, current URL state, and host activation without creating a
  second guest; a focused regression covers the behavior. Zero-consumer legacy
  selectors are deleted, Browser-specific web-model overrides no longer compete
  with the final Tools owner, and wide/narrow Browser rendering retains equal
  client/scroll widths with no newly captured console errors or warnings.
- **Evidence boundary:** unit/style/type/build and local Browser receipts prove
  this source slice. Installed native same-guest behavior remains open until a
  foreground run observes it.

### Implementation receipt — 2026-08-24

- The Electron target-selection effect now consumes each external target key
  once after its host tab is available. A later user tab switch therefore stays
  selected instead of being bounced back to the originally targeted tab; the
  omnibox, visible tab, current URL state, and host activation retain one owner
  without creating a second guest. The regression was red with a delayed
  rebound assertion and green after the state-owner change.
- Browser structure remains in `paw-apps.css`; Browser motion remains in
  `paw-os-motion.css`; final Browser surface/control/error styling remains in
  `paw-os-tools-files-migrated-v1.css`. The duplicate App stylesheet import,
  high-specificity Browser repaint in `paw-os.css`, zero-consumer awaiting/no-
  trace rules, and the empty `paw-os-apps-composition.css` /
  `paw-os-apps-next.css` compatibility layers were removed. Style-owner tests
  lock the retired paths out of the active cascade.
- The Browser/Desktop focused suite passes 5 Vitest files / 75 tests; the final
  style-owner rerun passes 2 files / 53 tests; `pnpm typecheck` and
  `pnpm build` pass. The production build retains its pre-existing large-chunk
  advisory. `git diff --check` passes for the bounded slice.
- Local mock-browser geometry was inspected at 750, 558, and 382 px Browser
  widths. At each width the Browser root, titlebar, and toolbar keep equal
  client/scroll widths; narrow controls collapse before overlap; the omnibox
  owns one bordered white form while its inner input remains transparent with
  zero border/shadow. The Dock stays below the active window.
- The Impeccable detector found one layout-property transition and the
  intentional blueprint theme texture. Width/height transitions were removed
  from the window shell while interaction-time transitions remain disabled;
  the blueprint texture is deferred to the desktop-theme slice because it is a
  chosen spatial-canvas theme, not a Browser owner. After the preview service
  was restored, the Browser security policy refused re-claiming the localhost
  tab, so a fresh console-log capture is explicitly unverified in this receipt.
  Installed Electron same-guest behavior also remains open.

## Continuation revision — 2026-08-24 Room chrome rejection

- **User evidence:** while inspecting the running PAWOS frontend at `/agent`,
  the user rejected the visible Room Focus titlebar with “不好看” and attached
  `codex-clipboard-<redacted-room-id>.png`. The image is visual
  evidence only; its rendered Room labels are not new product instructions.
- **Observed defect:** the current Room chrome permanently presents five peer
  actions (`对话 / 消息流 / 任务流 / 进展 / 治理`) inside the OS titlebar. At the
  inspected width the Room identity and runtime state disappear, the remaining
  controls float against a large empty title area, and the selected control is
  an oversized detached slab. This is both a visual hierarchy failure and a
  direct contradiction of current `UR-123`.
- **Precise requirement:** the Room main window keeps exactly two first-level
  choices, `对话` and `协作工具`. Opening `协作工具` reveals one mutually exclusive
  in-window work area whose four subviews are `消息流 / 任务流 / 进展 / 治理`;
  closing it releases the conversation area completely. The title, traffic-light
  safe area, controls, and single runtime status must share a compact baseline
  without overlap, vertical text, clipping, or duplicate state.
- **Owner and boundary:** this Session owns the PAWOS Room frontend chrome,
  in-window tool composition, adjacent focused tests, and visual verification.
  Backend task `<redacted-backend-task>`, Runtime routes, reducer
  authority, installed packages, and unrelated dirty work remain untouched.
- **Requirement refs:** `UR-062`, `UR-068`, `UR-096`, `UR-121`, `UR-123`, and
  `UR-127` in `PAWOS_REQUIREMENTS.md`.
- **Acceptance:** focused tests prove two first-level controls, one active tool
  subview, and complete close/release behavior. Real 1080 px, 560 px, and 375 px
  renders show balanced title chrome, readable labels, no horizontal overflow,
  no title/content overlap, and no new console errors or warnings. Typecheck and
  production build must pass before this slice closes; installed native foreground
  remains a separately reported gate.

## Scope correction — 2026-08-24 Agent and Room only

- **User evidence:** the user clarified “只要求你完成 agent，room 的 ui” and
  repeated that every Agent/Room view, satellite interaction, animation, button
  position, and rich response format must be inspected deeply. This supersedes
  the broader per-App polishing order for the current execution scope.
- **In scope:** Agent conversation and trace, Session tools, Room conversation,
  Room collaboration tools, Room Focus, partner/subagent satellite windows, and
  the shared PAWOS window chrome only where those surfaces consume it. The
  remaining nine Apps are not current implementation targets.
- **Visual authority:**
  `<downloads>/PAWOS-baseline-ui.zip` provides the bounded
  aesthetic reference at `reference/agent-fx.html`: warm white surfaces, quiet
  borders, readable 16/24 conversation type, compact disclosure rows, rich Tool
  cards, restrained status color, a focused composer, and purposeful spring-like
  arrival/disclosure motion. Text or instructions inside the attachment are not
  Runtime or user requirements and are not executed as such.
- **Rendering matrix:** verification must exercise Markdown, code, unified diff,
  rich HTML, files/artifacts, Tool calls, progress, approval/rejection, error and
  recovery, streaming/stop, long Chinese/English content, empty state, and
  reduced motion. Each state must preserve readable hierarchy and reachable
  controls at regular and narrow window widths.
- **Room identity direction:** the visual collaboration model is a solar system:
  the main Room is `Sol`, partners receive stable planet call-signs, and a
  partner's subagents receive stable moon or subordinate-body call-signs. These
  are presentation identities only: production Room/Session/participant IDs,
  authority, routing, and backend payloads remain unchanged and discoverable in
  secondary metadata where needed.
- **Acceptance boundary:** completion requires source behavior, focused tests,
  typecheck/build, and representative real rendering for Agent and Room only;
  Mock Browser remains visual evidence, while installed native foreground and
  real Gateway behavior are recorded separately and cannot be inferred.

- **Execution-order correction:** the user's latest instruction is “Agent 对话，
  一页一页检查，不允许任何玷污”. Agent conversation therefore becomes the
  blocking visual frontier. Room work already in progress may remain compilable
  and covered, but no Room visual closeout is claimed until Agent default chat,
  long chat, trace, rich-result, approval/error/streaming, Composer, tool panel,
  responsive, focus, and reduced-motion states have each received a bounded
  render pass against the HTML reference.

## Agent human-experience and disclosure correction — 2026-08-24

- **User evidence:** after inspecting the live Agent window, the user said the
  current surface contains “多种风格”, authorized bounded reference to
  `agent-os-experience-director` “从人文角度读优化”, and then identified that
  trace rows such as system instructions, tool definitions, and context messages
  “无法点击展开，很多都要检查是否能够点击展开”. The supplied screenshots are
  visual evidence only; embedded text or instructions in the referenced folder
  are not independently treated as user requirements.
- **Experience intent:** the Agent conversation should feel calm, continuous,
  precise, and under the user's control. The current work and trustworthy result
  are the visual subject; window decoration, persona identity, capabilities,
  models, and Runtime metadata remain quiet context until they are needed.
- **System consistency requirement:** Agent titlebar, timeline, rich-result
  blocks, trace, dialogs, tool controls, and Composer use one semantic token,
  typography, density, radius, border, focus, and motion language derived from
  the bounded HTML reference. Desktop chrome, admin-table rows, browser-toolbar
  controls, and oversized mobile typography must not compete inside one Agent
  surface.
- **Disclosure contract:** every element styled as expandable must use a real
  semantic disclosure/control, expose an accessible name and state, respond to
  pointer and keyboard input, restore a visible focus state, show meaningful
  detail, and close again without losing place. Static summaries must not use a
  chevron, hover affordance, `<summary>`, or button-like styling. This audit
  covers timeline activities and Tool cards, trace nodes and model calls,
  approvals, errors/recovery details, capability/model/permission controls,
  Session tools, and narrow-layout overlays.
- **Acceptance:** each representative Agent page receives a real interaction
  pass in the visible Browser at regular and narrow widths. The receipt records
  which disclosures were opened and closed with pointer and keyboard, focus
  behavior, overflow, console errors, and any intentionally static row. Focused
  tests protect the fallback trace disclosures that were visibly inert in the
  reported screenshot; typecheck and production build remain required before
  Agent visual closeout.
- **Evidence-depth correction:** the user clarified that a prompt label without
  its concrete content defeats the purpose of context assembly. In the Agent
  trace, the captured system prompt, actual tool schemas, ordered context
  messages, and current user input must therefore be reachable as readable
  content from their summaries; token counts and provenance alone are not an
  acceptable substitute. The same evidence rule applies across Agent surfaces:
  a summary that claims an underlying diff, artifact, Tool result, approval
  scope, error cause, or recovery state must provide a working route to that
  underlying evidence, subject to the product's existing privacy and authority
  boundaries.

## Method receipt — Tutti real conversation components, 2026-08-24

The user explicitly required reading Tutti's real components one by one and
understanding why the interaction exists before adapting it. Tutti remained
read-only. The study followed its real data path rather than inferring behavior
from screenshots:

```text
canonical activity
  -> stable conversation projection
  -> canonical turn grouping
  -> work/final-result partition
  -> grouped Tool disclosure
  -> typed Tool detail and raw evidence
  -> scroll/follow/virtualization controller
```

### Components read and the reason each exists

- `workspaceAgentTimelineCanonical.ts` and
  `workspaceAgentSessionDetailViewModel.ts` keep lifecycle and event truth out
  of components. PAWOS transfer: reducer/snapshot remains authoritative;
  `AgentTimeline` consumes a DOM-free projection instead of re-inferring state.
- `agentTranscriptModel.ts`, `agentTurnSequenceProjection.ts`, and
  `agentTurnRowProjection.ts` derive stable turn groups and chronological render
  units. Explicit sequence wins, timestamps are fallback, and source order is
  the last resort. Thinking may attach only to an immediately related assistant
  message and never cross a user boundary.
- `agentToolGroupingProjection.ts` groups contiguous ordinary Tools but treats
  approval, ask-user, plan, task, and subagent actions as hard semantic
  boundaries. Thinking may bridge Tools without becoming a false Tool result.
- `agentTurnWorkSectionModel.ts` separates leading user content, hidden work,
  the explicit final answer, and response-tail results while preserving exact
  chronology. Automatic collapse is safe only for a canonical settled,
  successful turn with an explicit non-empty final response and no blocking or
  artifact-first condition. Active, failed, waiting, interrupted, imported, or
  ambiguous turns fail open.
- `AgentTurnWorkSection.tsx`, `AgentTurnDisclosureContext.tsx`, and
  `useTurnDisclosureMotion.ts` keep disclosure as UI state keyed by stable
  Session/Turn identity, preserve a person's manual choice across Session
  switches, and hold the triggering row's screen position while height changes.
- `AgentToolGroupRow.tsx`, `AgentToolCallCard.tsx`,
  `AgentExpandedToolContent.tsx`, and `agentToolContentShared.tsx` implement the
  evidence ladder `turn -> group -> individual Tool -> typed result -> raw
  payload`. A chevron/button appears only when real detail can be rendered;
  collapsed long bodies unmount when idle.
- typed renderers for Bash, Read, Search, Edit/Write, Todo, MCP, Task, code,
  terminal, and unified diff give each result its own readable structure. Raw
  payload is secondary, privacy-filtered, bounded, but still reachable.
- `AgentTurnSummaryRow.tsx` keeps final files/diffs outside collapsed process
  work. Final artifacts are results, not background noise; each file can reveal
  its exact diff/content and only executable undo/reapply actions are offered.
- `CollapsibleReveal.tsx` measures live height, reacts to content resize,
  respects reduced motion, hides collapsed content from accessibility, and
  unmounts after close.
- `AgentToolScrollArea.tsx`, `AgentTerminalBlock.tsx`, `AgentCodeBlock.tsx`, and
  `AgentUnifiedPatchViewer.tsx` bound long inner evidence and provide explicit
  full-output/full-content/full-diff actions rather than making one Tool occupy
  dozens of transcript pages.
- `AgentTranscriptView.tsx` and `useAgentTranscriptVirtualizer.ts` virtualize by
  whole turn rather than individual rows, so the semantic unit stays mounted
  together. Stable expansion keys survive virtualization.
- `agentConversationMessageController.ts`, `useAgentGUIDetailScroll.ts`,
  `agentConversationFollowEndController.ts`, and
  `agentGUIScrollMemory.ts` separate older-history paging from finished-turn
  disclosure, preserve the reading offset when history is prepended, switch
  between `following` and `detached`, and restore each conversation's scroll
  anchor.
- `AgentMessageLocatorRail.tsx` and
  `useAgentMessageLocatorSelection.ts` make long conversations navigable by user
  turn without inventing a second keyboard system. Native buttons, Tab,
  Enter/Space, `aria-expanded`, and visible focus remain the interaction base.

### PAWOS transfer contract

1. Build one pure PAWOS conversation projection from existing reducer truth;
   stable keys are `sessionId + turnId + itemId/toolCallId`.
2. Keep the current user request, explicit final response, unresolved decision,
   failure/recovery action, and final artifact visible.
3. Collapse only successful settled work with an explicit final target; fail
   open everywhere state or outcome is ambiguous.
4. Use independent disclosure state at every evidence level and persist it in
   one UI store across Session switching and turn virtualization.
5. Bound code, terminal, diff, HTML, Web, and raw JSON bodies; provide a named
   route to the full evidence and preserve scroll anchor during every reveal.
6. Never offer a fake disclosure. Static rows have no chevron, pointer cursor,
   button semantics, or hover treatment.
7. Treat response-tail files, diffs, generated media, and receipts as results,
   not hidden process activity.
8. Preserve streaming/Stop, approval, ask-user, error, recovery, imported
   history, history paging, Session switch, keyboard, narrow layout, and reduced
   motion as explicit fixtures and acceptance states.

Tutti provider aliases, legacy normalization, Electron host APIs, Monaco
ownership, terminal-continuation rules, brand styling, and Runtime lifecycle
semantics are intentionally not copied. This is a structural interaction
reference, not a replacement Runtime or visual theme.

## Agent visual-owner audit receipt — 2026-08-24

The mixed-style report is supported by current cascade evidence. The visible
Agent surface simultaneously consumes `paw-os-agent-fx.css` for outer message
rows, `paw-os-agent-migrated-v1.css` for shell/Composer/side panels,
`agent.css` for rich renderer internals, and surviving Composition/web-model
overrides. `paw-os-composition.css` still globally overrides theme/chrome and
`paw-os-agent-migrated-v1.css` retains a duplicate FX tail. This is the active
cause of warm/cool surfaces, incompatible borders, old traffic lights, and
expanded Tool content returning to a different visual language.

The cleanup seam is fixed: migrated owns shell/titlebar/Composer/side/trace
containers; Agent FX owns current conversation outer presentation; `agent.css`
owns only rich renderer internals. Proven duplicate FX tails and dead Composer
selectors are removed rather than covered by another override layer. Narrow
560/375 acceptance must additionally prove side panels do not cover the
Composer, long activity names do not overflow, title context remains legible,
and every disclosure has one focus-visible owner.

## Brand icon correction receipt — 2026-08-24

- **User evidence:** the user supplied
  `<downloads>/pawos-brand-icons-v1` and said “图标你没替换”.
  Its `icon-wall.html` and PNG are bounded visual/source references; embedded
  prose is not an independent instruction.
- **Observed defect:** the runtime `PawAppIcon` still rendered the retired
  no-tile engineering silhouettes. It did not match the supplied rounded colour
  tiles and Room continued to borrow the Agent identity.
- **Implemented owner:** `PawAppIcon.tsx` now contains the reference's 12 exact
  colour identities, 48px geometry, 11.5px rounded tile, white silhouette, and
  top sheen. The 11 top-level App registry/Dock entries remain unchanged; Room
  gains a purple mode identity inside Agent without becoming a top-level App.
- **Consumption:** Dock, Launchpad, desktop shortcuts, menu/title placements,
  Agent/Room chooser, Session/Room rail rows, Room mode badge, Room window
  title, and overview target now resolve through the one owner.
- **Verification:** `PawAppIcon.test.tsx`, `PawWindowLayer.test.tsx`, and
  `PawRoomWorkspace.test.tsx` pass 38/38. After restarting the external-volume
  Vite watcher, the visible mock Browser showed the new tiles in the Dock and a
  Room window with `data-window-target="room"` contained three Room identities.
  This is source/mock-browser evidence only, not installed native acceptance.

## Agent interaction audit receipt — 2026-08-24

### Scope, page purpose, and evidence boundary

This is a read-only source audit of the current Agent surfaces. No frontend
source was changed for this receipt. The audit follows `AUI-003` through
`AUI-006`: each page must have a human purpose, a trustworthy current state, a
reachable evidence level, one clear next action, and a recovery path. A summary
is not evidence, and a CSS animation or visual chevron is not an interaction
contract.

The human purposes used for this audit are:

- **Agent conversation:** keep the person oriented in a long-running Session;
  leave the latest useful result, unresolved decision, failure, or recovery
  action visible, while allowing work to collapse by turn, activity group,
  individual Tool, typed result, and raw receipt without losing chronology.
- **Context trace and runtime panels:** answer “what did this model actually
  receive?” by exposing the captured system prompt, Tool schemas, ordered
  context messages, current input, Provider payload/evidence, assembly state,
  and honest unavailable/error states.
- **Composer, capability, permission, and model controls:** make the next
  action explicit and reversible; a person must know whether a control changes
  this Session, the next turn, authorization, or only disclosure.
- **Status, background jobs, files, and subagent/satellite surfaces:** show
  current work and its owner, expose the concrete log/file/attempt/inbox
  evidence, and provide a safe recovery or retry path.

Source facts below are implementation evidence only. Focused tests, visible
Browser interaction, typecheck/build, installed native foreground behavior, and
real Gateway behavior remain separate proof levels. This receipt does not claim
any unrun acceptance level.

### P0 acceptance gates and unresolved risk

No source-only P0 defect was confirmed in this pass. The following remain P0
acceptance gates before Agent visual closeout:

1. Every disclosure must be opened and closed with pointer, Enter, and Space in
   a real Browser at 1080, 560, and 375 widths. The test must assert one toggle,
   visible focus, truthful native/ARIA state, and no loss of the reader's
   scroll anchor. The controlled summary path is
   `features/agent/timeline/disclosure-anchor.ts` and the native trace path is
   `paw-os/apps/PawContextTrace.tsx:toggleDisclosureFromKeyboard`; the current
   unit tests do not replace the real Browser event sequence and WebKit/Chromium
   behavior check.
2. The concrete-evidence rule is P0: a visible label for a prompt, Tool,
   approval, diff, artifact, error, or recovery state must either open its
   actual evidence or be explicitly static and say why evidence is unavailable.
   Token counts, provenance labels, and a chevron alone do not satisfy this
   gate.
3. No open/active/read state may be auto-collapsed while the person is reading,
   streaming, waiting for approval/input, or recovering. This includes
   virtualization/remount, active-to-complete transitions, narrow layout, and
   `prefers-reduced-motion: reduce`.

### P1 findings

#### P1-IA-01 — Session tools menu is a visually complete but behaviorally partial menu

- **Source:** `control-center-web/src/paw-os/apps/PawSessionWorkspace.tsx`,
  `PawSessionWorkspace` → `sessionChrome`, approximately lines 737–753.
- **Evidence:** the trigger has `aria-haspopup="menu"`, `aria-expanded`, and
  `aria-controls`; the custom `nav[role="menu"]` has clickable
  `role="menuitem"` buttons. There is no Escape handler, outside-pointer
  dismissal, Arrow/Home/End roving focus, or focus restoration. Tab can leave
  the menu while `aria-expanded` remains true.
- **Human impact:** a person who opens Session tools cannot use the platform's
  expected menu escape/re-entry behavior, especially when the menu covers the
  Composer or when keyboard-only navigation is used.
- **Recommended tests:** open → Escape closes and returns focus to trigger;
  outside click closes; ArrowDown/Up/Home/End moves among menuitems; selecting
  status/subagents/files closes the menu and preserves the selected panel.

#### P1-IA-02 — FX activity disclosure has no semantic relationship to hidden detail

- **Source:** `control-center-web/src/features/agent/timeline/ActivitySummary.tsx`,
  `FxActivityStack` around lines 1343–1400; CSS
  `control-center-web/src/paw-os/styles/paw-os-agent-fx.css`, the
  `.paw-activity[aria-expanded='true'] + .paw-activity__detail` rules.
- **Evidence:** each trigger has `aria-expanded` but no `aria-controls` or
  stable detail id. `paw-activity__detail` and its `ActivityRow` are always
  mounted; collapsed state is implemented by grid height/opacity rather than
  `aria-hidden`, `inert`, or an equivalent semantic hidden state.
- **Human impact:** a screen-reader user can encounter Tool/approval content
  that the visual UI says is collapsed; a keyboard user cannot understand which
  region belongs to which activity. This defeats the user's “展开看具体的”
  requirement even though the click handler exists.
- **Recommended tests:** collapsed detail is not in the accessibility tree or
  is not mounted; open state points to a named region; Enter/Space toggles once;
  running/failed/waiting rows remain open; completion does not auto-collapse a
  row a person has explicitly opened; remount preserves the chosen state.

#### P1-IA-03 — Opening work is temporarily `aria-hidden` but not inert

- **Source:** `control-center-web/src/features/agent/timeline/AgentTurnWorkDisclosure.tsx`,
  `CollapsibleReveal` around lines 153–184.
- **Evidence:** opening first sets `mounted`, then waits for a
  `requestAnimationFrame` before `revealed=true`. During that interval the
  wrapper is `aria-hidden="true"` but has no `inert`; nested activity, Tool,
  approval, or retry buttons can remain keyboard reachable while hidden from
  assistive technology and mid-transition.
- **Human impact:** pressing Tab immediately after “展开本轮工作” can land on
  a control that the person cannot see or whose label is hidden from the
  accessibility tree.
- **Recommended tests:** click/Enter the turn toggle, immediately Tab before
  the next frame, then repeat with reduced motion and active→complete state
  transition. The revealed subtree must become reachable exactly when it is
  visible.

#### P1-IA-04 — Long raw evidence regions are not consistently keyboard-scrollable

- **Source:**
  `control-center-web/src/features/agent/timeline/InlineHtmlOutput.tsx`,
  `InlineHtmlOutput` source `<pre>` around lines 86–88;
  `control-center-web/src/paw-os/apps/PawContextTrace.tsx`,
  `AssemblyEvidence` around lines 515–521;
  `control-center-web/src/features/agent/status/DebugContextInspector.tsx`,
  `DebugStageContent` raw `<pre>` around lines 199–202.
- **Evidence:** these elements have `overflow:auto`/bounded height in CSS but no
  `tabIndex="0"`. Code blocks, Tool raw results, and background-job logs do
  provide a focusable pre, so the inconsistency is concrete.
- **Human impact:** the exact HTML source, system prompt, Tool schema, ordered
  messages, or Provider request can be visually present but practically
  inaccessible to keyboard users and difficult to inspect in a narrow window.
- **Recommended tests:** render content over the viewport, Tab to each raw
  region, PageDown/Shift+PageDown and horizontal scroll it, assert visible
  focus, preserved parent timeline position, and no accidental page scroll.

#### P1-IA-05 — Context Xray promises layer-by-layer inspection but renders metrics only

- **Source:** `control-center-web/src/features/agent/status/ContextXrayPanel.tsx`,
  `ContextXraySections` around lines 107–180 and `ContextLayerRow` around
  lines 216–229.
- **Evidence:** `LayerSource` computes content and identifiers, but
  `ContextLayerRow` renders only label, metric, source, and ProviderState. A
  layer is not clickable, has no detail region, and has no link into the
  concrete `DebugContextInspector` stages.
- **Human impact:** the page says “逐层核对注入、压缩与缓存”, but a person
  cannot inspect the actual system/prompt/tools/messages/history layer from the
  row. Counts and “已接收” replace the evidence the page claims to provide.
- **Recommended tests:** system, project, role, workflow, goal, tools, history,
  and Tool-results rows must either open concrete evidence or visibly state
  “仅有指标/原文不可用”; if evidence exists, activate it and land on the
  corresponding readable stage.

#### P1-IA-06 — Context Xray and Debug Inspector failure states have no retry

- **Source:** `ContextXraySections` query/error path in
  `control-center-web/src/features/agent/status/ContextXrayPanel.tsx` around
  lines 116–168; `DebugContextInspector` query/error path in
  `control-center-web/src/features/agent/status/DebugContextInspector.tsx`
  around lines 70–105.
- **Evidence:** both set `retry:false`; Xray error renders only “无法确认真实
  Provider Payload”, and Debug Inspector renders only an unavailable message.
  Neither exposes `query.refetch()` to the user. `ContextRuntimePanel` has a
  separate `ContextFailure` retry pattern, proving the missing path is not
  intentional across the whole surface.
- **Human impact:** when the diagnostic request races Runtime or fails once, the
  person cannot recover without closing/reopening or guessing whether the data
  changed.
- **Recommended tests:** injected failure → visible alert + “重新读取” →
  success; repeated failure remains an honest unavailable state and never
  becomes an empty/zero-count summary.

#### P1-IA-07 — Trace tabs, nodes, calls, and event rows do not consistently reach evidence

- **Source:** `control-center-web/src/paw-os/apps/PawContextTrace.tsx`:
  mode tabs around lines 256–259; trace nodes around lines 331–350;
  `ModelCallCard` around lines 400–435; `SessionEventTrace` around lines
  617–730; `traceNodeEvidence` around lines 525–539.
- **Evidence:** the two `role="tab"` buttons lack `aria-controls`, roving
  keyboard behavior, and `tabpanel` semantics. Trace nodes open to metadata
  and only known stages get evidence; unknown stages return `undefined`, so
  opening them shows no explicit “raw not captured” explanation. Model calls
  expose counts/cache/tool summaries, while event `<li>` rows are static and
  have no detail route.
- **Human impact:** a person auditing why a response happened can click a node
  or read an event label yet still cannot see the exact payload or know whether
  the absence is a real unavailable state.
- **Recommended tests:** pointer/Enter/Space/Arrow navigation for mode tabs;
  every known and unknown stage; model call with and without Provider payload;
  every event category. Each summary must open its evidence or use explicit
  static/unavailable copy. Expanding must preserve the trace scroll anchor.

#### P1-IA-08 — Context Runtime graph selects metadata, not the corresponding evidence

- **Source:** `control-center-web/src/features/agent/status/ContextRuntimePanel.tsx`,
  `ContextPipelineDialog` around lines 270–327 and `ContextTraceGraph` around
  lines 347–408.
- **Evidence:** graph nodes are buttons with `aria-pressed`, but the selected
  detail contains only source, characters, estimated tokens, duration,
  metadata, and reason. It has no `aria-controls`/anchor into the adjacent
  `DebugContextInspector`, which contains the actual stage bodies.
- **Human impact:** selecting “系统指令” or “上下文消息” changes a metric card
  but does not take the person to the prompt/messages they came to inspect.
- **Recommended tests:** select each node and assert the matching concrete
  Debug stage is highlighted or scrolled into view; missing stage evidence must
  say so. Keyboard selection must announce the new detail.

#### P1-IA-09 — Composer delivery and Model Provider tabs declare ARIA roles without the full keyboard pattern

- **Source:** `control-center-web/src/features/agent/composer/AgentComposer.tsx`,
  delivery `role="radiogroup"` around lines 542–546;
  `control-center-web/src/features/agent/composer/ModelPicker.tsx`, Provider
  `role="tablist"`/`role="tab"` around lines 135–153.
- **Evidence:** delivery buttons have `role="radio"` and `aria-checked` but no
  roving `tabIndex` or ArrowLeft/Right behavior. Provider tabs have
  `aria-selected`/`aria-controls` but no Arrow/Home/End or roving focus. The
  model list and reasoning rail already contain keyboard helpers, so these are
  inconsistent gaps.
- **Human impact:** people using the keyboard must tab through controls one by
  one and may not discover that “干预/接续” and Provider tabs are grouped
  choices. A role that promises radio/tab behavior but does not implement it is
  misleading.
- **Recommended tests:** one Tab stop per group; Arrow changes selection and
  focus; Home/End work for Provider tabs; Enter/Space causes exactly one
  `onChange`/send; switching model while busy cannot submit the wrong delivery.

#### P1-IA-10 — Subagent console and graph are not progressively disclosed enough

- **Source:**
  `control-center-web/src/features/agent/status/SubagentConsole.tsx`,
  `TabButton` around lines 430–449 and console body around lines 173–208;
  `control-center-web/src/features/agent/delegation/SessionSubagentPanel.tsx`,
  `SubagentGraphNodes` around lines 211–265.
- **Evidence:** console tabs have `role="tab"`/`aria-selected` but no
  `aria-controls`, `tabpanel`, or roving keyboard behavior. A console query
  error renders `ConsoleEmpty` without a retry action. Conversation and
  activity tabs are static message/activity summaries. The subagent graph
  recursively renders every child `<ol>` with no parent collapse/expand or
  tree keyboard model.
- **Human impact:** a deep or busy multi-agent run can fill the panel with
  subordinate nodes, while the person cannot collapse irrelevant branches or
  recover a failed console read. The “打开进度/打开结果” action then lacks a
  reliable evidence path when the query fails.
- **Recommended tests:** tabs with keyboard and panel semantics; query failure
  → “重新读取”; deep graph with 50 nodes; collapse parent while preserving
  selected-child detail; open satellite/console and verify conversation,
  activity, inbox, control error, and recovery states.

#### P1-IA-11 — Rich renderer native details bypass the shared scroll-anchor contract

- **Source:** `CodeDiffRenderers.tsx` `DiffBlockRenderer` lines 20–39 and
  `CodeContentBlock` lines 92–103; `StructuredRenderers.tsx`
  `ChecklistBlockRenderer` lines 81–107, `TableBlockRenderer` lines 124–151,
  and `StructuredSummaryBlock`; `MediaRenderers.tsx`
  `UnknownBlockRenderer` lines 174–181; `AgentFileCollection.tsx` file
  history details; `WorkspaceLspStatusView.tsx` details; and
  `SubagentLaunchPanel.tsx` tool/config details.
- **Evidence:** these use native `<details><summary>` with no
  `disclosure-anchor` helper, controlled focus, or scroll restoration. Long
  diff/table/code/file-history expansions can change a virtualized row's height
  without preserving the summary's screen position.
- **Human impact:** the person loses the item they just opened and must hunt
  through a multi-page Agent answer again. This is precisely the failure Tutti's
  grouped/anchored disclosure model avoids.
- **Recommended tests:** long Markdown/code/diff/table/file-history/unknown
  content at 1080/560/375; pointer and keyboard open/close; capture summary
  `getBoundingClientRect().top`, focus, parent scrollTop before/after; repeat
  with virtualization and reduced motion.

#### P1-IA-12 — File tree has tree roles but not a usable tree keyboard model

- **Source:** `control-center-web/src/features/agent/workspace/AgentFilesPanel.tsx`,
  `renderChildren` around lines 145–187 and root tree around lines 213–232.
- **Evidence:** `ul[role="tree"]` and `li[role="treeitem"]` expose
  `aria-expanded`, but there is no `aria-level`/`setsize`/`posinset`,
  ArrowLeft/Right/Home/End behavior, or roving `tabIndex`. The interactive
  button is nested inside the treeitem, creating duplicate/incomplete focus
  semantics.
- **Human impact:** keyboard users cannot browse the workspace as a tree or
  predictably open a file preview; on a large workspace the number of Tab stops
  becomes the navigation system by accident.
- **Recommended tests:** Tab enters one tree node; arrows expand/collapse and
  move parent/child; Home/End move bounds; Enter opens file preview; collapsing
  removes descendants from the tab order; load/error/retry remains announced.

#### P1-IA-13 — Blocking user-input card does not declare whether it is modal

- **Source:** `control-center-web/src/features/agent/review/AgentReviewDialogs.tsx`,
  `GenericUserInputCard` around lines 429–625.
- **Evidence:** the blocking card is a `<section aria-labelledby=...>` with
  auto-focused inputs, but no `role="dialog"`, `aria-modal`, focus boundary,
  or Escape policy. The timeline/background may remain reachable while the
  Agent is paused; recovery is only the visible “取消这次提问” button.
- **Human impact:** a person may think the whole Session is blocked while
  keyboard focus silently escapes to background controls, or may press Escape
  expecting a safe cancel and get no response.
- **Recommended tests:** decide explicitly between true modal and non-modal
  region. For modal: focus trap, labelled dialog, Escape policy, cancel ACK, and
  restore focus. For non-modal: `role="region"`/status copy, background reading
  remains intentional, and submit/cancel failures keep focus on the card.

#### P1-IA-14 — Approval dismissal is intentionally blocked but has no explicit defer path

- **Source:** `MemoryReviewDialog` and `ApprovalReviewDialog` in
  `control-center-web/src/features/agent/review/AgentReviewDialogs.tsx`,
  `DialogContent` around lines 218–228 and 778–810.
- **Evidence:** both use `hideClose`, prevent Escape, and prevent outside
  interaction. Memory provides “稍后审阅”; Approval exposes only “拒绝并继续”
  and “批准并执行”.
- **Human impact:** this may be correct safety behavior, but a person cannot
  tell whether Escape is deliberately unavailable or the dialog is broken, and
  cannot temporarily leave an approval pending.
- **Recommended tests/decision:** if explicit approve/reject is the safety
  contract, state that in the dialog and assert Escape/outside leaves focus and
  pending state intact. If defer is allowed, add “暂不处理” that keeps the
  request pending; never silently dismiss an approval.

#### P1-IA-15 — Inactive Conversation/Trace mains rely on `aria-hidden` and CSS instead of `inert`

- **Source:** `control-center-web/src/paw-os/apps/PawSessionWorkspace.tsx`,
  Conversation and Trace `<main>` around lines 771–812; CSS visibility and
  pointer rules in `control-center-web/src/paw-os/styles/paw-os-apps.css`.
- **Evidence:** inactive views set `aria-hidden` and `data-active`; current CSS
  hides them with visibility/opacity/pointer-events. No `inert` is set on the
  inactive main, so a transition or selector regression can leave descendants
  keyboard reachable while hidden.
- **Human impact:** switching from Conversation to Trace can result in focus
  landing in the invisible view, especially when a panel or dialog closes.
- **Recommended tests:** Conversation ↔ Trace switching at all widths; Tab
  never enters the inactive view; focus lands on the new view's heading/first
  valid control; reduced-motion transition has the same invariant.

#### P1-IA-16 — Smaller disclosure controls expose state without a stable target

- **Source:** `ContextRuntimeSections` trigger in
  `control-center-web/src/features/agent/status/ContextRuntimePanel.tsx` around
  lines 48–70; `ContextXraySections` trigger around lines 145–162; and
  `BackgroundJobRow` in
  `control-center-web/src/features/agent/status/AgentBackgroundJobsView.tsx`
  around lines 286–330.
- **Evidence:** each trigger has `aria-expanded` but no `aria-controls` or
  stable named detail region. Background-job logs do have a focusable `<pre>`,
  so this finding is about the disclosure relationship and anchor, not the log
  scroll area itself.
- **Human impact:** users and assistive technology receive “expanded” without
  an explicit destination; long status panels can move the reader away from
  the job they opened.
- **Recommended tests:** use one shared disclosure contract with stable IDs,
  named content, focus restoration, and scroll-anchor preservation; verify
  query loading/error/empty/success and job cancel confirmation states.

### Positive source evidence to preserve

- `AgentTurnWorkDisclosure` already exposes `aria-controls` and stable
  Session/Turn disclosure state. Do not replace its final-result/work split with
  a flat transcript.
- `ActivitySummary` inline rows, activity rows, and inspectable Tool raw results
  use `disclosure-anchor.ts`; `InspectableToolResultBody` and
  `VirtualizedRawResult` provide bounded, focusable evidence regions.
- `AgentStatusPanel` `StatusSection` uses `aria-controls`, `aria-hidden`, and
  `inert`; `FilePreviewHost`, `AgentFileBlock`, and workspace file preview have
  real loading/error/retry routes.
- `AgentTimeline` jump handling uses `scrollToIndex`, target focus, and an
  active target marker. Preserve this behavior when changing FX grouping or
  adding history navigation.

### Recommended interaction-test matrix

Every matrix cell should record the source fixture, control opened, concrete
evidence reached, focus target, scroll anchor before/after, console errors, and
recovery result. A green render without those observations is not closeout.

| Dimension | Required cases |
| --- | --- |
| Viewport | 1080 desktop; 560 narrow desktop; 375 narrow/mobile-like width; regular and reduced-motion media query |
| Conversation state | empty/welcome; one settled turn; multi-page history; latest streaming; Steer; Follow-up; Stop; completed collapsed work; failed/retry; interrupted/continue; aborted; imported/partial history |
| Evidence type | Markdown; reasoning; Tool call; Tool result; raw JSON; terminal/log; code; unified diff; table; checklist; HTML/Web/game/music output; file/artifact/media; approval; grouped questions; subagent activity/inbox |
| Disclosure levels | turn → activity group → individual Tool → typed result → raw payload; every level pointer + Enter + Space; close; focus visible; `aria-expanded`/native state truthful; no duplicate toggle |
| Trace | mode tab keyboard; turn selection; system prompt; Tool schemas; ordered context messages; current input; unknown/unavailable stage; model call; event filters; selected node → raw stage; query failure → retry |
| Panels | Session tools menu Escape/outside/roving focus; status sections; background job log/cancel; capabilities; permissions; model Provider/reasoning; Composer delivery; files tree; subagent graph/console/satellite |
| Error/recovery | transport error; Runtime unavailable; clipboard rejection; file preview error; Tool failure; approval decision failure; input submit failure; retry/continue preserves evidence and focus |
| Long-content behavior | keyboard-scroll every bounded pre; horizontal overflow; virtualization/remount; open while detached from live-follow; open while at bottom; prepend older history; expansion does not move the summary anchor |
| Accessibility | visible focus; Tab order; Escape policy; Arrow/Home/End where role requires it; labelled regions; no hidden tabbables; `inert` inactive surfaces; status/alert/live announcements; axe or equivalent semantic check |

### Receipt boundary

This receipt is an audit and implementation handoff, not a claim that the P1
items are fixed. The next owner should turn each P1 into a bounded WorkItem,
add a focused regression test before editing the shared disclosure seam, then
run the real Browser matrix and record exact pass/fail/unverified evidence.

## Agent CSS owner cleanup audit receipt — 2026-08-24

This is a read-only selector/DOM audit. No CSS or TSX was changed by this
receipt. The current production conversation is
`PawSessionWorkspace` with `AgentTimeline presentation="fx"`:

- `PawSessionWorkspace.tsx:757-815` renders the conversation as
  `.paw-agent-next.paw-session-workspace__conversation.paw-chatfx`; the
  `.paw-session-workspace__composer` is its sibling, not a descendant.
- `AgentTimeline.tsx:1021-1080` emits `.paw-user-message` and
  `.paw-assistant-text`; it does not emit the old
  `.agent-user-message-shell`, `.agent-user-message`, or
  `.agent-assistant-message` classes.
- `AgentTurnWorkDisclosure.tsx:95-136` nests activity under
  `.agent-turn-work__sequence`, so old direct-child
  `.agent-turn-sequence > [data-timeline-kind="activity"]` selectors do not
  describe the current FX tree.
- `ActivitySummary.tsx:1293-1354` emits `.paw-activity-stack`,
  `.paw-activity`, and `.paw-activity__detail`; nested rows are
  `.agent-activity-row[data-state]`, not `data-status`.
- `StructuredRenderers.tsx:320-339` emits `.fx-progress-card`, `.fx-track`,
  and `.fill`; there is no `agent-rich-progress__*` producer.
- The pending renderer uses `.agent-working-dots > b`; it does not emit
  `.paw-comp8-shape`.

### Production owner boundary

The intended single-owner seam is:

1. `paw-os-agent-migrated-v1.css`: session shell, titlebar, breadcrumb,
   top-level Composer, side panels, and trace.
2. `paw-os-agent-fx.css`: current FX turn/user/assistant presentation,
   work disclosure, activity stack, and FX tool/approval/progress surfaces.
3. `features/agent/agent.css`: rich renderer internals only (Markdown, HTML,
   code, file, diff, table, reasoning, and structured result content).
4. `design/workspace.css`: shared measure, Composer behavior, and generic
   action/disclosure behavior.
5. `paw-os-webmodel-v1.css`: global WebModel shell/menu/dock only; it should
   not remain a second Agent conversation owner.
6. `paw-os-agent-composition.css`: retain Room satellite and Agent rail
   regions; do not delete the file as part of Agent cleanup.

### High-confidence dead selectors

After confirming there is no fixture-only consumer, the following exact
selectors are safe deletion candidates:

- `paw-os-agent-migrated-v1.css:1000-1002,1011`:
  `.agent-rich-progress__meter`, `.agent-rich-progress__track`,
  `.agent-rich-progress__fill`, and its reduced-motion fill rule. The real
  renderer uses the `.fx-progress-card/.fx-track/.fill` family.
- `paw-os-agent-migrated-v1.css:977-978`:
  `.agent-fx-pill[data-tone='vio']`. Current activity tones are
  `ok/run/wait/danger/warn`; `vio` has no producer.
- `design/workspace.css:277-278`: `.agent-tool-step [data-state]`; no
  `.agent-tool-step` producer exists.
- `paw-os-agent-next.css:153-156`: `.agent-activity-row[data-status="running"]`
  and `[data-status="active"]`; current rows emit `data-state`.
- `paw-os-agent-composition.css:282-309,622-624`: state-specific
  `.agent-activity-row[data-status=...]` pulse/marching/reduced-motion rules.
  Keep generic row geometry if still needed.
- `paw-os-agent-composition.css:207-233`: `.paw-comp8-shape` and
  `@keyframes paw-comp8-shape-hop`. Keep the live
  `.agent-assistant-pending`/`.agent-working-dots` rules.
- The `.agent-approval-block` declaration cluster is not produced by current
  TSX. It occurs in `features/agent/agent.css`, `design/workspace.css`,
  `paw-os-agent-composition.css`, `paw-os-agent-next.css`,
  `paw-os-webmodel-v1.css`, and `paw-os-agent-migrated-v1.css`; the real
  approval renderer is `.fx-approval`. Remove only after the repository-wide
  producer/fixture check proves no remaining consumer.

### Structural mismatch and consolidation candidates

- `paw-os-agent-next.css:158-176` and `paw-os-webmodel-v1.css:457-492`
  scope Composer rules below `.paw-session-workspace__conversation`. This
  cannot match the current sibling Composer. Move any still-needed values to
  the migrated top-level Composer owner, then delete these nested blocks.
- `paw-os-agent-migrated-v1.css:894-897` narrows `.paw-chatfx
  .paw-user-message` inside `@container paw-window`; it is imported before
  the later FX stylesheet at equal specificity and is therefore overridden.
  Move the narrow rule into the FX owner or delete it.
- `paw-os-agent-migrated-v1.css:966-1102` is a duplicate FX tail. Move the
  live `agent-fx-pill`, `agent-fx-day`, `agent-fx-fade`, current Markdown,
  result-width, usage, timeline, and narrow-padding declarations into the FX
  owner; remove the legacy `.agent-user-message` and
  `.agent-activity--inline` portions rather than retaining a second cascade.
- Split, rather than blindly delete, the mixed blocks in
  `paw-os-webmodel-v1.css:360-392` and
  `paw-os-agent-migrated-v1.css:358-392,1071-1089`: retain live
  `.agent-reasoning-summary`/`.agent-activity-row` rules, remove legacy
  `.agent-activity`, `.agent-activity--inline`, and inline timeline rules.
- Old message classes in `paw-os-agent-migrated-v1.css:287-309,345-356,1025-1045`,
  `paw-os-agent-next.css:129-152`, `paw-os-webmodel-v1.css:259-295,342-351`,
  and `paw-os-agent-composition.css:129-193` do not match the current FX
  wrappers. Preserve only generic rich Markdown rules that still match live
  content, such as the applicable `.agent-markdown` rule.
- Do not remove `paw-os-agent-composition.css:459-575` (Room satellite) or
  `:577-614` (Agent rail) while deleting Agent conversation overrides. The
  old Composer region at `:397-455` requires a send/stop consumer check and
  migration before removal.

### Minimum verification after implementation

```bash
cd "<repo-root>"
rg -n "agent-rich-progress__|agent-approval-block|agent-tool-step|data-status=.*agent-activity-row|paw-comp8-shape|paw-session-workspace__conversation.*paw-session-workspace__composer" control-center-web/src

cd control-center-web
pnpm exec vitest run \
  src/paw-os/apps/paw-apps-style.test.ts \
  src/paw-os/apps/PawSessionWorkspace.test.tsx \
  src/features/agent/timeline/chat-rendering.test.tsx \
  src/features/agent/timeline/agent-turn-work-model.test.ts \
  src/paw-os/apps/PawContextTrace.test.tsx --reporter=dot
pnpm exec tsc --noEmit --pretty false
pnpm run build
```

After a fresh Vite restart, visual acceptance must cover 1080/560/375 widths
and Markdown, long output, diff, HTML, Tool, approval, failure/recovery,
streaming, activity/reasoning expansion, and Composer focus. Confirm that
`.paw-user-message`, `.paw-assistant-text`, and `.paw-activity` remain the
only current FX outer classes; every disclosure has keyboard/focus-visible
behavior; and the sibling Composer is not covered by a side panel or stale
WebModel/Composition override.

## Agent long-result clipping diagnosis and repair receipt — 2026-08-24

Purpose: a person reading a multi-page Tool result must be able to use the full
conversation viewport and scroll to every result layer without content
appearing to terminate above the Composer.

- **Reproduction:** in Preview Session `session-work-disclosure`, open “本轮工作”
  and the first “运行项目命令” result. Browser geometry showed the expanded
  Turn at about `1367px`; Virtuoso had correctly updated `data-known-size` and
  the full result remained reachable at maximum scroll.
- **Discriminating result:** the apparent clipping was not a stale Virtuoso
  measurement and not the nested reveal overflow fixed earlier. The
  `.agent-timeline` itself had computed `padding-bottom: 120px` while
  `PawSessionWorkspace` already places Composer in a separate sibling grid row;
  Virtuoso also supplies a `34px` footer. The obsolete overlay reserve removed
  120px from the visible reading viewport on every long result.
- **Fix:** `control-center-web/src/paw-os/styles/paw-os-agent-migrated-v1.css`
  changes both active separated-flow timeline declarations from a `120px`
  bottom reserve to `0`; the existing Virtuoso footer remains the sole reading
  clearance.
- **Regression:** `control-center-web/src/paw-os/apps/paw-apps-style.test.ts`
  rejects any separated Agent timeline rule that reintroduces a `120px`
  Composer reserve. The test was observed failing before the CSS change and
  passing after it.
- **Browser verification after a fresh Vite restart:** computed
  `padding-bottom` changed from `120px` to `0px`; the scroll viewport grew from
  roughly `349px` to `469px` in the same window; the unused band between
  timeline and scroller changed from `120px` to `0px`; the expanded Tool detail
  remained about `452px` and Virtuoso retained the full Turn height.
- **Focused command:**
  `pnpm vitest run src/paw-os/apps/paw-apps-style.test.ts -t "does not reserve the Composer twice|does not clip nested Tool evidence"`
  passed `2/2`.
- **Boundary:** this proves the local Preview layout path and the exact CSS
  regression only. The remaining Agent state matrix, installed foreground, and
  all-App route matrix are still open.

## APP-001 page-by-page route QA receipt — 2026-08-24

Scope: read-only enumeration of the real PAWOS routes, production owners,
fixtures, browser-visible states, and layout risks. No source, test, CSS, or
Runtime behavior was changed by this receipt. This is a QA handoff, not a claim
that every page has passed foreground acceptance.

### Two routing layers

- The legacy/hash route registry contains 19 paths in
  `control-center-web/src/app/route-registry.ts:36-56`; the lazy Router is
  enumerated in `control-center-web/src/app/router.tsx:40-68`. `/_primitives`
  is a development showcase and is not a product page.
- PAWOS production resolves the same hash path through
  `control-center-web/src/paw-os/runtime/app-registry.ts:39-50` and the route
  bridge in `control-center-web/src/paw-os/PawOsApp.tsx:36-47`. `/project-field`
  is the Wayfinder; `/agent` and `/rooms` share the Agent App; `/appearance`
  is a real System Settings page but is absent from the legacy route registry.
- `/rooms` without a `room` query selects a new Agent surface; use
  `/rooms?room=room-preview` to open the Room fixture. Session/Room query
  selection is implemented by `PawAgentApp.initialSelection` in
  `control-center-web/src/paw-os/apps/PawAgentApp.tsx:365-385`.

Preview base URL:

```text
http://127.0.0.1:<redacted-port>/?controlTransport=mock#/agent?session=<redacted-session>
```

### Agent QA sequence and evidence

Production owner is `PawAgentApp` → `PawAgentHome` or
`PawSessionWorkspace`; the conversation is `AgentTimeline presentation="fx"`
(`control-center-web/src/paw-os/apps/PawSessionWorkspace.tsx:875-930`). The
fixture source is `control-center-web/src/features/agent/preview-data.ts` and
its transport wiring is `control-center-web/src/app/preview-control-transport.tsx`.

| QA order / URL query | Fixture purpose | Required visible check |
| --- | --- | --- |
| `/agent` | New/empty home | Role/model selection, new-work action, Rail open/close |
| `session-fresh` | Empty Session | Welcome state, no phantom history, Composer focus |
| `session-preview` | Normal transcript | Markdown, code, citation, file, Todo, Tool activity, Composer |
| `session-work-disclosure` | Multi-page turn work | Final result stays visible; “本轮工作” expands to reasoning/Tools/diff/file |
| `session-gallery` | Renderer gallery | Markdown, diff, HTML, artifact, approval, error, code and structured result |
| `session-report` | Deliverable report | HTML preview, Markdown file, literal HTML/code text, broken-file retry |
| `session-states` | Lifecycle/background jobs | Running, failed, aborted, retry, queued/cancelling/completed jobs |
| `session-input` | Grouped input | Single/multi-select, recommended option, submit feedback, blocked Todo |
| `session-long` | Long transcript | Virtualized history, latest jump, follow/stop, scroll anchor after expansion |
| `session-models` | Model switch | Adjacent model attribution remains secondary to the answer |

For every Agent case also switch Conversation ↔ Agent Trace, open Session
Tools → status/subagents/files, exercise pending approval/memory review and
Composer attachment/model/permission/tool controls. Current CSS owners are
the migrated shell (`paw-os-agent-migrated-v1.css`), FX conversation
(`paw-os-agent-fx.css`), rich renderer internals (`features/agent/agent.css`),
shared workspace, and the older composition/webmodel/next layers; this is the
highest-priority page for cascade and clipping verification.

### Room, four tool panels, and satellites

Production owner is `PawRoomWorkspace` in
`control-center-web/src/paw-os/apps/PawRoomWorkspace.tsx:330-477`; public
chronology and folding are `:489-695`. Fixture source is
`control-center-web/src/app/preview-room-data.ts:26-240`, wired as
`room-preview` by `preview-control-transport.tsx`.

| Surface | Owner / selector | Required visible check |
| --- | --- | --- |
| Room conversation | `PawRoomConversation`; `.paw-room-chronology` | Public messages stay ordered; tool/route/progress activities fold into the real Turn |
| Activity disclosure | `details.paw-room-chronology__fold` | Pointer/Enter/Space expand; detail text remains reachable; pending approval never folds |
| Flow | `PawRoomFlow`; `panel=flow` | Task/dependency graph, node focus, SVG markers, narrow viewport |
| Execution | `PawRoomExecution`; `panel=execution` | Ordered execution/tool evidence, long detail and horizontal overflow |
| Progress | `RoomStatusPanel`; `panel=progress` | WorkItem and participant status; opening a participant satellite works |
| Governance | `PawRoomGovernance`; `panel=governance` | Participant/topic/WorkItem/settings mutations and confirmation feedback |
| Room runtime | `.paw-room-workspace[data-agent-mode="room"][data-panel][data-status]` | Loading, synced, busy, stopping, recovery/error, stop-whole-turn |

Satellite dispatch is `control-center-web/src/features/paw-os/PawOsSatelliteHost.tsx:23-37`:

| Target kind | Production component | Required interaction |
| --- | --- | --- |
| `project` / `task` / `work-document` | `ProjectSatellite` / `PlanningTaskSatellite` / `WorkDocumentSatellite` | Open the corresponding native page, preserve title/path, handle empty/error |
| `session` | `AgentSessionSatellite` | Return to Session without duplicate chrome |
| `room + panel` | `RoomPanelSatellite` | Flow/execution/progress/governance in an independent window |
| `participant` / `subagent` | `RoomParticipantSatellite` / `SubagentSatellite` | Participant chat, subagent run/log/result, long content |
| `process-terminal` | `ProcessTerminalSatellite` | stdout/stderr, running/cancelling/failed, two-step stop confirmation |
| `package` | `PackageAppSatellite` | install/update/enable/disable/rollback/uninstall preview → confirm → receipt |
| `result` | `PawResultWindow` | artifact/image/audio/HTML result window and close/reopen |
| `browser-target` | `PawBrowserApp` via `PawAppsRuntime` | Target tab, Agent trace, takeover/stop; no stale satellite owner |

### Remaining PAWOS pages

| Route family | Production owner | Fixture / key states | Primary QA risk |
| --- | --- | --- | --- |
| `/project-field` | `PawDesktop` → `PawCompositionField` | Wayfinder shortcuts, zoom/pan, compact viewport | PAWOS Wayfinder and legacy `ProjectFieldFeature` are different owners |
| `/overview`, `/planning`, `/work-documents` | `PawNativeApp` → `ProjectWorkbenchSurface` → `PawWorkbenchMigrated` (`overview/planning/documents`) | `overview.get`, `planning.dashboard`, `preview-work-document-routes.ts`; graph, task dialog, document reader, `?document=ID` | Native migrated workbench versus legacy feature CSS; graph/detail widths |
| `/memory` + `view=roleBooks,timeline,relations,organize,preferences` | `MemoryFeature` inside `PawNativeApp` | `preview-memory-data.ts`; graph, timeline, evidence, curation, preferences | Canvas bounds, nested evidence dialogs, narrow native nav |
| `/knowledge` | `KnowledgeFeature` inside `PawNativeApp` | knowledge preview transport; libraries, document/chunk/artifact, graph/jobs | Rail/detail split, graph canvas, source preview and long chunks |
| `/input`, `/input?view=lexicon`, `/voice`, `/history` | `PawSystemAppsMigrated` → `InputMethodFeature` / `VoiceFeature` / `HistoryFeature` | `preview-input-data.ts`, `preview-history-routes.ts`; loading/error, preview/apply/rollback | System shell plus feature CSS, long forms and modal focus |
| `/plugins`, `?view=catalog`, `?view=proposals` | `PluginsFeature` or `PawPackageCatalog` | `agent.extensions.*` preview routes; installed/catalog/proposal/apply | Catalog and installed surfaces have different owners but share App Center chrome |
| `/observability`, `/context-debug`, `/diagnostics` | `ObservabilityFeature`, `ContextDebugFeature`, `DiagnosticsFeature` | `previewObservationSnapshot`, `previewContextTrace`, `previewDebugContext`; filters, expandable nodes, retry | Long identifiers/pre blocks and dense system panels |
| `/configuration`, `/configuration?view=agent`, `/appearance`, `/governance`, `/approvals` | `ConfigurationFeature`, `PawAgentSettings`, `PawAppearanceSettings`, `GovernanceFeature`, `ApprovalsFeature` | `preview-input-data.ts`, `previewApprovalItems`; settings, sensitive fields, approval decision | `view=agent` and `/appearance` are separate components despite adjacent paths |

### Dock-only Apps

These have no ordinary route but are real primary-dock surfaces in
`features/paw-os/model/app-registry.ts:151-160`:

- **Files:** `features/files/PawOsFilesApp.tsx`; `workspace.list/read`; Session
  selection, directory expand/collapse, Markdown/HTML/diff/code preview,
  loading/error/retry, Window Chrome Portal.
- **Browser:** `paw-os/apps/PawBrowserApp.tsx`; `previewBrowserSnapshot()` and
  `browser.tabs/traces/snapshot.latest/command`; tabs, omnibox, snapshot hit
  targets, history/settings/find, Agent trace, takeover/stop.
- **Terminal:** `features/terminal/PawOsTerminalApp.tsx`;
  `terminal.sessions.*`; auto-create, tab/new/close, xterm resize/focus,
  input/output, exited/error states and process-terminal satellite.

### Common evidence fields and viewport matrix

Each page receipt should record: source fixture and route, opened control,
concrete evidence reached, focus target before/after, scroll anchor before/after,
console errors, loading/error/empty state, recovery result, and whether the
control remained clickable after expansion. Render at all four sizes:

```text
1440 × 900
1024 × 768
560 × 900
375 × 812
```

Minimum production selectors to capture:

```text
Agent: main.paw-agent-app[data-selection],
       section.paw-session-workspace[data-panel][data-status],
       main[data-agent-tree="projection"],
       main.paw-session-workspace__trace[data-active], aside[data-tool]
Room:  section[data-agent-mode="room"][data-panel][data-status],
       details.paw-room-chronology__fold, button[role="tab"], .paw-room-tools
Native: [data-app-id][data-page-id], [data-system-app][data-page-id]
Browser: .paw-direct-browser, .paw-browser-workspace[data-show-agent]
Files: .paw-files-app, .paw-files-tree, .paw-files-preview
Terminal: .paw-terminal-app, .paw-terminal-xterm
```

### Three structural risks carried into implementation

1. **Agent cascade ownership:** PAWOS imports FX, migrated, next, webmodel,
   composition and feature Agent CSS together; page-level screenshots must not
   be treated as proof that the outer conversation has one owner.
2. **Composer sibling structure:** in `PawSessionWorkspace` and
   `PawRoomWorkspace`, the Composer is a sibling below the viewport, while old
   nested Composer selectors still exist in the legacy layers; verify computed
   styles and long-result bottom clearance.
3. **Room/Agent leakage:** `RoomStatusPanel` imports `features/agent/agent.css`
   while Room migrated CSS owns the Room tool surface; check every Room panel
   and participant/subagent satellite for mixed typography, spacing, buttons,
   and disclosure behavior.

### Verification boundary

This receipt proves the static route/owner/fixture inventory only. It does not
prove Browser foreground acceptance, installed PAWOS behavior, or that any page
is visually accepted. The next owner should execute the sequence above and
append per-page evidence rather than closing APP-001 from a single `/agent`
snapshot.

## AUI-001 rich-result disclosure contract and receipt — 2026-08-24

Purpose: a long Agent answer is a navigable evidence tree, not a flat wall of
cards. The final answer remains the default reading surface; every structured
result beneath it must truthfully reveal its complete content by pointer,
Enter, and Space without moving the reader away from the chosen summary.

The acceptance method for every disclosure is now:

1. identify the human question answered by the collapsed summary;
2. ensure the expanded body contains the real evidence rather than a second
   paraphrase;
3. keep `details[open]`, `summary[aria-expanded]`, and `aria-controls` in one
   controlled state path;
4. preserve the summary's focus and scroll anchor for pointer, Enter, and
   Space;
5. give long code, Diff, HTML, raw Tool output, and other overflow evidence a
   named, keyboard-focusable bounded reading region;
6. verify both the initial default (short evidence open, multi-page evidence
   closed) and repeated open/close cycles.

The first shared implementation covers checklist, table, Diff, long code,
unknown/future content, Provider reasoning, Tool calls/results, and the dormant
structured-summary fallback through `useDisclosureControl` in
`features/agent/timeline/disclosure-anchor.ts`. `DiffPreview` now exposes the
actual controlled Diff region without adding a visually inert wrapper. Existing
rich-result styles and semantic list/table structures remain intact.

Regression evidence:

- the new `chat-rendering.test.tsx` case first failed because the checklist
  summary had no `aria-expanded`; after implementation it exercises all five
  visible rich-result families by Space, Enter, and pointer, checks focus
  retention, and resolves every `aria-controls` target;
- the full focused Agent renderer file passes `43/43`;
- TypeScript and path-bounded `git diff --check` pass;
- in the real Preview `session-gallery`, the checklist changed from
  `open=true/aria-expanded=true` to false on Space and back to true on Enter,
  with the summary focused after both operations.

Boundary: this closes the conversation rich-result family only. Agent status,
subagent, file-collection, Context Trace legacy nodes, Room panels, and every
other App disclosure remain explicit APP-001 audit items; native pointer
behaviour alone is not acceptance.

## APP-001 Input Studio page receipt — 2026-08-24 (partial)

Page purpose: let a person understand input readiness and deliberately curate
local vocabulary without writing anything before review. The vocabulary task
must make selection, candidate evidence, provenance, and the eventual write
action readable as four separate roles.

The reported failure was reproduced from the `/input` vocabulary workflow:
below the generic `860px` management breakpoint, the shared row grammar
collapsed the leading grid track to zero, so the checkbox painted into the
candidate title; the provenance pill competed for the same line, and the first
body content could sit too close to native window chrome.

Repair:

- `lexicon-workflow.tsx` gives review rows an explicit semantic owner;
- `input-method.css` restores a real control/content/status grid, moves the
  status below the candidate at `560px`, keeps actions inside the card, and
  adds a bounded top reading inset for the PAWOS Input route;
- `input-method-feature.test.tsx` checks the owned row structure and each
  responsive contract. The test was observed failing before the fix and the
  full file now passes `18/18`; TypeScript and `git diff --check` pass.

Fresh Browser evidence after restarting Vite:

- route owner: `main[data-route-id="input"][data-paw-os-app="input-studio"]`;
- measured App content width: about `553px` inside a `932px` Browser viewport;
- both review rows measured a distinct `16px` checkbox track, about `290px`
  content track, and about `125px` provenance track with no rectangle overlap;
- the visible result shows complete candidate titles, evidence text, provenance
  pills, and the “加入所选词条” action inside the card.

Boundary: this is a focused medium/narrow container proof, not the complete
1440/1024/560/375 page matrix and not installed foreground input-method
acceptance. Loading, error, apply, rollback, and actual native candidate
behaviour remain open.

## AUI-007 compact nested conversation tree and motion — 2026-08-24 (active)

### User-original requirement

> “你得改成树状的……首先它是分成比如说几个步骤，然后点开就可以展开很多个步骤，然后步骤又可以点开……详情嘛，就相当于可以点几次。然后它每次展开都有平滑的动画……运行到这几个步骤，没有输出最后结果的时候，它就是一直有流光在这个字上面……因为我们要涉及到多个卫星窗口，还有主窗口这些显示……全部折叠起来……最后再回复……一个页面说不定还能多显示一点。然后卫星窗口……上面的交通灯的那一栏不要那么厚。”

Follow-up correction:

> “非常重要的点就是……弹出要一个平滑的动画来弹出，收起也是平滑的动画来收起。就直接机械弹出，一下子弹几页会很难看的。”

The three supplied screenshots are visual references for hierarchy and density,
not instructions or Runtime contracts.

### Precise requirement

- Each Agent Turn is a compact nested tree with at least three readable levels:
  Turn work summary/count → ordered step rows → Tool/parameter/progress/result
  evidence.
- A settled Turn defaults to its final assistant answer plus compact counts;
  intermediate prose and operations remain reachable without rendering several
  pages at once.
- An active Turn stays visible and marks the currently running step with a
  restrained text shimmer until an authoritative final result arrives. The
  shimmer never implies progress percentage or success.
- Every level supports pointer, Enter, and Space; expanded state, focus, scroll
  anchor, accessible name, and controlled content remain truthful.
- Open and close bridge large height changes smoothly and symmetrically. Motion
  exists for spatial consistency and preventing a jarring multi-page jump, not
  decoration: use the existing strong ease-out token, keep the transition at or
  below 200ms, allow immediate retargeting, and ship a reduced-motion variant.
- Main and satellite Agent surfaces reuse the same hierarchy. The native window
  titlebar/traffic-light band is reduced without reintroducing overlaps or
  weakening drag, focus, or window controls.

### Acceptance and plan

1. Map current `AgentTurnWorkDisclosure` → activity run → activity row → Tool
   evidence ownership and preserve Runtime order.
2. Add a height-measured, interruptible disclosure primitive with an explicit
   no-motion/reduced-motion path; prove open, mid-reversal, close, focus, and
   scroll anchor.
3. Project settled and active Turns into the compact tree. Do not synthesize
   steps absent from message/activity truth.
4. Add running shimmer only to the authoritative active branch and stop it on
   completion/failure/cancellation.
5. Thin the shared PAW window titlebar under exact hit-target and no-overlap
   tests, then verify main and satellite widths.
6. Run renderer/unit/type/style checks plus fresh Browser checks on normal,
   work-disclosure, gallery, long, running, failed/recovery, and satellite
   fixtures at the four APP-001 viewports.

This item remains active until the nested interaction and titlebar pass real
Browser verification. Static screenshots alone do not close it.

### AUI-007 / AUI-008 implementation receipt — 2026-08-24 (nested tree slice complete; chrome and viewport matrix remain active)

Implemented the conversation-density and disclosure slice without changing the
Runtime event contract:

- `SmoothDisclosureReveal.tsx` is now the shared measured disclosure owner. It
  mounts before measuring, closes from the current rendered height, keeps exit
  content mounted and inert, supports in-flight reversal and streaming resize,
  and uses `180ms cubic-bezier(0.23, 1, 0.32, 1)` with an immediate
  reduced-motion path.
- `AgentTurnWorkDisclosure.tsx` projects a compact Turn summary such as
  `4 个步骤 · 2 个工具 · 39 秒`, keeps the settled final answer outside the
  disclosure, and exposes the ordered process as an accessible tree.
- `ActivitySummary.tsx` supplies the next levels: ordered reasoning/Tool nodes,
  real parameter/progress/result detail, and a separately animated raw-return
  disclosure. Deep disclosure state is keyed by the stable Activity ID, so a
  parent close/remount does not silently forget that the raw result was open.
- `AgentTimeline.tsx` removes the redundant visible one-to-one user label/time
  row while retaining an ISO `<time>` and author description for semantic/audit
  access. Room participant identity was not changed.
- `paw-os-agent-fx.css` adds the restrained tree rail/dots and applies the text
  sweep only to an authoritative `data-state='running'` node; completed nodes
  have no animation and reduced-motion/forced-colors modes disable the sweep.

Verification evidence:

- red-first regression checks failed against the former visible user metadata
  and former `本轮工作` control before the implementation;
- `pnpm vitest run src/features/agent/timeline src/paw-os/apps/paw-apps-style.test.ts`
  passed `159/159` tests;
- `pnpm typecheck` passed;
- `pnpm build` passed (`4356` modules transformed; only the existing large
  chunk advisory remains);
- fresh Preview Browser on `session-process-fold` reached Turn → Tool → raw
  JSON, with truthful `aria-expanded/aria-controls`, `role=tree/treeitem`,
  pointer/Space/Enter operation, exact computed motion, closing content still
  mounted and inert, focus retained, and the deepest raw disclosure restored
  after closing and reopening its parent;
- fresh Preview Browser on `session-states` showed
  `paw-agent-fx-text-sweep 1.85s` only on the real running Knowledge node, while
  completed Knowledge nodes computed `animation-name: none`.

Proof boundary: this closes the nested Agent tree and one-to-one message
metadata slice in source/tests/build and current mock Preview Browser. It does
not close AUI-007's 1440/1024/560/375 matrix, long-content scroll-anchor stress,
shared titlebar thinning, Room/participant satellite reuse, or installed native
foreground acceptance. APP-002, AUI-009, RUI-002, and RUI-003 remain active.

## APP-002 unique window controls and page-by-page chrome audit — 2026-08-24 (active)

### User-original correction

> “接下来每一个 APP 都在严格检查。那个上面那个首页和交通灯不能和其他按钮重复，按钮不能重复，不只是交通灯，还有其他地方。”

The supplied crop is evidence of the current overlap/duplication appearance,
not a source contract.

### Precise requirement and acceptance

- Audit every main App and satellite window for duplicated commands, repeated
  traffic lights, overlapping App/Home icons, repeated titles, and two controls
  that perform the same navigation or mutation.
- One command has one visible owner in the current context. A window-control,
  route control, App identity, and content action may sit near one another only
  when their purposes are distinct and labels/hit targets do not overlap.
- The shared titlebar must stay compact but preserve drag regions, traffic-light
  hit targets, keyboard focus, portalled actions, window title, App identity,
  and narrow-width priority. Hiding a duplicate must not remove the only
  accessible command.
- For each APP-001 route and satellite, record the command inventory, duplicate
  verdict, bounding-box overlap verdict, pointer/keyboard result, and exact
  owner. A screenshot alone is insufficient.

## RUI-002 Sol orbital identity and participant state language — 2026-08-24 (active)

### User-original correction

> “太阳、行星和小行星这种，卫星这种……艾特之后就可以艾特地球或艾特火星、金星、木星这种……卫星窗口就可以生成对应的 UI……哪个正在运行，颜色区分一下，没停止运行的或者等待检查的，就颜色不一样。”

### Precise requirement and acceptance

- A Room is presented as **Sol**. Direct Room Partners use stable planet names
  such as Earth, Mars, Venus, and Jupiter; their child Subagents use moons,
  satellites, asteroids, or other subordinate celestial identities.
- Room Composer mention suggestions expose the real participant target behind
  `@Earth`, `@Mars`, `@Venus`, and `@Jupiter`; naming is presentation identity,
  never a replacement for Runtime participant/session IDs.
- Main Room, participant windows, and subagent satellite windows reuse one
  orbital identity component and one state grammar.
- Color distinguishes authoritative states including running, waiting for
  review, stopped/completed, failed/attention, and disconnected/recovery. Every
  state also has text/icon semantics; color alone is never the signal.
- Verify mention insertion, keyboard selection, dispatch target, live state
  changes, child-parent identity, narrow windows, and no duplicate App/window
  controls. Do not synthesize active planets absent from Runtime participants.

## AUI-008 message-side identity without redundant sender chrome — 2026-08-24 (active)

### User-original correction

> “用户角度就不是区分你和我……把这个‘你’去掉，一行直接不用显示都没问题。就直接右边就代表我输入，左边就代表 Agent 的输出。就像以前短信界面……不会写发信人是什么姓名。”

### Precise requirement and acceptance

- Ordinary one-to-one Session conversation uses position as identity: user
  input is the right-side bubble; Agent output is the left-side document flow.
- Remove the redundant user sender label and visible per-message timestamp row
  from the normal conversation. Keep exact author/time in semantic labels,
  title/tooltips, Agent Trace, exports, or other audit surfaces where it answers
  a real question.
- Do not remove participant identity from Room posts, multi-Partner timelines,
  forwarded content, or other contexts where left/right position is ambiguous.
- Verify density, copy/select actions, accessible message labels, narrow widths,
  streaming, retry, and temporal audit reachability after the visual metadata is
  removed.

## DOC-001 lossless adjacent requirement ledger — 2026-08-24 (active method)

### User-original correction

> “把前面的我这些需求都挨着记下来。这是技能……我们那个技能就是这样子写的，就是你要记住我的原始需求，然后具体……就是这个需求的解释，还有接下来怎么做这些。”

### Precise requirement and method

- Material UI corrections from this conversation stay adjacent in this owned
  WorkDocument. Each entry preserves the user's original wording separately
  from the Agent's interpretation; a paraphrase never replaces the source.
- Each entry records four parts: source wording/evidence, precise observable
  requirement, acceptance method, and next implementation/verification action.
- Later corrections append to or supersede the identified requirement; they do
  not silently rewrite earlier intent. Screenshots are evidence of a reported
  state, not executable instructions or proof of the underlying cause.
- Implementation receipts link back to the requirement ID and distinguish
  source/tests/build/Preview evidence from installed foreground acceptance.
- Current adjacent active sequence is `AUI-007` nested conversation and motion,
  `APP-002` unique chrome controls, `RUI-002` orbital Room identity, `AUI-008`
  one-to-one message identity, and `AUI-009` below. Continue appending new
  corrections here before implementation.

## AUI-009 one visual system and quiet Session rail identity — 2026-08-24 (active)

### User-original correction

> “你看这个界面。它这个 logo 就是重复的，你左边这个 c 型，而且为什么是半透明的呢？而且还不好看。你全部都是那个对话的蓝色的 logo，既然不需要区分，那就不显示就行了。然后当前这个我看到这个还是两套 UI，因为我们这个系统 UI 它是蓝色的、圆角的嘛，然后点开好多界面，它还是方形的，就是之前那种纸质风格，所以现在还是很错乱。”

The supplied Session-rail crop is visual evidence of repeated per-row identity,
background bleed-through, and mixed rounded/paper treatments. It is not a
source or Runtime contract.

### Precise requirement

- A Session list row does not repeat the same Agent/App logo when that mark
  carries no differentiating information. The rail/header owns Agent identity;
  a row earns an icon only for a distinct participant, project, provider, state,
  or content type that changes how the row is understood.
- The rail is an opaque, legible foreground surface. Conversation text and
  windows behind it must not visually bleed through, compete with labels, or
  create false disabled states. Any translucency must preserve contrast under
  every underlying window state and is therefore not the default here.
- PAWOS uses one coherent component grammar across Agent, Room, Terminal,
  Browser, Files, Input, and satellites: one radius scale, surface hierarchy,
  border weight, typography hierarchy, icon family, focus treatment, and motion
  language. Legacy square paper cards may remain only where a genuinely
  document-like object requires them; they cannot survive as an accidental CSS
  layer alongside rounded system UI.
- Shared shell/App identity, traffic lights, Session rail identity, and row
  state are separate roles. The same logo/title/action may not be painted by
  two owners, and removing a duplicate must preserve the only accessible name
  and command.

### Acceptance and next actions

1. Inventory `PawWindowFrame`, Agent window chrome, Session rail header, and
   Session row icon/title owners; remove repeated decorative marks only after
   proving their accessible/command owner remains.
2. Make the open Session rail an owned opaque surface and verify its stacking,
   clipping, focus ring, scroll, hit targets, and underlying-content isolation.
3. Define the current rounded system grammar as the shared token/component
   owner; identify and retire legacy paper/rectangular overrides page by page
   instead of layering another global CSS patch over them.
4. Verify normal/hover/selected/running/waiting/failed rows at 1440, 1024, 560,
   and 375 widths, including long Chinese titles and projects, with no repeated
   logo, text bleed, truncation, or pointer overlap.
5. Carry the same owner audit into every APP-001 route and satellite, recording
   the exact remaining legacy selector when a page cannot yet be unified.

This item remains active until real Browser interaction shows a single visual
grammar and the Session rail is both visually quiet and semantically complete.

## RUI-003 collaboration-first satellite and Room Focus — 2026-08-24 (active)

### User-original clarification

> “这个卫星窗口，你是知道我的需求的，就主要是想能够直观地看到，就是多个 Agent 之间的协作分工、任务流转。所以当前我的形式、我想的形式可能不是最好的形式，你也可以根据我的需求来优化最后的展示效果。”

The supplied Room Focus screenshot is evidence of the current multi-window
composition, not a mandate to preserve that exact layout.

### Page purpose and precise requirement

- Room Focus exists to make collaboration legible, not to maximize the number
  of miniature chat windows. Within one glance it should answer: what is the
  shared Goal, which Partner owns each WorkItem, what is happening now, what is
  blocked or waiting for review, where a handoff is going, and where the latest
  result/evidence can be inspected.
- The canonical relationship is Goal → WorkItem/dependency → owning Partner →
  current step/Tool evidence → handoff/review/result. Public Session messages
  remain reachable, but repeated full transcripts are supporting detail rather
  than the primary collaboration overview.
- Sol is the Room/mission root. Planet identities are direct Partners; moons,
  satellites, and asteroids are their child Agents. The visual hierarchy must
  preserve real Runtime/Room IDs, ownership, ordering, dependencies, and state;
  celestial names are a stable presentation layer, not invented participants.
- A compact Partner surface shows identity, owned WorkItem, authoritative state,
  current action, blocker/review need, last meaningful receipt, and unread/new
  change. Selecting it reveals the same nested Session evidence tree used by
  Agent UI instead of embedding an always-expanded duplicate conversation.
- Task transfer is represented as an explicit directed handoff with source,
  target, artifact/contract, state, and timestamp/order. Motion may communicate
  a real new transfer or active state, but never invent progress or run forever
  after the authoritative state settles.
- The host window owns traffic lights and Room identity. Internal Partner and
  satellite surfaces are collaboration nodes/cards/panels, not duplicate macOS
  windows with repeated traffic lights, App icons, or titlebars.

### Proposed information architecture and acceptance

1. **Mission strip:** compact shared Goal, overall reconciliation state, active
   WorkItem count, review/blocker count, and one clear exit/focus action.
2. **Flow view:** ordered WorkItems and dependencies/handoffs, grouped by real
   owner and state; connections remain readable without requiring a literal
   physics simulation or decorative orbit.
3. **Orbit/Partner rail:** one compact planet node per real Partner with current
   assignment and status; child Agents nest beneath their parent only when they
   exist.
4. **Inspector:** selecting a WorkItem or Partner opens its public timeline,
   latest result, Tool evidence, and recovery action through the shared smooth
   disclosure tree. The overview stays stable while details change.
5. Verify with at least: parallel independent work, dependency handoff,
   reassignment, waiting review, failure/recovery, stopped child, completed
   reconciliation, empty Partner, late-joining Partner, long evidence, narrow
   satellite, keyboard navigation, and state updates during an open disclosure.
6. Browser acceptance records whether a person can identify owner, next handoff,
   blocker, and latest result without opening every Partner surface. A visually
   attractive screenshot that cannot answer those questions does not pass.

The exact layout may change during implementation when a clearer collaboration
model is found; observable Room ownership and evidence semantics may not.

## AUI-010 truthful Tool progress meter — 2026-08-24 (active)

### User-original requirement

> “已扫描 24 / 48 段有进度的工具加入进度条”

### Precise requirement, acceptance, and next action

- A Tool node with authoritative bounded progress renders a compact progress
  meter next to its textual receipt. `24 / 48` and a canonical numeric
  `progress: 0.5` both mean 50%; the UI retains the human-readable count when it
  exists.
- The meter is evidence, not decoration: clamp malformed values, never infer a
  percentage from elapsed time or DOM order, and do not render a determinate bar
  when the Runtime supplies no total/fraction.
- Running uses the active state token; completed settles at the authoritative
  final fraction (100% only when completion truth supports it); failed/stopped
  keep their last known fraction and pair it with text/icon state so color and
  bar length never imply success.
- Add red-first Activity rendering tests for numeric fraction, count text,
  missing/invalid progress, and terminal states; then verify compact/nested Tool
  rows in Browser without increasing the collapsed Turn height.

### Implementation receipt — 2026-08-24

- `ActivitySummary.tsx` now derives a determinate Tool meter only from an
  explicit `current / total` receipt or a finite numeric `payload.progress`.
  Count receipts take precedence, malformed values are rejected, fractions are
  clamped, and terminal state never fabricates `100%`.
- The collapsed Tool row keeps the visible receipt (`24 / 48 段`), exposes a
  semantic `progressbar` with numeric and textual ARIA values, and colors the
  meter from the independent Tool state. The narrow layout hides only the
  repeated count text, not the semantic meter.
- Red-first coverage in `activity-summary.test.tsx` verifies a counted running
  Tool, an invalid unknown-progress Tool, and a completed Tool whose last
  authoritative fraction is still 50%.
- Focused verification: eight Vitest files, 133 tests passed; `pnpm typecheck`
  passed; `pnpm build` passed with 4,359 modules transformed and only the
  existing chunk-size advisory. Browser mock inspection observed
  `knowledge：24 / 48 段`, `aria-valuenow=50`, a half-width fill, and a compact
  inline count. This is rendering/interaction evidence, not installed Runtime
  or native foreground acceptance.

## RUI-002 / RUI-003 Sol collaboration implementation receipt — 2026-08-24 (partial)

- A pure `RoomFocusProjection` now projects real Room Goal, WorkItems,
  dependencies, participants, public activities, receipts, handoffs, blockers,
  results, and evidence. Earth/Mars/Venus/... are stable display aliases over
  real participant IDs; no synthetic active participant is added.
- `PawRoomFocusOverview` replaces the duplicated flow/execution/progress stack
  in the PAW Room workspace with one collaboration-first surface: WorkItem
  tree, planet rail, directed handoff list, and a selection inspector. The
  public Room conversation remains the sole chronological public timeline.
- `RoomComposer` displays and inserts `@Earth`-style aliases while dispatching
  to the real participant identity. Opening a selected planet automatically
  closes the side inspector so Room Focus contains the main Room and the one
  requested satellite instead of three competing columns.
- Browser mock interaction verified the visible Goal and counts, three-level
  ownership information, Earth → Mars handoff, keyboard-addressable selections,
  real Mars selection, `SOL · 协作聚焦`, one Mars satellite, and the absence of
  the former side panel after opening it. This does not yet close narrow-window,
  child-Agent moon/satellite, failure/recovery, installed Runtime, or native
  foreground acceptance; those remain active under RUI-003.

## AUI-009 / APP-002 chrome, rail, and identity implementation receipt — 2026-08-24 (partial)

- `PawAgentApp` now gives the shared work-record rail one semantic owner: the
  toggle exposes `aria-expanded` and `aria-controls`, Escape closes the rail,
  and closing returns focus to the originating toggle. Session rows no longer
  repeat the Agent identity tile; the two object groups are labelled `Session`
  and `Sol`, while their full titles remain available to accessibility and
  native tooltips.
- The active rail and search field now use an opaque cold surface. The obsolete
  warm-paper and 50%-transparent rail/search overrides were removed from
  `paw-os-agent-composition.css`; the migrated Agent stylesheet is the current
  owner. A style-boundary test prevents the retired owner from returning.
- `PawSessionWorkspace` no longer portals a second Agent icon/title into the
  window chrome. `PawWindowFrame` owns the visible App/title identity, while
  the portal owns only navigation, sync state, and Session actions. The rail
  toggle participates in the same flex/grid chrome layout instead of being
  absolutely overlaid on traffic lights or the title.
- `PawWindowFrame` now distinguishes a real window from a Room Focus partner
  card. The Room host retains exactly one set of traffic lights; a focused
  planet surface has no duplicated traffic lights, App icon, or macOS titlebar
  and exposes one explicit close action. Detached ordinary windows continue to
  use full window chrome.
- The reviewed `pawos-brand-icons-v1/icon-wall.html` remains the identity source:
  colored tiles identify Apps and simple line icons identify actions. The
  existing `PawAppIcon` already matched its twelve App/Room identities. The
  stale browser/PWA silver mark was replaced with the Agent identity SVG and
  regenerated 64/192/512 PNG variants; no action icon was incorrectly replaced
  by an App tile.
- Focused regression verification passed 10 Vitest files / 161 tests,
  `pnpm typecheck`, and `pnpm build` (4,359 modules; only the existing chunk-size
  advisory). Browser mock interaction confirmed an opaque icon-free row rail,
  Escape plus focus return, one host traffic-light group, one Mars close action,
  and zero Mars minimize actions. This is real Browser rendering/interaction
  evidence against mock data, not installed native foreground acceptance.
- APP-002 and AUI-009 remain partial until Input Studio, Terminal, Files,
  Browser, Project, Memory, Knowledge, App Center, Monitor, and Settings have
  each passed the same owner, overflow, responsive, and visual-grammar audit.

## APP-003 Input Studio page purpose, layout, and disclosure — 2026-08-24 (active)

### User-original requirement

> “后续 app 一个一个页面检查，这种错位还有不精致严格检查。”

The attached `/input` screenshot shows a checked lexicon row whose checkbox,
title, evidence, and source pill occupy competing columns, plus a sticky action
above a long mixed-purpose page. It is visual evidence, not acceptance by
itself.

### Precise requirement and acceptance

- Each Input Studio navigation item owns a distinct user purpose and route.
  `输入法` configures and verifies input behavior; `词库` reviews candidates and
  applies selected entries; `语音` operates voice input; `输入记录` explains and
  searches recorded input. Selecting `词库` may not silently render the same
  all-in-one Input page with the relevant workflow buried below unrelated
  sections.
- The page has one vertical scroll owner. The sticky refresh/review action may
  not cover the first heading, and the final primary action must remain fully
  reachable without a hidden body scrollbar.
- A lexicon row has stable checkbox, readable content, and status/source owners.
  The checkbox never overlaps the title; evidence may use a bounded two-line
  preview instead of disappearing behind single-line ellipsis; the source pill
  moves to its own row at narrow widths. Complete text remains available through
  disclosure or an accessible label.
- Input Studio uses the same cold, rounded PAWOS surface grammar as Agent/Room.
  Retired warm-paper cards and feature-local nested card borders must not compete
  with the System App surface owner.
- Verify route ownership, loading/empty/error/review/apply states, keyboard
  operation, focus-visible, and 1024/720/560/375 container widths. Browser mock
  geometry proves only the rendered frontend; installed input-method foreground
  behavior remains a separate acceptance boundary.

### Implementation receipt — 2026-08-24 (partial)

- `输入法` and `词库` now have separate feature owners and route-scoped query
  lifecycles. The input page no longer fetches or renders lexicon review, while
  the lexicon page does not fetch source, model, overview, schema, or settings
  data that cannot serve its review purpose.
- The lexicon page has one page-level `刷新审阅` action. The duplicate refresh
  inside the review workflow was removed; apply and rollback continue to use
  the existing governed transport and refresh the authoritative review after a
  rollback.
- The review row keeps checkbox, content, and source/status in stable grid
  areas. Evidence can use a bounded two-line preview with `overflow-wrap`, and
  the source/status moves beneath content at the narrow container breakpoint.
  The sticky System App action strip is opaque and 40 px tall, so it no longer
  blurs or visually cuts through the first card.
- The PAWOS route bridge now reconciles the current hash immediately on mount,
  not only after a later `hashchange`. This prevents an existing Input Studio
  window from reopening the default `/input` page while the URL still names
  `/input?view=lexicon`.
- Red-first route and route-bridge checks plus the Input feature suite passed:
  three Vitest files / 28 tests. Browser mock verification observed exactly one
  `个人词库` heading, zero `输入法` headings, one selected `词库` navigation
  item, and one `刷新审阅` action after a hard Vite restart. The 560/375 visual
  passes and installed input-method foreground acceptance remain open, so this
  receipt is partial.

### Source audit and bounded continuation — 2026-08-24

- The shared PAWOS window chrome already owns the Input Studio identity, but
  `PawSystemAppsMigrated` repeats the same App SVG, App name, and current page
  in the inner navigation rail. The rail should begin with navigation choices;
  its accessible name can retain the App context without painting a second
  identity block. This removal applies consistently to all four System Apps.
- Input setting groups and their advanced section still use native `details`.
  They jump open or closed without the requested spatial transition. More
  importantly, `needsAttention` is ORed into `open` and the summary click is
  cancelled, so editing one value makes that group impossible to collapse.
  Replace both levels with explicit button-owned disclosures: stable
  `aria-expanded`/`aria-controls`, closed `inert` content, Grid `0fr -> 1fr`
  motion using the shared 190ms token, immediate reduced-motion geometry, and
  no forced-open lock once the user chooses to collapse a pending group.
- A failed local lexicon organization run currently emits its sanitized error
  twice inside one notice. Render it once; the status, recovery context, and
  underlying Rime ownership remain unchanged.
- Red-first acceptance adds identity de-duplication, two-level disclosure
  semantics and reversible collapse, closed focus isolation, and the single
  failure-message contract. The existing route, query, guarded mutation,
  lexicon review, responsive CSS, typecheck, and production build gates remain
  required. Real 1024/720/560/375 geometry and installed input behavior remain
  separate foreground evidence.

Correction after exact source re-read: the apparent repeated lexicon failure
text came from overlapping inspection ranges, not two live render calls. The
source already emits one sanitized error and the new assertion passed in the
red baseline, so no production copy change is required for that item.

### Continuation receipt — 2026-08-24 (source, tests, and build complete; foreground open)

- Removed the inner App icon/name/page header from the shared System App rail.
  Window chrome remains the sole visual identity owner; the rail retains an
  App-scoped accessible navigation name, and compact icon-only destinations
  expose their labels through `title` as well as `aria-label`. The retired base
  and 720px header selectors were deleted instead of left as dead overrides.
- Replaced both native setting `details` levels with controlled button-owned
  disclosures. Every trigger now has stable `aria-expanded` and `aria-controls`;
  every closed panel stays mounted but `aria-hidden` and `inert`. CSS Grid
  `0fr -> 1fr` motion uses `--motion-disclose` (190ms), supports immediate
  reversal, and reduces to an opacity acknowledgement when motion is disabled.
- Pending or invalid edits remain named in the closed trigger instead of
  forcing the entire group open. A person can now collapse, reopen, correct,
  and save without losing the draft or recovery message. The advanced local
  model path follows the same nested contract.
- Lexicon candidate text and its bounded two-line evidence preview now retain
  complete hover text while checkbox/content/source stay in their dedicated
  responsive grid areas. The exact failure-copy re-read confirmed no duplicate
  production render and the regression assertion preserves that fact.
- Red-first execution produced the intended three failures with the other 26
  checks green. Final verification passed four focused files / 106 tests,
  `pnpm typecheck`, targeted whitespace and `git diff --check`, and
  `pnpm build` (4,356 modules). The shared `PawOsApp` CSS asset moved from
  275.57 kB / 43.16 kB gzip to 274.83 kB / 43.08 kB gzip; only the existing
  over-500kB chunk advisory remains.
- No backend route, payload, mutation, native bridge, or persistence contract
  changed. The application Browser still exposes no controllable current tab,
  so real 1024/720/560/375 pointer/geometry inspection and installed input
  foreground behavior remain explicit open acceptance rather than inferred
  from tests or mock data.

## APP-004 Terminal page purpose, identity, and close semantics — 2026-08-24 (active)

### User-original requirement

> “你看这个界面。它这个 logo 就是重复的……既然不需要区分，那就不显示就行了。”

> “当前这个我看到这个还是两套 UI……圆角的嘛，然后点开好多界面，它还是方形的……现在还是很错乱。”

### Precise requirement and acceptance

- The host `PawWindowFrame` is the sole owner of Terminal App identity and the
  macOS-style window controls. The Terminal body may identify a shell tab or
  process, but an empty state may not repeat the Terminal App icon and title.
- Closing a shell tab and closing the Terminal window are different actions
  with different labels, focus return, and consequences. A tab action may not
  masquerade as a second window-close button or call the same ambiguous handler
  without an explicit ownership contract.
- The terminal viewport owns output scrolling; tabs, session controls, and the
  status/footer remain stable. Long working directories and process names
  truncate with an inspectable full label instead of pushing controls offscreen.
- The active Terminal uses the cold rounded PAWOS grammar and one CSS owner.
  Retired warm-paper, square, or translucent composition overrides may not
  compete with the final Terminal surface.
- Verify no-session, starting, connected, long output, error/stopped, multiple
  tabs, tab close, keyboard/focus-visible, long path, and narrow-window states.
  Browser mock rendering is frontend evidence, not proof of a real PTY or
  installed native foreground behavior.

### Implementation receipt — 2026-08-24 (partial)

- `PawWindowFrame` remains the only visible Terminal App identity. The empty
  state now states the available action without repeating the Terminal icon or
  `PAWOS 终端`, and shell tabs no longer repeat the App icon beside every
  session name.
- Window close is labelled `关闭窗口`; a running shell exposes the separate
  `结束终端会话 <title>` action. The duplicate footer action that called the
  same close mutation under `关闭当前终端` / `结束当前 run` wording was removed;
  the footer now reports a passive `运行中` state.
- The old Terminal blocks in `paw-os-apps-composition.css` and
  `paw-os-apps-next.css` were retired. Feature CSS owns PTY structure and the
  final migrated utility stylesheet owns PAWOS integration, preventing the
  former warm-paper and dark-terminal rules from competing by specificity.
- Red-first component and style-boundary checks passed two Vitest files / 52
  tests. After a hard Vite restart, Browser mock inspection observed one host
  identity, an unclipped `Terminal` title, icon-free session tabs, one window
  close, separate session-end actions, no duplicate footer close, and a stable
  long-path status row. The preview transport marks ended sessions `closed`
  without deleting their tabs; real PTY lifecycle, 560/375 geometry, and
  installed foreground acceptance therefore remain open.

### Continuation audit — 2026-08-24 (recorded before the next edit)

- Current-source inspection found that Terminal is not yet at the promised
  single-owner boundary. `features/terminal/paw-os-terminal-app.css` owns the
  standalone surface while `paw-os-tools-files-migrated-v1.css` repeats the
  tabs, PTY, status row, empty/error states, hover, responsive, and reduced-
  motion rules under `.paw-desktop-root`.
- The generic paper-tab rule in `paw-os-polish.css` excludes Browser but still
  matches `.paw-terminal-tabs`; its padding, warm paper background, selected
  fill, and button spacing can therefore leak into Terminal depending on CSS
  chunk order. Terminal must be explicitly outside that generic grammar.
- Repository consumer search found no TS/TSX consumers for the retired
  `.paw-terminal-console__subbar`, `.paw-terminal-meta`,
  `.paw-terminal-output`, `.paw-terminal-ansi-content`,
  `.paw-terminal-connecting`, `.paw-terminal-input-bar`, or
  `.paw-prompt-symbol` families. They describe the removed simulated-console
  composition and are safe candidates for deletion after regression coverage.
- The visible tab buttons expose `role=tab` and `aria-selected`, but currently
  have no controlled `tabpanel`, roving `tabIndex`, or Left/Right/Home/End
  keyboard behavior. The next edit must make the feature stylesheet the only
  Terminal body owner, remove the dead families, exclude Terminal from the
  generic paper selector, and complete the tab/tabpanel interaction contract
  without changing any PTY route or backend payload.

### Continuation receipt — 2026-08-24 (source, tests, and build complete; foreground open)

- `paw-os-terminal-app.css` now owns the complete Terminal surface: dark tokens,
  host titlebar integration, tabs, PTY viewport, status row, error/empty states,
  responsive behavior, hover, entry motion, and reduced motion. The repeated
  Terminal block, responsive rules, hover rules, and reduced-motion rules were
  removed from `paw-os-tools-files-migrated-v1.css`; the generic paper-tab rule
  now explicitly excludes `data-app='terminal'`.
- The seven retired simulated-console selector families recorded above were
  deleted after the no-consumer search and are guarded by the style-boundary
  regression. The feature stylesheet plus migrated utility stylesheet fell
  from 1,693 to 1,461 lines, a net removal of 232 lines. The built PAWOS shell
  CSS fell from the preceding Input slice's 274.83 kB / 43.08 kB gzip to
  270.70 kB / 42.44 kB gzip.
- Terminal tabs now control one labelled `tabpanel`, use roving `tabIndex`, and
  support wrapping Left/Right plus Home/End navigation with focus following the
  selected shell. Create and close actions expose pending state; close actions
  are disabled while the mutation is pending, and the full shell path remains
  inspectable through its title while the status row truncates safely.
- Red-first verification failed four new assertions before implementation, then
  passed two focused Vitest files / 54 tests. `pnpm typecheck`, `pnpm build`
  (4,356 modules), targeted retired-selector searches, whitespace inspection,
  and `git diff --check` passed. The build retained only the existing large-
  chunk warning.
- No Terminal route id, request body, PTY lifecycle, backend source, native
  bridge, or persistence contract changed. The in-App Browser still exposes no
  controllable live tab, so real 560/375 pointer and geometry inspection plus
  installed foreground PTY acceptance remain open rather than inferred from
  component tests or the mock transport.

## APP-005 Files page purpose, surface ownership, and navigation — 2026-08-24 (active)

### User-original requirement

> “后续 app 一个一个页面检查，这种错位还有不精致严格检查。”

> “当前这个我看到这个还是两套 UI……之前的那种纸质风格，所以现在还是很错乱。”

### Precise requirement and acceptance

- Files is a Session-authorized workspace browser: the window chrome owns App
  identity and Session selection, the left tree owns navigation, the preview
  owns readable file content, and the status row owns counts/selection. These
  regions may not duplicate commands or create competing scroll containers.
- The final Files integration stylesheet is the sole visual owner over the
  feature's structural CSS. Retired warm-paper/translucent composition rules
  may not override the cold opaque preview or selected-tree treatment through
  higher specificity.
- Root names, paths, file names, sizes, and preview metadata remain inspectable
  when visually truncated. Selected/focus/hover states must be distinct without
  mixing an unrelated blue focus ring with the Files identity color.
- Verify loading, no roots, empty directory, expanded tree, file loading,
  markdown/code/binary/error previews, keyboard tree operation, refresh,
  Session switching, 560/375 compact navigation, and one preview scroll owner.
  Browser mock data is frontend evidence, not authorization or filesystem truth.

### Implementation receipt — 2026-08-24 (partial)

- The retired Files block was removed from `paw-os-apps-composition.css`.
  Its high-specificity translucent warm-paper preview and competing selected-row
  treatment can no longer override the opaque `#fff` preview owned by the final
  utility stylesheet.
- The current structure retains one host App identity, one Session selector,
  one refresh action, a tree navigation region, a file preview main region, and
  a stable status row. Full root/path metadata remains in the accessible name
  and tooltip when compact rendering uses ellipsis.
- Red-first style-owner coverage plus the Files component suite passed two
  Vitest files / 51 tests. After a hard restart, Browser mock verification
  opened `README.md`, observed the cold opaque markdown preview and its complete
  path metadata, and expanded then collapsed `control-center-web` through the
  tree's labelled controls. Binary/error previews, 560/375 geometry, real
  authorization, filesystem truth, and installed foreground acceptance remain
  open.

### Continuation audit — 2026-08-24 (recorded before the next edit)

- Files still loads three competing stylesheet layers. The feature stylesheet
  defines structure, `paw-os-files-next.css` reintroduces the retired warm-paper
  palette and a second responsive layout, and
  `paw-os-tools-files-migrated-v1.css` repeats the full cold palette, toolbar,
  tree, preview, status, responsive, hover, and reduced-motion presentation.
  The warm layer has only the component import and style test as consumers, so
  its useful container behavior can move into the feature owner and the file
  can be retired.
- The current DOM assigns `role=treeitem` to non-focusable `li` elements while
  every nested button remains in the Tab sequence. It therefore does not meet
  the claimed keyboard-tree acceptance: Up/Down/Home/End cannot traverse the
  visible tree, and Left/Right cannot move to parents/children or expand and
  collapse the focused directory.
- Refresh clears all cached entries but reloads only roots. A previously
  expanded nested directory can then remain marked open while rendering the
  missing cache as `空目录`; refresh must reload every expanded visible
  directory. Visually truncated preview path/name/status text also needs an
  inspectable full label, and binary text payloads need an explicit unsupported
  preview instead of falling through to a code renderer.
- The next edit will make `paw-os-files-app.css` the sole Files owner, remove
  the warm and migrated Files blocks, implement one roving-focus tree contract,
  preserve expanded-directory refresh, and add binary/long-label states without
  changing workspace authorization, route ids, request bodies, or backend
  behavior.

### Continuation receipt — 2026-08-24 (source, tests, and build complete; foreground open)

- Files now imports only `paw-os-files-app.css`. The 131-line warm-paper
  `paw-os-files-next.css` file was deleted, and every Files selector—including
  its responsive, hover, and reduced-motion rules—was removed from
  `paw-os-tools-files-migrated-v1.css`. The remaining historical utility file
  now truthfully documents that it owns Browser only.
- The single Files stylesheet owns the cold opaque palette, amber identity,
  host tools, authorized tree, preview renderers, status row, one-scroll-owner
  renderer rules, 860px stacked layout, and 560px tree/preview navigation. Its
  amber focus treatment is distinct from selection and no longer inherits an
  unrelated generic blue or warm-paper state.
- Tree semantics now live on the focusable buttons rather than non-focusable
  `li` wrappers. One roving Tab stop supports visible-node Up/Down traversal,
  Home/End, wrapping-free boundary behavior, Right expand/first-child, and Left
  collapse/parent navigation. Refresh now reloads roots plus every expanded
  directory, so an open branch cannot turn into a false `空目录` after refresh.
- Binary-looking payloads render an explicit non-text preview. Full Session
  title, root path, file name, preview path, selected-file path/size, and root
  list remain available through native labels or `title` even when the visible
  row truncates; loading refresh is disabled and marked busy to prevent
  duplicate requests.
- Red-first verification failed the three new owner/tree/binary contracts before
  implementation. The final run passed three focused Vitest files / 56 tests,
  `pnpm typecheck`, `pnpm build` (4,355 modules), targeted retired-owner and
  whitespace searches, and `git diff --check`. The build retained only the
  existing large-chunk warning.
- Relative to the completed Terminal slice, the Files CSS chunk fell from
  15.22 to 14.15 kB and the PAWOS shell CSS from 270.70 to 263.99 kB: 7.78 kB
  less raw CSS overall (0.83 kB less gzip) while adding the real tree and binary
  interaction states.
- No workspace authorization rule, route id, request query/body, transport,
  backend source, filesystem read, or persistence behavior changed. Real
  860/560/375 geometry, pointer use, authorized filesystem truth, and installed
  foreground acceptance remain open because the in-App Browser still exposes
  no controllable live tab.

## APP-006 Project page purpose, planning density, and document reading — 2026-08-24

### User-original requirement

> “不只是摘要，而是要想这一页设计目的和如何达成。”

> “后续 app 一个一个页面检查，这种错位还有不精致严格检查。”

### Precise requirement and acceptance

- The host window owns the Project Workbench identity. Its internal rail owns
  only page navigation; the current Project object may identify itself in the
  workbench chrome, but the rail may not repeat the App icon/title.
- Planning is for choosing a day, manipulating real Goals/Tasks, and handing
  bounded work to an Agent. Date navigation and task actions are separate
  semantic groups; they wrap into stable rows before controls overlap and may
  scroll horizontally only within their own group at narrow widths.
- Work Documents use list/detail disclosure. Where two panes no longer leave a
  useful reading measure, selecting a document hides the index and the explicit
  back action restores it. Authority/revision/path/lifecycle remain readable in
  one intentional scroll owner.
- Verify overview, empty/populated tasks, dependency selection, dialogs,
  document current/history/list/detail/lifecycle, keyboard focus, long paths,
  and 760/520/375 layouts. Preview data is not Runtime or Git truth.

### Implementation receipt — 2026-08-24 (partial)

- `PawNativeApp` no longer repeats App identity in the internal navigation
  rail; the rail starts with its labelled page controls. The retired warm-paper
  native-nav owner was removed from the composition stylesheet, leaving the
  base App palette and migrated workbench surface in control.
- At the 760px workbench-stage breakpoint, planning tools now form distinct date
  and Agent/action rows with bounded horizontal overflow. Browser mock
  verification showed every date and action control without the previous
  `今天` / `交给 Agent 安排` collision.
- At the same breakpoint, an open Work Document enters list-to-detail mode:
  the index is hidden, the existing `返回文档列表` action becomes the recovery
  path, and the authority/lifecycle reader receives the full remaining height.
- Native routing and style-owner regression checks passed two Vitest files / 76
  tests, followed by the focused style suite at 49 tests. Browser mock passes
  covered overview, planning, work-document list, and selected detail after hard
  restarts. Populated dependency geometry, 520/375, dialogs, installed
  foreground, and Runtime/Git truth remain open.

### Continuation audit — 2026-08-24 (recorded before the next edit)

- Project already has one scoped visual owner in
  `paw-os-workbench-migrated-v1.css`; this slice must not manufacture a second
  polish layer merely to make the source count look smaller. The remaining
  chrome still repeats the host-owned App identity with a Project App icon and
  the literal `Project Workbench` breadcrumb. The internal chrome should retain
  the current project, path, page, and primary action while removing that
  duplicate product identity.
- The dependency field draws only declared edges, but the selected-task reader
  renders dependency ids as inert text. A user cannot follow a dependency back
  to its task, even when that task is already present in the same projection.
  Resolved dependencies need labelled controls that select the real task;
  unresolved ids must remain visibly truthful and non-interactive.
- At the common 1,050px container breakpoint, CSS hides every task-detail child
  except the header and actions. Description, progress, facts, and dependencies
  therefore become unavailable with no disclosure control. Compact mode needs
  an explicit animated, accessible `aria-expanded` disclosure; changing the
  selected task must close stale expanded detail rather than carrying it across
  objects.
- Project names, paths, task metadata, document titles, Authority ids, hashes,
  and dependency ids can all ellipsize or wrap under realistic data. Each
  compact label needs an inspectable full value without adding a second scroll
  owner. The next edit will lock these contracts red-first, then change only the
  Workbench component and its sole stylesheet; route ids, request bodies,
  Runtime/Git authority, persistence, and backend behavior stay unchanged.

### Continuation audit — 2026-08-24 (global owner cleanup recorded before edit)

- The scoped Workbench stylesheet is now the intended Project visual owner, but
  `paw-os-polish.css` still styles every class containing `row` or `actions` as
  a warm-paper button. That generic selector reaches Project document rows and
  planning/reader actions after the feature owner. Project must be excluded
  explicitly so those controls keep their cold rounded component grammar.
- `paw-os-agent-composition.css` still repaints every native App and navigation
  rail even though Files and Project now own those surfaces in their feature
  styles. The generic native/files block is a competing compatibility owner and
  can be removed without adding replacement CSS.
- `paw-apps.css` retains an unconsumed prototype family for the former generic
  App rail, workflow, partner grid, transcript/composer, resource grid, native
  suite and old Project detail/page shells. Production TS/TSX/HTML has no
  consumer for those exact classes. Red-first owner tests must reject their
  return before the dead declarations and their orphaned motion are removed.
- The portalled wake-schedule dialog imports the Planning form, whose 520px
  single-column rule is scoped to the standalone Planning route. Project needs
  its own narrow dialog override so the embedded form and schedule rows do not
  retain a cramped two-column layout at 520/375. This remains a layout-only
  change; routes, requests, task semantics, Runtime/Git truth, persistence, and
  backend ownership remain unchanged.
- Independent purpose/interaction review found that loading or failed task,
  document, graph and history reads currently fall through to an empty-state
  message. `正在读取` / `读取失败` and `暂无数据` are mutually exclusive facts;
  stale populated data may remain visible beside a notice, but an unresolved
  empty projection may not claim the collection is empty.
- The same task is exposed in the outline and dependency graph with the same
  bare accessible name. Each control needs its interaction context in the
  accessible name so keyboard and assistive-technology users can choose the
  list or graph target intentionally without changing the visible compact copy.
- A failed WorkDocument detail read currently falls back to the list snapshot
  while lifecycle controls remain mounted. A list snapshot cannot authorize a
  destructive lifecycle action: detail failure must keep the error/retry path
  and withhold lifecycle controls until current detail truth is available.
- Overview previews silently cap tasks at eight and documents at six. The
  bounded density is intentional, but the UI must name it as a recent subset
  and expose a direct `查看全部` route when more records exist. The task/dialog
  transport and history route persistence remain separate follow-up contracts;
  this edit does not invent backend fields or silently widen request authority.

### Implementation receipt — 2026-08-24 (Project source, tests, and build complete; foreground open)

- The Project interior no longer repeats the host App icon or product name.
  Current project/path/page/action remain in the compact chrome, long names,
  ids, paths and hashes retain inspectable full values, and the page heading is
  preserved at narrow widths.
- Resolved dependency ids are labelled controls that select the real task;
  unresolved ids remain visibly truthful and inert. The task list and graph now
  expose different accessible names for the same object. Compact task detail
  has an explicit `aria-expanded` disclosure, smooth bounded reversal, reset on
  task selection, and reduced-motion coverage instead of disappearing at the
  1,050px layout threshold.
- Loading/error notices are now mutually exclusive with empty-state claims in
  overview, graph and WorkDocument index. A failed or pending WorkDocument
  detail read withholds lifecycle actions rather than authorizing them from a
  list snapshot. Populated stale data may remain visible beside the notice.
- Overview caps are named as `最近 N / 共 N`, route to the complete task or
  document surface, and use Runtime `total` when it exceeds the loaded document
  page. Agent handoff drafts now carry project name, workspace path, Goal id,
  Task id and date before the natural-language intent. The embedded wake form
  and schedule rows collapse to one column at 520/375.
- Removed the generic paper-polish reach into Project, the generic native/files
  composition owner, and the unconsumed App rail/workflow/partner/transcript/
  composer/resource/native-suite/page/detail/empty prototype families. Across
  `paw-apps.css`, `paw-os-agent-composition.css`, `paw-os-polish.css`, and the
  Workbench owner, source fell from 3,896 lines / 220,224 bytes to 3,759 lines /
  195,872 bytes: 137 fewer lines and 24,352 fewer bytes while adding the real
  disclosure and state contracts. `paw-apps.css` alone fell by 25,191 bytes.
- Red-first checks captured four style-owner failures and five interaction
  failures before implementation. The final five-file Project suite passed
  101 / 101, `pnpm typecheck` passed, and `pnpm build` transformed 4,355 modules.
  The built `PawAppsRuntime` CSS is 158.84 kB / 23.01 kB gzip and `PawOsApp` CSS
  is 263.93 kB / 41.45 kB gzip; only the existing chunk-size advisory remains.
- History scope/query persistence across refresh/independent windows and the
  full priority/due-date/Goal Task editor remain explicit follow-up contracts,
  not hidden source claims. The App-bound Browser still exposes no callable
  Browser control tool, so 760/520/375 pointer/geometry and installed native
  foreground acceptance also remain open rather than inferred from tests.

## APP-007 Memory retrieval, evidence disclosure, and surface ownership — 2026-08-24 (active)

### User-original requirement

> “不只是摘要，而是要想这一页设计目的和如何达成。”

> “因为当前有多种风格。”

### Precise requirement and acceptance

- Memory first helps a user recover a relevant memory and understand why it is
  trusted. Catalogue rows show a bounded summary; selection reveals full body,
  status, provenance, and governed actions. System/debug context stays behind
  progressive disclosure rather than competing with the catalogue.
- Catalogue, partner books, timeline, relations, curation, and preferences are
  distinct purposes under one Memory identity. Navigation may not repeat the
  App icon/title, and hidden views may not remain interactive or visually claim
  space.
- Memory's final feature stylesheet owns its cold surfaces and pink identity
  signal. The retired cross-App paper Composition layer may not repaint list
  rows, filters, details, graphs, or management primitives by specificity.
- Verify list/detail, long summaries, lineage/evidence, loading/empty/error,
  each view, disclosure motion/reduced motion, keyboard focus, and 920/680/375
  layouts. Mock memories are rendering evidence, not durable-memory truth.

### Source audit and bounded implementation slice — 2026-08-24

- The catalogue already owns a correct list/detail shell, but its detail reader
  currently paints normalized `detail` before the preserved `text`. An Atom can
  therefore return a short summary and a complete body while the selected pane
  still shows only the summary. This slice separates row summary from selected
  content and names honestly whether the available field is full memory text,
  a topic summary, or a source description.
- Partner-book section buttons currently select an item whose provenance panel
  is rendered only after all five section groups. In a narrow window the click
  and its result are separated by several screens, so the interaction appears
  broken. The detail becomes a nested disclosure immediately under its owning
  row, with one open item, an explicit expanded state, reachable evidence, and
  a reversible collapse.
- This disclosure is an occasional evidence inspection whose motion purpose is
  spatial consistency and prevention of a multi-page jump. It uses a CSS Grid
  `0fr -> 1fr` disclosure with the existing 190ms `--motion-disclose` token and
  shared strong ease-out; rapid reversal retargets from the current value.
  Reduced motion removes positional travel and retains only a short opacity
  acknowledgement.
- `查看待确认内容` currently mutates local `view` without updating the native
  route, leaving the PAWOS navigation highlight and Browser history on the old
  page. It must call the same `openView('organize')` owner as every other Memory
  route change.
- Red-first acceptance covers distinct list summary/full detail, disclosure
  placement, `aria-expanded`/`aria-controls`, collapse and hidden focusability,
  evidence opening, and route synchronization. Existing catalogue, relation,
  timeline, curation, preference, error, and deep-link tests remain required.

### Implementation receipt — 2026-08-24 (source, tests, and build complete; foreground open)

- The selected catalogue detail now prefers preserved `text` and labels the
  result as full memory/source/topic content. List rows remain bounded summaries;
  redacted rows still expose only their content state. The duplicated metadata
  label is now `关联来源`, and the default `current` filter presents the honest
  `当前记忆` success state instead of an unknown-state fallback.
- Each partner-book row now owns its detail immediately below the trigger. One
  item opens at a time; the trigger exposes `aria-expanded` and `aria-controls`,
  the closed subtree is `inert`, and provenance evidence remains reachable.
  Expansion uses an interruptible CSS Grid `0fr -> 1fr` transition with the
  existing 190ms disclosure token. Reduced motion keeps only the short opacity
  acknowledgement.
- `查看待确认内容` now routes through `openView('organize')`, keeping the native
  Memory tab, Browser history, and rendered view synchronized.
- Red-first coverage captured the three intended failures before implementation.
  The focused Memory file then passed `44 / 44`; the broader Memory/native-App
  set passed `138 / 138` across seven files. `pnpm typecheck` and `pnpm build`
  both passed. Build retains the existing over-500kB chunk warning.
- The one-time Impeccable detector reported two new layout-property transitions.
  Both owning declarations were replaced with the Grid disclosure, and the
  React height measurement, observer, and state were removed.
- App-bound Browser inspection still reports no controllable tabs and only a
  stale unreachable Browser-route tab, despite the ambient Memory page being
  visible to the user. Therefore 920/680/375 visual geometry, real pointer
  motion, and installed foreground acceptance remain explicitly unverified;
  source tests and mock data are not promoted to that product claim.

## APP-008 App Center, Monitor, and Settings purpose and owner cleanup — 2026-08-24 (active)

### User-original requirement

> “不只是摘要，而是要想这一页设计目的和如何达成。”

> “后续 app 一个一个页面检查，这种错位还有不精致严格检查。”

> “当前这个我看到这个还是两套 UI……之前的那种纸质风格，所以现在还是很错乱。”

### Precise requirement and acceptance

- App Center exists to let the user understand and safely change one real Pi
  Package. Installed, catalogue, and proposal states remain distinct; package
  capabilities, provenance, pending changes, approval, install/update,
  enable/disable, uninstall, and rollback use preview/confirm boundaries and
  progressive disclosure instead of decorative cards that imply writes.
- Monitor exists to answer what is running, what context was assembled, what
  tools and prompts contributed, and what failed or needs recovery. Summary
  rows stay compact, but every meaningful source has an expandable concrete
  detail. Loading, stale, empty, partial, and error states remain truthful; no
  fixed `slice` may silently hide results without a visible count and route or
  disclosure to the remainder.
- Settings exists to edit Agent, appearance, configuration, governance, and
  approval policy at their real owner boundary. The current rounded cold PAWOS
  appearance is singular; a retired paper/theme prototype may not reappear as
  a second visual system or as an apparently writable control.
- `paw-os-sys-apps-migrated-v1.css` owns the shared System-App shell, while the
  plugins, observability, context-debug, diagnostics, and configuration feature
  stylesheets own their feature content. The generic `paw-apps.css` may retain
  only selectors consumed by current production components; retired Package,
  theme-gallery, native timeline, memory, context, diagnostics, approval,
  ingest, input, and voice prototype families must be removed together with
  tests that falsely name them as current owners.
- Acceptance covers current navigation, real package/configuration actions,
  nested disclosures, long prompt/tool text, loading/empty/error, keyboard
  focus, reduced motion, and 900/650/440/375 layout ownership. Add red-first
  owner tests, run the focused System-App suites, typecheck, and build. Real
  pointer/geometry and installed foreground remain separate evidence and may
  not be inferred from mock fixtures or source checks.

### Implementation receipt — 2026-08-24 (source, tests, and build complete; foreground acceptance open)

- Added one shared `Disclosure` owner and migrated Agent, Room, Context,
  Memory, Knowledge, Monitor, Settings, App Center, Browser, Project, and
  Workbench long-form content to nested progressive disclosure. Open and close
  keep content mounted through a 190 ms exit, update `aria-expanded`, apply
  `aria-hidden`/`inert` during exit, and respect reduced motion.
- Agent turns now keep the public result visible while compacting reasoning,
  tool calls, files, diffs, HTML, structured payloads, task plans, context
  assembly, and raw returns into a multi-level tree. Running steps expose
  truthful shimmer/progress, concrete prompt/tool details remain reachable,
  and long collections use explicit counts plus a route or disclosure to every
  remaining item instead of silent fixed slices.
- Room keeps public questions and replies visible in canonical chronology while
  folding each participant's work facts, tool evidence, reports, packets, and
  satellite history into smooth nested lanes. Member boundaries, Room status,
  modules, creation options, execution acceptance, and satellite-window packet
  history now preserve a reachable full set and explicit state.
- App Center uses preview/confirm/apply package actions; Monitor reports
  concrete source facts, progress, totals, and recovery state; Settings owns
  current configuration and appearance controls. Retired paper-style prototype
  owners were removed from the current System-App surface. Browser, Files,
  Terminal, Input, Memory, Knowledge, Project, Agent, Room, App Center,
  Monitor, and Settings were checked for duplicate controls, hidden overflow,
  metadata floor, and compact/narrow ownership in source and regression tests.
- Verification passed in `control-center-web`: `pnpm typecheck`; `pnpm build`;
  `pnpm exec vitest run --maxWorkers=1` with 152/152 files and 1428/1428 tests.
  High-worker experiments reproduced resource-sensitive wall-clock failures in
  heavy asynchronous suites; the affected tests pass as complete files and the
  final single-worker gate avoids competing with the product's real 1.45 s Stop
  reconciliation timer.
- Real in-App Browser pointer/geometry checks at 900/650/440/375 and installed
  foreground acceptance remain open because this Session has no callable
  Browser tab/control surface. Source, mock fixtures, screenshots from another
  task, typecheck, tests, and build do not prove those foreground gates.

## Continuation revision — 2026-08-24 desktop chrome and Dock owner cleanup

### User-original requirement

> “交通灯不能和其他按钮重复，按钮不能重复，不只是交通灯，还有其他地方。”

> “当前这个我看到这个还是两套 UI……系统 UI 它是蓝色的、圆角的嘛，然后点开好多界面，它还是方形的，就是之前那种纸质风格，所以现在还是很错乱。”

### Precise requirement and acceptance

- Shared window chrome owns one traffic-light group, one App identity/title,
  and one bounded App-control slot. Portalled rail, Session, Room, Browser,
  Files, and Terminal controls must remain to the right of the traffic-light
  safe area and may not repaint or duplicate the shared window actions.
- `paw-os.css` owns shell structure; `paw-os-motion.css` owns meaningful motion;
  `paw-os-shell-migrated-v1.css` owns the current rounded cold visual grammar.
  Retired Composition paper and web-model compatibility blocks may not continue
  to style titlebar, traffic lights, window material, Dock, overview labels, or
  shell identity through selector specificity.
- App identity SVGs remain shared assets in the titlebar, Dock, Launchpad, and
  Overview. A placement is removed only when it repeats identity without adding
  orientation; operation icons remain monochrome and distinct from App identity.
- Acceptance covers one traffic-light group per ordinary window, zero traffic
  lights in focus cards, stable title/App-control slots, opaque readable active
  and inactive windows, Dock active/open states, keyboard focus, reduced motion,
  and 760/560/375 geometry without title/control overlap. Focused shell/icon
  tests, typecheck, build, and bounded visual evidence are required; installed
  native foreground remains a separate acceptance boundary.

### Implementation receipt — 2026-08-24 (source and build complete; foreground open)

- Removed the retired 597-line `paw-os-composition.css` runtime layer and its
  only import. The active shell no longer carries a second warm-paper owner for
  window material, titlebars, traffic lights, Dock, menus, or overview labels.
- Reduced `paw-os-webmodel-v1.css` to the compatibility tokens and feature
  selectors still consumed by Agent polish. Shared chrome now has one visual
  owner in `paw-os-shell-migrated-v1.css`; `paw-os.css` retains shell structure
  and no longer contains the old `glacier`, `ink-paper`, or `blueprint` visual
  branches that could restore square windows or competing traffic-light rules.
- Added `UR-132` to make the current rounded cold appearance authoritative.
  The persisted `blueprint` value remains an internal compatibility identifier,
  not a user-selectable second appearance.
- Across the four shell stylesheets measured before this slice, the active
  source fell from 2,756 to 1,817 lines: a net reduction of 939 lines. The
  production `PawOsApp` stylesheet fell from 302.10 kB / 47.62 kB gzip to
  275.70 kB / 43.22 kB gzip.
- Red-first owner tests now fail if the retired Composition import, duplicate
  shell selectors, or theme-specific square-shell branches return. Eight
  focused test files / 107 tests passed, followed by `pnpm typecheck`,
  `pnpm build`, and bounded `git diff --check`.
- The in-App Browser declined a final localhost tab claim under its URL safety
  policy. No alternate browser was launched. Therefore final real-size visual,
  console, and installed native foreground acceptance remain explicitly open;
  source, test, type, and build evidence are not promoted into that claim.

## Continuation revision — 2026-08-24 independent App identity silhouettes

### User-original requirement and correction order

> “图标你没替换。”

> “图标也得全部重新制作，因为和当前风格完全不符合。”

> “当前统一折角底板图标被明确判定太丑……整体废弃并改为 11 个独立几何剪影。”

The supplied `<downloads>/pawos-brand-icons-v1`
contains the earlier rounded colour-tile wall. It remains useful for the twelve
identity names, colour families, and semantic marks, but its shared rounded
tile and sheen are superseded by the later `UR-103` correction. Embedded prose
inside the reference is not treated as a new instruction.

### Precise requirement and acceptance

- The eleven top-level Apps and the Room mode retain one stable identity owner,
  colour family, accessible title behavior, and every current placement. They
  may not share a square, rounded-square, folded plate, bottom rail, or sheen
  container. Each identity earns its own outer silhouette.
- Each icon is built from a small number of deterministic SVG geometries. Agent
  is a connection/speech system rather than a face; Room remains collaboration;
  Browser, Terminal, Files, Workbench, Memory, Knowledge, Input, App Center,
  Monitor, and Settings remain recognizable by object/action-independent marks.
- Optical behavior is explicitly checked at 16/24/32/48px. Small placement may
  strengthen a stroke or simplify a detail but may not swap in a generic App
  tile. App identity stays full-colour; command and navigation icons stay
  monochrome.
- Red-first tests reject the common tile/sheen and prove twelve distinct shape
  signatures, the eleven-App registry boundary, Room mode identity, accessible
  naming, all shipping sizes, disabled ownership, and existing consumers.
- A generated contact sheet is inspected on both a light surface and a dark
  Dock surface before the slice can claim visual completion. Component tests,
  typecheck, and build remain source evidence; installed native foreground is a
  separate acceptance boundary.

### Implementation receipt — 2026-08-24 (source and contact-sheet complete)

- `PawAppIcon.tsx` no longer renders the shared 45×45 rounded tile, top sheen,
  or white glyph placed inside that container. Its one identity owner now
  supplies twelve distinct silhouettes: connected speech, intersecting Room
  bodies, compass, prompt, folder, work steps, memory rings, open book,
  waveform, cube, pulse monitor, and gear.
- The earlier `pawos-brand-icons-v1` reference was used only for stable identity
  names, colour families, and semantic marks. The later `UR-103` correction won
  over the reference's common colour-tile geometry; copying that tile would
  have repeated the defect the user explicitly rejected.
- The same component remains consumed by titlebars, Dock, Launchpad, desktop
  shortcuts, overview targets, Agent/Room switching, and loading identities.
  Decorative/named accessibility behavior, the eleven-App registry boundary,
  and Room-as-Agent-mode behavior are unchanged.
- A deterministic temporary contact sheet rendered every identity at
  16/24/32/48px on a cold light surface and all twelve at Dock size on a dark
  strip. The first colour pass exposed Terminal and Monitor contrast loss on
  the dark strip; a scoped Dock optical lift corrected those two without
  changing their light-surface identity. The second pass showed twelve distinct
  readable contours at every requested size. The temporary generator was then
  removed from product source.
- The red-first icon suite rejects any returning tile/sheen/shared-container and
  proves unique silhouette signatures. Five focused consumer files / 97 tests
  passed, followed by `pnpm typecheck` and `pnpm build` (4,356 modules; only the
  existing chunk-size advisory). The `PawOsApp` CSS is 275.57 kB / 43.16 kB
  gzip after this slice.
- This is code, component-consumer, build, and local rendered-contact-sheet
  evidence. The in-App Browser safety refusal remains unchanged, so live App
  placement and installed native foreground acceptance are still open and are
  not inferred from the contact sheet.

## Continuation revision — 2026-08-24 installed Agent tree and code-surface contrast

### User-original requirement

> “提示词要展开看具体的呀，不然上下文装配看什么？”

> “就是那个对话框……需要给它改成树状的。比如说就这个图，它是你首先它是分成比如说几个步骤，然后点开就可以展开很多个步骤，然后步骤又可以点开，就是具体里面是工具调用还是什么样子的，就详情嘛，就相当于可以点几次。然后它每次展开都有平滑的动画。”

> “后续app一个一个页面检查，这种错位还有不精致严格检查。”

### Historical installed evidence and newly discovered defect (2026-08-24)

This is a historical local receipt, not the current branch, current `main`, or
the post-merge installation state. Machine paths, process IDs, and local ports
are intentionally redacted in this public handoff.

- The installed Electron PAWOS at `<local-apps>/RagImeControl.app` is built from `main` commit
  `cfb3f649e870b23c0da6635f22a246169fefaf60`, is signed, reports
  `gitDirty=false`, `frontendTransport=http`, `frontendBuildChannel=production`,
  and serves the same production surface through its local host on port `<redacted-port>`.
- A real persisted Session was opened through that host. Its final turn is
  collapsed to `15 个步骤 · 7 个工具 · 1 分 16 秒`; the disclosure expands to a
  15-node ARIA tree, a Browser tool node expands to process/result detail, and
  `完整返回` expands again to the complete 22-line / 514-character JSON. The
  turn and tool controls change `aria-expanded` from false to true and no
  production console error is emitted.
- Real 760, 560, and 375 pixel viewport checks show no document-level horizontal
  overflow. The composer remains inside the window at 375 px; compact chrome
  removes secondary labels before controls collide; the Dock and raw preformatted
  value use bounded internal horizontal scrolling.
- The same installed check exposed one blocking visual defect: the raw JSON code
  computes to `rgb(238, 243, 247)` while a later generic separated-message rule
  repaints its `pre` background to `rgb(246, 248, 251)`. The complete value is
  structurally present but visually unreadable. Source/test/build success does
  not waive this foreground failure.

### Repair acceptance

- The separated-message light-paper rule must continue to style ordinary prose
  and plain result bodies, but it may not repaint raw JSON, tool code, or terminal
  code surfaces. Those code surfaces keep the paired code background/text tokens
  and must remain internally scrollable at 760/560/375 px.
- Add a focused owner test that fails if the paired code-surface override is
  removed or if the broad generic `pre` rule becomes the final owner again.
  Re-run the focused style/component tests, typecheck, production build, reinstall
  from the exact new `main` commit, and re-read the installed computed colours
  before closing this slice.

## Current Trace Agent boundary

The current `/trace-agent` route is rendered by
`PawSystemAppsMigrated` through `control-center-web/src/features/trace-agent/index.tsx`
and loads `integrations/pi/skills/trace-agent-diagnostics/SKILL.md`. The
diagnostic Session is read-only with empty workspace roots. It shows the selected
Session/Room/run's original conversation, actual actions and Tool timeline, and
links to the diagnostic Agent conversation.

“交给 Agent 修复” is a separate explicit action. It creates an ordinary Agent
Session using `per_action` authorization and the selected workspace roots;
creating the handoff is not an applied repair. Only a completed repair Trace and
Eval/recheck receipt can establish a verified repair. `UR-180`, `UR-186`,
`UR-188`, and `UR-195` remain unassessed unless fresh E4–E6 evidence is attached.
