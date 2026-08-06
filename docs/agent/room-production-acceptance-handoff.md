# Room production acceptance handoff

> as_of: 2026-08-06 21:34 CST
> status: collapsed-card priority fix `d30901ab` is committed, installed from clean worktree `/tmp/paw-room-meaningful-progress-install.6Z2yR7`, and component-audited green at full hash `d30901ab96debf76d2743bc8cde3ed938b5caf19`. Complete frontend regression is `104 files / 1005/1005`; TypeScript and `git diff --check` pass. Installed GUI replay shows the card now retains meaningful live progress and the natural-language Room correctly waited for Start. After Start, four vertical Tasks were created, but three peers remained queued because child Todo authority rejected the parent WorkItem lineage. The single-file `agent_sessions.py` fix is proven by the same focused test failing on clean `d30901ab` and passing in the implementation worktree; the complete backend Room suite passes `561/561` in `884.261s`. Commit, reinstall and GUI recovery remain.
> canonical worktree: `/Volumes/undo 4t/git/learnA/.worktrees/paw-room-final-fix`
> branch: `codex/room-production-acceptance-final`
> current source commit: `021c97807b58f885e6c3b047a38d40446c7804a4` (this checkpoint document is maintained in a follow-up commit)

## 0. Mandatory takeover gate: do not start by running commands

This checkpoint is being handed to a new conversation because the previous conversation became too long. The first response in the new conversation must **not** run a command, edit a file, start tests, stage/commit, install, launch a Room, or delegate work.

The new owner must first reply to the user in natural Chinese with exactly these four parts:

1. **当前做到哪里** — distinguish implemented/tested work from installed/GUI-verified work;
2. **现在仍有哪些问题** — restate the open product and acceptance gaps below;
3. **我理解的 Room 愿景** — restate the user's non-negotiable requirements below;
4. **确认后第一步** — name only the first bounded action it proposes.

Then wait for the user to confirm or correct that understanding. This is a handoff-specific takeover gate, not a product rule that every clear Room request must be clarified. After the user confirms, continue autonomously until a true user decision/permission/credential blocker occurs.

### Current problems at the handoff moment

- The latest installed Room source is `021c97807b58f885e6c3b047a38d40446c7804a4`, installed from clean worktree `/tmp/paw-room-live-progress-install.XitWK5`. Its exact component audit is green and the managed Pi runtime is `pi-0.80.7-98cfe6a3a0a4-raghost-727365f27d` from source `98cfe6a3a0a420ac6de4f85153c55fbc8809b845`.
- A fresh creation modal at that installed commit shows all four companions as `已邀请` and says they have equal capability; the earlier permanent `主持/实现/调研/最终复核` presentation defect is fixed in the installed GUI.
- The earlier internal-instruction GUI attempt remains invalid acceptance evidence and must never be reused.
- The valid natural-language run used only this ordinary product request: `我想把这个小客户目录做得更好用：可以批量导入 CSV 客户并先看看每一行有没有问题；能按邮箱后缀筛选；发现重复客户时能先对比、合并，合并错了还能撤销；还能查看每位客户是谁在什么时候改过什么。`
- That run verified the compact attributed state, natural Chinese vertical plan, four equal peers, and the no-work-before-Start gate. Commit `021c9780` projects live summary/update counts into the collapsed header, suppresses task-check recovery copy from deliverables, and distinguishes active silence from a real wait.
- Installed replay then exposed a narrower ordering defect: after the nine-update `reasoning_summary`, a later generic `participant_status` event (“完成了一步”) became the collapsed-card focus, so the header regressed to `澄·远 正在继续任务`. The current follow-up excludes generic participant bookkeeping when a meaningful public work summary exists. Its red-capable fixture reproduces the real ordering; focused Room tests and TypeScript pass.
- That follow-up is now installed commit `d30901ab`. The same Room shows a meaningful current headline, update count, Todo and “有新进展 · 回到最新” instead of the generic card reported by the user.
- Start produced four real vertical Tasks in the task view, but only the Facilitator ran; the other three stayed queued. Production logs show `_active_room_todo_lineage` rejecting bounded child Tasks because their shared parent WorkItem remains owned by the Facilitator. The existing `agent_sessions.py` change accepts a `parentTaskId` child while retaining exact Room/root/task/session/participant checks. The existing two-peer nested-lineage regression fails on clean `d30901ab` with the production exception and passes with this change.
- No fresh full-auto GUI Room has completed the required end-to-end path after this follow-up. The installed/Web UI must still prove the compact composer status, user-language planning, governed requirement/execution document, clarification, real parallel Tasks, peer review without self-review, recovery, integration, and a single final delivery.
- Several user-reported requirements remain GUI-only acceptance items. The next owner must use the ledger in section 4.1 and may only call a row fixed after its stated evidence boundary passes.
- Existing screenshots and old Rooms still contain known failures such as stale `执行中`, duplicate/overlapping cards, weak tool results, meaningless citation placeholders, missing delivery reports, or fake visual parallelism. They are reproduction evidence, not proof of the current source.
- Both Room authority documents are already tracked. Stage their existing changes explicitly; do not use a broad forced add for the ignored `/docs/` tree.
- Installation must come from a clean detached worktree at the new commit. Do not install the dirty source tree or overwrite unrelated Pi/product changes.

