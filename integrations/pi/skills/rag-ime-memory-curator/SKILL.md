---
name: rag-ime-memory-curator
description: Governed workflow for reviewing evidence and proposing RAG-IME memory changes through ime_memory and agent_role_book. Use for remember, correct, forget, rollback, Timeline review, Topic Book curation, or Role Book proposals; every durable activation remains bound to native approval.
when:
  - 用户要求审阅、整理、应用或回滚智鼬记忆草案
  - 用户询问 ime_memory 草案审批流程
  - 项目、功能、修复或迁移已完成，需要判断是否形成可复用记忆或角色能力记录
does: 先过持久信息门，再用 ime_memory 或 agent_role_book 生成受控草案。
input: 用户持久化意图、经授权 Evidence 或草案、当前 Session 固定角色版本。
output: 待审记忆或角色书草案、证据引用和审批或回滚状态。
notFor:
  - 普通聊天、进度播报、失败回执或未完成工作
  - 直接读写 SQLite
  - 绕过逐项审批
---

# RAG-IME Memory Curator

The structured `ime_memory` and `agent_role_book` Tools own the actual
contracts. This Skill describes the Agent workflow around them. It never grants
permission, never replaces native approval, and never makes direct database
writes.

## Memory Model

Use this hierarchy and keep its boundaries explicit:

```text
Evidence -> Current Atom -> Topic Book
        \-> cross-App Task Timeline (continuity only)

Agent identity and behavior -> Role Book (separate governance domain)
```

- **Evidence** is immutable provenance such as a finalized user message or a
  quality-gated input event. Evidence can support a claim; it is not itself a
  durable fact.
- A **Current Atom** is one independently retrievable, evidence-backed claim.
  Only a successfully approved `remember_apply` or `correct_apply` can create a
  current claim.
- A **Topic Book** organizes supported Current Atoms into a durable topic view.
  It must reference its Atoms and evidence; it is not a transcript dump.
- A **Task Timeline** is a date-oriented continuity view. One semantic task may
  cross Apps, while every event keeps its original App provenance. A Timeline
  may support intent or chronology, never establish a long-term fact, and an
  Agent must never approve it automatically.
- A **Role Book** describes the Agent, not the user. Never copy Role Book
  content into user Atoms or Topic Books.

## Hard Boundaries

- Use only records returned by `ime_memory`; never read or write the SQLite database directly.
- Treat only finalized, quality-gated, currently visible input as evidence.
  Never promote isolated words, Rime commit fragments, transport tags, runtime
  probes, deleted text, or a Timeline summary by itself.
- Preserve every event's App as provenance. Events from different Apps may be
  grouped only when the backend identifies one continuous semantic task; never
  invent, merge, or rewrite their App provenance.
- The lightning Active-RAG buffer is live, editable context owned by Squirrel. It is not long-term memory and this skill must not persist it.
- Treat `sensitive`, `not_for_memory`, `expired`, explicitly forgotten, and
  actively tombstoned sources as unavailable. A raw input hidden after a
  reviewed Atom was derived is not the same as an explicit forget: the Agent
  may use the already-approved Atom, but must not reopen or quote the hidden
  raw input. A missing source fails closed.
- A chat message saying "approved" never substitutes for the native checklist,
  hash-bound preview, approval dialog, receipt, or rollback guard.
- Durable memory is a semantic synthesis, not a transcript archive. Keep raw
  messages, tool output, and rejected drafts only in Evidence/audit storage;
  never copy them verbatim into an Atom, Topic Book, Phrase, or Timeline.

## Durable-Information Gate

Classify every source before proposing any semantic artifact:

| Source content | Disposition | Durable output |
| --- | --- | --- |
| Evidence-backed fact, stable preference, decision, long-lived constraint, or continuing plan | `remember` | One normalized Current Atom; optionally update a Book |
| Question with no asserted durable information | `not_for_memory` | None |
| Failed, rejected, timed-out, or unapplied Tool receipt | `not_for_memory` | None; retain audit receipt only |
| Curation protocol/status such as `curation_prepare`, `runId`, "draft ready", or "wait for review" | `not_for_memory` | None |
| Repeated question or duplicate message | `not_for_memory` for duplicates | At most one synthesized fact, only when one actually exists |
| One-turn command such as continue, retry, refresh, click, merge, submit, build, or install | `not_for_memory` | None unless it explicitly states a durable policy |
| Ambiguous or conflicting evidence | `needs_review` | None until resolved |

- A question may contain a durable assertion, for example "以后每次都不要截图，可以吗？".
  Extract only "以后每次都不要截图" as a constraint; never store the question
  or invent its answer.
- A successful receipt is eligible only when the completed state will matter in
  a future session. Routine success/status receipts remain operational history.
- `instruction` may narrow the topic, but it can never override this gate,
  source governance, privacy, Atom-first lineage, or native approval.

## When To Run This Skill

