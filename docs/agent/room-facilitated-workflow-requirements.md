# Room Facilitated Workflow Requirements

- Document class: sole tracked authority for current Room product behavior and acceptance status
- Approved vision window: user decisions made on or after 2026-08-02
- Contract revision: 2026-08-06
- Acceptance state: current source now has focused regressions for persisted full-auto mode, one role/Task work frame across retry Dispatches, terminal user-facing delivery summaries, default-collapsed truthful motion, multiline Tool output, a visible execution plan before every start, peer feature ownership, and one governed requirement/execution WorkDocument. The installed build remains older than the latest fixes. The latest foreground Room proved real parallel Dispatches but did not reach integration, independent review, and one final report; production acceptance remains open.
- Status rule: source, test, installed, and foreground evidence are reported separately

## Latest user corrections (verbatim)

> 可以显示具体谁在干什么。字少一些就行

> 说了测试问题要用用户语言，用户不可能说这些我想把这个小客户目录做得更能用：增加 CSV 批量导入并逐行预览、按邮箱域名筛选、重复客户合并并可撤销、查看客户变更历史。请先对齐真正影响方案的关键需求，已有合理默认值就直接决定，一次最多问 4 个问题；然后展示按完整用户功能纵向拆分的分工、依赖和波次。必须等我确认并点击“开始行动”后再读写文件、运行命令、测试或分派伙伴。开始后请让多位平等伙伴真正并行交付，最后由没有参与对应实现或集成范围的伙伴独立复核。

Derived acceptance: the compact composer status names the active companion and
her current user-facing work with few words. GUI acceptance prompts contain
only what an ordinary user wants to achieve; they never teach the Room its own
question, planning, dispatch, testing, or review policy.

Older handoffs, ignored local notes under `docs/`, screenshots, prototypes, tests,
and README summaries are evidence or navigation only. They cannot override this
file. A later product correction must update this contract and its status ledger
in the same tracked change.

## Product outcome

Room turns one natural conversation into visible, governed multi-companion work.
The user talks to one companion first. That Facilitator clarifies only material
missing choices, splits genuinely independent work among peer companions, keeps
their bounded private subagents beneath the owning work item, integrates the
result, requests independent review when policy requires it, and returns one
final report.

Room is also a long-running work system, not only a sequence of short chat
turns. In full-auto mode a bounded goal may keep making real progress across
many model turns, process restarts, and one or more days without asking the user
to operate each failed Tool step.

The conversation is the primary interaction surface. The Tasks surface is a
read-only projection for progress, division of work, dependencies, Todo,
subagents, attributed results, workspaces, review, and delivery. Its graph is an
overview, not an editor, execution gate, or second orchestrator.

## User-visible conversation

### Receiving companion

- Without an opening mention, `澄·远` receives the request and becomes the
  initial Facilitator.
- One explicit companion mention in the opening message selects that companion.
  For example, `@澄·今 我准备写 TUI` is received by `澄·今`.
- A later mention is ordinary communication. It does not transfer ownership,
  assign work, or start execution.
- Facilitator is a responsibility for this work, not a permanent hierarchy or a
  replacement for a companion's persona.

### Conditional clarification and visible start

The receiving companion first inspects facts already available from the
repository and runtime, then chooses one of two intake branches. Both branches
converge on the same visible execution-plan review and explicit start action.

1. If no material user-owned choice is missing, do not ask ceremonial questions.
   Continue directly to the visible execution plan, but do not write code, run
   tests, install, or dispatch implementation work yet.
2. If material user-owned choices remain, ask at most one clarification round.
   Put two to four independent questions together in one ordinary companion
   message, number them, and label compact choices `A/B/C` so the user can reply
   concisely, for example `1A 2C`. Do not turn requirement discovery into a
   serial questionnaire.
3. When there is exactly one genuinely mutually exclusive decision, use the
   native option box with 2–5 honest single-select options and at most one
   recommendation. Every option has a short name and a natural paragraph that
   explains the resulting scope, concrete user action and visible outcome,
   important exclusion or constraint, and effort or tradeoff instead of merely
   repeating the name. The interface supplies `其他`; choosing it reveals free
   text.
4. Clicking a native option only selects it. The user must then click
   `确认并发送`; selection alone never advances the Room. Ordinary grouped
   questions are answered by one normal user message, not by several stacked
   option cards.
5. Option and custom answers carry an explicit answer kind. Custom text is never
   relabelled merely because it equals an option's internal value.
6. Each answer appears as a separate chronological user message. The prior
   question remains in place, becomes read-only, and is never the sole record of
   the answer.
7. A dependent follow-up is allowed only when the received answer exposes one
   new high-impact choice that cannot be safely inspected or inferred. It stays
   inside the same bounded clarification exchange; repeated minor questions are
   a product defect.
8. Before defining work, the companion must be able to name the concrete entry
   or surface, what the user will do and see, the real deliverables, and an
   observable completion check. `端到端可用`, `完整`, and `可运行闭环` describe
   scope but do not replace those specifics; `当前项目`, `规定入口`, `核心操作`,
   and `真实结果` are placeholders and must not release execution.
9. On either branch, the Facilitator summarizes the understood user outcome and
   shows the proposed execution plan before asking `现在开始行动吗？`. The plan
   includes shared behavior/contracts, one to four vertical user-visible
   feature tasks, peer owners, dependencies and waves, write boundaries,
   integration, acceptance, and document continuity. It uses the user's
   language and point of view; internal English type names, camelCase fields,
   protocol vocabulary, and unverified entry points stay in expandable
   technical detail or the post-start WorkDocument.
10. Clicking it appends an ordinary user message such as `开始行动`. That message
   is durably ordered before the fresh execute Dispatch is released; a crash or
   retry cannot begin a Worker or Reviewer without the visible authorization.

Canonical ordering:

```text
用户：@澄·今 给客户管理补上批量导入、筛选保存、合并撤销和编辑回滚
澄·今：我来接手。还有两项会影响四个功能怎样落地的选择：
        1. 写入前的确认强度：A 逐项确认 / B 按整批确认
        2. 历史保留范围：A 永久保留 / B 按项目现有策略
用户：1A 2B
澄·今：我明白了……这是开始前的功能分工、依赖和验收方案
        [公共约定、伙伴功能任务、波次、集成、验收、文档留存]
        现在开始行动吗？
        [开始行动]
用户：开始行动
澄·今：我负责批量导入的完整用户操作，同时组织公共约定和最终集成……
澄·远：我负责筛选保存的完整用户操作……
澄·瞬：我负责合并、差异预览和撤销的完整用户操作……
澄·初：我负责编辑历史和单条回滚的完整用户操作……
澄·远：实现和测试完成，交回澄·今
澄·今：已完成集成，系统正按真实参与记录分配互不自审的复核目标……
复核伙伴：提交自己未实现、未集成部分的审查 Findings……
澄·今：最终总结……
```

This fixes ordering and ownership, not literal generated wording. Production
must never branch on `写 TUI`, fixed answers, companion display names, or a
preview fixture.

Clarification copy is conversation, not an audit report. The companion first
acknowledges the user's goal, explains briefly why the one current choice
matters, and asks it. Public copy does not announce that a work card was read,
declare the request insufficient, or recite goal/deliverable/acceptance
categories. It also does not tell an ordinary user that the system is “对齐”、
“澄清” or passing a “门禁”; it says naturally what is understood and what one
remaining choice would change.

## Roles and execution ownership

### Facilitator

- Room creation and invitation surfaces present all companions as equal-capability
  peers. They do not pre-label one companion as the permanent implementer,
  researcher, or final reviewer. Any stored collaboration role is only an
  opening-routing preference; the visible plan and actual provenance determine
  current responsibilities.
- Owns requirements, decomposition, WorkItem assignment, dependencies,
  integration, review policy, and the only final report.
- May implement and integrate, but cannot independently review its own work.
- Parallelizes only independent, non-overlapping slices when that materially
  reduces waiting.
- Remains a peer companion. Coordination responsibility never makes the
  Facilitator a permanent commander or a reason to give other companions only
  read-only summary work.

### Room companion

- Receives a structured WorkItem with objective, expected output, acceptance
  criteria, dependencies, owner, and workspace policy.
- Publishes meaningful progress, evidence, result, and handoff for its own slice;
  it does not publish a competing product-wide final.