### User's non-negotiable Room vision

- The user enters one natural-language goal; the default companion receives it, while `@伙伴` may change the receiver.
- If decision-changing details are genuinely missing, infer inspectable facts first and ask at most one clarification round. Two to four independent questions may be grouped with numbered A/B/C choices and answered compactly; a single mutually exclusive choice uses the option box. Selecting an option still requires confirmation; only “其他” opens free text. Confirmed answers stay inside the asking companion's chronological card.
- Before every implementation starts, show the understood goal, locked shared contracts, one to four vertical feature tasks with owners/dependencies/waves/write boundaries, integration, and acceptance. No companion dispatch, write, or test may begin until the user clicks “开始行动”.
- Start-up uses Claude-style progressive disclosure: only compact routing cards are always present; the exact full Skill loads for the current stage, and linked references/scripts/examples load only when needed. Do not compress a complete Skill to a uniform 6 KiB/120-line cap.
- Split only by user-visible feature after shared contracts are locked. One feature has one Room Agent owner end-to-end; never split one feature horizontally into frontend/backend/parser/test work. At most four peer Room Agents run, in dependency waves rather than fake roster-filling.
- Every active Room companion uses the same model and complete work capability. `collaborationRole` is only current responsibility, never a permanent capability tier; the Facilitator may also own a complete feature. Do not reserve one companion as an idle or lower-capability Reviewer. After integration, use actual authorship/integration provenance to assign bounded review targets so nobody reviews its own work.
- After Start, one governed Markdown WorkDocument keeps two separate logical sections: immutable/append-only user source plus current confirmed requirements, and accepted plan plus Todo/progress/evidence/failures/risks/handoff/next action. Every stage updates it from new user requirements and its own material progress; recovery and handoff read it before verifying source and runtime.
- A decomposable multi-feature task must create multiple real companion Tasks in parallel. The graph is only a compact overview; it cannot substitute for actual concurrent work.
- One companion Task is one continuous card. Retries stay in that card; a separate Task gets a separate card. Do not duplicate avatars or split one reply across miscellaneous boxes.
- Every companion message, question, confirmed answer, tool, progress item, and result stays inside that companion's large card, with nested cards for detail. Cards use authoritative creation time from oldest to newest; alignment ends its card before implementation cards begin.
- Active work has restrained but obvious motion and live updates. Recent actions remain in time order at the bottom. Important long-running read/edit/write/bash operations stream visibly and are individually expandable.
- The unchanged composer toolbar uses its available space to name who is doing what in a short phrase, for example `澄·远：梳理需求` or `澄·初：批量导入`. A generic `协作进行中` label is insufficient.
- Each card exposes the companion's current public work summary, real Todo, tools, worktree, files/diff, tests, artifacts, recovery, and handoff from the same source at different densities. Todo stays at the bottom while unfinished and disappears when fully settled.
- When a companion finishes, `已交付`/`已转交` must immediately become a user-facing report of what changed, what was produced, verification, risks, and who receives it. It must not leave stale `正在处理` text or a bare state label.
- Ordinary code, command, parameter, and transient Provider failures recover inside the Room. The Facilitator retries, switches model, redistributes, or serializes work without asking the user to babysit local failures.
- Luna independent approval is rare and reserved for genuinely dangerous operations. Safe bounded workspace reads/writes/tests should not incur a review round merely for ceremony.
- Integration and a genuinely independent review happen before the Facilitator gives one final answer. Partners keep distinct personalities and role-specific voices; they do not repeat the same Facilitator-style final text.
- Public UI uses ordinary user language, not `Kernel`, `Root`, `Dispatch`, `Task`, `AC`, `Receipt ID`, protocol JSON, `需求对齐`, `已锁定`, or “回答保留在下一条消息”. Missing optional telemetry stays quiet rather than looking like a failure.
- Successful physical worktrees are cleaned only after integration while a permanent Room/requirement/owner/base/result ledger remains. Failed, blocked, cancelled, conflicting, or orphaned worktrees remain visibly marked until explicit resolution.
- Runtime/debug/conversation data should prefer the configured external-volume owner and bounded retention. Do not blindly move a live database or App Support directory without an owner-aware migration.

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
| Clarification becomes a slow formal questionnaire | **code + skill regression passed; fresh GUI required** | Inspectable facts are inferred; at most one round asks 2–4 independent numbered questions, or one option box for one mutually exclusive choice. |
| “开始行动” fires before the user sees the split | **code + backend/frontend regression passed; fresh GUI required** | The card shows shared contracts, 1–4 vertical feature tasks, owners, dependencies/waves, write boundaries, integration and acceptance; nothing executes before the typed start action. |
| One feature is split horizontally across peer Agents | **code + skill regression passed; fresh full-auto GUI required** | Each user-visible feature has one end-to-end Room Agent owner; multiple peer Agents appear only for multiple independent features. |
| Static Reviewer/Researcher labels reduce a peer's ability | **code + backend regression passed; fresh full-auto GUI required** | Any active peer may own implementation; independent review is selected later from provenance, not a permanent low-capability role. |
| Four-person planning permanently keeps one companion idle as Reviewer or treats the Facilitator as a master | **code + Skill/plan regression passed; fresh full-auto GUI required** | All companions are peers and may own complete features, including the Facilitator. Review targets are assigned after integration from actual provenance; a peer may review another non-overlapping target but never its own implementation or integration. |
| Room creation or settings advertise permanent `主持/实现/调研/最终复核` capability classes | **code + focused regression passed; reinstall/fresh GUI required** | Creation shows every invited companion as an equal-capability peer. Stored routing preferences are described only as next-round opening preferences; the accepted plan and real provenance determine current responsibilities. |
| Requirement and execution context lives only in chat and is lost after compaction/handoff | **canonical document + all workflow Skills + WorkDocument regression passed; fresh full-auto GUI required** | After Start, one governed WorkDocument separately preserves user source/current requirements and execution plan/Todo/progress/evidence/failures/risks/handoff/next action. Later user changes and every owner's material progress update it; recovery reads it before source/runtime verification. |
| Complete workflow Skills are compressed to 6 KiB/120 lines | **canonical document + Skill regression passed** | Only compact routing cards are always loaded; the selected full Skill and its required references load progressively without the obsolete whole-file cap. |
| “Parallel” is only drawn in the graph and only one companion actually works | **backend policy/tests passed; fresh full-auto GUI required** | An approved multi-feature plan creates multiple real Tasks and at least two concurrently active companion cards with distinct work/results. |
| Four vertical Tasks exist but peer Tasks remain `排队中` while only the Facilitator runs | **installed GUI and gateway log reproduced; focused red/green plus complete backend `561/561` passed** | Bounded child Tasks may inherit the parent Room WorkItem and still bind their own Session Todo, so the worker starts independent peers concurrently. Reinstall and GUI recovery remain. |
| Companion local error becomes a user blocker | **recovery contract and regression recorded; fresh full-auto GUI required** | Ordinary file/command/parameter/Provider errors show `正在恢复 / 已恢复` in expandable history and continue without user intervention. |
| Independent Luna approval runs on ordinary safe workspace writes | **requirement recorded; not part of this scoped UI patch** | In full-auto mode, ordinary bounded workspace operations proceed; Luna arbitration is reserved for genuinely dangerous operations. |
| Provider/model/token/cache shows misleading `未上报` failure copy | **recorded, fresh GUI required** | Real telemetry appears when supplied; absent optional telemetry is quiet and does not look like a task failure. |
| Dependency graph is visually large, sparse, overlapping, or treated as the workflow itself | **overview-only contract recorded; fresh GUI required** | Graph remains a compact overview; detailed Todo/tools/diff/handoff stay in the companion cards. |
| Conversation cold-load is slow and requires a `载入更早记录` button | **recent-two preload/automatic pagination requirement recorded; not proven by this patch** | Recent conversations are warm-preloaded and earlier history loads automatically on scroll without a manual button. |
| Room/session side panel is blank, redundant, or contains dead controls | **recorded in canonical requirements; not proven by this patch** | Mode-specific sidebars show only working Room or Session information; no blank Room panel and no dead buttons. |
| Worktree ownership/history is forgotten or successful worktrees accumulate | **ledger and cleanup contract recorded; install/GUI pending** | Each Task records creator, Room, requirement, branch/path, base and result hash; success cleans the physical worktree after integration, failures remain marked until explicitly resolved. |
| Runtime/debug data fills the system disk | **external live debug root configured; full storage migration not part of this patch** | New bounded debug context lands under `/Volumes/undo 4t/RagImeRuntime/debug-context/live`; do not raw-move an active database or App Support tree without an owner-aware migration. |

