from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


CONTROL_MARKER_SCHEMA = "rag-ime.control-build-marker.v1"
VOICE_MARKER_SCHEMA = "rag-ime.voice-build-marker.v1"
COMPONENT_MARKER_SCHEMA = "rag-ime.component-install-marker.v1"
SQUIRREL_MARKER_SCHEMA = "rag-ime.squirrel-build-marker.v2"
PI_POINTER_SCHEMA = "rag-ime.pi-runtime-pointer.v1"
PI_MANIFEST_SCHEMA = "rag-ime.pi-runtime-manifest.v1"


def load_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def sha256_file(path: Path) -> str | None:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def assistant_overlay_sha256(repo_root: Path) -> str | None:
    names = (
        "RagImeAssistantSurfaceState.swift",
        "RagImeSuggestionCardView.swift",
        "RagImeSuggestionRowView.swift",
        "RagImeNonActivatingPanel.swift",
        "RagImeAssistantPanelController.swift",
    )
    digest = hashlib.sha256()
    for name in names:
        path = repo_root / "squirrel-patches" / "sources" / name
        try:
            content = path.read_bytes()
        except OSError:
            return None
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(content)
        digest.update(b"\0")
    return digest.hexdigest()


def audit_installed_product(
    *,
    repo_root: Path,
    home: Path | None = None,
    app_support: Path | None = None,
    expected_commit: str = "",
    required_components: Iterable[str] = ("control", "sidecar", "squirrel"),
    verify_pi_files: bool = True,
) -> dict[str, Any]:
    home = (home or Path.home()).expanduser().resolve()
    app_support = (
        app_support or home / "Library" / "Application Support" / "RagIme"
    ).expanduser().resolve()
    repo_root = repo_root.expanduser().resolve()
    required = frozenset(required_components)

    marker_paths = {
        "control": home
        / "Applications"
        / "RagImeControl.app"
        / "Contents"
        / "Resources"
        / "rag-ime-control-web-build-marker.json",
        "voice": home
        / "Applications"
        / "RagImeVoice.app"
        / "Contents"
        / "Resources"
        / "rag-ime-voice-build-marker.json",
        "sidecar": app_support / "app" / "rag-ime-install-marker.json",
        "mlxPredictor": app_support
        / "components"
        / "mlx-predictor"
        / "rag-ime-install-marker.json",
        "memoryBookMaintenance": app_support
        / "components"
        / "memory-book-maintenance"
        / "rag-ime-install-marker.json",
    }
    markers = {name: load_json(path) for name, path in marker_paths.items()}
    expected = (
        expected_commit.strip()
        or _text(_mapping(markers.get("control")).get("gitCommit"))
        or _text(_mapping(markers.get("sidecar")).get("sourceCommit"))
    )

    components: dict[str, dict[str, Any]] = {}
    components["control"] = _commit_component(
        component_id="control",
        marker_path=marker_paths["control"],
        marker=markers["control"],
        schema=CONTROL_MARKER_SCHEMA,
        commit_key="gitCommit",
        expected_commit=expected,
        required="control" in required,
    )
    components["voice"] = _commit_component(
        component_id="voice",
        marker_path=marker_paths["voice"],
        marker=markers["voice"],
        schema=VOICE_MARKER_SCHEMA,
        commit_key="gitCommit",
        expected_commit=expected,
        required="voice" in required,
        capability_keys=(
            "finalSecondPass",
            "semanticSmoothing",
            "fullResultReplacement",
        ),
    )
    for component_id, marker_component in (
        ("sidecar", "sidecar-runtime"),
        ("mlxPredictor", "mlx-predictor"),
        ("memoryBookMaintenance", "memory-book-maintenance"),
    ):
        components[component_id] = _commit_component(
            component_id=component_id,
            marker_path=marker_paths[component_id],
            marker=markers[component_id],
            schema=COMPONENT_MARKER_SCHEMA,
            commit_key="sourceCommit",
            expected_commit=expected,
            required=component_id in required,
            expected_marker_component=marker_component,
        )

    components["squirrel"] = _squirrel_component(
        repo_root=repo_root,
        marker_path=home
        / "Library"
        / "Input Methods"
        / "Squirrel.app"
        / "Contents"
        / "Resources"
        / "rag-ime-build-marker.json",
        required="squirrel" in required,
    )
    components["piRuntime"] = _pi_component(
        runtime_root=app_support / "PiRuntime",
        required="piRuntime" in required,
        verify_files=verify_pi_files,
    )

    issues = [
        {"component": name, "code": item["code"], "detail": item["detail"]}
        for name, item in components.items()
        if not item["ok"]
    ]
    return {
        "schemaVersion": "rag-ime.installed-product-audit.v1",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "ok": not issues and bool(expected),
        "expectedCommit": expected,
        "repoRoot": str(repo_root),
        "appSupport": str(app_support),
        "components": components,
        "issues": issues,
        "summary": (
            "All installed product components are current and provenance-aligned."
            if not issues and expected
            else issues[0]["detail"]
            if issues
            else "No canonical installed product commit was found."
        ),
    }