- May launch bounded private subagents. The companion remains accountable for
  checking and integrating their output.

### Nested subagent

- Is a private child Session beneath one companion and WorkItem, not another
  Room partner.
- Cannot own or settle Room work, ask the Room user directly, or expose private
  transcript and hidden reasoning.
- Is bounded by lineage, generation, budget, timeout, cancellation, and depth.
  Late output cannot revive cancelled work.

### Reviewer

- Reviews its bounded target against the latest requirements and integrated
  evidence.
- Is independent from the author and Integrator of that bounded target,
  normally using fresh read-only context. A peer who implemented another
  non-overlapping feature may review this target, but never its own work.
- Is selected after integration from actual authorship, integration, and
  delivery provenance. Planning must not permanently reserve an idle companion
  or turn review into a lower-capability role.
- Submits structured Findings. Runtime policy derives the verdict; the Reviewer
  cannot fix a finding and approve the same fix.

### Runtime authority

Backend state owns work identity, capability leases, requirements, waits,
receipts, review, cancellation, and terminal state. Mentions, filesystem paths,
assistant prose, screenshots, and frontend state cannot create ownership or
prove completion.

## Stage-resident Skills

One exact governed Skill is bound to the current managed-Pi work stage. Skills
use Claude-style progressive disclosure rather than one permanent prompt
containing every workflow:

1. Startup context contains only the compact routing card needed to decide
   whether a Skill applies.
2. Entering a stage loads that one Skill's complete `SKILL.md`; the full body may
   exceed an old uniform 6 KiB or 120-line budget when the workflow genuinely
   needs the detail.
3. References, scripts, and examples load only when the selected Skill links to
   them and the current action requires them.

The routing card stays compact. Completeness belongs in the progressively loaded
body and references; deleting required workflow rules merely to satisfy a flat
file-size cap is a contract violation.

- intake and pre-definition resume: `alignment-and-decision`
- planning: `implementation-planning`
- implementation and post-definition resume: `implementation-execution`
- unknown bugs and performance regressions: Matt Pocock's governed
  `diagnosing-bugs` method
- explicitly requested architecture improvement: Matt Pocock's governed
  `improve-codebase-architecture` method
- closure self-check: `quality-gate`
- independent review: `independent-review`
- responsibility transfer: `structured-handoff`

The runtime stage selects the Skill. A Skill cannot select its own work, widen
Tools, bypass approval, or settle completion. The exact Skill name, content
hash, policy revision, work lineage, Session, capability epoch, and load reason
are receipted; stale or mismatched loads fail closed.

## Governed requirement and execution record

After the user approves the visible plan, the active WorkItem binds exactly one
governed Markdown WorkDocument. It is one physical record with two clearly
separated logical sections, not two files that can drift apart:

- the requirement section preserves the original user request and vision
  byte-for-byte, appends later user corrections or withdrawals verbatim, and
  keeps a replaceable current confirmed interpretation below the immutable
  source;
- the execution section keeps the approved vertical plan, current owner and
  slice, Todo/checkpoint, material progress, evidence, failed routes, blockers,
  remaining risk, handoff, and smallest next action.

Every stage updates the record from its own authoritative progress. A new user
requirement, correction, removal, or priority change is appended immediately and
the current interpretation/plan is reconciled without rewriting history. An
implementation, integration, verification, review, failure, recovery, or
handoff updates the execution section when material state changes. It is not a
per-Tool transcript, token log, or commit diary.

Only the current authorized owner writes the shared record; concurrent helpers
return a bounded proposed delta. After compaction, restart, replacement, or
handoff, the next owner reads the project continuity index, then this
WorkDocument, then verifies the current source, Git state, receipts, and runtime
before acting. Chat history and AI summaries cannot replace the user source or
fresh evidence. Runtime/RequirementCatalog state remains authoritative; the
document is the durable navigation and recovery surface. The backend archives
it on authoritative terminal state and never deletes it on a timer.

## Authoritative lifecycle

1. Capture the opening request and initial Facilitator.
2. Choose the direct or clarification branch.
3. Append every accepted answer as a new requirement revision and durable
   answer identity, publish its chronological user post, and only then
   CAS-release the one resume Dispatch. A crash in any window remains
   non-executable or exactly replayable, and a specific question revision
   resumes at most once.
4. Present the visible execution plan on both intake branches, wait for the
   typed start action, durably prepare its one-shot identity, publish the user
   message, and only then CAS-release execution. Any partial transaction remains
   non-executable and retryable.
5. Define the accepted work atomically, fence the intake Dispatch, and bind the
   one governed WorkDocument to the accepted WorkItem before the first approved
   implementation write.
6. Create one fresh execute-capable Facilitator Dispatch with a new identity,
   capability lease, epoch, and implementation Skill. The intake Dispatch never
   gains execute capability.
7. Create structured peer WorkItems and directed Dispatches. Independent work
   may run in parallel; dependencies remain serial.
8. Workers deliver artifacts, verification, and residual risk. Delivery remains
   integration-pending.
9. The Facilitator integrates in the sole authoritative integration workspace.
10. Apply policy-selected independent review to the integrated revision and
    close any bounded repair/re-review loop.
11. When work is quiescent, create exactly one read-only final-report lease.
12. The Facilitator publishes one final report; only its reporter receipt may
    lead to completed state.

Waits have an explicit owner, epoch, and resume condition. Resume is idempotent.
A wait cannot target itself or form a cycle. Historical materialized
continuations are upcast before recovery; an old record with no safe child
continuation stays non-runnable and emits one recoverable failure signal instead
of looping forever.

## Long-running autonomy and recovery

- Ordinary code errors, command failures, invalid Tool arguments, and transient
  Provider failures are owned by the companion doing the work. She reads the
  useful error, changes the code, command, or arguments, and retries without
  interrupting the user. A recoverable child failure does not block or settle
  the Room.
- Every companion has durable Todo, a current checkpoint, owned WorkItem and
  workspace binding, latest meaningful action, produced artifacts, verification
  state, and remaining work. A model turn or process may end without losing
  these facts; the next authorized run resumes from the checkpoint instead of
  starting the task again or relying on chat prose.
- Every material requirement change and every material execution transition is
  also reflected in the WorkItem's governed WorkDocument. The active owner
  updates it from current user instructions and her own real progress; helpers
  propose deltas instead of racing to write the same file.
- The Facilitator supervises recovery. Within configured policy she may retry
  the same step, revise its approach, reassign unfinished work, turn unsafe
  parallel work into ordered work, rebind a retained workspace, select another
  allowed model, and then continue integration, review, and final delivery.
  Every recovery changes durable state and keeps its attempt lineage.
- The user is asked only when progress truly requires a new user-owned decision,
  permission, credential, or external action, or when multiple bounded recovery
  attempts have produced evidence that no safe path remains. The Room then asks
  one natural, decision-changing question or reports one consolidated blocker;
  it never delegates routine debugging to the user.
- The conversation surface defaults to `正在恢复`, `已恢复`, and the next useful
  action. Exact attempts, safe command output, errors, and recovery decisions
  remain available inside the expandable Tool record. Repeated attempts are one
  chronological record with truthful lineage, not repeated failure cards or
  fake progress animation.
- Retry budgets, backoff, model choices, capability leases, cancellation,
  context compaction, checkpoints, and workspace cleanup are runtime-owned.
  React may display them but cannot invent a retry, keep a dead run alive, or
  decide that recovery succeeded.

### Risk-based approval, not approval theater

- Ordinary bounded work inside an already authorized workspace is decided by
  deterministic policy and does not enter model approval: reading/searching,
  creating or editing ordinary project files, applying bounded patches, running
  focused tests, and non-destructive local commands covered by the active
  capability lease.
- Model adjudication is reserved for a genuinely pending decision whose effect
  crosses or materially changes a trust boundary: leaving the authorized
  workspace, destructive deletion or overwrite, credential or permission
  access, external network/publication, dependency or application installation,
  system configuration, privileged process control, or another explicitly
  classified high-risk effect.
- Independent model adjudication is an exceptional slow path. It is used only
  when deterministic policy can name the bounded proposed effect but cannot
  safely decide it from existing authorization and risk rules. Common Room work
  must not invoke an approval model for ceremony, telemetry, a second opinion,
  or because the model is available; unnecessary adjudication latency is itself
  a product defect.
