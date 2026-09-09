"""Apply a validated Trace candidate through its existing resource owner.

Only the App's final explicit action reaches this bridge. A model can register
source versions and propose candidates, but cannot supply an installation path,
an outcome, or an application receipt here. The first durable reservation is
written before any owner mutation; uncertain reservations are never replayed.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path

from .db import sqlite_connection
from .trace_optimization_versions import digest, text

_ACTIONS = {"apply", "replace", "install"}
_IDENTITY_FIELDS = ("candidateId", "reportId", "targetKind", "targetRef", "parentVersionRef", "candidateVersionRef")


def _mapping(value, name):
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} owner returned no bound receipt")
    return dict(value)


def _pending_receipt(versions, request_key):
    # The version owner only exposes receipt lookup by ref. This read resolves
    # its existing unique request key without creating another ledger or state.
    versions.initialize()
    with sqlite_connection(versions.db_path) as conn:
        row = conn.execute("SELECT receipt_ref FROM trace_optimization_application_receipts WHERE request_key=?", (request_key,)).fetchone()
    return versions.application_receipt(row[0]) if row else None


def _assert_no_uncertain_application(versions, candidate_id):
    with sqlite_connection(versions.db_path) as conn:
        row = conn.execute("""SELECT receipt_ref FROM trace_optimization_application_receipts
            WHERE json_extract(payload_json,'$.candidateId')=? AND status IN ('applying','interrupted')
            LIMIT 1""", (candidate_id,)).fetchone()
    if row:
        raise ValueError("candidate has an unresolved application receipt; inspect its owner before retrying")


def _response(candidates, receipt, client_request_id, *, replayed):
    application = None
    status = receipt["status"]
    if status in {"applied", "failed", "interrupted"}:
        application = candidates.bind_application(receipt["candidateId"], client_request_id=client_request_id,
            action=receipt["action"], receipt_ref=receipt["receiptRef"])
    return {"ok": status == "applied", "status": status, "receipt": receipt, "application": application,
        "replayed": replayed, "requiresReconciliation": status in {"applying", "interrupted"}}


def _versions_for_candidate(versions, candidate):
    before = versions.get(candidate["parentVersionRef"])
    after = versions.get(candidate["candidateVersionRef"])
    for record, ref in ((before, candidate["parentVersionRef"]), (after, candidate["candidateVersionRef"])):
        if (record["versionRef"] != ref or record["reportId"] != candidate["reportId"]
            or record["targetKind"] != candidate["targetKind"] or record["targetRef"] != candidate["targetRef"]):
            raise ValueError("registered version belongs to another candidate target or report")
    if before["destinationPath"] != after["destinationPath"]:
        raise ValueError("baseline and candidate destinations differ")
    if bool(before["sourceWasFile"]) != bool(after["sourceWasFile"]):
        raise ValueError("baseline and candidate resource types differ")
    return before, after


def _package_manifest(version):
    if version["sourceWasFile"] or "package.json" not in version["manifest"]:
        raise ValueError("directory application requires a registered Pi package.json")
    source = Path(version["snapshotPath"]) / "package.json"
    manifest = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(manifest, Mapping):
        raise ValueError("package.json must contain an object")
    return {"name": text(manifest.get("name"), "package name", 240),
        "version": text(manifest.get("version"), "package version", 240)}


def _prepare_package(extensions, before, after, action):
    if extensions is None:
        raise ValueError("Pi Package installation owner is unavailable")
    baseline_manifest = _package_manifest(before)
    manifest = _package_manifest(after)
    if baseline_manifest["name"] != manifest["name"]:
        raise ValueError("baseline and candidate Pi Package identities differ")
    validation = _mapping(extensions.validate({"packageSource": after["snapshotPath"]}), "Package validation")
    if validation.get("ok") is not True or validation.get("distribution") != "pi_package":
        raise ValueError("candidate was not validated as a native Pi Package")
    extension = _mapping(validation.get("extension"), "Package validation identity")
    plugin_id = text(extension.get("id"), "validated package identity", 240)
    package_digest = text(extension.get("digest"), "validated package digest", 240)
    if extension.get("version") != manifest["version"]:
        raise ValueError("Pi prepared another package version")
    inventory = _mapping(extensions.list(), "Installed package inventory")
    if inventory.get("ok") is not True or inventory.get("runtimeAvailable") is not True:
        raise ValueError("active Pi Package inventory is unavailable")
    matches = [item for item in inventory.get("items", []) if isinstance(item, Mapping) and item.get("id") == plugin_id]
    if action == "install" and matches:
        raise ValueError("this Pi Package is already installed; use the validated replace action")
    if action == "replace":
        baseline = _mapping(extensions.validate({"packageSource": before["snapshotPath"]}), "Parent package validation")
        parent_extension = _mapping(baseline.get("extension"), "Parent package identity")
        if (baseline.get("ok") is not True or baseline.get("distribution") != "pi_package"
            or parent_extension.get("id") != plugin_id or parent_extension.get("version") != baseline_manifest["version"]):
            raise ValueError("Pi parent package identity differs from the registered target")
        parent_digest = text(parent_extension.get("digest"), "parent package digest", 240)
        if (len(matches) != 1 or matches[0].get("digest") != parent_digest
            or matches[0].get("version") != baseline_manifest["version"]):
            raise ValueError("active Pi Package differs from the validated parent version")
    owner_action = "install" if action == "install" else "update"
    preview = _mapping(extensions.preview({"action": owner_action,
        "validationToken": text(validation.get("validationToken"), "validationToken"), "enable": True}), "Package preview")
    if preview.get("ok") is not True or preview.get("requiredConfirm") != "apply":
        raise ValueError("Pi Package preview did not expose the expected application gate")
    summary = _mapping(preview.get("summary"), "Package preview identity")
    if (summary.get("pluginId") != plugin_id or summary.get("version") != manifest["version"]
        or summary.get("action") != owner_action or summary.get("enableAfterInstall") is not True):
        raise ValueError("Pi Package preview differs from the registered candidate")
    payload = {"previewToken": text(preview.get("previewToken"), "previewToken"),
        "payloadSha256": text(preview.get("payloadSha256"), "payloadSha256"), "confirmText": "apply"}
    return payload, {"ownerAction": owner_action, "pluginId": plugin_id, "version": manifest["version"],
        "packageName": manifest["name"], "packageDigest": package_digest}


def _verify_package_receipt(result, expected):
    result = _mapping(result, "Package application")
    if result.get("ok") is not True:
        raise ValueError("Pi Package owner did not return a successful application receipt")
    receipt = _mapping(result.get("receipt"), "Package application")
    plugin = _mapping(receipt.get("plugin"), "Installed package")
    if (receipt.get("action") != expected["ownerAction"] or plugin.get("id") != expected["pluginId"]
        or plugin.get("version") != expected["version"] or plugin.get("digest") != expected["packageDigest"]
        or plugin.get("enabled") is not True):
        raise ValueError("installed package receipt differs from the prepared candidate")
    return {**expected, "owner": "pi_package", "ownerReceiptId": text(receipt.get("receiptId"), "Package receipt ID"),
        "ownerReceiptSha256": digest(receipt), "installedVersion": plugin["version"],
        "installedDigest": plugin["digest"], "enabled": True,
        "rollbackAvailable": receipt.get("rollbackAvailable") is True}


def apply_trace_candidate(versions, candidates, extensions, candidate, action, client_request_id):
    """Return a bound applied/failed/uncertain receipt without replaying effects.

    ``candidate`` is treated only as an identity hint. The current candidate,
    comparison, supported action and source snapshots are read from their host
    stores again. ``client_request_id`` is frozen globally for this owner: reuse
    with another candidate, version, report or action is a conflict.
    """
    if not isinstance(candidate, Mapping):
        raise ValueError("candidate identity is required")
    identifier = text(candidate.get("candidateId"), "candidateId", 240)
    request_id = text(client_request_id, "clientRequestId", 240)
    if action not in _ACTIONS:
        raise ValueError("unsupported candidate application action")
    current = candidates.get_candidate(identifier)
    if current is None:
        raise KeyError(identifier)
    for key in _IDENTITY_FIELDS:
        if key in candidate and candidate[key] != current[key]:
            raise ValueError("candidate identity differs from the current host record")
    request_key = "trace-apply:" + digest(request_id)
    previous = _pending_receipt(versions, request_key)
    if previous is not None:
        expected = {"candidateId": identifier, "reportId": current["reportId"], "targetKind": current["targetKind"],
            "targetRef": current["targetRef"], "versionRef": current["candidateVersionRef"],
            "parentVersionRef": current["parentVersionRef"], "action": action}
        if any(previous.get(key) != value for key, value in expected.items()):
            raise ValueError("application request ID is already bound to different input")
        return _response(candidates, previous, request_id, replayed=True)
    _assert_no_uncertain_application(versions, identifier)
    if action not in current.get("availableActions", []):
        raise ValueError("candidate has no validated owning action available")
    comparisons = [item for item in candidates.read(current["reportId"])["comparisons"] if item["candidateId"] == identifier]
    latest = comparisons[-1] if comparisons else {}
    if latest.get("decision") != "kept" or latest.get("comparable") is not True:
        raise ValueError("candidate needs a real comparable kept result before application")
    before, after = _versions_for_candidate(versions, current)
    if action not in (versions.resolve(current["targetKind"], after["versionRef"]) or {}).get("availableActions", []):
        raise ValueError("registered resource owner does not support this action")
    package = not after["sourceWasFile"]
    if package:
        if action not in {"install", "replace"}:
            raise ValueError("Pi Packages support install or replace")
        _package_manifest(before)
        _package_manifest(after)
    elif action not in {"apply", "replace"}:
        raise ValueError("single files support apply or replace")
    request = {"candidateId": identifier, "reportId": current["reportId"], "comparisonId": latest["comparisonId"],
        "targetKind": current["targetKind"], "targetRef": current["targetRef"], "action": action,
        "versionRef": after["versionRef"], "parentVersionRef": before["versionRef"],
        "parentContentSha256": before["contentSha256"], "candidateContentSha256": after["contentSha256"]}
    receipt, replayed = versions.begin_application(request_key, request)
    if replayed:
        return _response(candidates, receipt, request_id, replayed=True)
    effect_started = False
    try:
        if package:
            payload, expected = _prepare_package(extensions, before, after, action)
            # Preparation may be slow. Detect source drift again immediately
            # before handing the exact retained prepared package to its owner.
            _versions_for_candidate(versions, current)
            effect_started = True
            result = extensions.apply(payload)
            details = _verify_package_receipt(result, expected)
        else:
            before, after = _versions_for_candidate(versions, current)
            # A destination drift is a known failure before replacement. The
            # owner repeats this check inside its atomic file application.
            destination = Path(before["destinationPath"])
            if (destination.is_symlink() or not destination.is_file()
                or hashlib.sha256(destination.read_bytes()).hexdigest() != before["manifest"][before["entryPath"]]):
                raise ValueError("active file differs from the validated parent version")
            effect_started = True
            result = _mapping(versions.apply_file(before, after), "File application")
            if result.get("contentSha256") != after["manifest"][after["entryPath"]] or result.get("replacesVersionRef") != before["versionRef"]:
                raise ValueError("applied file receipt differs from the registered candidate")
            details = {"owner": "project_file", "contentSha256": result["contentSha256"],
                "replacesVersionRef": result["replacesVersionRef"]}
    except Exception as exc:
        # Once the mutation owner is entered, an exception does not prove
        # nothing happened. Preserve uncertainty rather than rerunning it.
        receipt = versions.finish_application(receipt, status="interrupted" if effect_started else "failed",
            details={"owner": "pi_package" if package else "project_file", "phase": "application" if effect_started else "preparation",
                "reasonCode": type(exc).__name__, "message": str(exc)[:1600], "requiresReconciliation": effect_started})
        return _response(candidates, receipt, request_id, replayed=False)
    # If this settlement itself fails, the applying reservation remains. It is
    # intentionally outside the catch: a retry reads that reservation and must
    # reconcile it, never repeat the successful external side effect.
    receipt = versions.finish_application(receipt, status="applied", details=details)
    return _response(candidates, receipt, request_id, replayed=False)
