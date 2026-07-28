from __future__ import annotations

import json
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence


SCHEMA_VERSION = "rag-ime.macos-uninstall.v1"
LAUNCH_AGENT_LABELS = (
    "com.rag-ime.agent-gateway",
    "com.rag-ime.desktop-bridge",
    "com.rag-ime.memory-book-maintenance",
    "com.rag-ime.mineru",
    "com.rag-ime.mlx-predictor",
    "com.rag-ime.sidecar",
    "com.rag-ime.voice",
)
LEGACY_LAUNCH_AGENT_LABELS = (
    "com.rag-ime.frontend",
)
OWNED_LAUNCH_AGENT_LABELS = LAUNCH_AGENT_LABELS + LEGACY_LAUNCH_AGENT_LABELS
APP_BUNDLES = (
    ("RagImeControl.app", "com.rag-ime.control"),
    ("RagImeDesktopBridge.app", "com.rag-ime.desktop-bridge"),
    ("RagImeVoice.app", "com.rag-ime.voice"),
)
RIME_MANAGED_BLOCKS = (
    (
        "squirrel.custom.yaml",
        "# >>> RAG-IME managed block",
        "# <<< RAG-IME managed block",
    ),
    (
        "default.custom.yaml",
        "# >>> RAG-IME default managed block",
        "# <<< RAG-IME default managed block",
    ),
    (
        "luna_pinyin_simp.custom.yaml",
        "# rag-ime-managed-sichuan-fuzzy-pinyin: begin",
        "# rag-ime-managed-sichuan-fuzzy-pinyin: end",
    ),
)
VOICE_KEYCHAIN_SERVICE = "com.rag-ime.voice.volcengine"
VOICE_KEYCHAIN_ACCOUNTS = ("app-id", "access-token", "resource-id")
COMPONENT_SCOPES = ("all", "sidecar", "voice")
SQUIRREL_MARKER_SCHEMAS = (
    "rag-ime.squirrel-build-marker.v1",
    "rag-ime.squirrel-build-marker.v2",
)
RUNTIME_CACHE_RELATIVE_PATHS = (
    Path("Library/Application Support/RagIme/app"),
    Path("Library/Application Support/RagIme/components"),
    Path("Library/Application Support/RagIme/BrowserCopilot/extension"),
    Path("Library/Application Support/RagIme/disabled-input-method-backups"),
    Path("Library/Caches/RagIme/BrowserCopilot/managed-profile/Default/Cache"),
    Path("Library/Caches/RagIme/BrowserCopilot/managed-profile/Default/Code Cache"),
)


@dataclass(frozen=True)
class MacOSUninstallOptions:
    component_scope: str = "all"
    remove_patched_squirrel: bool = False
    remove_rime_managed_config: bool = False
    purge_runtime_cache: bool = False
    purge_local_data: bool = False
    purge_credentials: bool = False
    purge_voice_config: bool = False


CommandRunner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


