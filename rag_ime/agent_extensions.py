from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from threading import RLock

from .agent_runtime_driver import AgentRuntimeDriver, AgentRuntimeError


_MAX_PLUGIN_FILES = 256
_MAX_PLUGIN_BYTES = 5 * 1024 * 1024
_MAX_NATIVE_PACKAGE_FILES = 1024
_MAX_NATIVE_PACKAGE_BYTES = 20 * 1024 * 1024
_MAX_SKILL_FILES = 2_048
_MAX_SKILL_FILE_BYTES = 2 * 1024 * 1024
_MAX_SKILL_BODY_BYTES = 64 * 1024
_SAFE_SUFFIXES = {".ts", ".js", ".mjs", ".json", ".md"}
_PREVIEW_TTL_MS = 10 * 60 * 1000
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SKILL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SKILL_RESOURCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,255}$")
_SKILL_FRONTMATTER = re.compile(
    r"\A---[ \t]*\r?\n(?P<frontmatter>.*?)\r?\n---(?:\s*\r?\n|\s*\Z)",
    re.DOTALL,
)
_EXTENSION_BINDING_CAPABILITY = "pawos.extension.binding."
_EXTENSION_BINDING_TOKEN = re.compile(
    r"^pawos\.extension\.binding\.([0-9a-f]{40})$"
)
_EXTENSION_PACKAGE_SEGMENT = re.compile(
    r"^(?:[a-z0-9][a-z0-9.-]*|SKILL\.md)$"
)


