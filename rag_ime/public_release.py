from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Iterable


SCHEMA_VERSION = "rag-ime.public-release-audit.v3"
RELEASE_MANIFEST_SCHEMA_VERSION = "rag-ime.release-manifest.v2"
DEFAULT_RELEASE_MANIFEST_PATH = "output/release/release-manifest.json"
REQUIRED_ARTIFACT_KINDS = {"macos_release", "corresponding_source"}
REQUIRED_RELEASE_EVIDENCE = {
    "codesign": ("valid", "macos_release"),
    "notarization": ("accepted", "macos_release"),
    "stapling": ("valid", "macos_release"),
    "correspondingSource": ("verified", "corresponding_source"),
    "projectLicense": ("verified", None),
    "thirdPartyNotices": ("verified", None),
    "foregroundAcceptance": ("passed", "macos_release"),
}
LICENSE_NAMES = ("LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING")
REQUIRED_FILES = (
    "ARCHITECTURE.md",
    "CHANGELOG.md",
    "CODE_OF_CONDUCT.md",
    "CONTRIBUTING.md",
    "README.md",
    "SECURITY.md",
    "THIRD_PARTY_NOTICES.md",
    "pyproject.toml",
    "release/feature-registry.json",
    "release/product-status.json",
    "release/release-manifest.example.json",
)
FORBIDDEN_PREFIXES = (
    "docs/",
    "debug/",
    "macos/RagImeMac/",
    "scripts/build_macos_frontend.sh",
    "scripts/doctor_macos_frontend.sh",
    "scripts/install_macos_frontend.sh",
    "scripts/install_system_macos_frontend.sh",
    "scripts/refresh_macos_input_sources.sh",
    "scripts/reset_macos_ragime_registration.sh",
    ".rag-ime-data/",
    ".rag-ime-demo/",
    ".venv/",
    "build/",
    "output/",
    "dataset/quarantine/",
    "scripts/quarantine/",
)
FORBIDDEN_PARTS = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "node_modules"}
FORBIDDEN_NAMES = {".DS_Store", "installation.yaml"}
FORBIDDEN_SUFFIXES = (
    ".sqlite",
    ".sqlite3",
    ".db",
    ".log",
    ".dmg",
    ".safetensors",
    ".gguf",
    ".onnx",
    ".mlmodel",
)
HANDOFF_PATTERN = re.compile(r"(^|/)[^/]*handoff[^/]*\.(?:md|txt)$", re.IGNORECASE)
SECRET_PATTERNS = (
    ("openai_style_key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("notion_token", re.compile(r"\bntn_[A-Za-z0-9_-]{20,}\b")),
    ("bearer_token", re.compile(r"\bBearer\s+[A-Za-z0-9._-]{24,}\b", re.IGNORECASE)),
)
SECRET_FIXTURE_MARKERS = (
    "api.example.com",
    "public-audit-secret-fixture",
    "real-looking-secret",
    "replace-with-your-key",
)
MACHINE_PATH_PATTERNS = (
    ("macos_home", re.compile(r"/Users/(?!example(?:/|\b)|Shared(?:/|\b))[A-Za-z0-9._ -]+/")),
    ("external_volume", re.compile(r"/Volumes/(?!Example(?:/|\b))[A-Za-z0-9._ -]+/")),
)
MACHINE_PATH_SCAN_EXCLUDED_PREFIXES = ("tests/",)
TEXT_SUFFIXES = {
    ".c",
    ".h",
    ".html",
    ".js",
    ".json",
    ".jsonl",
    ".md",
    ".mjs",
    ".plist",
    ".patch",
    ".py",
    ".sh",
    ".swift",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}


def audit_public_release(
    root: str | Path,
    *,
    tracked_files: Iterable[str] | None = None,
    candidate_files: Iterable[str] | None = None,
    dirty: bool | None = None,
    release_manifest_path: str | Path = DEFAULT_RELEASE_MANIFEST_PATH,
) -> dict[str, object]:
    repo_root = Path(root).resolve()
    injected_tracked = tracked_files is not None
    tracked = sorted(set(tracked_files if injected_tracked else _git_lines(repo_root, "ls-files")))
    existing = [path for path in tracked if (repo_root / path).is_file()]
    if candidate_files is not None:
        candidates = sorted(set(candidate_files))
    elif injected_tracked:
        candidates = list(existing)
    else:
        untracked = _git_lines(repo_root, "ls-files", "--others", "--exclude-standard")
        candidates = sorted(set(existing) | {path for path in untracked if (repo_root / path).is_file()})
    untracked_candidates = [path for path in candidates if path not in tracked]
    missing_tracked = [path for path in tracked if not (repo_root / path).exists()]
    forbidden = [path for path in existing if _forbidden_public_path(path)]
    forbidden_candidates = [path for path in candidates if _forbidden_public_path(path)]
    secret_hits = _scan_secret_shapes(repo_root, candidates)
    machine_path_hits = _scan_machine_paths(repo_root, candidates)
    required_missing = [path for path in REQUIRED_FILES if not (repo_root / path).is_file()]
    required_untracked = [path for path in REQUIRED_FILES if (repo_root / path).is_file() and path not in tracked]
    license_files = [name for name in LICENSE_NAMES if (repo_root / name).is_file()]
    dirty_state = bool(_git_status(repo_root)) if dirty is None else bool(dirty)
    product_status, product_status_error = _load_product_status(repo_root)
    release_manifest = audit_release_manifest(repo_root, release_manifest_path)
    repository_blockers: list[dict[str, object]] = []
    if required_missing:
        repository_blockers.append(
            {"id": "required_public_files_missing", "paths": required_missing}
        )
    if required_untracked:
        repository_blockers.append(
            {"id": "required_public_files_untracked", "paths": required_untracked}
        )
    if not license_files:
        repository_blockers.append(
            {"id": "top_level_license_missing", "paths": list(LICENSE_NAMES)}
        )
    if forbidden:
        repository_blockers.append(
            {"id": "forbidden_tracked_artifacts", "paths": forbidden}
        )
    if forbidden_candidates:
        repository_blockers.append(
            {
                "id": "forbidden_candidate_artifacts",
                "paths": forbidden_candidates,
            }
        )
    if secret_hits:
        repository_blockers.append(
            {"id": "possible_secret_shapes", "hits": secret_hits}
        )
    if machine_path_hits:
        repository_blockers.append(
            {"id": "machine_specific_paths", "hits": machine_path_hits}
        )
    if dirty_state:
        repository_blockers.append({"id": "working_tree_dirty"})
    if product_status_error:
        repository_blockers.append(
            {"id": "product_status_invalid", "detail": product_status_error}
        )

    distribution_blockers: list[dict[str, object]] = []
    if not product_status_error and product_status:
        evidence = product_status.get("foregroundEvidence")
        foreground = evidence if isinstance(evidence, dict) else {}
        if product_status.get("productStatus") != "foreground_verified" or foreground.get("strictSoakPassed") is not True:
            distribution_blockers.append({"id": "foreground_acceptance_pending"})
        if product_status.get("releaseStatus") != "ready":
            distribution_blockers.append({"id": "release_status_declared_blocked"})
    if release_manifest["status"] == "missing":
        distribution_blockers.append(
            {"id": "release_manifest_missing", "path": release_manifest["path"]}
        )
    elif release_manifest["status"] != "valid":
        distribution_blockers.append(
            {
                "id": "release_manifest_invalid",
                "path": release_manifest["path"],
                "issues": release_manifest["issues"],
            }
        )
    blockers = [*repository_blockers, *distribution_blockers]
    repository_ready = not repository_blockers
    distribution_ready = not blockers
    total_bytes = sum((repo_root / path).stat().st_size for path in existing)
    return {
        "schemaVersion": SCHEMA_VERSION,
        # `ok` retains its v2 meaning: a distributable macOS release is ready.
        # A source repository can be safe to make public while signing,
        # notarization, foreground acceptance, or a binary manifest is pending.
        "ok": distribution_ready,
        "repositoryReady": repository_ready,
        "distributionReady": distribution_ready,
        "root": str(repo_root),
        "trackedFileCount": len(existing),
        "trackedBytes": total_bytes,
        "candidateFileCount": len(candidates),
        "untrackedCandidateCount": len(untracked_candidates),
        "workingTreeDirty": dirty_state,
        "licenseFiles": license_files,
        "requiredMissing": required_missing,
        "requiredUntracked": required_untracked,
        "forbiddenTracked": forbidden,
        "forbiddenCandidates": forbidden_candidates,
        "missingTracked": missing_tracked,
        "secretShapeHits": secret_hits,
        "machinePathHits": machine_path_hits,
        "productStatus": {
            "productStatus": product_status.get("productStatus") if product_status else None,
            "releaseStatus": product_status.get("releaseStatus") if product_status else None,
            "strictSoakPassed": (
                product_status.get("foregroundEvidence", {}).get("strictSoakPassed")
                if product_status and isinstance(product_status.get("foregroundEvidence"), dict)
                else None
            ),
        },
        "releaseManifest": release_manifest,
        "repositoryBlockers": repository_blockers,
        "distributionBlockers": distribution_blockers,
        "blockers": blockers,
        "notes": [
            "Missing tracked files are reported separately because a pending deletion is not removed from HEAD until committed.",
            "This shape scan is a release guard, not a substitute for provider-side credential rotation.",
            "Candidate scans include tracked files plus non-ignored untracked files so a clean commit cannot introduce an unaudited artifact.",
            "repositoryReady covers public source hygiene; distributionReady additionally requires foreground acceptance and a verified macOS release manifest.",
            "Product-status release flags are declarations only; release readiness also requires a valid, hash-verified release manifest.",
        ],
    }


def audit_release_manifest(root: str | Path, manifest_path: str | Path = DEFAULT_RELEASE_MANIFEST_PATH) -> dict[str, object]:
    """Validate generated release artifacts and evidence without trusting status booleans."""

    repo_root = Path(root).resolve()
    manifest_file, path_issue = _resolve_repo_path(repo_root, manifest_path)
    display_path = str(manifest_path).replace("\\", "/")
    if path_issue:
        return {
            "schemaVersion": RELEASE_MANIFEST_SCHEMA_VERSION,
            "path": display_path,
            "status": "invalid",
            "releaseId": None,
            "sourceCommit": None,
            "artifacts": [],
            "evidence": {},
            "issues": [path_issue],
        }
    assert manifest_file is not None
    try:
        payload = json.loads(manifest_file.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {
            "schemaVersion": RELEASE_MANIFEST_SCHEMA_VERSION,
            "path": display_path,
            "status": "missing",
            "releaseId": None,
            "sourceCommit": None,
            "artifacts": [],
            "evidence": {},
            "issues": [],
        }
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "schemaVersion": RELEASE_MANIFEST_SCHEMA_VERSION,
            "path": display_path,
            "status": "invalid",
            "releaseId": None,
            "sourceCommit": None,
            "artifacts": [],
            "evidence": {},
            "issues": [{"id": "manifest_unreadable", "detail": type(exc).__name__}],
        }

    issues: list[dict[str, object]] = []
    if not isinstance(payload, dict):
        payload = {}
        issues.append({"id": "manifest_not_object"})
    if payload.get("schemaVersion") != RELEASE_MANIFEST_SCHEMA_VERSION:
        issues.append({"id": "manifest_schema_unsupported", "field": "schemaVersion"})
    if payload.get("templateOnly") is True:
        issues.append({"id": "manifest_template_not_release", "field": "templateOnly"})
    release_id = payload.get("releaseId")
    if not isinstance(release_id, str) or not release_id.strip():
        issues.append({"id": "manifest_field_invalid", "field": "releaseId"})
    source_commit = payload.get("sourceCommit")
    if not isinstance(source_commit, str) or re.fullmatch(r"[0-9a-f]{40}", source_commit) is None:
        issues.append({"id": "manifest_field_invalid", "field": "sourceCommit"})
    else:
        head = _git_head(repo_root)
        if head and source_commit != head:
            issues.append(
                {
                    "id": "source_commit_mismatch",
                    "field": "sourceCommit",
                    "expected": head,
                    "actual": source_commit,
                }
            )

    artifact_reports: list[dict[str, object]] = []
    artifact_by_id: dict[str, dict[str, object]] = {}
    raw_artifacts = payload.get("artifacts")
    if not isinstance(raw_artifacts, list):
        raw_artifacts = []
        issues.append({"id": "manifest_field_invalid", "field": "artifacts"})
    for index, raw_artifact in enumerate(raw_artifacts):
        report, artifact_issues = _audit_manifest_file_record(
            repo_root,
            raw_artifact,
            record_type="artifact",
            index=index,
            require_size=True,
        )
        artifact_reports.append(report)
        issues.extend(artifact_issues)
        artifact_id = report.get("id")
        if isinstance(artifact_id, str) and artifact_id:
            if artifact_id in artifact_by_id:
                issues.append({"id": "artifact_id_duplicate", "artifactId": artifact_id})
            else:
                artifact_by_id[artifact_id] = report

    present_kinds = {str(item.get("kind")) for item in artifact_reports if item.get("ok") is True}
    for kind in sorted(REQUIRED_ARTIFACT_KINDS - present_kinds):
        issues.append({"id": "required_artifact_kind_missing", "kind": kind})

    evidence_reports: dict[str, dict[str, object]] = {}
    raw_evidence = payload.get("evidence")
    if not isinstance(raw_evidence, dict):
        raw_evidence = {}
        issues.append({"id": "manifest_field_invalid", "field": "evidence"})
    for evidence_id, (expected_result, expected_kind) in REQUIRED_RELEASE_EVIDENCE.items():
        raw_record = raw_evidence.get(evidence_id)
        if not isinstance(raw_record, dict):
            issues.append({"id": "required_evidence_missing", "evidenceId": evidence_id})
            continue
        report, evidence_issues = _audit_manifest_file_record(
            repo_root,
            raw_record,
            record_type="evidence",
            record_id=evidence_id,
            require_size=False,
        )
        evidence_reports[evidence_id] = report
        issues.extend(evidence_issues)
        report["result"] = raw_record.get("result")
        if raw_record.get("result") != expected_result:
            report["ok"] = False
            issues.append(
                {
                    "id": "evidence_result_invalid",
                    "evidenceId": evidence_id,
                    "expected": expected_result,
                    "actual": raw_record.get("result"),
                }
            )
        artifact_id = raw_record.get("artifactId")
        if expected_kind is not None:
            artifact = artifact_by_id.get(str(artifact_id))
            if artifact is None:
                report["ok"] = False
                issues.append(
                    {"id": "evidence_artifact_missing", "evidenceId": evidence_id, "artifactId": artifact_id}
                )
            elif artifact.get("kind") != expected_kind:
                report["ok"] = False
                issues.append(
                    {
                        "id": "evidence_artifact_kind_mismatch",
                        "evidenceId": evidence_id,
                        "expected": expected_kind,
                        "actual": artifact.get("kind"),
                    }
                )
            else:
                evidence_artifact_digest = raw_record.get("artifactSha256")
                artifact_digest = artifact.get("actualSha256")
                if evidence_artifact_digest != artifact_digest:
                    report["ok"] = False
                    issues.append(
                        {
                            "id": "evidence_artifact_sha256_mismatch",
                            "evidenceId": evidence_id,
                            "artifactId": artifact_id,
                            "expected": artifact_digest,
                            "actual": evidence_artifact_digest,
                        }
                    )

    return {
        "schemaVersion": RELEASE_MANIFEST_SCHEMA_VERSION,
        "path": display_path,
        "status": "valid" if not issues else "invalid",
        "releaseId": release_id if isinstance(release_id, str) else None,
        "sourceCommit": source_commit if isinstance(source_commit, str) else None,
        "artifacts": artifact_reports,
        "evidence": evidence_reports,
        "issues": issues,
    }


def _audit_manifest_file_record(
    root: Path,
    raw_record: object,
    *,
    record_type: str,
    index: int | None = None,
    record_id: str | None = None,
    require_size: bool,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    issues: list[dict[str, object]] = []
    location: dict[str, object] = {"recordType": record_type}
    if index is not None:
        location["index"] = index
    if record_id is not None:
        location["evidenceId"] = record_id
    if not isinstance(raw_record, dict):
        return {"ok": False}, [{"id": f"{record_type}_record_invalid", **location}]

    item_id = raw_record.get("id") if record_type == "artifact" else record_id
    kind = raw_record.get("kind") if record_type == "artifact" else None
    if record_type == "artifact":
        if not isinstance(item_id, str) or not item_id:
            issues.append({"id": "artifact_field_invalid", "field": "id", **location})
        if not isinstance(kind, str) or not kind:
            issues.append({"id": "artifact_field_invalid", "field": "kind", **location})

    relative_path = raw_record.get("path")
    file_path, path_issue = _resolve_repo_path(root, relative_path)
    if path_issue:
        issues.append({**path_issue, **location})
    expected_digest = raw_record.get("sha256")
    if not isinstance(expected_digest, str) or re.fullmatch(r"[0-9a-f]{64}", expected_digest) is None:
        issues.append({"id": f"{record_type}_sha256_invalid", **location})
    expected_size = raw_record.get("sizeBytes")
    if require_size and (not isinstance(expected_size, int) or isinstance(expected_size, bool) or expected_size <= 0):
        issues.append({"id": "artifact_size_invalid", **location})

    actual_digest: str | None = None
    actual_size: int | None = None
    if file_path is not None and path_issue is None:
        if not file_path.is_file():
            issues.append({"id": f"{record_type}_file_missing", "path": str(relative_path), **location})
        else:
            actual_size = file_path.stat().st_size
            actual_digest = _sha256_file(file_path)
            if record_type == "evidence" and actual_size == 0:
                issues.append({"id": "evidence_file_empty", "path": str(relative_path), **location})
            if isinstance(expected_digest, str) and actual_digest != expected_digest:
                issues.append(
                    {
                        "id": f"{record_type}_sha256_mismatch",
                        "path": str(relative_path),
                        "expected": expected_digest,
                        "actual": actual_digest,
                        **location,
                    }
                )
            if require_size and isinstance(expected_size, int) and not isinstance(expected_size, bool):
                if actual_size != expected_size:
                    issues.append(
                        {
                            "id": "artifact_size_mismatch",
                            "path": str(relative_path),
                            "expected": expected_size,
                            "actual": actual_size,
                            **location,
                        }
                    )

    return (
        {
            "id": item_id,
            "kind": kind,
            "path": relative_path,
            "expectedSha256": expected_digest,
            "actualSha256": actual_digest,
            "expectedSizeBytes": expected_size if require_size else None,
            "actualSizeBytes": actual_size,
            "ok": not issues,
        },
        issues,
    )


def _resolve_repo_path(root: Path, relative: object) -> tuple[Path | None, dict[str, object] | None]:
    if not isinstance(relative, (str, Path)) or not str(relative):
        return None, {"id": "release_path_invalid", "path": relative}
    candidate = Path(relative)
    if candidate.is_absolute():
        return None, {"id": "release_path_outside_root", "path": str(relative)}
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        return None, {"id": "release_path_outside_root", "path": str(relative)}
    return resolved, None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_head(root: Path) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


def _load_product_status(root: Path) -> tuple[dict[str, object], str]:
    path = root / "release" / "product-status.json"
    if not path.is_file():
        return {}, ""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {}, f"release/product-status.json could not be read: {type(exc).__name__}"
    if not isinstance(payload, dict) or payload.get("schemaVersion") != "rag-ime.product-status.v1":
        return {}, "release/product-status.json has an unsupported schema"
    return payload, ""


def write_public_release_report(report: dict[str, object], path: str | Path) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _forbidden_public_path(path: str) -> bool:
    normalized = path.replace("\\", "/")
    parts = set(Path(normalized).parts)
    name = Path(normalized).name
    return (
        any(normalized.startswith(prefix) for prefix in FORBIDDEN_PREFIXES)
        or bool(parts & FORBIDDEN_PARTS)
        or name in FORBIDDEN_NAMES
        or name.endswith(".userdb")
        or any(name.endswith(suffix) for suffix in FORBIDDEN_SUFFIXES)
        or bool(HANDOFF_PATTERN.search(normalized))
    )


def _scan_secret_shapes(root: Path, files: Iterable[str]) -> list[dict[str, object]]:
    hits: list[dict[str, object]] = []
    for relative in files:
        path = root / relative
        if path.suffix.lower() not in TEXT_SUFFIXES or path.stat().st_size > 2_500_000:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            if any(marker in line.lower() for marker in SECRET_FIXTURE_MARKERS):
                continue
            for kind, pattern in SECRET_PATTERNS:
                match = pattern.search(line)
                if match is None:
                    continue
                digest = hashlib.sha256(match.group(0).encode("utf-8")).hexdigest()[:12]
                hits.append({"path": relative, "line": line_number, "kind": kind, "valueHash": f"sha256:{digest}"})
    return hits


def _scan_machine_paths(root: Path, files: Iterable[str]) -> list[dict[str, object]]:
    hits: list[dict[str, object]] = []
    for relative in files:
        normalized = relative.replace("\\", "/")
        if normalized.startswith(MACHINE_PATH_SCAN_EXCLUDED_PREFIXES):
            continue
        path = root / relative
        if path.suffix.lower() not in TEXT_SUFFIXES or path.stat().st_size > 2_500_000:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            for kind, pattern in MACHINE_PATH_PATTERNS:
                match = pattern.search(line)
                if match is None:
                    continue
                digest = hashlib.sha256(match.group(0).encode("utf-8")).hexdigest()[:12]
                hits.append({"path": relative, "line": line_number, "kind": kind, "valueHash": f"sha256:{digest}"})
                break
    return hits


def _git_lines(root: Path, *args: str) -> list[str]:
    completed = subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return [line for line in completed.stdout.splitlines() if line]


def _git_status(root: Path) -> str:
    completed = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()
