# Room production acceptance handoff

> as_of: 2026-08-06 17:21 CST
> status: implementation and expanded automated regression passed; scoped commit, clean install, and fresh real GUI Room acceptance remain
> canonical worktree: `/Volumes/undo 4t/git/learnA/.worktrees/paw-room-final-fix`
> branch: `codex/room-production-acceptance-final`
> current HEAD: `7cf08c66a5697d0675b98533145bc8364eebbd3d`

## 0. Mandatory takeover gate: do not start by running commands

This checkpoint is being handed to a new conversation because the previous conversation became too long. The first response in the new conversation must **not** run a command, edit a file, start tests, stage/commit, install, launch a Room, or delegate work.

The new owner must first reply to the user in natural Chinese with exactly these four parts:

1. **当前做到哪里** — distinguish implemented/tested work from installed/GUI-verified work;
2. **现在仍有哪些问题** — restate the open product and acceptance gaps below;
3. **我理解的 Room 愿景** — restate the user's non-negotiable requirements below;
4. **确认后第一步** — name only the first bounded action it proposes.

Then wait for the user to confirm or correct that understanding. This is a handoff-specific takeover gate, not a product rule that every clear Room request must be clarified. After the user confirms, continue autonomously until a true user decision/permission/credential blocker occurs.

### Current problems at the handoff moment

- The expanded Room patch is still **uncommitted** inside a dirty worktree. Twenty-six owned files are listed in section 5; the remaining dirty files belong to the user or other work and must not enter the commit.
- Automated evidence is green, but the currently installed `RagImeControl.app` has **not** been proven to contain this final patch. Source tests are not installed-product acceptance.
- No fresh full-auto GUI Room has completed the required end-to-end path after this final patch. The installed/Web UI must still prove clarification, real parallel Tasks, per-companion cards, recovery, integration, independent review, and a single final delivery.
- Several user-reported requirements remain GUI-only acceptance items. The next owner must use the ledger in section 4.1 and may only call a row fixed after its stated evidence boundary passes.
- Existing screenshots and old Rooms still contain known failures such as stale `执行中`, duplicate/overlapping cards, weak tool results, meaningless citation placeholders, missing delivery reports, or fake visual parallelism. They are reproduction evidence, not proof of the current source.
- The handoff file itself is ignored by the repository's `/docs/` rule and therefore needs `git add -f` if included in the scoped commit.
- Installation must come from a clean detached worktree at the new commit. Do not install the dirty source tree or overwrite unrelated Pi/product changes.

### User's non-negotiable Room vision

- The user enters one natural-language goal; the default companion receives it, while `@伙伴` may change the receiver.
- If decision-changing details are genuinely missing, infer inspectable facts first and ask at most one clarification round. Two to four independent questions may be grouped with numbered A/B/C choices and answered compactly; a single mutually exclusive choice uses the option box. Selecting an option still requires confirmation; only “其他” opens free text. Confirmed answers stay inside the asking companion's chronological card.
- Before every implementation starts, show the understood goal, locked shared contracts, one to four vertical feature tasks with owners/dependencies/waves/write boundaries, integration, and acceptance. No companion dispatch, write, or test may begin until the user clicks “开始行动”.
- Split only by user-visible feature after shared contracts are locked. One feature has one Room Agent owner end-to-end; never split one feature horizontally into frontend/backend/parser/test work. At most four peer Room Agents run, in dependency waves rather than fake roster-filling.
- Every active Room companion uses the same model and complete work capability. `collaborationRole` is only current responsibility, never a permanent capability tier; bounded read-only investigation belongs to the feature owner's subagent, not a peer Room role.
- A decomposable multi-feature task must create multiple real companion Tasks in parallel. The graph is only a compact overview; it cannot substitute for actual concurrent work.
- One companion Task is one continuous card. Retries stay in that card; a separate Task gets a separate card. Do not duplicate avatars or split one reply across miscellaneous boxes.
- Every companion message, question, confirmed answer, tool, progress item, and result stays inside that companion's large card, with nested cards for detail. Cards use authoritative creation time from oldest to newest; alignment ends its card before implementation cards begin.
- Active work has restrained but obvious motion and live updates. Recent actions remain in time order at the bottom. Important long-running read/edit/write/bash operations stream visibly and are individually expandable.
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

