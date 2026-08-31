---
name: pawos-app-builder
description: Create or evolve a source-isolated PAWOS Extension App, its App-owned frontend, vertical Skill, managed lifecycle, and Trace/Eval evidence. Use when PAWOS should self-build, sandbox-test, install, update, uninstall, or roll back a vertical App. Do not use for ordinary built-in App edits, a surface-less Pi Package, or bypassing product confirmation and installed foreground acceptance.
metadata:
  routing:
    when:
      - 自举、安装或升级 PAWOS 垂直 App
      - 创建 App 专属前端与 Skill
    does: 生成隔离 App、前端、Skill 与测试。
    input: 场景、模式、数据、验收。
    output: 候选、沙箱与安装回执。
    notFor:
      - 内建 App 小改
      - 绕过安装确认
---

# Build A PAWOS Extension App

Build one vertical product inside its own owner directory. The App owns its
information architecture, modes, domain inputs, result presentation, frontend,
and packaged Skill. PAWOS owns only generic discovery, hosting, lifecycle, and
window projection; Pi remains the sole Session, Tool-loop, transcript, Steer,
Stop, compaction, and recovery Runtime.

## Read The Relevant Contract

- For the owner tree, manifest, App/Skill binding, and Package invariants, read
  [references/extension-app-contract.md](references/extension-app-contract.md).
- For any App screen or conversation change, read
  [references/frontend-contract.md](references/frontend-contract.md). For a new
  App, copy and adapt [assets/frontend-template/](assets/frontend-template/);
  never overwrite an existing App with the starter.
- For sandbox experiments, install/update/uninstall/rollback, or acceptance,
  read [references/lifecycle-and-verification.md](references/lifecycle-and-verification.md).

## Work From One Owner Boundary

1. Bind the exact PAW checkout and `control-center-web/extension-apps/<app-id>/`.
   Inspect the generic host, nearest App only as a structural reference, current
   manifest/Package, installed receipt, and related tests before editing.
2. Write an observable App contract: people and jobs, modes, authoritative data,
   domain inputs/actions/results, failure/recovery, permissions, and foreground
   acceptance. Keep user wording separate from Agent interpretation.
3. Co-version the App manifest and frontend, one App-specific Pi Skill, and the
   deterministic vertical suite binding. Keep business code in the owner tree.
4. Add the focused tests required by the verification matrix. If a missing core
   seam is proven, add only a generic host contract and prove it against multiple
   App identities; never branch on this App id.
5. Validate and sandbox-test the source candidate without changing the installed
   App. Failed, cancelled, skipped, and incomparable results remain explicit.
6. Produce one lifecycle proposal with exact versions, permissions, evidence,
   previous active version, and rollback target. Stop before apply unless the
   user explicitly authorized that state change.
7. After an authorized apply, verify the installed inventory and one real
   App-owned foreground conversation. Source, tests, builds, previews, fixtures,
   and screenshots do not prove installed acceptance.

## Result

Report exactly one current state: `candidate_created`, `sandbox_failed`,
`sandbox_verified`, `install_pending_confirmation`, `installed`,
`foreground_accepted`, `update_failed`, `uninstalled`, or `rolled_back`.
Include changed owner paths, App/Skill/suite versions, focused checks,
SandboxRun/Trace/Eval ids when present, lifecycle receipt when present, and the
remaining proof boundary. Do not describe a candidate as installed or a
fixture run as production truth.