- `全自动` means those genuinely risky pending decisions may be independently
  judged by the configured approval companion (currently Luna Max) using the
  Room's authorization history. It does not send every ordinary Tool call to
  Luna and does not convert a safe workspace edit into a model verdict.
- Safe operations retain an ordinary Tool/command receipt and meaningful result,
  but the public UI does not show `审批模型`, `批准`, `裁决说明`, or an approval
  card. A model approval card for a bounded ordinary file creation, edit, or test
  inside the authorized workspace is an acceptance failure.
- Deterministic allow/deny classification remains authoritative. The approval
  model cannot widen the current capability, authorize an unknown effect, or
  turn a hard policy denial into approval.

## Parallel workspaces and permanent ledger

- A small coherent single-writer task may use the governed current workspace.
- Read-only independent work may share an immutable baseline.
- Concurrent writers receive distinct isolated workspaces from one pinned Room
  baseline. Exactly one Integrator owns the authoritative integration workspace.
- One writable workspace binding belongs to one WorkItem responsibility, not to
  a persona forever.
- The permanent ledger records work lineage, requirement revision, owner and
  Session, repository and pinned baseline, physical binding, lease history,
  delivery snapshot, per-file diff stats, integration revision, terminal reason,
  cleanup state, and authorizing receipts.
- Worker delivery is hash-bound and remains pending until Facilitator
  integration.
- After successful integration, record the integrated revision first; then clean
  the exact child worktree and retain the logical ledger forever.
- Failed, blocked, cancelled, conflicting, orphaned, incomplete, or unintegrated
  workspaces remain physically present and red until the Facilitator issues a
  receipted retry/rebind or a reasoned snapshot/hash-bound abandonment.
- Cleanup is idempotent and exact-path scoped. A missing path records an observed
  result; it never broadens deletion scope.

## Conversation surface

The conversation must feel temporal because real work facts keep arriving, not
because a client timer pretends work happened.

- Each active companion has one readable lane with avatar, current semantic
  state, current action, latest update time, elapsed time, completion summary,
  and a continuous chronological activity stream beneath it.
- One public work frame represents one companion responsibility for one
  authoritative Task/WorkItem. Recovery, retry, resume, and replacement
  Dispatches for that same owner and work are attempts inside the same frame;
  they do not create another avatar card. A later genuinely different Task may
  create another chronological frame for the same companion.
- Companion frames are collapsed by default. The header always remains useful:
  while truly active it shows the current action, restrained live motion,
  latest update, elapsed time, and Todo progress; when terminal it stops motion
  and replaces all `正在处理` / `等待下一条进展` copy with the companion's
  user-facing result, concrete files or artifacts, focused verification,
  residual risk, and explicit handoff source/target when applicable.
- Every bound companion resolves to her configured portrait in the conversation
  lane, Tasks graph, WorkItem detail, and partner progress view. An initial,
  generic route glyph, missing image, or another companion's portrait is only a
  bounded loading fallback and must be replaced as soon as the authoritative
  persona projection is available.
- The role header answers four questions without expansion: what the companion
  is doing now, why that action matters, what she will do next, and how much of
  her Todo is complete. `执行中`, `当前任务推进有新进展`, a Tool family such as
  `bash`, or a step count is not a sufficient current-action summary.
- A coalesced work summary must refresh the collapsed role header as well as
  the expanded activity row. The header names the current user-facing phase
  and, when the same summary has changed repeatedly, exposes the authoritative
  update count; it must not keep an older `正在继续任务` headline while the
  expanded row says `已更新 9 次`.
- While a turn remains active, an old public timestamp means only that no new
  public-safe event has arrived. The header says the companion is still
  processing and that no new public progress is available; it must not claim
  the companion is `正在等待` unless an authoritative wait or user decision is
  actually present. Internal task-check recovery copy is never presented as a
  promised deliverable.
- Activity is one vertical stream, not a stack of nested cards and columns.
  Tool activity, public-safe work summaries, results, waits, handoffs, and
  workspace transitions share the same time order.
- New work summaries and Tool events append at the chronological bottom using
  authoritative server sequence and event time. A mutable summary may update in
  place only inside its current tail row; it must not remain above later events
  or make recent work appear earlier than an older Tool call.
- The default density follows the Codex activity-flow pattern: compact rows
  expose useful facts such as action, file name, command status, and attributed
  `+N/-N`; repeated plumbing, long arguments, and raw output stay collapsed.
  Each row may expand in place to bounded input, output, diff, or safe failure
  details without opening another column or nested card stack.
- Disclosure has two independent levels. Closing a companion lane must retain a
  compact live tail with the latest three meaningful actions, any currently
  active Tool, current/next work, latest update, and non-empty Todo progress; it
  must not collapse a multi-page run into one opaque summary card or hide every
  sign of work. Older repeated actions may become one truthful count. Opening
  the lane reveals the complete chronological stream. Each Tool row then owns
  its own disclosure, so opening one result never expands the whole lane or
  every Tool. The active Tool may auto-open while streaming and settle back to
  its compact semantic row after completion.
- Repository work uses first-class semantic rows instead of the generic label
  `工具操作`. Search and test are semantic `bash` results, while diff is the
  semantic result of `edit` or `write`; none is a fifth basic coding Tool. A
  compact sequence may read `已搜索 …`, `已读取 RoomTurn.tsx`, and
  `已编辑 RoomTurn.tsx +46 -1`; expanding it reveals matched locations, the
  bounded command/output, or the attributed patch. File manipulation must be
  strong enough to support repeated edits and verification during a day-scale
  run, not only report that an opaque Tool returned.
- Expanded result details lead with the semantic result: affected file or
  artifact, meaningful output, changed lines or diff, test/command verdict,
  exit status when relevant, and the next consequence. A panel containing only
  `状态：已完成`, `已有变更`, `结果已回传`, or a schema/state revision is an
  acceptance failure. Failed attempts and recovery remain below that result as
  bounded diagnostic detail.
- Search detail lists bounded matched files, line numbers, and useful snippets;
  a zero-result search names the searched scope and query without an empty dark
  output block. Read detail renders the requested range with line numbers.
  Command detail renders the command, working directory, ordered stdout/stderr,
  duration, exit code, and truncation. Edit and write detail render the actual
  per-file Diff or created-file preview and `+N/-N`. Internal evidence handles,
  protocol fields, and a second `状态：已完成 / 结果摘要` box are audit-only and
  never substitute for these user-meaningful results.
- A persisted multiline result must retain semantic line boundaries. If a read
  reports a 260-line requested/returned window, the bounded preview renders its
  actual multiple lines with the correct starting line and a truthful
  truncation notice; collapsing those lines into one horizontal row while still
  claiming `260 行` is an acceptance failure.
- A long-running edit has its own truthful active treatment: the file and
  current edit stage remain visible, real progress events update the row, and a
  restrained edit indicator continues only while that Tool call is active.
  Completion settles into the file/diff summary; failure settles into one
  expandable error with recovery attempts. A client timer, heartbeat, or
  elapsed-time repaint must never animate an edit that is not actually running.
- A companion's real conversational update remains visually separate from the
  activity rows. Private reasoning, internal protocol steps, and duplicate
  status paraphrases are never promoted into public companion speech.
- New real events receive subtle one-shot arrival feedback and bottom-aware
  follow. Scrolling up never yanks the user down; `回到最新` restores follow.
- The compact live indicator beside `@` names who is doing what in a short
  user-facing phrase, for example `澄·远：梳理需求` or
  `澄·初：批量导入`. A generic `协作进行中` label does not meet this
  requirement, and the composer does not grow to accommodate the label.
- Private orchestration objectives are never promoted as user-facing work.
  Merely containing a schema word such as `questionOptions` cannot turn an
  internal instruction into a false “选项没有准备完整” failure; real Tool
  validation failures still get the bounded recovery message.
- A freshness timeout changes motion to truthful waiting/stalled state. Network
  heartbeat and elapsed-time repaint never masquerade as work.
- Terminal and final events still auto-follow and announce once when the user is
  already at the bottom. Disconnect and reduced-motion stop decorative motion.
- Pending clarification owns the interaction point. The ordinary composer is
  hidden only while the current question is answerable; stale or terminal
  questions cannot trap input.
- The active companion's Todo summary is always visible in her lane: completed,
  active, waiting, blocked, and abandoned counts plus the current item. Expanding
  it reveals the durable list without creating a second checklist.