def extension_app_binding_sha256(
    app_manifest: Mapping[str, object],
    *,
    skill_sha256: str,
    package_version: str,
) -> str:
    """Derive the stable co-version binding for an Extension App package.

    The manifest's own binding field is excluded so the value can be checked
    after it is written.  The Skill bytes and package version are included
    explicitly even though the version is also present in the manifest: this
    makes the binding contract clear to package producers and reviewers.
    """

    normalized_skill_sha256 = str(skill_sha256).strip().lower()
    normalized_package_version = str(package_version).strip()
    if not _SHA256.fullmatch(normalized_skill_sha256):
        raise ValueError("Extension App Skill digest must be a lowercase SHA-256")
    if not normalized_package_version:
        raise ValueError("Extension App package version is required")
    canonical_manifest = {
        str(key): value
        for key, value in app_manifest.items()
        if str(key) != "bindingSha256"
    }
    payload = json.dumps(
        {
            "manifest": canonical_manifest,
            "packageVersion": normalized_package_version,
            "skillSha256": normalized_skill_sha256,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def extension_app_binding_capability(binding_sha256: str) -> str:
    """Encode one binding digest into NativePackageManager's safe capability ID."""

    normalized = str(binding_sha256).strip().lower()
    if not _SHA256.fullmatch(normalized):
        raise ValueError("Extension App binding must be a lowercase SHA-256")
    capability = f"{_EXTENSION_BINDING_CAPABILITY}{normalized[:40]}"
    if len(capability) > 64:
        raise ValueError("Extension App binding capability exceeds the Runtime limit")
    return capability


def extension_app_binding_capability_from_capabilities(
    capabilities: object,
) -> str | None:
    """Return exactly one valid Extension App binding capability, if present."""

    if not isinstance(capabilities, (list, tuple)):
        return None
    matches = [
        value
        for value in capabilities
        if isinstance(value, str) and _EXTENSION_BINDING_TOKEN.fullmatch(value)
    ]
    if len(matches) != 1:
        return None
    return matches[0]


def _extension_app_evidence(
    value: Mapping[str, object] | None,
    *,
    package_id: str = "",
    version: str = "",
) -> dict[str, object] | None:
    """Project only a self-consistent binding proof for API consumers.

    Native Pi currently guarantees the capability list and package version in
    installed inventory/receipts.  A richer ``extensionApp`` catalog object
    is retained when present, but never trusted without the same bounded
    binding capability.
    """

    if value is None:
        return None
    raw_manifest = value.get("manifest")
    manifest = dict(raw_manifest) if isinstance(raw_manifest, Mapping) else {}
    raw_extension = value.get("extensionApp")
    if raw_extension is None and isinstance(manifest.get("paw"), Mapping):
        raw_extension = manifest["paw"].get("extensionApp")
    extension = dict(raw_extension) if isinstance(raw_extension, Mapping) else {}
    capabilities = value.get("capabilities")
    if not isinstance(capabilities, (list, tuple)):
        package_paw = manifest.get("paw")
        capabilities = package_paw.get("capabilities") if isinstance(package_paw, Mapping) else None
    binding_capability = extension.get("bindingCapability")
    if not isinstance(binding_capability, str):
        binding_capability = extension_app_binding_capability_from_capabilities(
            capabilities
        )
    if not isinstance(binding_capability, str) or not _EXTENSION_BINDING_TOKEN.fullmatch(
        binding_capability
    ):
        return None
    binding_sha256 = extension.get("bindingSha256")
    if binding_sha256 is not None:
        if not isinstance(binding_sha256, str) or not _SHA256.fullmatch(binding_sha256):
            return None
        if extension_app_binding_capability(binding_sha256) != binding_capability:
            return None
    resolved_version = (
        extension.get("version")
        or version
        or value.get("version")
        or manifest.get("version")
    )
    if not isinstance(resolved_version, str) or not resolved_version.strip():
        return None
    evidence: dict[str, object] = {
        key: item
        for key, item in extension.items()
        if key
        in {
            "id",
            "packageId",
            "version",
            "bindingSha256",
            "skillRef",
            "skillSha256",
            "verticalSuiteId",
            "verticalSuiteRevision",
            "sandbox",
        }
    }
    evidence["version"] = resolved_version.strip()
    evidence["bindingCapability"] = binding_capability
    if package_id and "packageId" not in evidence:
        evidence["packageId"] = package_id
    elif "packageId" not in evidence and isinstance(manifest.get("name"), str):
        evidence["packageId"] = manifest["name"]
    return evidence


def _verified_extension_app_evidence(
    value: Mapping[str, object],
    *,
    package_id: str = "",
    version: str = "",
    require_managed_source: bool = True,
) -> dict[str, object] | None:
    """Rebuild complete App evidence from the exact Runtime-owned package.

    Pi deliberately exposes only generic Package state.  The Sidecar therefore
    verifies the content-addressed managed source that Pi returned, then reads
    the App contract stored inside that package.  A copied capability or a
    partial API object is never enough to expose a PAWOS App.
    """

    raw_runtime_capabilities = value.get("capabilities")
    if (
        not isinstance(raw_runtime_capabilities, (list, tuple))
        or any(not isinstance(item, str) for item in raw_runtime_capabilities)
        or len(set(raw_runtime_capabilities)) != len(raw_runtime_capabilities)
    ):
        return None
    runtime_capabilities = tuple(raw_runtime_capabilities)
    runtime_binding = extension_app_binding_capability_from_capabilities(
        runtime_capabilities
    )
    if runtime_binding is None:
        return None
    raw_source = value.get("source")
    source = raw_source if isinstance(raw_source, str) else ""
    if not source and isinstance(raw_source, Mapping):
        for key in ("resolved", "requested"):
            candidate = raw_source.get(key)
            if isinstance(candidate, str) and candidate:
                source = candidate
                break
    if not source:
        return None
    expected_digest = str(
        value.get("digest") or value.get("installedDigest") or ""
    ).strip()
    resolved_package_id = str(package_id or value.get("id") or "").strip()
    resolved_version = str(version or value.get("version") or "").strip()
    requested = Path(source).expanduser()
    if not requested.is_absolute():
        return None
    try:
        canonical_source = requested.resolve(strict=True)
    except OSError:
        return None
    if require_managed_source:
        package_key = hashlib.sha256(resolved_package_id.encode("utf-8")).hexdigest()[:16]
        if (
            not _SHA256.fullmatch(expected_digest)
            or canonical_source.name != expected_digest
            or canonical_source.parent.name != package_key
            or canonical_source.parent.parent.name != "packages"
        ):
            return None
    evidence = _verified_extension_app_source(
        str(canonical_source),
        expected_digest,
        resolved_package_id,
        resolved_version,
        runtime_capabilities,
    )
    if evidence is None or evidence.get("bindingCapability") != runtime_binding:
        return None
    return dict(evidence)


def _verified_extension_app_source(
    source: str,
    expected_digest: str,
    package_id: str,
    version: str,
    runtime_capabilities: tuple[str, ...],
) -> dict[str, object] | None:
    try:
        requested = Path(source).expanduser()
        if requested.is_symlink() or not requested.is_dir():
            return None
        package_root = requested.resolve(strict=True)
        files: list[Path] = []
        total_bytes = 0

        def visit(directory: Path) -> bool:
            nonlocal total_bytes
            try:
                visible = [
                    item
                    for item in directory.iterdir()
                    if item.name not in {".git", "node_modules"}
                ]
                if len({item.name.casefold() for item in visible}) != len(visible):
                    return False
                entries = sorted(
                    visible,
                    key=lambda item: (item.name.casefold(), item.name),
                )
            except OSError:
                return False
            for item in entries:
                if not _EXTENSION_PACKAGE_SEGMENT.fullmatch(item.name):
                    return False
                if item.is_symlink():
                    return False
                if item.is_dir():
                    if not visit(item):
                        return False
                    continue
                if not item.is_file():
                    return False
                files.append(item)
                total_bytes += item.stat().st_size
                if (
                    len(files) > _MAX_NATIVE_PACKAGE_FILES
                    or total_bytes > _MAX_NATIVE_PACKAGE_BYTES
                ):
                    return False
            return True

        if not visit(package_root):
            return None
        digest = hashlib.sha256()
        for item in files:
            digest.update(item.relative_to(package_root).as_posix().encode("utf-8"))
            digest.update(b"\0")
            digest.update(item.read_bytes())
            digest.update(b"\0")
        package_digest = digest.hexdigest()
        if expected_digest and (
            not _SHA256.fullmatch(expected_digest)
            or package_digest != expected_digest
        ):
            return None

        package_path = package_root / "package.json"
        if package_path.is_symlink() or not package_path.is_file():
            return None
        package_manifest = json.loads(package_path.read_text(encoding="utf-8"))
        if not isinstance(package_manifest, Mapping):
            return None
        manifest_package_id = str(package_manifest.get("name") or "")
        manifest_version = str(package_manifest.get("version") or "")
        if package_id and manifest_package_id != package_id:
            return None
        if version and manifest_version != version:
            return None
        paw = package_manifest.get("paw")
        if not isinstance(paw, Mapping):
            return None
        raw_package_capabilities = paw.get("capabilities")
        if (
            not isinstance(raw_package_capabilities, list)
            or any(not isinstance(item, str) for item in raw_package_capabilities)
            or len(set(raw_package_capabilities)) != len(raw_package_capabilities)
            or tuple(sorted(raw_package_capabilities)) != runtime_capabilities
        ):
            return None
        binding_capability = extension_app_binding_capability_from_capabilities(
            raw_package_capabilities
        )
        extension = paw.get("extensionApp")
        if not binding_capability or not isinstance(extension, Mapping):
            return None
        app_manifest = extension.get("manifest")
        if not isinstance(app_manifest, Mapping):
            return None
        skill_ref = str(extension.get("skillRef") or "")
        skill_path = package_root / "skills" / skill_ref / "SKILL.md"
        if (
            not skill_ref
            or skill_path.is_symlink()
            or not skill_path.is_file()
            or not skill_path.resolve(strict=True).is_relative_to(package_root)
        ):
            return None
        skill_sha256 = hashlib.sha256(skill_path.read_bytes()).hexdigest()
        binding_sha256 = str(extension.get("bindingSha256") or "")
        if (
            not _SHA256.fullmatch(binding_sha256)
            or extension_app_binding_capability(binding_sha256)
            != binding_capability
            or str(extension.get("skillSha256") or "") != skill_sha256
            or str(app_manifest.get("bindingSha256") or "") != binding_sha256
            or str(app_manifest.get("skillSha256") or "") != skill_sha256
            or extension_app_binding_sha256(
                app_manifest,
                skill_sha256=skill_sha256,
                package_version=manifest_version,
            )
            != binding_sha256
        ):
            return None
        required = {
            "id": str(app_manifest.get("id") or ""),
            "packageId": str(app_manifest.get("packageId") or ""),
            "version": str(app_manifest.get("version") or ""),
            "bindingSha256": binding_sha256,
            "skillRef": str(app_manifest.get("skillRef") or ""),
            "skillSha256": skill_sha256,
            "verticalSuiteId": str(app_manifest.get("verticalSuiteId") or ""),
            "verticalSuiteRevision": str(
                app_manifest.get("verticalSuiteRevision") or ""
            ),
        }
        sandbox_contract = app_manifest.get("sandbox")
        if sandbox_contract is not None:
            if (
                not isinstance(sandbox_contract, Mapping)
                or set(sandbox_contract) != {"default", "connectorPackageId", "policyId"}
                or sandbox_contract.get("default") not in {"required", "optional", "disabled"}
                or sandbox_contract.get("connectorPackageId") != "vertical-agent-sandbox"
                or sandbox_contract.get("policyId") != "vertical-readonly-v1"
                or extension.get("sandbox") != sandbox_contract
            ):
                return None
        if (
            not all(required.values())
            or required["packageId"] != manifest_package_id
            or required["version"] != manifest_version
        ):
            return None
        for field, expected in required.items():
            if field == "skillSha256":
                continue
            if str(extension.get(field) or "") != expected:
                return None
        return {
            **required,
            **({"sandbox": dict(sandbox_contract)} if isinstance(sandbox_contract, Mapping) else {}),
            "bindingCapability": binding_capability,
            "packageDigest": package_digest,
        }
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        return None


def _public_package_source(value: object) -> dict[str, str]:
    kind = "managed"
    if isinstance(value, Mapping):
        candidate = value.get("kind")
        if isinstance(candidate, str) and candidate in {"local", "npm", "git"}:
            kind = candidate
    labels = {
        "managed": "Runtime-managed Pi Package",
        "local": "Local package staged by Runtime",
        "npm": "npm package resolved by Runtime",
        "git": "Git package resolved by Runtime",
    }
    return {"kind": kind, "label": labels[kind]}


def _public_version_record(value: object) -> dict[str, str] | None:
    if not isinstance(value, Mapping):
        return None
    version = str(value.get("version") or "")
    digest = str(value.get("digest") or "")
    if not version or not digest:
        return None
    result = {"version": version, "digest": digest}
    installed_at = str(value.get("installedAt") or "")
    if installed_at:
        result["installedAt"] = installed_at
    return result


def _public_plugin_payload(value: Mapping[str, object]) -> dict[str, object]:
    result: dict[str, object] = {
        "id": str(value.get("id") or ""),
        "name": str(value.get("name") or value.get("id") or ""),
        "version": str(value.get("version") or ""),
        "description": str(value.get("description") or ""),
        "digest": str(value.get("digest") or ""),
        "enabled": value.get("enabled") is True,
        "distribution": str(value.get("distribution") or ""),
        "permissions": [
            str(item) for item in value.get("permissions") or [] if isinstance(item, str)
        ],
        "capabilities": [
            str(item) for item in value.get("capabilities") or [] if isinstance(item, str)
        ],
        "resources": {
            kind: [
                str(item)
                for item in value.get("resources", {}).get(kind, [])
                if isinstance(item, str)
            ]
            for kind in ("extensions", "skills", "prompts", "themes")
        }
        if isinstance(value.get("resources"), Mapping)
        else {},
        "source": _public_package_source(value.get("source")),
    }
    versions = [
        record
        for item in value.get("installedVersions") or []
        if (record := _public_version_record(item)) is not None
    ]
    if versions:
        result["installedVersions"] = versions
    rollback = _public_version_record(value.get("rollbackTarget"))
    if rollback is not None:
        result["rollbackTarget"] = rollback
    if value.get("removed") is True:
        result["removed"] = True
    return result


def _bounded_skill_text(value: object, *, maximum: int = 512) -> str:
    """Return display metadata without control characters or unbounded text."""

    text = str(value or "").replace("\x00", "").strip()
    text = "".join(character for character in text if character in "\n\t" or ord(character) >= 0x20)
    return text[:maximum].strip()


def _skill_frontmatter(content: str) -> tuple[str, str] | None:
    match = _SKILL_FRONTMATTER.match(content)
    if match is None:
        return None
    values: dict[str, str] = {}
    for line in match.group("frontmatter").splitlines():
        key, separator, raw_value = line.partition(":")
        if not separator or key.strip() not in {"name", "description"}:
            continue
        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key.strip()] = _bounded_skill_text(value)
    name = values.get("name", "")
    if not _SKILL_ID.fullmatch(name):
        return None
    return name, values.get("description", "")


def _read_skill_file(path: Path) -> tuple[str, str, bytes] | None:
    """Read and validate one server-owned Skill file."""

    try:
        if path.is_symlink() or not path.is_file():
            return None
        data = path.read_bytes()
        if not data or len(data) > _MAX_SKILL_FILE_BYTES:
            return None
        content = data.decode("utf-8")
    except (OSError, UnicodeError):
        return None
    frontmatter = _skill_frontmatter(content)
    if frontmatter is None or path.parent.name != frontmatter[0]:
        return None
    return frontmatter[0], frontmatter[1], data


def _discover_skill_files(root: Path) -> tuple[Path, ...]:
    """Discover only regular ``SKILL.md`` files below one trusted root."""

    try:
        if root.is_symlink() or not root.exists():
            return ()
        canonical_root = root.resolve(strict=True)
        if not canonical_root.is_dir():
            return (canonical_root,) if canonical_root.name == "SKILL.md" else ()
    except OSError:
        return ()
    discovered: list[Path] = []
    pending = [canonical_root]
    while pending and len(discovered) < _MAX_SKILL_FILES:
        directory = pending.pop()
        try:
            entries = sorted(
                directory.iterdir(),
                key=lambda item: (item.name.casefold(), item.name),
                reverse=True,
            )
        except OSError:
            continue
        for item in entries:
            try:
                if item.is_symlink():
                    continue
                if item.is_dir():
                    pending.append(item)
                elif item.name == "SKILL.md" and item.is_file():
                    resolved = item.resolve(strict=True)
                    if _is_within(resolved, canonical_root):
                        discovered.append(resolved)
                        if len(discovered) >= _MAX_SKILL_FILES:
                            break
            except OSError:
                continue
    return tuple(sorted(set(discovered), key=lambda item: item.as_posix()))


def _safe_skill_resource(value: object) -> str | None:
    resource = str(value or "").strip().replace("\\", "/")
    path = Path(resource)
    if (
        not resource
        or not _SKILL_RESOURCE.fullmatch(resource)
        or path.is_absolute()
        or ".." in path.parts
        or path.name != "SKILL.md"
    ):
        return None
    return path.as_posix()


def _runtime_package_source_path(value: Mapping[str, object]) -> Path | None:
    """Extract a resolved, content-addressed Package directory from Runtime."""

    package_id = str(value.get("id") or "").strip()
    expected_digest = str(
        value.get("digest") or value.get("installedDigest") or ""
    ).strip().lower()
    if not package_id or not _SHA256.fullmatch(expected_digest):
        return None
    package_key = hashlib.sha256(package_id.encode("utf-8")).hexdigest()[:16]
    raw_source = value.get("source")
    candidates: list[object] = []
    if isinstance(raw_source, str):
        candidates.append(raw_source)
    elif isinstance(raw_source, Mapping):
        candidates.extend(
            raw_source.get(key)
            for key in ("resolved", "requested", "path", "root", "sourcePath", "packagePath")
        )
    candidates.extend(
        value.get(key)
        for key in ("sourcePath", "packagePath", "packageRoot", "root")
    )
    for candidate in candidates:
        if not isinstance(candidate, str) or not candidate.strip():
            continue
        requested = Path(candidate).expanduser()
        if not requested.is_absolute():
            continue
        try:
            resolved = requested.resolve(strict=True)
        except OSError:
            continue
        if (
            requested.is_symlink()
            or resolved.is_symlink()
            or not resolved.is_dir()
            or resolved.name != expected_digest
            or resolved.parent.name != package_key
            or resolved.parent.parent.name != "packages"
        ):
            continue
        return resolved
    return None


def _skill_resource_prefix(root: Path, *, bundled: bool) -> str:
    parts = root.parts
    if bundled and len(parts) >= 3 and parts[-3:] == ("integrations", "pi", "skills"):
        return "integrations/pi/skills"
    if not bundled and len(parts) >= 2 and parts[-2:] == (".agents", "skills"):
        return ".agents/skills"
    if not bundled and len(parts) >= 2 and parts[-2:] == (".pi", "skills"):
        return ".pi/skills"
    return root.name or "skills"


def _skill_digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _bounded_utf8_prefix(data: bytes, maximum: int) -> tuple[str, bool]:
    truncated = len(data) > maximum
    end = min(len(data), maximum)
    while end >= 0:
        try:
            return data[:end].decode("utf-8"), truncated or end < len(data)
        except UnicodeDecodeError:
            end -= 1
    return "", True


class AgentExtensionService:
    """Product-owned approval boundary around the managed Pi plugin store."""

    def __init__(
        self,
        *,
        runtime_provider: Callable[[], AgentRuntimeDriver],
        inbox_root: str | Path,
        catalog_path: str | Path | None = None,
        bundled_skills_root: str | Path | None = None,
        project_skills_roots: tuple[str | Path, ...] = (),
    ) -> None:
        self._runtime_provider = runtime_provider
        self.inbox_root = Path(inbox_root).expanduser().resolve(strict=False)
        self.catalog_path = (
            Path(catalog_path).expanduser().resolve(strict=False)
            if catalog_path is not None
            else Path(__file__).with_name("plugin_catalog.json")
        )
        self.bundled_skills_root = (
            Path(bundled_skills_root).expanduser().resolve(strict=False)
            if bundled_skills_root is not None
            else Path(__file__).resolve().parents[1] / "integrations" / "pi" / "skills"
        )
        configured_project_roots = tuple(
            Path(value).expanduser().resolve(strict=False)
            for value in project_skills_roots
            if str(value).strip()
        )
        if not configured_project_roots:
            configured_paths = os.environ.get("RAG_IME_PROJECT_SKILL_PATHS", "")
            configured_project_roots = tuple(
                Path(value).expanduser().resolve(strict=False)
                for value in configured_paths.split(os.pathsep)
                if value.strip()
            )
        self.project_skills_roots = configured_project_roots
        self._lock = RLock()
        self._tokens: dict[str, dict[str, object]] = {}
        self._proposals: dict[str, dict[str, object]] = {}

    def list(self) -> dict[str, object]:
        try:
            plugins = self._call("plugin_list")
        except AgentRuntimeError:
            # The Sidecar can serve management routes while the managed Pi
            # Runtime is owned by the Agent gateway (or is still starting).
            # Project that state explicitly so the plugin page remains
            # navigable instead of terminating the HTTP connection.
            return {
                "schemaVersion": "rag-ime.plugin-inventory.v1",
                "ok": True,
                "runtimeAvailable": False,
                "items": [],
            }
        if not isinstance(plugins, list):
            raise AgentRuntimeError("Pi Runtime Host returned an invalid plugin list")
        items: list[dict[str, object]] = []
        for value in plugins:
            if not isinstance(value, Mapping):
                continue
            raw_versions = value.get("installedVersions")
            versions = [
                record
                for raw_version in raw_versions if (record := _public_version_record(raw_version)) is not None
            ] if isinstance(raw_versions, list) else []
            package_id = str(value.get("id") or "")
            package_version = str(value.get("version") or "")
            capabilities = [
                str(item)
                for item in value.get("capabilities") or []
                if isinstance(item, str)
            ]
            item: dict[str, object] = {
                "id": package_id,
                "displayName": str(value.get("name") or package_id or "Plugin"),
                "version": package_version,
                "description": str(value.get("description") or ""),
                "digest": str(value.get("digest") or ""),
                "enabled": value.get("enabled") is True,
                "installed": True,
                "rollbackAvailable": isinstance(
                    value.get("rollbackTarget"), Mapping
                ),
                "updateAvailable": False,
                "permissions": [
                    str(item)
                    for item in value.get("permissions") or []
                    if isinstance(item, str)
                ],
                "resources": {
                    kind: [
                        str(item)
                        for item in value.get("resources", {}).get(kind, [])
                        if isinstance(item, str)
                    ]
                    for kind in ("extensions", "skills", "prompts", "themes")
                }
                if isinstance(value.get("resources"), Mapping)
                else {},
                "source": _public_package_source(value.get("source")),
                "capabilities": capabilities,
                "installedVersions": versions,
                "rollbackTarget": _public_version_record(value.get("rollbackTarget")),
            }
            evidence = _verified_extension_app_evidence(
                value,
                package_id=package_id,
                version=package_version,
            )
            if evidence is not None:
                item["extensionApp"] = evidence
            items.append(item)
        return {
            "schemaVersion": "rag-ime.plugin-inventory.v1",
            "ok": True,
            "runtimeAvailable": True,
            "items": items,
        }

    def skills_list(self) -> dict[str, object]:
        """Project every currently discoverable Skill without exposing paths."""

        runtime_available = True
        try:
            packages = self._call("plugin_list")
        except AgentRuntimeError:
            packages = []
            runtime_available = False
        if not isinstance(packages, list):
            raise AgentRuntimeError("Pi Runtime Host returned an invalid plugin list")
        records = self._skill_inventory_records(packages)
        items = [dict(item) for item, _path in records]
        revision = _payload_digest({"items": items})
        return {
            "schemaVersion": "rag-ime.skill-inventory.v1",
            "ok": True,
            "runtimeAvailable": runtime_available,
            "revision": revision,
            "items": items,
        }

    def skill_detail(self, payload: Mapping[str, object]) -> dict[str, object]:
        """Read bounded instructions for an inventory ID, never a client path."""

        skill_id = _bounded_skill_text(payload.get("skillId"), maximum=128)
        if not _SKILL_ID.fullmatch(skill_id):
            raise ValueError("skillId is invalid")
        records = self._skill_inventory_records()
        selected = next(
            ((dict(item), path) for item, path in records if item.get("skillId") == skill_id),
            None,
        )
        if selected is None:
            raise ValueError("Skill is not present in the current inventory")
        item, path = selected
        loaded = _read_skill_file(path)
        if loaded is None:
            raise ValueError("Skill content is unavailable")
        _name, _description, data = loaded
        digest = _skill_digest(data)
        if digest != str(item.get("digest") or ""):
            raise ValueError("Skill content changed; reload the inventory")
        try:
            full_content = data.decode("utf-8")
        except UnicodeDecodeError as error:  # pragma: no cover - guarded by reader
            raise ValueError("Skill content is not valid UTF-8") from error
        frontmatter = _SKILL_FRONTMATTER.match(full_content)
        instructions = full_content[frontmatter.end() :] if frontmatter else full_content
        body, truncated = _bounded_utf8_prefix(
            instructions.strip().encode("utf-8"),
            _MAX_SKILL_BODY_BYTES,
        )
        item.update(
            {
                "body": body,
                "bodyBytes": len(body.encode("utf-8")),
                "bodyTruncated": truncated,
                "contentBytes": len(data),
            }
        )
        return {
            "schemaVersion": "rag-ime.skill-detail.v1",
            "ok": True,
            "revision": str(item.get("contentRevision") or ""),
            "item": item,
        }

    def _skill_inventory_records(
        self,
        packages: list[object] | None = None,
    ) -> list[tuple[dict[str, object], Path]]:
        """Build a bounded, deterministic projection and its private path index."""

        records: list[tuple[dict[str, object], Path]] = []
        seen_paths: set[Path] = set()

        def add_file(
            path: Path,
            *,
            source_kind: str,
            root: Path,
            resource_path: str,
            package: Mapping[str, object] | None = None,
        ) -> None:
            if len(records) >= _MAX_SKILL_FILES:
                return
            try:
                canonical_root = root.resolve(strict=True)
                canonical_path = path.resolve(strict=True)
            except OSError:
                return
            if (
                canonical_path in seen_paths
                or not _is_within(canonical_path, canonical_root)
            ):
                return
            loaded = _read_skill_file(canonical_path)
            if loaded is None:
                return
            name, description, data = loaded
            seen_paths.add(canonical_path)
            digest = _skill_digest(data)
            item: dict[str, object] = {
                "skillId": name,
                "name": name,
                "description": description
                or (
                    _bounded_skill_text(package.get("description"))
                    if isinstance(package, Mapping)
                    else ""
                ),
                "sourceKind": source_kind,
                "resourcePath": resource_path,
                "digest": digest,
                "contentRevision": f"sha256:{digest}",
                "sizeBytes": len(data),
                "installed": True,
                "enabled": None,
                "installState": source_kind,
                "management": "inspect_only",
                "managementReason": (
                    "This Skill is supplied by Pi and has no independent enable switch."
                    if source_kind == "bundled"
                    else "This project Skill is discovered from the project workspace "
                    "and has no independent Package lifecycle."
                ),
                "actions": [],
            }
            if isinstance(package, Mapping):
                package_id = _bounded_skill_text(package.get("id"), maximum=160)
                package_version = _bounded_skill_text(package.get("version"), maximum=64)
                if not package_id:
                    return
                package_installed = package.get("removed") is not True
                package_enabled = package.get("enabled") is True and package_installed
                item.update(
                    {
                        "packageId": package_id,
                        "packageVersion": package_version,
                        "enabled": package_enabled,
                        "installed": package_installed,
                        "installState": (
                            "enabled"
                            if package_enabled
                            else "disabled" if package_installed else "uninstalled"
                        ),
                        "management": "package",
                        "managementReason": (
                            "This Skill belongs to the Package; lifecycle changes apply "
                            "to the whole Package and all of its resources."
                        ),
                        "actions": ["enable", "disable", "update", "uninstall"],
                    }
                )
            records.append((item, canonical_path))

        def add_local_root(root: Path, source_kind: str) -> None:
            try:
                canonical_root = root.resolve(strict=True)
            except OSError:
                return
            prefix = _skill_resource_prefix(
                canonical_root,
                bundled=source_kind == "bundled",
            )
            for path in _discover_skill_files(canonical_root):
                try:
                    relative = path.relative_to(canonical_root).as_posix()
                except ValueError:
                    continue
                add_file(
                    path,
                    source_kind=source_kind,
                    root=canonical_root,
                    resource_path=f"{prefix}/{relative}",
                )

        add_local_root(self.bundled_skills_root, "bundled")
        for root in self.project_skills_roots:
            add_local_root(root, "project")

        if packages is None:
            try:
                packages = self._call("plugin_list")
            except AgentRuntimeError:
                packages = []
        for raw_package in packages:
            if not isinstance(raw_package, Mapping):
                continue
            package_id = _bounded_skill_text(raw_package.get("id"), maximum=160)
            if not package_id:
                continue
            root = _runtime_package_source_path(raw_package)
            if root is None:
                continue
            resources = raw_package.get("resources")
            raw_skills = resources.get("skills") if isinstance(resources, Mapping) else None
            skill_resources = (
                [_safe_skill_resource(value) for value in raw_skills]
                if isinstance(raw_skills, list)
                else []
            )
            skill_resources = [
                value for value in skill_resources if isinstance(value, str)
            ]
            if skill_resources:
                for resource in skill_resources:
                    candidate = root / resource
                    if candidate.is_dir():
                        candidate = candidate / "SKILL.md"
                    add_file(
                        candidate,
                        source_kind="package",
                        root=root,
                        resource_path=resource,
                        package=raw_package,
                    )
            else:
                for path in _discover_skill_files(root / "skills"):
                    try:
                        resource = path.relative_to(root).as_posix()
                    except ValueError:
                        continue
                    add_file(
                        path,
                        source_kind="package",
                        root=root,
                        resource_path=resource,
                        package=raw_package,
                    )

        # A runtime may reject duplicate names before loading them. The
        # projection keeps each trusted source inspectable while assigning
        # deterministic route IDs for any stale or conflicting inventory.
        records.sort(
            key=lambda record: (
                str(record[0].get("name") or "").casefold(),
                str(record[0].get("name") or ""),
                str(record[0].get("sourceKind") or ""),
                str(record[0].get("packageId") or ""),
                str(record[0].get("resourcePath") or ""),
            )
        )
        counts: dict[str, int] = {}
        for item, _path in records:
            name = str(item.get("skillId") or "")
            counts[name] = counts.get(name, 0) + 1
        used_ids: set[str] = set()
        for item, path in records:
            skill_id = str(item.get("skillId") or "")
            if counts.get(skill_id, 0) > 1 or skill_id in used_ids:
                source = str(item.get("sourceKind") or "skill")
                owner_key = "\0".join(
                    (
                        source,
                        str(item.get("packageId") or ""),
                        str(item.get("resourcePath") or ""),
                        str(path),
                    )
                )
                sequence = 1
                while True:
                    digest = hashlib.sha256(
                        f"{owner_key}\0{sequence}".encode("utf-8")
                    ).hexdigest()[:12]
                    suffix = f"--{source}--{digest}"
                    candidate = f"{skill_id[: 128 - len(suffix)]}{suffix}"
                    if candidate not in used_ids:
                        item["skillId"] = candidate
                        break
                    sequence += 1
            used_ids.add(str(item.get("skillId") or ""))
        records.sort(
            key=lambda record: (
                str(record[0].get("name") or "").casefold(),
                str(record[0].get("name") or ""),
                str(record[0].get("sourceKind") or ""),
                str(record[0].get("packageId") or ""),
                str(record[0].get("resourcePath") or ""),
                str(record[0].get("skillId") or ""),
            )
        )
        return records

    def extension_app_skill_owners(self) -> dict[str, str]:
        """Return verified enabled App Skill ownership for Session disclosure."""

        inventory = self.list()
        if inventory.get("runtimeAvailable") is False:
            return {}
        owners: dict[str, str] = {}
        for item in inventory.get("items") or []:
            if not isinstance(item, Mapping) or item.get("enabled") is not True:
                continue
            evidence = item.get("extensionApp")
            if not isinstance(evidence, Mapping):
                continue
            skill_ref = str(evidence.get("skillRef") or "").strip()
            owner_app_id = str(evidence.get("id") or "").strip()
            if skill_ref and owner_app_id:
                owners[skill_ref] = owner_app_id
        return owners

    def catalog(self) -> dict[str, object]:
        document = self._catalog_document()
        inventory = self.list()
        runtime_available = inventory.get("runtimeAvailable") is not False
        installed = {
            str(item.get("id") or ""): item
            for item in inventory["items"]
            if isinstance(item, Mapping)
        }
        entries: list[dict[str, object]] = []
        runtime_packages: list[dict[str, object]] = []
        if runtime_available:
            try:
                raw_packages = self._call("plugin_catalog")
            except AgentRuntimeError:
                # Older staged runtimes do not expose the native Pi Package
                # catalog. Keep the legacy first-party catalog readable until
                # the atomic runtime cutover completes.
                raw_packages = []
            if not isinstance(raw_packages, list):
                raise AgentRuntimeError(
                    "Pi Runtime Host returned an invalid Pi Package catalog"
                )
            runtime_packages = [
                dict(value) for value in raw_packages if isinstance(value, Mapping)
            ]
        for package in runtime_packages:
            package_id = str(package.get("id") or package.get("name") or "")
            if not package_id:
                continue
            version = str(package.get("version") or "")
            installed_version = str(package.get("installedVersion") or "")
            package_capabilities = [
                str(value)
                for value in package.get("capabilities") or []
                if isinstance(value, str)
            ]
            entry: dict[str, object] = {
                "id": package_id,
                "displayName": str(
                    package.get("displayName") or package.get("name") or package_id
                ),
                "description": str(package.get("description") or ""),
                "publisher": "Personal Agent Workbench",
                "source": {
                    "kind": "bundled_pi_package",
                    "label": "Bundled with the active Pi Runtime",
                },
                "permissions": [],
                "capabilities": package_capabilities,
                "compatibility": {"runtimeProtocol": "2", "pi": ">=0.84.2"},
                "security": {
                    "reviewed": True,
                    "networkAccess": package_id.endswith("/subagent"),
                    "enforcement": "content_addressed_pi_package",
                    "notes": (
                        "First-party Pi Package. Install, enable, disable, and uninstall "
                        "are owned by the active Pi Runtime Host."
                    ),
                },
                "versions": ([{"version": version, "releasedAt": "", "notes": ""}] if version else []),
                "latestVersion": version,
                "installedVersion": installed_version,
                "version": installed_version or version,
                "installed": package.get("installed") is True,
                "enabled": package.get("enabled") is True,
                "updateAvailable": bool(
                    installed_version
                    and version
                    and _version_key(version) > _version_key(installed_version)
                ),
                "installState": (
                    "update_available"
                    if installed_version
                    and version
                    and _version_key(version) > _version_key(installed_version)
                    else "installed"
                    if package.get("installed") is True
                    else "available"
                ),
                "actionable": True,
                "distribution": "pi_package",
                "bundled": True,
            }
            current = installed.get(package_id)
            current_evidence = current.get("extensionApp") if current else None
            if (
                isinstance(current_evidence, Mapping)
                and installed_version == version
            ):
                entry["capabilities"] = list(current.get("capabilities") or [])
                entry["extensionApp"] = dict(current_evidence)
            elif not installed_version:
                candidate_evidence = _verified_extension_app_evidence(
                    package,
                    package_id=package_id,
                    version=version,
                    require_managed_source=False,
                )
                if candidate_evidence is not None:
                    entry["extensionApp"] = candidate_evidence
            entries.append(entry)
        for raw_entry in document.get("entries") or []:
            if not isinstance(raw_entry, Mapping):
                continue
            versions = [
                dict(value)
                for value in raw_entry.get("versions") or []
                if isinstance(value, Mapping)
            ]
            versions.sort(
                key=lambda value: _version_key(str(value.get("version") or "")),
                reverse=True,
            )
            plugin_id = str(raw_entry.get("id") or "")
            current = installed.get(plugin_id)
            current_version = str(current.get("version") or "") if current else ""
            latest_version = str(versions[0].get("version") or "") if versions else ""
            source = dict(raw_entry.get("source") or {})
            entries.append(
                {
                    "id": plugin_id,
                    "displayName": str(raw_entry.get("displayName") or plugin_id),
                    "description": str(raw_entry.get("description") or ""),
                    "publisher": str(raw_entry.get("publisher") or ""),
                    "source": source,
                    "permissions": [
                        str(value)
                        for value in raw_entry.get("permissions") or []
                        if isinstance(value, str)
                    ],
                    "compatibility": dict(raw_entry.get("compatibility") or {}),
                    "security": dict(raw_entry.get("security") or {}),
                    "versions": [
                        {
                            "version": str(value.get("version") or ""),
                            "releasedAt": str(value.get("releasedAt") or ""),
                            "notes": str(value.get("notes") or ""),
                        }
                        for value in versions
                    ],
                    "latestVersion": latest_version,
                    "installedVersion": current_version,
                    "installed": current is not None,
                    "enabled": bool(current and current.get("enabled") is True),
                    "updateAvailable": bool(
                        current_version
                        and latest_version
                        and _version_key(latest_version) > _version_key(current_version)
                    ),
                    "installState": (
                        "review_only"
                        if source.get("kind") == "review_only" or not versions
                        else "update_available"
                        if current_version
                        and _version_key(latest_version) > _version_key(current_version)
                        else "installed"
                        if current_version
                        else "available"
                    ),
                    "actionable": source.get("kind") == "bundled" and bool(versions),
                }
            )
        catalog_ids = {
            str(item.get("id") or "")
            for item in entries
            if isinstance(item, Mapping)
        }
        for plugin_id, current in sorted(installed.items()):
            if not plugin_id or plugin_id in catalog_ids:
                continue
            entries.append(
                {
                    "id": plugin_id,
                    "displayName": str(
                        current.get("displayName") or plugin_id
                    ),
                    "description": str(current.get("description") or ""),
                    "publisher": "",
                    "source": {
                        "kind": "runtime_inventory",
                        "label": "Installed runtime inventory",
                    },
                    "permissions": list(current.get("permissions") or []),
                    "compatibility": {},
                    "security": {},
                    "versions": [],
                    "latestVersion": "",
                    "installedVersion": str(current.get("version") or ""),
                    "installed": True,
                    "enabled": current.get("enabled") is True,
                    "updateAvailable": False,
                    "installState": "orphaned",
                    "actionable": False,
                }
            )
        return {
            "schemaVersion": "rag-ime.plugin-catalog.v1",
            "ok": True,
            "catalogVersion": str(document.get("catalogVersion") or ""),
            "distribution": "bundled_and_pi_packages",
            "runtimeAvailable": runtime_available,
            "items": entries,
        }

    def create_package_draft(self, payload: Mapping[str, object]) -> dict[str, object]:
        package_json = payload.get("packageJson")
        files = payload.get("files")
        if not isinstance(package_json, Mapping) or not isinstance(files, Mapping):
            raise ValueError("Pi Package draft requires packageJson and files objects")
        draft_id = str(payload.get("draftId") or "").strip()
        if not draft_id:
            raise ValueError("Pi Package draft requires draftId")
        result = self._call(
            "plugin_create_package",
            {
                "draftId": draft_id,
                "packageJson": dict(package_json),
                "files": dict(files),
            },
        )
        if not isinstance(result, Mapping):
            raise AgentRuntimeError("Pi Runtime Host returned an invalid Pi Package draft")
        raw_package = result.get("package")
        package = dict(raw_package) if isinstance(raw_package, Mapping) else {}
        return {
            "ok": True,
            "draft": {
                "draftId": str(result.get("draftId") or draft_id),
                "sourcePath": str(result.get("sourcePath") or ""),
                "package": {
                    "name": str(package.get("name") or ""),
                    "version": str(package.get("version") or ""),
                },
            },
        }

    def proposals(self) -> dict[str, object]:
        with self._lock:
            self._prune_locked()
            items = [dict(value) for value in self._proposals.values()]
        items.sort(key=lambda item: int(item.get("createdAtMs") or 0), reverse=True)
        return {"ok": True, "items": items}

    def validate(self, payload: Mapping[str, object]) -> dict[str, object]:
        source_path = str(payload.get("sourcePath") or "").strip()
        package_source = str(payload.get("packageSource") or "").strip()
        catalog_id = str(payload.get("catalogId") or "").strip()
        catalog_version = str(payload.get("catalogVersion") or "").strip()
        if sum(bool(value) for value in (source_path, package_source, catalog_id)) != 1:
            raise ValueError(
                "plugin validation requires exactly one sourcePath, packageSource, or catalogId"
            )
        catalog_selection: dict[str, str] = {}
        staged: Path | None = None
        prepared_package_id = ""
        distribution = "review_only"
        if catalog_id:
            runtime_package = self._runtime_catalog_package(catalog_id, catalog_version)
            if runtime_package is not None:
                resolved_version = str(runtime_package.get("version") or "")
                source = str(runtime_package.get("source") or "")
                if not source:
                    raise AgentRuntimeError(
                        "Pi Runtime Host omitted the bundled Package source"
                    )
                validation = self._call("plugin_prepare_package", source)
                if not isinstance(validation, Mapping):
                    raise AgentRuntimeError(
                        "Pi Runtime Host returned an invalid Pi Package validation"
                    )
                prepared_package_id = str(validation.get("preparedPackageId") or "")
                if not prepared_package_id:
                    raise AgentRuntimeError(
                        "Pi Runtime Host did not retain the bundled Pi Package"
                    )
                catalog_selection = {
                    "catalogId": catalog_id,
                    "catalogVersion": resolved_version,
                }
                distribution = "pi_package"
            else:
                source, resolved_version = self._catalog_source(
                    catalog_id, catalog_version
                )
                staged = self._stage_source(source)
                catalog_selection = {
                    "catalogId": catalog_id,
                    "catalogVersion": resolved_version,
                }
                validation = self._call("plugin_validate", str(staged))
                distribution = "bundled"
        elif package_source:
            validation = self._call("plugin_prepare_package", package_source)
            if not isinstance(validation, Mapping):
                raise AgentRuntimeError("Pi Runtime Host returned an invalid Pi Package validation")
            prepared_package_id = str(validation.get("preparedPackageId") or "")
            if not prepared_package_id:
                raise AgentRuntimeError("Pi Runtime Host did not retain the prepared Pi Package")
            distribution = "pi_package"
        elif source_path:
            staged = self._stage_source(Path(source_path))
            validation = self._call("plugin_validate", str(staged))
        if not isinstance(validation, Mapping):
            raise AgentRuntimeError("Pi Runtime Host returned an invalid plugin validation")
        token = secrets.token_urlsafe(32)
        expires_at_ms = _now_ms() + _PREVIEW_TTL_MS
        with self._lock:
            self._tokens[token] = {
                "kind": "validation",
                "sourcePath": str(staged) if staged is not None else "",
                "preparedPackageId": prepared_package_id,
                "digest": str(validation.get("digest") or ""),
                "validation": dict(validation),
                "catalog": catalog_selection,
                # Legacy local extension drafts remain review-only. Native Pi
                # Packages are resolved and retained by Pi, then may reach the
                # same product-owned explicit confirmation gate as bundled items.
                "distribution": distribution,
                "expiresAtMs": expires_at_ms,
            }
            self._prune_locked()
        return {
            "ok": True,
            "validationToken": token,
            "expiresAtMs": expires_at_ms,
            "checks": [
                "manifest",
                "pi-resources" if distribution == "pi_package" else "entry",
                "path-boundary",
                "content-digest",
            ],
            "distribution": distribution,
            "warnings": (
                []
                if distribution in {"bundled", "pi_package"}
                else [
                    "自定义插件只完成源码草稿校验，不会被加载执行；"
                    "需先进入第一方产品目录。"
                ]
            ),
            "extension": self._public_validation(validation),
            "catalog": catalog_selection,
        }

    def preview(self, payload: Mapping[str, object]) -> dict[str, object]:
        action = str(payload.get("action") or "install").strip().lower()
        if action not in {
            "install",
            "update",
            "enable",
            "disable",
            "uninstall",
            "rollback",
        }:
            raise ValueError("unsupported plugin action")
        operation: dict[str, object] = {"action": action}
        if action in {"install", "update"}:
            validation_token = str(payload.get("validationToken") or "").strip()
            validation = self._token(validation_token, kind="validation", consume=False)
            if validation.get("distribution") not in {"bundled", "pi_package"}:
                raise ValueError(
                    "local and Agent-authored plugins are review-only until they "
                    "are added to the signed first-party catalog"
                )
            operation.update(
                {
                    "sourcePath": str(validation["sourcePath"]),
                    "preparedPackageId": str(validation.get("preparedPackageId") or ""),
                    "expectedDigest": str(validation["digest"]),
                    "enable": payload.get("enable") is True,
                    "manifest": dict(validation["validation"]),
                    "catalog": dict(validation.get("catalog") or {}),
                }
            )
            host_preview_payload: dict[str, object] = {
                "expectedDigest": str(validation["digest"]),
                "enable": payload.get("enable") is True,
            }
            prepared_package_id = str(validation.get("preparedPackageId") or "")
            if prepared_package_id:
                host_preview_payload["preparedPackageId"] = prepared_package_id
            else:
                host_preview_payload["sourcePath"] = str(validation["sourcePath"])
            host_preview = self._call(
                "plugin_preview_install", host_preview_payload
            )
            if not isinstance(host_preview, Mapping):
                raise AgentRuntimeError(
                    "Pi Runtime Host returned an invalid plugin install preview"
                )
            host_preview_token = str(host_preview.get("previewToken") or "")
            host_payload_sha256 = str(host_preview.get("payloadSha256") or "")
            if not host_preview_token or not host_payload_sha256:
                raise AgentRuntimeError(
                    "Pi Runtime Host did not return a bound plugin install preview"
                )
            operation.update(
                {
                    "hostPreviewToken": host_preview_token,
                    "hostPayloadSha256": host_payload_sha256,
                }
            )
        else:
            plugin_id = str(payload.get("pluginId") or "").strip()
            if not plugin_id:
                raise ValueError("plugin action requires pluginId")
            operation["pluginId"] = plugin_id
            installed = self._installed_plugin(plugin_id)
            operation.update(
                {
                    "expectedActiveDigest": str(installed.get("digest") or ""),
                    "expectedEnabled": installed.get("enabled") is True,
                    "displayName": str(
                        installed.get("displayName")
                        or installed.get("name")
                        or plugin_id
                    ),
                    "version": str(installed.get("version") or ""),
                    "permissions": [
                        str(value)
                        for value in installed.get("permissions") or []
                        if isinstance(value, str)
                    ],
                }
            )
            if not operation["expectedActiveDigest"]:
                raise ValueError("plugin active state is incomplete")
            if action == "rollback":
                target = installed.get("rollbackTarget")
                if not isinstance(target, Mapping):
                    raise ValueError("plugin rollback is unavailable")
                operation.update(
                    {
                        "expectedActiveDigest": str(installed.get("digest") or ""),
                        "targetDigest": str(target.get("digest") or ""),
                        "targetVersion": str(target.get("version") or ""),
                    }
                )
                if not operation["expectedActiveDigest"] or not operation["targetDigest"]:
                    raise ValueError("plugin rollback state is incomplete")
        payload_sha256 = _payload_digest(operation)
        preview_token = secrets.token_urlsafe(32)
        expires_at_ms = _now_ms() + _PREVIEW_TTL_MS
        with self._lock:
            self._tokens[preview_token] = {
                "kind": "preview",
                "operation": operation,
                "payloadSha256": payload_sha256,
                "expiresAtMs": expires_at_ms,
            }
            proposal_id = f"plugin-proposal:{secrets.token_hex(8)}"
            self._proposals[proposal_id] = {
                "proposalId": proposal_id,
                "previewToken": preview_token,
                "payloadSha256": payload_sha256,
                "expiresAtMs": expires_at_ms,
                "createdAtMs": _now_ms(),
                "summary": self._summary(operation),
            }
            self._prune_locked()
        return {
            "ok": True,
            "previewToken": preview_token,
            "payloadSha256": payload_sha256,
            "requiredConfirm": "apply",
            "expiresAtMs": expires_at_ms,
            "proposalId": proposal_id,
            "summary": self._summary(operation),
        }

    def inspect_preview(self, payload: Mapping[str, object]) -> dict[str, object]:
        preview = self._token(str(payload.get("previewToken") or ""), kind="preview", consume=False)
        if payload.get("payloadSha256") != preview.get("payloadSha256"):
            raise ValueError("plugin preview payload digest does not match")
        operation = preview.get("operation")
        if not isinstance(operation, Mapping):
            raise AgentRuntimeError("plugin preview is invalid")
        return self._summary(operation)

    def apply(self, payload: Mapping[str, object]) -> dict[str, object]:
        if str(payload.get("confirmText") or "").strip().lower() != "apply":
            raise ValueError("plugin change requires confirmText=apply")
        preview_token = str(payload.get("previewToken") or "").strip()
        with self._lock:
            preview = self._token(preview_token, kind="preview", consume=False)
            expected_hash = str(preview.get("payloadSha256") or "")
            if str(payload.get("payloadSha256") or "") != expected_hash:
                raise ValueError("plugin preview payload digest does not match")
            if isinstance(preview.get("result"), Mapping):
                return json.loads(json.dumps(preview["result"]))
            # Consume before the Host call. An uncertain outcome must never be
            # replayed; only a known successful receipt may be returned again.
            self._token(preview_token, kind="preview", consume=True)
        operation = preview.get("operation")
        if not isinstance(operation, Mapping):
            raise AgentRuntimeError("plugin preview is invalid")
        action = str(operation.get("action") or "")
        if action in {"install", "update"}:
            install_payload: dict[str, object] = {
                "expectedDigest": str(operation.get("expectedDigest") or ""),
                "enable": operation.get("enable") is True,
                "previewToken": str(operation.get("hostPreviewToken") or ""),
                "payloadSha256": str(operation.get("hostPayloadSha256") or ""),
                "confirmText": "apply",
            }
            prepared_package_id = str(operation.get("preparedPackageId") or "")
            if prepared_package_id:
                install_payload["preparedPackageId"] = prepared_package_id
            else:
                install_payload["sourcePath"] = str(operation.get("sourcePath") or "")
            plugin = self._call(
                "plugin_install",
                install_payload,
            )
        elif action in {"enable", "disable"}:
            plugin = self._call(
                "plugin_enable",
                str(operation.get("pluginId") or ""),
                enabled=action == "enable",
                expected_active_digest=str(
                    operation.get("expectedActiveDigest") or ""
                ),
                expected_enabled=operation.get("expectedEnabled") is True,
            )
        elif action == "uninstall":
            plugin = self._call(
                "plugin_uninstall",
                str(operation.get("pluginId") or ""),
                expected_active_digest=str(
                    operation.get("expectedActiveDigest") or ""
                ),
                expected_enabled=operation.get("expectedEnabled") is True,
            )
        elif action == "rollback":
            plugin = self._call(
                "plugin_rollback",
                str(operation.get("pluginId") or ""),
                expected_active_digest=str(operation.get("expectedActiveDigest") or ""),
                target_digest=str(operation.get("targetDigest") or ""),
            )
        else:
            raise AgentRuntimeError("plugin preview action is invalid")
        with self._lock:
            for proposal_id, proposal in tuple(self._proposals.items()):
                if proposal.get("previewToken") == preview_token:
                    self._proposals.pop(proposal_id, None)
        plugin_payload = dict(plugin) if isinstance(plugin, Mapping) else {}
        receipt: dict[str, object] = {
            "receiptId": f"plugin:{action}:{secrets.token_hex(8)}",
            "action": action,
            "appliedAtMs": _now_ms(),
            "plugin": _public_plugin_payload(plugin_payload),
            "rollbackAvailable": bool(
                isinstance(plugin, Mapping)
                and len(plugin.get("installedVersions") or []) > 1
            ),
        }
        evidence = _verified_extension_app_evidence(
            plugin_payload,
            package_id=str(plugin_payload.get("id") or operation.get("pluginId") or ""),
            version=str(plugin_payload.get("version") or operation.get("version") or ""),
        )
        if evidence is not None:
            receipt["extensionApp"] = evidence
        result = {
            "ok": True,
            "receipt": receipt,
        }
        with self._lock:
            self._tokens[preview_token] = {
                **preview,
                "expiresAtMs": _now_ms() + _PREVIEW_TTL_MS,
                "result": json.loads(json.dumps(result)),
            }
        return result

    def _call(self, method: str, *args: object, **kwargs: object) -> object:
        runtime = self._runtime_provider()
        target = getattr(runtime, method, None)
        if not callable(target):
            raise AgentRuntimeError("managed plugin lifecycle requires Pi Runtime protocol v2")
        return target(*args, **kwargs)

    def _installed_plugin(self, plugin_id: str) -> dict[str, object]:
        plugins = self._call("plugin_list")
        if not isinstance(plugins, list):
            raise AgentRuntimeError("Pi Runtime Host returned an invalid plugin list")
        plugin = next(
            (
                dict(value)
                for value in plugins
                if isinstance(value, Mapping)
                and str(value.get("id") or "") == plugin_id
            ),
            None,
        )
        if plugin is None:
            raise ValueError("plugin is not installed")
        return plugin

    def _stage_source(self, source: Path) -> Path:
        source = source.expanduser().resolve(strict=True)
        self.inbox_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if _is_within(source, self.inbox_root):
            return source
        if not source.is_dir() or source.is_symlink():
            raise ValueError("plugin source must be a regular directory")
        destination = self.inbox_root / f"import-{int(time.time())}-{secrets.token_hex(6)}"
        temporary = self.inbox_root / f".{destination.name}.tmp"
        file_count = 0
        total_bytes = 0
        temporary.mkdir(mode=0o700)
        try:
            for root, directories, files in os.walk(source, followlinks=False):
                root_path = Path(root)
                for name in directories:
                    child = root_path / name
                    if child.is_symlink():
                        raise ValueError("plugin source must not contain symbolic links")
                    (temporary / child.relative_to(source)).mkdir(
                        parents=True,
                        exist_ok=True,
                        mode=0o700,
                    )
                for name in files:
                    child = root_path / name
                    if child.is_symlink() or not child.is_file():
                        raise ValueError("plugin source must contain regular files only")
                    if child.name != "rag-ime-plugin.json" and child.suffix.lower() not in _SAFE_SUFFIXES:
                        raise ValueError(f"unsupported plugin source file: {child.name}")
                    file_count += 1
                    total_bytes += child.stat().st_size
                    if file_count > _MAX_PLUGIN_FILES or total_bytes > _MAX_PLUGIN_BYTES:
                        raise ValueError("plugin source exceeds the managed file or size limit")
                    target = temporary / child.relative_to(source)
                    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    shutil.copyfile(child, target)
                    target.chmod(0o600)
            if file_count == 0:
                raise ValueError("plugin source is empty")
            temporary.rename(destination)
            return destination
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            raise

    def _catalog_document(self) -> dict[str, object]:
        document = json.loads(self.catalog_path.read_text(encoding="utf-8"))
        if not isinstance(document, dict) or document.get("schemaVersion") != "rag-ime.plugin-catalog.v1":
            raise ValueError("managed plugin catalog is invalid")
        return document

    def _catalog_source(self, catalog_id: str, version: str) -> tuple[Path, str]:
        entry = next(
            (
                value
                for value in self._catalog_document().get("entries") or []
                if isinstance(value, Mapping) and str(value.get("id") or "") == catalog_id
            ),
            None,
        )
        if not isinstance(entry, Mapping):
            raise ValueError("plugin catalog item does not exist")
        source = entry.get("source")
        if not isinstance(source, Mapping) or source.get("kind") != "bundled":
            raise ValueError("plugin catalog item is available for review only")
        versions = [
            value for value in entry.get("versions") or [] if isinstance(value, Mapping)
        ]
        versions.sort(
            key=lambda value: _version_key(str(value.get("version") or "")),
            reverse=True,
        )
        selected = next(
            (
                value
                for value in versions
                if not version or str(value.get("version") or "") == version
            ),
            None,
        )
        if not isinstance(selected, Mapping):
            raise ValueError("plugin catalog version does not exist")
        relative = Path(str(selected.get("sourcePath") or ""))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("plugin catalog source path is invalid")
        root = self.catalog_path.parent.resolve(strict=True)
        resolved = (root / relative).resolve(strict=True)
        if not _is_within(resolved, root):
            raise ValueError("plugin catalog source escapes the product bundle")
        return resolved, str(selected.get("version") or "")

    def _runtime_catalog_package(
        self, catalog_id: str, version: str
    ) -> dict[str, object] | None:
        try:
            packages = self._call("plugin_catalog")
        except AgentRuntimeError:
            return None
        if not isinstance(packages, list):
            raise AgentRuntimeError(
                "Pi Runtime Host returned an invalid Pi Package catalog"
            )
        package = next(
            (
                dict(value)
                for value in packages
                if isinstance(value, Mapping)
                and str(value.get("id") or value.get("name") or "") == catalog_id
            ),
            None,
        )
        if package is None:
            return None
        available_version = str(package.get("version") or "")
        if version and version != available_version:
            raise ValueError("plugin catalog version does not exist")
        return package

    def _token(self, token: str, *, kind: str, consume: bool) -> dict[str, object]:
        if not token:
            raise ValueError(f"plugin {kind} token is required")
        with self._lock:
            self._prune_locked()
            value = self._tokens.pop(token, None) if consume else self._tokens.get(token)
            if value is None or value.get("kind") != kind:
                raise ValueError(f"plugin {kind} token is invalid or expired")
            return dict(value)

    def _prune_locked(self) -> None:
        now = _now_ms()
        for token, value in tuple(self._tokens.items()):
            if int(value.get("expiresAtMs") or 0) <= now:
                self._tokens.pop(token, None)
        for proposal_id, value in tuple(self._proposals.items()):
            if int(value.get("expiresAtMs") or 0) <= now:
                self._proposals.pop(proposal_id, None)

    @staticmethod
    def _public_validation(
        validation: Mapping[str, object],
    ) -> dict[str, object]:
        raw_manifest = validation.get("manifest")
        manifest = dict(raw_manifest) if isinstance(raw_manifest, Mapping) else {}
        result = {
            "id": str(manifest.get("id") or ""),
            "displayName": str(manifest.get("name") or ""),
            "version": str(manifest.get("version") or ""),
            "description": str(manifest.get("description") or ""),
            "entry": str(manifest.get("entry") or ""),
            "permissions": [
                str(item) for item in manifest.get("permissions") or [] if isinstance(item, str)
            ],
            "digest": str(validation.get("digest") or ""),
            "capabilities": [
                str(item)
                for item in validation.get("capabilities") or []
                if isinstance(item, str)
            ],
            "files": [str(item) for item in validation.get("files") or [] if isinstance(item, str)],
            "totalBytes": int(validation.get("totalBytes") or 0),
            "installPreview": dict(validation.get("installPreview") or {}),
            "resources": {
                kind: [
                    str(item)
                    for item in (validation.get("resources") or {}).get(kind, [])
                    if isinstance(item, str)
                ]
                for kind in ("extensions", "skills", "prompts", "themes")
            }
            if isinstance(validation.get("resources"), Mapping)
            else {},
            "source": _public_package_source(validation.get("source")),
        }
        evidence = _extension_app_evidence(
            validation,
            package_id=str(manifest.get("name") or manifest.get("id") or ""),
            version=str(manifest.get("version") or ""),
        )
        if evidence is not None:
            result["extensionApp"] = evidence
        return result

    @staticmethod
    def _summary(operation: Mapping[str, object]) -> dict[str, object]:
        action = str(operation.get("action") or "")
        raw_validation = operation.get("manifest")
        raw_manifest = raw_validation.get("manifest") if isinstance(raw_validation, Mapping) else None
        manifest = dict(raw_manifest) if isinstance(raw_manifest, Mapping) else {}
        resources = raw_validation.get("resources") if isinstance(raw_validation, Mapping) else None
        source = raw_validation.get("source") if isinstance(raw_validation, Mapping) else None
        summary = {
            "action": action,
            "pluginId": str(operation.get("pluginId") or manifest.get("id") or ""),
            "displayName": str(
                manifest.get("name")
                or operation.get("displayName")
                or operation.get("pluginId")
                or ""
            ),
            "version": str(manifest.get("version") or operation.get("version") or ""),
            "targetVersion": str(operation.get("targetVersion") or ""),
            "permissions": list(
                manifest.get("permissions") or operation.get("permissions") or []
            ),
            "resources": dict(resources) if isinstance(resources, Mapping) else {},
            "source": _public_package_source(source),
            "enableAfterInstall": operation.get("enable") is True,
            "expectedEnabled": operation.get("expectedEnabled"),
            "expectedActiveDigest": str(
                operation.get("expectedActiveDigest") or ""
            ),
        }
        evidence = _extension_app_evidence(
            operation.get("manifest") if isinstance(operation.get("manifest"), Mapping) else None,
            package_id=str(operation.get("pluginId") or manifest.get("name") or ""),
            version=str(manifest.get("version") or operation.get("version") or ""),
        )
        if evidence is not None:
            summary["extensionApp"] = evidence
        return summary


def _payload_digest(value: Mapping[str, object]) -> str:
    encoded = json.dumps(
        dict(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _now_ms() -> int:
    return int(time.time() * 1000)


def _version_key(value: str) -> tuple[int, ...]:
    parts = value.split(".")
    if not parts or any(not part.isdigit() for part in parts):
        return ()
    return tuple(int(part) for part in parts)
