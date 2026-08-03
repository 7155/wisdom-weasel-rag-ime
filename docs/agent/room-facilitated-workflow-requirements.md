# Room Product Contract And Implementation Audit

- Document class: the single authoritative Room product contract and dated implementation ledger
- Contract status: approved through the 2026-08-03 conversation-first, live-activity, workspace-lifecycle, and native-GUI acceptance realignment
- Implementation status: 2026-08-03 source remediation and dead-version cleanup are complete; fresh independent re-review, coherent installation, and native foreground acceptance remain open
- Decision window: prefer decisions made on or after 2026-08-02
- Scope: Room V2 intake, collaboration, nested delegation, review, settlement, and the Control Center conversation/task surfaces
- Authority: this file is the only current product and implementation-status authority. Older checkpoints, handoffs, previews, tests, README prose, and implementation notes are evidence or navigation only and cannot override it.
- Change rule: append later user corrections to `User Source`; never rewrite earlier user text. Update implementation status only from inspected source, fresh tests, or installed foreground evidence.

## User Source · immutable

The following source text is preserved in the user's language and chronological order. It is normative input; the derived contract below may clarify it but must not overwrite it.

<!-- USER_SOURCE_BEGIN -->

> 1，默认她，但是@就可以改。2.这个图就可以分配多个任务，多个agent并行，形成图结构。你还有其他问题吗，用alin对齐技能

> 这个ui是不对的，用户输入任务，一个ai来接，然后判断是否需要对齐，对齐弹出选项，选了应该按时间先后出现消息。然后直到问题问完，询问开始行动。执行前门禁 · 并行
> **需求对齐所以不是必须的。图只是可视化，不然太复杂**

> 先展示一下聊天界面是怎么信息流的，这个前端也重要

> 如果 AI 判断完全不需要澄清，就不用确认了

```text
用户：@澄·今 我准备写 TUI
澄·今：我来接手，还有一个会影响实现方式的问题
          [选项卡]

用户：终端原生 TUI

澄·今：首版最重要的交付边界是什么？
          [选项卡]

用户：先完成可运行闭环

澄·今：已经对齐……现在开始行动吗？
          [开始行动]

用户：开始行动

澄·今：我把工作拆成两项并行任务……
澄·远：我负责 TUI 界面实现……
澄·今：我正在完成状态模型与集成准备……
澄·远：实现和测试完成，交回澄·今
澄·今：已完成集成，交给澄·初独立复核
澄·初：提交审查 Findings……
澄·今：最终总结这个很不错
```

> 然后这个任务页面是专门展示的，任务进度，分工，内容，和每个agent的subagent（这个是为了展示我们和主从多agent的区别）。你看文档主要看8月2号之后的，这个才是我最近讨论对齐最新的想法

> 这些流程是有专门的对齐和实施技能的，常驻加载来保证流程你看看

> 相当于我们现在重新梳理，不就不用管就文档的那些旧内容了

> 然后因为是多agent的模式。每个角色还是得暴露一下当前在干什么在大框下面滚动更新最近在干什么（思维摘要和tool），调用了哪些工具（可以展开看输出），完成情况。还有就是并行工作的话，还有worktree的愿景你找到了吗，不清楚的话grillme

> worktree也得记录，比如技能写的文档就得记录哪些room的agent在哪些需求上建立wt，最后合并得统一，因为有的wt会忘记什么时候谁为了完成什么功能建立的

> 双面同源、不同密度（推荐）：对话页角色大卡持续显示完整实时活动；任务页 WorkItem 默认只显示最新摘要和完成情况，点击后在卡内展开同一份活动记录。图继续只是概览。

> 这个信息就缺少时间性和流动性，用户等待就感觉这个没变，就只有步骤数量变动，不是好的交互。推荐：成功集成后自动清理物理 worktree并永久保留台账；失败、阻塞、取消、冲突或孤儿 worktree 一律保留并标红，直到 Facilitator 明确重试或带快照/hash Receipt 放弃。

> 没问题，前端就是应该多刷新显示信息，才能让用户感觉agent在认真疯狂干活，用户就会很舒服。

> 下一步应以这套最新愿景建立唯一权威文档，再逐项审计“已实现、部分实现、未实现”

> 测试最后验收结果，就是，你在前端gui，进行输入，用用户语气，比如我要完成tui。然后她问你需求，你对齐，等等等等，然后就完成这个具体任务。得符合我的需求

> room也得支持todo，这样做就不用两个不同的实现，就只要前端任务界面可以展示每个角色的todo就行

> 还有把mat的技能库里面的debug和优化代码的技能也加入

> 每个角色的diff和成果也得展示，这样做用户才知道角色改了哪些代码，出了哪些文件和结果，就像这个图

> 过程中顺便清理那些什么v1v2啥的，就保留用的就行，代码太乱了

<!-- USER_SOURCE_END -->

Screenshot source receipts:

| Source | SHA-256 |
| --- | --- |
| `codex-clipboard-093aee0f-f4c0-4f71-a5a7-0d8b1e526058.png` | `97d6b9d7d95db03830479120e77c1495299046d628682d0a82b3e21c8a2fca08` |
| `codex-clipboard-7e02d987-e293-4383-9ace-2e4d38afa854.png` | `387f2108c5f3afeb2844fe53a0589537979323755b068a84d012775ba2557761` |
| `codex-clipboard-f0d24cae-79f0-428d-b23d-1025b45b54cf.png` | `f8071e69773121b6fd557bd35c4ae2d299d587f7aa8ec63ef3df53771af5446e` |
| `codex-clipboard-8ce2e2c5-fb5a-4ed4-8a5f-b68b8e997ace.png` | `46192b6dd262e6f684efa86f2e89ef5314d53edc9763d8fdfb6253ac2bd5d7de` |
| `codex-clipboard-d8709918-67b4-4bb3-abb0-e710038f41ab.png` | `6ea642a56dc9a9c0c2bbcc765f11a73b525b0a97c75710acdab6c6fc8af452a8` |
| `codex-clipboard-daf0dc2c-a092-40ce-b6a5-8245abe0991a.png` | `cfda53ba1ef60af877345b31ce7e1b4b2b448a41ec126df5777743f7a0aae9e5` |

User Source marker-body UTF-8 SHA-256 (markers excluded): `1e62a28d7426ac6975cc4981ce2fe5c41c2dcd03953a37ab6749895bfe0bd870`

## Product goal

Room should feel like a natural conversation that can turn into governed, visible multi-Agent work. The user talks to one companion first. That companion clarifies only when a material decision is missing, then multiple Room companions can own peer work slices, each companion may use bounded private subagents, one Facilitator integrates the result, independent review is used when policy requires it, and exactly one final report returns to the user.

