# PAWOS Extension App Source Contract

Use one business owner tree. Core PAWOS may expose reusable host seams, but it
must not contain the vertical App's modes, prompts, styling, domain fields, or
result rules.

```text
control-center-web/extension-apps/<app-id>/
├── pawos-app.json
├── App.tsx
├── app.css
├── App.test.tsx
└── pi-package/
    ├── package.json
    ├── index.ts
    └── skills/<skill-name>/SKILL.md
```

## Manifest And Co-versioned Package

`pawos-app.json` is the build-time registry authority. It declares a unique
`extension:<slug>` id and `/extensions/<slug>` route, SemVer App version,
visible identity/icon, presentation, `skillRef`, `packageId`, exact vertical
suite id/revision, `skillSha256`, `bindingSha256`, and an optional sandbox
contract.

When `sandbox` is present it has exactly:

```json
{
  "default": "optional",
  "connectorPackageId": "vertical-agent-sandbox",
  "policyId": "vertical-readonly-v1"
}
```

`default` is `required`, `optional`, or `disabled`. Connector and policy ids are
fixed Runtime authorities, not App-authored commands or filesystem grants.

- The Pi Package name equals `packageId`; its version equals the App version;
  its `pi.skills` entry resolves `skillRef` under `pi-package/skills/`.
- `skillSha256` hashes the exact packaged `SKILL.md`. `bindingSha256` hashes the
  canonical App manifest with only `bindingSha256` removed, the exact Skill
  digest, and Package version.
- The Package's `paw.extensionApp` repeats the App identity, versions, Skill,
  suite, digests, and canonical manifest. `paw.capabilities` includes the
  bounded `pawos.extension.binding.<first-40-hex>` token.
- `verticalSuiteId` and `verticalSuiteRevision` resolve through
  `rag_ime.vertical_agent_harness.resolve_builtin_vertical_suite`. An App
  references a registered suite; it does not copy fixtures or Truth into its
  source tree and never treats test data as production data.
- The packaged Skill is the single App Skill copy and is not symlinked. Package
  resources use Pi's ordinary `extensions`, `skills`, `prompts`, and `themes`
  kinds with relative paths only.
- Except for the required `SKILL.md` spelling, Package path segments use
  lowercase ASCII letters, digits, dots, and hyphens. Reject symlinks,
  case-fold collisions, traversal, commands, external URLs, secrets, private
  machine paths, and cross-App business imports. Native limits are 1024 files
  and 20 MiB total.

## Generic Core Change Rule

Add a core change only when the owner App cannot express a required behavior
through the existing manifest, host, shared primitives, or typed transport.
Name the missing generic capability, keep the App-specific policy in the owner
tree, and protect the core seam with either two manifest identities or a
generic contract fixture. Removal of an older seam requires proving it has no
current consumer.

The frontend, lifecycle, and verification details are intentionally separate:
read `frontend-contract.md` for UI/Session behavior and
`lifecycle-and-verification.md` for sandbox and product mutations.
