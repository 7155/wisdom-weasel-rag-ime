---
name: structured-result-presentation
description: Present inspectable results as bounded typed blocks without leaking raw structured payloads into model context.
when:
  - 结果包含适合扫读的卡片、清单、表格、产物、引用或状态
  - 用户需要可刷新、可复查的结构化交付
does: 选择最小内容块，优先受信任结构化通道，无工具时才输出完整 fenced fallback。
input: 已完成结果、可公开证据和目标展示形态。
output: 最小可扫读内容块与不重复的文字结论。
notFor:
  - 纯短文本回答或私有推理过程
  - HTML、小组件、脚本、任意网页内容
---

# Structured Result Presentation

## Positive Triggers

Use the smallest block that improves inspection:

- `card`: one compact result with a title and a few related facts. Not for long prose.
- `checklist`: bounded items whose completed state matters. Not for unordered notes.
- `table`: comparable rows with stable columns. Not for a single fact or narrative.
- `artifact`: a generated file or durable output reference. Not for inline prose.
- `reference`: a source or evidence reference the user may revisit. Not for unsupported claims.
- `status`: a current state, outcome, or bounded progress signal. Not for hidden reasoning.

Keep the ordinary assistant text as the human-readable conclusion. Do not repeat
the complete block data in that text.

## Delivery Order

1. When `room_post` or `room_commit` exposes typed `blocks`, put only
   `{id,type,data}` in that tool argument. The server owns source, visibility,
   generation, digest, ref, summary, and presentation metadata.
2. On another trusted runtime event surface, emit `agentBlocks` beside the
   assistant message. Do not serialize those blocks into the message text.
3. Only when neither structured surface exists, append exactly one complete
   fallback fence after the readable answer:

````text
```rag_ime_blocks
{"schemaVersion":"rag-ime.agent-blocks.v1","blocks":[{"id":"check:release","type":"checklist","data":{"title":"发布","items":[{"text":"测试通过","checked":true}]}}]}
```
````

The fallback must be complete JSON. Never stream a partial fence. If valid JSON
cannot be completed, omit the fence and return readable text only.

## Hard Boundaries

- Maximum 16 blocks; prefer one to three.
- Never emit `html_widget`, HTML, script, style, `srcdoc`, event-handler keys,
  CSS, `javascript:` URLs, or untrusted URL schemes.
- Never supply server-owned metadata and never invent a digest or ref.
- Do not duplicate raw rows, checklist items, or artifact metadata in prose.
- Blocks describe results. They do not contain private reasoning, tool traces,
  capability data, routing commands, or another Agent's internal Session.