The conversation is the primary interaction surface. The Tasks page is a dedicated, read-only work view for progress, division of work, task content, dependencies, each Room companion's bounded subagents, review, and final delivery. It is not an execution gate or a second orchestrator.

## Latest user-visible flow

### Facilitator selection

- The default initial Facilitator is `澄·远`.
- One explicit companion mention in the opening user message selects a different initial Facilitator. For example, `@澄·今 我准备写 TUI` is received by `澄·今`.
- After the Root exists, ordinary `@` mentions are communication only. They do not silently transfer ownership, create WorkItems, or start Dispatches.
- The Facilitator owns requirement decisions, decomposition, assignment, dependency handling, integration, the review decision, and the one final user-facing report. This is workflow accountability, not a master/slave hierarchy over the other Room companions.

### Conditional clarification

The receiving companion first inspects facts that are already reachable from the repository and runtime, then decides whether a material user-owned choice is missing.

- If no material clarification is needed, do not show a confirmation gate and do not ask the user to repeat an approval phrase. The opening user request authorizes execution, and the Facilitator proceeds directly to definition, planning, and action.
- If clarification is needed, ask one question at a time in normal chronological chat. Use 2–5 single-select options with at most one recommendation when the choice set is honest and bounded; otherwise allow a free-form answer.
- Selecting an option creates a new ordinary user message after the question. The answered question card remains in place and locks; it is not the only record of the answer.
- The Facilitator asks the next dependent question only after that answer appears. Questions are not presented as a parallel `0/N confirmed` execution gate.
- When all necessary questions are answered, the Facilitator briefly summarizes the aligned goal and asks `现在开始行动吗？`. The `开始行动` control is shown only on this clarification path.
- Selecting it creates a chronological user message such as `开始行动`. No Worker or Reviewer starts before this action.
- Whether the runtime uses a private intake/alignment Dispatch to support this decision is an implementation detail. It must not make requirement alignment mandatory in the UI or retain execute capability after definition.

### Canonical conversation acceptance example

```text
用户：@澄·今 我准备写 TUI
澄·今：我来接手，还有一个会影响实现方式的问题
          [选项卡]

用户：终端原生 TUI

澄·今：首版最重要的交付边界是什么？
          [选项卡]

用户：先完成可运行闭环

澄·今：已经对齐……现在开始行动吗？
          [开始行动]

用户：开始行动

澄·今：我把工作拆成两项并行任务……
澄·远：我负责 TUI 界面实现……
澄·今：我正在完成状态模型与集成准备……
澄·远：实现和测试完成，交回澄·今
澄·今：已完成集成，交给澄·初独立复核
澄·初：提交审查 Findings……
澄·今：最终总结……
```

This transcript fixes ordering and role semantics, not literal generated wording. Production behavior must never branch on the string `写 TUI`, fixed answers, companion display names, or a preview fixture.

## Stage-resident workflow Skills

The conversation and execution flow are backed by governed managed-Pi Skills, not only by prompt wording or frontend state. “Resident” means one exact required Skill remains bound to the active Dispatch/Session context epoch for its current stage; it does not mean that every Skill body is injected into every prompt.

- `align` / requirements and solution stages require `alignment-and-decision`. That Skill requires fact inspection before asking, reserves questions for material user-owned choices, and explicitly says a complete request needs no fixed confirmation phrase.
- planning requires `implementation-planning` when the lifecycle enters that stage.
- `execute`, `resume`, and ordinary implementation work require `implementation-execution`; `retry` selects its debugging route and `revise` selects its feedback route. This Skill starts only after definition/handoff, preserves accepted requirements, implements bounded evidence-producing slices, and stops on cancellation or no progress.
- Unknown defects and performance regressions use the governed `diagnosing-bugs` method from Matt Pocock's skill library: build a red-capable feedback loop, reproduce and minimise, rank falsifiable hypotheses, instrument one prediction at a time, then fix and regression-test. It is a method Skill selected inside an authorized implementation/retry lane; it cannot create work or widen capability.
- Explicit codebase-architecture improvement uses the governed `improve-codebase-architecture` method from the same library. It inspects real friction and proposes a small evidence-backed shortlist before refactoring. It does not run automatically after every task, and selection never bypasses alignment, planning, workspace, review, or user-decision gates.
- self-check/closure requires `quality-gate`; independent review requires `independent-review`; responsibility transfer uses `structured-handoff`.
- The Kernel Dispatch intent selects the required stage. Skills never select their own Dispatch, widen capability, settle a Root, or replace Kernel gates.
- Managed Pi loads the exact required Skill body and returns a `roomSkillLoad` receipt. The product pins Skill name/hash, policy revision, Root/Task/Dispatch/Session lineage, capability epoch, and load reason. A mismatched or stale load fails closed.
- If the required Skill changes between stages, the idle managed Pi Session is closed and reopened with the new stage Skill. Compaction recovery restores/verifies the exact pinned Skill revision without duplicating arbitrary Skill text into another context owner.
- The stage Skill is a behavioral guard, not proof of execution. Work still requires authoritative Dispatches, Tool/capability receipts, evidence, review policy, and installed foreground acceptance.

## Collaboration ownership

### Facilitator

- Owns the current Root's requirement revision, WorkItem plan, assignment, reassignment, dependency handling, integration, review policy application, and final report.
- May implement or integrate work, but cannot independently review its own authored or integrated result.
- Parallelizes only genuinely independent, non-overlapping slices when doing so materially reduces waiting.
- Uses existing eligible Room companions first. Adding a companion requires an explicit roster operation; a mention is not an assignment.

### Room companion / Worker

- Receives a structured WorkItem with objective, expected output, acceptance criteria, dependencies, owner, and workspace policy.
- Owns a visible, concrete slice and may publish eligible progress, evidence, and a handoff. It does not publish a competing final answer.
- May reject an assignment with a structured reason such as missing capability, permission, dependency, or usable context. The Facilitator repairs or reassigns the work.
- May launch bounded nested subagents for narrower checks. The companion remains accountable for verifying and integrating their results.

### Nested subagent

- Is a bounded private child Session owned by its parent companion's delegation batch/run.
- Is not a Room participant, cannot own or settle the Root/Task, cannot ask the Room user directly, and cannot publish private transcript or hidden reasoning.
- Returns a bounded result/error to the parent as evidence. Child completion is not automatic WorkItem acceptance.
- Is fenced by task lineage, generation, budget, timeout, cancellation, and delegation-depth rules. Late output cannot revive cancelled Room work.

### Reviewer

- Reviews the integrated result against the latest requirement revision and ReviewTarget, not each ordinary child action.
- Must be distinct from the authors and Integrator of the reviewed target and normally uses fresh, read-only context.
- Submits structured Findings and a recommendation. The Kernel derives the authoritative Verdict; reviewer prose does not directly settle the Root.
- Does not fix a finding and approve its own fix.

### Kernel

