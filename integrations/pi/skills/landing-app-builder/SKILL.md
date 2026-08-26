---
name: landing-app-builder
description: Turn a user-described vertical need into a reusable Pi Package (Skill + optional prompt/theme) for PAW landing forms. Use when the user wants to create a domain App such as 智能调研、问数、知识问答助手; after drafting, stop at propose_install so the product can prompt installation. Do not use for ordinary one-off answers, for forking Pi Runtime/shell, or to claim an App is installed without an apply receipt.
metadata:
  routing:
    when:
      - 用户描述一个可复用的落地场景或垂直助手并希望变成可安装 App
      - 落地形态下需要为新能力写 Skill / prompt / theme 并提交安装预览
    does: 分析需求、起草最小 Package、校验并提出安装；停在产品确认。
    input: 场景目标、验收、是否需要主题或定期报告。
    output: Package 草稿、校验、propose_install 预览；不声称已安装。
    notFor:
      - 一次性问答或普通改文件
      - 绕过确认、伪造安装、或第二套 Runtime
---

# Landing App Builder

Turn a described vertical into a **installable Pi Package** that PAW can surface
as a Launchpad identity. Packages carry Skills / prompts / themes / extensions —
never executable UI. New chrome or charts stay first-party; themes may change
atmosphere.

## Workflow

1. Restate the landing job: who uses it, default Dock focus, Knowledge scope,
   and how success is checked. Prefer one Package purpose.
2. Call `plugins` `op=catalog` then `op=list`. Reuse when a package already fits.
3. When creating, build the smallest Package:
   - one Skill that says when / not for, with concrete examples (e.g. 智能调研);
   - optional prompt for the answering style;
   - optional theme tokens only if display must feel distinct;
   - no second Session/Tool loop, no secrets, no forged install.
4. Prefer `plugin-creator` mechanics: `create_package` → validate returned
   `sourcePath` → `propose_install` → **stop**. Proposal is not installation.
5. Tell the user the frontend will show an install prompt (App Center → 建议).
   After they confirm apply, the Package appears as a Launchpad icon and new
   Sessions load its Skills/prompts/themes.
6. If they ask for scheduled reports later, record it as a follow-up Outcome;
   do not invent a second scheduler inside the Package.

## Truthful Result

Report exactly one of: `existing_package_found`, `draft_created`,
`validation_failed`, `proposal_pending_confirmation`, or receipt-backed
`installed` / `updated` / `rolled_back`. Never infer install from proposal.
