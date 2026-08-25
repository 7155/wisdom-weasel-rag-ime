from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from threading import RLock

from .agent_runtime_driver import AgentRuntimeDriver, AgentRuntimeError


_MAX_PLUGIN_FILES = 256
_MAX_PLUGIN_BYTES = 5 * 1024 * 1024
_SAFE_SUFFIXES = {".ts", ".js", ".mjs", ".json", ".md"}
_PREVIEW_TTL_MS = 10 * 60 * 1000


class AgentExtensionService:
    """Product-owned approval boundary around the managed Pi plugin store."""

    def __init__(
        self,
        *,
        runtime_provider: Callable[[], AgentRuntimeDriver],
        inbox_root: str | Path,
        catalog_path: str | Path | None = None,
    ) -> None:
        self._runtime_provider = runtime_provider
        self.inbox_root = Path(inbox_root).expanduser().resolve(strict=False)
        self.catalog_path = (
            Path(catalog_path).expanduser().resolve(strict=False)
            if catalog_path is not None
            else Path(__file__).with_name("plugin_catalog.json")
        )
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
            versions = raw_versions if isinstance(raw_versions, list) else []
            items.append(
                {
                    "id": str(value.get("id") or ""),
                    "displayName": str(value.get("name") or value.get("id") or "Plugin"),
                    "version": str(value.get("version") or ""),
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
                    "source": (
                        dict(value["source"])
                        if isinstance(value.get("source"), Mapping)
                        else {}
                    ),
                    "installedVersions": versions,
                    "rollbackTarget": (
                        dict(value["rollbackTarget"])
                        if isinstance(value.get("rollbackTarget"), Mapping)
                        else None
                    ),
                }
            )
        return {
            "schemaVersion": "rag-ime.plugin-inventory.v1",
            "ok": True,
            "runtimeAvailable": True,
            "items": items,
        }

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
            entries.append(
                {
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
                    "capabilities": [
                        str(value)
                        for value in package.get("capabilities") or []
                        if isinstance(value, str)
                    ],
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
            )
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
        return {"ok": True, "draft": dict(result)}

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

    def apply(self, payload: Mapping[str, object]) -> dict[str, object]:
        if str(payload.get("confirmText") or "").strip().lower() != "apply":
            raise ValueError("plugin change requires confirmText=apply")
        preview_token = str(payload.get("previewToken") or "").strip()
        preview = self._token(preview_token, kind="preview", consume=True)
        expected_hash = str(preview.get("payloadSha256") or "")
        if str(payload.get("payloadSha256") or "") != expected_hash:
            raise ValueError("plugin preview payload digest does not match")
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
        return {
            "ok": True,
            "receipt": {
                "receiptId": f"plugin:{action}:{secrets.token_hex(8)}",
                "action": action,
                "appliedAtMs": _now_ms(),
                "plugin": dict(plugin) if isinstance(plugin, Mapping) else {},
                "rollbackAvailable": bool(
                    isinstance(plugin, Mapping)
                    and len(plugin.get("installedVersions") or []) > 1
                ),
            },
        }

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
        *,
        include_source: bool = False,
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
            "source": dict(validation.get("source") or {})
            if isinstance(validation.get("source"), Mapping)
            else {},
        }
        if include_source:
            result["sourcePath"] = str(validation.get("sourcePath") or "")
        return result

    @staticmethod
    def _summary(operation: Mapping[str, object]) -> dict[str, object]:
        action = str(operation.get("action") or "")
        raw_validation = operation.get("manifest")
        raw_manifest = raw_validation.get("manifest") if isinstance(raw_validation, Mapping) else None
        manifest = dict(raw_manifest) if isinstance(raw_manifest, Mapping) else {}
        resources = raw_validation.get("resources") if isinstance(raw_validation, Mapping) else None
        source = raw_validation.get("source") if isinstance(raw_validation, Mapping) else None
        return {
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
            "source": dict(source) if isinstance(source, Mapping) else {},
            "enableAfterInstall": operation.get("enable") is True,
            "expectedEnabled": operation.get("expectedEnabled"),
            "expectedActiveDigest": str(
                operation.get("expectedActiveDigest") or ""
            ),
        }


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
