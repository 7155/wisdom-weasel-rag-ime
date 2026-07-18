---
name: rag-ime-memory-curator
description: Optional workflow guidance for reviewing RAG-IME Atom-first memory drafts through the structured ime_memory tool. The Tool schema owns correctness; never apply a draft without selective native approval.
when:
  - 用户要求审阅、整理、应用或回滚智鼬记忆草案
  - 用户询问 ime_memory 草案审批流程
does: 用 ime_memory 准备并受控应用记忆草案。
notFor:
  - 普通记忆查询或自动生成
  - 直接读写 SQLite
  - 绕过逐项审批
---

# RAG-IME Memory Curator

The structured `ime_memory` Tool owns the actual contract. This Skill only describes the optional human workflow around it; automatic draft generation and direct Tool calls must work when this file is never loaded.

## Hard Boundaries

- Use only records returned by `ime_memory`; never read or write the SQLite database directly.
- Treat only finalized, quality-gated input as evidence. Never promote isolated words, Rime commit fragments, transport tags, runtime probes, or deleted text.
- Preserve each record's App as provenance. Never concatenate different Apps and never turn an App name into a semantic group or tag.
- The lightning Active-RAG buffer is live, editable context owned by Squirrel. It is not long-term memory and this skill must not persist it.
- Every change is a draft. Chat approval never substitutes for the native checklist and approval dialog.

## Workflow

1. Call `ime_memory` with `op=maintenance_status`. Reuse a real unfinished `runId` when one exists; never invent one.
2. When no current draft exists, call `ime_memory` exactly once with `op=curation_prepare`, `scope=incremental`, and `policy=conservative`. Do not enumerate database operations in chat.
3. The backend freezes a snapshot, asks an internal worker only for Atom decisions, derives Book/Group/Tag/relations, computes lexicon proposals from native Rime feedback, and stores the full diff out of band.
4. Stop after receiving the compact `runId` and counts. The user reviews individual changes on the Memory page.
5. Apply only the checked diffs by using the real `runId` with `op=maintenance_apply`. Native approval remains mandatory.
6. Use `op=maintenance_rollback` only with the exact applied `runId` returned by the tool and explain what will be restored.

## Draft Quality

- Atom: one independently retrievable claim. Keep source event IDs and App provenance.
- Book: a durable topic summary assembled from multiple supported atoms, not a transcript dump.
- Group: a coarse user-facing content area such as input method, research, or job search.
- Tag: a stable concept, entity, preference, or domain term. Reject generic verbs and one-off UI states.
- Tag merge: only synonyms, aliases, case variants, abbreviations, or old/new names.
- Tag edge: use for broader, narrower, part-of, requires, enables, supports, conflicts-with, or related concepts. Do not merge related-but-distinct concepts.

Read [VCP patterns](references/vcp-patterns.md) when deciding how to separate raw evidence, semantic organization, and retrieval-time injection.

## Example Instruction

```text
整理输入法相关记忆：删除单词碎片与传输标签；合并等价原子和同义标签；保留 App 来源；
把稳定需求归入现有“输入法”组；不要把问题或计划改写成已完成事实。只生成可勾选草案。
```
