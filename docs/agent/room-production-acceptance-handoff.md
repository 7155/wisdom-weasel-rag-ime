# Room production acceptance handoff

> as_of: 2026-08-07 11:15 CST
> status: Room source commit `7de9cb1eabac4df691751de5b09280467f09ac7d` is committed, clean-installed, and component-aligned. Its managed-retry repair passed `64/64`; preceding full evidence remains backend `564/564`, frontend `104 files / 1007/1007`, TypeScript, Python compile, and `git diff --check`. The live Room proved the exact managed retry can resume its continuation, then reached a governed integration conflict on `tests/test_duplicates.py`. It has not completed later waves, full WorkDocument evidence, distributed independent review, or one final delivery. The user has now ratified a fuller architecture contract: Kernel-owned stable feature graph and transaction-owned events, equal peer outcome ownership, scoped integration, policy-derived target review, execution-time corrections, one readable WorkDocument, and a frontend that never guesses business state. These are now recorded in the authority document and Skills but are not yet implemented by `7de9cb1e`.
> canonical worktree: `/Volumes/undo 4t/git/learnA/.worktrees/paw-room-final-fix`
> branch: `codex/room-production-acceptance-final`
> current source commit: `7de9cb1eabac4df691751de5b09280467f09ac7d` plus the uncommitted authority/Skill/evaluation corrections listed in section 5; their focused contract suite passes `33/33`, and no new Room runtime implementation is included in that correction

## 0. Mandatory takeover gate: do not start by running commands

This checkpoint is being handed to a new conversation because the previous conversation became too long. The first response in the new conversation must **not** run a command, edit a file, start tests, stage/commit, install, launch a Room, or delegate work.

The new owner must first reply to the user in natural Chinese with exactly these four parts:

1. **当前做到哪里** — distinguish implemented/tested work from installed/GUI-verified work;
2. **现在仍有哪些问题** — restate the open product and acceptance gaps below;
3. **我理解的 Room 愿景** — restate the user's non-negotiable requirements below;
4. **确认后第一步** — name only the first bounded action it proposes.

Then wait for the user to confirm or correct that understanding. This is a handoff-specific takeover gate, not a product rule that every clear Room request must be clarified. After the user confirms, continue autonomously until a true user decision/permission/credential blocker occurs.

### Current problems at the handoff moment

- The current real Room is `客户目录真实并行最终验收 20260807`, Room
  `room:cc0492b7-d1f4-4789-b503-b2b1890e82bc`, Root
  `room-root:7a3711cbc44aa1fe7b20eb53771ec55a`. The retry wake path returned the Root
  to `running`; the later duplicate-customer delivery is held by integration
  binding `room-workspace-binding:410043c84d3c870e5d2757f2ea065902`
  with `state=conflict` on `tests/test_duplicates.py`. The target workspace has
  existing changes. Resolve through the governed workspace/integration flow;
  never overwrite it or edit the database to fake completion.
- The installed source is `7de9cb1e`, built from clean detached worktree
  `/Volumes/undo 4t/git/learnA/.worktrees/paw-room-final-fix-clean-7de9cb1e`.
  Component audit is green. The managed Pi runtime is
  `pi-0.80.7-98cfe6a3a0a4-raghost-c1414ab249` from source
  `98cfe6a3a0a420ac6de4f85153c55fbc8809b845`.
- The current architecture review identified open root-contract work: state and
  live events are not yet transactionally coupled; the approved plan is not yet
  materialized as stable feature `RoomTask` identities; Start/WorkDocument/dispatch release
  is not one durable preparation flow; frontend components can still infer
  business state; target-scoped required review and execution-time user
  intervention are not implemented. Existing regression claims below describe
  `7de9cb1e`, not these new target contracts.
- Historical checkpoint `021c97807b58f885e6c3b047a38d40446c7804a4` was installed from clean worktree `/tmp/paw-room-live-progress-install.XitWK5`; its earlier component audit and managed Pi runtime evidence remain diagnostic history, not the latest installed state.
- At that historical checkpoint, a fresh creation modal showed all four companions as `已邀请` and said they had equal capability; the earlier permanent `主持/实现/调研/最终复核` presentation defect was fixed in the installed GUI.
- The earlier internal-instruction GUI attempt remains invalid acceptance evidence and must never be reused.
- The valid natural-language run used only this ordinary product request: `我想把这个小客户目录做得更好用：可以批量导入 CSV 客户并先看看每一行有没有问题；能按邮箱后缀筛选；发现重复客户时能先对比、合并，合并错了还能撤销；还能查看每位客户是谁在什么时候改过什么。`
- That run verified the compact attributed state, natural Chinese vertical plan, four equal peers, and the no-work-before-Start gate. Commit `021c9780` projects live summary/update counts into the collapsed header, suppresses task-check recovery copy from deliverables, and distinguishes active silence from a real wait.
- Installed replay then exposed a narrower ordering defect: after the nine-update `reasoning_summary`, a later generic `participant_status` event (“完成了一步”) became the collapsed-card focus, so the header regressed to `澄·远 正在继续任务`. The current follow-up excludes generic participant bookkeeping when a meaningful public work summary exists. Its red-capable fixture reproduces the real ordering; focused Room tests and TypeScript pass.
- That follow-up is now installed commit `d30901ab`. The same Room shows a meaningful current headline, update count, Todo and “有新进展 · 回到最新” instead of the generic card reported by the user.
- Start produced four real vertical Tasks in the task view, but only the Facilitator initially ran; the other three stayed queued. Production logs showed `_active_room_todo_lineage` rejecting bounded child Tasks because their shared parent WorkItem remains owned by the Facilitator. Commit `53089a7b` accepts a `parentTaskId` child while retaining exact Room/root/task/session/participant checks. It is installed, and reloading the original Room recovered all three peers into genuine running Dispatches without a user retry.
- The recovered run also proves that an approved feature `wave` was presentation-only: all three peer Tasks were created together even though duplicate merge was explicitly wave 2. The current follow-up resolves the approved feature for each target, exposes the current/ready/waiting wave through `room_state`, and rejects later-wave collaboration until every earlier peer feature is committed and each isolated worktree is integrated. Because the old Room started before this gate existed, it may continue as recovery evidence but cannot prove correct wave scheduling.
- No fresh full-auto GUI Room has completed the required end-to-end path after this follow-up. The installed/Web UI must still prove the compact composer status, user-language planning, governed requirement/execution document, clarification, real parallel Tasks, peer review without self-review, recovery, integration, and a single final delivery.
- A real installed run exposed a queue-head blocker in an older Room: it had already reached `executing` but had no `work_documents` row. The old Room was stopped and is cancelled, so it remains diagnostic evidence only. The current source now repairs this exact post-Start loss at the context boundary; a fresh installed Room must still prove the visible recovery path.
- Several user-reported requirements remain GUI-only acceptance items. The next owner must use the ledger in section 4.1 and may only call a row fixed after its stated evidence boundary passes.
- The current automated run is green, but no fresh installed Room has yet shown the new peer-wait recovery, later-wave waiting card, or Kernel-over-WorkItem projection in one natural-language journey. These remain GUI acceptance items, not source-only completion claims.
- Existing screenshots and old Rooms still contain known failures such as stale `执行中`, duplicate/overlapping cards, weak tool results, meaningless citation placeholders, missing delivery reports, or fake visual parallelism. They are reproduction evidence, not proof of the current source.
- Both Room authority documents are already tracked. Stage their existing changes explicitly; do not use a broad forced add for the ignored `/docs/` tree.
- Installation must come from a clean detached worktree at the new commit. Do not install the dirty source tree or overwrite unrelated Pi/product changes.