- Owns Root, Task, WorkItem, Dispatch, capability lease, requirement revision, wait epoch, receipt, ReviewTarget, Finding, Verdict, cancellation, and terminal state.
- Natural-language claims, mentions, filesystem paths, child completion, screenshots, or frontend state cannot create ownership or prove settlement.
- Fails closed when evidence is stale, foreign, incomplete, invalid, or unauthorized. A recoverable Tool/provider failure may retry within policy; it does not permanently kill the Root merely because one attempt failed.

## Authoritative lifecycle and safety invariants

1. The user submits one opening goal, optionally selecting the initial Facilitator with one explicit `@` mention.
2. The Facilitator performs bounded intake and chooses the no-clarification or clarification branch described above.
3. Every accepted answer appends a new RequirementAnchor/RequirementItem revision and an ordinary user RoomPost. Each `(rootId, questionId, answerRevision)` may resume at most once; one Root may legitimately resume for several different questions.
4. A superseding answer appends a later revision. History is not rewritten, and stale, unrelated, superseded, or already-consumed answers cannot resume work.
5. If clarification occurred, the user must select `开始行动` after the final summary. If no clarification was needed, the opening request already supplies execution intent.
6. `room_define` is an atomic, idempotent transition. It validates the current requirement revision and acceptance criteria, binds them to the existing Root/Task, creates or confirms the accountable root WorkItem, completes/fences any intake Dispatch, and records the transition receipt.
7. Execution starts through a new Facilitator ExecuteDispatch with a new Dispatch identity, capability lease, and epoch. The old intake/alignment Dispatch never gains execute Tools; late calls from it are rejected. Dangerous Tools still require their independent approval policy.
8. The Facilitator creates structured WorkItems. The Kernel creates directed Dispatches; `room_collaborate` may create bounded, non-overlapping implementation work only after definition and is never an intake fanout or frontend assignment path.
9. Independent WorkItems may run in parallel. Dependent work remains serial. Workers return artifacts, focused verification receipts, and residual risks to the Facilitator.
10. The Facilitator integrates accepted results in one authoritative integration workspace.
11. General product review is selected by Facilitator risk unless the Root's `reviewPolicy` requires it. The current three-companion `写 TUI` production canary sets review required; this must not be implemented with prompt/display-name special cases.
12. After review acceptance and repair closure, the Root reaches `workQuiescent`, then `ready_to_report`.
13. The Kernel creates one read-only ReportDispatch/final-report lease. The Facilitator publishes exactly one final report, a reporter terminal receipt is recorded, and only then may `runtimeQuiescent` lead to Root `completed`.

### Wait/resume semantics

- Each wait has an explicit wait epoch and owner. A completion, failure, cancellation, timeout, or accepted user answer may satisfy its declared resume condition.
- A Dispatch cannot wait on itself, create a wait cycle, or continue writing while suspended.
- Resume is idempotent per wait epoch. Reconnect or duplicate transport delivery cannot create duplicate Dispatches.

### Review governance

- The Kernel derives one of `accepted`, `accepted_with_notes`, `changes_requested`, or `disputed` from admitted Findings and current evidence.
- A blocking Finding must bind the current acceptance criterion or constraint, current ReviewTarget and requirement/artifact revision, evidence from that revision, a reproduction or failing check, and user impact.
- Stale, duplicate, unactionable, out-of-scope, or unsupported findings cannot block settlement.
- Repair and re-review are limited to the affected finding/target scope. Two failed rechecks of the same Finding escalate it instead of creating an unbounded loop.
- A dispute gets one Reviewer reconsideration. If still disputed, use a finding-scoped independent Arbiter or ask the user to choose the residual risk; do not restart the whole Room by default.
- Advisories must be resolved, dismissed with evidence, or explicitly accepted as residual risk before final reporting.

## Workspace and parallelism policy

- A small coherent single-writer task uses the current governed workspace.
- Read-only independent investigation may run concurrently against the same baseline.
- Concurrent writable WorkItems use separately receipted isolated workspaces based on the same Root baseline.
- Exactly one Facilitator/Integrator owns the authoritative integration workspace.
- Filesystem paths do not prove participant identity, workspace isolation, or accepted evidence.

### Workspace ledger and ownership

- An isolated workspace/worktree belongs to one writable WorkItem responsibility, not to a companion persona. The same companion may own different WorkItems over time; those bindings remain separate ledger entries.
- Kernel/workspace receipts are authoritative. A Skill-owned WorkDocument may mirror a compact `Workspace Ledger` for recovery, but it cannot create ownership, prove isolation, authorize integration, or decide cleanup.
- Every materialized writable workspace records at least: `workspaceBindingId`, Room/Root/Task/WorkItem/Dispatch lineage, requirement revision and acceptance aliases, participant and Session binding, repository identity, common Root baseline commit, physical path, workspace policy, creation reason/time, lease and ownership history, delivery revision, integration state/ref, terminal reason, cleanup policy/state, and the receipts/hashes that authorize every transition.
- Read-only Workers and Reviewers may share an immutable baseline when policy permits. Every concurrent writer receives a separate receipted workspace from the same Root baseline. No two concurrent participants write the authoritative integration workspace or the same delivery artifact set.
- Worker `deliver` records artifacts, focused verification, residual risk, workspace head/snapshot, and an integration-pending receipt. Delivery alone never mutates the canonical branch and never satisfies Root completion.
- Only the Facilitator/Integrator may apply a delivered workspace to the authoritative integration workspace through a bounded, idempotent integration operation. Conflict leaves the delivery and source workspace intact.

### Workspace retention and cleanup

- After successful integration, the Kernel records the integrated commit/artifact revision and a hash-bound integration receipt. Only then may it automatically remove the physical child worktree. The logical ledger, ownership history, evidence, hashes, and cleanup receipt are retained permanently.
- A failed, blocked, cancelled, conflicting, orphaned, incompletely delivered, or unintegrated workspace is never automatically deleted. It remains physically present, appears as `需要处理`/danger in the Tasks projection, and keeps its last verifiable snapshot/hash.
- An orphan means authoritative ownership/lease has ended or cannot be recovered while the physical workspace or unintegrated delivery still exists. Discovery marks it for attention; it does not silently adopt or delete it.
- A retained workspace leaves the attention state only when the Facilitator either issues an explicit retry/rebind receipt, or explicitly abandons it with reason, actor, time, snapshot/hash, affected acceptance aliases, and a durable abandonment receipt. Abandonment may then authorize cleanup but never erases the ledger.
- Cleanup is idempotent and scoped to the exact receipted path. Missing-path cleanup records the observed result; it does not broaden the deletion target or infer success from a parent directory.
- Workspace lifecycle events (`materialized`, `work_started`, `delivered`, `integration_started`, `integrated`, `conflict`, `retained`, `retry_bound`, `abandoned`, `cleaned`) are ordinary authoritative activity inputs for both UI surfaces.