- Visibility follows Todo convergence, not the lane label. Any pending,
  in-progress, or blocked item remains anchored at the card bottom after a
  failure, stop, retry, or terminal delivery so recovery checkpoints are not
  lost. The Todo block disappears only when every item is completed or
  abandoned; a finished checklist must not keep occupying the conversation.
- Todo is a dedicated live region anchored at the bottom of the companion lane,
  after the chronological activity stream. It is not rendered as a generic Tool
  row or a result panel. The default view shows every Todo title with its real
  status, highlights the current item, reports completed/total and the next item,
  and names a blocker when present. Updates refresh that bottom region in place
  with subtle feedback while a separate chronological state-change event remains
  in the stream. `Todo：2/4 已完成…` without the four item titles is insufficient.
- A missing Todo or an authoritative Todo with zero tasks renders no Todo block,
  no heading, and no “当前没有 Todo” confirmation. Absence is not user-facing
  progress. As soon as the first real item exists, the same bottom region
  appears and updates in place.
- Expanding Todo reveals each item's checkpoint, relevant file/artifact or test,
  and latest meaningful update. It must not expand to `结果明细 / 状态：已完成`
  with no task-specific content.
- Internal protocol words and identifiers stay in optional audit detail. Remove
  the old execution-gate panel and lead with ordinary conversation.

### One canonical basic coding-Tool surface

- The only public basic coding Tools available to the model and projected by
  Agent, Room, conversation, and Tasks frontends are `read`, `edit`, `write`,
  and `bash`. A localized row may say `正在读取` or `已编辑`, but its canonical
  public Tool identity remains one of those four everywhere.
- `workspace_*`, `read_file`, `edit_file`, `write_file`, `shell`,
  `apply_patch`, and similar historical or Provider-specific names may exist
  only as non-model-visible compatibility, authorization, or audit aliases.
  The owning process upcasts an alias once at its Provider, persisted-history,
  or backend boundary before the call enters the model-visible catalog or UI
  projection. An alias must never register a second capability, appear as a
  second public Tool, create a separate permission decision, produce a parallel
  receipt/history branch, or select another frontend renderer. Original legacy
  spelling may remain only inside optional audit provenance.
- All four Tools use one chronological row contract: a compact semantic summary,
  latest real update time, truthful active state, bounded incremental output,
  completion or failure, and an in-place disclosure for parameters, output,
  attempts, and safe diagnostics. A newly accepted call receives restrained
  one-shot arrival feedback; ongoing motion starts only after an authoritative
  active event and stops on completion, failure, cancellation, disconnect, or
  reduced-motion preference. A timer or heartbeat cannot manufacture progress.
- A running row distinguishes `等待首段结果`, newly received output, continued
  output, recovery, and terminal state. Stream chunks are ordered by stable
  call identity plus server sequence, append at the chronological bottom, and
  reconcile after reconnect without duplication. The last truthful output stays
  readable while a bounded retry is recovering; routine argument, code, command,
  or transient Provider errors remain inside the row and do not ask the user to
  operate the retry.
- `read` shows the target path and requested range or bound before execution.
  While active it can reveal newly received bounded text with a streaming cursor;
  completion provides code-aware content with line numbers, truncation state,
  copy, and folding instead of only `状态：已完成`.
- `edit` shows the target and bounded change intent without exposing hidden
  reasoning. Its active treatment identifies the current file and real edit
  stage, incrementally renders available patch hunks, and settles into the actual
  attributed Diff, per-file `+N/-N`, and verification consequence. A failed
  attempt preserves its useful error and recovery lineage beneath the last good
  patch instead of creating repeated top-level failure cards.
- `write` shows the target, create/replace mode, and bounded size or line progress
  without dumping a large proposed body into the collapsed row. It streams
  truthful write progress when the runtime reports it and completes with the
  actual created or replaced artifact, line count, attributed Diff, and next
  verification step. It must not display a file as written merely because a
  model proposed content or a client timer elapsed.
- `bash` keeps the command and working directory distinct from its result. While
  active it appends bounded stdout and stderr in their real order with a visible
  running cursor; completion exposes exit code, duration, truncation, and the
  semantic search/test/command verdict. Failure and autonomous retry remain
  expandable in the same call lineage, with the recovered result becoming the
  compact summary.
- Conversation and Tasks reuse these exact call records and renderers at
  different density. Neither React surface infers missing chunks, synthesizes a
  Diff from repository-wide dirt, or maintains another Tool state machine.

### Conversation history loading and long-session performance

- `正在恢复`, `已恢复`, `已确认为空`, and `恢复失败` are distinct frontend
  states. `turnOrder.length === 0` is not proof that a Session is empty.
- Selecting a Session immediately shows its header and either the last hydrated
  transcript or one compact `正在恢复这段对话` state with truthful motion. It
  never flashes the new-conversation welcome, an empty canvas, or zero-message
  copy while the authoritative snapshot is still in flight.
- A cached transcript remains visible while its cursor and catalogs refresh in
  the background. Model, Tool, command, Todo, and task-center controls load
  independently; one slow history response must not make the entire workspace
  inert.
- Only a successful authoritative empty snapshot may show the welcome view. A
  failed or interrupted history request preserves cached content when present;
  without cache it shows a recoverable history state, not a fake empty Session.
- Initial hydration returns a bounded newest page rather than the complete
  lifetime transcript. The default bound is at most 100 visible turns or 512 KB
  of public projection, whichever is reached first. Older pages load when the
  reader approaches the historical edge, retain scroll position, and merge by
  stable event/message identity. Live events arriving during hydration are
  buffered and reconciled by sequence instead of being lost or duplicated.
- The timeline stays virtualized after hydration. A Session switch must expose
  cached content or the recovery state within one render frame; cached history
  should be readable within 100 ms, and the first newest-page content should
  render within 500 ms after its successful local response. Performance
  acceptance records response bytes, request time, hydration/render time, turn
  count, and whether older-page loading preserved the reader's position.
- Loading motion is restrained, stops on terminal state or disconnect, and
  honors reduced motion. It communicates history recovery only; it cannot be
  reused as evidence that an Agent is doing implementation work.

## Tasks surface: same source, lower density

- Conversation and Tasks project the same authoritative event and workspace
  records. They do not maintain separate completion truth.
- A WorkItem card defaults to owner, objective, semantic state, latest summary,
  completion, last update, dependency/blocker, and verification.
- Its primary label is the user-meaningful work objective, never the most recent
  Tool family (`bash`, `工具操作`, or `提交工作结果`). The current Todo item and
  completed/total Todo count remain visible in the compact card.
- Expanding the card reveals that same activity stream, Tool details, Todo,
  subagents, workspace lifecycle, delivery, and result—never a copied second
  feed.
- Each companion's Todo is joined from the existing authoritative Session Todo.
  Room does not implement another checklist and React does not infer completion.
- Each companion's result shows only her receipted contribution: artifacts,
  per-file `+N/-N` for meaningful text diffs, focused checks, result, integration
  disposition, and residual risk. Repository-wide dirt and another companion's
  patch must never be attributed to her.
- Nested subagents are grouped beneath the owning companion/WorkItem with public
  task, state, bounded budget/usage, timing, and result or safe error.
- The dependency graph remains compact: short goal/task/result nodes, owner,
  state, and edges. It does not absorb Tool logs, Todo, subagents, or actions.
- The graph uses a legible left-to-right goal/work/result flow with aligned
  lanes, short readable node titles, visible owner, state, Todo progress, next
  dependency, and an accessible non-color status cue. Edges attach to nodes and
  communicate real dependency direction; excessive empty canvas, detached
  dotted lines, bullet-only legends, truncated objectives without a useful
  summary, and oversized single-task layouts are acceptance failures.
- Motion is semantic and bounded: a newly released WorkItem enters once, an
  active edge or node shows restrained ongoing state, handoff visibly changes
  ownership/state, and terminal nodes settle. Reduced-motion disables the
  decorative part without hiding state.
- Ordinary `waiting`, `waiting for a peer`, and `waiting for the next step` use
  neutral or informational styling. Ochre/red warning treatments are reserved
  for a concrete delay that needs attention, a confirmed blocker, or failure;
  a normal wait must not look like an error. Root, lane, WorkItem, and graph
  labels derive from the same authoritative state so a running or peer-waiting
  Root cannot be presented as `已阻塞` merely because an earlier Tool attempt
  failed and recovered.

