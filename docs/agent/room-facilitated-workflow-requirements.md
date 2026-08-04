# Room Facilitated Workflow Requirements

- Document class: sole tracked authority for current Room product behavior and acceptance status
- Approved vision window: user decisions made on or after 2026-08-02
- Contract revision: 2026-08-04
- Acceptance state: source remediation passed current full regression and independent Sol max review with no remaining P0/P1/P2; coherent install plus native foreground acceptance remain open
- Status rule: source, test, installed, and foreground evidence are reported separately

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

### Conditional clarification

The receiving companion first inspects facts already available from the
repository and runtime, then chooses one of two branches.

1. If no material user-owned choice is missing, the opening request authorizes
   action. Do not ask for confirmation and do not show `开始行动`.
2. If a material choice is missing, ask one question at a time in the normal
   message stream.
3. Each question presents 2–5 honest single-select options, with at most one
   recommendation. Every option has a short name and a natural paragraph that
   explains the resulting scope, effort, or tradeoff instead of repeating the
   name. Free text remains hidden until the user chooses `其他`.
4. Clicking an option only selects it. The user must then click `确认并发送`;
   selection alone never advances the Room. `其他` reveals the text field and
   is the only free-text branch for an active alignment question. Active
   alignment never emits an optionless question.
5. Option and custom answers carry an explicit answer kind. Custom text is never
   relabelled merely because it equals an option's internal value.
6. The answer appears as a separate chronological user message. The prior
   question remains in place, becomes read-only, and is never the sole record of
   the answer.
7. Only after that answer appears may the Facilitator ask the next dependent
   question.
8. Before defining work, the companion must be able to name the concrete entry
   or surface, what the user will do and see, the real deliverables, and an
   observable completion check. `端到端可用`, `完整`, and `可运行闭环` describe
   scope but do not replace those specifics; `当前项目`, `规定入口`, `核心操作`,
   and `真实结果` are placeholders and must not release execution.
9. After the last necessary answer, the Facilitator summarizes what she now
   understands and asks `现在开始行动吗？`. The one-shot `开始行动` control exists only on
   this clarification branch.
10. Clicking it appends an ordinary user message such as `开始行动`. That message
   is durably ordered before the fresh execute Dispatch is released; a crash or
   retry cannot begin a Worker or Reviewer without the visible authorization.

Canonical ordering:

```text
用户：@澄·今 我准备写 TUI
澄·今：我来接手，还有一个会影响实现方式的问题
        [选项]
用户：终端原生 TUI
澄·今：首版最重要的交付边界是什么？
        [选项]
用户：先完成可运行闭环
澄·今：我明白了……现在开始行动吗？
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

- Owns requirements, decomposition, WorkItem assignment, dependencies,
  integration, review policy, and the only final report.
- May implement and integrate, but cannot independently review its own work.
- Parallelizes only independent, non-overlapping slices when that materially
  reduces waiting.

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

- Reviews the integrated target against the latest requirements and evidence.
- Is independent from authors and Integrator, normally using fresh read-only
  context.
- Submits structured Findings. Runtime policy derives the verdict; the Reviewer
  cannot fix a finding and approve the same fix.

### Runtime authority

Backend state owns work identity, capability leases, requirements, waits,
receipts, review, cancellation, and terminal state. Mentions, filesystem paths,
assistant prose, screenshots, and frontend state cannot create ownership or
prove completion.

## Stage-resident Skills

One exact governed Skill is bound to the current managed-Pi work stage. This is
not a permanent prompt containing every workflow.

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

## Authoritative lifecycle

1. Capture the opening request and initial Facilitator.
2. Choose the direct or clarification branch.
3. Append every accepted answer as a new requirement revision and durable
   answer identity, publish its chronological user post, and only then
   CAS-release the one resume Dispatch. A crash in any window remains
   non-executable or exactly replayable, and a specific question revision
   resumes at most once.
4. If clarification occurred, wait for the typed start action, durably prepare
   its one-shot identity, publish the user message, and only then CAS-release
   execution. Any partial transaction remains non-executable and retryable.
5. Define the accepted work atomically and fence the intake Dispatch.
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
- Activity is one vertical stream, not a stack of nested cards and columns.
  Tool activity, public-safe work summaries, results, waits, handoffs, and
  workspace transitions share the same time order.
- The default density follows the Codex activity-flow pattern: compact rows
  expose useful facts such as action, file name, command status, and attributed
  `+N/-N`; repeated plumbing, long arguments, and raw output stay collapsed.
  Each row may expand in place to bounded input, output, diff, or safe failure
  details without opening another column or nested card stack.
- Repository work uses first-class semantic rows for search, read, edit/create,
  command, test, and diff instead of the generic label `工具操作`. A compact
  sequence may read `已搜索 …`, `已读取 RoomTurn.tsx`, and
  `已编辑 RoomTurn.tsx +46 -1`; expanding it reveals matched locations, the
  bounded command/output, or the attributed patch. File manipulation must be
  strong enough to support repeated edits and verification during a day-scale
  run, not only report that an opaque Tool returned.
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
- A freshness timeout changes motion to truthful waiting/stalled state. Network
  heartbeat and elapsed-time repaint never masquerade as work.
- Terminal and final events still auto-follow and announce once when the user is
  already at the bottom. Disconnect and reduced-motion stop decorative motion.
- Pending clarification owns the interaction point. The ordinary composer is
  hidden only while the current question is answerable; stale or terminal
  questions cannot trap input.
- Internal protocol words and identifiers stay in optional audit detail. Remove
  the old execution-gate panel and lead with ordinary conversation.

## Tasks surface: same source, lower density

- Conversation and Tasks project the same authoritative event and workspace
  records. They do not maintain separate completion truth.
- A WorkItem card defaults to owner, objective, semantic state, latest summary,
  completion, last update, dependency/blocker, and verification.
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
- Primary Tasks statistics exclude internal final-report bookkeeping; Report
  work remains visible only where its audit role matters.
- Provider calls, artifacts, diffs, Todo, and workspace state stay bound to the
  response, Session, participant, WorkItem, baseline, and revision that produced
  them.

## Implementation and acceptance ledger

| Area | Source/test state | Installed foreground state |
| --- | --- | --- |
| opening Facilitator, conditional clarification, crash-safe chronological answers and typed start | implemented; current Web 950/950, Room Kernel 98/98, and Runtime/public projection 104/104 passed; prior command receipt and injected-crash gates also passed | open |
| fresh execute Dispatch, peer work, nested delegation, integration, review, one report | implemented; current Room Kernel 98/98 and prior focused settlement gates passed | open |
| stage Skills and capability receipts | implemented; Skill 25/25 and Pi runtime 70/70 passed | open |
| permanent workspace ledger, same-baseline isolation, integration-before-cleanup, red retention | implemented; settlement and canary 18/18 passed | open |
| continuous conversation activity and lower-density Tasks projection | implemented; current Web 950/950 passed | open |
| Session Todo, per-owner result/diff, subagent grouping | implemented; source projections and Web regression passed | open |
| day-scale full-auto recovery, durable checkpoints, automatic repair/retry/reassignment/model fallback | partially implemented; durable Dispatch attempts, Todo, workspace ledger, reconnect state, direct failed-Tool retry lineage, and Provider retry projection exist and passed source regression; restart-resume plus injected native recovery acceptance remain open | open |
| historical continuation recovery and Report-stat filtering | implemented; historical upcast 7/7 and settlement regression passed | open |
| tracked authority portability | implemented by `docs/agent/room-facilitated-workflow-requirements.md` | not applicable |
| coherent App/Web/Python/managed-Pi provenance | production Web build passed; coherent install pending | open |
| real installed Room completing a concrete TUI task | not a source claim | open |

No row may be promoted to native accepted by unit tests, mock transport, hidden
browser, direct API, screenshot, health response, copied hash, assistant prose,
or terminal state alone.

## Required native foreground acceptance

Use one coherent installed build and one fresh Room in the foreground
`RagImeControl.app`:

1. Record installed app version/build/commit/hash/signature and matching
   App/Web/Python/runtime/managed-Pi provenance.
2. Submit a natural bounded request such as `我要完成 TUI`; do not include
   protocol instructions or canned answers.
3. If real ambiguity exists, answer the inline option-first questions and click
   `开始行动` only after the natural understanding summary. Also preserve the direct path for a
   fully specified request.
4. Observe distinct Facilitator and peer ownership, at least two real parallel
   WorkItems when appropriate, each owner's Todo and attributed result/diff,
   real Tool/activity updates, one bounded nested subagent, delivery,
   Facilitator integration, required-canary independent review, and one final.
5. Verify the requested artifact and focused checks in the governed workspace.
   Confirm successful child cleanup and retained danger workspaces match the
   permanent ledger.
6. Reload the same Room and confirm chronology, tasks, activity, provenance,
   review, workspace state, and one final remain coherent.
7. Correlate the visible flow with durable receipts and installed provenance.
   Any fake activity, skipped implementation, missing integration/review,
   incomplete artifact, duplicate final, or mismatch keeps acceptance open.
8. In full-auto mode, inject at least one recoverable command or Tool-argument
   failure and one transient Provider failure. Confirm the owning companion
   repairs or retries it, the Facilitator continues the plan, the user is not
   asked to handle the intermediate error, the expanded Tool row preserves the
   attempt details, and the Room still reaches verified delivery. Restart once
   after a durable checkpoint and confirm work resumes without duplicating
   completed Todo, workspaces, messages, or the final report.

## Explicit non-goals

- mandatory alignment or confirmation for every request
- a user-editable task graph or frontend orchestrator
- a permanent global commander or master/slave companion tree
- ownership inferred from display names or later mentions
- a second Ask Tool, Room state store, event bus, Todo implementation, or cost
  schema
- prompt-specific `写 TUI` behavior
- loading all stage Skills into every prompt
- exposing hidden reasoning or private subagent transcript
- claiming production completion from source-only or diagnostic evidence