def build_macos_uninstall_plan(
    home: str | Path,
    *,
    options: MacOSUninstallOptions | None = None,
    uid: int | None = None,
) -> dict[str, object]:
    selected = options or MacOSUninstallOptions()
    if not str(home).strip():
        raise ValueError("uninstall home must not be empty")
    home_path = Path(home).expanduser().absolute()
    if home_path.resolve() == Path("/"):
        raise ValueError("uninstall home must not be the filesystem root")
    if selected.component_scope not in COMPONENT_SCOPES:
        raise ValueError(f"unsupported uninstall component scope: {selected.component_scope}")
    domain = f"gui/{os.getuid() if uid is None else int(uid)}"
    actions: list[dict[str, object]] = []
    warnings: list[dict[str, str]] = []

    launch_agent_dir = home_path / "Library" / "LaunchAgents"
    for label in _launch_agent_labels_for_scope(selected.component_scope):
        target = launch_agent_dir / f"{label}.plist"
        exists = target.exists() or target.is_symlink()
        path_safe = _path_is_safe_for_action(target, home_path, allow_target_symlink=False)
        actual_label = _launch_agent_label(target) if exists and path_safe else ""
        verified = exists and path_safe and actual_label == label
        actions.append(
            {
                **_path_action(
                    kind="remove_launch_agent",
                    target=target,
                    present=verified,
                    reason="launch agent label ownership check",
                    metadata={
                        "expectedLabel": label,
                        "actualLabel": actual_label,
                        "domain": domain,
                        "lifecycle": (
                            "legacy" if label in LEGACY_LAUNCH_AGENT_LABELS else "active"
                        ),
                    },
                ),
                "status": "planned" if verified else ("absent" if not exists else "skipped_unverified"),
            }
        )
        if exists and not verified:
            warnings.append(
                {
                    "id": "launch_agent_not_owned" if path_safe else "launch_agent_path_escapes_home",
                    "target": str(target),
                    "detail": (
                        "launch agent Label does not match its known RAG-IME filename"
                        if path_safe
                        else "launch agent or its parent resolves outside the selected home"
                    ),
                }
            )

    applications = home_path / "Applications"
    for name, expected_bundle_id in _app_bundles_for_scope(selected.component_scope):
        target = applications / name
        if not target.exists() and not target.is_symlink():
            actions.append(
                _path_action(
                    kind="remove_owned_app",
                    target=target,
                    present=False,
                    reason="known RAG-IME app bundle",
                    metadata={"expectedBundleId": expected_bundle_id},
                )
            )
            continue
        if not _path_is_safe_for_action(target, home_path, allow_target_symlink=False):
            actions.append(
                {
                    **_path_action(
                        kind="remove_owned_app",
                        target=target,
                        present=False,
                        reason="bundle path ownership check",
                        metadata={"expectedBundleId": expected_bundle_id},
                    ),
                    "status": "skipped_unverified",
                }
            )
            warnings.append(
                {
                    "id": "app_path_escapes_home",
                    "target": str(target),
                    "detail": "app or its parent resolves outside the selected home",
                }
            )
            continue
        actual_bundle_id = _bundle_identifier(target)
        verified = actual_bundle_id == expected_bundle_id
        actions.append(
            {
                **_path_action(
                    kind="remove_owned_app",
                    target=target,
                    present=verified,
                    reason="bundle identifier ownership check",
                    metadata={
                        "expectedBundleId": expected_bundle_id,
                        "actualBundleId": actual_bundle_id,
                    },
                ),
                "status": "planned" if verified else "skipped_unverified",
            }
        )
        if not verified:
            warnings.append(
                {
                    "id": "app_bundle_not_owned",
                    "target": str(target),
                    "detail": "bundle identifier does not match the RAG-IME component",
                }
            )

    if selected.remove_patched_squirrel:
        squirrel = home_path / "Library" / "Input Methods" / "Squirrel.app"
        squirrel_present = squirrel.exists() or squirrel.is_symlink()
        marker = squirrel / "Contents" / "Resources" / "rag-ime-build-marker.json"
        path_safe = _path_is_safe_for_action(squirrel, home_path, allow_target_symlink=False)
        marker_safe = path_safe and _descendant_is_safe(marker, squirrel, allow_target_symlink=False)
        marker_payload = _load_json(marker) if marker_safe else {}
        marker_valid = (
            marker_safe
            and squirrel.is_dir()
            and marker_payload.get("schemaVersion") in SQUIRREL_MARKER_SCHEMAS
            and str(marker_payload.get("bundleId") or "").startswith("im.rime.inputmethod.Squirrel")
        )
        actions.append(
            {
                **_path_action(
                    kind="remove_marked_squirrel",
                    target=squirrel,
                    present=marker_valid,
                    reason="explicit option plus RAG-IME build marker",
                    metadata={
                        "markerPath": str(marker),
                        "expectedMarkerSchemas": list(SQUIRREL_MARKER_SCHEMAS),
                        "actualMarkerSchema": str(marker_payload.get("schemaVersion") or ""),
                        "markerBundleId": str(marker_payload.get("bundleId") or ""),
                    },
                ),
                "status": "planned" if marker_valid else ("absent" if not squirrel_present else "skipped_unverified"),
            }
        )
        if squirrel_present and not marker_valid:
            warnings.append(
                {
                    "id": "squirrel_not_owned" if path_safe else "squirrel_path_escapes_home",
                    "target": str(squirrel),
                    "detail": (
                        "Squirrel is present but has no valid RAG-IME build marker"
                        if path_safe
                        else "Squirrel or its parent resolves outside the selected home"
                    ),
                }
            )

    if selected.remove_rime_managed_config:
        rime_dir = home_path / "Library" / "Rime"
        for name, begin, end in RIME_MANAGED_BLOCKS:
            target = rime_dir / name
            target_present = target.exists() or target.is_symlink()
            path_safe = _path_is_safe_for_action(target, home_path, allow_target_symlink=False)
            text = _read_text(target) if path_safe else ""
            begin_count = text.count(begin)
            end_count = text.count(end)
            markers_valid = begin_count == 1 and end_count == 1
            status = (
                "planned"
                if path_safe and markers_valid
                else ("absent" if not target_present else "skipped_unverified")
            )
            actions.append(
                {
                    **_path_action(
                        kind="remove_rime_managed_block",
                        target=target,
                        present=status == "planned",
                        reason="explicit option plus paired managed markers",
                        metadata={"beginMarker": begin, "endMarker": end},
                    ),
                    "status": status,
                }
            )
            if target_present and path_safe and (begin_count == 0) != (end_count == 0):
                warnings.append(
                    {
                        "id": "rime_managed_markers_incomplete",
                        "target": str(target),
                        "detail": "only one managed marker is present; refusing to edit",
                    }
                )
            elif target_present and path_safe and (begin_count > 1 or end_count > 1):
                warnings.append(
                    {
                        "id": "rime_managed_markers_ambiguous",
                        "target": str(target),
                        "detail": "managed markers occur more than once; refusing to edit",
                    }
                )
            elif target_present and not path_safe:
                warnings.append(
                    {
                        "id": "rime_target_escapes_home",
                        "target": str(target),
                        "detail": "Rime file or its parent resolves outside the selected home",
                    }
                )

    if selected.purge_runtime_cache:
        for relative in RUNTIME_CACHE_RELATIVE_PATHS:
            _append_safe_purge_action(
                actions,
                warnings,
                kind="purge_owned_runtime_cache",
                target=home_path / relative,
                home=home_path,
                reason="explicit generated-code or allowlisted-cache purge before a clean reinstall",
            )

    if selected.purge_local_data:
        for target, reason in (
            (home_path / "Library" / "Application Support" / "RagIme", "explicit local data purge"),
            (home_path / "Library" / "Logs" / "RagIme", "explicit log purge"),
        ):
            _append_safe_purge_action(
                actions,
                warnings,
                kind="purge_owned_data",
                target=target,
                home=home_path,
                reason=reason,
            )

    if selected.purge_credentials:
        for account in VOICE_KEYCHAIN_ACCOUNTS:
            actions.append(
                {
                    "kind": "delete_keychain_item",
                    "target": f"{VOICE_KEYCHAIN_SERVICE}/{account}",
                    "status": "planned",
                    "present": None,
                    "reason": "explicit credential purge",
                    "destructive": True,
                    "metadata": {"service": VOICE_KEYCHAIN_SERVICE, "account": account},
                }
            )

    if selected.purge_voice_config:
        voice_config = home_path / "Library" / "Application Support" / "RagIme" / "voice-hotwords.json"
        _append_safe_purge_action(
            actions,
            warnings,
            kind="purge_owned_file",
            target=voice_config,
            home=home_path,
            reason="explicit voice private-config purge",
        )

    planned_count = sum(1 for action in actions if action.get("status") == "planned")
    preserved_by_default = ["macOS TCC/privacy-list entries"]
    if not selected.purge_local_data:
        app_support = home_path / "Library" / "Application Support" / "RagIme"
        preserved_by_default.append(
            f"{app_support} (except voice-hotwords.json)"
            if selected.purge_voice_config
            else str(app_support)
        )
        preserved_by_default.append(str(home_path / "Library" / "Logs" / "RagIme"))
    if not selected.remove_rime_managed_config:
        preserved_by_default.append(str(home_path / "Library" / "Rime"))
    if not selected.remove_patched_squirrel:
        preserved_by_default.append(str(home_path / "Library" / "Input Methods" / "Squirrel.app"))
    if not selected.purge_runtime_cache:
        preserved_by_default.extend(
            str(home_path / relative) for relative in RUNTIME_CACHE_RELATIVE_PATHS
        )

    return {
        "schemaVersion": SCHEMA_VERSION,
        "mode": "dry-run",
        "ok": True,
        "home": str(home_path),
        "domain": domain,
        "requiresExplicitApply": True,
        "options": {
            "componentScope": selected.component_scope,
            "removePatchedSquirrel": selected.remove_patched_squirrel,
            "removeRimeManagedConfig": selected.remove_rime_managed_config,
            "purgeRuntimeCache": selected.purge_runtime_cache,
            "purgeLocalData": selected.purge_local_data,
            "purgeCredentials": selected.purge_credentials,
            "purgeVoiceConfig": selected.purge_voice_config,
        },
        "plannedActionCount": planned_count,
        "actions": actions,
        "warnings": warnings,
        "preservedByDefault": preserved_by_default,
        "notes": [
            "Dry-run performs no launchctl, Keychain, filesystem, Rime, or input-source mutation.",
            "System-level /Library/Input Methods is never removed by this tool.",
            "Rime edits require paired managed markers and preserve a backup before mutation.",
            "TCC/privacy-list entries remain a manual System Settings action.",
        ],
    }