def _commit_component(
    *,
    component_id: str,
    marker_path: Path,
    marker: Mapping[str, Any] | None,
    schema: str,
    commit_key: str,
    expected_commit: str,
    required: bool,
    expected_marker_component: str = "",
    capability_keys: tuple[str, ...] = (),
) -> dict[str, Any]:
    marker = _mapping(marker)
    installed = bool(marker)
    installed_commit = _text(marker.get(commit_key))
    schema_valid = marker.get("schemaVersion") == schema
    component_valid = not expected_marker_component or marker.get("component") == expected_marker_component
    clean = not _truthy(marker.get("gitDirty")) and not _truthy(marker.get("sourceDirty"))
    capabilities = _mapping(marker.get("capabilities"))
    capabilities_valid = all(capabilities.get(key) is True for key in capability_keys)
    current = bool(expected_commit and installed_commit == expected_commit)

    if not installed:
        ok = not required
        code = "not_installed"
        detail = f"{component_id} is not installed" + (" but is required." if required else ".")
    elif not schema_valid or not component_valid:
        ok = False
        code = "invalid_marker"
        detail = f"{component_id} has an invalid or overwritten installation marker."
    elif not clean:
        ok = False
        code = "dirty_build"
        detail = f"{component_id} was installed from an uncommitted source tree."
    elif capability_keys and not capabilities_valid:
        ok = False
        code = "incomplete_capabilities"
        detail = f"{component_id} does not declare the complete runtime capability contract."
    elif not expected_commit:
        ok = False
        code = "missing_expected_commit"
        detail = f"{component_id} cannot be compared because the canonical product commit is missing."
    elif not current:
        ok = False
        code = "commit_mismatch"
        detail = f"{component_id} was installed from {installed_commit or 'an unknown commit'}, expected {expected_commit}."
    else:
        ok = True
        code = "ready"
        detail = f"{component_id} matches the canonical installed product commit."

    return {
        "id": component_id,
        "ok": ok,
        "code": code,
        "detail": detail,
        "required": required,
        "installed": installed,
        "current": current,
        "cleanSource": clean if installed else None,
        "markerPath": str(marker_path),
        "installedCommit": installed_commit,
        "expectedCommit": expected_commit,
        "marker": dict(marker),
    }


