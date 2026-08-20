---
name: project-maintainer
description: Maintain the Personal Agent Workbench product installation and its self-hosted runtime. Use when designing or implementing PAW build, install, uninstall, update, rollback, repair, or recovery behavior, including LaunchAgents and the managed Pi Runtime. Do not use for ordinary feature development, one-off code edits, unrelated software installation, or as a substitute for runtime permissions, approvals, receipts, and version snapshots.
when:
  - 维护 PAW 安装、升级或回滚
  - 修改 LaunchAgent 或 Pi Runtime
does: 按可恢复顺序实施并验证安装。
input: 维护目标、授权和验收。
output: 变更、回执、验证与风险。
notFor:
  - 普通功能或一次性修改
  - 绕过权限、审批或版本快照
---

# Maintain Personal Agent Workbench

Keep PAW's source checkout, installed application, Sidecar, Agent Gateway, and
managed Pi Runtime aligned without inventing a second installer or lifecycle
owner. This Skill guides the workflow; product scripts, Runtime policy, native
permissions, approvals, receipts, and snapshots remain authoritative.

## Trigger Boundary

Use this Skill when the requested product work changes how PAW is built,
installed, upgraded, uninstalled, repaired, rolled back, restored, or kept
running on its host. This includes designing those flows before implementation.

Do not activate it merely because ordinary feature code will eventually ship in
an app build. If the task discovers a missing reusable Pi capability, hand only
that capability branch to `plugin-creator`; do not turn routine maintenance into
a Package.

## Workflow

1. Resolve the canonical PAW checkout and read its nearest project guide. Verify
   the origin, branch, dirty state, and exact requested target before changing
   source or installed state. Preserve unrelated work.
2. Classify the operation as `design`, `build`, `install`, `update`, `uninstall`,
   `rollback`, `repair`, or `restore`. State whether the user authorized source
   edits, installed-state changes, or both.
3. Inventory only the affected layers: source revision, web bundle, native app,
   Sidecar code, Agent Gateway, managed Pi generation, LaunchAgents, App Support
   data, configuration, and databases. Never infer readiness from a single
   process or health badge.
4. Establish a recoverable order before mutation. Keep user data and previous
   managed generations intact, use the product's existing scripts, and identify
   the receipt or snapshot that proves each state transition. An uninstall must
   name what is retained and what is removed before it runs.
5. Make the smallest coherent source change. Do not add a second installer,
   package loader, process supervisor, permission system, Session loop, Room
   runtime, or ad-hoc state database.
6. Run focused repository checks first. Treat source tests, a successful build,
   installation, process readiness, API health, Pi Session readiness, and real
   foreground acceptance as distinct evidence levels.
7. Apply an install, update, uninstall, rollback, or restore only when that state
   change is within the user's request. Verify the installed marker, relevant
   process/listener, and one real downstream route after the operation.
8. Report exact changed layers, authoritative receipts, focused checks, retained
   data, rollback path, and anything not verified. A preview or build is not an
   installation; a healthy Sidecar is not proof that Pi is ready.

## Failure And Recovery Rules

- Retry a startup, network, or process-race failure at most once when the action
  is read-only or idempotent and the bound is explicit.
- Do not automatically retry logic errors, schema errors, failed acceptance, or
  writes whose Tool receipt is unknown. Repair, reconcile the receipt, or ask for
  an explicit decision.
- Never delete broad directories, overwrite user databases, reset a dirty
  checkout, or replace an active version without a recoverable prior state.
- Newly installed Pi resources apply to new Sessions. Existing Sessions retain
  their captured resource snapshot unless the product contract says otherwise.

## Result Contract

Return:

```text
operation and authorization boundary
affected source and installed layers
preflight and recovery point
source/build/install/runtime/acceptance evidence by level
receipts and retained data
rollback path and residual risk
```
