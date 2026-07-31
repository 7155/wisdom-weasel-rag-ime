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
- Source support for governed coordinator background jobs includes approval-bound
  launch, durable redacted logs, lifecycle events, management APIs, and Control
  Center controls; focused background-job validation and same-snapshot installed
  acceptance remain open.
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

### Open Validation Gates

- **FAILED — full backend gate work receipt:** `python3 -m unittest discover -s
  tests` reported exactly: 3192 tests, 33 failures, 66 errors, 3 skipped.
  This gate remains open and must not be reported as passed.

### Known Distribution Gates

- Fresh installed foreground acceptance for Squirrel, Accessibility, and voice.
- Candidate-quality sign-off for the configured local model.
- Developer ID signing, notarization, stapling, clean-machine installation, and
  a hash-verified `rag-ime.release-manifest.v2`.