def _squirrel_component(*, repo_root: Path, marker_path: Path, required: bool) -> dict[str, Any]:
    marker = _mapping(load_json(marker_path))
    installed = bool(marker)
    current_patch = sha256_file(repo_root / "squirrel-patches" / "0001-add-rag-ime-sidecar.patch")
    current_overlay = assistant_overlay_sha256(repo_root)
    current = bool(
        installed
        and marker.get("schemaVersion") == SQUIRREL_MARKER_SCHEMA
        and current_patch
        and marker.get("patchSha256") == current_patch
        and current_overlay
        and marker.get("overlaySha256") == current_overlay
    )
    if not installed:
        ok = not required
        code = "not_installed"
        detail = "squirrel is not installed" + (" but is required." if required else ".")
    elif marker.get("schemaVersion") != SQUIRREL_MARKER_SCHEMA:
        ok = False
        code = "invalid_marker"
        detail = "squirrel has an old or invalid installation marker."
    elif not current_patch or not current_overlay:
        ok = False
        code = "source_unavailable"
        detail = "squirrel source patch or overlay files are unavailable for comparison."
    elif not current:
        ok = False
        code = "source_mismatch"
        detail = "squirrel was built from a different patch or assistant overlay than this product source."
    elif _truthy(marker.get("gitDirty")):
        ok = False
        code = "dirty_build"
        detail = "squirrel was installed from an uncommitted source tree."
    else:
        ok = True
        code = "ready"
        detail = "squirrel matches the current product patch and assistant overlay."
    return {
        "id": "squirrel",
        "ok": ok,
        "code": code,
        "detail": detail,
        "required": required,
        "installed": installed,
        "current": current,
        "markerPath": str(marker_path),
        "currentPatchSha256": current_patch,
        "currentOverlaySha256": current_overlay,
        "marker": dict(marker),
    }


def _pi_component(*, runtime_root: Path, required: bool, verify_files: bool) -> dict[str, Any]:
    pointer_path = runtime_root / "current.json"
    pointer = _mapping(load_json(pointer_path))
    version = _text(pointer.get("version"))
    manifest_path = runtime_root / version / "manifest.json" if version else runtime_root / "missing-manifest.json"
    manifest = _mapping(load_json(manifest_path))
    manifest_hash = sha256_file(manifest_path)
    pointer_valid = pointer.get("schemaVersion") == PI_POINTER_SCHEMA
    manifest_valid = bool(
        manifest.get("schemaVersion") == PI_MANIFEST_SCHEMA
        and manifest.get("runtimeVersion") == version
        and str(manifest.get("runtimeProtocolVersion")) == "2"
        and manifest_hash
        and manifest_hash == pointer.get("manifestSha256")
    )
    files_valid = _pi_files_valid(runtime_root / version, manifest) if verify_files and manifest_valid else manifest_valid
    installed = bool(pointer)
    if not installed:
        ok = not required
        code = "not_installed"
        detail = "piRuntime is not installed" + (" but is required." if required else ".")
    elif not pointer_valid or not manifest_valid:
        ok = False
        code = "invalid_manifest"
        detail = "piRuntime pointer and manifest do not describe the same verified protocol-v2 payload."
    elif not files_valid:
        ok = False
        code = "payload_mismatch"
        detail = "piRuntime payload files no longer match the activated manifest."
    else:
        ok = True
        code = "ready"
        detail = "piRuntime pointer, manifest, and payload are verified."
    return {
        "id": "piRuntime",
        "ok": ok,
        "code": code,
        "detail": detail,
        "required": required,
        "installed": installed,
        "current": files_valid,
        "pointerPath": str(pointer_path),
        "manifestPath": str(manifest_path),
        "runtimeVersion": version,
        "sourceCommit": _text(_mapping(manifest.get("source")).get("commit")),
        "marker": dict(pointer),
    }


def _pi_files_valid(runtime_dir: Path, manifest: Mapping[str, Any]) -> bool:
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        return False
    for item in files:
        if not isinstance(item, Mapping):
            return False
        relative = Path(_text(item.get("path")))
        if not relative.parts or relative.is_absolute() or ".." in relative.parts:
            return False
        if sha256_file(runtime_dir / relative) != _text(item.get("sha256")):
            return False
    return True


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _text(value: object) -> str:
    return str(value).strip() if value is not None else ""


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return _text(value).lower() in {"1", "true", "yes", "on"}
