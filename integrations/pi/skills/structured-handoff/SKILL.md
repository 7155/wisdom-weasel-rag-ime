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

A handoff is not "I changed some files." It is a bounded transfer of
responsibility that lets the receiver decide and act without reconstructing the
sender's private Session. If the receiver cannot identify the remaining work,
the evidence, and the first safe action, the handoff is incomplete.

## Private Receiver Packet

Every handoff must preserve these fields for the receiving AI and Kernel:

1. **What**: completed behavior, changed artifacts, and inspectable evidence.
2. **Why**: why responsibility must move now and why this receiver fits.
3. **Tradeoff / Attempts**: rejected or failed approaches only when they
   prevent repeated work; include observed results, not hidden reasoning.
4. **Open Questions / Risks**: unresolved facts, assumptions, permissions,
   cancellation state, and remaining acceptance aliases.
5. **Next Action**: one exact takeover point, expected output, and resume
   condition.

Exact aliases, evidence references, receiver references, and takeover commands
stay in structured private fields. The public report translates only what the
user needs to understand the transfer.

## Workflow

1. Use the latest Room state already present in context. Call `room_state`
   only when that state is absent or its revision no longer proves current
   responsibility, then confirm that this is a real ownership transfer. Use
   `room_collaborate` instead when you still own and can continue the current
   responsibility.
2. Reconcile the private packet with the verbatim user text supplied by the
   Runtime, later append-only corrections, current Dispatch, accepted
   decisions, current artifacts, and eligible evidence.
3. Map completed and remaining work to the exact acceptance aliases in
   structured Tool fields. Evidence references or receipts must be fresh and
   eligible under the active
   lifecycle schema; prose claims alone are not evidence.
4. Choose an eligible receiver from the current participant directory. If the
   current model cannot finish, name the required participant or model
   capability and explain the fit. Do not invent a receiver.
5. Write a separate public handoff report in natural language: what is done,
   why responsibility is moving, useful observed attempts, open risk, and the
   high-level next action. Do not expose exact aliases, references, participant
   IDs, protocol vocabulary, or private takeover instructions.
6. Submit `room_commit` with `decision=handoff`, the private receiver reference,
   intent, next task, expected output, remaining acceptance aliases, evidence,
   residual risks, and the separate public report.
7. After the Kernel accepts the handoff, stop changing the transferred work.
   A rejected proposal leaves ownership unchanged; repair only the named
   contract error.

## Complete Example

Private receiver fields record that the parser preserves quoted commas, the
focused regression evidence, the release-capable receiver, the exact packaging
check, its expected output, and the remaining acceptance alias.

Public report:

```text
Quoted commas now parse correctly and the focused regression passes. The
remaining packaging check needs the release-capable teammate, so I have
transferred that bounded check. Signing remains unverified; the next visible
result will be the installed-app launch check.
```

Incomplete: "I changed the parser, please take over." It omits completed work,
the transfer reason, risk, and the next observable result.

## Output Contract

Return two distinct products: the private five-part receiver packet with exact
aliases, artifacts, evidence references, receiver and takeover fields; and a
plain-language public report with completed work, transfer reason, useful
attempt results, open risk, and high-level next action. Only the accepted
Kernel receipt creates the next Dispatch.

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
