## What changed

Describe the user-visible entry, current call chain, and ownership boundary.

## Why

Name the demonstrated defect or maintenance pressure. Avoid line-count-only
refactors.

## Verification

- [ ] Focused tests (command and real exit code)
- [ ] Import/route/lint/type gates where applicable
- [ ] Broad Python suite for substantial changes
- [ ] Web typecheck/tests/build for UI changes
- [ ] Native build and attended foreground evidence for Squirrel/macOS changes

## Safety and compatibility

- [ ] No credentials, personal input, databases, models, logs, or build output
- [ ] Provider payload, Session history, Room/Tool receipts, and persisted data
      remain compatible or migration/rollback is documented
- [ ] Third-party provenance and notices are updated when needed