def apply_macos_uninstall_plan(
    plan: Mapping[str, object],
    *,
    command_runner: CommandRunner | None = None,
    platform_name: str | None = None,
) -> dict[str, object]:
    if plan.get("schemaVersion") != SCHEMA_VERSION:
        raise ValueError("unsupported uninstall plan schema")
    if (platform_name or sys.platform) != "darwin":
        raise RuntimeError("RAG-IME uninstall apply is supported only on macOS")
    raw_home = str(plan.get("home") or "").strip()
    if not raw_home:
        raise ValueError("uninstall home must not be empty or filesystem root")
    home = Path(raw_home).expanduser().absolute()
    if home.resolve() == Path("/"):
        raise ValueError("uninstall home must not be empty or filesystem root")
    runner = command_runner or _run_command
    results: list[dict[str, object]] = []
    ok = True
    for raw_action in plan.get("actions", []):
        if not isinstance(raw_action, Mapping) or raw_action.get("status") != "planned":
            continue
        if not ok:
            results.append(
                {
                    "kind": str(raw_action.get("kind") or ""),
                    "target": str(raw_action.get("target") or ""),
                    "status": "not_applied",
                    "detail": "a prior uninstall action failed; rerun the dry-run before retrying",
                }
            )
            continue
        action = dict(raw_action)
        try:
            result = _apply_action(action, home=home, runner=runner)
        except Exception as exc:
            ok = False
            result = {
                "kind": str(action.get("kind") or ""),
                "target": str(action.get("target") or ""),
                "status": "failed",
                "error": exc.__class__.__name__,
                "detail": str(exc),
            }
        results.append(result)
    return {
        **dict(plan),
        "mode": "apply",
        "ok": ok,
        "appliedActionCount": sum(1 for result in results if result.get("status") == "applied"),
        "results": results,
    }


