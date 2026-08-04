# Contributing

Thanks for helping improve Personal Agent Workbench. The project combines a
local Python runtime, React Control Center, Agent/Room orchestration, optional
Provider integrations, and macOS input/voice/browser adapters. A small-looking
change can therefore cross privacy or lifecycle boundaries.

## Before You Start

- Use Python 3.12 or newer.
- Use Node.js 22 and the pinned `pnpm@11.9.0` for `control-center-web/`.
- Use Xcode 16 or newer for patched Squirrel and native release work.
- Read [ARCHITECTURE.md](ARCHITECTURE.md).
- Open an issue before changing persisted schemas, Provider context ordering,
  Tool approval, Room settlement/cancellation, or cross-language route
  contracts.

## Local Setup

```bash
uv sync --locked --python 3.12
corepack enable
corepack prepare pnpm@11.9.0 --activate
scripts/run_control_center_pnpm.sh install --frozen-lockfile
```

Do not add local API keys, model weights, personal input history, databases,
build products, or macOS permission state to fixtures.

## Change Discipline

- Trace one real entry point through its downstream consumer before editing.
- Keep one authoritative owner for each stateful concern.
- Migrate complete capabilities and delete the replaced path in the same change.
- Prefer typed request/result/receipt boundaries over undocumented dictionaries.
- Keep transport, application, lifecycle, persistence, Provider, and UI
  responsibilities separate.
- Do not split a file only because it is large.
- Do not introduce forwarding-only facades, service locators, universal base
  classes, or a second event/message protocol.

## Verification

Run focused tests while working. Before a substantial pull request, run:

```bash
uv run --locked python -m compileall -q rag_ime scripts tests
uv run --locked python scripts/check_import_boundaries.py
uv run --locked python scripts/check_route_ownership.py
uvx --from ruff==0.14.2 ruff check rag_ime scripts tests
uvx --from mypy==2.3.0 mypy
uv run --locked python scripts/check_product_status.py --json
uv run --locked python scripts/check_public_release.py --repository-only
uv run --locked python -m unittest discover -s tests
scripts/run_control_center_pnpm.sh typecheck
scripts/run_control_center_pnpm.sh test
scripts/run_control_center_pnpm.sh build
```

Native or input-method changes also require the relevant build and an attended
foreground test. A backend JSON response is not proof that a candidate was
visible and selectable in Squirrel.

## Pull Requests

Describe:

- the user-visible entry and complete call chain affected;
- the old owner and new owner;
- compatibility and rollback behavior;
- focused and broad commands with real exit codes;
- privacy, security, Provider, Session, Room, and persistence impact;
- screenshots only when UI behavior changes.

Keep commits focused. Do not mix generated output or unrelated formatting with
the behavioral change.

## Third-Party Source

Do not copy third-party source without confirming its license and recording the
provenance in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Distribution of
patched Squirrel must include its exact corresponding source and notices.