### Genuine multi-companion acceptance

- An invited participant, an idle participant card, or multiple Sessions polled
  by the frontend does not count as collaboration.
- Complexity is calibrated by concrete responsibility seams, not by adjectives
  or file count. `为已有系统增加批量数据导入：从产品现有的界面、CLI、API 或库接口
  接收数据，完成校验与保存，持续报告进度和逐项错误，最后产出可核对结果` is the
  canonical positive example: entry contracts, processing/persistence,
  progress and failure recovery, and cross-boundary acceptance are normally
  separable, while the Facilitator retains integration and the end-to-end run.
  Unless source inspection proves those seams conflict on one owner, at least
  one peer must receive real work. `修复一个已经定位的函数边界条件并补一个聚焦测试` is
  the contrasting single-owner example. These examples train analogous
  decomposition and never authorize a request-text-specific branch.
- A task selected to exercise Room parallelism must produce at least two real,
  independently owned WorkItems with distinct directed execution, overlapping
  active intervals when dependencies permit, separate Todo/checkpoints, and
  attributed results before Facilitator integration.
- If the Facilitator legitimately keeps a task single-writer, the UI states the
  concrete dependency or overlap risk and must not label that run parallel or
  use it as the Room multi-companion acceptance case.
- The acceptance flow must show the Facilitator's own integration work, at least
  one peer implementation/research contribution, and a later independent review
  contribution as distinct responsibilities. Reviewer participation alone does
  not satisfy the two-WorkItem implementation requirement.

### Clarification acceptance prompt discipline

- The foreground clarification test starts from an ordinary product request
  with at least one real user-owned choice, but does not embed the desired
  answers, role assignments, decomposition, tools, review policy, or acceptance
  procedure. A suitable general example is `我想给这个项目加一个能批量导入数据的功能`:
  the existing product surface determines what is already knowable, while the
  entry surface, accepted data form, and failure/result behavior may require
  one-at-a-time choices.
- A fully specified audit prompt is valid only for the direct-execution branch.
  It cannot be cited as evidence that option-first clarification, confirmed
  answers, the natural understanding summary, or the typed start action works.
- This is an acceptance-fixture discipline, not a phrase-specific route. The
  runtime must decide material ambiguity from current facts and the selected
  stage Skill, never from matching `批量导入`, `TUI`, or another canned request.

## Public language and persona

Companions use natural language understandable to ordinary users. Public copy
does not expose Kernel, Root, Dispatch, Task, acceptance-criterion IDs, Receipt
IDs, private reasoning, or protocol JSON. It does not copy Cat Cafe characters,
catchphrases, or performance style, and companions do not repeat one generic
Facilitator final.

Stable persona and current responsibility are separate prompt owners:

- `澄·远`: calm, clear, structured; solves the real problem and closes the
  verification loop.
- `澄·今`: warm, direct, pragmatic; receives the immediate problem and offers
  the easiest valid next step.
- `澄·初`: bright, curious, restrained; distinguishes clues from facts and asks
  few precise questions.
- `澄·瞬`: concise and fast; extracts decision-changing signals and hands off
  beyond rapid triage rather than presenting speed as certainty.

Current product scope is voice input only. Room companions do not produce TTS.

## Event and provenance contract

- Server sequence plus stable event identity determine chronology and reconnect.
  Equal text never deduplicates distinct events.
- The reader remains backward compatible with historical or non-alignment wait
  records that contain no options. That replay compatibility does not authorize
  active alignment to emit a text-first question.
- Reload preserves answered questions, separate answers, activity, Todo,
  task/subagent hierarchy, attributed results, workspaces, review, and exactly
  one final.
- Every completed response reports its real Provider/model and runtime-reported
  token/cache usage. Usage is `reported`, `not_reported`, or `not_applicable`;
  missing data is never rendered as zero.
- A managed Room turn that ends through a Tool-only authoritative commit still
  produces one safe response-evidence event after settlement. It carries only
  bounded Provider/model/usage fields, binds to the exact Dispatch and resulting
  Post, and reuses the same response-evidence renderer as a normal completed
  message. Tool arguments, hidden text, and protocol bodies remain private.
- Primary Tasks statistics exclude internal final-report bookkeeping; Report
  work remains visible only where its audit role matters.
- Provider calls, artifacts, diffs, Todo, and workspace state stay bound to the
  response, Session, participant, WorkItem, baseline, and revision that produced
  them.

## Local storage and external-volume boundary

- High-growth durable Room data is configurable and should use the user's
  external SSD when it is present: Agent/Room data, SQLite, debug context,
  models, Knowledge runtime/data, managed Pi runtime, worktree ledgers, and
  bounded logs. The app bundle and the minimal launch integration may remain on
  the system volume.
- Migration is controlled and reversible. Stop all owners first; make a
  consistent SQLite backup and pass `PRAGMA quick_check`; copy or rebuild each
  supported owner at the configured external root; update every producer and
  consumer to the same root; restart; then verify health, Room/Session replay,
  Pi canary, Knowledge CRUD, model health, and real foreground input. Never move
  a live SQLite/WAL pair or a physical Git worktree behind its permanent ledger.
- The product must not solve this with unsupported partial symlinks. Managed Pi
  and Knowledge reject symlinked roots, worktree metadata contains absolute
  bindings, and a split desktop-bridge/socket root would create two runtimes.
  Until every launcher supports the same external root and log directory, keep
  the old system directory as a recoverable fallback and report the remaining
  split-owner gap explicitly.
- External capacity alone is not the whole durability contract. Before treating
  personal conversation, Knowledge, or SQLite data as permanently migrated,
  ownership and encryption of the target APFS volume must be verified or the
  user must explicitly accept that residual risk. Rebuildable models and caches
  may move independently.

## Read-only source references, not product owners

External and adjacent sources may supply interaction and implementation
patterns, but they do not replace the Room contracts, runtime owners, Personas,
or acceptance evidence above.

- Codex is the density reference for a chronological conversation with compact,
  individually expandable search/read/edit/command/diff rows.
- The read-only OMP source is the reference for a latest-live Todo replacing its
  earlier live snapshot, persistent last-good Todo on a failed update, active
  Tool animation, streaming edit preview, and per-file diff statistics. Relevant
  files include `oh-my-pi/packages/coding-agent/src/modes/components/tool-execution.ts`,
  `oh-my-pi/packages/coding-agent/src/modes/utils/event-controller.ts`, and
  `oh-my-pi/packages/collab-web/src/tool-render/tools/todo.tsx`.
- `slopus/happy` is the read-only reference for explicit `isLoaded` versus empty
  conversation state, inverted virtual history, a bounded newest slice with
  older-message loading, compact Tool rows, concrete Todo titles, and expandable
  patch/diff views. Relevant upstream files include
  `packages/happy-app/sources/-session/SessionView.tsx`, `ChatList.tsx`,
  `ToolView.tsx`, `TodoView.tsx`, `CodexPatchView.tsx`, and `ToolDiffView.tsx`.
- Claude Code permission modes are a policy reference for separating ordinary
  authorized work from rare trust-boundary decisions. Room retains its own
  deterministic capability leases, receipts, approval model, and UI language.
- Copying another project's component tree, master/child hierarchy, character
  system, private reasoning display, or permission defaults is explicitly out
  of scope. Adapt the proven pattern to the existing authoritative owner and add
  Room-specific source, regression, and foreground evidence.

## Implementation and acceptance ledger

### 2026-08-06 current checkpoint

- Commit `8f9221a6048bbb3f46d543dc5e157741f842eb2e` persists the Room full-auto
  execution policy through creation, SQLite reload, migration `0146`, and
  participant workspace recovery. Its focused source regressions passed before
  installation.
- Foreground Room `room:dee4e68f-c011-4958-b1b5-bf17f1549320` proved two
  independently directed worker Dispatches and one returned frontend audit, but
  backend recovery did not converge to Facilitator integration, independent
  review, and one final report. It is evidence of real parallel release and a
  failed closure, not a production pass.
