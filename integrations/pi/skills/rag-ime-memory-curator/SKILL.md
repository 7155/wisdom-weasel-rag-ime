---
name: rag-ime-memory-curator
description: Governed workflow for reviewing evidence and proposing RAG-IME memory changes through ime_memory and agent_role_book. Use for remember, correct, forget, rollback, Timeline review, Topic Book curation, or Role Book proposals; every durable activation remains bound to native approval.
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
- Treat `sensitive`, `not_for_memory`, `expired`, deleted, and actively
  tombstoned sources as unavailable. Do not quote, open, summarize,
  reconstruct, or use them as evidence. A missing source fails closed.
- A chat message saying "approved" never substitutes for the native checklist,
  hash-bound preview, approval dialog, receipt, or rollback guard.

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
  and the narrowest valid project/App scope.
- Topic Book: multiple supported Current Atoms with stable Atom references;
  never silently absorb a retracted or unsupported Atom.
- Timeline: task continuity across Apps is allowed, but all source events must
  be conserved exactly once and retain App provenance.
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
改写成已完成事实。所有 remember/correct/forget 只生成受治理预览并等待原生审批。
```
