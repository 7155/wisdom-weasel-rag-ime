---
name: requirement-alignment
description: Turn an intended piece of work into a user-confirmed scope and acceptance packet before planning or managed execution begins.
when:
  - 目标将进入执行，但范围、验收或禁区未确认
does: 保留用户原话，只追问会改变结果的缺口。
input: 用户原话、纠正、事实、约束和未决项。
output: 范围、验收、禁区、非目标、未决项和确认状态。
notFor:
  - 闲聊、已确认需求或能直接查明的事实
---

# Requirement Alignment

Use this Skill in the same user-facing Session that received the goal. A Room
may later execute the work, but alignment is not a Room routing event and does
not create a master Agent.

## Two-Layer Requirement Model

- **Original request**: byte-preserved user input and later explicit
  corrections. It is immutable evidence.
- **Requirement directory**: a revisionable working index containing scope,
  acceptance, constraints, non-goals, decisions, and open questions. It may be
  corrected, but never overwrites the original.

## Workflow

1. Preserve the user's original wording as the immutable source. Later answers
   and corrections may refine the working requirement directory, but never
   replace that source.
2. Separate what can be inspected, what has a safe reversible default, and
   what only the user can decide. Inspect the first two before asking.
3. Ask one material question at a time only when its answer can change scope,
   acceptance, permission, cost, ownership, safety, or an irreversible action.
   Use `grill-me` only for a consequential tradeoff that deserves explicit
   challenge; routine clarification stays here.
4. Accept concise answers such as "按建议" or "全部采用". Do not reopen a
   resolved choice in different words.
5. When no material gap remains, present one compact confirmation packet:
   original goal, in-scope result, user-visible acceptance checks, constraints
   and permissions, explicit non-goals, reversible defaults, and remaining
   risks.
6. Wait for an explicit confirmation or correction. Silence, a topic change,
   or an Agent's own summary is not confirmation.

## Confirmation Packet

```text
Goal:
In scope:
Acceptance:
Constraints and permissions:
Non-goals:
Decisions and reversible defaults:
Open questions:
Readiness status:
```

Acceptance must be observable in user or runtime terms. "Implement the
backend" is work; "a cancelled Room rejects every late write and the UI stays
locked until Root quiescence" is acceptance.

## Question Rule

Ask only when the answer changes the result. A good question names the decision
and its effect: "Should Room be workspace-managed or fully trusted? The first
asks only on boundary escape; the second removes ordinary approval but keeps
workspace, cancellation, audit, and dangerous-action fences."

Bad questions ask for repository facts, repeat an already confirmed choice, or
bundle several unrelated decisions.

## Output Contract

Return one human-readable packet with one status:

- `needs_user_answer`: exactly one material question remains;
- `ready_for_confirmation`: the packet is complete but not approved;
- `confirmed`: the user approved this revision;
- `blocked_by_external_fact`: an indispensable fact cannot be obtained.

Always include `Open questions` and `Readiness status`. A confirmed packet is
input to planning; it is not itself a WorkItem or authorization.

## Self-Check

- Are the user's original words still available unchanged?
- Can each acceptance item be verified without guessing?
- Did I separate fact lookup, reversible defaults, and user-owned decisions?
- Did the user explicitly confirm this revision?
- Did I avoid starting work or routing Agents before confirmation?

## Boundaries

Do not ask for inspectable facts, turn reversible details into product
decisions, erase the original request, start implementation, create managed
work, route an `@`, or treat confirmation as permission for unrelated actions.