Do not run memory curation merely because the Agent is chatting, a turn ended,
or the role is `companion-present-v1`. Ordinary user and assistant messages remain
Evidence/audit records and do not by themselves trigger a Tool call.

Run one compact curation check only at one of these boundaries:

- `task_completion`: a project, feature, bug fix, migration, or coherent stage
  has actually completed and its verified outcome may matter in a later
  session;
- `explicit_request`: the user explicitly asks to remember, correct, forget, or
  organize memory;
- `idle_batch`: the out-of-dialogue maintenance runner performs its low-frequency
  batch. It must be draft-only, bounded, and never compete with an active chat.

At `task_completion`, first apply the Durable-Information Gate locally. If the
completed work yields no reusable fact, decision, durable constraint, stable
preference, continuing plan, or evidence-backed lesson, do not call a memory
Tool. If something survives, call `ime_memory` once with
`op=curation_prepare`, `trigger=task_completion`, a short `instruction`, and
the conservative incremental policy. Never call it once per message, once per
tool result, or once per progress update. This completion check is the default
token-saving path.

Role Book maintenance follows the same completion boundary. Propose a Role Book
revision only when completed work produced a supported change to capabilities,
recent work, active commitments, or lessons/limits. Chat style, an assistant
promise, self-praise, failure narration, and temporary working state are not
Role Book updates.

## Governed User Memory Writes

### Remember

1. Identify the exact user claim and active Evidence IDs. Do not use Agent
   inference or Timeline text as the only evidence.
2. Call `ime_memory` with `op=remember_preview`. Keep the returned
   `proposalId`; a preview does not create a Current Atom.
3. Show the compact proposal result and stop for native review.
4. Call `op=remember_apply` only with that exact `proposalId` when the user
   chooses to proceed. The native approval gate still decides whether it is
   applied.

### Correct

1. Resolve the current target Atom and evidence for the replacement claim.
2. Call `op=correct_preview` with the target and corrected text.
3. Apply only through `op=correct_apply` with the exact returned `proposalId`
   and native approval.
4. Never overwrite the old Atom. A successful correction makes the old Atom
   superseded, creates a new Current Atom, and preserves the shared
   `lineageId`, `claimKey`, and `memory_supersessions` history. Multi-parent
   lineage stays in the supersession graph rather than being flattened.

### Forget

1. Resolve the exact current target and state the user's reason.
2. Call `op=forget_preview`; do not reveal already-forgotten source text while
   explaining the preview.
3. Apply only through `op=forget_apply` with the exact `proposalId` and native
   approval. Successful forget retracts the claim and activates its tombstone;
   retrieval and source drill-down must then fail closed.

### Roll Back

- Use `op=governance_rollback` only for the exact applied `proposalId` whose
  receipt says rollback is available. Rollback has its own state hash and
  native approval; never manufacture a proposal ID or reuse an old approval.
- The older maintenance flow remains separate: inspect
  `op=maintenance_status`, prepare at most one conservative
  `op=curation_prepare` run, apply checked diffs with the real `runId`, and use
  `op=maintenance_rollback` only for that applied run.

## Draft Quality

- Atom: one current claim, one stable claim slot, explicit Evidence references,
  and the narrowest valid project/App scope. Use a normalized assertion, not a
  question, protocol field, status line, or verbatim long source message.
- Topic Book: multiple supported Current Atoms with stable Atom references;
  never silently absorb a retracted or unsupported Atom and never create a Book
  directly from transcript text when no durable Atom survives the gate.
- Timeline: task continuity across Apps is allowed, but all source events must
  be conserved exactly once and retain App provenance. Summarize a small number
  of semantic tasks; do not use one Timeline card per input or copy input text.
- Tags and Groups are auxiliary retrieval organization, not the source of
  truth. Merge only synonyms, aliases, case variants, abbreviations, or
  explicit old/new names. Do not merge related-but-distinct concepts.

## Role Book Governance

- Use `agent_role_book` only with `op=get`, `op=history`,
  `op=propose_revision`, or `op=review`.
- A session is pinned to one Role Book revision. Read and propose against that
  pinned revision; a stale or unpinned session must fail rather than rebase
  itself silently.
- `propose_revision` may create only a draft. The Tool has no activation
  operation, so the Agent cannot activate, self-promote, or change its own
  permissions, safety policy, or tool authority.
- Review happens outside activation. Even after another trusted control path
  activates a later revision, the current session remains pinned to its
  original revision.

Read [VCP patterns](references/vcp-patterns.md) when deciding how to separate raw evidence, semantic organization, and retrieval-time injection.

## Example Instruction

```text
整理输入法相关记忆：从可见 Evidence 识别 Current Atom，把稳定 Atom 组织进 Topic Book；
跨 App 的连续工作只进入 Task Timeline，并保留每条 App 来源；不要把问题、计划或 Timeline
改写成已完成事实。无事实问题、失败回执、流程噪声、重复问句和临时指令只保留为 Evidence，
不生成任何长期记忆产物。所有 remember/correct/forget 只生成受治理预览并等待原生审批。
```