def write_uninstall_report(report: Mapping[str, object], path: str | Path) -> None:
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(report), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    target.chmod(0o600)


def _apply_action(action: Mapping[str, object], *, home: Path, runner: CommandRunner) -> dict[str, object]:
    kind = str(action.get("kind") or "")
    target_text = str(action.get("target") or "")
    metadata = action.get("metadata") if isinstance(action.get("metadata"), Mapping) else {}
    if kind == "delete_keychain_item":
        service = str(metadata.get("service") or "")
        account = str(metadata.get("account") or "")
        if (
            service != VOICE_KEYCHAIN_SERVICE
            or account not in VOICE_KEYCHAIN_ACCOUNTS
            or target_text != f"{service}/{account}"
        ):
            raise ValueError("uninstall plan contains an unowned Keychain target")
        args = [
            "security",
            "delete-generic-password",
            "-s",
            service,
            "-a",
            account,
        ]
        completed = runner(args)
        if completed.returncode not in {0, 44}:
            raise RuntimeError(f"Keychain deletion failed with exit code {completed.returncode}")
        return {
            "kind": kind,
            "target": target_text,
            "status": "applied" if completed.returncode == 0 else "already_absent",
            "commandReturnCode": int(completed.returncode),
        }

    target = Path(target_text).expanduser().absolute()
    _require_path_within_home(target, home)
    _require_allowlisted_target(kind, target, home)
    if kind == "remove_launch_agent":
        _require_path_within_home(target, home, allow_target_symlink=False)
        expected = str(metadata.get("expectedLabel") or "")
        expected_target = home / "Library" / "LaunchAgents" / f"{expected}.plist"
        domain = str(metadata.get("domain") or "")
        if (
            expected not in OWNED_LAUNCH_AGENT_LABELS
            or target != expected_target
            or not domain.startswith("gui/")
            or not domain.removeprefix("gui/").isdigit()
            or _launch_agent_label(target) != expected
        ):
            raise RuntimeError("launch agent ownership changed after planning")
        completed = runner(
            [
                "launchctl",
                "bootout",
                f"{domain}/{expected}",
            ]
        )
        # launchctl maps ESRCH ("No such process") to exit code 3 when an
        # owned plist remains on disk but the job is already unloaded. That is
        # the idempotent state an uninstall is trying to reach, not a reason to
        # strand every later owned component.
        if completed.returncode not in {0, 3}:
            raise RuntimeError(
                f"launch agent bootout failed with exit code {completed.returncode}"
            )
        target.unlink(missing_ok=True)
        return {
            "kind": kind,
            "target": str(target),
            "status": "applied" if completed.returncode == 0 else "already_absent",
            "commandReturnCode": int(completed.returncode),
        }
    if kind == "remove_owned_app":
        _require_path_within_home(target, home, allow_target_symlink=False)
        expected = str(metadata.get("expectedBundleId") or "")
        expected_by_target = {
            home / "Applications" / name: bundle_id for name, bundle_id in APP_BUNDLES
        }
        if expected_by_target.get(target) != expected or _bundle_identifier(target) != expected:
            raise RuntimeError("app ownership changed after planning")
        _remove_path(target)
        return {"kind": kind, "target": str(target), "status": "applied"}
    if kind == "remove_marked_squirrel":
        _require_path_within_home(target, home, allow_target_symlink=False)
        marker = target / "Contents" / "Resources" / "rag-ime-build-marker.json"
        if not _descendant_is_safe(marker, target, allow_target_symlink=False):
            raise RuntimeError("Squirrel build marker escapes the owned app bundle")
        payload = _load_json(marker)
        if (
            payload.get("schemaVersion") not in SQUIRREL_MARKER_SCHEMAS
            or not str(payload.get("bundleId") or "").startswith("im.rime.inputmethod.Squirrel")
        ):
            raise RuntimeError("Squirrel ownership changed after planning")
        _remove_path(target)
        return {"kind": kind, "target": str(target), "status": "applied"}
    if kind == "remove_rime_managed_block":
        _require_path_within_home(target, home, allow_target_symlink=False)
        begin = str(metadata.get("beginMarker") or "")
        end = str(metadata.get("endMarker") or "")
        expected_by_target = {
            home / "Library" / "Rime" / name: (expected_begin, expected_end)
            for name, expected_begin, expected_end in RIME_MANAGED_BLOCKS
        }
        if expected_by_target.get(target) != (begin, end):
            raise RuntimeError("Rime managed-marker ownership changed after planning")
        backup = _remove_managed_block(target, begin=begin, end=end)
        return {
            "kind": kind,
            "target": str(target),
            "status": "applied",
            "backupPath": str(backup),
        }
    if kind in {"purge_owned_data", "purge_owned_file", "purge_owned_runtime_cache"}:
        _remove_path(target)
        return {"kind": kind, "target": str(target), "status": "applied"}
    raise ValueError(f"unsupported uninstall action: {kind}")