## Persona and public speaking style (“语音风格”)

- In this contract, the user's “语音风格” means companions' **public textual
  language**: ordinary user-facing wording, no internal protocol vocabulary, no copied
  Cat Cafe mannerisms, and no generic repeated Facilitator final across participant
  lanes.
- This does not mean spoken output. Current product scope has **voice input only**;
  Agent and Room companions do not produce audio or TTS.
- Persona and collaboration responsibility are orthogonal prompt owners. Persona owns
  stable identity and tone; the current Facilitator/Worker/Reviewer role owns what the
  companion must communicate for this WorkItem. Neither layer may change facts,
  permissions, Tool policy, Kernel state, or acceptance.
- The production persona voices are:
  - `澄·远` — calm, clear, structured; fixes the real problem first, then dependencies,
    trade-offs, and the verification loop; depth without unnecessary length.
  - `澄·今` — warm, direct, pragmatic; receives the immediate problem first and offers
    the easiest valid next step; explains complexity without inflating simple work.
  - `澄·初` — bright, curious, restrained; finds key names, times, and relationships,
    asks few precise questions, and keeps clues distinct from facts.
  - `澄·瞬` — short, fast, clean; scans large material for decision-changing signals,
    keeps only key excerpts/conflicts/gaps, and hands off beyond rapid triage instead of
    presenting speed as certainty.
- The active collaboration role then shapes public content:
  - Facilitator: alignment, plan, assignments, integration, and the only final report.
  - Worker: owned slice, meaningful progress, evidence-backed result, and explicit
    handoff; never a competing product-wide final.
  - Reviewer: review scope, Findings, evidence, disposition, and residual risk;
    independent from implementation and never falsely certain.
- Public messages use ordinary user language and preserve each companion's voice while
  remaining concise and non-repetitive. Do not expose `Kernel`, `Root`, `Dispatch`,
  `Task`, `AC`, receipt IDs, private reasoning, or protocol JSON. Do not copy Cat Cafe
  characters, role-play mannerisms, or a generic identical “Facilitator voice” across
  every lane.
- Voice-input transcription and cleanup remain a separate owned pipeline. They preserve
  the user's meaning, facts, tone, person, numbers, English, code, and proper nouns;
  they do not become Agent/Room speech synthesis or authorize persona rewriting.

## Control Center conversation surface

- Preserve one chronological Room timeline. Do not replace it with a large red `执行前门禁 · 并行` panel or create a second activity feed.
- A question is an inline component in the asking companion's message. A selected/custom answer appears as the next user message and the original card locks as answered.
- Only one dependent question is active at a time. A later question appears after the previous user answer.
- The `开始行动` control appears only after a real clarification sequence. A fully specified request begins action without another confirmation.
- After action begins, companions speak in role-specific natural language: Facilitator plan/integration/final, Worker owned slice/result/handoff, Reviewer scope/Findings/residual risk.
- Publish at most one conversational update per participant per logical work round. Tool start/progress/finish/retry/wait updates one stable activity surface rather than creating chat-bubble spam.
- Safe reasoning summaries are labelled `工作摘要`. Never expose hidden chain-of-thought, system/developer prompts, private peer traffic, credentials, raw unredacted Tool output, or internal receipt IDs.

### Live activity, time, and perceived flow

The interface should feel active because verifiable work facts keep arriving, not because the client fabricates motion. Aggregate step counts are secondary summaries and never the sole progress signal.

- Each role card continuously answers four questions: what this companion is doing now, what last changed and when, why it is waiting when applicable, and what event or time can move it next.
- The card header shows semantic state plus current public action, `最近更新 HH:mm:ss · N 秒前`, and secondary total duration. Completion shows finish time and duration.
- The full conversation card contains one bounded chronological activity stream. Each real event displays time and semantic status; Tool start/progress/finish updates one stable row keyed by authoritative Tool/event identity. Arguments and redacted output expand inside that row.
- Public `工作摘要` may state current objective, inspected area, key finding, next step, blocker, and risk. It is not hidden reasoning and cannot be generated merely to make the interface look busy.
- New authoritative events appear promptly with restrained 180–220ms entry feedback. When the reader is at the bottom the stream follows new events; manual upward scrolling suspends follow and exposes `回到最新`.
- Client timers may update elapsed time or an authoritative retry countdown once per second, but they do not refresh `最近更新`, create activity events, or imply ongoing work. Transport/SSE heartbeats are connectivity evidence only and never work progress.
- A running animation is allowed only while a fresh authoritative Tool/work activity is active. It stops on wait, settle, disconnect, or expired progress evidence and respects reduced motion.
- Waiting state exposes wait target/reason, start time, resume condition, and next retry/check time when one exists. If no automatic resume exists, say so and expose the permitted Facilitator/user action instead of running an indefinite animation.
- The projection distinguishes `正在执行`, `正常等待`, `可能停滞`, `阻塞`, and terminal states from authoritative lease, Tool, timeout, wait, and retry evidence. The frontend does not invent a universal timeout or settle state locally.
- Primary copy uses user meaning (`等待集成冲突处理`, `需要你确认`) rather than leading with `room_commit`, Root, Dispatch, Kernel, receipt IDs, or raw protocol errors. Technical details remain expandable.

## Dedicated Tasks surface

The `任务` tab is a first-class, dedicated view. It must answer: what work exists, who owns each part, what each part contains, which parts can run in parallel, what is blocked, what has been verified, which nested subagents each companion used, and how the Room reaches review and result.

It follows the approved `双面同源、不同密度` rule: the conversation role card shows the complete bounded live activity stream; each Tasks WorkItem defaults to the latest activity summary, completion/evidence state, and last-update time, then expands the same underlying events inside the card. The task graph remains a structural overview and never duplicates the activity owner.

### Two visible collaboration levels

- Top level: Room companions are peer collaborators with durable public responsibility. The Facilitator has coordination/integration responsibility but is not drawn as a master controlling anonymous slaves.
- Nested level: each companion's bounded subagents appear inside or immediately beneath that companion's owned WorkItem. Their indentation/containment must make clear that they are temporary helpers, not equal Room companions or separate delivery owners.
- This two-level projection is the visible product distinction from a single-master/many-subagents system: several accountable Room companions can work in parallel, and each may independently use bounded children for its own slice.

### Graph and task-card content

