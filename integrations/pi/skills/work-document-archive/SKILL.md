---
name: work-document-archive
description: Bounded adapter for governed WorkDocument archive requests; the backend remains lifecycle owner.
when:
  - 明确请求工作文档归档、恢复或历史
input: Operation-specific query, document, authority, or transition refs.
output: Normalized packet with the untouched backend response or receipt.
does: 调用受管 WorkDocument API。
notFor:
  - 文件、索引或生命周期归属
  - 擦除或 Room 必经阶段
---

# Work Document Archive

This Skill is a progressively loaded adapter to the governed WorkDocument
contract. It never becomes another registry, queue, index, or lifecycle owner.

## Trigger

Load this Skill only when the user asks to list, search, inspect, archive,
repair, or reopen governed work documents, or explicitly asks to include
archived history. Do not load it merely because a Goal, Plan, or Room reaches a
terminal state.

## Inputs

Use only the inputs required by the selected operation:

| Operation | Required inputs |
|---|---|
| `list` | `limit` and active scope |
| `search` | `query`, `limit`, and explicit `history` scope |
| `get` | `documentRef` |
| `archive` | `documentRef`, `authorityRef`, and `terminalReceiptId` |
| `repair` | `documentRef` and `authorityRef` |
| `reopen` | `documentRef`, `authorityRef`, next `authorityRevision`, and `transitionReceiptId` |

`authorityRef` contains `authorityKind` (`session_goal`, `session_plan`, or
`room_work_item`), `authorityId`, and the current `authorityRevision`. Never
infer terminal authority from prose, filenames, timestamps, local status, or
the Skill's own output.

## Owner and Authority

The backend WorkDocument registry and outbox are the canonical owner of
identity, state, transitions, indexes, and recovery. Goal, Plan, and Room
terminal receipts authorize archive eligibility. This Skill only translates an
intent into a governed API request and reports the authoritative response.

## Workflow

1. Use `GET /api/agent/work-documents?limit=` for ordinary list and active
   discovery. It defaults to non-archived documents; active search must remain
   within those returned entries. Use
   `GET /api/agent/work-documents/history/search?query=&limit=` only after the
   caller explicitly requests archived history. Use
   `GET /api/agent/work-documents/{documentId}` for one known document.
2. Before any mutation, load the document detail and compare its authority
   kind, id, and revision with `authorityRef`. Stop on any mismatch.
3. For archive, require matching authority and document refs and call
   `POST /api/agent/work-documents/{documentId}/archive` with only
   `{terminalReceiptId}`. The backend, not this Skill, validates the terminal
   receipt and decides eligibility.
4. Submit idempotent reconciliation through
   `POST /api/agent/work-documents/{documentId}/repair` with `{}`. Submit reopen
   through `POST /api/agent/work-documents/{documentId}/reopen` with
   `{authorityRevision, transitionReceiptId}`; the backend decides whether that
   is the canonical nonterminal next authority revision.
5. Keep active wire schema names `work-document-list.v1`,
   `work-document-detail.v1`, and `work-document-command.v1` unchanged. Put the
   untouched backend response or receipt inside one normalized Skill packet;
   do not rename, synthesize, or discard backend fields. Treat
   `archive_pending`, `reopen_pending`, and `error` as authoritative
   non-terminal outcomes, not permission to change a file or bypass governance.

## Archive Is Not Erase

Archive preserves a governed document and its history. Erase is a separate,
destructive, approval-bound workflow: `erase-preview` produces a hash-bound R3
approval and `erase` may execute only that approved payload. This Skill does
not expose either erase operation. Archive has no automatic expiry or deletion
timer. Reject `delete` as an alias and ask the caller to choose archive or the
separate governed erase workflow explicitly.

## Stop Conditions

Stop without issuing a mutation when refs are missing or disagree, archive has
no authoritative `terminalReceiptId`, history was not explicitly requested,
reopen lacks its two required refs, or the request conflates archive with
delete or erase. After any backend rejection or request receipt, stop and
report it; do not manufacture evidence, force a transition, or retry through
another path.

## Output Contract

Return one normalized Skill packet with the requested operation, supplied
document/authority/query inputs, permitted next step, and the untouched backend
response or receipt. The backend payload remains authoritative for state,
evidence, rejection reason, and transition status. Never report `archived` or
reopened until that payload says so; after returning one backend outcome, stop.

## Self-Check

- Was the Skill explicitly triggered rather than inserted as a Room stage?
- Did active-only discovery remain the default and archived history stay
  opt-in?
- Did archive carry authoritative terminal evidence for the same authority and
  document?
- Did the backend remain the only lifecycle and state owner?
- Did I keep archive, delete, and erase distinct?

## Boundaries

Never move, rename, create, or delete work-document files; set terminal state;
edit a registry, outbox, index, receipt, Goal, Plan, or Room; infer authority;
include archived results by default; call erase operations; or claim ownership
of archive, repair, or reopen lifecycles. This Skill is ordinary on-demand
catalog content, not a mandatory Room stage.
