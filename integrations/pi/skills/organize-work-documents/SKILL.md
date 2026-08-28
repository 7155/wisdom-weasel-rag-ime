---
name: organize-work-documents
description: "Build a lossless, source-linked ledger from user-original requirements, then check, link, condense, and index work documents maintained by Session and Room Agents. Use when an explicit request or background organizer captures source wording, requirement meaning, corrections, document receipts, or accepted results. Do not use to perform active work, infer Runtime status, overwrite an active owner's meaning, or block finalization; e.g., report an orphaned WorkItem to its supervisor instead of assigning an Agent."
---

# Organize Work Documents

Act as a document gardener. Active Agents create and update work meaning; this
Skill turns the user's source wording into a complete, navigable requirement
record without discarding the wording, constraints, corrections, or evidence
that gave each requirement its meaning.

## Lossless User Requirement Ledger

For a requirements, decision, TaskBrief, WorkDocument, or handoff derived from
user messages, place a clearly labelled **User Requirement Ledger** immediately
below the document title, before metadata, implementation plans, status claims,
or Agent-authored summaries. The ledger is the organized meaning of the user's
messages, not a transcript dump.

Each ledger entry must have a stable requirement ID and contain:

```text
ID and topic | state and priority
current controlling requirement | user-visible acceptance meaning
must preserve | must not do | dependencies or ordering
source quotes and source refs | corrections and superseded meanings
```

- Organize by product meaning, not message order. Translate every relevant user
  statement into the behavior, capability, constraint, prohibition, sequence,
  or acceptance result it actually requires. Do not reduce a concrete request
  to a vague theme such as "improve UX".
- Keep the organized requirement distinct from its evidence. Copy supporting
  user words verbatim in the entry or link to an immediately following raw
  evidence section. Preserve wording, punctuation, typos, repetition, and
  corrections; never silently polish a quotation.
- Record the source thread/task and message or turn identifiers when available.
  Include only actual user-message text. Ambient UI state, attachment wrappers,
  tool output, and Agent paraphrases are not user requirements.
- Mark each entry `current`, `superseded`, `ambiguous`, or `pending decision`.
  Put the newest controlling correction first. Retain older quotations and link
  them with `supersedes` / `superseded by`; never delete or rewrite history to
  hide a conflict.
- Merging repeated statements is allowed only when every source reference stays
  attached and every distinct detail survives in the organized requirement.
  Repetition can strengthen priority; it is not permission to drop constraints.
- Maintain a source-coverage audit. Every relevant source message must map to at
  least one requirement ID or be explicitly labelled duplicate, reference-only,
  non-requirement, or unavailable. Report unmapped sources and evidence gaps;
  never imply complete coverage when retrieval was partial.
- Separate user-owned meaning from Agent-derived interpretation. Acceptance
  criteria may make user-visible meaning testable, but they must not introduce
  new scope, Runtime facts, implementation choices, or product copy.
- If exact wording cannot be retrieved, record the missing source reference and
  the gap. Never manufacture a quotation from memory or an Agent summary.
- An external raw-source file is acceptable only when the primary document
  starts with the organized ledger and links directly to the evidence. A buried
  handoff-only copy does not satisfy this rule.

## Completion Must Be Recorded

Requirements at the start and results at the end are one document loop. The
active Session or Room owner, not the background organizer, writes a closing
revision after the work actually reaches a terminal result.

The closing revision must record:

```text
result and requirement IDs satisfied | changed files or artifacts
operability verification and evidence | requirement-satisfaction verification
installed/foreground proof when required
unverified boundaries | residual risks | rollback or next action
owner and timestamp | document revision/hash receipt
```

- A partial or blocked result is still recorded, with completed scope, blocker,
  and one executable next step. It must not be rewritten as complete.
- Tests, builds, screenshots, health probes, installation, and real foreground
  acceptance are separate evidence levels. Record only the levels actually
  proved by receipts.
- The organizer verifies that a closing revision and its source receipt exist,
  links accepted results into the relevant requirement/outcome/handoff, and
  reports a missing or stale closeout as an owner-visible gap.
