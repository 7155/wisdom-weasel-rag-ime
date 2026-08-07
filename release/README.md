# Build, Install, And Release

The tracked [Room product contract](room-product-contract.md) is the sole
authority for current Room behavior and native acceptance status. This build
guide explains how to produce evidence for that contract; it does not override
it.

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
git checkout 3e2bac77319571ac0047a83529aae241db4b88a3
npm ci

cd ../personal-agent-workbench
uv sync --frozen
scripts/run_control_center_pnpm.sh install --frozen-lockfile
```

The product contract rejects a Pi source tree that does not contain the pinned
runtime-host implementation. This checkpoint includes the deterministic
Goal/Room lifecycle, native coding-tool evidence, long-result handles, and the
pre-dispatch model-context fence. Do not substitute an arbitrary Pi release
just because its CLI starts.

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
uvx --from "mypy==2.3.0" mypy
uvx --from "ruff==0.14.2" ruff check rag_ime scripts tests
python3 scripts/check_public_release.py --repository-only
```

Frontend verification:

```bash
scripts/run_control_center_pnpm.sh typecheck
scripts/run_control_center_pnpm.sh test
scripts/run_control_center_pnpm.sh build
scripts/run_control_center_pnpm.sh test:e2e
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

If this deliberately transfers the installed Squirrel marker from another
checkout to the current clean checkout, make that one owner handoff explicit:

```bash
RAG_IME_SQUIRREL_ALLOW_SOURCE_ROOT_CHANGE=1 \
  scripts/install_product_stack.sh \
  --include-squirrel \
  --include-pi \
  --pi-worktree ../pi
```

Do not set the handoff flag for routine reinstalls from the same checkout.

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

### Clean Reinstall Without Deleting User Data

Use this sequence when an older local build must be replaced but databases,
governed memory, Sessions, Provider authentication, credentials, logs, and
Rime user configuration must survive.

First verify that the user-installed Squirrel is the single canonical input
method. The second command is read-only and reports whether a duplicate
system-wide bundle would be quarantined:

```bash
python3 scripts/audit_canonical_squirrel_bundles.py
scripts/quarantine_duplicate_squirrel_app.sh --preflight
```

If the preflight reports a same-bundle-id duplicate under
`/Library/Input Methods`, run the quarantine command without `--preflight`.
It moves that duplicate aside and re-registers the canonical user bundle; it
does not delete the canonical Squirrel.

Review and then apply the same narrowly scoped uninstall options:

```bash
python3 scripts/uninstall_rag_ime.py \
  --purge-runtime-cache \
  --report /tmp/personal-agent-workbench-uninstall-plan.json

python3 scripts/uninstall_rag_ime.py \
  --apply \
  --purge-runtime-cache \
  --report /tmp/personal-agent-workbench-uninstall-result.json
```

Do not add `--purge-local-data`, `--purge-credentials`,
`--remove-rime-managed-config`, or `--remove-patched-squirrel` to a clean
reinstall. Those flags intentionally cross the preservation boundary.

Reinstall from the clean source checkout, verify that every installed
component resolves to the new source generation, and only then prune retired
managed Pi generations:

```bash
scripts/install_product_stack.sh \
  --include-pi \
  --pi-worktree ../pi \
  --skip-mlx

python3 scripts/check_installed_product_components.py --require-current

python3 scripts/prune_managed_pi_runtime.py \
  --report /tmp/personal-agent-workbench-pi-retention-plan.json

python3 scripts/prune_managed_pi_runtime.py \
  --apply \
  --plan /tmp/personal-agent-workbench-pi-retention-plan.json \
  --report /tmp/personal-agent-workbench-pi-retention-result.json
```

Runtime retention keeps the accepted active and immediate previous
generations for rollback. It removes only digest-bound generations in the
accepted retired lineage and refuses a changed dry-run plan.

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
