# Security Policy

## Supported State

Security fixes target the current `main` branch. The repository may publish
source before it publishes a signed and notarized macOS binary.

## Reporting A Vulnerability

Please use a private
[GitHub Security Advisory](https://github.com/7155/personal-agent-workbench/security/advisories/new).
Do not open a public issue for a vulnerability that could expose:

- API keys, Keychain entries, cookies, OAuth material, or Provider credentials;
- personal input history, selected text, memory, Room transcripts, or files;
- arbitrary local command, path traversal, native bridge, or browser control;
- Agent Tool approval, capability, Session, Room, or settlement bypasses;
- remote Agent Gateway authentication or route-exposure failures;
- dependency, build, signing, corresponding-source, or update-chain problems.

Include the affected commit, reproduction conditions, expected boundary, and a
minimal redacted proof. Never attach a real credential, private database, or
personal input trace.

This is a personal project without a response-time SLA. Reports will be
acknowledged and triaged as capacity permits.

## Security Model

- Local services bind to loopback by default.
- Passive input completion and retrieval are local by default.
- Explicit remote Provider actions require user configuration.
- Secure, denied, stale, or unknown foreground contexts fail closed.
- Provider secrets belong in macOS Keychain or ignored local configuration.
- Remote routes are a strict subset of local routes.
- Tool calls require schema validation, policy/approval evidence, and terminal
  execution receipts.
- Room capabilities bind to Session, Dispatch, capability epoch, and canonical
  arguments.
- Local databases, logs, model weights, build output, and personal input
  history are excluded from source control.

## Important Limitations

- An Agent with filesystem or Shell authority can modify user data within its
  approved scope. Review approvals and use an isolated workspace.
- macOS Accessibility, microphone, browser, and input-method permissions are
  powerful OS capabilities; grant only what you intend to test.
- A source checkout, test pass, or unsigned local build is not equivalent to a
  signed and notarized distribution.
- Backups contain local product data and are not password encrypted by this
  project. Store them accordingly.