- The main flow is `Room goal -> peer-owned WorkItems -> integration -> optional/required review -> result`.
- Multiple independent WorkItems form parallel branches; real prerequisites and delivery relationships form directed edges. Chat mentions never create edges.
- Each WorkItem card shows, in readable priority: objective or result, owner avatar/name, concrete task content and expected output, semantic state, current action/next step, dependency/blocker/wait target, touched public artifacts/files when available, and verification state.
- Each companion's WorkItem section projects that companion's authoritative Todo items from the existing Todo/task owner. Todo is one finer-grained execution view beneath the WorkItem, not a second Room task implementation or frontend-owned checklist. It shows item text, semantic state, current/blocked item, and completion progress; reconnect preserves the same identities and order.
- Each companion's result section shows her own delivered outputs: created/changed files or other artifacts, per-file added/deleted line counts when a textual diff exists, focused checks, produced result, and residual risk. Attribution must come from that WorkItem's receipted workspace/delivery revision. Never label a repository-wide dirty diff, another companion's patch, generated/cache/private files, or an unintegrated result as that companion's contribution.
- Diff is a readable contribution summary by default (`file`, `+N`, `-N`), with bounded expandable patch/audit detail when safe. Binary/generated/private content is represented semantically rather than dumping raw data. Integration may show the accepted combined revision separately without erasing per-companion provenance.
- Aggregate counts show completed, active, waiting, and attention-needed work.
- Nested subagent rows are grouped by the parent task/companion and may show public-safe template/role, ordinal, bounded task, state, budget/usage, result or safe error, and timing. Do not expose child transcript, hidden reasoning, private context, or protocol IDs.
- WorkItem details show the current workspace binding and lifecycle in user language: whether an isolated worktree exists, its owner/responsibility and baseline, delivery/integration state, and whether the physical workspace was cleaned or retained for attention. Raw paths and hashes stay in expandable audit details.
- Runtime duration, attempts, raw Dispatch/Receipt identifiers, and similar diagnostics remain in details/debug views unless anomalous.
- The graph and nested-run sections are read-only projections of Kernel/Event Store and delegation-store state. Users do not drag nodes, draw dependencies, or assign work by editing the graph; React does not infer or settle lifecycle.
- Desktop and narrow layouts preserve hierarchy, reading order, keyboard access, text/icon status, and reduced-motion behavior.

## Event, history, and provenance contract

- The timeline and Tasks page are two projections of the same authoritative Room state, not independent histories.
- Every projected event carries stable identity including `eventId`, `roomSequence`, `rootId`, `dispatchId`, `participantId`, `sourceSessionId/sourceMessageId`, `eventKind`, and `generation` when applicable.
- Merge and reconnect order by server sequence and stable event identity. Never deduplicate different events merely because their text matches.
- Snapshot reload preserves answered cards, chronological user answers, task/subagent hierarchy, settled Tool activity, attributed contributions, and exactly one final result.
- Every completed assistant response carries its actual Provider and model plus runtime-reported token/cache usage. Usage fields are tri-state: `reported`, `not_reported`, or `not_applicable`; missing data is never rendered as a fabricated zero.
- Todo and contribution projections retain stable owner and WorkItem lineage. A delivered artifact/diff summary binds the exact workspace baseline, delivery snapshot/revision, and integration disposition so reload cannot reassign one companion's work to another.
- Provenance belongs to the response that caused the Provider calls. Task-level cost aggregation remains out of scope.

## Implementation audit snapshot · 2026-08-03

### Current independent-review remediation ledger

The latest frozen independent review inspected review-only snapshot commit
`2e55925f73ded02c3cf49ddf298a752842a978e6`, tree
`f3777c23b103319c7dd4b6e1a111a780433163f2`. That snapshot deliberately
included this otherwise ignored document and therefore is not an installable
release artifact. The review found one P0, six P1, and one P2 product defects.
All eight findings now have source fixes and focused regression evidence in the
canonical worktree. The following table is the current status authority;
`source-fixed, re-review open` never means production accepted.

| Finding | Severity | Current status | Required closing evidence |
| --- | --- | --- | --- |
| Integration could apply a child-workspace mutation made after delivery | P0 | `source-fixed, re-review open` | Exact delivery revision/snapshot/patch lease, mutation and TOCTOU negative tests, rollback/retention proof, then independent review. |
| One Session Todo could be copied onto several same-Session WorkItems | P1 | `source-fixed, re-review open` | Todo `roomLineage` is bound to Room/Root/Task/WorkItem/Dispatch/Session/participant/generation and revisions; backend and frontend same-Session multi-WorkItem negatives are green. |
| A large mandatory private alignment rail contradicted conversation-first conditional clarification | P1 | `source-fixed, re-review open` | No `0/N`/parallel-confirm rail in the real conversation; real question cards and clarification-only start remain. Focused Room UI test must stay green. |
| Answer requests did not carry exact question/Root/wait identity, so an ordinary message could resume the latest wait | P1 | `source-fixed, re-review open` | Route, application, Kernel consumption, durable event, and UI body bind `answerToPostId` plus `answerToRootId`; wrong question/Root and identity-free messages fail closed. |
| Reload lifted non-answer user posts above all role lanes and lane grouping changed A/B/A into A/A/B | P1 | `source-fixed, re-review open` | `RoomPost.chronology` carries authoritative Room event identity/sequence/time/anchor; one global stream preserves question/answer/aligned summary/start and A/B/A in live and replay tests. |
| Different authoritative events with equal normalized text were deduplicated | P1 | `source-fixed, re-review open` | Coalescing now requires an explicit shared source alias; equal text with different authoritative identities remains visible. |
| Running motion and elapsed UI survived stale/disconnected evidence indefinitely | P1 | `source-fixed, re-review open` | Semantic running state is separate from motion eligibility; non-synced or older-than-15-second evidence stops animation and reports freshness, while a fresh reconnect resumes it. |
| Internal ReportDispatch appeared as an extra peer Task/Todo card in addition to the result | P2 | `source-fixed, re-review open` | Backend emits `taskKind=report`; peer graph/count/cards/Todo exclude it; the canonical final Post/receipt remains the single result node. Focused frontend tests are green. |

The frozen review also confirmed source paths for opening Facilitator selection,
conditional direct action, fresh execute dispatch after definition, bounded
nested delegation, review governance, reporter fencing, unique final settlement,
workspace retention/cleanup, and persona layers. Those paths still require a
new fixed snapshot, independent re-review, coherent installation, and the
foreground native acceptance procedure below. The old installed application is
not current evidence.

Current source verification before the new review freeze:

- Backend remediation selections passed: core Room set `74/74`, capability
  policy `11/11`, lifecycle cancellation `12/12`, and the prior focused Room
  combination `80/80`; typed-start, Report/Todo, answer-identity, delivery
  immutability, and workspace TOCTOU negatives are included in those focused
  selections.
- Frontend chronology/freshness lane passed `163/163`; the merged Room and
  shared-contract selection passed `290/290`; `pnpm typecheck` passed.
- Contract generation is reproducible at `152` schemas. Kernel-contract,
  database-migration, and shadow-ledger selections passed `28/28`; workspace
  LSP passed `8/8`; `git diff --check` passed.
