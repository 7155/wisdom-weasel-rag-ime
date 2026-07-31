---
name: memory-curation
description: Review evidence and prepare governed changes to durable personal memory when the user explicitly asks, a verified task yields reusable knowledge, or the idle curator runs.
when:
  - 用户明确要求整理、纠正、遗忘、应用或回滚记忆
  - 任务验收后整理少量可复用事实草案
  - 低频维护审阅候选记忆
does: 区分证据、记忆、主题与时间线，生成带来源的待审草案。
input: 用户意图、已授权 Evidence、当前记忆状态、冲突、作用域和治理回执。
output: 待审记忆变更、证据引用、冲突说明、审批状态和可用回滚点。
notFor:
  - 普通聊天、临时进度、失败回执、一次性命令或 Room 私有过程
  - 直写数据库、自动批准或永久保存整段原始对话
---

# Memory Curation

This Skill organizes durable memory. The always-on System policy decides when
to submit a small `memory_capture` candidate; this Skill is not required for
that capture and must not run on every turn.

## Capture Versus Curation

- `memory_capture` records a small candidate when the user states a durable
  preference, fact, decision, correction, constraint, continuing plan, or
  verified reusable lesson.
- This Skill reviews candidates and current memory, resolves conflict and
  scope, and proposes governed durable changes.
- A candidate is evidence awaiting organization. It is neither an applied Atom
  nor permission to preserve the whole conversation.

## Memory Model

```text
authorized Evidence -> one Current Atom -> optional Topic Book
                    \-> Task Timeline for continuity only

Agent identity and behavior -> Role Book, governed separately
```

- Evidence preserves where a claim came from. It is not automatically a fact.
- A Current Atom is one current, independently retrievable claim with lineage.
- A Topic Book organizes supported Atoms; it is not a transcript summary.
- A Timeline preserves task chronology and source provenance. It may explain
  continuity but cannot prove a durable fact by itself.
- Role Book describes an Agent, never the user, and cannot expand authority.

## Workflow

1. Confirm a legitimate trigger: explicit user request, verified task
   completion with reusable information, or a bounded idle maintenance run.
2. Apply the durable-information gate. Keep stable preference, fact, decision,
   correction, long-lived constraint, continuing plan, or verified reusable
   lesson. Exclude questions without assertions, duplicates, temporary
   progress, one-turn commands, failed or unapplied receipts, workflow status,
   guesses, secrets, and private process.
3. Resolve current memory before proposing a change. Distinguish new claim,
   correction, duplicate, conflict, forget request, and organizational update.
4. Preserve the narrowest valid user or project scope and human-readable
   provenance. Synthesize one normalized claim; do not paste a long source.
5. Call `memory` with the exact operation family disclosed by the Tool:
   user changes use `remember_preview|remember_apply`,
   `correct_preview|correct_apply`, or `forget_preview|forget_apply`;
   maintenance uses `maintenance_preview|maintenance_review`,
   `maintenance_apply`, or `maintenance_rollback`. `list`, `search`, `get`,
   `review`, and explanation operations never mutate memory.
6. Stop for the native review boundary whenever the Tool says approval is
   required. A chat message saying "approved" is not an approval receipt.
7. Report what was proposed or applied, its evidence, conflicts, current state,
   and rollback availability. Never claim a Book, Timeline, Role Book, or Atom
   revision became active without its authoritative Tool receipt.

## Candidate Decision Table

| Observation | Action |
|---|---|
| stable new user preference | propose one scoped Current Atom |
| explicit correction | supersede the old Atom and keep lineage |
| duplicate wording | link evidence; do not create another current claim |
| conflicting unverified claims | preserve conflict for review |
| task chronology only | Timeline, not a durable fact |
| several supported Atoms on one topic | optionally update a Topic Book |
| forget request | use governed forget/tombstone path and preserve receipt |

## Quality Rules

- One Atom holds one current claim and keeps correction/supersession lineage.
- A Book references current supported Atoms and drops retracted claims.
- A Timeline conserves source events and App provenance exactly once.
- Tags and groups improve retrieval; they are not the source of truth.
- Hidden, expired, forgotten, sensitive, or tombstoned sources fail closed.
- Background curation remains bounded and draft-first; it does not interrupt an
  active conversation or replace manual review.

## Output Contract

Return one operation result with the normalized claim or organization change,
human-readable evidence source, conflict/duplicate decision, approval state,
affected scope, authoritative receipt when present, and rollback status. A
preview, review, rejection, or apply receipt is terminal for this Skill turn;
never continue into another mutation without the Tool's required authority.

## Self-Check

- Is the proposed claim stable enough to help a future task?
- Is it one claim with the narrowest correct scope and readable provenance?
- Did I distinguish Evidence, Atom, Book, Timeline, and Role Book?
- Is this a draft, an approved change, or an applied revision?
- Can the user review, correct, forget, or roll it back?

## Boundaries

Do not read or write SQLite directly, turn a Timeline into fact evidence,
copy Agent identity into user memory, reopen forgotten raw text, auto-apply a
manual draft, suppress the existing background auto-apply lane, or treat
memory capture and memory curation as two competing write paths.
