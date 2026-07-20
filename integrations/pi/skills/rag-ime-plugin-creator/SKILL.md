---
name: rag-ime-plugin-creator
description: Create a managed Wisdom Weasel Pi plugin when the user asks to make, scaffold, validate, or install a plugin. Use ime_plugins for the draft and proposal lifecycle; never bypass Control Center approval.
when:
  - 用户要求创建、校验或安装智鼬 managed plugin
  - 用户要把插件草案提交控制中心审批
does: 用 ime_plugins 创建、校验并提交安装申请。
input: 插件目的、触发条件、最小权限和所需文件。
output: 可校验插件草案、验证结果和待审安装提议。
notFor:
  - 绕过控制中心直接安装、启停或回滚
  - 写入密钥或未声明的高风险权限
---

# Managed Plugin Creator

Create only the smallest plugin needed for the user's goal.

## Workflow

1. Ask for the plugin's purpose, trigger, expected behavior, and required permissions when any are unclear.
2. Choose a lowercase stable plugin id and a semantic version. Declare only permissions the implementation actually needs.
3. Call `ime_plugins` with `operation=create_draft` and these arguments:
   - `draftId`: a unique lowercase identifier.
   - `manifest`: `schemaVersion`, `id`, `name`, `version`, `description`, `entry`, and `permissions`.
   - `files`: UTF-8 TypeScript, JavaScript, JSON, or Markdown source files. Do not include `rag-ime-plugin.json`; the runtime writes it from the manifest.
4. Call `ime_plugins` with `operation=validate` and the returned `sourcePath`.
5. Fix validation errors by creating a new draft id. Never modify the managed inbox directly.
6. After validation succeeds, call `ime_plugins` with `operation=propose_install`, the `validationToken`, and `enable=false` unless the user explicitly asked to enable it immediately.
7. Report the proposal and tell the user it is waiting in the Plugins workbench. Do not claim installation completed.

## Boundaries

- Never request or expose secrets in plugin source.
- Never use filesystem tools to write into the managed plugin store.
- Never install, enable, disable, or roll back a plugin without the Control Center approval flow.
- Keep network, process, filesystem, and destructive capabilities absent unless the user asked for them and the manifest declares them.
- The Agent can draft, validate, and propose. Only the user can approve the final write.