- That foreground run exposed deterministic presentation defects now covered by
  source regressions: retry Dispatches for one companion/Task created duplicate
  avatar cards; an older attempt could overwrite a newer retry's card state; a
  terminal delivery still inherited old running copy and stale motion; an
  unfinished Todo disappeared after failure or stop; and persisted multiline
  Tool output lost its newline structure. The current source passes the 65-test
  focused lane/chronology set, the complete Room frontend set (22 files,
  286/286), TypeScript, the production Web build, and the 124-test event
  projection/Kernel service set. Import-boundary, route-ownership, and diff
  checks also pass; the Python run retains pre-existing unclosed SQLite/file
  `ResourceWarning`s that are not treated as assertion failures.
  The first unconstrained full Web run reached 992/994; both non-Room failures
  passed together on immediate isolated rerun (18/18), and the complete suite
  then passed 104 files and 994/994 tests with four workers. These are not
  installed foreground evidence yet.
- The system volume reached `No space left on device` during the run. Four old
  inactive debug-context directories were moved intact to the external SSD and
  `privacy.debugContextDirectory` now targets the external debug-context root,
  recovering approximately 2.5 GiB. A complete app-support migration remains
  open because desktop bridge/log roots and physical worktree/SQLite ownership
  must be made coherent before a controlled stop, copy, restart, and rollback
  verification.

| Area | Source/test state | Installed foreground state |
| --- | --- | --- |
| opening Facilitator, conditional clarification, crash-safe chronological answers and typed start | implemented; current Room frontend 286/286, TypeScript, production build, focused backend/runtime regressions, and the complete Web suite (104 files, 994/994 with four workers) passed; the preceding unconstrained run's two non-Room timing failures also passed together on isolated rerun 18/18 | open |
| fresh execute Dispatch, peer work, nested delegation, integration, review, one report | source now exposes the parallel execution policy to the fresh Facilitator Dispatch and rejects a parallel Facilitator final before at least one eligible peer has returned real execute work; review policy can be durably raised at definition and cannot be downgraded; focused gates passed | open; a fresh installed Room must still prove the positive peer/integration/review/final path |
| stage Skills and capability receipts | implemented; Skill 25/25 and Pi runtime 70/70 passed | open |
| permanent workspace ledger, same-baseline isolation, integration-before-cleanup, red retention | source now permits an unrelated dirty target by pinning `HEAD`, storing the target snapshot/status/path receipt permanently, and creating the child from that commit; integration rejects any changed-path overlap before target mutation while non-overlapping delivery preserves the user's dirt. The complete 42-test workspace coordinator module, 7-test ledger module, compilation, and diff checks passed | open; a fresh Room must still prove two simultaneous isolated writers, integration, cleanup, and permanent ledger readback |
| continuous conversation activity and lower-density Tasks projection | source now reorders mutable activity by its latest authoritative timestamp, derives concrete role copy from the owned task and expected delivery, keeps any unfinished Todo as the final sticky block, removes the redundant answered-question notice, makes the whole companion lane foldable, and gives the graph compact status markers, concrete current/next action, dependency labels, and truthful active-edge motion; Room frontend 286/286, complete Web 994/994, TypeScript, and the current production Web build passed | prior foreground failure remains authoritative until the coherent build is installed and rechecked |
| canonical `read` / `edit` / `write` / `bash` surface, streaming and personalized result views | implemented in source: public catalog projection exposes the four basic coding Tools once, historical aliases upcast into them, Agent and Room share the artifact/Diff renderer, active mutations animate without publishing a half-built Diff, and completed bash rows preserve bounded stdout/stderr plus exit status. Structured read/search payloads now survive the Room event boundary as numbered source windows and matched file/line/snippet rows instead of generic result cards; focused Python projection, TypeScript, and 75 Agent/Room activity tests passed | open; all four tools must be exercised in one coherent foreground build |
| history loading, cached transcript continuity, bounded initial page and older-history loading | explicit loading/empty/failed projection plus newest 80-event and newest 100-complete-turn windows, stable `beforeEventId` / `beforeMessageId` older-page merge, and total-count reconciliation are implemented; 138 backend/policy/route tests, focused Web paging/loading checks, the complete 974-test Web suite, TypeScript, and the prior local no-false-welcome checks passed | source Web shell passed; coherent installed foreground timing open |
| risk-based full-auto approval | scoped hash-bound text write/edit/patch now bypass Luna by deterministic policy; focused policy and Agent-service regression passed while R3, sensitive, and out-of-scope cases remain model-routed | fresh full-auto Room foreground open |
| Session Todo, per-owner result/diff, subagent grouping | implemented on one authoritative Session Todo: every item may persist a current checkpoint, categorized file/Diff/artifact/test reference, and authoritative update time; migration 0145 preserves prior event history while admitting checkpoint events; writable and read-only Room roles can maintain their own Todo; Agent and Room task surfaces project the same fields at different density. An unfinished Todo now survives failed, stopped, and terminal lanes at the card bottom and disappears only after every item completes or is abandoned. Room frontend 286/286, TypeScript, production build, and the affected backend/runtime checks passed | open; a fresh installed multi-companion Room must show distinct live Todo and attributed results for every real owner |
| real Provider/model/token/cache provenance on Tool-only Room replies | implemented through one post-bound `response_evidence` path shared with the existing reply footer; the settled lookup is fenced by exact Session, runtime turn, `room_commit` Tool call, applied receipt, committed Dispatch, and resulting Post; terminal Room replay admits only that matching provenance; focused v1, v2, projection, real SQLite kernel, and Web regressions passed; incomplete evidence renders no misleading placeholder | open; corrected installed Room must show the real fields on its resulting reply |
| day-scale full-auto recovery, durable checkpoints, automatic repair/retry/reassignment/model fallback | partially implemented; durable Dispatch attempts, Todo, workspace ledger, reconnect state, direct failed-Tool retry lineage, and Provider retry projection exist and passed source regression; restart-resume plus injected native recovery acceptance remain open | open |
| historical continuation recovery and Report-stat filtering | implemented; historical upcast 7/7 and settlement regression passed | open |
| tracked authority portability | implemented by `docs/agent/room-facilitated-workflow-requirements.md` | not applicable |
| coherent App/Web/Python/managed-Pi provenance | clean commit `bffbd5a2` passed generated-contract reproduction, TypeScript, the complete Web suite inside the official production build, native Web dist validation, signed App build, and static footprint; its App marker is clean and binds native production transport to that exact commit | open; the sandbox refused replacement of `/Users/undo/Applications/RagImeControl.app`, whose installed marker remains `ae71bc07` |
| real Room completing a concrete TUI task | not a source claim | the 2026-08-05 run created `rag_ime/tui.py` and `tests/test_tui.py` but remained a single-Facilitator failed run; its focused test currently has 1 error in 5 tests, so the artifacts are preserved as an uncommitted recovery input rather than reported as delivery |

## 2026-08-05 Markdown-link-checker Room findings

Room `通用多人协作验收 20260805` used the real local production Web transport
and the generic request `我想给这个项目加一个真正能用的 Markdown 文档链接检查命令。`
It is an acceptance probe for decomposition, not a product-specific branch.

Verified behavior:

- Four decision-changing questions appeared one at a time with described
  options, explicit `确认并发送`, chronological user answers, a natural summary,
  and one `开始行动` message.
- The opening Facilitator attempted a real peer implementation assignment and,
  after isolated workspace preparation failed, recovered without asking the
  user and assigned a separate read-only source investigation.
- Provider/model and reported token/cache evidence were visible on the
  completed alignment response.

The run was deliberately stopped and is not accepted. Its retained evidence
exposes these current failures:

- The observed build rejected `isolated_writable` for any dirty base worktree,
  including unrelated untracked recovery files. The fallback produced only one
  read-only peer while implementation remained serial, so that Room did not
  create two overlapping, independently owned implementation WorkItems. Source
  now pins `HEAD`, stores a permanent reservation receipt containing the target
  snapshot, status hash, bounded path list and truncation count, and creates the
  child worktree from that commit. Integration preserves unrelated target dirt
  and retains the child red before applying when its changed paths overlap any
  current target change. Focused non-overlap and overlap tests pass; a fresh
  foreground Room still has to prove two real concurrent writers and their
  final integration.
- A missing or zero-item Todo rendered `澄·远 的 Todo / 当前没有 Todo`; this is
  non-information and must render nothing until a real item exists.
- A normal waiting lane used ochre warning styling and looked failed. Warning
  styling is reserved for attention; ordinary peer wait is neutral/info.
