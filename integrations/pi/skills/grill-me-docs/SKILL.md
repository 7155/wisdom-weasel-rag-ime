---
name: grill-me-docs
description: Resolve one consequential architecture or product decision after source and runtime evidence cannot decide it, then preserve only user-confirmed decisions and genuinely open questions in durable project documentation. Use only when the user wants an ADR, glossary, or durable decision record.
when:
  - 用户要求 grill with docs，或要把未决重大取舍写成 ADR、术语表或决策文档
  - 源码和运行事实已核对，仍有会改变架构或产品行为且须用户选择的取舍
does: 沿用 grill-me 的一次一问，只记录用户确认的决定和开放问题。
input: 已验证事实、一个未决取舍、候选、既有文档与目标路径。
output: 确认的决策或开放问题，以及必要的术语、ADR 或决策文档更新。
notFor:
  - 普通修复、事实查询、清晰需求、可逆默认或例行 Room 阶段
  - 用户未要求落盘，或只需要 grill-me
  - 面试闲聊、模型猜测、未验证建议、临时进度或工具日志
---

# Grill Me Docs

## Place in the Existing Workflow

This is the durable-output mode of `grill-me`, not a second planner.
`requirement-alignment` still owns scope and acceptance, while
`solution-convergence` still compares viable approaches. Use this Skill only
to resolve one remaining user-owned decision and preserve its confirmed result.

## Entry Gate

Proceed only when all of these are true:

1. The user wants a durable glossary, ADR, or decision/open-question record.
2. Relevant source, tests, configuration, documentation, and runtime evidence
   have already been inspected.
3. Evidence cannot settle one consequential architecture or product choice.
4. The repository's documentation convention and the intended write target
   are known. Native write approval remains required.

If evidence answers the question, return that fact to the caller. If the user
does not want durable artifacts, use `grill-me`. Do not turn either case into
this workflow.

## Workflow

1. Read the repository guide and existing glossary, ADRs, and decision records.
   Separate observed facts from user-owned choices before asking anything.
2. State one decision, its user-visible or architectural consequence, at most
   three materially different options, and one recommended answer.
3. Ask exactly one decision question and wait. A recommendation is not a
   decision.
4. Accept only the user's direct answer as the choice. Agent summaries, model
   guesses, tool output, silence, and private Room discussion cannot confirm a
   decision.
5. After confirmation, update only the agreed documentation:
   - record the chosen rule and verified context;
   - keep a genuinely unresolved item explicitly labelled as an open question;
   - add a glossary term only when the user confirmed the canonical meaning;
   - offer an ADR only when the choice is hard to reverse, surprising without
     context, and the result of a real tradeoff.
6. Preserve existing repository conventions. Create a glossary or ADR location
   lazily only when the user requested that artifact and the write is approved.
7. If another consequential decision remains in the requested scope, repeat
   one question at a time. Otherwise return the documented decision and the
   exact handoff point without starting implementation.

## Documentation Contract

```text
Decision status: confirmed by user | open question
Verified context:
Decision question:
User choice:
Reason stated by user:
Rejected alternatives:
Consequences:
Open questions:
Evidence references:
```

Omit fields that add no value. Never fill a missing user reason with a model
inference. A glossary defines project language, not implementation or a hidden
spec. An open question stays visibly unresolved and must not be phrased as a
fact.

## Output Contract

Exit as `needs_user_answer`, `decision_documented`,
`open_question_documented`, `no_document_worthy_decision`, or
`blocked_by_external_fact`. Include the document path and changed section only
after an approved write has actually succeeded.

## Self-Check

- Did evidence lookup finish before the first question?
- Did I ask exactly one user-owned decision and recommend an answer?
- Is every recorded decision backed by a direct user choice?
- Are guesses, interview chatter, private Room process, and tool logs absent?
- Did I keep planning, managed work, and implementation outside this Skill?

## Boundaries

Do not write code, start implementation, create Task or Dispatch state, add a
mandatory Room stage, or claim that documentation approval grants execution
authority. Do not record model recommendations as decisions, turn an open
question into truth, or persist unverified claims. The surrounding conversation
and Kernel own every later workflow and permission decision.