def _path_action(
    *,
    kind: str,
    target: Path,
    present: bool,
    reason: str,
    metadata: Mapping[str, object] | None = None,
    destructive: bool = False,
) -> dict[str, object]:
    return {
        "kind": kind,
        "target": str(target),
        "status": "planned" if present else "absent",
        "present": bool(present),
        "reason": reason,
        "destructive": bool(destructive),
        "metadata": dict(metadata or {}),
    }


def _append_safe_purge_action(
    actions: list[dict[str, object]],
    warnings: list[dict[str, str]],
    *,
    kind: str,
    target: Path,
    home: Path,
    reason: str,
) -> None:
    present = target.exists() or target.is_symlink()
    path_safe = _path_is_safe_for_action(target, home, allow_target_symlink=True)
    actions.append(
        {
            **_path_action(
                kind=kind,
                target=target,
                present=present and path_safe,
                reason=reason,
                destructive=True,
            ),
            "status": "planned" if present and path_safe else ("absent" if not present else "skipped_unverified"),
        }
    )
    if present and not path_safe:
        warnings.append(
            {
                "id": "purge_target_escapes_home",
                "target": str(target),
                "detail": "purge target parent resolves outside the selected home",
            }
        )


def _launch_agent_labels_for_scope(scope: str) -> tuple[str, ...]:
    if scope == "voice":
        return ("com.rag-ime.voice",)
    if scope == "sidecar":
        return ("com.rag-ime.sidecar", "com.rag-ime.agent-gateway")
    return OWNED_LAUNCH_AGENT_LABELS


