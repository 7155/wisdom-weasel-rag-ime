---
name: bootstrap-project-context
description: "Create or minimally repair a project's root AGENTS.md when a project-bound Session has no reliable context entrypoint. Use when Runtime reports a missing root guide or the user explicitly invokes project initialization. Do not use for ordinary chat, transient task status, or replacing an existing guide; e.g., do not write live Session IDs into Markdown."
metadata:
  routing:
    when:
      - 项目根缺少 AGENTS.md 或用户要求初始化上下文
    notFor:
      - 普通任务或覆盖已有规则
    does: 创建精简 AGENTS.md 并索引 docs 与 WorkDocument。
    input: 项目根与文档。
    output: 入口与索引。
---

# Bootstrap Project Context

Give future Agents one small, accurate project entrypoint. `AGENTS.md` routes
context; it is not a second task database, transcript, or Runtime projection.

## Workflow

1. Use only the task-bound workspace root. Check the exact root `AGENTS.md`
   path before searching elsewhere. Never treat `AGENT.md`, a parent guide, or
   a nested dependency guide as the root project guide.
2. If a regular root `AGENTS.md` already exists, preserve it. During an
   explicit `/init`, inspect it and add only missing stable facts supported by
   current source or scripts; automatic bootstrap must not rewrite it.
3. Before a new file, inspect the root listing, Git status when available,
   README, package/build manifests, primary source entrypoints, tests, and
   existing durable docs. Ignore dependencies, generated output, caches,
   archives, and unrelated worktrees.
4. Create `AGENTS.md` with `workspace_write` using
   `resourceRevision=missing`. Keep it short and project-specific:
   - project purpose, current deliverable, and explicit non-goals;
   - authoritative source areas and their unique owners;
   - verified development, test, build, and install commands;
   - data, permission, Runtime, Git, and release boundaries;
   - a context index linking only the smallest relevant existing docs;
   - the document rules below.
5. Record durable accepted requirements in the project's existing canonical
   requirements document. If none exists, name `docs/agent/requirements.md` as
   the default and create it only when there is an actual requirement to
   preserve. Do not create empty ceremony during bootstrap.
6. Keep active task documents anywhere below the project's existing `docs/`
   convention and register them to the real `session_goal` or `room_work_item`
   through the write's `workDocument` field, or `work_documents` when that Tool
   is in the current profile. Bound writes must copy the live
   `authorityRevision` from the current workboard or document projection. The
   guide should tell Agents to discover them with `work_documents list/get`,
   then read only referenced sections with `workspace_read`.
7. Never copy live owner, running, completion, approval, WorkItem, or Session
   state into `AGENTS.md`. Resolve current ownership through Runtime. Resolve a
   document's Session through `WorkDocument -> authorityKey -> WorkItem ->
   participant Session`, and contact another Room participant directly through
   peer intercom when context is missing.
8. Do not create a second docs registry, modify business code, commit, or push.
   Return the exact file change, inspected authorities, stable routes added,
   and facts that remain unverified.

## Required Document Rule

The generated guide must make these boundaries explicit in plain language:

```text
AGENTS.md = stable project entrypoint and routing rules
durable requirements doc = accepted requirement history
WorkDocument registry = active document/WorkItem/Session relationships
Runtime and Git = current execution and workspace facts
```
