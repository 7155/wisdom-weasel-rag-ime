---
name: structured-handoff
description: Hand bounded work to another owner with enough public evidence and an exact takeover point, without dumping private Session process.
when:
  - 当前所有者无法或不应继续，需要转移责任
does: 汇总证据、失败、剩余验收和准确接手点。
input: 当前责任、证据、失败、剩余验收、风险和所需能力。
output: 可接管的公开交接包和建议接手对象。
notFor:
  - 最终收口、进度播报或不转移责任的并行咨询
---

# Structured Handoff

## Core Principle

A handoff is not "I changed some files." It is a bounded transfer of
responsibility that lets the receiver decide and act without reconstructing the
sender's private Session. If the receiver cannot identify the remaining work,
the evidence, and the first safe action, the handoff is incomplete.

## Five-Part Packet

Every handoff must contain:

1. **What**: completed behavior, changed artifacts, and inspectable evidence.
2. **Why**: why responsibility must move now and why this receiver fits.
3. **Tradeoff / Attempts**: rejected or failed approaches only when they
   prevent repeated work; include observed results, not hidden reasoning.
4. **Open Questions / Risks**: unresolved facts, assumptions, permissions,
   cancellation state, and remaining acceptance aliases.
5. **Next Action**: one exact takeover point, expected output, and resume
   condition.

## Workflow

1. Use the latest Room state already present in context. Call `room_state`
   only when that state is absent or its revision no longer proves current
   responsibility, then confirm that this is a real ownership transfer. Use
   `room_collaborate` instead when you still own and can continue the current
   responsibility.
2. Reconcile the packet with the immutable request, current Dispatch, accepted
   decisions, current artifacts, and successful Tool receipts.
3. Map completed and remaining work to the human-readable acceptance aliases.
   Evidence references must come from successful Tool results; prose claims
   are not evidence.
4. Choose an eligible receiver from the current participant directory. If the
   current model cannot finish, name the required participant or model
   capability and explain the fit. Do not invent a receiver.
5. Write the five-part public packet. Keep it narrow enough that ownership is
   unambiguous and complete enough that the receiver need not reread the whole
   transcript.
6. Submit `room_commit` with `decision=handoff`, the receiver reference, intent,
   next task, expected output, remaining acceptance aliases, evidence, and
   residual risks.
7. After the Kernel accepts the handoff, stop changing the transferred work.
   A rejected proposal leaves ownership unchanged; repair only the named
   contract error.

## Complete Example

```text
What: parser now preserves quoted commas; focused regression passed (evidenceRef ...).
Why: remaining macOS packaging check requires the release-capable participant.
Tradeoff/Attempts: local unsigned build passed; signing was not attempted without that capability.
Open Questions/Risks: AC "installed app opens" remains; notarization is outside this task.
Next Action: build from the current clean commit, install, open once, and return the install receipt.
```

Incomplete: "I changed the parser, please take over." It omits evidence,
remaining acceptance, receiver fit, and the exact first action.

## Output Contract

Return the five-part packet, recommended receiver or model capability,
completed and remaining acceptance, relevant artifacts, evidence references,
exact takeover point, blockers, risks, and resume condition. The packet is a
proposal; only the accepted Kernel receipt creates the next Dispatch.

## Self-Check

- Can the receiver begin with one concrete action?
- Can a reviewer distinguish completed, failed, and merely unverified work?
- Did every completion claim cite an inspectable successful receipt?
- Will both owners avoid editing the same responsibility after acceptance?

## Boundaries

Do not dump the transcript, leak private Session reasoning, use handoff as a
progress post or final closure, wake an Agent through free-text `@`, grant
capability, transfer to an unknown participant, or keep changing accepted
transferred work.
