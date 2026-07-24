---
name: grill-me
description: Resolve one consequential product, architecture, permission, or interaction tradeoff through focused questioning. Use when the user explicitly asks to be challenged or when evidence cannot decide a choice that materially changes the result; do not use for routine Room intake.
when:
  - 用户说 grill me、要求质询方案，或真实取舍尚未形成共同理解
does: 先自行核对事实，再一次只追问一个必须由用户决定的取舍。
input: 待决定的问题、已知事实、候选方案、约束和当前分歧。
output: 决策记录、理由、被否决选项、未决问题和可验收下一步。
notFor:
  - 能从源码、测试、配置或运行证据直接查明的事实
  - 普通 Room 需求收集、已经明确的决定、进度确认或借提问拖延执行
---

# Grill Me

## Workflow

1. Restate the single decision and the user-visible consequence of choosing it
   incorrectly. Do not widen the discussion to adjacent design questions.
2. Inspect available source, tests, configuration, and runtime evidence first.
   Do not ask the user to rediscover facts the system can verify.
3. Present at most three materially different options. For each, give the
   user-visible effect, main tradeoff, and your recommendation in plain
   language. Do not present cosmetic variants as separate options.
4. Ask exactly one decision question. Do not bundle unrelated choices.
5. Treat a direct answer such as "按建议", "全部采用", or an explicit option
   choice as a decision. Do not ask the same question again in different words.
6. After the answer, update the decision record and check whether another
   consequential tradeoff still blocks the next phase. Repeat only when needed.
7. End with the chosen rule, reasons, rejected alternatives, acceptance
   consequence, and any still-open question. Hand this decision back to the
   calling conversation; do not start work yourself.

## Exit Contract

Exit as `decision_ready`, `needs_one_more_decision`, or
`blocked_by_external_fact`. A decision is ready only when the surrounding
requirement or planning conversation can continue without guessing about this
tradeoff.

## Boundaries

Do not turn source facts into preference questions, steer the user toward a
hidden favorite, interrogate for completeness after the material decision is
settled, implement before shared understanding, create a Task or Dispatch, or
claim completion. The user owns product tradeoffs; the surrounding
conversation chooses any next Skill, and Kernel plus native approval own
execution authority.