- The task/header projection could say `已阻塞` while the authoritative Root was
  waiting and a peer was still active. Recoverable Tool/workspace attempts must
  not become the Root's user-visible terminal state, and every surface must use
  the same current projection.
- Task graph owners used initials or generic route glyphs instead of the bound
  companion portraits. The graph also showed vague action text and only one
  effective worker, so it did not communicate real parallel ownership.
- Closing a companion lane hid the entire multi-page Tool timeline. The closed
  lane must retain a compact recent-action tail; opening the lane reveals the
  full stream, and each Tool keeps its own independent disclosure.
- Compact Tool rows repeated useful counts but expanded search/read results were
  dominated by generic parameter and result cards, internal evidence handles,
  and duplicated completion state. Search lacked bounded matched
  file/line/snippet rows; read lacked a useful code window; edit/write must show
  their true Diff; bash must show ordered output and exit semantics. The four
  canonical renderers remain the only implementation.

The stopped Root and child work remain in the permanent Room/workspace ledger;
no failed or cancelled physical workspace may be silently deleted. A corrected
same-request rerun must prove two real parallel WorkItems, distinct non-empty
Todo/checkpoints, attributed results/diffs, Facilitator integration, independent
review when required, and one final user-facing delivery.

## 2026-08-04 real HTTP foreground findings

Room `Room 浏览器生产闭环验收 20260804` used the real local HTTP transport,
not preview fixtures, with full-auto approval and an isolated TUI workspace.

Verified in the foreground:

- `@澄·今` selected the opening Facilitator.
- Three necessary questions appeared one at a time with described options.
- Selecting an option did not send it; `确认并发送` appended each answer as a
  later user message.
- The understanding summary preceded `开始行动`, and clicking it appended a
  chronological user message before implementation work began.
- A failed Tool argument and an interrupted model response were recovered
  without asking the user; Todo advanced from `0/4` to `1/4`.
- Tool rows were expandable and exposed bounded input and returned content.

Open acceptance failures observed in that same run:

- The top role summary could continue to say `执行失败` after the expanded row
  showed a successful retry, and phrases such as `当前任务推进有新进展` did not
  reveal the concrete work, next action, or completion state.
- Mutable work-summary placement did not reliably communicate bottom-ordered
  chronology.
- Completed Tool result panels could reduce the outcome to generic state instead
  of the meaningful file, output, diff, test, or consequence.
- Durable Todo existed in events but was not visible enough in the role header or
  compact WorkItem view.
- Todo was exposed as a generic completed runtime row whose details repeated only
  aggregate counts. It lacked the item titles and was not fixed at the bottom as
  a continuously refreshed companion work list.
- The task graph showed one large WorkItem with weak hierarchy, excessive empty
  space, sparse node content, and an unattractive/disconnected visual flow.
- Four participants were present, but only the Facilitator owned one real
  WorkItem at the recorded checkpoint. This does not satisfy multi-companion
  parallel acceptance.
- A bounded test-file creation inside the authorized workspace was routed through
  Luna Max and rendered a full approval verdict. This is approval overreach; the
  operation should have been deterministically allowed with only a normal Tool
  receipt.
- Switching to a long Agent/Room participant Session rendered the new-session
  welcome for roughly 0.4–0.6 seconds before replacing it with history. In a
  measured cold load the first real transcript appeared at roughly 1.25 seconds;
  the selected snapshot was about 315 KB and its local HTTP request took roughly
  0.26–0.36 seconds. The false welcome was a frontend state bug, while the full
  lifetime snapshot remains an architectural performance gap requiring bounded
  newest-page hydration and older-history loading.

Current source correction and Web-shell evidence:

- The Agent workspace now tracks history as `loading`, `ready`, or `failed`
  per Session. A slow snapshot shows one animated `正在恢复这段对话` state;
  cached history remains visible; the welcome appears only after a successful
  empty snapshot.
- Focused loading/empty tests and the complete 112-test Agent feature suite
  passed. In local Web switching and forced cold navigation, no sample rendered
  the false welcome. The recovery state remained visible until the real long
  transcript mounted.
- The same pre-fix run took roughly 2.1 seconds to expose the virtual timeline
  and roughly 3 seconds to mount visible articles. The response contained 16
  messages and 194 live events; about 219 KB of compact payload belonged to live
  events alone. The source now requests the newest 80 events and newest 100
  complete turns, returns stable event and message cursors, merges older pages
  by identity while buffering newer SSE events, reconciles the total Session
  message count, and keeps the virtual timeline authoritative. Applying the event bound
  to the measured 195-event fixture reduces the pretty-printed response from
  316,048 bytes to 129,840 bytes (58.9%); real post-install response and render
  timing remain open until the coherent gateway build is installed.
- Mutable Room activity now follows its latest authoritative update time, so an
  updated work summary moves to the chronological bottom instead of appearing
  to change in place above later Tools. The same row and role header derive
  concrete copy from the authoritative task objective and expected delivery,
  without publishing private Provider reasoning. Todo is the final sticky block
  in an expanded WorkItem card. The task graph uses a compact horizontal legend,
  visible parallel/dependency labels, one concrete current or next action per
  node, and moving dashed edges only while the dependency is active. These
  changes passed focused Room tests and the full 974-test Web suite; fresh
  installed foreground evidence is still required.
- Full-auto approval policy now treats a prepared, hash-bound ordinary text
  write/edit/patch inside the granted workspace as deterministic policy work.
  Sensitive paths, out-of-scope paths, and R3 effects remain model-routed. A
  focused service regression proves the bounded write path never calls Luna;
  fresh Room foreground evidence remains required.

## 2026-08-05 source correction and acceptance checkpoint

The most recent foreground Room was
`room:04bf7d88-eb5d-49b1-b060-ef2807fb6af4`. It is evidence of a failed
production attempt, not evidence that the current source works. Only `澄·今`
performed implementation work; no peer implementation WorkItem, independent
review contribution, integration, or final delivery was produced. The run
ended in `runtime_turn_failed` after creating uncommitted `rag_ime/tui.py` and
`tests/test_tui.py`. Running that focused suite now produces four passes and one
error because the streaming test expects `stream_turn` while the implementation
calls only `prompt`. Those files remain intact as the next fresh Room's concrete
recovery input and are excluded from the infrastructure commit until the Room
repairs and verifies them.

Two separate source defects behind the visible symptoms are now corrected:

- A managed turn that completed only by calling `room_commit` carried real
  `openai-codex`, `gpt-5.6-luna`, token, and cache fields in Pi's terminal
  assistant message, but both runtime adapters discarded that Tool-only message
  before `message_completed`. The projection therefore had no evidence to bind
  to the resulting Room Post. Both adapters now publish one bounded
  `response_evidence` event after Room settlement and before `turn_completed`;
  a historical non-authorizing lookup binds it through the exact Session,
  runtime turn, `room_commit` Tool call, capability manifest, applied execution
  receipt, committed Dispatch, and resulting Post. Terminal replay rejects all
  late execution events except response evidence that matches that canonical
  Post; the frontend additionally requires the event turn to equal the evidence
  Root, so a valid Post/Dispatch tuple cannot be inserted into another Room
  turn. The reply footer prefers the newest complete `response_evidence`, falls
  back to a complete normal completed-message event, and skips newer incomplete
  evidence instead of masking older complete evidence. Missing or partial
  evidence no longer emits `模型 / Provider 未上报` filler.
- A normal defined parallel Root did release the fresh Facilitator execute
  Dispatch, but its model-facing `room_state` omitted the peer/reviewer
  obligation and the peer-result completion fence applied only to the older
  managed-ingress path. The execute state now names eligible peer and reviewer
  references, minimum peer work, assigned peer work, review policy, and the next
  action. Final delivery from an ordinary parallel Root is rejected until a real
  eligible peer execute result is public, and the same fence applies before the
  Facilitator may start review. Review targets now include every current
  execute/revise result, including read-only contributions; final delivery
  rejects a review that omits a late implementation or revision. The review
  requirement may be set at `room_define`, is receipted, and cannot be
  downgraded. A Reviewer in the roster remains capacity, not an automatic
  requirement; explicit user/acceptance policy and risk decide whether review
  is required. `room_define` must always submit that decision as an explicit
  boolean; omission or a non-boolean value is rejected so a model mistake cannot
  silently turn a required review off. The runtime never infers the decision
  from example keywords or merely from the presence of a Reviewer.