- These are source receipts only. They do not replace independent review,
  installation provenance, or native foreground acceptance.

### Versioned contract cleanup

The version suffix is a wire/persistence version, not a cleanup signal by
itself. The 2026-08-03 reference-graph audit removed five declarations with no
live product consumer: `room-task.v2`, `room-legacy-ref.v1`,
`room-peer-invitation.v1`, `room-rollout-policy.v1`, and
`room-rollout-receipt.v1`, together with their generated TypeScript mirrors and
dead registry entries. The database migration test retains a synthetic
`room-task.v2` payload because migration `0124` is the proof that stored Tasks
are upgraded to v3.

`room-root-execution.v2`, `room-commit.v2`, and `room-commit.v3` remain on
purpose. They were real persisted formats, old Root/Commit payloads are still
read raw, and no complete read upcaster exists. Deleting them would break
upgrade/replay for existing users. They may be removed only after a tested
v2/v3-to-current read upcaster covers old databases; immutable historical
Commit rows must not be rewritten merely to make the source tree look newer.
Current v1/v2 contracts with route, runtime, projection, Skill, receipt, or DB
consumers also remain authoritative.

### Historical pre-remediation baseline audit

The detailed tables below preserve the earlier dirty-worktree audit at
`9f9fc3311395573ab9c90d6c23753a9fc28ccb7b` so evidence is not rewritten. Their
row statuses are superseded by the current remediation ledger above and must
not be quoted as current completion counts. `implemented` meant only that the
inspected source contained a structural gate and focused tests exercised it;
it never implied installed acceptance. `installed-unverified` and
`native-failed` still override source or test evidence for production claims.

The worktree was `main`, four commits ahead of `origin/main`, with extensive pre-existing uncommitted Room and unrelated changes. The audits were read-only apart from this document. No old `28/35`, “seven remaining”, test count, screenshot, preview, or prior handoff may be used as the current completion measure.

### Intake, execution, review, and settlement

| Contract area | Status | Current evidence | Blocking gap / next proof |
| --- | --- | --- | --- |
| Default `澄·远`; opening `@` overrides only initial Facilitator | `partial` · P0 | Default metadata and frontend ordering exist in `rag_ime/agent_roles.py` and `control-center-web/src/features/rooms/index.tsx`. | `rag_ime/agent_room_application.py` currently overwrites opening requested participants with the default, and a test locks that opposite behavior. Preserve and validate the one explicit opening mention when Root ownership is created. |
| Complete request starts without clarification or confirmation | `partial` · P0 | The alignment prompt asks the model to inspect ambiguity and may call `room_define` directly. | Every ordinary opening still creates an align Dispatch and there is no authoritative branch receipt proving `clarification_not_required`. Add a persistent intake phase decision without adding a universal UI gate. |
| Clarification is one chronological question at a time | `partial` · P0 | Bounded questions, options, recommended choice, answer revisions, and resume logic exist; question posts are real Room events. | The frontend filters the real user answer from the execution lane and mutates the old question card visually. No persisted `awaiting_start` phase prevents an arbitrary later message from resuming execution. |
| Clarification ends with explicit chronological `开始行动` | `missing` · P0 | The UI shows alignment status text only. | There is no typed start command, button callback, authoritative receipt, or backend transition. Add it only for Roots that actually clarified; fully specified Roots bypass it. |
| `room_define` fences align and creates exactly one fresh Facilitator ExecuteDispatch | `missing` · P0 | `room_define` validates RequirementCatalog/WorkItem and records a definition receipt. | It neither settles/fences alignment nor enqueues execution. The align manifest cannot collaborate and align commit cannot hand off, which is the observed native dead end. Implement an idempotent Kernel transaction with a new Dispatch identity, capability epoch, and implementation-stage binding. |
| Facilitator decomposes genuine parallel peer WorkItems | `partial` · P1 | Kernel collaboration can enqueue multiple child Tasks/Dispatches while the parent remains active. | Fresh defined Roots cannot reach it. The definition has no durable lane plan/required peer evidence, and current completion gates can allow zero Worker deliveries. Prove two distinct peers running independent work in one installed Root. |
| Nested subagents remain bounded under each peer | `partial` · P1 | Delegation storage carries Room/root/task/dispatch lineage and quiescence fences. | Real Room delegation drops non-zero `generation`, and `roomBound` does not fail closed on incomplete lineage. No two-peer nested-child end-to-end proof exists. |
| Worker delivery cannot satisfy Root before Facilitator integration | `implemented` · source only | Worker deliver publishes a work result; pending isolated integration blocks Root completion; only the Root Facilitator may integrate. | Must still pass the new crash-safe workspace lifecycle and installed task proof below. |
| Review is risk/policy driven and independent | `partial` · P1 | Review begins after integration; reviewer/author separation and freshness/findings gates exist. | Merely having an active Reviewer currently forces review. Persist an explicit risk/policy decision and receipt. The required production canary must still use independent review. |
| Exactly one read-only final ReportDispatch | `missing` · P0 | Reporter identity is selected and non-reporter root delivery is rejected. | No ReportDispatch producer or report intent exists. The execution Dispatch may publish the final itself. Create one idempotent report lease only after work, integration, and required review are quiescent. |
| Stage-resident Skills fail closed | `partial` · P0 | Stage-to-Skill mapping, name/hash/catalog/epoch validation, stage switching, and load receipts exist. | A missing `roomSkillLoad` is accepted when the policy requires it, and active Tool/settle paths do not always require a matching current receipt. Execute/report stages are absent. |
| Terminal and unintegrated-result hard gates | `implemented` · source only | Kernel recomputes pending integration in the final transaction and rejects premature terminal settlement. | Add ReportDispatch, workspace receipts, reconnect, and installed negative-path evidence before production acceptance. |

Backend audit verification: nine focused Room/Kernel/delegation/Skill Python selections passed; one initially misnamed unittest selection loaded no test and was corrected before counting. These are source-level receipts only.

Matt skill source status: personal Codex copies of upstream `diagnosing-bugs` and
`improve-codebase-architecture` were installed from pinned upstream commit
`2ab958093e83e0ec752e6c1c5932da465bf23e0c`. The product already contains an
adapted `systematic-debugging` method and an unregistered
`improve-codebase-architecture` bundle, so Room integration is still `partial`:
the exact debugging route, Room policy entries, stage binding, provenance, and
managed-Pi build/tests must be made coherent before installed acceptance.

### Workspace and worktree lifecycle