### User's non-negotiable Room vision

- The user enters one natural-language goal; the default companion receives it, while `@伙伴` may change the receiver.
- If decision-changing details are genuinely missing, infer inspectable facts first and ask at most one clarification round. Two to four independent questions may be grouped with numbered A/B/C choices and answered compactly; a single mutually exclusive choice uses the option box. Selecting an option still requires confirmation; only “其他” opens free text. Confirmed answers stay inside the asking companion's chronological card.
- Before every implementation starts, show the understood goal, locked shared contracts, one to four vertical feature tasks with owners/dependencies/waves/write boundaries, integration, and acceptance. No project-file read/write, command, test, install, or companion dispatch may begin until the user clicks “开始行动”; pre-Start alignment uses user messages and already-projected Room/product metadata.
- Start-up uses Claude-style progressive disclosure: only compact routing cards are always present; the exact full Skill loads for the current stage, and linked references/scripts/examples load only when needed. Do not compress a complete Skill to a uniform 6 KiB/120-line cap.
- Split only by user-visible feature after shared contracts are locked. One feature has one Room Agent owner end-to-end; never split one feature horizontally into frontend/backend/parser/test work. At most four peer Room Agents run, in dependency waves rather than fake roster-filling.
- The approved PlanRevision is a Kernel-owned versioned outcome graph. Every
  feature uses one stable `RoomTask` identity with user outcome, peer owner,
  dependency Task identities, derived
  wave, write boundary and acceptance. Retry/recovery/reassignment creates a new
  Dispatch attempt for the same Task; call order and Agent prose cannot redefine
  it. Do not introduce a parallel FeatureWorkItem lifecycle; legacy WorkItem is
  migrated toward a compatibility projection.
- Every active Room companion uses the same model and complete work capability. `collaborationRole` is only current responsibility, never a permanent capability tier; the Facilitator may also own a complete feature. Do not reserve one companion as an idle or lower-capability Reviewer. After integration, use actual authorship/integration provenance to assign bounded review targets so nobody reviews its own work.
- Receiving, coordination, scoped integration, review, and reporting are
  assignable responsibilities, not ranks. The receiving companion is not a
  master. Any eligible peer may own a complete feature or an integration scope.
- The definition stage prepares one governed Markdown WorkDocument without
  touching the target project; Start freezes its approved plan revision and
  activates it before attempts release. It keeps two separate logical sections:
  immutable/append-only user source plus current confirmed requirements, and
  accepted plan plus Todo/progress/evidence/failures/risks/handoff/next action.
  Every Skill updates it from new user requirements and its own material
  progress; recovery and handoff read it before verifying source and runtime.
- A decomposable multi-feature task must create multiple real companion Tasks in parallel. The graph is only a compact overview; it cannot substitute for actual concurrent work.
- One companion Task is one continuous card. Retries stay in that card; a separate Task gets a separate card. Do not duplicate avatars or split one reply across miscellaneous boxes.
- Every companion message, question, confirmed answer, tool, progress item, and result stays inside that companion's large card, with nested cards for detail. Cards use authoritative creation time from oldest to newest; alignment ends its card before implementation cards begin.
- Active work has restrained but obvious motion and live updates. Recent actions remain in time order at the bottom. Important long-running read/edit/write/bash operations stream visibly and are individually expandable.
- The unchanged composer toolbar uses its available space to name who is doing what in a short phrase, for example `澄·远：梳理需求` or `澄·初：批量导入`. A generic `协作进行中` label is insufficient.
- Each card exposes the companion's current public work summary, real Todo, tools, worktree, files/diff, tests, artifacts, recovery, and handoff from the same source at different densities. Todo stays at the bottom while unfinished and disappears when fully settled.
- When a companion finishes, `已交付`/`已转交` must immediately become a user-facing report of what changed, what was produced, verification, risks, and who receives it. It must not leave stale `正在处理` text or a bare state label.
- Ordinary code, command, parameter, and transient Provider failures recover inside the Room. The Facilitator retries, switches model, redistributes, or serializes work without asking the user to babysit local failures.
- The user may send corrections, priority changes, pauses, or status questions
  while execution is active. Exact corrections append to the WorkDocument;
  only affected features pause or replan when safe, while unrelated work may
  continue. A shared-contract or dangerous expansion returns to visible
  approval instead of being silently accepted.
- Luna independent approval is rare and reserved for genuinely dangerous operations. Safe bounded workspace reads/writes/tests should not incur a review round merely for ceremony.
- Code, data, artifact, and integration-changing work always has a genuinely
  independent post-integration review before the current reporter gives one
  final answer. Review is per bounded target: exclude that revision's authors,
  repairers, and integrators, not everyone who worked anywhere in the Room.
  Pure discussion/read-only work may have an explicit policy exemption. If no
  eligible peer exists, report the independence blocker rather than fake a pass.
  Partners keep distinct personalities and role-specific voices; they do not
  repeat the same reporter-style final text.
