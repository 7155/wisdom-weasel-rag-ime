# Changelog

Personal Agent Workbench follows a source-first development model. A public
source checkpoint is not a signed and notarized macOS binary release.

## Unreleased

### Added

- Structured Agent Sessions and durable multi-Agent Rooms with Root, Task,
  Dispatch, quality-gate, continuation, and settlement evidence.
- Capability-bound Tool disclosure, authorization, approval, execution, and
  terminal receipts.
- Protocol-owned Pi v1/v2 selection and an enforced public runtime contract.
- Paper-workspace Control Center UI with responsive Session and Room views.
- Local browser, voice, foreground-context, knowledge, planning, governed
  memory, backup, and restore boundaries.
- Separate public-source and distributable-binary readiness decisions.
- Governed coordinator background jobs include approval-bound launch, durable
  redacted cursor logs, lifecycle events, management APIs, cancellation, and
  Control Center controls. Focused validation and connected current-source
  browser acceptance pass; formal same-snapshot installed acceptance remains open.
- Plan and Goal lifecycles, per-capability Tool/Skill disclosure, Session
  overrides, governed workspace operations, explicit LSP degradation, and active/
  archived Work Document flows share backend-owned contracts with Control Center
  projections. `agent_goal` is discoverable through the managed Pi Tool catalog.
- Source support lets Room messages carry bounded, Room-owned clipboard or file
  images through authorized participant dispatch without exposing Session-private
  media; focused image-flow validation and same-snapshot installed acceptance
  remain open.

### Changed

- The public project identity is now Personal Agent Workbench; the default
  on-device companion is “澄.”
- Python 3.12 is the declared and tested minimum.
- Model selection is feature-owned: Agent/Room roles, Active RAG, and voice
  refinement use real runtime model catalogs instead of dead settings.
- HTTP route ownership is consolidated for ordinary families, with a
  fail-closed ratchet for deliberately special routes.
- Room-turn bookkeeping has one mutation owner.
- Pi v1 and v2 share explicit public projection/value contracts.
- Managed Rooms now execute peer-owned slices in parallel, gate final delivery on
  shared review and evidence, and recover bounded participant Sessions without
  requiring manual control-plane repair.
- The Control Center Room timeline now separates live reasoning, Tool activity,
  public participant reports, shared review, and the final reply in equal,
  responsive participant lanes with user-facing status language.

### Fixed

- Exact failed Room Tool commands cannot loop under a new call ID without new
  successful Tool evidence.
- A terminal Tool invocation receipt cannot execute twice.
- Worktree-based audit paths resolve through Git's common directory.
- IME display feedback is deduplicated and stale fuzzy holdover is removed.
- Duplicate definitions, unreachable route branches, a live IME `NameError`,
  and response-contract enforcement gaps were repaired.
- Native Control Center Room creation and policy updates now forward governed
  execution fields instead of rejecting the Web contract at the bridge.
- Sealed Room maintenance now uses lightweight control-state fencing, preserves
  transcripts when reopening revoked nonresident Sessions, and treats repeated
  Tool-disclosure receipt timestamps as idempotent instead of blocking compaction.
- Room WorkItems now mirror canonical Kernel lifecycle changes and startup
  reconciliation; blocked work is no longer presented as actively executing.
- Room settlement now deduplicates review invitations, retries recoverable
  commits without losing accepted work, and reconciles transient resume lanes
  against the authoritative terminal Root.
- Final integration repair restored the Tool-matrix write receipt, current Room
  migration fixtures, DeepSeek memory-organizer transport, bounded runtime Tool
  manifests, and clarification routing through the dedicated Room Tool.
- Foreground verification now recognizes the AppKit assistant overlay as the
  authoritative post-commit surface, accepts current action-button badges,
  commits native Rime composition before assistant selection, and fails before
  clearing evidence when frontend tracing is disabled.

### Validation

- `python3 -m unittest discover -s tests` passed 3,289 tests with three
  explicitly skipped cases in 1,429.139 seconds. The preceding audit's sole
  stale execution-policy wording assertion was repaired and the entire suite
  rerun. Existing unclosed-SQLite `ResourceWarning` output remains visible.
- Control Center passed 96 files / 801 tests and its production build. Full
  Playwright passed 160 cases with 35 intentional skips.
- Import boundaries passed. Route ownership passed with 91 dispatched routes,
  204 declared routes, and 40/40 undeclared-route checks.
- The current managed Pi payload passed protocol-v2, OAuth, and Runtime hello
  smoke checks. It was not installed.
- A real TextEdit/Squirrel run produced 84 privacy-safe AppKit events and passed
  native Rime composition, post-commit overlay visibility, source badges,
  Option+number assistant selection, commit, and follow-up checks. The focused
  foreground analyzer suite passes 79 tests.
- The repository-only release audit finds no forbidden, secret-shaped, or
  machine-path candidates, but correctly fails while the worktree is dirty.
  Distribution also remains blocked by foreground acceptance, the declared
  blocked status, and the missing release manifest.

### Known Distribution Gates

- Fresh installed foreground acceptance for Squirrel, Accessibility, and voice.
- Candidate-quality sign-off for the configured local model.
- Developer ID signing, notarization, stapling, clean-machine installation, and
  a hash-verified `rag-ime.release-manifest.v2`.