| Contract area | Status | Current evidence | Blocking gap / next proof |
| --- | --- | --- | --- |
| One writable WorkItem owns one isolated binding | `partial` · P0 | Physical worktree allocation keys by Root/Task/base path and follows Task ownership transfer rather than persona. Read-only snapshot fencing also exists. | There is no independent durable `workspaceBindingId` entity or permanent ledger. Materialization happens before the Kernel Task/receipt, so a crash can create an undiscoverable orphan. |
| All concurrent writers share one Root baseline; one integration writer | `missing` · P0 | Only the Facilitator may call the current integration operation. | Each prepare reads whatever `HEAD` exists at that moment; Root does not pin repository identity/base commit, and there is no integration-workspace lease/single-writer state. |
| Delivery is hash-bound and integration-pending | `partial` · P0 | An isolated child must deliver rather than hand off, and pending integration blocks Root. | Delivery omits workspace head/snapshot and artifact revision, and has no dedicated hash-bound delivery receipt. |
| Integration receipt precedes exact child cleanup | `missing` · P0 | Patch application and basic conflict retention exist. | Current code applies, removes the worktree, then records integration. Its reference is not bound to patch/base/integrated revision and removal failures are ignored. Reverse the state machine: record applied revision/hash, clean exact receipted path, then record cleanup result. |
| Failed/blocked/cancelled/conflicting/orphaned worktrees remain red | `missing` · P0 | A patch-check conflict happens to leave the directory present. | There are no lifecycle states, orphan discovery, retry/rebind command, snapshot/hash-bound abandon command, or danger projection. Cancellation can leave Root permanently ambiguous. |
| Workspace lifecycle reaches both UI densities | `missing` · P0 | Generic Task state and a pending-integration summary exist. | `materialized` through `cleaned` events are not projected; integration detail fields are currently dropped/mismatched. Conversation needs full events and Tasks needs latest summary plus disclosure from the same events. |
| Skill WorkDocument is a mirror, Kernel receipts are authority | `partial` · P1 | Skill prose already says runtime authority wins. | `WorkDocumentService` still reads legacy Room work-item tables rather than a Kernel workspace ledger. A document can only mirror after that authoritative ledger exists. |

The existing six workspace tests do not cover same-Root baseline, materialize crash, conflict/orphan discovery, abandon, receipt-before-cleanup, cleanup failure, permanent ledger, or UI projection.

### Conversation and Tasks UI

| Contract area | Status | Current evidence | Blocking gap / next proof |
| --- | --- | --- | --- |
| Conversation is the default Room surface | `implemented` · source tested | Room selection defaults and resets to the conversation/posts view. | Reconfirm in installed native UI. |
| Questions and answers append chronologically | `partial` · P0 | Questions/options are real events and option/free-form input exists. | Selected answer is hidden from the execution lane and rendered back into the prior question card. Preserve the locked card and append a separate user turn. |
| Explicit `开始行动` after real clarification | `missing` · P0 | None beyond alignment status copy. | Render the typed backend transition as a one-shot inline control and append the resulting user message. Never show it on the no-clarification path. |
| Conversation peer card is a complete live activity surface | `partial` · P1 | Avatar/state/current work/activity/summary/Tool disclosure/output/failure are present. | Activity rows lack event time; card duration is Root-wide; wait/resume often degrades to generic copy; nested subagents are absent. |
| Activity feels temporal because real facts arrive | `partial` · P1 | Room snapshot/SSE and sequence-gap handling are real; bottom-aware follow logic exists. | Infinite scan/edge animation depends only on `running`, not freshness. Add last-update time, event-time rows, one-shot arrival feedback, `回到最新`, stale/wait semantics, and motion stop on expired evidence. |
| Conversation and Tasks are same source, different density | `partial` · P1 | Room SSE, Kernel SSE, and delegation data already converge in one client store and disclosures exist. | They are still separate read models merged client-side. Tasks is high density and does not expand the exact same activity stream. |
| Tasks shows peer WorkItems and nested subagents under the owner | `partial` · P1 | Task nodes show objective/owner/state/action/wait/verification and dependencies; nested runs show public budget/state/time/result. | Nested runs live inside graph nodes rather than the owning peer/WorkItem card. |
| Tasks reuses each companion Session's authoritative Todo | `missing` · P1 | The ordinary Agent runtime already owns structured Session Todo and nested runs already carry Todo lineage. | Room snapshot/SSE and WorkItem cards do not project the owning participant Session's Todo. Add a bounded owner/WorkItem join; do not add a Room checklist store or local React Todo state. |
| Each companion shows receipted artifacts and per-file diff stats | `partial` · P1 | Workspace delivery records an exact binding/snapshot and `changedFiles`; WorkItem submissions can carry artifact/evidence refs. | Delivery does not persist per-file additions/deletions and the UI has no companion result/diff section. Compute bounded stats against the binding's pinned baseline, persist them with the delivery revision, and render only that WorkItem's attributed result. |
| Graph is overview only | `missing` · P1 | A real dependency graph exists. | Nodes currently contain action, waiting, verification, result, and subagent detail and grow with children. Reduce graph to short title, owner, state, and dependencies. |
| Human semantics first; protocol lives in audit disclosure | `partial` · P1 | Graph avoids Agent/Dispatch/Receipt nodes and failure/retry/stop are visible. | Primary UI still leads with `Room 目标`, `Facilitator`, `执行前门禁`, Dispatch tooltips, and always-visible receipts. Structured resume conditions are absent. |

Frontend audit verification: five focused test files passed `141/141`; app and node TypeScript checks passed with `--noEmit --incremental false`. No browser, native build, or installed interaction was counted.

### Installed production status

| Evidence | Status | Meaning |
| --- | --- | --- |
| Installed app `/Users/undo/Applications/RagImeControl.app` reports `1.1.0` build `2`; executable hash was `eb2a3c…180d`; strict code-sign verification passed with ad-hoc identity. | `installed-unverified` | Identity/provenance only; not a Room behavior receipt. |
| Installed sidecar/workspace Python and managed-Pi Skill hashes matched the audited dirty source generation. | `installed-unverified` | Copied files and accepted generation do not prove the running processes exercised them. |
| Installed frontend `index.html` differed from the worktree `dist/index.html`. | `native-failed` | There is no coherent same-snapshot App/Web/Python/Pi acceptance bundle. |
| Production DB contained no Tasks using `workspacePolicy`, no isolated/read-only workspace Tasks, and no `room_integrate` receipts. | `native-failed` | The latest workspace flow has never been proven in production data. |
| Most recent native Room stopped after alignment/definition and never entered Worker implementation, integration, or independent review. | `native-failed` · P0 | Reproduce only after source fixes; current production acceptance remains open. |

### Ordered implementation gate

1. Fix the authoritative intake/define/execute/report state machine and fail-closed stage Skill receipts.
2. Add a crash-safe permanent workspace ledger and lifecycle before allowing a new writable production canary.
3. Project the same authoritative activity/workspace/subagent events into the chronological conversation and lower-density Tasks view.
4. Run focused positive/negative/reconnect tests, then independent review against this exact contract and fixed integration revision.
5. Build and install one coherent App/Web/Python/Runtime/managed-Pi snapshot and record provenance.
6. Complete the installed foreground GUI procedure below. Only that evidence can change production status to accepted.