- Public UI uses ordinary user language, not `Kernel`, `Root`, `Dispatch`, `Task`, `AC`, `Receipt ID`, protocol JSON, `需求对齐`, `已锁定`, or “回答保留在下一条消息”. Missing optional telemetry stays quiet rather than looking like a failure.
- Successful physical worktrees are cleaned only after integration while a permanent Room/requirement/owner/base/result ledger remains. Failed, blocked, cancelled, conflicting, or orphaned worktrees remain visibly marked until explicit resolution.
- Source retirement is progressive, not deferred wholesale: each new authority
  migrates named consumers, passes its focused and proportional full regressions,
  then immediately removes the replaced branch/file and obsolete tests. Git and
  the verified backup provide rollback; duplicate writable lifecycles do not.
  Files such as `agent_room_legacy_*` that still have a named live consumer are
  migrated first and are never deleted merely because their name looks old.
- Runtime/debug/conversation data should prefer the configured external-volume owner and bounded retention. Do not blindly move a live database or App Support directory without an owner-aware migration.
- Every authoritative state mutation and its public event/wake record is
  transactionally coupled and isolated per Room. The backend supplies active
  Root, phase, typed wait reason, runnable frontier, integration/review
  readiness and final identity; the frontend may format them but never infer a
  second business truth.

## 1. Objective and authority

Finish Room before starting the deferred Knowledge RAG integration. The authoritative product contract is:

1. this handoff for the exact checkpoint and remaining commands;
2. `docs/agent/room-facilitated-workflow-requirements.md` for the latest Room product vision and acceptance contract;
3. the current source and tests in this worktree.

Older Room screenshots, v1/v2 prototypes, historical handoffs, and earlier stopped Rooms are evidence of past failures, not current product authority.

The most recent user-visible requirement is non-negotiable: when a companion card reaches **已交付 / 已转交**, the card must immediately report in natural user-facing language what was delivered and who receives it. A bare state label or stale “正在处理” text is not a delivery.

## 2. Product behavior now implemented in the current Room source

- One companion + one Task is one card. Retries of the same Task remain in that card; different Tasks assigned to the same companion remain separate cards.
- The current retry is selected from a deterministic total event order. Legacy events cannot reclaim a card after an authoritative sequenced retry, even when an old result arrives later by timestamp.
- Active cards animate only while real work is active. Terminal cards settle, default to collapsed, and no longer display stale running/waiting copy.
- A terminal `work_result` or `handoff` replaces the card headline with the companion's public delivery report. Expanded details show files, diff totals, verification, risks, and handoff evidence when available.
- Todo stays at the bottom of a companion card while any item is unfinished, including after failure, stop, or an incomplete terminal result. It disappears only after every item is completed or abandoned.
- Read/edit/write/bash activity remains chronologically inside the same companion card. Tool rows are expandable, stream while running, and preserve bounded multiline output/diff previews instead of rendering only one line.
- Public copy avoids protocol terms and mechanical “需求对齐” language. Ordinary failures recover inside the Room; users are interrupted only for a real decision, permission, credential, or proven unrecoverable block.
- Questions and confirmed answers render inside the asking companion's card; the answer appears immediately, followed by persistent live status and a “回到最新进度” action when the user has scrolled away.
- The live status is a compact abstract indicator inside the composer toolbar to the right of `@`; it must not create a separate floating box, cover validation content, or change the composer size. After an answer or Start action, it immediately says that the input was received and work continues.
- `room_define` now requires a visible one-to-four-item execution plan. It locks shared contracts, vertical feature owners, dependency waves, write boundaries, integration, and acceptance; even a clear request waits for the typed “开始行动” authorization before dispatch, writes, or tests.
- A premature Facilitator delivery proposal with an active peer is normalized to a durable wait bound to that peer's exact Dispatch; the peer's public delivery creates a Facilitator resume Dispatch and returns the Root to running.
- The Task view renders approved features without a Task as compact plan cards. Later-wave cards remain visibly waiting until every earlier feature is complete and its isolated worktree is integrated; a real Task replaces the plan card when dispatched.
- The main Room projection selects the newest Kernel Root and its generation before falling back to legacy WorkItems, so a blocked or waiting Root cannot be masked by stale active bookkeeping.
- All active peer role labels are capability-neutral. Parallel work requirements derive from the approved feature plan rather than the Room's routing label or a static Reviewer/Researcher class.
- Automatic Session Todo initialization recognizes both immediate legacy execution and the approved planned dispatch released after “开始行动”; Todo wording no longer changes implementation capability from a static role label.
- Durable workflow skills preserve the immutable user source, visible plan, execution evidence, quality gate, and independent review across compaction or handoff.
- User-visible execution plans are written in the user's language and from the user's point of view. Internal English type declarations, camelCase fields, protocol names, and uninspected entry points remain in the WorkDocument or expandable technical detail.
- One governed WorkDocument is updated from later user corrections and from every owner's material progress across planning, implementation, quality, review, recovery, and handoff. It is not split into two drifting files or used as a Tool transcript.
- Live answer/start/task feedback is now rendered in the unchanged composer toolbar instead of a standalone status card. When the reader is above the newest activity, that compact indicator becomes the “有新进展 · 回到最新” action.
- Alignment reasoning now says it is organizing requirements and the execution plan; it no longer pretends the user still owes a decision while the model is merely planning.
- Facilitator and peer ownership are capability-neutral. The Facilitator may own a complete feature; review is selected later against bounded targets from actual provenance, not by pre-freezing an idle Reviewer.
- Room creation, settings, the partner view, task lanes, and the `@` menu no longer present stored routing roles as capability levels. Every companion is presented as able to own a complete task; current responsibilities come from the approved plan and actual provenance.

## 3. Independent review result

The reused read-only reviewer initially found three P1 defects:

1. an old Task outcome could override a newer retry;
2. a terminal card could retain old running/waiting copy;
3. failure/abort could hide unfinished Todo.

All three are now fixed. The final follow-up review returned `fixed`:

- mixed legacy/sequence replay is a transitive total order;
- three input permutations all select `dispatch-new`;
- a later-timestamp legacy old attempt cannot reclaim the card;
- the reviewer ran the focused lane test `14/14` and `git diff --check`, both passed;
- the reviewer did not modify files.

## 4. Verification already completed

Current expanded code state:

- latest Room plan/Skill/capability/WorkDocument focus: `51/51` passed;
- latest complete backend Room discovery suite: `561/561` passed in `719.332s`; injected `Pi host exited`, `ENOSPC`, `stale projection`, and preflight failures were expected negative-path output;
- latest complete frontend suite: `104 files, 1001/1001` passed;
- latest Room composer focus after removing the old standalone task-lock copy: `4/4` passed;
- latest TypeScript: `pnpm typecheck` passed;
- latest equal-peer creation/settings focus: frontend `125/125` and backend capability/plan `24/24` passed;
- current `git diff --check`: passed.
- latest focused composer/status/private-brief regression: `114/114` passed;
- latest complete frontend after the attributed compact-status fix: `104 files / 1004/1004` passed;
- latest TypeScript after the attributed compact-status fix: passed.
- latest complete backend Room discovery after the wave/approval/WorkDocument integration: `563/563` passed in `616.541s`;
- latest combined approval/execution-plan/Room/WorkDocument gate: `200/200` passed in `249.437s`;
- focused WorkDocument gate after the idempotent context-refresh fix: `15/15` passed;
- the original read-only snapshot regression test: `1/1` passed after the fix;
- current Python compile and `git diff --check`: passed;
- current full Room backend discovery with the waiting/grouped-question follow-up: `563/563` passed in `642.853s`;
- current complete frontend with the follow-up: `104 files / 1005/1005` passed;
- current TypeScript with the follow-up: passed;
- pre-cleanup backup: `5.0G` at `/Volumes/undo 4t/agent-workbench-backups/20260806-2349`; all Git bundles passed `git bundle verify`, the SQLite copy passed `PRAGMA integrity_check`, and `SHA256SUMS` records the critical artifacts.

Earlier regression counts remain historical evidence for commit `8461079f`; use
the latest numbers above for this follow-up. The complete frontend run still
prints pre-existing duplicate React-key warnings in the collaboration-profile
test, but all 1001 tests pass and this follow-up does not touch that surface.

### 4.1 User-reported bug and requirement ledger

The labels below are intentionally strict:

- **code + regression passed** means the current uncommitted patch has direct automated evidence;
- **recorded, fresh GUI required** means it remains a required acceptance item and must not be reported as fixed from source/tests alone;
- **not part of this patch** means preserve the requirement but do not silently broaden the scoped commit.