This table is an acceptance ledger, not a claim that every recorded item is already fixed. Only rows explicitly marked **code + regression passed** may be treated as implemented before the fresh installed GUI journey.

## 5. Exact residual-fix commit scope

The compact attributed-status/private-brief follow-up is commit `f6e41175`; collapsed-progress projection is `021c9780`; meaningful live-summary priority is installed commit `d30901ab`. The current child Todo-lineage follow-up must contain exactly these two files:

1. `rag_ime/agent_sessions.py`
2. `docs/agent/room-production-acceptance-handoff.md`

Do not stage, reset, discard, clean, or overwrite these unrelated user/other-agent changes:

```text
README.md
rag_ime/agent_approval_model.py
rag_ime/agent_execution_policy.py
rag_ime/agent_room_settlement.py
rag_ime/agent_workspace.py
tests/test_agent_execution_policy.py
tests/test_agent_room_settlement.py
md-link-check
rag_ime/md_link_check.py
rag_ime/tui.py
scripts/sync_codex_oauth_to_pi.py
tests/test_md_link_check.py
tests/test_sync_codex_oauth_to_pi.py
tests/test_tui.py
```

## 6. Exact next steps

1. Run the focused two-peer nested-lineage regression plus the complete backend Room suite and `git diff --check` for the current two-file follow-up.
2. Stage only the two files in section 5 and commit them as `fix(room): start bounded peer todos`.
3. Create a clean detached worktree at that commit. Do not install from this dirty implementation worktree.
4. From the clean worktree, run `scripts/install_product_stack.sh --include-pi --pi-worktree '/Volumes/undo 4t/git/learnA/.worktrees/pi-room-runtime-98cfe6a3'` with the configured Xcode beta developer directory.
5. Run `scripts/check_installed_product_components.py --require-current` and record exact component evidence for the new commit.
6. Reload the existing natural-language Room and verify the three queued child Tasks recover into running companion work without a manual user retry; confirm at least two peers are active concurrently and their dialogue cards appear.
7. Continue that Room through the remaining full-auto GUI journey below. Hidden APIs and browser internals may diagnose failures but do not replace the visible journey.
8. Only after the fresh Room genuinely completes may the temporary physical install worktree be cleaned. Keep the permanent Room/requirement/owner/base/result ledger required by the product contract.

