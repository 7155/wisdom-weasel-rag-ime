# Simple Implementation Continuity

Borrow the useful part of an LLM Wiki: recover from a small index, then open
one current document. Do not build a Wiki system.

## Layer 1: One Small Project Index

Use the project root to select `docs/agent/chat-summary.md`. Maintain one
replace-in-place block at its top:

```markdown
<!-- implementation-continuity:start -->
## Current Implementation

- Updated: <time>
- Plan: <accepted plan ref and revision>
- Active responsibility: <existing Goal, Task or Dispatch ref>
- Work document: <canonical active path and content hash>
- Slice: <one current vertical code slice>
- Next: <one smallest evidence-producing action>
- Freshness: <branch and HEAD; dirty paths summarized>

### Open acceptance
- <alias>: <next observable condition>                   <!-- at most 6 -->

### Blockers
- <blocker>: resume when <objective condition>           <!-- at most 3 -->

### Verified project facts
- <fact>: <source path and revision or evidence ref>     <!-- at most 10 -->

### Failed approaches
- <attempt>: <evidence that rules it out>                <!-- at most 3 -->
<!-- implementation-continuity:end -->
```

Omit empty sections. Keep the complete block below 100 lines and 8 KiB. It is
an index, not a diary or the detailed implementation record.

## Layer 2: One Work Item, One WorkDocument

Use the existing Runtime authority: `session_todo`, `session_goal`, or
`room_work_item`. Its authority key identifies one WorkDocument automatically;
do not invent another work ID. All Todo revisions, code slices, reviews, and
commits for that responsibility update the same canonical active file. A commit
never creates a WorkDocument.

Every WorkDocument begins with:

```markdown
<!-- user-source:start -->
## User Source — Preserve Verbatim

### Original User Request
Source: <message/event or RequirementAnchor ref>; UTF-8 SHA-256: <required>
> <exact user text in its original language and order>

### Original User Vision
Source: <message/event or RequirementAnchor ref>; UTF-8 SHA-256: <required>
> <exact end-state or why text, or: Not separately stated>

### Later User Corrections
- Source: <ref when available>
  > <exact later user text; append only>
<!-- user-source:end -->

## AI Interpretation
<derived scope, decisions, plan, progress, and explanation>
```

For Room implementation, keep one compact block below the interpretation:

```markdown
### Workspace Ledger
- Room / responsibility: <Room ref; Root, WorkItem or Task ref; owner>
- Requirements: <current requirement revision and acceptance aliases>
- Binding: <binding ref; policy; common baseline; physical workspace when bound>
- Delivery / integration: <authoritative lifecycle and evidence refs>
- Cleanup: <cleaned, retained, retry-bound, abandoned, or attention reason>
```

Replace this block from the latest Runtime task context and workspace receipts;
do not append a transition diary. Keep the binding and final integration/cleanup
outcome after the physical worktree is removed. Retained, conflicting,
cancelled, blocked, incomplete, or orphaned work stays unresolved until a
receipted retry/rebind or snapshot/hash-bound abandonment. This mirror never
creates a workspace, authorizes integration or cleanup, or overrides Runtime.

The original request and vision are immutable. Later corrections append; they
never rewrite history. AI interpretation may be replaced as understanding
improves. In a Room, copy original RequirementAnchor bytes, not a derived
RequirementCatalog sentence. If credentials appear, persist an explicit
redaction marker instead of the secret and alter no other user text.

## Read and Update

1. After compaction, handoff, or a fresh Session, read only the project index,
   then the referenced active WorkDocument, then the source paths needed next.
   Do not read chronological project history or archived documents by default.
2. Before each slice, recheck source hashes and compare plan and acceptance
   against the verbatim request, vision, and corrections. Repair drift first.
3. Inspect source before editing it. Source wins over stale navigation notes.
4. Update the same WorkDocument only when interpretation, decision, slice,
   evidence, blocker, failed approach, next action, or authoritative workspace
   lifecycle changes. Do not append a Tool or commit transcript.
5. Only the active implementation owner writes it. Helpers return proposed
   deltas so concurrent Agents do not race on one file.
6. Rewriting unchanged content is a no-op.

## Archive and Retention

- The WorkDocument backend remains lifecycle owner. A canonical terminal
  receipt moves the complete file from `docs/agent/work/active/` to
  `docs/agent/work/archive/`; Skills never move it themselves.
- Archive immediately on authoritative terminal state. A recent-completed view
  should query archive instead of keeping finished documents active on a timer.
- Archived documents are retained indefinitely and excluded from default
  context. There is no automatic expiry or deletion. A separate user-approved,
  hash-bound destructive erase is the only removal path.
- Explicit history search or an authoritative reopen may load an archive.

## Evidence Boundary

Both files are navigation, never authority. Current user instructions, Runtime
state, repository source, Git state, fresh tests, receipts, and real runtime
observations remain authoritative within their measured boundaries. Do not
mark acceptance complete in these files or add a separate schema, index,
compilation pass, promotion service, or document database.
