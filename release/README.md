# Build, Install, And Release

This directory separates three different claims that must not be confused:

| Scope | What it proves | Current gate |
| --- | --- | --- |
| Public source | The tracked repository is clean, licensed, and free of known private artifacts or secret-shaped content. | `python3 scripts/check_public_release.py --repository-only` |
| Local source build | The Web Control Center, native helpers, and pinned managed Pi Runtime can be built from source on the current Mac. | The non-destructive walkthrough below |
| Public macOS distribution | A package is Developer ID signed, notarized, stapled, foreground-accepted, and hash-bound to its corresponding source. | `python3 scripts/check_public_release.py` |

The first two scopes can pass while the public macOS distribution remains
blocked. An ad-hoc signed `.app` produced by the local build is not a public
release artifact.

The `RAG_IME_*` environment variables, `RagIme` Application Support directory,
and existing bundle identifiers are compatibility identifiers. The user-facing
product and Python package are named Personal Agent Workbench; changing the
stored paths or bundle identities requires a separate migration and is not part
of a source-repository rename.

## Requirements

- macOS 14 or newer on Apple Silicon;
- Python 3.12 or newer;
- Git and Xcode command-line tools;
- full Xcode only when building the patched Squirrel input method;
- Node.js 22.19 or newer;
- pnpm 11 for `control-center-web`;
- npm for the pinned Pi source checkout;
- `uv` for the locked Python environment.

Model weights, API credentials, OAuth credentials, databases, and personal
context archives are intentionally not included.

## Checkout And Dependencies

The managed runtime is built from a separate, source-pinned Pi checkout. Keep
the two repositories next to each other:

```bash
git clone https://github.com/7155/personal-agent-workbench.git
git clone https://github.com/7155/pi.git

cd pi
git checkout 0cb10fa18118632b6e3d3233cbc18d7ea6486114
npm ci

cd ../personal-agent-workbench
uv sync --frozen
pnpm --dir control-center-web install --frozen-lockfile
```

The product contract rejects a Pi source tree that does not contain the pinned
runtime-host implementation. Do not substitute an arbitrary Pi release just
because its CLI starts.

## Non-Destructive Build Walkthrough

These commands build into `build/` and do not install, load LaunchAgents,
replace an input method, or restart an application:

```bash
scripts/build_control_center.sh build-release
scripts/build_voice_input.sh build
scripts/build_desktop_bridge.sh build

python3 scripts/build_managed_pi_runtime_v2.py \
  --pi-worktree ../pi \
  --output build/managed-pi-runtime/release-check \
  --force

codesign --verify --deep --strict build/RagImeControl.app
codesign --verify --deep --strict build/RagImeVoice.app
codesign --verify --deep --strict build/RagImeDesktopBridge.app
```

The local native apps are ad-hoc signed so macOS can execute and inspect them.
That signature is suitable for development only.

Run the source and architecture gates from a clean checkout:

```bash
python3 -m compileall -q rag_ime scripts tests
python3 scripts/check_import_boundaries.py
python3 scripts/check_route_ownership.py
python3 scripts/check_product_status.py --json
uvx --offline mypy
uvx --offline ruff@0.14.2 check rag_ime scripts tests
python3 scripts/check_public_release.py --repository-only
```

Frontend verification:

```bash
pnpm --dir control-center-web typecheck
pnpm --dir control-center-web test
pnpm --dir control-center-web build
pnpm --dir control-center-web test:e2e
```

## Local Installation

Installation changes `~/Library/Application Support/RagIme`,
`~/Library/LaunchAgents`, and `~/Applications`; `--include-squirrel` also
replaces the user-installed Squirrel bundle. Review the command before running
it.

For a first complete local installation:

```bash
scripts/prepare_squirrel_workspace.sh
scripts/build_patched_squirrel.sh build

scripts/install_product_stack.sh \
  --include-squirrel \
  --include-pi \
  --pi-worktree ../pi
```

For an existing installation that should keep its current Squirrel and skip an
optional local MLX predictor:

```bash
scripts/install_product_stack.sh \
  --include-pi \
  --pi-worktree ../pi \
  --skip-mlx
```

The installer refuses dirty tracked source, writes source-generation markers,
installs the visible Control Center last, and checks that the installed
components agree on the expected commit before returning success.

Inspect the removal plan without changing the machine:

```bash
python3 scripts/uninstall_rag_ime.py
```

Apply that plan only when removal is intended:

```bash
python3 scripts/uninstall_rag_ime.py --apply
```

## Source Publication And Binary Release

Before changing repository visibility, commit all intended source changes and
run:

```bash
python3 scripts/check_public_release.py --repository-only
```

Do not treat `--allow-blocked` as a release pass. It exists only to print the
remaining blockers with exit code zero.

An unsigned engineering staging archive can be assembled with
`scripts/prepare_release_candidate.py` after the patched Squirrel source and
all four app bundles exist. The staging manifest deliberately contains
`releaseEligible: false`.

A distributable macOS release additionally requires:

1. one clean source commit and the exact patched Squirrel corresponding source;
2. completed foreground acceptance for input, voice, Accessibility, and Room;
3. Developer ID signing for every shipped executable and bundle;
4. Apple notarization and stapling;
5. clean-machine Gatekeeper, installation, upgrade, and rollback checks;
6. a generated `output/release/release-manifest.json` matching
   `release/release-manifest.example.json`;
7. a final successful `python3 scripts/check_public_release.py`.

The release metadata files are:

- `feature-registry.json`: feature-level source and foreground status;
- `product-status.json`: verified scope and unresolved release gates;
- `release-manifest.example.json`: the required signed-distribution evidence
  shape.

Never edit a blocker away merely to make the distribution audit green.