## 7. Fresh GUI acceptance journey

Use only a natural user request. Never put Room policies, Agent allocation, question limits, testing instructions, or review rules into the test message. A valid multi-feature example is:

```text
我想让客户列表更好用，能一次导入很多客户，也能更容易找到并处理重复的人，还想知道谁改过客户资料。
```

Acceptance requires visible evidence of all of the following:

- at most one clarification round: either 2–4 independent numbered A/B/C questions, or one option-first question for one mutually exclusive choice;
- selecting an option does not submit it until explicit confirmation; “其他” alone opens free-form input;
- the confirmed answer appears as the next user message in chronological order;
- immediately after the answer or Start action, the unchanged composer toolbar shows a compact received/running state to the right of `@`; no separate status box covers the conversation, and scrolling away exposes “有新进展 · 回到最新” there;
- while work is active, that compact status names the companion and current user-facing work in a short phrase instead of only saying `协作进行中`;
- after the final necessary question, the companion summarizes the goal and shows the complete execution plan;
- even when clarification is unnecessary, the visible plan waits for explicit “开始行动”; no write, test, or peer dispatch occurs before it;
- the plan uses the user's language and point of view, contains no raw English schema/camelCase inventory, and locks shared contracts plus each user-visible feature end-to-end to one of at most four same-capability Room Agents, with dependencies/waves, write boundaries, integration, acceptance, and document continuity;
- after “开始行动”, a multi-feature request becomes multiple real companion Tasks running concurrently, not one feature split by technical layer or one Task merely drawn as parallel;
- the Facilitator may own a complete feature like any peer; no companion is permanently held idle as a low-capability Reviewer, and later bounded review assignments follow real provenance without self-review;
- the active WorkItem registers one governed WorkDocument; inspect it to confirm immutable/append-only user source, current requirements, accepted plan, Todo/progress/evidence/failures/risks/handoff/next action, and a material update from real execution progress;
- each companion has one Task card, active motion, recent action, expandable tool rows, bottom Todo, worktree/diff/artifact evidence, and a public handoff/delivery report;
- ordinary tool/command/Provider errors recover without asking the user to babysit them;
- integration and an actually independent review happen before the Facilitator's single final response;
- delivered cards are collapsed by default and show exactly what was delivered; completed Todo is absent;
- model/provider/token/cache fields show real reported values when available and do not show misleading placeholder failure copy;
- the dependency graph remains a compact overview and does not overlap or duplicate the detailed cards.

