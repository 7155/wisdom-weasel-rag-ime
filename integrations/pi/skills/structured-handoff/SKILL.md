---
name: structured-handoff
description: Hand bounded work to another owner with a private structured receiver packet and a concise user-facing transfer report, without dumping Session process.
when:
  - 当前所有者无法或不应继续，需要转移责任
does: 汇总证据、失败、剩余验收和准确接手点。
input: 当前责任、证据、失败、剩余验收、风险和所需能力。
output: 私有接手包，以及说明已完成内容、转交原因、风险和下一步的公开报告。
notFor:
  - 最终收口、进度播报或不转移责任的并行咨询
---

# Structured Handoff

## Core Principle

A handoff transfers bounded responsibility. The receiver must understand the
remaining work, evidence, and first safe action without reconstructing private
Session history. Reference plans, WorkDocuments, decisions, diffs, and evidence
by stable ref instead of copying. Redact credentials, tokens, PII, and private
context, leaving an explicit redaction marker when material.

## Workflow

1. Confirm this is a real ownership transfer using current Runtime/Room state.
   Use bounded collaboration when the current owner can and should continue;
   never wake an owner through a free-text mention.
2. Reconcile the packet with original user text, append-only corrections,
   current responsibility, accepted decisions, artifacts, and evidence.
3. Map complete and remaining work to exact acceptance aliases in private
   fields. Evidence must be fresh and eligible under the active
   lifecycle schema; prose claims alone are not evidence.
4. Choose an eligible receiver from the governed Room roster. The Facilitator
   owns assignment and reassignment; do not use round-robin or silently recruit
   a new Agent. If the current model cannot finish, name the required
   capability and explain why.
5. Write a distinct public report: completed behavior, transfer reason, useful
   observed attempts, open risk, and high-level next action. Hide aliases,
   internal refs, participant IDs, protocol language, and takeover commands.
6. Submit through the active lifecycle Tool with receiver, intent, next task,
   expected output, remaining aliases, evidence, risks, and public report.
7. Stop editing transferred work after acceptance. If rejected, ownership has
   not moved; repair only the named contract problem.

## Managed Room Boundary

- The Facilitator owns decomposition, assignment, reassignment, dependency
  handling, and integration. A formal transfer is a new bounded
  `room_partner(operation="delegate")` call, not a free-text mention.
- The receiver uses its own Session and the workspace mode selected for that
  delegation.
  Participant identity is distinct from a filesystem root. For concurrent
  writable children, require separately receipted isolated workspaces from the
  same Root baseline and one Facilitator-owned integration workspace. Do not
  claim automatic Git worktree cloning without a receipt.
- Temporary Session micro-agents may call peers directly inside their bounded
  Session tree, but remain private at the Room boundary. Use a formal Room
  partner when attribution and visible lifecycle matter.
- Review is optional and begins only after integration when the Facilitator
  chooses it by risk. Delegate a fixed review scope to a distinct participant;
  self-review is forbidden. If review is not chosen, do not manufacture it.
- Keep private refs and takeover details private. Only the Facilitator/reporter
  owns the Root's final public summary.
- Transfer only accepted evidence receipts; a filesystem path or participant
  prose cannot establish completion or ownership.
- A review receiver must be a distinct participant, never the author or
  Integrator.

## Private Receiver Packet

1. **What**: completed behavior, changed artifacts, inspectable evidence.
2. **Why**: transfer reason and receiver fit.
3. **Tradeoff / Attempts**: observed failed or rejected routes worth preserving.
4. **Open Questions / Risks**: assumptions, permissions, cancellation, and
   remaining acceptance.
5. **Next Action**: one exact takeover point, expected output, and resume condition.

Public report:

```text
What now works and how it was checked. Why ownership is moving. What remains
uncertain. What user-visible result should happen next.
```

## Output Contract

Return two distinct products: a private five-part receiver packet containing
exact aliases, artifacts, evidence, receiver, and takeover fields; and a
plain-language public report containing completed behavior, transfer reason,
useful attempt results, open risk, and next action. Ownership changes only
after the Facilitator accepts the delegated result and stops editing the
transferred scope concurrently.

## Self-Check

- Can the receiver start with one concrete action at the exact takeover point?
- Are complete, failed, and unverified work distinguishable?
- Does every completion claim cite inspectable evidence?
- Are referenced artifacts stable and sensitive content redacted?
- Will owners avoid concurrent edits after acceptance?

## Boundaries

Do not dump transcripts or reasoning, leak sensitive context, use handoff for
progress or final closure, wake an Agent through free text, grant capability,
duplicate artifacts, transfer to an unknown owner, or keep editing after an
accepted handoff.