| User-visible requirement or observed bug | Checkpoint status | What the next session must verify |
| --- | --- | --- |
| `已交付` only shows a state and does not tell the user the result | **code + regression passed** | Terminal card headline contains the public result; expanded card contains deliverables/evidence and the recipient/handoff instead of stale activity text. |
| One companion Task appears as several avatar boxes / one reply has duplicate frames | **code + regression passed** | Same Task retry remains one card; a genuinely different Task for the same companion becomes a different card. |
| Old failed/stopped attempt overrides a new retry | **code + regression + independent review passed** | New retry remains active even after a delayed old failure/result event arrives. |
| Card says `执行中` after no work is running | **code + regression passed** | Motion and active label appear only for actual active state; terminal card is settled. |
| Cards cannot collapse, expand over each other, or are open by default | **default-collapse code passed; layout needs fresh GUI** | Every companion card starts collapsed, expands inside its own flow, and does not overlap the next card or the dependency graph. |
| `执行中` and important read/edit/write/bash operations have no visible motion/streaming feedback | **code path recorded; fresh GUI required** | Active border/progress treatment visibly updates; long edit/write and shell output stream before completion and settle afterward. |
| Tool detail shows only one line or generic `状态：已完成` | **code + regression passed** | Read shows multiple bounded numbered lines, edit/write shows a real diff/result, bash shows command/output/exit state, and each row is individually expandable. |
| Tool list contains duplicate implementations for the same read/edit/write/bash capability | **canonical requirement recorded; fresh runtime audit required** | Public Room exposes one canonical personalized renderer per base tool; aliases must normalize to it rather than create a second UI. |
| Todo appears in the wrong place, remains after 4/4, or disappears on failure | **code + regression passed** | Unfinished Todo is fixed at the card bottom across active/failure/stop; fully completed or abandoned Todo disappears. |
| `进度更新 • 引用来源 • 引用来源` meaningless placeholder cards | **recorded, fresh GUI required** | Empty citation shells are suppressed; real sources display useful labels/targets inside the owning activity card. |
| Timeline updates jump above older events instead of staying in time order | **code + chronology regression passed** | New activity appears at the bottom of the companion card; user answers appear immediately after the question they answer. |
| Answer or Start is accepted but the user sees no immediate feedback, or a floating status box covers content | **code + complete frontend regression passed; fresh GUI required** | Composer size stays unchanged; a compact spinner/status appears to the right of `@`, says the answer was received, and becomes “有新进展 · 回到最新” when the reader is above the tail. No standalone status card covers validation or conversation content. |
| Compact status only says `协作进行中`, so the user still cannot tell who is doing what | **code + focused regression passed; fresh GUI required** | The same toolbar area shows a short attributed action such as `澄·远：梳理需求`; concurrent work lists the active companions and compact task labels without enlarging the composer. |
| A private alignment brief containing `questionOptions` is shown as “选项没有准备完整” even though no question failed | **code + focused regression passed; fresh GUI required** | Internal orchestration briefs never become public objectives or false failures; the card falls back to a natural phase summary while real schema failures retain the recovery message. |
| Expanded work summary says `已更新 9 次` while the collapsed card stays on `正在继续任务`, shows task-check recovery copy as `要交付`, or calls active silence `正在等待` | **installed replay reproduced the late-status ordering case; follow-up focused regression passed** | The collapsed card prefers the newest meaningful public summary over later generic bookkeeping, refreshes its update count, hides recovery guidance from deliverables, and treats active silence as `仍在处理` unless a real wait exists. Full regression, reinstall and GUI replay remain. |
| Option selection submits immediately or free text appears before options | **code + regression passed; fresh GUI required** | Options show explanatory descriptions first; selection requires explicit confirmation; only “其他” opens free input. |
| Mechanical copy such as `需求对齐`, `已锁定`, `回答保留在下一条用户消息中`, protocol IDs, or JSON | **public-copy requirement recorded; fresh GUI required** | The companion speaks naturally from the user's perspective and exposes no internal protocol vocabulary. |
| Plan mixes Chinese with raw English schemas/camelCase or speaks from the system's perspective | **code + capability/Skill/frontend regression passed; fresh GUI required** | Main plan uses the user's language and describes what the user can do and see. Internal type/field inventories and unverified entry points stay in the WorkDocument or expandable technical details. |
| Clarification becomes a slow formal questionnaire or every question is forced into an option box | **code + skill/settlement regression passed; fresh GUI required** | Inspectable facts are inferred; at most one round asks 2–4 independent numbered questions in one natural-language prompt, while one mutually exclusive choice may use the option box. |
| “开始行动” fires before the user sees the split | **code + backend/frontend regression passed; fresh GUI required** | The card shows shared contracts, 1–4 vertical feature tasks, owners, dependencies/waves, write boundaries, integration and acceptance; nothing executes before the typed start action. |
| One feature is split horizontally across peer Agents | **code + skill regression passed; fresh full-auto GUI required** | Each user-visible feature has one end-to-end Room Agent owner; multiple peer Agents appear only for multiple independent features. |
| Static Reviewer/Researcher labels reduce a peer's ability | **code + backend regression passed; fresh full-auto GUI required** | Any active peer may own implementation; independent review is selected later from provenance, not a permanent low-capability role. |
| Four-person planning permanently keeps one companion idle as Reviewer or treats the Facilitator as a master | **code + Skill/plan regression passed; fresh full-auto GUI required** | All companions are peers and may own complete features, including the Facilitator. Review targets are assigned after integration from actual provenance; a peer may review another non-overlapping target but never its own implementation or integration. |
| Room creation or settings advertise permanent `主持/实现/调研/最终复核` capability classes | **code + focused regression passed; reinstall/fresh GUI required** | Creation shows every invited companion as an equal-capability peer. Stored routing preferences are described only as next-round opening preferences; the accepted plan and real provenance determine current responsibilities. |
| Requirement and execution context lives only in chat and is lost after compaction/handoff | **canonical document + all workflow Skills + WorkDocument regression passed; fresh full-auto GUI required** | After Start, one governed WorkDocument separately preserves user source/current requirements and execution plan/Todo/progress/evidence/failures/risks/handoff/next action. Later user changes and every owner's material progress update it; recovery reads it before source/runtime verification. |
| Complete workflow Skills are compressed to 6 KiB/120 lines | **canonical document + Skill regression passed** | Only compact routing cards are always loaded; the selected full Skill and its required references load progressively without the obsolete whole-file cap. |
| “Parallel” is only drawn in the graph and only one companion actually works | **backend policy/tests passed; fresh full-auto GUI required** | An approved multi-feature plan creates multiple real Tasks and at least two concurrently active companion cards with distinct work/results. |
| Four vertical Tasks exist but peer Tasks remain `排队中` while only the Facilitator runs | **installed commit `53089a7b`; existing Room recovered three peers into real running Dispatches** | Bounded child Tasks inherit the parent Room WorkItem while binding their own Session Todo. Database state and visible peer cards now prove concurrent execution; a new Room still needs to carry this through final delivery. |
| Plan labels features as wave 1/wave 2 but `room_collaborate` starts every peer together | **backend cause confirmed; wave-gate code + focused regression + full Room regression passed; install/fresh GUI pending** | Only current-wave features may be assigned. A later wave is rejected until earlier peer work is committed and every isolated worktree is integrated; the next `room_state` exposes current, ready and waiting features. A fresh installed Room must visibly keep wave 2 waiting and open it only after wave 1 integration. |
| Facilitator proposes final delivery while an active peer is still working | **code + settlement regression + full Room regression passed; fresh GUI required** | The Room visibly waits for the named peer, keeps the same task card alive, resumes the Facilitator after that peer's public delivery, and never emits a false final completion. |
| Stale legacy WorkItem says `执行中` after the latest Kernel Root is blocked or waiting | **code + frontend regression + full Room regression passed; fresh GUI required** | Header, context bar, task view, and compact status all use the newest Root generation; legacy WorkItem data is only a fallback when no Kernel Root exists. |
| Companion local error becomes a user blocker | **recovery contract and regression recorded; fresh full-auto GUI required** | Ordinary file/command/parameter/Provider errors show `正在恢复 / 已恢复` in expandable history and continue without user intervention. |
| Independent Luna approval runs on ordinary safe workspace writes | **requirement recorded; not part of this scoped UI patch** | In full-auto mode, ordinary bounded workspace operations proceed; Luna arbitration is reserved for genuinely dangerous operations. |
| Provider/model/token/cache shows misleading `未上报` failure copy | **recorded, fresh GUI required** | Real telemetry appears when supplied; absent optional telemetry is quiet and does not look like a task failure. |
| Dependency graph is visually large, sparse, overlapping, or treated as the workflow itself | **overview-only contract recorded; fresh GUI required** | Graph remains a compact overview; detailed Todo/tools/diff/handoff stay in the companion cards. |
| Conversation cold-load is slow and requires a `载入更早记录` button | **recent-two preload/automatic pagination requirement recorded; not proven by this patch** | Recent conversations are warm-preloaded and earlier history loads automatically on scroll without a manual button. |
| Room/session side panel is blank, redundant, or contains dead controls | **recorded in canonical requirements; not proven by this patch** | Mode-specific sidebars show only working Room or Session information; no blank Room panel and no dead buttons. |
| Worktree ownership/history is forgotten or successful worktrees accumulate | **ledger and cleanup contract recorded; install/GUI pending** | Each Task records creator, Room, requirement, branch/path, base and result hash; success cleans the physical worktree after integration, failures remain marked until explicitly resolved. |
| Runtime/debug data fills the system disk | **external live debug root configured; full storage migration not part of this patch** | New bounded debug context lands under `/Volumes/undo 4t/RagImeRuntime/debug-context/live`; do not raw-move an active database or App Support tree without an owner-aware migration. |

