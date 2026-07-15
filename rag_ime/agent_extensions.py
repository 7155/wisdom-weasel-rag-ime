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
    ) -> None:
        self._runtime_provider = runtime_provider
        self.inbox_root = Path(inbox_root).expanduser().resolve(strict=False)
        self._lock = RLock()
        self._tokens: dict[str, dict[str, object]] = {}
        self._proposals: dict[str, dict[str, object]] = {}

    def list(self) -> dict[str, object]:
        plugins = self._call("plugin_list")
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
                    "rollbackAvailable": len(versions) > 1,
                    "updateAvailable": False,
                    "permissions": [
                        str(item)
                        for item in value.get("permissions") or []
                        if isinstance(item, str)
                    ],
                    "installedVersions": versions,
                }
            )
        return {"ok": True, "items": items}

    def create_draft(self, payload: Mapping[str, object]) -> dict[str, object]:
        manifest = payload.get("manifest")
        files = payload.get("files")
        if not isinstance(manifest, Mapping) or not isinstance(files, Mapping):
            raise ValueError("plugin draft requires manifest and files objects")
        draft_id = str(payload.get("draftId") or "").strip()
        if not draft_id:
            raise ValueError("plugin draft requires draftId")
        result = self._call(
            "plugin_create",
            {"draftId": draft_id, "manifest": dict(manifest), "files": dict(files)},
        )
        if not isinstance(result, Mapping):
            raise AgentRuntimeError("Pi Runtime Host returned an invalid plugin draft")
        return {"ok": True, "draft": self._public_validation(result, include_source=True)}

    def proposals(self) -> dict[str, object]:
        with self._lock:
            self._prune_locked()
            items = [dict(value) for value in self._proposals.values()]
        items.sort(key=lambda item: int(item.get("createdAtMs") or 0), reverse=True)
        return {"ok": True, "items": items}

    def validate(self, payload: Mapping[str, object]) -> dict[str, object]:
        source_path = str(payload.get("sourcePath") or "").strip()
        if not source_path:
            raise ValueError("plugin validation requires sourcePath")
        staged = self._stage_source(Path(source_path))
        validation = self._call("plugin_validate", str(staged))
        if not isinstance(validation, Mapping):
            raise AgentRuntimeError("Pi Runtime Host returned an invalid plugin validation")
        token = secrets.token_urlsafe(32)
        expires_at_ms = _now_ms() + _PREVIEW_TTL_MS
        with self._lock:
            self._tokens[token] = {
                "kind": "validation",
                "sourcePath": str(staged),
                "digest": str(validation.get("digest") or ""),
                "validation": dict(validation),
                "expiresAtMs": expires_at_ms,
            }
            self._prune_locked()
        return {
            "ok": True,
            "validationToken": token,
            "expiresAtMs": expires_at_ms,
            "checks": ["manifest", "entry", "path-boundary", "size-limit", "content-digest"],
            "warnings": [],
            "extension": self._public_validation(validation),
        }

    def preview(self, payload: Mapping[str, object]) -> dict[str, object]:
        action = str(payload.get("action") or "install").strip().lower()
        if action not in {"install", "enable", "disable", "rollback"}:
            raise ValueError("unsupported plugin action")
        operation: dict[str, object] = {"action": action}
        if action == "install":
            validation_token = str(payload.get("validationToken") or "").strip()
            validation = self._token(validation_token, kind="validation", consume=False)
            operation.update(
                {
                    "sourcePath": str(validation["sourcePath"]),
                    "expectedDigest": str(validation["digest"]),
                    "enable": payload.get("enable") is True,
                    "manifest": dict(validation["validation"]),
                }
            )
        else:
            plugin_id = str(payload.get("pluginId") or "").strip()
            if not plugin_id:
                raise ValueError("plugin action requires pluginId")
            operation["pluginId"] = plugin_id
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
        if action == "install":
            plugin = self._call(
                "plugin_install",
                {
                    "sourcePath": str(operation.get("sourcePath") or ""),
                    "expectedDigest": str(operation.get("expectedDigest") or ""),
                    "enable": operation.get("enable") is True,
                },
            )
        elif action in {"enable", "disable"}:
            plugin = self._call(
                "plugin_enable",
                str(operation.get("pluginId") or ""),
                enabled=action == "enable",
            )
        elif action == "rollback":
            plugin = self._call("plugin_rollback", str(operation.get("pluginId") or ""))
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
        return {
            "action": action,
            "pluginId": str(operation.get("pluginId") or manifest.get("id") or ""),
            "displayName": str(manifest.get("name") or operation.get("pluginId") or ""),
            "version": str(manifest.get("version") or ""),
            "permissions": list(manifest.get("permissions") or []),
            "enableAfterInstall": operation.get("enable") is True,
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
