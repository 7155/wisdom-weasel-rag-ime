---
name: organize-work-documents
description: "Check, link, condense, and index work documents already maintained by Session and Room Agents. Use when the existing background organizer or an explicit cleanup request processes document receipts or accepted results. Do not use to perform active work, infer Runtime status, overwrite an active owner's meaning, or block finalization; e.g., do not mark a task complete from a Markdown checkbox."
---

# Organize Work Documents

Act as a document gardener. Active Agents create and update work meaning; this Skill keeps that material navigable and internally consistent.

## Workflow

1. Start from document-update receipts, final results, accepted decisions, and directly referenced documents. Do not reconstruct work from entire transcripts.
2. Identify document owners and active scopes before editing.
3. Check summaries, source refs, revisions, links, duplicate sections, stale claims, missing accepted results, and oversized completed history.
4. Apply low-risk structural updates: indexes, links, headings, source metadata, compact summaries, and condensation of closed material.
5. Preserve original meaning and evidence. Propose a delta instead of rewriting ambiguous, conflicting, or still-active semantic content.
6. Promote only cross-scope accepted results into higher-level summaries; keep transient progress and Runtime facts out.
7. Emit document-update events for changed revisions and a bounded issue list for owners.

## Output

Return the common `AgentResult` envelope with:

```text
documents inspected | structural updates | proposed semantic deltas
broken or stale refs | condensed history | higher-level summary updates
document update receipts | owner-visible issues
```

## Not For

Do not perform the underlying task, infer completion or ownership from Markdown, overwrite an active owner's meaning, mutate Skill workflows or model/persona cards silently, or block Session and Room finalization.

Example: a checked box may be stale; use the Runtime projection or accepted result rather than converting it into a completion fact.
