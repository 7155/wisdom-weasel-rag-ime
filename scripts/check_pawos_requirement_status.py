#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "pawos.requirement-status.v1"
STATUS_BEGIN = "<!-- PAWOS_REQUIREMENT_STATUS_JSON_BEGIN -->"
STATUS_END = "<!-- PAWOS_REQUIREMENT_STATUS_JSON_END -->"
REQUIREMENT_PATTERN = re.compile(r"^### (UR-(\d{3}))\b", re.MULTILINE)
SHA256_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
EVIDENCE_LEVELS = {
    "E1": "Source",
    "E2": "Test",
    "E3": "Build",
    "E4": "Install",
    "E5": "Runtime",
    "E6": "Foreground",
}
ASSESSMENTS = {"unassessed", "in_progress", "blocked", "complete", "cancelled", "not_applicable"}
RUNS_VERDICTS = {"unverified", "passed", "failed", "blocked", "not_applicable"}
REQUIREMENT_VERDICTS = {"unverified", "satisfied", "not_satisfied", "blocked", "not_applicable"}


def extract_status_payload(text: str) -> dict[str, Any]:
    if text.count(STATUS_BEGIN) != 1 or text.count(STATUS_END) != 1:
        raise ValueError("status document must contain exactly one machine-readable JSON block")
    block = text.split(STATUS_BEGIN, 1)[1].split(STATUS_END, 1)[0].strip()
    match = re.fullmatch(r"```json\s*(.*?)\s*```", block, re.DOTALL)
    if match is None:
        raise ValueError("status JSON block must be fenced as ```json")
    payload = json.loads(match.group(1))
    if not isinstance(payload, dict):
        raise ValueError("status JSON must contain an object")
    return payload


def requirement_ids(text: str) -> tuple[list[str], list[str]]:
    matches = list(REQUIREMENT_PATTERN.finditer(text))
    ids = [match.group(1) for match in matches]
    errors: list[str] = []
    duplicates = sorted(requirement_id for requirement_id, count in Counter(ids).items() if count > 1)
    if duplicates:
        errors.append(f"duplicate requirement headings: {', '.join(duplicates)}")
    for position, requirement_id in enumerate(ids, start=1):
        expected = f"UR-{position:03d}"
        if requirement_id != expected:
            errors.append(
                f"requirements headings are not continuous: expected {expected}, found {requirement_id}"
            )
            break
    if not ids:
        errors.append("requirements document contains no UR headings")
    return ids, errors


def _validate_receipts(receipts: object, errors: list[str]) -> dict[str, dict[str, Any]]:
    if not isinstance(receipts, dict):
        errors.append("receipts must be an object")
        return {}
    checked: dict[str, dict[str, Any]] = {}
    for receipt_id, raw_receipt in receipts.items():
        prefix = f"receipt {receipt_id}"
        if not isinstance(receipt_id, str) or not receipt_id.startswith("RCP-"):
            errors.append(f"{prefix}: id must start with RCP-")
        if not isinstance(raw_receipt, dict):
            errors.append(f"{prefix}: value must be an object")
            continue
        checked[str(receipt_id)] = raw_receipt
        if raw_receipt.get("level") not in EVIDENCE_LEVELS:
            errors.append(f"{prefix}: unsupported evidence level {raw_receipt.get('level')}")
        for field in ("recordedAt", "owner", "claim"):
            if not isinstance(raw_receipt.get(field), str) or not str(raw_receipt[field]).strip():
                errors.append(f"{prefix}: {field} is required")
        artifact_refs = raw_receipt.get("artifactRefs")
        if not isinstance(artifact_refs, list) or not artifact_refs or not all(
            isinstance(value, str) and value.strip() for value in artifact_refs
        ):
            errors.append(f"{prefix}: artifactRefs must be a non-empty string list")
        digest = raw_receipt.get("sha256")
        if not isinstance(digest, str) or SHA256_PATTERN.fullmatch(digest) is None:
            errors.append(f"{prefix}: sha256 must use sha256:<64 lowercase hex>")
    return checked


def _merged_status(defaults: dict[str, Any], override: object, requirement_id: str, errors: list[str]) -> dict[str, Any]:
    if not isinstance(override, dict):
        errors.append(f"{requirement_id}: status override must be an object")
        return dict(defaults)
    unknown_fields = sorted(
        set(override)
        - {
            "assessment",
            "runsVerdict",
            "requirementVerdict",
            "evidenceRefs",
            "requiredEvidenceLevels",
            "owner",
            "updatedAt",
            "nextAction",
            "note",
        }
    )
    if unknown_fields:
        errors.append(f"{requirement_id}: unsupported fields: {', '.join(unknown_fields)}")
    return {**defaults, **override}


