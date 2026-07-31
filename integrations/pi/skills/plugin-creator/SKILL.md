---
name: plugin-creator
description: Create the smallest managed Personal Agent Workbench plugin draft, validate it, and submit it to the product approval flow without inventing a second plugin path.
when:
  - 用户要求创建、更新、校验或申请安装受管插件
does: 设计最小 manifest 和文件，通过统一受管插件工具生成、校验并提交待审提议。
input: 插件目的、正面触发、Not for、输入输出、最小权限、文件、启用请求和验证方式。
output: 插件草案、manifest 摘要、校验回执、提议/批准状态和剩余风险。
notFor:
  - 绕过控制中心直接安装、启停、扩权或回滚
  - 写入密钥、复制任意代码插件，或创建与现有 Skill、Tool 重复的入口
---

# Plugin Creator

Create only the smallest plugin needed for the user's goal.

## Plugin Contract

The plugin is one managed package with one manifest, one entry point, declared
permissions, and a validation receipt. A Skill teaches a workflow; a Tool
performs one capability; a hook observes or gates a lifecycle. Do not create a
plugin when one of those existing owners already solves the need.

## Workflow

1. Confirm the plugin's single purpose, positive trigger, Not for cases, input,
   output, expected effect, and verification. First check whether an existing
   Skill, Tool, hook, or plugin already owns the need.
2. Choose a lowercase stable id and semantic version. Keep the entry point thin
   and declare only permissions the implementation actually uses.
3. Call `plugins` with `op=create_draft` and:
   - `draftId`: a unique lowercase identifier.
   - `manifest`: `schemaVersion`, `id`, `name`, `version`, `description`, `entry`, and `permissions`.
   - `files`: UTF-8 TypeScript, JavaScript, JSON, or Markdown source files. Do not include `rag-ime-plugin.json`; the runtime writes it from the manifest.
4. Call `plugins` with `op=validate` and the exact returned `sourcePath`.
   Validation failure ends this attempt; fix errors in a new draft and never
   mutate the managed inbox.
5. After validation succeeds, call `plugins` with `op=propose_install`, the
   exact `validationToken`, and the confirmed `enable` request. Default
   `enable` to false unless the request explicitly says otherwise.
6. Stop at the returned proposal or approval boundary. `propose_install`
   success is only a proposal; it is never proof that installation occurred.

## Manifest Review

Before proposal, verify:

- id and version are stable and lowercase where required;
- description states the user-visible capability;
- entry resolves inside the draft;
- every permission has a concrete implementation use;
- network, process, filesystem, and destructive access are absent by default;
- validation covers load, malformed input, denied permission, and expected
  output where applicable;
- no token, key, cookie, user path, or generated cache is included.

## Output Contract

Return exactly one truthful status:

- `draft_created`: a draft exists but no install proposal was accepted;
- `validation_failed`: validation returned errors and no proposal was made;
- `proposal_pending_approval`: the governed proposal exists but is unapplied;
- `installed`: only an authoritative install receipt proves this status.

Include the draft ID and source path, manifest digest, validation token or
receipt, requested permissions, requested enable state, proposal/approval
state, and residual risk when those fields exist. Never infer approval or
installation from draft creation, validation, or proposal success.

## Self-Check

- Did I search for an existing Skill, Tool, hook, or plugin first?
- Is there one canonical create/validate/propose path?
- Does the manifest request the minimum authority?
- Am I reporting proposal state rather than claiming installation?

## Boundaries

- Never request or expose secrets in source.
- Never use filesystem tools to write the managed plugin store.
- Keep network, process, filesystem, and destructive permissions absent unless
  the confirmed need requires them and the manifest declares them.
- The Agent may draft, validate, and propose. The native product flow owns the
  final state change.
