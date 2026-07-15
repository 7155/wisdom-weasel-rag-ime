#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rag_ime.agent_tool_ids import CONTROL_TOOL_IDS
from rag_ime.managed_pi_runtime import (
    MANIFEST_NAME,
    ManagedPiRuntimeError,
    build_managed_pi_runtime_manifest,
    write_managed_pi_runtime_manifest,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Create a signed-by-hash manifest for an already prepared offline Pi runtime tree"
    )
    parser.add_argument("--payload", required=True)
    parser.add_argument("--runtime-version", required=True)
    parser.add_argument("--pi-version", required=True)
    parser.add_argument("--launch-kind", choices=("node", "standalone"), required=True)
    parser.add_argument("--pi-entrypoint", required=True)
    parser.add_argument("--node-entrypoint", default="")
    parser.add_argument("--extension-entrypoint", required=True)
    parser.add_argument("--tool", action="append", default=[])
    parser.add_argument("--source-repository", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--source-package", required=True)
    args = parser.parse_args(argv)
    payload = Path(args.payload).expanduser()
    try:
        manifest = build_managed_pi_runtime_manifest(
            payload,
            runtime_version=args.runtime_version,
            pi_version=args.pi_version,
            launch_kind=args.launch_kind,
            pi_entrypoint=args.pi_entrypoint,
            node_entrypoint=args.node_entrypoint,
            extension_entrypoint=args.extension_entrypoint,
            tools=tuple(args.tool or CONTROL_TOOL_IDS),
            source_repository=args.source_repository,
            source_commit=args.source_commit,
            source_package=args.source_package,
        )
        write_managed_pi_runtime_manifest(payload / MANIFEST_NAME, manifest)
    except (OSError, ManagedPiRuntimeError) as exc:
        print(f"managed Pi runtime preparation failed: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "ok": True,
                "manifest": str((payload / MANIFEST_NAME).resolve()),
                "runtimeVersion": manifest["runtimeVersion"],
                "piVersion": manifest["piVersion"],
                "fileCount": len(manifest["files"]),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