def validate_requirement_status(requirements_path: Path, status_path: Path) -> dict[str, Any]:
    requirements_bytes = requirements_path.read_bytes()
    requirements_text = requirements_bytes.decode("utf-8")
    ids, errors = requirement_ids(requirements_text)
    try:
        payload = extract_status_payload(status_path.read_text(encoding="utf-8"))
    except (ValueError, json.JSONDecodeError) as exc:
        errors.append(str(exc))
        payload = {}

    if payload.get("schemaVersion") != SCHEMA_VERSION:
        errors.append(f"schemaVersion must be {SCHEMA_VERSION}")

    source_receipt = payload.get("sourceReceipt")
    if not isinstance(source_receipt, dict):
        errors.append("sourceReceipt must be an object")
    else:
        if source_receipt.get("path") != requirements_path.name:
            errors.append(f"sourceReceipt.path must be {requirements_path.name}")
        expected_hash = "sha256:" + hashlib.sha256(requirements_bytes).hexdigest()
        if source_receipt.get("sha256") != expected_hash:
            errors.append(
                "sourceReceipt.sha256 does not match the current requirements document; "
                f"expected {expected_hash}"
            )

    if payload.get("evidenceLevelLabels") != EVIDENCE_LEVELS:
        errors.append("evidenceLevelLabels must define E1 Source through E6 Foreground exactly")

    defaults = payload.get("defaults")
    if not isinstance(defaults, dict):
        errors.append("defaults must be an object")
        defaults = {}
    required_defaults = {
        "assessment": "unassessed",
        "runsVerdict": "unverified",
        "requirementVerdict": "unverified",
        "evidenceRefs": [],
    }
    if defaults != required_defaults:
        errors.append("defaults must be the conservative unassessed/unverified baseline")

    receipts = _validate_receipts(payload.get("receipts"), errors)
    entries = payload.get("requirements")
    if not isinstance(entries, dict):
        errors.append("requirements must be an object")
        entries = {}
    missing = [requirement_id for requirement_id in ids if requirement_id not in entries]
    extra = [requirement_id for requirement_id in entries if requirement_id not in ids]
    if missing:
        errors.append(f"status index is missing requirements: {', '.join(missing)}")
    if extra:
        errors.append(f"status index has unknown requirements: {', '.join(extra)}")

    assessment_counts: Counter[str] = Counter()
    complete_count = 0
    for requirement_id in ids:
        status = _merged_status(defaults, entries.get(requirement_id, {}), requirement_id, errors)
        assessment = status.get("assessment")
        runs_verdict = status.get("runsVerdict")
        requirement_verdict = status.get("requirementVerdict")
        evidence_refs = status.get("evidenceRefs")
        required_evidence_levels = status.get("requiredEvidenceLevels")
        if assessment not in ASSESSMENTS:
            errors.append(f"{requirement_id}: unsupported assessment {assessment}")
        else:
            assessment_counts[str(assessment)] += 1
        if runs_verdict not in RUNS_VERDICTS:
            errors.append(f"{requirement_id}: unsupported runsVerdict {runs_verdict}")
        if requirement_verdict not in REQUIREMENT_VERDICTS:
            errors.append(f"{requirement_id}: unsupported requirementVerdict {requirement_verdict}")
        if not isinstance(evidence_refs, list) or not all(isinstance(value, str) for value in evidence_refs):
            errors.append(f"{requirement_id}: evidenceRefs must be a string list")
            evidence_refs = []
        missing_receipts = [receipt_id for receipt_id in evidence_refs if receipt_id not in receipts]
        if missing_receipts:
            errors.append(f"{requirement_id}: unknown evidence receipts: {', '.join(missing_receipts)}")
        if assessment == "complete":
            complete_count += 1
            if runs_verdict != "passed":
                errors.append(f"{requirement_id}: complete requires runsVerdict=passed")
            if requirement_verdict != "satisfied":
                errors.append(f"{requirement_id}: complete requires requirementVerdict=satisfied")
            if not evidence_refs:
                errors.append(f"{requirement_id}: complete requires at least one evidence receipt")
            if (
                not isinstance(required_evidence_levels, list)
                or not required_evidence_levels
                or not all(isinstance(level, str) for level in required_evidence_levels)
            ):
                errors.append(f"{requirement_id}: complete requires explicit requiredEvidenceLevels")
                required_evidence_levels = []
            invalid_levels = [level for level in required_evidence_levels if level not in EVIDENCE_LEVELS]
            if invalid_levels:
                errors.append(
                    f"{requirement_id}: unsupported required evidence levels: {', '.join(invalid_levels)}"
                )
            receipt_levels = {
                receipts[receipt_id].get("level")
                for receipt_id in evidence_refs
                if receipt_id in receipts
            }
            missing_levels = [level for level in required_evidence_levels if level not in receipt_levels]
            if missing_levels:
                errors.append(
                    f"{requirement_id}: missing receipts for required evidence levels: "
                    f"{', '.join(missing_levels)}"
                )
            for field in ("owner", "updatedAt", "note"):
                if not isinstance(status.get(field), str) or not str(status[field]).strip():
                    errors.append(f"{requirement_id}: complete requires {field}")

    return {
        "schemaVersion": "pawos.requirement-status-check.v1",
        "ok": not errors,
        "requirementsPath": str(requirements_path.resolve()),
        "statusPath": str(status_path.resolve()),
        "requirementCount": len(ids),
        "firstRequirementId": ids[0] if ids else None,
        "lastRequirementId": ids[-1] if ids else None,
        "assessmentCounts": dict(sorted(assessment_counts.items())),
        "completeCount": complete_count,
        "receiptCount": len(receipts),
        "errors": errors,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the PAWOS requirement status index.")
    parser.add_argument(
        "--requirements",
        default="control-center-web/docs/pawos/PAWOS_REQUIREMENTS.md",
    )
    parser.add_argument(
        "--status",
        default="control-center-web/docs/pawos/PAWOS_REQUIREMENT_STATUS.md",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = validate_requirement_status(Path(args.requirements), Path(args.status))
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("OK" if report["ok"] else "FAILED")
        print(
            f"requirements={report['requirementCount']} complete={report['completeCount']} "
            f"assessments={report['assessmentCounts']} receipts={report['receiptCount']}"
        )
        for error in report["errors"]:
            print(f"- {error}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
