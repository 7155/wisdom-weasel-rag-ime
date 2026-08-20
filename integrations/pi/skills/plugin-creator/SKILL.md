---
name: plugin-creator
description: Search for, inspect, acquire, update, roll back, or create a native Pi Package for Personal Agent Workbench. Use when a task needs a reusable extension, Skill, prompt, or theme that is not already available, or when the user asks to install a package from npm, Git, or a local directory. Do not use for ordinary task logic already covered by an existing Tool, Skill, hook, or package; for one-off file edits that do not justify a reusable capability; for secrets; or to bypass the product confirmation that applies a package change.
when:
  - 用户要求管理或创建可复用 Pi Package
  - 缺少可复用 Tool 或 Skill
does: 搜索、校验并生成安装预览；缺少时创建包。
input: 能力、来源和验收。
output: 包、校验与安装提议。
notFor:
  - 普通任务或一次性修改
  - 密钥、不明代码或绕过确认
---

# Pi Package Creator

Give a PAW Session the missing reusable capability through Pi's native Package
system. PAW owns discovery, receipts, enabled state, version history, rollback,
and the final product confirmation. Pi owns package resolution and loading.

## Workflow

1. State the missing capability, when it should trigger, when it should not,
   expected input/output, and how to verify it.
2. Call `plugins` with `op=catalog`, then `op=list`. Prefer an existing package
   when it materially fits. Do not create a duplicate Tool, Skill, hook, prompt,
   theme, or extension.
3. For an existing npm spec, Git URL, local directory, or catalog item, call
   `plugins` with `op=validate` and exactly one of `packageSource` or `catalogId`.
4. Create only when no suitable package exists and the capability is worth
   reusing. Build one minimal Pi Package with:
   - a stable npm package name and semantic version;
   - one `pi` manifest declaring only the needed `extensions`, `skills`,
     `prompts`, or `themes`;
   - UTF-8 source files with one clear owner and no credentials;
   - a Skill description that says when to use it and includes concrete Not for
     examples when the package contains a Skill.
5. Call `plugins` with `op=create_package`, a unique immutable `draftId`, the
   complete `packageJson`, and all package `files`. Never mutate a returned
   managed draft.
6. Validate the exact returned `sourcePath` as `packageSource`. If validation
   fails, explain the error and create a new draft version; do not patch the
   retained inbox in place.
7. Call `plugins` with `op=propose_install`, the exact `validationToken`, and
   the requested `enable` state. Then stop at the PAW confirmation card.
   Proposal success is not installation.
8. Update an installed capability under the same package identity with a higher
   semantic version. Keep the current version active if preparation or install
   fails. Use the product rollback action when the user requests recovery; do
   not silently create a replacement package.

## Creation Rules

- Keep one package purpose and the smallest resource set that proves it.
- Prefer a Skill for reusable workflow guidance, an extension for executable
  behavior, a prompt for an explicit reusable prompt, and a theme for display.
- Put model-specific behavior in a model-card prompt/package, not in a role or
  unrelated Skill.
- Do not add a second event bus, permission system, Session loop, Tool loop, or
  package loader.
- Package preparation and read-only inspection do not require Luna approval.
  The product's explicit confirmation owns the install or update state change.
- Newly enabled Skills, prompts, and themes are loaded by new Sessions. Existing
  Sessions keep their current context stable.

## Truthful Result

Report exactly one state:

- `existing_package_found`: a suitable package was found; no state changed.
- `draft_created`: an immutable package draft exists; it is not installed.
- `validation_failed`: the exact source failed preparation or validation.
- `proposal_pending_confirmation`: PAW has an unapplied preview.
- `installed`: only an authoritative apply receipt proves installation.
- `updated` or `rolled_back`: only the corresponding receipt proves it.

Include the package identity/version, source kind, declared resources, validation
or receipt reference, requested enabled state, and remaining limitation. Never
infer installation from search, creation, validation, or proposal success.