This table is an acceptance ledger, not a claim that every recorded item is already fixed. Only rows explicitly marked **code + regression passed** may be treated as implemented before the fresh installed GUI journey.

## 5. Exact current documentation and Skill correction scope

The runtime/UI fixes described by the old twelve-file scope are already
committed through `7de9cb1e`. Do not repeat or recreate that commit. The current
uncommitted correction injects the ratified full vision into these authority,
progressively loaded workflow, and deterministic evaluation files only:

1. `docs/agent/room-facilitated-workflow-requirements.md`
2. `docs/agent/room-production-acceptance-handoff.md`
3. `integrations/pi/skills/alignment-and-decision/SKILL.md`
4. `integrations/pi/skills/implementation-planning/SKILL.md`
5. `integrations/pi/skills/implementation-execution/SKILL.md`
6. `integrations/pi/skills/implementation-execution/references/execution-continuity-contract.md`
7. `integrations/pi/skills/quality-gate/SKILL.md`
8. `integrations/pi/skills/independent-review/SKILL.md`
9. `integrations/pi/skills/review-feedback-resolution/SKILL.md`
10. `integrations/pi/skills/structured-handoff/SKILL.md`
11. `eval/room-v2/task-effect-fixtures.v1.json`
12. `rag_ime/room_effect_eval.py`
13. `tests/test_agent_room_skills.py`
14. `tests/test_room_effect_eval.py`
15. `docs/agent/room-external-model-review-bundle-20260807.md` (ignored by
    `/docs/`; use `git add -f` only if this review artifact is intentionally
    committed)

These files define target behavior and regression guards. They do not implement
the new Kernel entities, outbox flow, frontend projection, intervention flow, or
distributed review runtime. Those require separate code changes and fresh
evidence after this contract correction.

Do not stage, reset, discard, clean, or overwrite these unrelated user/other-agent changes:

```text
README.md
md-link-check
rag_ime/md_link_check.py
rag_ime/tui.py
scripts/sync_codex_oauth_to_pi.py
tests/test_md_link_check.py
tests/test_sync_codex_oauth_to_pi.py
tests/test_tui.py
```

## 6. Exact next steps

1. Preserve the completed correction validation: `python3 -m unittest
   tests.test_agent_room_skills tests.test_room_effect_eval` passed `33/33`;
   JSON parsing and `git diff --check` passed. If these files change again,
   rerun those checks; do not mix unrelated dirty files.
2. Preserve the current live Room and resolve the existing
   `tests/test_duplicates.py` conflict only through the governed
   workspace/integration authority. Record whether its legacy flow can complete;
   do not treat it as proof of the new architecture.
3. Follow the phased plan in the authority document without a big-bang rewrite.
   The first reversible commits are: one canonical RoomScreenModel/selector;
   pure wait and settlement policies behind current facades; transactional
   state/event Outbox with per-Room projection isolation. Then materialize the
   approved PlanRevision as stable RoomTasks at Start, demote legacy WorkItems,
   add execution-time correction, scoped integration/review/final gates, and
   finally split the large UI files after lifecycle decisions have moved out.
4. Run deterministic state-machine E2E with retry, restart, SSE reconnect, one
   malformed old Room, dependency release, scoped integration, cross-review,
   repair/re-review, and exactly one final delivery.
5. Create a clean detached worktree at the verified commit, install with the
   full Xcode path
   `/Volumes/undo 4t/MyGlobalDownloads/DE9ECF0E-21E5-4AF3-90D2-7FD095158973/Xcode-beta.app/Contents/Developer`,
   audit every installed component, and run a
   new ordinary-language GUI Room through section 7. The current legacy Room
   remains migration/recovery evidence only.
6. After Room acceptance, create a new recoverable backup; audit and integrate
   valid Room, Knowledge, Memory, and Project Field/岛屿 work into the canonical
   product worktree; run full product verification.
7. Only then archive or delete proven obsolete/test/generated code, documents,
   Rooms, worktrees, old Pi/runtime generations, and installs. Retain the
   permanent logical Room/workspace ledger and recovery evidence.

## 7. Fresh GUI acceptance journey

Use only a natural user request. Never put Room policies, Agent allocation, question limits, testing instructions, or review rules into the test message. The current acceptance task remains the isolated TUI fixture; use:

```text
请把这个现在只能列出客户的程序做成真正好用的终端界面：我想在终端里浏览和搜索客户，新增或编辑资料，删除时先确认并能撤销，而且退出再打开后数据仍然保留。
```

Acceptance requires visible evidence of all of the following:

- at most one clarification round: either 2–4 independent numbered A/B/C questions, or one option-first question for one mutually exclusive choice;
- selecting an option does not submit it until explicit confirmation; “其他” alone opens free-form input;
- the confirmed answer appears as the next user message in chronological order;
- immediately after the answer or Start action, the unchanged composer toolbar shows a compact received/running state to the right of `@`; no separate status box covers the conversation, and scrolling away exposes “有新进展 · 回到最新” there;
- while work is active, that compact status names the companion and current user-facing work in a short phrase instead of only saying `协作进行中`;
- after the final necessary question, the companion summarizes the goal and shows the complete execution plan;
- even when clarification is unnecessary, the visible plan waits for explicit “开始行动”; no project-file read/write, command, test, install, or peer dispatch occurs before it;
- the plan uses the user's language and point of view, contains no raw English schema/camelCase inventory, and locks shared contracts plus each user-visible feature end-to-end to one of at most four same-capability Room Agents, with stable identity, dependency IDs/derived waves, write boundaries, scoped integration, acceptance, and document continuity;
- after “开始行动”, a multi-feature request becomes multiple real companion Tasks running concurrently, not one feature split by technical layer or one Task merely drawn as parallel;
- the receiving companion may own a complete feature like any peer; no companion is permanently held idle as a low-capability Reviewer, and later bounded review assignments follow real implementation/repair/integration provenance without self-review;
- the active WorkItem registers one governed WorkDocument; inspect it to confirm immutable/append-only user source, current requirements, accepted plan, Todo/progress/evidence/failures/risks/handoff/next action, and a material update from real execution progress;
- each companion has one Task card, active motion, recent action, expandable tool rows, bottom Todo, worktree/diff/artifact evidence, and a public handoff/delivery report;
- ordinary tool/command/Provider errors recover without asking the user to babysit them;
- execution-time user corrections append verbatim, affect only the necessary features, and visibly resume from a revised plan rather than being rejected by a locked composer;
- scoped integration and every required target's actually independent review happen before the current reporter's single final response;
- delivered cards are collapsed by default and show exactly what was delivered; completed Todo is absent;
- model/provider/token/cache fields show real reported values when available and do not show misleading placeholder failure copy;
- the dependency graph remains a compact overview and does not overlap or duplicate the detailed cards.
- Root, feature, wait, integration, review and final state update from one backend projection without refresh; one malformed old Room cannot freeze the active Room.