## 2. Product behavior now implemented in the uncommitted Room patch

- One companion + one Task is one card. Retries of the same Task remain in that card; different Tasks assigned to the same companion remain separate cards.
- The current retry is selected from a deterministic total event order. Legacy events cannot reclaim a card after an authoritative sequenced retry, even when an old result arrives later by timestamp.
- Active cards animate only while real work is active. Terminal cards settle, default to collapsed, and no longer display stale running/waiting copy.
- A terminal `work_result` or `handoff` replaces the card headline with the companion's public delivery report. Expanded details show files, diff totals, verification, risks, and handoff evidence when available.
- Todo stays at the bottom of a companion card while any item is unfinished, including after failure, stop, or an incomplete terminal result. It disappears only after every item is completed or abandoned.
- Read/edit/write/bash activity remains chronologically inside the same companion card. Tool rows are expandable, stream while running, and preserve bounded multiline output/diff previews instead of rendering only one line.
- Public copy avoids protocol terms and mechanical “需求对齐” language. Ordinary failures recover inside the Room; users are interrupted only for a real decision, permission, credential, or proven unrecoverable block.
- Questions and confirmed answers render inside the asking companion's card; the answer appears immediately, followed by persistent live status and a “回到最新进度” action when the user has scrolled away.
- `room_define` now requires a visible one-to-four-item execution plan. It locks shared contracts, vertical feature owners, dependency waves, write boundaries, integration, and acceptance; even a clear request waits for the typed “开始行动” authorization before dispatch, writes, or tests.
- All active peer role labels are capability-neutral. Parallel work requirements derive from the approved feature plan rather than the Room's routing label or a static Reviewer/Researcher class.
- Automatic Session Todo initialization recognizes both immediate legacy execution and the approved planned dispatch released after “开始行动”; Todo wording no longer changes implementation capability from a static role label.
- Durable workflow skills preserve the immutable user source, visible plan, execution evidence, quality gate, and independent review across compaction or handoff.

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

- focused plan/card/order tests: `3 files, 39/39` passed;
- complete Room frontend suite after the expanded interaction patch: `22 files, 292/292` passed;
- TypeScript after the final ordering fix: `pnpm exec tsc -b --pretty false` passed;
- complete frontend suite before the final isolated ordering fix: `104 files, 994/994` passed with `--maxWorkers=4`;
- isolated rerun for two first-pass timing flakes: `18/18` passed;
- Python Kernel service regression: `101/101` passed;
- Python Room capability/definition/skill/routing/settlement/policy regression: `158/158` passed; emitted `ResourceWarning`s and the injected `Pi host exited` path were non-fatal test-path output;
- production web build: passed before the final TypeScript-only ordering fix;
- import-boundary check: passed;
- route-ownership check: passed (`91 dispatched`, `205 declared`, `40/40 undeclared`);
- current `git diff --check`: passed.

