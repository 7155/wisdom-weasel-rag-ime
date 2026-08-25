#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import tempfile
import time
from pathlib import Path
from typing import Iterable, Mapping


SCHEMA_VERSION = "paw.codex-skill-install.v1"
RECEIPT_NAME = "paw-managed-skills.json"
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "integrations" / "pi" / "skills"
_SKILL_NAME = re.compile(r"^name:\s*([a-z0-9][a-z0-9-]*)\s*$", re.MULTILINE)


def _directory_digest(root: Path) -> str:
    if not root.is_dir() or root.is_symlink():
        raise ValueError(f"skill path must be a regular directory: {root}")
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        if path.is_symlink():
            raise ValueError(f"skill directory must not contain symbolic links: {path}")
        relative = path.relative_to(root).as_posix().encode("utf-8")
        if path.is_dir():
            digest.update(b"D\0" + relative + b"\0")
            continue
        if not path.is_file():
            raise ValueError(f"skill directory contains an unsupported entry: {path}")
        digest.update(b"F\0" + relative + b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return "sha256:" + digest.hexdigest()


def _source_skills(source_root: Path, selected: Iterable[str] = ()) -> dict[str, Path]:
    source_root = source_root.expanduser().resolve(strict=True)
    if not source_root.is_dir():
        raise ValueError("Codex skill source root must be a directory")
    selected_names = {value.strip() for value in selected if value.strip()}
    skills: dict[str, Path] = {}
    for candidate in sorted(source_root.iterdir(), key=lambda item: item.name):
        if not candidate.is_dir() or candidate.is_symlink():
            continue
        skill_file = candidate / "SKILL.md"
        if not skill_file.is_file() or skill_file.is_symlink():
            continue
        match = _SKILL_NAME.search(skill_file.read_text(encoding="utf-8"))
        if match is None or match.group(1) != candidate.name:
            raise ValueError(f"skill name does not match its directory: {candidate}")
        if selected_names and candidate.name not in selected_names:
            continue
        skills[candidate.name] = candidate
    missing = selected_names.difference(skills)
    if missing:
        raise ValueError(f"unknown PAW skill(s): {', '.join(sorted(missing))}")
    return skills


def _codex_home(path: str | Path) -> Path:
    resolved = Path(path).expanduser().absolute()
    if resolved == Path("/"):
        raise ValueError("Codex home must not be the filesystem root")
    return resolved


def _read_receipt(codex_home: Path) -> dict[str, object]:
    receipt_path = codex_home / RECEIPT_NAME
    if not receipt_path.exists():
        return {"schemaVersion": SCHEMA_VERSION, "skills": {}}
    if not receipt_path.is_file() or receipt_path.is_symlink():
        raise ValueError("PAW Codex skill receipt must be a regular file")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if not isinstance(receipt, dict) or receipt.get("schemaVersion") != SCHEMA_VERSION:
        raise ValueError("PAW Codex skill receipt has an unsupported schema")
    skills = receipt.get("skills")
    if not isinstance(skills, dict):
        raise ValueError("PAW Codex skill receipt is invalid")
    return receipt


def _write_receipt(codex_home: Path, skills: Mapping[str, object], source_root: Path) -> None:
    codex_home.mkdir(parents=True, exist_ok=True, mode=0o700)
    receipt_path = codex_home / RECEIPT_NAME
    payload = {
        "schemaVersion": SCHEMA_VERSION,
        "sourceRoot": str(source_root.resolve()),
        "updatedAtMs": int(time.time() * 1000),
        "skills": dict(sorted(skills.items())),
    }
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{RECEIPT_NAME}.", dir=codex_home
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        temporary.chmod(0o600)
        os.replace(temporary, receipt_path)
    finally:
        if temporary.exists():
            temporary.unlink()


def skill_install_status(
    source_root: str | Path = DEFAULT_SOURCE,
    codex_home: str | Path = Path.home() / ".codex",
    *,
    selected: Iterable[str] = (),
) -> dict[str, object]:
    source = Path(source_root)
    home = _codex_home(codex_home)
    sources = _source_skills(source, selected)
    receipt = _read_receipt(home)
    managed = receipt.get("skills")
    managed_skills = managed if isinstance(managed, dict) else {}
    items: list[dict[str, str]] = []
    for name, source_path in sources.items():
        source_digest = _directory_digest(source_path)
        target = home / "skills" / name
        if not target.exists() and not target.is_symlink():
            state = "missing"
            target_digest = ""
        elif not target.is_dir() or target.is_symlink():
            state = "conflict"
            target_digest = ""
        else:
            target_digest = _directory_digest(target)
            managed_entry = managed_skills.get(name)
            managed_digest = (
                str(managed_entry.get("digest") or "")
                if isinstance(managed_entry, Mapping)
                else ""
            )
            if target_digest == source_digest and target_digest == managed_digest:
                state = "managed"
            elif target_digest == source_digest:
                state = "present"
            elif managed_digest:
                state = "modified-managed"
            else:
                state = "conflict"
        items.append(
            {
                "name": name,
                "state": state,
                "sourceDigest": source_digest,
                "targetDigest": target_digest,
            }
        )
    summary: dict[str, int] = {}
    for item in items:
        state = item["state"]
        summary[state] = summary.get(state, 0) + 1
    return {
        "schemaVersion": SCHEMA_VERSION,
        "ok": True,
        "sourceRoot": str(source.resolve()),
        "targetRoot": str(home / "skills"),
        "receiptPath": str(home / RECEIPT_NAME),
        "summary": summary,
        "items": items,
    }


def _install_one(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    staging_root = Path(
        tempfile.mkdtemp(prefix=f".paw-skill-{target.name}-", dir=target.parent)
    )
    staged = staging_root / target.name
    try:
        shutil.copytree(source, staged, symlinks=False)
        if _directory_digest(staged) != _directory_digest(source):
            raise ValueError(f"staged Codex skill does not match its source: {target.name}")
        os.replace(staged, target)
    finally:
        shutil.rmtree(staging_root, ignore_errors=True)


def install_codex_skills(
    source_root: str | Path = DEFAULT_SOURCE,
    codex_home: str | Path = Path.home() / ".codex",
    *,
    selected: Iterable[str] = (),
) -> dict[str, object]:
    source = Path(source_root).expanduser().resolve(strict=True)
    home = _codex_home(codex_home)
    sources = _source_skills(source, selected)
    receipt = _read_receipt(home)
    raw_managed = receipt.get("skills")
    managed: dict[str, object] = dict(raw_managed) if isinstance(raw_managed, dict) else {}
    installed: list[str] = []
    reused: list[str] = []
    conflicts: list[str] = []
    for name, source_path in sources.items():
        target = home / "skills" / name
        source_digest = _directory_digest(source_path)
        if not target.exists() and not target.is_symlink():
            _install_one(source_path, target)
            managed[name] = {
                "digest": source_digest,
                "sourcePath": str(source_path.relative_to(source)),
            }
            installed.append(name)
            continue
        if target.is_dir() and not target.is_symlink() and _directory_digest(target) == source_digest:
            reused.append(name)
            continue
        conflicts.append(name)
    if managed:
        _write_receipt(home, managed, source)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "ok": True,
        "installed": installed,
        "reused": reused,
        "conflicts": conflicts,
        "receiptPath": str(home / RECEIPT_NAME),
    }


def uninstall_codex_skills(codex_home: str | Path = Path.home() / ".codex") -> dict[str, object]:
    home = _codex_home(codex_home)
    receipt = _read_receipt(home)
    raw_managed = receipt.get("skills")
    managed: dict[str, object] = dict(raw_managed) if isinstance(raw_managed, dict) else {}
    remaining: dict[str, object] = {}
    removed: list[str] = []
    absent: list[str] = []
    preserved_modified: list[str] = []
    for name, entry in sorted(managed.items()):
        if Path(name).name != name or not isinstance(entry, Mapping):
            preserved_modified.append(name)
            remaining[name] = entry
            continue
        target = home / "skills" / name
        expected_digest = str(entry.get("digest") or "")
        if not target.exists() and not target.is_symlink():
            absent.append(name)
            continue
        if (
            not expected_digest
            or not target.is_dir()
            or target.is_symlink()
            or _directory_digest(target) != expected_digest
        ):
            preserved_modified.append(name)
            remaining[name] = entry
            continue
        shutil.rmtree(target)
        removed.append(name)
    receipt_path = home / RECEIPT_NAME
    if remaining:
        source_root = Path(str(receipt.get("sourceRoot") or DEFAULT_SOURCE))
        _write_receipt(home, remaining, source_root)
    elif receipt_path.exists() and receipt_path.is_file() and not receipt_path.is_symlink():
        receipt_path.unlink()
    return {
        "schemaVersion": SCHEMA_VERSION,
        "ok": True,
        "removed": removed,
        "absent": absent,
        "preservedModified": preserved_modified,
        "receiptPath": str(receipt_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Inspect, install, or safely uninstall PAW's development Skills for Codex"
    )
    parser.add_argument("action", choices=("status", "install", "uninstall"), nargs="?", default="status")
    parser.add_argument("--source-root", default=str(DEFAULT_SOURCE))
    parser.add_argument(
        "--codex-home",
        default=os.environ.get("CODEX_HOME") or str(Path.home() / ".codex"),
    )
    parser.add_argument("--skill", action="append", default=[], help="Limit install/status to one exact skill name; repeatable")
    args = parser.parse_args()
    if args.action == "install":
        result = install_codex_skills(args.source_root, args.codex_home, selected=args.skill)
    elif args.action == "uninstall":
        result = uninstall_codex_skills(args.codex_home)
    else:
        result = skill_install_status(args.source_root, args.codex_home, selected=args.skill)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