def _app_bundles_for_scope(scope: str) -> tuple[tuple[str, str], ...]:
    if scope == "voice":
        return (("RagImeVoice.app", "com.rag-ime.voice"),)
    if scope == "sidecar":
        return ()
    return APP_BUNDLES


def _bundle_identifier(app: Path) -> str:
    info_path = app / "Contents" / "Info.plist"
    if not _descendant_is_safe(info_path, app, allow_target_symlink=False):
        return ""
    try:
        payload = plistlib.loads(info_path.read_bytes())
    except (OSError, ValueError, TypeError, plistlib.InvalidFileException):
        return ""
    return str(payload.get("CFBundleIdentifier") or "") if isinstance(payload, dict) else ""


def _load_json(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _launch_agent_label(path: Path) -> str:
    if not _descendant_is_safe(path, path.parent, allow_target_symlink=False):
        return ""
    try:
        payload = plistlib.loads(path.read_bytes())
    except (OSError, ValueError, TypeError, plistlib.InvalidFileException):
        return ""
    return str(payload.get("Label") or "") if isinstance(payload, dict) else ""


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def _remove_managed_block(path: Path, *, begin: str, end: str) -> Path:
    original = path.read_bytes()
    text = original.decode("utf-8")
    if text.count(begin) != 1 or text.count(end) != 1:
        raise RuntimeError("managed block markers are missing or ambiguous after planning")
    start = text.find(begin)
    finish = text.find(end, start + len(begin))
    if start < 0 or finish < 0:
        raise RuntimeError("managed block markers changed after planning")
    finish += len(end)
    before = text[:start].rstrip()
    after = text[finish:].lstrip("\n")
    if before and after:
        updated = before + "\n\n" + after
    else:
        updated = before + after
    if updated and not updated.endswith("\n"):
        updated += "\n"
    backup = _next_backup_path(path)
    mode = path.stat(follow_symlinks=False).st_mode & 0o777
    _write_exclusive_file(backup, original, mode=mode)
    _atomic_replace_text(path, updated, mode=mode)
    return backup


def _next_backup_path(path: Path) -> Path:
    base = path.with_name(path.name + ".rag-ime-uninstall.bak")
    if not base.exists() and not base.is_symlink():
        return base
    index = 1
    while True:
        candidate = path.with_name(path.name + f".rag-ime-uninstall.bak.{index}")
        if not candidate.exists() and not candidate.is_symlink():
            return candidate
        index += 1


def _write_exclusive_file(path: Path, content: bytes, *, mode: int) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, mode)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _atomic_replace_text(path: Path, content: str, *, mode: int) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.rag-ime-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(mode)
        os.replace(temporary, path)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def _remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path)