Do not reinterpret the earlier unconstrained full frontend run (`992/994`) as a product failure: its two timing failures immediately passed together (`18/18`), and the bounded-worker full rerun passed `994/994`.

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
| Option selection submits immediately or free text appears before options | **code + regression passed; fresh GUI required** | Options show explanatory descriptions first; selection requires explicit confirmation; only “其他” opens free input. |
| Mechanical copy such as `需求对齐`, `已锁定`, `回答保留在下一条用户消息中`, protocol IDs, or JSON | **public-copy requirement recorded; fresh GUI required** | The companion speaks naturally from the user's perspective and exposes no internal protocol vocabulary. |
| Clarification becomes a slow formal questionnaire | **code + skill regression passed; fresh GUI required** | Inspectable facts are inferred; at most one round asks 2–4 independent numbered questions, or one option box for one mutually exclusive choice. |
| “开始行动” fires before the user sees the split | **code + backend/frontend regression passed; fresh GUI required** | The card shows shared contracts, 1–4 vertical feature tasks, owners, dependencies/waves, write boundaries, integration and acceptance; nothing executes before the typed start action. |
| One feature is split horizontally across peer Agents | **code + skill regression passed; fresh full-auto GUI required** | Each user-visible feature has one end-to-end Room Agent owner; multiple peer Agents appear only for multiple independent features. |
| Static Reviewer/Researcher labels reduce a peer's ability | **code + backend regression passed; fresh full-auto GUI required** | Any active peer may own implementation; independent review is selected later from provenance, not a permanent low-capability role. |
| “Parallel” is only drawn in the graph and only one companion actually works | **backend policy/tests passed; fresh full-auto GUI required** | An approved multi-feature plan creates multiple real Tasks and at least two concurrently active companion cards with distinct work/results. |
| Companion local error becomes a user blocker | **recovery contract and regression recorded; fresh full-auto GUI required** | Ordinary file/command/parameter/Provider errors show `正在恢复 / 已恢复` in expandable history and continue without user intervention. |
| Independent Luna approval runs on ordinary safe workspace writes | **requirement recorded; not part of this scoped UI patch** | In full-auto mode, ordinary bounded workspace operations proceed; Luna arbitration is reserved for genuinely dangerous operations. |
| Provider/model/token/cache shows misleading `未上报` failure copy | **recorded, fresh GUI required** | Real telemetry appears when supplied; absent optional telemetry is quiet and does not look like a task failure. |
| Dependency graph is visually large, sparse, overlapping, or treated as the workflow itself | **overview-only contract recorded; fresh GUI required** | Graph remains a compact overview; detailed Todo/tools/diff/handoff stay in the companion cards. |
| Conversation cold-load is slow and requires a `载入更早记录` button | **recent-two preload/automatic pagination requirement recorded; not proven by this patch** | Recent conversations are warm-preloaded and earlier history loads automatically on scroll without a manual button. |
| Room/session side panel is blank, redundant, or contains dead controls | **recorded in canonical requirements; not proven by this patch** | Mode-specific sidebars show only working Room or Session information; no blank Room panel and no dead buttons. |
| Worktree ownership/history is forgotten or successful worktrees accumulate | **ledger and cleanup contract recorded; install/GUI pending** | Each Task records creator, Room, requirement, branch/path, base and result hash; success cleans the physical worktree after integration, failures remain marked until explicitly resolved. |
| Runtime/debug data fills the system disk | **external live debug root configured; full storage migration not part of this patch** | New bounded debug context lands under `/Volumes/undo 4t/RagImeRuntime/debug-context/live`; do not raw-move an active database or App Support tree without an owner-aware migration. |

This table is an acceptance ledger, not a claim that every recorded item is already fixed. Only rows explicitly marked **code + regression passed** may be treated as implemented before the fresh installed GUI journey.

## 5. Exact intended commit scope

Stage only these 26 files:

1. `control-center-web/src/features/rooms/RoomQuestionDialog.tsx`
2. `control-center-web/src/features/rooms/index.tsx`
3. `control-center-web/src/features/rooms/rooms-feature.test.tsx`
4. `control-center-web/src/features/rooms/rooms.css`
5. `control-center-web/src/features/rooms/runtime/room-execution-lanes.test.ts`
6. `control-center-web/src/features/rooms/runtime/room-execution-lanes.ts`
7. `control-center-web/src/features/rooms/timeline/RoomStartActionGate.test.tsx`
8. `control-center-web/src/features/rooms/timeline/RoomStartActionGate.tsx`
9. `control-center-web/src/features/rooms/timeline/RoomTurn.chronology.test.tsx`
10. `control-center-web/src/features/rooms/timeline/RoomTurn.tsx`
11. `integrations/pi/skills/alignment-and-decision/SKILL.md`
12. `integrations/pi/skills/implementation-execution/SKILL.md`
13. `integrations/pi/skills/implementation-planning/SKILL.md`
14. `rag_ime/agent_definitions.py`
15. `rag_ime/agent_room_application.py`
16. `rag_ime/agent_room_capabilities.py`
17. `rag_ime/agent_room_kernel.py`
18. `rag_ime/agent_room_kernel_application.py`
19. `rag_ime/agent_room_routing.py`
20. `rag_ime/agent_service.py`
21. `tests/test_agent_definitions.py`
22. `tests/test_agent_room_capabilities.py`
23. `tests/test_agent_room_kernel_service.py`
24. `tests/test_agent_room_skills.py`
25. `tests/test_agent_rooms.py`
26. `docs/agent/room-production-acceptance-handoff.md`

