# Room production acceptance handoff

> as_of: 2026-08-06 14:25 CST
> status: implementation and independent code review passed; clean commit, install, and fresh real GUI Room acceptance remain
> canonical worktree: `/Volumes/undo 4t/git/learnA/.worktrees/paw-room-final-fix`
> branch: `codex/room-production-acceptance-final`
> current HEAD: `8f9221a6048bbb3f46d543dc5e157741f842eb2e`

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

Current final code state:

- focused current-retry/chronology tests: `34/34` passed;
- complete Room frontend suite after the final ordering fix: `22 files, 288/288` passed;
- TypeScript after the final ordering fix: `pnpm exec tsc -b --pretty false` passed;
- complete frontend suite before the final isolated ordering fix: `104 files, 994/994` passed with `--maxWorkers=4`;
- isolated rerun for two first-pass timing flakes: `18/18` passed;
- Python Room/event projection regression: `124/124` passed; emitted `ResourceWarning`s and the injected `Pi host exited` path were non-fatal test-path output;
- production web build: passed before the final TypeScript-only ordering fix;
- import-boundary check: passed;
- route-ownership check: passed (`91 dispatched`, `205 declared`, `40/40 undeclared`);
- current `git diff --check`: passed.

Do not reinterpret the earlier unconstrained full frontend run (`992/994`) as a product failure: its two timing failures immediately passed together (`18/18`), and the bounded-worker full rerun passed `994/994`.

## 5. Exact intended commit scope

Stage only these implementation files plus this handoff:

1. `control-center-web/src/features/rooms/rooms-feature.test.tsx`
2. `control-center-web/src/features/rooms/runtime/room-execution-lanes.test.ts`
3. `control-center-web/src/features/rooms/runtime/room-execution-lanes.ts`
4. `control-center-web/src/features/rooms/timeline/RoomTurn.activity.test.tsx`
5. `control-center-web/src/features/rooms/timeline/RoomTurn.chronology.test.tsx`
6. `control-center-web/src/features/rooms/timeline/RoomTurn.tsx`
7. `docs/agent/room-facilitated-workflow-requirements.md`
8. `docs/agent/room-production-acceptance-handoff.md`
9. `rag_ime/agent_event_projection.py`
10. `tests/test_agent_event_projection.py`

Do not stage, reset, discard, clean, or overwrite these unrelated user/other-agent changes:

```text
README.md
integrations/pi/skills/implementation-execution/SKILL.md
rag_ime/agent_approval_model.py
rag_ime/agent_definitions.py
rag_ime/agent_execution_policy.py
rag_ime/agent_service.py
rag_ime/agent_sessions.py
rag_ime/agent_workspace.py
tests/test_agent_execution_policy.py
tests/test_agent_room_kernel_service.py
md-link-check
rag_ime/md_link_check.py
rag_ime/tui.py
scripts/sync_codex_oauth_to_pi.py
tests/test_md_link_check.py
tests/test_sync_codex_oauth_to_pi.py
tests/test_tui.py
```

`tests/test_agent_room_kernel_service.py` was used in regression runs but is still outside this patch's ownership and must not be staged.

## 6. Exact next steps

1. Read this file, the canonical requirements, and the worktree `AGENTS.md`/README before acting.
2. Recheck `git status --short` and `git diff --check`.
3. Stage the ten explicit files above with path-qualified `git add`; this repository ignores new files under `/docs/`, so add this handoff itself with `git add -f docs/agent/room-production-acceptance-handoff.md`. Verify `git diff --cached --name-only` is exactly that list and run `git diff --cached --check`.
4. Commit the scoped patch. Suggested message: `fix(room): report companion deliveries truthfully`.
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

- one option-first question at a time; each option includes a short explanatory sentence;
- selecting an option does not submit it until explicit confirmation; “其他” alone opens free-form input;
- the confirmed answer appears as the next user message in chronological order;
- after the final necessary question, the companion summarizes the understood goal naturally and asks whether to start;
- if clarification is unnecessary for another test prompt, work starts without a redundant confirmation gate;
- after “开始行动”, a decomposable task becomes multiple real companion Tasks running concurrently, not one Task merely drawn as parallel;
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
先阅读 /Volumes/undo 4t/git/learnA/.worktrees/paw-room-final-fix/docs/agent/room-production-acceptance-handoff.md、同目录的 room-facilitated-workflow-requirements.md，以及该 worktree 的 AGENTS.md/README。继续第 6 节：只提交列出的十个文件，从新提交创建干净 worktree，安装当前构建，并在真实前端用全自动 Room 完成第 7 节的自然澄清、多伙伴并行、工具/Todo/交接/独立复核闭环。不要混入列出的其他脏文件，也不要在 Room 通过前开始 Knowledge 或岛屿任务。
```