The remaining Todo continuity gap from the source audit is also corrected.
`checkpoint` is now an operation on the existing Session Todo rather than a
second task system. Each item can retain a bounded natural-language checkpoint,
up to twenty typed references (`file`, `diff`, `artifact`, `test`, `url`, or
`other`), and its own authoritative update time inside the existing
event projection. Migration 0145 rebuilds only the operation constraint and
copies every prior Todo event and Room lineage unchanged. The Python gateway,
managed Pi Tool schema, read-only role profile, generated contracts, Agent
sidebar, and Room task card consume that same contract. A role can therefore
resume from a concrete item and show what changed without creating a parallel
Todo owner or reducing progress to `2/4` counts.

The collaboration calibration now uses one product-agnostic example pair rather
than the TUI acceptance phrase or a particular UI/API shape. Adding recoverable
batch processing through whatever public entry the project already owns—accepting
many inputs, validating and processing each, exposing progress and failures,
retrying failed items, and producing a verifiable result—contains independently
deliverable contract, processing/recovery, and acceptance seams. It should
receive real peer work unless source inspection proves one conflict-prone owner.
A located function-boundary fix plus one focused test is the contrasting
single-owner case. The analogy applies to applications, services, CLIs, and
libraries; production must not branch on any example wording.

Current verification of the combined working tree:

- complete Web suite: 104 files and 976 tests passed;
- the Todo/checkpoint increment passed the complete 97-test affected
  Session/migration/Skill/prompt/runtime-contract/capability set, focused
  gateway execution and static-Pi checks, TypeScript, 151 generated-contract
  reproduction, and the complete Web suite. The full Agent Tool file has one
  remaining environment failure in the governed background-job case because a
  nested `sandbox-exec` cannot enter this Codex sandbox; the Todo and Pi source
  assertions pass when run directly;
- complete Room settlement lifecycle: 49/49 passed, including premature-review,
  read-only review coverage, late-task freshness, and repair/re-review cases;
- focused Tool-only evidence path: Pi v1 (51/51), Pi v2 (80/80), Room
  projection (23/23), real SQLite kernel binding, and Web binding regressions
  passed;
- prompt/role and Room Skill contract suites passed (21/21 and 25/25). The full
  Room Kernel service file produced 96 passes, 2 skips, and one environment
  failure: its governed background-job command could not enter a nested macOS
  sandbox (`sandbox-exec: sandbox_apply: Operation not permitted`) under this
  Codex sandbox, so no ready log could be emitted. This is recorded as an
  environment-blocked foreground check, not a product pass;
- On clean product commit `e72d02677bd62d9452620d1f9450726d40f9e602`,
  TypeScript, 151 generated-contract reproduction, the complete Web suite
  (104 files, 976 tests), production/native Web build, signed App build, static
  transport footprint, route ownership, import boundaries, Python compilation,
  and `git diff --check` passed. The App marker reports `gitDirty: false`, native
  transport, production channel, and that exact commit. A fresh managed Pi v2
  payload also passed its smoke contract and binds product commit `e72d0267` to
  Pi source `98cfe6a3a0a420ac6de4f85153c55fbc8809b845`;
- On clean product commit `bffbd5a2d59ef6117264b06dc06f689e555ec086`,
  the current Todo/checkpoint change re-passed 85 prompt, Skill, Session,
  migration, and runtime-contract tests plus two focused Todo gateway tests,
  151 generated-contract reproduction, TypeScript, import boundaries, route
  ownership, and `git diff --check`. The official production/native build then
  completed its full Web test gate and Vite build, compiled and signed the
  WebKit App, and passed native dist and static-footprint checks. Its clean App
  marker names that exact commit; the executable SHA-256 is
  `879c4da74398797e674aa367d0c2e574cfa791fff00fe67675bd3430e1390ea6`;
- the expanded 422-test backend/runtime set produced 421 passes. Its one
  real-HTTP transport test reached the system proxy and received HTTP 403;
  rerunning only that case with all proxies removed was skipped because this
  sandbox cannot bind the local HTTP listener. It remains environment-blocked
  rather than reported as passed. Python 3.14 also reports existing unclosed
  SQLite/file `ResourceWarning` instances; they did not fail the suite but
  remain cleanup debt rather than silently counted as resolved.

These are source and local-build facts only. An earlier stack install could not
replace files under `~/Library/Application Support/RagIme/BrowserCopilot/extension`.
The later `bffbd5a2` App install rebuilt the verified App but the same Codex
filesystem sandbox rejected every replacement under
`/Users/undo/Applications/RagImeControl.app` with `Operation not permitted`.
Readback proves the installed App remains the older clean `ae71bc07` build; its
binary SHA-256 is
`76f3ccb1d273870eb05377c591c887e329839b60f4e8254088e895b0c433de65`.
A source-tree gateway also cannot bind a fresh loopback port in this sandbox.
The worktree App can be used for intermediate checks, but port `8768` still
serves the older installed build and may be used only as old-state evidence.
Production acceptance still requires installing the coherent
App/Python/Web/managed-Pi stack and completing the fresh foreground flow below.

No row may be promoted to native accepted by unit tests, mock transport, hidden
browser, direct API, screenshot, health response, copied hash, assistant prose,
or terminal state alone.

## Required native foreground acceptance

Use one coherent installed build and one fresh Room in the foreground
`RagImeControl.app`:

1. Record installed app version/build/commit/hash/signature and matching
   App/Web/Python/runtime/managed-Pi provenance.
2. Submit a natural bounded request with a real material choice, such as
   `我想给这个项目加一个能批量导入数据的功能`; do not include protocol
   instructions, canned answers, role assignments, or the intended task split.
3. If real ambiguity exists, answer the single bounded clarification round.
   Verify grouped questions when several independent choices exist and the
   native option box when exactly one mutually exclusive choice exists. On both
   ambiguous and fully specified paths, inspect the user-language vertical plan
   and click `开始行动` only after the natural understanding summary.
4. Observe distinct Facilitator and peer ownership, at least two real parallel
   WorkItems when appropriate, each owner's Todo and attributed result/diff,
   real Tool/activity updates, one bounded nested subagent, delivery,
   Facilitator integration, required-canary independent review, and one final.
5. Exercise `read`, `edit`, `write`, and `bash` through real governed work. Verify
   that no `workspace_*`, `write_file`, or other alias appears as a second public
   Tool; each call has its personalized compact row, truthful active animation,
   ordered incremental output, in-place folding, semantic completion/failure,
   and retained recovery detail. Confirm `edit` and `write` expose the actual
   attributed Diff and `bash` exposes bounded stdout/stderr plus exit status.
6. Verify the requested artifact and focused checks in the governed workspace.
   Confirm successful child cleanup and retained danger workspaces match the
   permanent ledger.
7. Reload the same Room and confirm chronology, tasks, activity, provenance,
   review, workspace state, and one final remain coherent. Switch between a
   cached long Session, an uncached long Session, and a real empty Session;
   confirm there is no false welcome/blank flash, the recovery state appears
   immediately when needed, and older history loads without moving the reader.
8. Correlate the visible flow with durable receipts and installed provenance.
   Any fake activity, skipped implementation, missing integration/review,
   incomplete artifact, duplicate final, or mismatch keeps acceptance open.
9. In full-auto mode, inject at least one recoverable command or Tool-argument
   failure and one transient Provider failure. Confirm the owning companion
   repairs or retries it, the Facilitator continues the plan, the user is not
   asked to handle the intermediate error, the expanded Tool row preserves the
   attempt details, and the Room still reaches verified delivery. Restart once
   after a durable checkpoint and confirm work resumes without duplicating
   completed Todo, workspaces, messages, or the final report.

## Explicit non-goals

- mandatory clarification questions for every request
- a user-editable task graph or frontend orchestrator
- a permanent global commander or master/slave companion tree
- ownership inferred from display names or later mentions
- a second Ask Tool, Room state store, event bus, Todo implementation, or cost
  schema
- a second public basic coding Tool, alias-specific execution path, or duplicate
  frontend renderer beside canonical `read`, `edit`, `write`, and `bash`
- prompt-specific `写 TUI` behavior
- loading all stage Skills into every prompt
- exposing hidden reasoning or private subagent transcript
- claiming production completion from source-only or diagnostic evidence
