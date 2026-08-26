from __future__ import annotations

import hashlib
import json
import secrets
import time
from collections.abc import Mapping
from pathlib import Path
from threading import RLock

from .knowledge_scope import KNOWLEDGE_DOMAINS, SCOPE_KINDS, VISIBILITIES


_PREVIEW_TTL_MS = 10 * 60 * 1000
_SCHEMA = "rag-ime.landing-form.v1"
_KNOWN_APP_IDS = frozenset(
    {
        "project-workbench",
        "agent",
        "memory",
        "knowledge",
        "input-studio",
        "app-center",
        "system-monitor",
        "system-settings",
        "files",
        "browser",
        "terminal",
    }
)
_ACTIONS = frozenset({"install", "activate", "deactivate", "rollback"})


def _now_ms() -> int:
    return int(time.time() * 1000)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class LandingFormService:
    """PAW-owned Landing Form composition: bind persona, knowledge, Dock/App
    visibility, and optional package refs as one switchable unit.

    Lifecycle mirrors AgentExtensionService (validate → preview → apply with
    confirmText=apply → receipt + rollback). Forms do not load Pi Packages
    themselves; they select and bind. Pi remains the package loader (D-011).
    """

    def __init__(
        self,
        *,
        state_root: str | Path,
        catalog_path: str | Path | None = None,
        product_root: str | Path | None = None,
    ) -> None:
        self.state_root = Path(state_root).expanduser().resolve(strict=False)
        self.catalog_path = (
            Path(catalog_path).expanduser().resolve(strict=False)
            if catalog_path is not None
            else Path(__file__).with_name("form_catalog.json")
        )
        self.product_root = (
            Path(product_root).expanduser().resolve(strict=False)
            if product_root is not None
            else Path(__file__).resolve().parent
        )
        self._lock = RLock()
        self._tokens: dict[str, dict[str, object]] = {}
        self.state_root.mkdir(parents=True, exist_ok=True)
        (self.state_root / "installed").mkdir(parents=True, exist_ok=True)
        (self.state_root / "receipts").mkdir(parents=True, exist_ok=True)

    def list(self) -> dict[str, object]:
        with self._lock:
            items = [self._public_installed(item) for item in self._installed_forms()]
            return {
                "schemaVersion": "rag-ime.landing-form-inventory.v1",
                "ok": True,
                "items": items,
            }

    def catalog(self) -> dict[str, object]:
        document = self._catalog_document()
        installed = {
            str(item.get("id") or ""): item for item in self.list()["items"] if isinstance(item, Mapping)
        }
        active = self.active().get("form")
        active_id = str(active.get("id") or "") if isinstance(active, Mapping) else ""
        items: list[dict[str, object]] = []
        for entry in document.get("entries") or []:
            if not isinstance(entry, Mapping):
                continue
            form_id = str(entry.get("id") or "")
            versions = entry.get("versions") if isinstance(entry.get("versions"), list) else []
            latest = versions[0] if versions and isinstance(versions[0], Mapping) else {}
            installed_item = installed.get(form_id)
            install_state = "available"
            if installed_item is not None:
                install_state = "installed"
                if form_id == active_id:
                    install_state = "active"
                installed_version = str(installed_item.get("version") or "")
                latest_version = str(latest.get("version") or "")
                if latest_version and installed_version and latest_version != installed_version:
                    install_state = "update_available"
            items.append(
                {
                    "id": form_id,
                    "displayName": str(entry.get("displayName") or form_id),
                    "description": str(entry.get("description") or ""),
                    "publisher": str(entry.get("publisher") or ""),
                    "source": dict(entry.get("source") or {})
                    if isinstance(entry.get("source"), Mapping)
                    else {},
                    "versions": [
                        {
                            "version": str(version.get("version") or ""),
                            "sourcePath": str(version.get("sourcePath") or ""),
                            "releasedAt": str(version.get("releasedAt") or ""),
                            "notes": str(version.get("notes") or ""),
                        }
                        for version in versions
                        if isinstance(version, Mapping)
                    ],
                    "installState": install_state,
                    "actionable": bool(versions)
                    and str((entry.get("source") or {}).get("kind") or "") == "bundled",
                    "latestVersion": str(latest.get("version") or ""),
                }
            )
        return {
            "schemaVersion": "rag-ime.landing-form-catalog.v1",
            "ok": True,
            "catalogVersion": str(document.get("catalogVersion") or ""),
            "items": items,
        }

    def active(self) -> dict[str, object]:
        with self._lock:
            pointer = self._read_json(self._active_path(), default={})
            form_id = str(pointer.get("formId") or "").strip()
            version = str(pointer.get("version") or "").strip()
            if not form_id or not version:
                return {
                    "schemaVersion": "rag-ime.landing-form-active.v1",
                    "ok": True,
                    "form": None,
                }
            installed = self._installed_form(form_id, version)
            if installed is None:
                return {
                    "schemaVersion": "rag-ime.landing-form-active.v1",
                    "ok": True,
                    "form": None,
                }
            return {
                "schemaVersion": "rag-ime.landing-form-active.v1",
                "ok": True,
                "form": self._public_installed(installed),
                "activatedAtMs": int(pointer.get("activatedAtMs") or 0),
                "receiptId": str(pointer.get("receiptId") or ""),
            }

    def validate(self, payload: Mapping[str, object]) -> dict[str, object]:
        catalog_id = str(payload.get("catalogId") or "").strip()
        source_path = str(payload.get("sourcePath") or "").strip()
        catalog_version = str(payload.get("catalogVersion") or "").strip()
        if bool(catalog_id) == bool(source_path):
            raise ValueError("validate requires exactly one of catalogId or sourcePath")
        catalog_selection: dict[str, object] = {}
        if catalog_id:
            entry, version_entry = self._catalog_version(catalog_id, catalog_version or None)
            source_path = str(version_entry.get("sourcePath") or "")
            catalog_selection = {
                "catalogId": catalog_id,
                "catalogVersion": str(version_entry.get("version") or ""),
                "sourcePath": source_path,
                "displayName": str(entry.get("displayName") or catalog_id),
            }
        resolved = self._resolve_source(source_path)
        manifest = self._load_manifest(resolved)
        digest = _sha256_text(json.dumps(manifest, sort_keys=True, ensure_ascii=False))
        checks = self._validate_manifest(manifest)
        token = secrets.token_urlsafe(18)
        expires = _now_ms() + _PREVIEW_TTL_MS
        with self._lock:
            self._tokens[token] = {
                "kind": "validation",
                "expiresAtMs": expires,
                "sourcePath": str(resolved),
                "digest": digest,
                "manifest": manifest,
                "catalog": catalog_selection,
            }
        return {
            "ok": True,
            "validationToken": token,
            "expiresAtMs": expires,
            "checks": checks,
            "form": self._public_manifest(manifest, digest=digest),
            "catalog": catalog_selection,
        }

    def preview(self, payload: Mapping[str, object]) -> dict[str, object]:
        action = str(payload.get("action") or "").strip().lower()
        if action not in _ACTIONS:
            raise ValueError("unsupported form action")
        operation: dict[str, object] = {"action": action}
        if action in {"install", "activate"}:
            validation_token = str(payload.get("validationToken") or "").strip()
            if action == "install":
                validation = self._token(validation_token, kind="validation", consume=False)
                operation.update(
                    {
                        "sourcePath": str(validation["sourcePath"]),
                        "expectedDigest": str(validation["digest"]),
                        "manifest": dict(validation["manifest"]),
                        "catalog": dict(validation.get("catalog") or {}),
                    }
                )
            else:
                form_id = str(payload.get("formId") or "").strip()
                version = str(payload.get("version") or "").strip()
                if validation_token:
                    validation = self._token(validation_token, kind="validation", consume=False)
                    manifest = dict(validation["manifest"])
                    form_id = str(manifest.get("id") or form_id)
                    version = str(manifest.get("version") or version)
                    operation.update(
                        {
                            "sourcePath": str(validation["sourcePath"]),
                            "expectedDigest": str(validation["digest"]),
                            "manifest": manifest,
                            "catalog": dict(validation.get("catalog") or {}),
                        }
                    )
                else:
                    installed = self._require_installed(form_id, version or None)
                    operation.update(
                        {
                            "formId": form_id,
                            "version": str(installed.get("version") or ""),
                            "manifest": dict(installed.get("manifest") or {}),
                            "expectedDigest": str(installed.get("digest") or ""),
                        }
                    )
        elif action == "deactivate":
            active = self.active().get("form")
            if not isinstance(active, Mapping) or not active.get("id"):
                raise ValueError("no active form to deactivate")
            operation.update(
                {
                    "formId": str(active.get("id") or ""),
                    "version": str(active.get("version") or ""),
                    "expectedDigest": str(active.get("digest") or ""),
                }
            )
        else:  # rollback
            form_id = str(payload.get("formId") or "").strip()
            target = self._rollback_target(form_id)
            if target is None:
                raise ValueError("rollback target is not available")
            operation.update(
                {
                    "formId": form_id,
                    "version": str(target.get("version") or ""),
                    "manifest": dict(target.get("manifest") or {}),
                    "expectedDigest": str(target.get("digest") or ""),
                    "rollbackFromReceiptId": str(target.get("receiptId") or ""),
                }
            )

        payload_body = json.dumps(operation, sort_keys=True, ensure_ascii=False)
        payload_sha256 = _sha256_text(payload_body)
        preview_token = secrets.token_urlsafe(18)
        expires = _now_ms() + _PREVIEW_TTL_MS
        with self._lock:
            self._tokens[preview_token] = {
                "kind": "preview",
                "expiresAtMs": expires,
                "payloadSha256": payload_sha256,
                "operation": operation,
            }
        summary = self._summary_for(action, operation)
        return {
            "ok": True,
            "previewToken": preview_token,
            "payloadSha256": payload_sha256,
            "requiredConfirm": "apply",
            "expiresAtMs": expires,
            "summary": summary,
        }

    def apply(self, payload: Mapping[str, object]) -> dict[str, object]:
        preview_token = str(payload.get("previewToken") or "").strip()
        payload_sha256 = str(payload.get("payloadSha256") or "").strip()
        confirm = str(payload.get("confirmText") or "").strip()
        if confirm != "apply":
            raise ValueError('confirmText must be "apply"')
        preview = self._token(preview_token, kind="preview", consume=True)
        if str(preview.get("payloadSha256") or "") != payload_sha256:
            raise ValueError("preview payload digest mismatch")
        operation = dict(preview.get("operation") or {})
        action = str(operation.get("action") or "")
        with self._lock:
            if action == "install":
                receipt = self._apply_install(operation)
            elif action == "activate":
                receipt = self._apply_activate(operation)
            elif action == "deactivate":
                receipt = self._apply_deactivate(operation)
            elif action == "rollback":
                receipt = self._apply_rollback(operation)
            else:
                raise ValueError("unsupported form action")
        return {"ok": True, "receipt": receipt}

    # --- internals ---------------------------------------------------------

    def _apply_install(self, operation: Mapping[str, object]) -> dict[str, object]:
        manifest = dict(operation.get("manifest") or {})
        form_id = str(manifest.get("id") or "")
        version = str(manifest.get("version") or "")
        digest = str(operation.get("expectedDigest") or "")
        path = self._installed_path(form_id, version)
        path.parent.mkdir(parents=True, exist_ok=True)
        previous_active = self._read_json(self._active_path(), default={})
        record = {
            "id": form_id,
            "version": version,
            "digest": digest,
            "manifest": manifest,
            "installedAtMs": _now_ms(),
            "sourcePath": str(operation.get("sourcePath") or ""),
            "catalog": dict(operation.get("catalog") or {}),
        }
        self._write_json(path, record)
        receipt = self._write_receipt(
            action="install",
            form=self._public_installed(record),
            previous_active=previous_active,
            rollback_available=bool(previous_active.get("formId")),
        )
        # Installing does not auto-activate; caller may preview activate next.
        return receipt

    def _apply_activate(self, operation: Mapping[str, object]) -> dict[str, object]:
        manifest = dict(operation.get("manifest") or {})
        form_id = str(operation.get("formId") or manifest.get("id") or "")
        version = str(operation.get("version") or manifest.get("version") or "")
        if "manifest" in operation and operation.get("sourcePath"):
            # Activate-from-validation: ensure installed first.
            installed_path = self._installed_path(form_id, version)
            if not installed_path.exists():
                self._apply_install(operation)
        installed = self._require_installed(form_id, version)
        previous_active = self._read_json(self._active_path(), default={})
        receipt = self._write_receipt(
            action="activate",
            form=self._public_installed(installed),
            previous_active=previous_active,
            rollback_available=True,
        )
        self._write_json(
            self._active_path(),
            {
                "formId": form_id,
                "version": str(installed.get("version") or ""),
                "activatedAtMs": _now_ms(),
                "receiptId": receipt["receiptId"],
                "previous": previous_active,
            },
        )
        return receipt

    def _apply_deactivate(self, operation: Mapping[str, object]) -> dict[str, object]:
        previous_active = self._read_json(self._active_path(), default={})
        form_id = str(operation.get("formId") or previous_active.get("formId") or "")
        version = str(operation.get("version") or previous_active.get("version") or "")
        installed = self._require_installed(form_id, version)
        receipt = self._write_receipt(
            action="deactivate",
            form=self._public_installed(installed),
            previous_active=previous_active,
            rollback_available=bool(previous_active.get("formId")),
        )
        if self._active_path().exists():
            self._active_path().unlink()
        return receipt

    def _apply_rollback(self, operation: Mapping[str, object]) -> dict[str, object]:
        form_id = str(operation.get("formId") or "")
        version = str(operation.get("version") or "")
        installed = self._require_installed(form_id, version)
        previous_active = self._read_json(self._active_path(), default={})
        receipt = self._write_receipt(
            action="rollback",
            form=self._public_installed(installed),
            previous_active=previous_active,
            rollback_available=False,
        )
        self._write_json(
            self._active_path(),
            {
                "formId": form_id,
                "version": version,
                "activatedAtMs": _now_ms(),
                "receiptId": receipt["receiptId"],
                "previous": previous_active,
            },
        )
        return receipt

    def _write_receipt(
        self,
        *,
        action: str,
        form: Mapping[str, object],
        previous_active: Mapping[str, object],
        rollback_available: bool,
    ) -> dict[str, object]:
        receipt_id = f"form-receipt-{secrets.token_hex(8)}"
        receipt = {
            "receiptId": receipt_id,
            "action": action,
            "appliedAtMs": _now_ms(),
            "form": dict(form),
            "previousActive": {
                "formId": str(previous_active.get("formId") or ""),
                "version": str(previous_active.get("version") or ""),
            },
            "rollbackAvailable": rollback_available,
        }
        self._write_json(self.state_root / "receipts" / f"{receipt_id}.json", receipt)
        return receipt

    def _summary_for(self, action: str, operation: Mapping[str, object]) -> dict[str, object]:
        manifest = operation.get("manifest") if isinstance(operation.get("manifest"), Mapping) else {}
        return {
            "action": action,
            "formId": str(operation.get("formId") or manifest.get("id") or ""),
            "displayName": str(manifest.get("displayName") or operation.get("formId") or ""),
            "version": str(operation.get("version") or manifest.get("version") or ""),
            "dockAppIds": list(manifest.get("dockAppIds") or []) if isinstance(manifest, Mapping) else [],
            "defaultLandingAppId": str(manifest.get("defaultLandingAppId") or "")
            if isinstance(manifest, Mapping)
            else "",
        }

    def _validate_manifest(self, manifest: Mapping[str, object]) -> list[dict[str, object]]:
        checks: list[dict[str, object]] = []

        def check(name: str, ok: bool, detail: str) -> None:
            checks.append({"name": name, "ok": ok, "detail": detail})
            if not ok:
                raise ValueError(f"form validation failed: {name}: {detail}")

        check(
            "schemaVersion",
            str(manifest.get("schemaVersion") or "") == _SCHEMA,
            f"expected {_SCHEMA}",
        )
        form_id = str(manifest.get("id") or "").strip()
        check("id", bool(form_id), "id is required")
        check("version", bool(str(manifest.get("version") or "").strip()), "version is required")
        check(
            "displayName",
            bool(str(manifest.get("displayName") or "").strip()),
            "displayName is required",
        )

        dock = manifest.get("dockAppIds")
        launchpad = manifest.get("launchpadAppIds")
        check("dockAppIds", isinstance(dock, list) and bool(dock), "dockAppIds must be a non-empty list")
        check(
            "launchpadAppIds",
            isinstance(launchpad, list) and bool(launchpad),
            "launchpadAppIds must be a non-empty list",
        )
        assert isinstance(dock, list) and isinstance(launchpad, list)
        unknown_dock = sorted({str(item) for item in dock} - _KNOWN_APP_IDS)
        unknown_launch = sorted({str(item) for item in launchpad} - _KNOWN_APP_IDS)
        check("dockAppIds.known", not unknown_dock, f"unknown apps: {unknown_dock}")
        check("launchpadAppIds.known", not unknown_launch, f"unknown apps: {unknown_launch}")

        landing = str(manifest.get("defaultLandingAppId") or "").strip()
        check(
            "defaultLandingAppId",
            landing in _KNOWN_APP_IDS and landing in {str(item) for item in launchpad},
            "defaultLandingAppId must be a launchpad app",
        )

        persona = manifest.get("defaultPersona")
        check("defaultPersona", isinstance(persona, Mapping), "defaultPersona object required")
        if isinstance(persona, Mapping):
            check(
                "defaultPersona.roleId",
                bool(str(persona.get("roleId") or "").strip()),
                "roleId required",
            )

        bindings = manifest.get("knowledgeBindings")
        check("knowledgeBindings", isinstance(bindings, list), "knowledgeBindings must be a list")
        if isinstance(bindings, list):
            for index, binding in enumerate(bindings):
                if not isinstance(binding, Mapping):
                    check(f"knowledgeBindings[{index}]", False, "must be an object")
                    continue
                domain = str(binding.get("knowledgeDomain") or "")
                scope_kind = str(binding.get("scopeKind") or "")
                visibility = str(binding.get("visibility") or "")
                check(
                    f"knowledgeBindings[{index}].domain",
                    domain in KNOWLEDGE_DOMAINS,
                    f"unsupported domain {domain}",
                )
                check(
                    f"knowledgeBindings[{index}].scopeKind",
                    scope_kind in SCOPE_KINDS,
                    f"unsupported scopeKind {scope_kind}",
                )
                check(
                    f"knowledgeBindings[{index}].visibility",
                    visibility in VISIBILITIES,
                    f"unsupported visibility {visibility}",
                )

        policy = str(manifest.get("policyPreset") or "default").strip()
        check("policyPreset", bool(policy), "policyPreset required")

        skill_refs = manifest.get("skillRefs")
        if skill_refs is not None:
            check("skillRefs", isinstance(skill_refs, list), "skillRefs must be a list when present")
            if isinstance(skill_refs, list):
                for index, ref in enumerate(skill_refs):
                    check(
                        f"skillRefs[{index}]",
                        isinstance(ref, str) and bool(str(ref).strip()),
                        "skill ref must be a non-empty string",
                    )

        bootstrap = manifest.get("bootstrapPrompt")
        if bootstrap is not None:
            check(
                "bootstrapPrompt",
                isinstance(bootstrap, str) and bool(str(bootstrap).strip()),
                "bootstrapPrompt must be a non-empty string when present",
            )
        return checks

    def _load_manifest(self, source_path: Path) -> dict[str, object]:
        manifest_path = source_path / "form.json"
        if not manifest_path.is_file():
            raise ValueError(f"form manifest missing at {manifest_path}")
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("form manifest must be an object")
        return payload

    def _resolve_source(self, source_path: str) -> Path:
        path = Path(source_path)
        if not path.is_absolute():
            path = (self.product_root / source_path).resolve(strict=False)
        else:
            path = path.expanduser().resolve(strict=False)
        if not path.is_dir():
            raise ValueError(f"form source path is not a directory: {path}")
        return path

    def _catalog_document(self) -> dict[str, object]:
        if not self.catalog_path.is_file():
            return {"schemaVersion": "rag-ime.landing-form-catalog.v1", "catalogVersion": "", "entries": []}
        payload = json.loads(self.catalog_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("form catalog must be an object")
        return payload

    def _catalog_version(
        self, catalog_id: str, catalog_version: str | None
    ) -> tuple[dict[str, object], dict[str, object]]:
        document = self._catalog_document()
        for entry in document.get("entries") or []:
            if not isinstance(entry, Mapping):
                continue
            if str(entry.get("id") or "") != catalog_id:
                continue
            versions = entry.get("versions") if isinstance(entry.get("versions"), list) else []
            for version in versions:
                if not isinstance(version, Mapping):
                    continue
                if catalog_version and str(version.get("version") or "") != catalog_version:
                    continue
                return dict(entry), dict(version)
            if versions and isinstance(versions[0], Mapping) and not catalog_version:
                return dict(entry), dict(versions[0])
        raise ValueError(f"unknown form catalog entry: {catalog_id}")

    def _installed_forms(self) -> list[dict[str, object]]:
        root = self.state_root / "installed"
        items: list[dict[str, object]] = []
        if not root.is_dir():
            return items
        for form_dir in sorted(root.iterdir()):
            if not form_dir.is_dir():
                continue
            for version_file in sorted(form_dir.glob("*.json")):
                payload = self._read_json(version_file, default=None)
                if isinstance(payload, dict) and payload.get("id"):
                    items.append(payload)
        return items

    def _installed_form(self, form_id: str, version: str | None) -> dict[str, object] | None:
        if version:
            path = self._installed_path(form_id, version)
            payload = self._read_json(path, default=None)
            return payload if isinstance(payload, dict) else None
        matches = [
            item
            for item in self._installed_forms()
            if str(item.get("id") or "") == form_id
        ]
        if not matches:
            return None
        return sorted(matches, key=lambda item: str(item.get("version") or ""), reverse=True)[0]

    def _require_installed(self, form_id: str, version: str | None) -> dict[str, object]:
        installed = self._installed_form(form_id, version)
        if installed is None:
            raise ValueError(f"form is not installed: {form_id}")
        return installed

    def _rollback_target(self, form_id: str) -> dict[str, object] | None:
        active = self._read_json(self._active_path(), default={})
        previous = active.get("previous") if isinstance(active.get("previous"), Mapping) else {}
        previous_id = str(previous.get("formId") or "").strip()
        previous_version = str(previous.get("version") or "").strip()
        if form_id and previous_id and form_id != previous_id:
            # Explicit rollback of a different form id is not supported in MVP.
            return None
        if not previous_id:
            return None
        installed = self._installed_form(previous_id, previous_version or None)
        if installed is None:
            return None
        return {
            **installed,
            "receiptId": str(active.get("receiptId") or ""),
        }

    def _public_manifest(
        self, manifest: Mapping[str, object], *, digest: str = ""
    ) -> dict[str, object]:
        return {
            "schemaVersion": _SCHEMA,
            "id": str(manifest.get("id") or ""),
            "displayName": str(manifest.get("displayName") or ""),
            "version": str(manifest.get("version") or ""),
            "description": str(manifest.get("description") or ""),
            "tagline": str(manifest.get("tagline") or ""),
            "dockAppIds": [str(item) for item in manifest.get("dockAppIds") or []],
            "launchpadAppIds": [str(item) for item in manifest.get("launchpadAppIds") or []],
            "defaultLandingAppId": str(manifest.get("defaultLandingAppId") or ""),
            "defaultPersona": dict(manifest.get("defaultPersona") or {})
            if isinstance(manifest.get("defaultPersona"), Mapping)
            else {},
            "knowledgeBindings": [
                dict(item)
                for item in (manifest.get("knowledgeBindings") or [])
                if isinstance(item, Mapping)
            ],
            "policyPreset": str(manifest.get("policyPreset") or "default"),
            "skillRefs": [str(item) for item in manifest.get("skillRefs") or [] if str(item).strip()],
            "bootstrapPrompt": str(manifest.get("bootstrapPrompt") or ""),
            "packageRefs": [
                dict(item)
                for item in (manifest.get("packageRefs") or [])
                if isinstance(item, Mapping)
            ],
            "digest": digest,
        }

    def _public_installed(self, installed: Mapping[str, object]) -> dict[str, object]:
        manifest = installed.get("manifest") if isinstance(installed.get("manifest"), Mapping) else installed
        public = self._public_manifest(
            manifest if isinstance(manifest, Mapping) else {},
            digest=str(installed.get("digest") or ""),
        )
        public["installedAtMs"] = int(installed.get("installedAtMs") or 0)
        public["installed"] = True
        active = self._read_json(self._active_path(), default={})
        public["active"] = (
            str(active.get("formId") or "") == public["id"]
            and str(active.get("version") or "") == public["version"]
        )
        return public

    def _installed_path(self, form_id: str, version: str) -> Path:
        return self.state_root / "installed" / form_id / f"{version}.json"

    def _active_path(self) -> Path:
        return self.state_root / "active.json"

    def _token(self, token: str, *, kind: str, consume: bool) -> dict[str, object]:
        with self._lock:
            record = self._tokens.get(token)
            if not isinstance(record, dict) or record.get("kind") != kind:
                raise ValueError(f"unknown or expired {kind} token")
            if int(record.get("expiresAtMs") or 0) < _now_ms():
                self._tokens.pop(token, None)
                raise ValueError(f"expired {kind} token")
            if consume:
                self._tokens.pop(token, None)
            return dict(record)

    @staticmethod
    def _read_json(path: Path, *, default: object) -> object:
        if not path.is_file():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return default

    @staticmethod
    def _write_json(path: Path, payload: Mapping[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
