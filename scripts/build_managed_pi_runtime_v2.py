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
    discover_managed_pi_runtime,
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
    try:
        installed = discover_managed_pi_runtime(
            Path.home() / "Library" / "Application Support" / "RagIme"
        )
        installed_node = Path(installed.node_executable)
        if installed_node.is_file():
            return str(installed_node)
    except (OSError, ManagedPiRuntimeError):
        pass
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
    managed_root = (
        Path.home()
        / "Library"
        / "Application Support"
        / "RagIme"
        / "PiRuntime"
    )
    pointer = managed_root / "current.json"
    try:
        version = str(json.loads(pointer.read_text(encoding="utf-8"))["version"])
    except (KeyError, json.JSONDecodeError, OSError):
        version = ""
    managed_node = managed_root / version / "bin" / "node"
    if version and managed_node.is_file():
        return str(managed_node)
    return shutil.which("node") or ""


def _node_relocation_error(node: Path) -> str:
    if sys.platform != "darwin":
        return ""
    try:
        linked = subprocess.run(
            ["otool", "-L", str(node)],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return "could not inspect Node dynamic-library dependencies"
    if "@rpath/libnode." in linked:
        return "Node depends on an external libnode dylib and is not relocatable"
    return ""


def _source_revision(pi_root: Path) -> tuple[str, str]:
    commit = _run(["git", "rev-parse", "HEAD"], cwd=pi_root)
    tracked_diff = subprocess.run(
        [
            "git",
            "diff",
            "--binary",
            "HEAD",
            "--",
            "packages",
            "package.json",
            "package-lock.json",
            "tsconfig.json",
        ],
        cwd=pi_root,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout
    untracked_output = _run(
        [
            "git",
            "ls-files",
            "--others",
            "--exclude-standard",
            "--",
            "packages",
            "package.json",
            "package-lock.json",
            "tsconfig.json",
        ],
        cwd=pi_root,
    )
    untracked = [line for line in untracked_output.splitlines() if line.strip()]
    if not tracked_diff and not untracked:
        return commit, ""
    digest = hashlib.sha256()
    digest.update(tracked_diff)
    for relative in sorted(untracked):
        path = pi_root / relative
        if not path.is_file() or path.is_symlink():
            continue
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
    dirty_digest = digest.hexdigest()[:12]
    return f"{commit}+dirty.{dirty_digest}", dirty_digest


def _hash_tree(path: Path) -> bytes:
    digest = hashlib.sha256()
    if not path.is_dir():
        return digest.digest()
    for item in sorted(candidate for candidate in path.rglob("*") if candidate.is_file()):
        digest.update(item.relative_to(path).as_posix().encode("utf-8"))
        digest.update(item.read_bytes())
    return digest.digest()


def _runtime_host_banner(skills_root: Path) -> str:
    skill_names = sorted(item.name for item in skills_root.iterdir() if item.is_dir()) if skills_root.is_dir() else []
    return (
        'import { createRequire as __createRequire } from "node:module"; '
        'import { delimiter as __pathDelimiter, dirname as __dirname, join as __join } from "node:path"; '
        'import { fileURLToPath as __fileURLToPath } from "node:url"; '
        'const require = __createRequire(import.meta.url); '
        f'const __ragImeSkillNames = {json.dumps(skill_names, ensure_ascii=True)}; '
        'const __ragImeRuntimeDir = __dirname(__fileURLToPath(import.meta.url)); '
        'const __ragImeSkillPaths = __ragImeSkillNames.map((name) => __join(__ragImeRuntimeDir, "skills", name)); '
        'const __ragImeConfiguredSkills = process.env.RAG_IME_PI_SKILL_PATHS || ""; '
        'process.env.RAG_IME_PI_SKILL_PATHS = '
        '[...__ragImeSkillPaths, __ragImeConfiguredSkills].filter(Boolean).join(__pathDelimiter);'
    )


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
    node_relocation_error = _node_relocation_error(node)
    if node_relocation_error:
        print(
            "managed Pi runtime build failed: "
            f"{node_relocation_error}; set RAG_IME_MANAGED_NODE to a standalone Node binary",
            file=sys.stderr,
        )
        return 1

    try:
        pi_version = str(json.loads(package_json.read_text(encoding="utf-8"))["version"])
        source_commit, dirty_digest = _source_revision(pi_root)
        provider_bridge_source = ROOT / "rag_ime" / "node" / "pi_provider_bridge_bundled.ts"
        product_skills = ROOT / "integrations" / "pi" / "skills"
        packager_digest = hashlib.sha256(
            provider_bridge_source.read_bytes()
            + Path(__file__).read_bytes()
            + _hash_tree(product_skills)
            + json.dumps(CONTROL_TOOL_IDS, separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:10]
        commit_prefix = source_commit.split("+", 1)[0][:12]
        dirty_suffix = f"-d{dirty_digest[:8]}" if dirty_digest else ""
        runtime_version = f"pi-{pi_version}-{commit_prefix}{dirty_suffix}-raghost-{packager_digest}"
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
            if product_skills.is_dir():
                runtime_skills = runtime_dir / "skills"
                runtime_skills.mkdir(exist_ok=True)
                for skill in sorted(item for item in product_skills.iterdir() if item.is_dir()):
                    shutil.copytree(skill, runtime_skills / skill.name, dirs_exist_ok=True)
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
                    f'--banner:js={_runtime_host_banner(product_skills)}',
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
