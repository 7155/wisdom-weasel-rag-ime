#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
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


def _run(command: list[str], *, cwd: Path) -> str:
    completed = subprocess.run(
        command,
        cwd=cwd,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return completed.stdout.strip()


def _default_node() -> str:
    configured = os.environ.get("RAG_IME_MANAGED_NODE", "").strip()
    if configured:
        return configured
    codex_runtime = (
        Path.home()
        / ".cache"
        / "codex-runtimes"
        / "codex-primary-runtime"
        / "dependencies"
        / "node"
        / "bin"
        / "node"
    )
    if codex_runtime.is_file():
        return str(codex_runtime)
    return shutil.which("node") or ""


def _smoke_runtime(node: Path, entrypoint: Path) -> dict[str, object]:
    request = {
        "protocolVersion": "2",
        "id": "managed-runtime-build-smoke",
        "method": "hello",
        "params": {},
    }
    with tempfile.TemporaryDirectory(prefix="rag-ime-pi-runtime-smoke-") as app_support:
        environment = dict(os.environ)
        environment.update(
            {
                "RAG_IME_APP_SUPPORT_DIR": app_support,
                "RAG_IME_PLUGIN_APPROVAL_TOKEN": "managed-runtime-build-smoke",
            }
        )
        completed = subprocess.run(
            [str(node), str(entrypoint)],
            input=json.dumps(request, separators=(",", ":")) + "\n",
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
            env=environment,
        )
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    if len(lines) != 1:
        raise ManagedPiRuntimeError("managed Pi Runtime Host smoke test returned an invalid response")
    response = json.loads(lines[0])
    result = response.get("result") if isinstance(response, dict) else None
    capabilities = result.get("capabilities") if isinstance(result, dict) else None
    if (
        not isinstance(response, dict)
        or not response.get("ok")
        or not isinstance(result, dict)
        or result.get("protocolVersion") != "2"
        or not isinstance(capabilities, dict)
        or not capabilities.get("multiSession")
    ):
        raise ManagedPiRuntimeError("managed Pi Runtime Host smoke test did not negotiate protocol v2")
    return response


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build a verified, SDK-backed Pi Runtime Host v2 payload without registry access"
    )
    parser.add_argument(
        "--pi-worktree",
        default=str(ROOT.parent / "pi-rag-ime-runtime"),
    )
    parser.add_argument("--output", default="")
    parser.add_argument(
        "--node",
        default=_default_node(),
        help="Relocatable Node 22+ binary copied into the managed payload",
    )
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--skip-smoke", action="store_true")
    args = parser.parse_args(argv)

    pi_root = Path(args.pi_worktree).expanduser().resolve()
    node = Path(args.node).expanduser().resolve() if args.node else Path()
    package_root = pi_root / "packages" / "rag-ime-runtime-host"
    package_json = pi_root / "packages" / "coding-agent" / "package.json"
    esbuild = pi_root / "node_modules" / ".bin" / "esbuild"
    if not package_root.is_dir() or not package_json.is_file() or not esbuild.is_file():
        print("managed Pi runtime build failed: Pi worktree is incomplete", file=sys.stderr)
        return 1
    if not node.is_file():
        print("managed Pi runtime build failed: Node executable is missing", file=sys.stderr)
        return 1

    try:
        pi_version = str(json.loads(package_json.read_text(encoding="utf-8"))["version"])
        source_commit = _run(["git", "rev-parse", "HEAD"], cwd=pi_root)
        provider_bridge_source = ROOT / "rag_ime" / "node" / "pi_provider_bridge_bundled.ts"
        packager_digest = hashlib.sha256(
            provider_bridge_source.read_bytes()
            + Path(__file__).read_bytes()
            + json.dumps(CONTROL_TOOL_IDS, separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:10]
        runtime_version = f"pi-{pi_version}-{source_commit[:12]}-raghost-{packager_digest}"
        destination = (
            Path(args.output).expanduser().resolve()
            if args.output
            else ROOT / "build" / "managed-pi-runtime" / runtime_version
        )
        if destination.exists():
            if not args.force:
                raise ManagedPiRuntimeError(f"output already exists: {destination}")
            shutil.rmtree(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        staging = destination.parent / f".{destination.name}.staging-{uuid.uuid4().hex}"
        staging.mkdir(mode=0o700)
        try:
            runtime_dir = staging / "runtime-host"
            bin_dir = staging / "bin"
            runtime_dir.mkdir(mode=0o700)
            bin_dir.mkdir(mode=0o700)
            bundled_skills = package_root / "skills"
            if bundled_skills.is_dir():
                shutil.copytree(bundled_skills, runtime_dir / "skills")
            bundled_entrypoint = runtime_dir / "cli.mjs"
            _run(
                [
                    str(esbuild),
                    str(package_root / "src" / "cli.ts"),
                    "--bundle",
                    "--platform=node",
                    "--format=esm",
                    "--target=node22",
                    f"--outfile={bundled_entrypoint}",
                    '--banner:js=import { createRequire as __createRequire } from "node:module"; const require = __createRequire(import.meta.url);',
                ],
                cwd=pi_root,
            )
            bundled_entrypoint.chmod(0o755)
            provider_bridge = runtime_dir / "provider-bridge.mjs"
            _run(
                [
                    str(esbuild),
                    str(provider_bridge_source),
                    "--bundle",
                    "--platform=node",
                    "--format=esm",
                    "--target=node22",
                    f"--outfile={provider_bridge}",
                    f"--alias:rag-ime-pi-auth-storage={pi_root / 'packages' / 'coding-agent' / 'src' / 'core' / 'auth-storage.ts'}",
                    f"--alias:rag-ime-pi-model-runtime={pi_root / 'packages' / 'coding-agent' / 'src' / 'core' / 'model-runtime.ts'}",
                    f"--alias:rag-ime-pi-openai-codex-oauth={pi_root / 'packages' / 'ai' / 'src' / 'auth' / 'oauth' / 'openai-codex.ts'}",
                    '--banner:js=import { createRequire as __createRequire } from "node:module"; const require = __createRequire(import.meta.url);',
                ],
                cwd=pi_root,
            )
            provider_bridge.chmod(0o755)
            packaged_node = bin_dir / "node"
            shutil.copy2(node, packaged_node)
            packaged_node.chmod(0o755)
            placeholder = runtime_dir / "extension-placeholder.mjs"
            placeholder.write_text(
                "// Protocol v2 loads product tools and managed plugins through the Runtime Host.\n"
                "export default function managedRuntimeV2Placeholder() {}\n",
                encoding="ascii",
            )
            smoke = {} if args.skip_smoke else _smoke_runtime(packaged_node, bundled_entrypoint)
            manifest = build_managed_pi_runtime_manifest(
                staging,
                runtime_version=runtime_version,
                pi_version=pi_version,
                launch_kind="node",
                pi_entrypoint="runtime-host/cli.mjs",
                node_entrypoint="bin/node",
                extension_entrypoint="runtime-host/extension-placeholder.mjs",
                tools=CONTROL_TOOL_IDS,
                source_repository=str(pi_root),
                source_commit=source_commit,
                source_package="@earendil-works/pi-rag-ime-runtime-host",
                protocol_version="2",
            )
            write_managed_pi_runtime_manifest(staging / MANIFEST_NAME, manifest)
            os.replace(staging, destination)
        finally:
            if staging.exists():
                shutil.rmtree(staging)
    except (KeyError, json.JSONDecodeError, OSError, subprocess.SubprocessError, ManagedPiRuntimeError) as exc:
        print(f"managed Pi runtime build failed: {exc}", file=sys.stderr)
        return 1

    result = {
        "ok": True,
        "runtimeVersion": runtime_version,
        "piVersion": pi_version,
        "protocolVersion": "2",
        "sourceCommit": source_commit,
        "payload": str(destination),
        "manifest": str(destination / MANIFEST_NAME),
        "fileCount": len(manifest["files"]),
        "smoke": smoke.get("result", {}) if smoke else {"skipped": True},
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