If the fresh Room fails any item, diagnose and fix the real backend/frontend owner, reinstall, and create another fresh Room. Do not patch a scenario-specific branch or let the frontend simulate orchestration.

## 8. Deferred work after Room acceptance

Do not start these before Room passes:

- Knowledge RAG integration handoff: `docs/agent/knowledge-agent-integration-handoff.md` (exact eight-file merge; held-out metrics MRR `0.250 -> 0.922`, Recall@10 `0.244 -> 0.989`, nDCG@10 `0.237 -> 0.927`);
- Project Field/island prototype handoff and session `019fcf5b-70ea-7ee0-a726-5a4bc9c40f29`;
- unrelated PAW-root `rag_ime/tui.py` and Markdown link checker files currently
  in the dirty worktree; these are not the isolated TUI acceptance fixture.

## 9. Direct resume prompt

```text
先完整阅读 /Volumes/undo 4t/git/learnA/.worktrees/paw-room-final-fix/docs/agent/room-production-acceptance-handoff.md、同目录的 room-facilitated-workflow-requirements.md，以及该 worktree 的 AGENTS.md/README。严格执行 handoff 第 0 节：第一条回复不要调用工具、运行命令、改文件、测试、提交、安装或分派伙伴；先用中文向我复述“当前做到哪里、现在仍有哪些问题、你理解的 Room 愿景、确认后准备做的第一步”，等我确认或纠正。确认后从第 6 节继续：先验证文档/Skill 修正，再通过受管 workspace/integration 流程处理当前真实 Room 的 tests/test_duplicates.py 冲突，不覆盖目标脏改动、不改数据库伪造状态。把当前 Room 当作旧流程恢复证据；随后严格按权威需求文档的渐进迁移计划推进：先统一 RoomScreenModel/selector，再提取纯 waiting/settlement policy，再做事务内事件 Outbox 和每 Room 隔离；然后实现 PlanRevision/稳定 RoomTask 依赖图、Start/WorkDocument/用户修正、范围级集成和互不自审复核/唯一最终交付，最后才拆巨型 UI 文件并删除已迁移旧分支。不要再增加与 Task/Dispatch/WorkItem 并列的 FeatureWorkItem 生命周期；现有 WorkItem 逐步降为兼容投影。所有伙伴平等并可实现完整功能，协调、集成、复核、汇报只是可追溯责任。新架构必须通过确定性状态机 E2E、干净安装和普通用户语言 GUI Room；之后先备份，再整合 Room、Knowledge、Memory、Project Field/岛屿并清理经证据确认废弃的文件、代码、Room、worktree、Pi/runtime 和文档。不要混入 handoff 中列出的无关脏文件。
```

## 10. 2026-08-07 08:53 CST latest correction

The installed/GUI journey at commit `5dd42bf1a65d163b076df4613b60a20e6a596750`
exposed three additional user-visible defects, so that journey is not final
acceptance evidence:

- the Facilitator's alignment and execution Dispatches shared one Task card,
  leaving the old card above `开始行动` and no new Facilitator execution card;
- current Task update time/Todo could be projected into a settled earlier phase;
- the broad customer-list test request advanced to a plan without a real user
  clarification round, and the dependency graph still repeated labels/arrows
  while omitting compact Todo progress.

Commit `07347fa3` fixed those owners directly and is included in installed
`7de9cb1e`:

- Room execution lanes carry an explicit execution phase derived from the typed
  `开始行动` chronology boundary. Same-phase retry Dispatches still coalesce;
  pre-Start alignment and post-Start execution do not.
- Only the newest phase receives current Task timestamps, Todo, workspace,
  subagent and delivery projections. Each card measures its own start/end time.
- Managed intake now treats unresolved data identity, import compatibility,
  merge/undo, retention and permission choices as material instead of silently
  defaulting a broad multi-feature request.
- Task graph nodes now contain task, owner, short state/action and authoritative
  `Todo x/y`; redundant `任务目标`/`当前状态` and arrow decoration are removed,
  with adaptive long-label styling.

Verification recorded for that follow-up:

- focused frontend: `5 files / 80 tests` passed;
- complete frontend: `104 files / 1009 tests` passed;
- complete Room backend: `564/564` passed in `883.591s`;
- TypeScript and `git diff --check` passed.

Those changes are committed, clean-installed, and component-audited through
`7de9cb1e`. The current live Room still has not completed its integration,
later-wave, distributed-review, and one-final-delivery journey, and the newly
ratified architecture contract in the authority document remains unimplemented.

The user's canonical consolidation scope is also explicit: all valid product
work in `Room`, `Knowledge`, `Memory`, and `Project Field/岛屿` must be preserved
and integrated. Provenance/conflict/generated-file review determines ordering
and cleanup, not whether any of those four domains may be dropped. Runtime
data, caches, superseded generated copies, and genuinely unconsumed obsolete
code remain excluded from source integration.

## 11. 2026-08-07 Pi Runtime SDK v2 与 Room 架构迁移当前进度

本 worktree 已接入并固定到已推送 Pi 提交
`3e2bac77319571ac0047a83529aae241db4b88a3`，当前精确边界如下：

- PAW 已识别 Continuation lease、RunScope、AgentSettledReceiptV2、
  ContextProvider、`session.settlement.get` 和 `session.await_settled` 能力。
- 普通聊天与 Room 的 Runtime 状态共用 exact Turn settlement；丢失
  `agent_settled` 事件时先按相同 `sessionId + turnId` 非阻塞查询，再有界
  等待，不再用 idle 推断新 Runtime 的完成状态。旧 `control_state` 路径
  仅保留给没有协商 V2 settlement 的 Runtime。