def _require_path_within_home(path: Path, home: Path, *, allow_target_symlink: bool = True) -> None:
    try:
        path.relative_to(home)
    except ValueError as exc:
        raise ValueError("uninstall target escapes the selected home") from exc
    if path == home:
        raise ValueError("uninstall target must not be the selected home")
    home_resolved = home.resolve()
    parent_resolved = path.parent.resolve()
    try:
        parent_resolved.relative_to(home_resolved)
    except ValueError as exc:
        raise ValueError("uninstall target parent resolves outside the selected home") from exc
    if not allow_target_symlink and path.is_symlink():
        raise ValueError("uninstall target must not be a symbolic link")


def _path_is_safe_for_action(path: Path, home: Path, *, allow_target_symlink: bool) -> bool:
    try:
        _require_path_within_home(path, home, allow_target_symlink=allow_target_symlink)
    except ValueError:
        return False
    return True


def _descendant_is_safe(path: Path, root: Path, *, allow_target_symlink: bool) -> bool:
    try:
        path.relative_to(root)
        parent_resolved = path.parent.resolve()
        parent_resolved.relative_to(root.resolve())
    except (OSError, ValueError):
        return False
    return allow_target_symlink or not path.is_symlink()


def _require_allowlisted_target(kind: str, target: Path, home: Path) -> None:
    allowed: dict[str, set[Path]] = {
        "remove_launch_agent": {
            home / "Library" / "LaunchAgents" / f"{label}.plist"
            for label in OWNED_LAUNCH_AGENT_LABELS
        },
        "remove_owned_app": {home / "Applications" / name for name, _ in APP_BUNDLES},
        "remove_marked_squirrel": {home / "Library" / "Input Methods" / "Squirrel.app"},
        "remove_rime_managed_block": {
            home / "Library" / "Rime" / name for name, _, _ in RIME_MANAGED_BLOCKS
        },
        "purge_owned_data": {
            home / "Library" / "Application Support" / "RagIme",
            home / "Library" / "Logs" / "RagIme",
        },
        "purge_owned_file": {
            home / "Library" / "Application Support" / "RagIme" / "voice-hotwords.json"
        },
        "purge_owned_runtime_cache": {
            home / relative for relative in RUNTIME_CACHE_RELATIVE_PATHS
        },
    }
    if kind not in allowed or target not in allowed[kind]:
        raise ValueError("uninstall plan contains a target outside the owned allowlist")


def _run_command(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(args), text=True, capture_output=True, check=False)
