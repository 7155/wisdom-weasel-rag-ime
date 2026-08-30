# PAWOS Extension App Contract

Use one source-owned folder:

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

`pawos-app.json` is the build-time registry authority. Required fields:

```json
{
  "schemaVersion": "pawos.extension-app.v1",
  "id": "extension:<slug>",
  "version": "0.1.0",
  "bindingSha256": "<canonical co-version binding>",
  "skillSha256": "<exact packaged SKILL.md SHA-256>",
  "packageId": "@paw/<slug>",
  "label": "Visible App name",
  "shortLabel": "Short name",
  "tagline": "One observable purpose",
  "route": "/extensions/<slug>",
  "presentation": "workspace",
  "accent": "green",
  "icon": {
    "symbol": "analytics",
    "background": "#087F68"
  },
  "skillRef": "<skill-name>",
  "verticalSuiteId": "<suite-id>",
  "verticalSuiteRevision": "<exact revision>"
}
```

Rules:

- `id` and route are unique; the id starts with `extension:` and the folder is
  the suffix. Versions use SemVer.
- `packageId` is the name in `pi-package/package.json`; the package version
  matches the App version and its `pi.skills` entry resolves `skillRef` below
  `pi-package/skills/`.
- `skillSha256` is the SHA-256 of the exact packaged `SKILL.md`.
  `bindingSha256` is calculated from the canonical App manifest with only that
  field removed, the exact `SKILL.md` SHA-256, and the package version. The Pi
  Package's `paw.extensionApp` must repeat the App identity/version/skill/suite,
  both digests, and the complete canonical App manifest. Its `paw.capabilities`
  must include the bounded
  `pawos.extension.binding.<first-40-hex>` token (64 characters total).
- `skillRef` resolves inside the same App folder during source validation and
  in the managed Pi Runtime after installation. The package is the only copy
  of the App Skill; it must not be symlinked.
- `verticalSuiteId` and `verticalSuiteRevision` must resolve exactly through
  the existing registered vertical-suite authority
  (`rag_ime.vertical_agent_harness.resolve_builtin_vertical_suite`). An App
  binds an existing suite such as `sgg`/`fixture-v2`; it does not copy
  `vertical-agent.json`, fixture data, Truth, or `examples/vertical_agents`
  into the App folder.
- The resolved suite must retain its declared sandbox boundary: network
  blocked and production writes blocked. A suite binding is a test reference,
  not permission to use fixture data as production business truth.
- The frontend default export is a React component that uses shared PAW
  primitives and the ordinary control transport. It does not create a second
  Session or Tool runtime.
- Extension source must not import preview fixtures, private machine paths,
  credentials, generated output, or another Extension App's business code.
- `pi-package/package.json` must declare only the ordinary Pi resource kinds
  (`extensions`, `skills`, `prompts`, and/or `themes`) using relative paths;
  arbitrary commands, external URLs, and path traversal are invalid.
- To keep the Sidecar digest identical to Native Pi's recursive `localeCompare`
  walk, Package path segments use lowercase ASCII letters, digits, dots, and
  hyphens; the required `SKILL.md` filename is the sole uppercase exception.
  Case-fold collisions are invalid. The Native limits are 1024 files and
  20 MiB total.
- Installation copies only validated source/build assets and the Pi Package's
  Skill resources. At runtime PAW resolves the installed package source, rejects
  symlinks, recomputes the package-manager digest, hashes the installed Skill,
  recomputes the App binding, and only then publishes the full installation
  evidence to PAWOS. Partial or stale Runtime metadata is fail-closed.
  The installed receipt records the manifest digest, App/Skill/suite versions,
  source commit, previous version, and rollback location.

Validation levels remain separate: manifest/Skill, unit/type/build, Host
sandbox Trace/Eval, install receipt, then real foreground conversation.