- For each substantive WorkItem, audit the requirement refs, current and
  accountable owners, Session/conversation and WorkDocument refs, next action,
  verification responsibility, both verification axes, and terminal receipt.
  Report orphaned, unfinished, or unclosed items to the supervisor; the
  organizer does not assign Agents or invent their Runtime state.
- The organizer never marks Runtime work complete from prose, a checkbox, a
  diff, or silence. Completion still belongs to the authoritative Runtime and
  the active owner's accepted result.
- Condensation may shorten closed history only after the result, evidence,
  residual risk, source refs, and revision receipt remain recoverable.

## Large Ledgers May Be Split

Split an oversized requirement ledger when one file has become harder to find,
read, or edit than a small document set. Splitting is a navigation change, not
permission to summarize, renumber, drop quotations, or weaken source coverage.

- Keep one canonical index at the original well-known path. It names every
  ledger file, its exact stable-ID range or product domain, and the separate
  evidence, status, contract, and handoff files that belong to the set.
- Give every split file a clear `previous / index / next` navigation block near
  the top and a **Continue reading / editing** block at the end. The final block
  names the exact next file; the last file points to the status or evidence file
  instead of ending silently.
- Prefer stable-ID ranges when requirements are already numbered and later
  corrections rely on sequence. Prefer product-domain volumes only when every
  requirement has one unambiguous home and cross-domain indexes remain complete.
- Preserve stable requirement IDs and existing source refs. Keep completion
  state in the canonical status ledger rather than copying drifting state into
  every volume.
- Update backlinks and discovery documents so an Agent entering through the
  index, any volume, status ledger, evidence file, or handoff can discover the
  complete document set without scanning the repository.
- After splitting, verify both directions: the union of volumes contains every
  requirement exactly once, and every indexed file exists. Report any gap or
  duplicate instead of treating the split as complete.

## Workflow

1. Start from document-update receipts, final results, accepted decisions, and directly referenced documents. Do not reconstruct work from entire transcripts unless the user explicitly asks to recover original requirements from a named task or conversation; in that case, extract only user messages, preserve exact wording and source identity, and record the retrieval boundary.
2. Identify document owners and active scopes before editing.
3. Inventory source messages, assign source refs, and classify each as requirement, correction, constraint, prohibition, acceptance result, duplicate, reference-only, non-requirement, or unavailable.
4. Build or verify the lossless ledger before touching implementation plans or summaries. Give each requirement a stable ID, current controlling meaning, source evidence, correction links, and user-visible acceptance meaning.
5. Audit both directions: every source maps to a ledger entry or explicit exclusion, and every ledger claim maps back to source evidence. Resolve no ambiguity by invention.
6. For terminal work, verify the active owner recorded a closing revision with result, changed artifacts, verification evidence, unverified boundaries, residual risk, and a revision/hash receipt. Record partial or blocked outcomes truthfully.
7. Check summaries, refs, revisions, links, duplicate sections, stale claims, WorkItem responsibility fields, both verification axes, missing accepted results, missing closeout receipts, and oversized completed history.
8. Apply low-risk structural updates: requirement ledgers, exact-source evidence, coverage matrices, closeout links, indexes, headings, source metadata, compact summaries, and condensation of closed material.
9. Preserve original meaning and evidence. Propose a delta instead of rewriting ambiguous, conflicting, or still-active semantic content.
10. Promote only cross-scope accepted results into higher-level summaries; keep transient progress and Runtime facts out.
11. Emit document-update events for changed revisions and a bounded issue list for owners.

## Output

Return the common `AgentResult` envelope with:

```text
documents inspected | user-source coverage and gaps
lossless requirement ledger | source-to-requirement coverage audit
structural updates | proposed semantic deltas | conflicts and corrections
broken or stale refs | condensed history | higher-level summary updates
completion records and both verification axes | orphaned or unclosed gaps
document update receipts | owner-visible issues
```

## Not For

Do not perform the underlying task, infer completion or ownership from Markdown, overwrite an active owner's meaning, mutate Skill workflows or model/persona cards silently, or block Session and Room finalization.

Example: a checked box may be stale; use the Runtime projection or accepted result rather than converting it into a completion fact.
