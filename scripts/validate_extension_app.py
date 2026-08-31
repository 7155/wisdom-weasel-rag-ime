#!/usr/bin/env python3
"""Validate one source-isolated PAWOS Extension App candidate.

This is a source gate, not an install command.  It validates the PAWOS App
manifest, the co-versioned Pi Package and Skill, then resolves the declared
vertical suite through PAW's existing registry.  Fixture data remains owned by
``examples/vertical_agents`` and is never copied into an Extension App.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
DEFAULT_APP = ROOT / "control-center-web" / "extension-apps" / "zhanggui-wenshu"

from rag_ime.agent_extensions import (
    extension_app_binding_capability,
    extension_app_binding_sha256,
)  # noqa: E402

_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_SEMVER = re.compile(
    r"^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
_PACKAGE_NAME = re.compile(
    r"^(?:@[a-z0-9][a-z0-9._~-]{0,63}/)?[a-z0-9][a-z0-9._~-]{0,63}$"
)
_RESOURCE_KEYS = ("extensions", "skills", "prompts", "themes")
_PRESENTATIONS = frozenset(
    {"workspace", "conversation", "library", "studio", "utility"}
)
_ACCENTS = frozenset(
    {"cyan", "blue", "violet", "amber", "green", "rose", "slate"}
)
_ICON_SYMBOLS = frozenset({"analytics", "assistant", "document", "commerce"})
_SANDBOX_DEFAULTS = frozenset({"required", "optional", "disabled"})
_SANDBOX_FIELDS = frozenset({"default", "connectorPackageId", "policyId"})
_DISALLOWED_FIXTURE_PATH_PARTS = frozenset(
    {"vertical-agent.json", "examples", "vertical_agents"}
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_PACKAGE_SEGMENT = re.compile(r"^(?:[a-z0-9][a-z0-9.-]*|SKILL\.md)$")
_MAX_NATIVE_PACKAGE_FILES = 1024
_MAX_NATIVE_PACKAGE_BYTES = 20 * 1024 * 1024


class ExtensionAppValidationError(ValueError):
    """The source candidate does not satisfy the Extension App contract."""


def _object_without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate object key {key!r}")
        result[key] = value
    return result


def _read_json_object(path: Path, *, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ExtensionAppValidationError(
            f"{label} must be a regular file: {path}"
        )
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_object_without_duplicate_keys,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        raise ExtensionAppValidationError(
            f"{label} is invalid at {path}: {error}"
        ) from error
    if not isinstance(value, dict):
        raise ExtensionAppValidationError(f"{label} must be an object: {path}")
    return value


def _assert_real_directory(path: Path, *, label: str) -> None:
    if path.is_symlink() or not path.is_dir():
        raise ExtensionAppValidationError(
            f"{label} must be a real directory: {path}"
        )


def _assert_no_symlinks(path: Path, *, label: str) -> None:
    _assert_real_directory(path, label=label)
    for child in path.rglob("*"):
        if child.is_symlink():
            raise ExtensionAppValidationError(
                f"{label} contains a symlink: {child}"
            )


def _assert_native_digest_compatible_tree(path: Path) -> None:
    file_count = 0
    total_bytes = 0
    for directory, directories, files in os.walk(path, followlinks=False):
        names = [*directories, *files]
        if len({name.casefold() for name in names}) != len(names):
            raise ExtensionAppValidationError(
                f"Extension App Pi Package has a case-colliding path in {directory}"
            )
        for name in names:
            if not _PACKAGE_SEGMENT.fullmatch(name):
                raise ExtensionAppValidationError(
                    "Extension App Pi Package paths must use lowercase ASCII, "
                    f"digits, dots, or hyphens (except SKILL.md): {name!r}"
                )
        for name in files:
            child = Path(directory) / name
            file_count += 1
            total_bytes += child.stat().st_size
            if (
                file_count > _MAX_NATIVE_PACKAGE_FILES
                or total_bytes > _MAX_NATIVE_PACKAGE_BYTES
            ):
                raise ExtensionAppValidationError(
                    "Extension App Pi Package exceeds Native Runtime limits"
                )


def _required_text(payload: dict[str, Any], key: str, *, label: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ExtensionAppValidationError(f"{label}.{key} must be non-empty text")
    return value.strip()


def _validate_sandbox_contract(app_manifest: dict[str, Any]) -> dict[str, str] | None:
    value = app_manifest.get("sandbox")
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != _SANDBOX_FIELDS:
        raise ExtensionAppValidationError(
            "Extension App manifest sandbox must contain default, connectorPackageId, and policyId only"
        )
    if value.get("default") not in _SANDBOX_DEFAULTS:
        raise ExtensionAppValidationError("Extension App manifest sandbox default is invalid")
    if value.get("connectorPackageId") != "vertical-agent-sandbox":
        raise ExtensionAppValidationError("Extension App manifest sandbox connector is invalid")
    if value.get("policyId") != "vertical-readonly-v1":
        raise ExtensionAppValidationError("Extension App manifest sandbox policy is invalid")
    return {key: str(value[key]) for key in sorted(_SANDBOX_FIELDS)}


def _resource_prefix(raw_path: str) -> PurePosixPath:
    if "\\" in raw_path:
        raise ExtensionAppValidationError(
            f"Pi resource path must use POSIX separators: {raw_path!r}"
        )
    path = raw_path[1:] if raw_path.startswith("!") else raw_path
    if not path or path.startswith("/"):
        raise ExtensionAppValidationError(
            f"Pi resource path must be relative: {raw_path!r}"
        )
    relative = PurePosixPath(path)
    if relative.is_absolute() or ".." in relative.parts:
        raise ExtensionAppValidationError(
            f"Pi resource path escapes its package: {raw_path!r}"
        )
    prefix: list[str] = []
    for part in relative.parts:
        if part in ("", "."):
            continue
        if any(character in part for character in "*?[{"):
            break
        prefix.append(part)
    return PurePosixPath(*prefix)


def _validate_pi_package(package_root: Path, app_manifest: dict[str, Any]) -> dict[str, Any]:
    _assert_no_symlinks(package_root, label="Extension App pi-package")
    _assert_native_digest_compatible_tree(package_root)
    package_manifest = _read_json_object(
        package_root / "package.json",
        label="Extension App Pi Package manifest",
    )
    package_name = _required_text(
        package_manifest,
        "name",
        label="Extension App Pi Package manifest",
    )
    if not _PACKAGE_NAME.fullmatch(package_name):
        raise ExtensionAppValidationError(
            f"Extension App Pi Package name is invalid: {package_name!r}"
        )
    package_version = _required_text(
        package_manifest,
        "version",
        label="Extension App Pi Package manifest",
    )
    if not _SEMVER.fullmatch(package_version):
        raise ExtensionAppValidationError(
            f"Extension App Pi Package version is invalid: {package_version!r}"
        )
    app_package_id = _required_text(app_manifest, "packageId", label="Extension App manifest")
    app_version = _required_text(app_manifest, "version", label="Extension App manifest")
    if package_name != app_package_id:
        raise ExtensionAppValidationError(
            f"Pi Package name {package_name!r} does not match App packageId {app_package_id!r}"
        )
    if package_version != app_version:
        raise ExtensionAppValidationError(
            f"Pi Package version {package_version!r} does not match App version {app_version!r}"
        )

    pi_manifest = package_manifest.get("pi")
    if not isinstance(pi_manifest, dict):
        raise ExtensionAppValidationError("Pi Package manifest requires a pi object")
    declared_resource_count = 0
    for key in _RESOURCE_KEYS:
        if key not in pi_manifest:
            continue
        paths = pi_manifest[key]
        if not isinstance(paths, list) or not paths:
            raise ExtensionAppValidationError(
                f"Pi Package pi.{key} must be a non-empty string array"
            )
        for raw_path in paths:
            if not isinstance(raw_path, str) or not raw_path.strip():
                raise ExtensionAppValidationError(
                    f"Pi Package pi.{key} contains an invalid path"
                )
            prefix = _resource_prefix(raw_path.strip())
            if raw_path.strip().startswith("!"):
                continue
            if not package_root.joinpath(*prefix.parts).exists():
                raise ExtensionAppValidationError(
                    f"Pi Package pi.{key} references a missing path: {raw_path!r}"
                )
            declared_resource_count += 1
    if declared_resource_count == 0:
        raise ExtensionAppValidationError("Pi Package manifest declares no Pi resources")

    skill_ref = _required_text(app_manifest, "skillRef", label="Extension App manifest")
    skill_path = package_root / "skills" / skill_ref / "SKILL.md"
    if skill_path.is_symlink() or not skill_path.is_file():
        raise ExtensionAppValidationError(
            f"App skillRef does not resolve inside pi-package: {skill_ref!r}"
        )
    skills = pi_manifest.get("skills")
    if not isinstance(skills, list) or not any(
        isinstance(path, str)
        and not path.startswith("!")
        and _resource_prefix(path.strip()).parts[:1] == ("skills",)
        for path in skills
    ):
        raise ExtensionAppValidationError(
            "Pi Package pi.skills must expose the App skill directory"
        )
    skill_sha256 = hashlib.sha256(skill_path.read_bytes()).hexdigest()
    if app_manifest.get("skillSha256") != skill_sha256:
        raise ExtensionAppValidationError(
            "Extension App manifest skillSha256 does not match its Package Skill"
        )
    binding_sha256 = app_manifest.get("bindingSha256")
    if not isinstance(binding_sha256, str) or not _SHA256.fullmatch(binding_sha256):
        raise ExtensionAppValidationError(
            "Extension App manifest bindingSha256 must be a lowercase SHA-256"
        )
    expected_binding = extension_app_binding_sha256(
        app_manifest,
        skill_sha256=skill_sha256,
        package_version=package_version,
    )
    if binding_sha256 != expected_binding:
        raise ExtensionAppValidationError(
            "Extension App bindingSha256 does not match canonical manifest, "
            "Skill, and package version"
        )
    paw = package_manifest.get("paw")
    if not isinstance(paw, dict):
        raise ExtensionAppValidationError("Pi Package manifest requires paw")
    capabilities = paw.get("capabilities")
    if (
        not isinstance(capabilities, list)
        or any(not isinstance(value, str) or not value.strip() for value in capabilities)
        or len(capabilities) != len(set(capabilities))
    ):
        raise ExtensionAppValidationError(
            "Pi Package paw.capabilities must be a unique string array"
        )
    expected_capability = extension_app_binding_capability(binding_sha256)
    binding_tokens = [
        value
        for value in capabilities
        if isinstance(value, str) and value.startswith("pawos.extension.binding.")
    ]
    if binding_tokens != [expected_capability]:
        raise ExtensionAppValidationError(
            "Pi Package paw.capabilities must contain the App binding capability"
        )
    package_extension = paw.get("extensionApp")
    if not isinstance(package_extension, dict):
        raise ExtensionAppValidationError(
            "Pi Package manifest requires paw.extensionApp"
        )
    expected_extension = {
        "id": _required_text(app_manifest, "id", label="Extension App manifest"),
        "packageId": package_name,
        "version": package_version,
        "bindingSha256": binding_sha256,
        "skillRef": skill_ref,
        "skillSha256": skill_sha256,
        "verticalSuiteId": _required_text(
            app_manifest, "verticalSuiteId", label="Extension App manifest"
        ),
        "verticalSuiteRevision": _required_text(
            app_manifest, "verticalSuiteRevision", label="Extension App manifest"
        ),
        "sandbox": app_manifest.get("sandbox"),
        "manifest": app_manifest,
    }
    for field, expected in expected_extension.items():
        if package_extension.get(field) != expected:
            raise ExtensionAppValidationError(
                "Pi Package paw.extensionApp does not match the App manifest "
                f"for {field}"
            )
    return package_manifest


def _find_quick_validate(explicit: str | None) -> Path | None:
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    configured = os.environ.get("PAWOS_SKILL_QUICK_VALIDATE", "").strip()
    if configured:
        candidates.append(Path(configured).expanduser())
    which = shutil.which("quick_validate.py")
    if which:
        candidates.append(Path(which))
    candidates.extend(
        [
            Path.home() / ".codex/skills/.system/skill-creator/scripts/quick_validate.py",
            Path.home() / ".agents/skills/skill-creator/scripts/quick_validate.py",
        ]
    )
    for candidate in candidates:
        if candidate.is_file() and not candidate.is_symlink():
            return candidate.resolve()
    return None


def _validate_skill_fallback(skill_path: Path) -> str:
    skill_file = skill_path / "SKILL.md"
    try:
        content = skill_file.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise ExtensionAppValidationError(f"Skill is unreadable: {skill_file}: {error}") from error
    if not content.startswith("---\n") or "\n---" not in content[4:]:
        raise ExtensionAppValidationError(f"Skill has invalid YAML frontmatter: {skill_file}")
    frontmatter_text, _body = content[4:].split("\n---", 1)
    try:
        frontmatter = yaml.safe_load(frontmatter_text)
    except yaml.YAMLError as error:
        raise ExtensionAppValidationError(f"Skill YAML is invalid: {skill_file}: {error}") from error
    if not isinstance(frontmatter, dict):
        raise ExtensionAppValidationError(f"Skill frontmatter must be an object: {skill_file}")
    name = frontmatter.get("name")
    description = frontmatter.get("description")
    if name != skill_path.name or not isinstance(name, str) or not _SLUG.fullmatch(name):
        raise ExtensionAppValidationError(
            f"Skill name must match its hyphenated directory: {skill_file}"
        )
    if not isinstance(description, str) or not description.strip():
        raise ExtensionAppValidationError(f"Skill description is required: {skill_file}")
    return "fallback"


def _validate_skill(skill_path: Path, *, quick_validate: str | None) -> str:
    _assert_no_symlinks(skill_path, label="Extension App Skill")
    validator = _find_quick_validate(quick_validate)
    if validator is None:
        return _validate_skill_fallback(skill_path)
    completed = subprocess.run(
        [sys.executable, str(validator), str(skill_path)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        detail = (completed.stdout.strip() or completed.stderr.strip() or "unknown error")
        raise ExtensionAppValidationError(
            f"quick_validate rejected the App Skill: {detail}"
        )
    return f"quick_validate.py:{validator}"


def _resolve_suite(app_manifest: dict[str, Any]) -> dict[str, Any]:
    try:
        from rag_ime.vertical_agent_harness import resolve_builtin_vertical_suite

        suite = resolve_builtin_vertical_suite(
            app_manifest.get("verticalSuiteId"),
            app_manifest.get("verticalSuiteRevision"),
        )
    except Exception as error:
        raise ExtensionAppValidationError(
            "Extension App vertical suite binding is not registered: "
            f"{app_manifest.get('verticalSuiteId')!r}/"
            f"{app_manifest.get('verticalSuiteRevision')!r}: {error}"
        ) from error
    sandbox = suite.get("sandbox")
    if not isinstance(sandbox, dict) or sandbox.get("network") != "blocked" or sandbox.get("productionWriteBlocked") is not True:
        raise ExtensionAppValidationError(
            "Registered vertical suite does not retain blocked network and production writes"
        )
    return suite


def validate_extension_app(
    app_directory: str | Path,
    *,
    quick_validate: str | None = None,
) -> dict[str, Any]:
    app_root = Path(app_directory).expanduser()
    _assert_real_directory(app_root, label="Extension App source")
    app_root = app_root.resolve()
    slug = app_root.name
    if not _SLUG.fullmatch(slug):
        raise ExtensionAppValidationError(f"Extension App directory slug is invalid: {slug!r}")
    for path in app_root.rglob("*"):
        relative_parts = path.relative_to(app_root).parts
        if any(part in _DISALLOWED_FIXTURE_PATH_PARTS for part in relative_parts):
            raise ExtensionAppValidationError(
                f"Extension App must bind a registered suite, not copy fixture paths: {path}"
            )

    app_manifest = _read_json_object(
        app_root / "pawos-app.json",
        label="Extension App manifest",
    )
    if app_manifest.get("schemaVersion") != "pawos.extension-app.v1":
        raise ExtensionAppValidationError("Extension App manifest schemaVersion is unsupported")
    app_id = _required_text(app_manifest, "id", label="Extension App manifest")
    if app_id != f"extension:{slug}":
        raise ExtensionAppValidationError(
            f"Extension App id must match its source directory: {app_id!r}"
        )
    app_version = _required_text(app_manifest, "version", label="Extension App manifest")
    if not _SEMVER.fullmatch(app_version):
        raise ExtensionAppValidationError(f"Extension App version is invalid: {app_version!r}")
    route = _required_text(app_manifest, "route", label="Extension App manifest")
    if route != f"/extensions/{slug}":
        raise ExtensionAppValidationError(
            f"Extension App route must match its source directory: {route!r}"
        )
    for key in ("packageId", "label", "shortLabel", "tagline", "skillRef", "verticalSuiteId", "verticalSuiteRevision"):
        _required_text(app_manifest, key, label="Extension App manifest")
    skill_ref = _required_text(app_manifest, "skillRef", label="Extension App manifest")
    if not _SLUG.fullmatch(skill_ref):
        raise ExtensionAppValidationError(
            f"Extension App skillRef must be a hyphenated name: {skill_ref!r}"
        )
    if app_manifest.get("presentation") not in _PRESENTATIONS:
        raise ExtensionAppValidationError("Extension App presentation is invalid")
    if app_manifest.get("accent") not in _ACCENTS:
        raise ExtensionAppValidationError("Extension App accent is invalid")
    sandbox_contract = _validate_sandbox_contract(app_manifest)
    icon = app_manifest.get("icon")
    if not isinstance(icon, dict) or icon.get("symbol") not in _ICON_SYMBOLS or not isinstance(icon.get("background"), str) or not re.fullmatch(r"#[0-9A-Fa-f]{6}", icon.get("background", "")):
        raise ExtensionAppValidationError("Extension App icon is invalid")
    skill_sha256 = app_manifest.get("skillSha256")
    if not isinstance(skill_sha256, str) or not _SHA256.fullmatch(skill_sha256):
        raise ExtensionAppValidationError(
            "Extension App manifest skillSha256 must be a lowercase SHA-256"
        )

    package_root = app_root / "pi-package"
    package_manifest = _validate_pi_package(package_root, app_manifest)
    skill_validator = _validate_skill(
        package_root / "skills" / skill_ref,
        quick_validate=quick_validate,
    )
    suite = _resolve_suite(app_manifest)
    if (app_root / "vertical-agent.json").exists():
        raise ExtensionAppValidationError(
            "Extension App must not copy vertical-agent.json; bind the registered suite instead"
        )
    return {
        "schemaVersion": "pawos.extension-app-validation.v1",
        "status": "valid",
        "appId": app_id,
        "version": app_version,
        "packageId": package_manifest["name"],
        "binding": {
            "bindingSha256": app_manifest["bindingSha256"],
            "bindingCapability": extension_app_binding_capability(
                str(app_manifest["bindingSha256"])
            ),
            "skillSha256": hashlib.sha256(
                (package_root / "skills" / skill_ref / "SKILL.md").read_bytes()
            ).hexdigest(),
        },
        "skill": {"name": skill_ref, "validator": skill_validator},
        "suite": {
            "suiteId": app_manifest["verticalSuiteId"],
            "suiteRevision": app_manifest["verticalSuiteRevision"],
            "registry": "rag_ime.vertical_agent_harness",
            "fixtureSource": "registered suite; not copied into Extension App",
            "sandbox": suite["sandbox"],
            "appPolicy": sandbox_contract,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("app_directory", nargs="?", default=str(DEFAULT_APP))
    parser.add_argument(
        "--quick-validate",
        default=None,
        help="Optional path to the shared skill quick_validate.py",
    )
    args = parser.parse_args(argv)
    try:
        result = validate_extension_app(
            args.app_directory,
            quick_validate=args.quick_validate,
        )
    except (ExtensionAppValidationError, OSError, subprocess.SubprocessError) as error:
        print(f"Extension App validation failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
