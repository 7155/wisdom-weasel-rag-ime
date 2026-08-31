# Extension App Lifecycle And Verification

Read this for sandbox experiments, installation changes, or acceptance claims.
Source work and installed product state are separate authorities.

## Self-bootstrap Sandbox Loop

1. Freeze the App/Skill/Package binding, source revision, registered suite
   revision, model/config, input fingerprint, sandbox decision, network/write
   boundary, and budgets before running.
2. For an installed-App experiment call only
   `extension.sandbox.experiment.run` with `sessionId`, `ownerAppId`,
   `experimentId`, `candidateBindingSha256`, and `requestedDecision`. Runtime
   derives suite, policy, workspace, and commands from the installed binding.
3. `required` always requests `run`; `optional` exposes a visible `run` or
   `skip`; `disabled` permits static validation only. No branch runs the suite
   directly on the Host or silently falls back when the Connector is missing.
4. A run retains linked SandboxRun, Trace, frozen Eval, source revision, and
   boundary receipts. A failure, cancellation, or skip retains its own receipt.
   Compare scores only when all frozen comparison fields match.
5. Diagnose the frozen Trace read-only. Repair only the bound owner workspace
   within granted authority, create a new candidate binding, and rerun. Never
   mutate a completed experiment or promote fixture output as production truth.

## Install, Update, Disable, Uninstall, And Rollback

- Prepare and validate through the managed Pi Package path. Product
  confirmation is required immediately before install, update, disable,
  uninstall, or rollback unless that exact mutation is already authorized.
- The proposal identifies App, Skill, Package, and suite versions; permission
  and sandbox changes; checks and receipts; current installed version; candidate
  binding; expected windows/icons; and exact rollback target.
- Install activates only a fully verified co-versioned App/Package/Skill
  binding. Runtime rejects symlinks, recomputes Package/Skill/binding digests,
  and fails closed on partial or stale metadata.
- Update stages the candidate without overwriting the active version, preserves
  current Sessions' resource snapshot, atomically moves the active pointer only
  after confirmation, and retains the previous version for rollback.
- Disable/uninstall removes the App identity from launch surfaces and closes its
  windows without deleting App-owned Session audit records or user data. State
  whether App data is retained and never infer deletion permission.
- Rollback restores the recorded frontend and Package/Skill generation together.
  A failed update leaves the prior active generation usable and emits a visible
  failure receipt; it is not a partial success.

## Required Verification Matrix

| Level | Required evidence |
| --- | --- |
| Source contract | manifest schema/identity/route; App-Package-Skill digests and versions; suite resolution; owner-only imports; no App-id branch in core |
| Frontend unit | mode isolation and switching; owner-filtered restore; exact first-turn contract; unknown admission replays the same id/payload; durably failed receipt uses a new id plus `retryOfClientMessageId`; accepted-turn failure uses a new id without lineage; no duplicate optimistic/restored message |
| Session behavior | ordinary Pi Session/Skill binding; follow-up; live Steer ordering; Stop from pre-admission and active Tool work; terminal failure/cancel; refresh/compaction recovery |
| Sandbox/Trace/Eval | required/optional/disabled decisions; missing/mismatched Connector; run/skip/fail/cancel receipts; frozen comparison rejection; Trace/Eval deep links |
| Responsive/a11y | keyboard mode navigation; focus and accessible names; live error/status semantics; reduced motion; narrow/short window; zoom and long localized content |
| Lifecycle | prepare/confirm/install; enable/disable; update success/failure; uninstall with retained audit/data boundary; rollback to exact prior co-versioned generation |
| Build | focused tests, typecheck, and production build on the candidate revision |
| Installed Runtime | installed+enabled inventory and digest readback; actual App/Skill versions; App-owned Session hidden from ordinary Agent list; restart/refresh restoration |
| Foreground | launch from real PAWOS identity; complete one real mode-specific conversation; retry or recovery; Steer/Stop; Trace link; resize and keyboard pass; uninstall/rollback result visible |

Tests should assert behavior and authoritative state, not headings or snapshots
alone. Use deterministic transport fixtures for unit/contract tests, then real
Runtime and foreground evidence for installed claims. Preview fixtures,
screenshots, builds, and source manifests never substitute for the last two
rows.

## Acceptance And Reporting

Keep four verdicts separate: candidate source/tests/build, sandbox experiment,
installed Runtime state, and foreground requirement satisfaction. Report exact
commands and ids, passed/failed/unverified rows, installed version when read
back, and the rollback target. If installation was not authorized or foreground
proof was not run, stop at that boundary and say so explicitly.