If the fresh Room fails any item, diagnose and fix the real backend/frontend owner, reinstall, and create another fresh Room. Do not patch a scenario-specific branch or let the frontend simulate orchestration.

## 8. Deferred work after Room acceptance

Do not start these before Room passes:

- Knowledge RAG integration handoff: `docs/agent/knowledge-agent-integration-handoff.md` (exact eight-file merge; held-out metrics MRR `0.250 -> 0.922`, Recall@10 `0.244 -> 0.989`, nDCG@10 `0.237 -> 0.927`);
- Project Field/island prototype handoff and session `019fcf5b-70ea-7ee0-a726-5a4bc9c40f29`;
- unrelated TUI and Markdown link checker files currently in the dirty worktree.

## 9. Direct resume prompt

```text
先完整阅读 /Volumes/undo 4t/git/learnA/.worktrees/paw-room-final-fix/docs/agent/room-production-acceptance-handoff.md、同目录的 room-facilitated-workflow-requirements.md，以及该 worktree 的 AGENTS.md/README。严格执行 handoff 第 0 节：第一条回复不要调用工具、运行命令、改文件、测试、提交、安装或分派伙伴；先用中文向我复述“当前做到哪里、现在仍有哪些问题、你理解的 Room 愿景、确认后准备做的第一步”，等我确认或纠正。确认后才继续第 6 节：只提交列出的二十二个文件，从新提交创建干净 worktree，安装当前构建，并在真实前端用全自动 Room 完成第 7 节的紧凑输入栏状态、成组澄清、用户语言纵向分工、显式开始批准、对等伙伴并行、受管 WorkDocument 持续更新、工具/Todo/交接/无自审复核闭环。不要混入列出的其他脏文件，也不要在 Room 通过前开始 Knowledge 或岛屿任务。
```