- 已有持久 transcript 的 Session 在同一 `externalSessionId`、同一文件上
  原位重开；身份或路径漂移会失败关闭。新 Session 若只有受管 transcript
  路径、文件尚未物化，则允许 Pi 在 Room 首次写入前于**同一路径**更新一次
  provisional ID；路径变化、空 ID、文件已存在或首次写入后的漂移仍失败
  关闭。成功后 binding 记录 runtime、settlement、context 和 migration history。
- 产品 Session ID 与 Pi transcript ID 不再错误地要求相同：外层 Turn
  receipt 固定产品 Session，内层 Agent receipt 固定原 transcript，二者
  通过 binding 显式关联。这是旧 Session 可原位迁移且 receipt 不被篡改的边界。
- Room Kernel 仍持有业务真相。Pi receipt 只进入 Runtime/聊天终态证据，
  不能越过 Room Commit、generation/capability、集成、复核或最终交付。
- managed build contract 已更新到 `3e2bac77`，并将
  `session.settlement.get`、`session.await_settled` 加入源码、manifest 和
  staged acceptance 门禁。
- Room 当前迁移已经完成单一前端 selector、纯策略、事务型 Outbox 与
  lease token fencing、Start 物化稳定 Task 图、同 Root 用户修正、受影响
  依赖闭包 PlanRevision、范围级集成/复核门禁，以及删除旧 `handoff`
  文本映射终态。仍存的 legacy/WorkItem 代码只可作为有真实消费者的兼容
  投影，后续按消费方迁移逐段删除，不能成为第二套业务真相。

已验证：

- Pi 源码 `npm run check`、Agent Core `34/34`、Coding Agent 相邻回归
  `64/64`、Runtime Host `14/14` 通过，并已推送到 `7155/pi`。
- Room 核心六组宽回归 `244/244` 通过；Pi exact settlement、Session 原位
  迁移、packager、managed manifest 与安全审计组合回归 `126/126` 通过。
- 前端单 worker 全量 `105 files / 1020 tests`、Room screen focused
  regression `8/8`、TypeScript、Python compile 与 `git diff --check` 通过。
  此前并发负载下唯一失败的复制提示计时断言在原用例与单 worker 全量中
  均通过，因此不修改无关 UI 代码。

已推送 PAW 基线 `9467dab0` 并与 Pi `3e2bac77` clean install；安装审计全部
对齐。首个 fresh Room 已证明消息即时出现和短状态实时显示，但在 Provider
确认前暴露了未物化 transcript 被误判为身份迁移的真实错误。本 follow-up
已修复该边界，Pi Runtime v2 `89/89` 与相邻 Session/build/install/kill-gate
`124/124` 通过。

仍未完成，禁止误报：提交并推送本 follow-up、从新提交重新原子安装、现有
Session 真实 transcript 原位恢复、普通聊天 GUI、同一 Room 中改为 TUI 的
完整用户旅程与最终愿景验收尚未完成。只有这些通过后才能创建本轮恢复备份，
再整合 Room、Knowledge、Memory、Project Field/岛屿并清理已证实废弃的
Room、worktree、Pi/runtime、代码和文档；RAG/Memory 正式整理与消融仍是
独立未完成工作。

## 12. 2026-08-07 current follow-up：全产品 Pi 消费方与同 Root 修正

本节取代第 11 节末尾的“下一步”状态，但保留其已提交基线证据。Pi follow-up
已提交并推送为 `30a802eed089f923633a99fab1428847dda20cc9`；PAW 当前工作树
完成了以下尚未提交、尚未安装的修正：

- Room Dispatch 恢复先按 `rootId + dedupeKey` 读取不可变 ContextLedger，
  已冻结的上下文只重放，不再因 Task/Requirement 后续变化重新渲染。
- 对齐、规划、执行、等待和阻塞阶段的普通用户修正都留在同一个有权威
  RequirementCatalog 的 Root。Start 前只更新 RequirementCatalog，不伪造
  WorkDocument；Start 后同时追加 RequirementAnchor 与同一 WorkDocument delta。
- pending clarification 的显式回答在同一事务里基于最新 catalog revision
  继续，先前普通修正不会再造成 `RoomContextConflict`。
- 无状态 completion 拥有独立顶层 RunScope；PAW 超时先按 `requestId` 调用
  `completion.cancel`，只有局部取消也失败时才退役共享 Host，避免误伤 Room、
  Memory 和其他 Session。
- Pi 的 `agent_settled` 观察者现在在 Agent run 退活后收到事件，同时保留
  settlement-emission fence，避免 receipt 已终态但 `isIdle()` 仍是假值。
- Memory model 每次成功都必须持久化精确 `pi.agent-settled.v2`；缺失、非
  completed 或仍有 operation 的 receipt 保持 resumable。默认正式租约为
  1200 秒，但延长时间不替代精确结算。
- 相同冻结 evidence packet 的 Memory 重试复用稳定 model run 与 Session；
  不完整指代、短命令和低质量片段不会进入 durable memory。正式 Luna 整理
  支持恢复已完成 receipt、延迟 verifier/semantic projection、最终 catalog 与
  semantic gate，以及内容寻址审计摘要；延迟模式不得误称 activation eligible。

本 follow-up 当前验证证据：

- Room 核心六组宽回归 `243/243`；
- Pi Runtime v2 调用方 `90/90`；
- Session/build/managed runtime/kill-gate 相邻回归 `136/136`；
- Memory executor `11/11`，owner curation `43/43`；
- Pi Agent Core `34/34`、Coding Agent `75/75`、Runtime Host `18/18`。

Pi 最终 `npm run check` 和 `diff --check` 已通过。仍需完成：PAW 最终单 worker
前端回归；限定提交并推送 PAW；从两个新提交干净安装并核对 manifest/source provenance；
随后在现有 TUI 验收 Room 中验证同 Root 修正、Start 后新执行框、真实并行、
Todo、工具详情、WorkDocument、交接、恢复、范围独立复核和唯一最终交付，
并验证普通 Session transcript 原位迁移。只有真实 GUI 全部通过后才备份和清理。