## Acceptance criteria

1. A fully specified installed Room request reaches action without clarification or an extra confirmation gate.
2. An underspecified installed request follows the canonical chronological flow: inline question, separate user answer, locked answered card, next question, aligned summary, `开始行动`, separate user start message, then execution.
3. The opening `@` selects the initial Facilitator; the default without `@` is `澄·远`. Later mentions do not mutate authoritative ownership.
4. `room_define` produces a fresh execute-capable Facilitator Dispatch exactly once; the intake/alignment Dispatch cannot execute or resume late.
5. The align Dispatch's managed Pi Session proves a pinned `alignment-and-decision` load; the execute Dispatch proves a distinct pinned `implementation-execution` load; stage changes, stale hashes/epochs, and compaction restore pass positive and negative receipt tests.
6. A fresh three-companion `写 TUI` canary visibly creates at least two genuinely independent WorkItems, runs them in parallel when appropriate, shows distinct companion updates, performs real handoffs and Facilitator integration, then uses an independent Reviewer under Root policy.
7. The Tasks page shows goal, progress totals, peer division of work, task content, dependencies, owner, state/action/blocker/evidence, integration/review/result, and any real nested subagent runs grouped beneath the correct parent task.
8. Source and native evidence prove that nested subagents are bounded private children, not Room partners, while their safe task/status/result projection remains visible.
9. Review Findings are revision-bound and Kernel-derived Verdict/repair/re-review/loop-limit behavior passes positive and negative tests.
10. Settlement follows `workQuiescent -> ready_to_report -> ReportDispatch -> one Facilitator final -> reporter receipt -> runtimeQuiescent -> completed`; failed, blocked, cancelled, and timed-out paths remain coherent and visible.
11. Safe live progress, role-specific public language, chronological history, collapse/expand/pagination, reconnect, bounded memory, and response-level Provider/model/token/cache provenance survive reload without duplicate/flicker/stale activity.
12. Every active role card shows current action, last real update, timestamp, full bounded event flow, stable expandable Tool rows, and truthful wait/resume information. Transport heartbeats and client timers never masquerade as work, and expired activity stops running motion and becomes waiting/stalled/blocked evidence.
13. Conversation and Tasks prove `双面同源、不同密度`: the conversation card exposes the complete public event stream; each WorkItem defaults to the latest summary/completion/update time and expands the same events; the graph remains overview only.
14. Concurrent writable WorkItems receive distinct receipted workspaces from one baseline, Worker delivery remains integration-pending, and only the Facilitator integrates. Successful hash-bound integration automatically cleans the exact physical child worktree while retaining the ledger; failed/blocked/cancelled/conflicting/orphaned worktrees remain present and red until a receipted Facilitator retry or snapshot/hash-bound abandonment.
15. Final acceptance operates the installed `/Users/undo/Applications/RagImeControl.app` in the foreground. An operator uses ordinary user language to submit one concrete task (for example, `我要完成 TUI`), answers any real clarification in the GUI, starts action when asked, and observes the product actually create, implement, test, integrate, review when required, and deliver that concrete task. A scripted transcript whose underlying task is not completed fails.
16. Hidden Chromium, direct API calls, preview fixtures, screenshots, unit tests, health 200, model self-report, and Kernel terminal state are diagnostics only and cannot independently close acceptance.
17. Acceptance records installed app/version/build/commit/hash/signature, Runtime Host and managed-Pi provenance, database, Provider/model, Root/participant IDs, requirement/artifact/ReviewTarget revisions, Findings/Verdict, nested-run lineage, Skill load receipts, workspace/integration/cleanup receipts, and final report ID.
18. Each Room companion's task section shows the existing authoritative Todo owned by her Session and bound to her WorkItem, including stable item order/state/current blocker and reconnect behavior. No second Room Todo implementation or frontend-only completion state exists.
19. Each Room companion's result section shows only her receipted contribution: artifact/file list, per-file added/deleted line counts when meaningful, focused verification, result, integration disposition, and residual risk. The exact delivery baseline/snapshot proves attribution; repository-wide dirt, binary/private content, and another companion's work are never mislabelled.
20. Versioned Room contracts remain only when they are the current wire format or have a proven route/runtime/projection/migration/replay consumer. Dead declarations and generated mirrors are removed; persisted historical versions remain until a tested read upcaster makes their removal safe.

### Installed native GUI acceptance procedure

The final production gate is one evidence bundle from the same fresh Root and installed build:

1. Open the installed `RagImeControl.app` foreground UI; record installed identity before submitting work.
2. Enter a natural, non-protocol request for a real bounded repository task. The acceptance prompt must not contain hidden Dispatch instructions, canned answers, or implementation literals.
3. If the request is materially underspecified, answer the companion's chronological inline questions and use `开始行动` only after the aligned summary. If a separate fully specified canary is run, it must begin without clarification or confirmation.
4. Observe distinct Facilitator and peer Worker ownership, at least two genuinely independent parallel WorkItems when the chosen task supports them, each owner's real Todo and attributed file/diff/result summary, real Tool/work events, one nested subagent under its parent WorkItem, delivery, integration, required-canary independent review, and one Facilitator final.
5. Verify the requested artifact and focused tests in the governed workspace, not just the conversation text. Confirm every child workspace and unintegrated result follows the retention/cleanup contract.
6. Reload/reconnect the same Room and verify chronological answers, activity, task/subagent hierarchy, workspaces, Findings/Verdict, telemetry, and exactly one final remain coherent.
7. Correlate GUI observations with database/Kernel/managed-Pi/Tool/Skill/workspace receipts and installed provenance. Any mismatch, fake activity, skipped implementation, missing integration/review, or incomplete artifact keeps acceptance open.

## Explicit non-goals

- Do not make requirement alignment or start confirmation mandatory for every request.
- Do not use the Tasks page as a user-editable graph, execution gate, or frontend orchestrator.
- Do not flatten Room companions and nested subagents into one master/slave tree.
- Do not use free-text mentions, round-robin selection, or companion display names as assignment/review policy.
- Do not introduce a permanent global commander Agent or make the Kernel a semantic planner.
- Do not require independent review for every ordinary task; apply the Root's review policy and general Facilitator risk decision.
- Do not create a second Ask Tool, Room state store, event bus, task-cost schema, or prompt-specific `写 TUI` path.
- Do not load alignment and implementation Skill bodies together merely to simulate a permanent workflow prompt; bind the exact required Skill to the authoritative stage.
- Do not prove production completion through model self-report, chat text, screenshots, mocks, preview fixtures, backend JSON, health 200, or source tests alone.