Do not stage, reset, discard, clean, or overwrite these unrelated user/other-agent changes:

```text
README.md
rag_ime/agent_approval_model.py
rag_ime/agent_execution_policy.py
rag_ime/agent_room_settlement.py
rag_ime/agent_sessions.py
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

1. Read this file, the canonical requirements, and the worktree `AGENTS.md`/README before acting.
2. Recheck `git status --short` and `git diff --check`.
3. Stage the 26 explicit files above with path-qualified `git add`; this repository ignores new files under `/docs/`, so add this handoff itself with `git add -f docs/agent/room-production-acceptance-handoff.md`. Verify `git diff --cached --name-only` is exactly that list and run `git diff --cached --check`.
4. Commit the scoped patch. Suggested message: `fix(room): make planning visible and task cards coherent`.
5. Create a clean detached worktree at that new commit. Do not install from this dirty implementation worktree.
6. From the clean worktree, install the current product stack into `RagImeControl.app`. The standard installer is `scripts/install_product_stack.sh`; Room acceptance needs the managed Pi runtime. Use the current Pi source at `/Volumes/undo 4t/git/learnA/pi` without modifying or staging its dirty work.
7. Run `scripts/check_installed_product_components.py --require-current` and record exact component evidence.
8. Create a **fresh** full-auto Room in the installed/Web shell and complete the GUI acceptance below. Hidden APIs and browser internals may diagnose failures but do not replace the visible journey.
9. Only after the fresh Room genuinely completes may the temporary physical install worktree be cleaned. Keep the permanent worktree ledger required by the product contract.

## 7. Fresh GUI acceptance journey

Use a natural ambiguous request that truly needs clarification and can be split, for example:

```text
我想给这个项目加一个能批量导入数据的功能
```

Acceptance requires visible evidence of all of the following:

- at most one clarification round: either 2–4 independent numbered A/B/C questions, or one option-first question for one mutually exclusive choice;
- selecting an option does not submit it until explicit confirmation; “其他” alone opens free-form input;
- the confirmed answer appears as the next user message in chronological order;
- after the final necessary question, the companion summarizes the goal and shows the complete execution plan;
- even when clarification is unnecessary, the visible plan waits for explicit “开始行动”; no write, test, or peer dispatch occurs before it;
- the plan locks shared contracts and assigns each user-visible feature end-to-end to one of at most four same-capability Room Agents, with dependencies/waves, write boundaries, integration and acceptance;
- after “开始行动”, a multi-feature request becomes multiple real companion Tasks running concurrently, not one feature split by technical layer or one Task merely drawn as parallel;
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
先完整阅读 /Volumes/undo 4t/git/learnA/.worktrees/paw-room-final-fix/docs/agent/room-production-acceptance-handoff.md、同目录的 room-facilitated-workflow-requirements.md，以及该 worktree 的 AGENTS.md/README。严格执行 handoff 第 0 节：第一条回复不要调用工具、运行命令、改文件、测试、提交、安装或分派伙伴；先用中文向我复述“当前做到哪里、现在仍有哪些问题、你理解的 Room 愿景、确认后准备做的第一步”，等我确认或纠正。确认后才继续第 6 节：只提交列出的二十六个文件，从新提交创建干净 worktree，安装当前构建，并在真实前端用全自动 Room 完成第 7 节的成组澄清、可见纵向分工、显式开始批准、多伙伴并行、工具/Todo/交接/独立复核闭环。不要混入列出的其他脏文件，也不要在 Room 通过前开始 Knowledge 或岛屿任务。
```
