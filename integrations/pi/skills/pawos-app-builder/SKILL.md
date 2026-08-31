---
name: pawos-app-builder
description: Create or evolve a source-isolated PAWOS Extension App, its vertical Skill, and its Trace/Eval suite. Use when the user asks an Agent inside PAWOS to design, build, test, install, or self-improve a vertical App. Do not use for ordinary edits to a built-in App, a generic Pi Package with no App surface, or bypassing install confirmation and foreground acceptance.
metadata:
  routing:
    when:
      - 制作或安装 PAWOS 垂直 App
      - 为垂直 App 创建专属 Skill
    does: 生成隔离 App、Skill 与 Trace/Eval。
    input: 场景、模式、验收。
    output: 候选、证据、安装回执。
    notFor:
      - 内建 App 小改
      - 绕过安装确认
---

# Build A PAWOS Extension App

Turn one vertical workflow into an independently owned PAWOS App without
embedding its business rules in the core shell. The Agent may modify the bound
source workspace, but PAWOS, Pi, Trace, App Center, and the product installer
retain their existing authority.

## Product Boundary

- Put the vertical product under `control-center-web/extension-apps/<app-id>/`.
  Its frontend, manifest, Skill, fixtures, and App-specific tests stay there.
- Core PAWOS code may provide only a generic Extension App registry, host,
  lifecycle, permission, and rollback seam. Never add an `if` branch for one
  business App to the desktop, Session loop, Tool loop, or transport.
- Reuse the ordinary Agent Session and typed control transport. A vertical App
  may change conversation presentation and default instructions; it must not
  fork Pi's Agent loop or invent a second event bus.
- A checked-in folder is a source candidate, not an installed App. App Center
  or the product installer owns apply/rollback, and foreground behavior owns
  final acceptance.

Read [references/extension-app-contract.md](references/extension-app-contract.md)
before creating a new App or changing its manifest.

## Self-Bootstrap Workflow

1. Bind the exact PAW checkout and one Extension App owner directory. Inspect
   the generic registry/host, nearest existing Extension App, current App
   manifest, installed receipt, and vertical suite before editing.
2. Convert the user's conversation into an observable App contract: user,
   supported conversation modes, views, state, authoritative data sources,
   Agent actions, error/recovery behavior, and foreground acceptance. Keep the
   user's original requirement separate from implementation notes.
3. Create or update four versioned products together:
   - the Extension App manifest and frontend;
   - one App-specific Pi Skill with a discriminating trigger;
   - one deterministic vertical manifest/fixture set;
   - focused UI, contract, Trace, and Eval tests.
4. Keep all business-specific code inside the owner directory. When a missing
   generic host capability is proven, add the smallest reusable core seam and
   test it with at least two manifest identities or one generic contract test;
   do not hard-code the current App.
5. Bind the manifest's sandbox contract before an experiment. `required` runs
   through the declared Connector and cannot be skipped; `optional` requires a
   visible `run` or `skip` decision; `disabled` permits static manifest/Skill/
   build validation only and never a direct Host run. This decision belongs to
   the candidate binding, not to an unrecorded Agent preference.
6. Build and test the candidate without touching the installed App. Every
   installed-App experiment calls `extension.sandbox.experiment.run` with only
   `sessionId`, `ownerAppId`, `experimentId`, `candidateBindingSha256`, and
   `requestedDecision`; Runtime derives the suite and policy from the installed
   binding. A `run` retains SandboxRun, Trace, EvalRun, exact source revision,
   and network/write boundary receipts. A `skip` retains its explicit receipt;
   it is never reported as sandbox success.
7. If the candidate fails, diagnose the frozen Trace in the read-only Trace
   Agent. After the user confirms the candidate repair once, use the separate
   full-automation repair Agent within the one owner workspace, then rerun the
   same sandbox fixture. Do not compare scores when the fixture, manifest
   revision, model/config, or input fingerprint changed.
8. When the candidate passes, produce one install proposal containing App and
   Skill versions, files, permissions, build/test evidence, rollback target,
   and expected desktop identity. Stop before apply unless the user has
   explicitly authorized installation.
9. After apply, open the installed App from PAWOS and run one real vertical
   conversation. Verify its mode-specific UI, Agent/Skill binding, Stop and
   recovery, Trace link, installed version, and rollback. A build, mock page,
   screenshot, or source folder is not this proof.

## Sandbox Selection And Experiment Receipt

- The manifest may declare `sandbox` as `{ default: required | optional |
  disabled, connectorPackageId: vertical-agent-sandbox,
  policyId: vertical-readonly-v1 }`. Do not substitute a local command, a
  guessed policy, or a different Connector ID.
- The App UI explains the declared default before an experiment. `required`
  submits `requestedDecision: run`; `optional` exposes both decisions; and
  `disabled` records only static validation. No branch may run the vertical
  suite directly on the Host.
- The client never sends suite IDs, policy IDs, workspace roots, command lines,
  or fixture paths to the experiment route. Those are Runtime-derived from the
  installed App binding so a stale or edited UI cannot widen the sandbox.
- A failed, cancelled, or skipped experiment is a first-class result. Keep its
  receipt and the candidate binding; do not silently fall through to Host
  execution or claim a missing SandboxRun/Trace/Eval as success.

## Conversation-Mode Apps

When the requested App changes Agent chat for modes such as question answering,
reconciliation, or explanation, project the same Session into mode-specific
controls and result views. Keep message order, Markdown, Tool status, Stop,
Steer, compaction, model/permission controls, and Runtime terminal state owned
by the shared Agent surface. The Extension App owns only mode selection,
domain prompts, domain inputs, domain result formatting, and App-specific
navigation.

## Result

Report one current state: `candidate_created`, `sandbox_failed`,
`sandbox_verified`, `install_pending_confirmation`, `installed`,
`foreground_accepted`, or `rolled_back`. Include exact App/Skill/suite versions,
changed owner paths, SandboxRun/Trace/Eval identities, install receipt when
present, and the remaining proof boundary.
