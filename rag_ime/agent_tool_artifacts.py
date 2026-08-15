from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
from urllib.parse import quote

from .agent_media import AgentMediaStore


_TEXT_MIME_BY_SUFFIX = {
    ".diff": "text/x-diff",
    ".htm": "text/html",
    ".html": "text/html",
    ".markdown": "text/markdown",
    ".md": "text/markdown",
    ".mdx": "text/markdown",
    ".patch": "text/x-patch",
}


@dataclass(frozen=True)
class ToolArtifactProjection:
    blocks: tuple[dict[str, object], ...] = ()
    status: str = "unavailable"
    reason: str = ""

    def receipt_fields(self) -> dict[str, object]:
        projection: dict[str, object] = {
            "status": self.status,
            "count": len(self.blocks),
        }
        if self.reason:
            projection["reason"] = self.reason
        payload: dict[str, object] = {
            "artifactProjection": projection
        }
        if self.blocks:
            payload["agentBlocks"] = [dict(block) for block in self.blocks]
        return payload


class AgentToolArtifactProjector:
    """Turn verified workspace mutations into Session-scoped file receipts.

    The mutation remains authoritative even when this optional presentation
    projection cannot be created. That prevents a post-write preview failure
    from making an applied approval look as if the write itself failed.
    """

    def __init__(self, media: AgentMediaStore) -> None:
        self.media = media

    def project_workspace_patch(
        self,
        *,
        session: Mapping[str, object],
        approval_id: str,
        receipt: Mapping[str, object],
        preview: Mapping[str, object],
    ) -> ToolArtifactProjection:
        return self.project_workspace_mutation(
            session=session,
            approval_id=approval_id,
            receipt=receipt,
            preview=preview,
            origin_tool="workspace_patch",
        )

    def project_workspace_read(
        self,
        *,
        session: Mapping[str, object],
        receipt: Mapping[str, object],
    ) -> ToolArtifactProjection:
        """Publish an explicitly requested workspace preview as a managed file.

        Ordinary reads stay ordinary Tool results. The caller opts into this
        projection only when the user asked to open, preview, or deliver the
        file, so source inspection does not flood the final answer with cards.
        """

        try:
            path = str(receipt.get("path") or "").strip()
            revision = str(receipt.get("resourceRevision") or "").strip()
            if not path or not revision.startswith("sha256:"):
                raise ValueError("workspace read receipt is incomplete")
            target = _authorized_regular_file(Path(path), session.get("workspaceRoots"))
            raw = _read_verified_revision(target, revision.removeprefix("sha256:"))
            session_id = str(session.get("id") or "").strip()
            if not session_id:
                raise ValueError("workspace artifact Session is missing")
            media_receipt = self.media.import_bytes(
                session_id=session_id,
                data=raw,
                mime_type=_text_mime_for(target.name),
                file_name=target.name,
                origin="tool_result",
                origin_tool="workspace_read",
                origin_receipt_id=revision,
            )
            return ToolArtifactProjection(
                blocks=(_file_block(media_receipt, kind="file"),),
                status="available",
            )
        except (OSError, TypeError, ValueError):
            return ToolArtifactProjection(status="unavailable", reason="verification_failed")

    def project_workspace_mutation(
        self,
        *,
        session: Mapping[str, object],
        approval_id: str,
        receipt: Mapping[str, object],
        preview: Mapping[str, object],
        origin_tool: str,
    ) -> ToolArtifactProjection:
        try:
            return self._project_workspace_mutation(
                session=session,
                approval_id=approval_id,
                receipt=receipt,
                preview=preview,
                origin_tool=origin_tool,
            )
        except (OSError, TypeError, ValueError):
            return ToolArtifactProjection(status="unavailable", reason="verification_failed")

    def _project_workspace_mutation(
        self,
        *,
        session: Mapping[str, object],
        approval_id: str,
        receipt: Mapping[str, object],
        preview: Mapping[str, object],
        origin_tool: str,
    ) -> ToolArtifactProjection:
        if receipt.get("mutationApplied") is not True:
            return ToolArtifactProjection(status="unavailable", reason="mutation_not_applied")

        action = preview.get("actionPayload")
        if not isinstance(action, Mapping):
            raise ValueError("workspace patch preview is missing its action payload")
        preview_path = str(action.get("path") or "").strip()
        receipt_path = str(receipt.get("path") or "").strip()
        if not preview_path or receipt_path != preview_path:
            raise ValueError("workspace patch path changed after approval")

        target = _authorized_regular_file(Path(receipt_path), session.get("workspaceRoots"))
        raw = _read_verified_postimage(target, receipt)
        session_id = str(session.get("id") or "").strip()
        if not session_id:
            raise ValueError("workspace artifact Session is missing")

        candidates = [(target.name, _text_mime_for(target.name), raw, "file")]
        diff = _approved_diff(preview)
        if diff:
            candidates.append((f"{target.name}.diff", "text/x-diff", diff.encode("utf-8"), "diff"))

        blocks: list[dict[str, object]] = []
        for file_name, mime_type, data, kind in candidates:
            try:
                media_receipt = self.media.import_bytes(
                    session_id=session_id,
                    data=data,
                    mime_type=mime_type,
                    file_name=file_name,
                    origin="tool_result",
                    origin_tool=origin_tool,
                    origin_receipt_id=approval_id,
                )
            except (OSError, TypeError, ValueError):
                continue
            blocks.append(_file_block(media_receipt, kind=kind))

        if not blocks:
            return ToolArtifactProjection(status="unavailable", reason="no_previewable_artifact")
        return ToolArtifactProjection(blocks=tuple(blocks), status="available")


def _authorized_regular_file(path: Path, raw_roots: object) -> Path:
    if path.is_symlink():
        raise ValueError("workspace artifact cannot be a symlink")
    target = path.expanduser().resolve(strict=True)
    roots = raw_roots if isinstance(raw_roots, list) else []
    authorized = False
    for raw_root in roots:
        root_path = Path(str(raw_root)).expanduser()
        if root_path.is_symlink():
            continue
        root = root_path.resolve(strict=True)
        if target == root or root in target.parents:
            authorized = True
            break
    if not authorized:
        raise ValueError("workspace artifact is outside the authorized roots")
    if target.is_symlink() or not target.is_file():
        raise ValueError("workspace artifact must be a regular file")
    return target


def _read_verified_postimage(path: Path, receipt: Mapping[str, object]) -> bytes:
    expected = str(receipt.get("postimageSha256") or "").strip().lower()
    return _read_verified_revision(path, expected)


def _read_verified_revision(path: Path, expected: str) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size <= 0 or metadata.st_size > 2 * 1024 * 1024:
            raise ValueError("workspace artifact size is not previewable")
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            raw = handle.read(2 * 1024 * 1024 + 1)
    finally:
        os.close(descriptor)
    if len(raw) != metadata.st_size or len(raw) > 2 * 1024 * 1024:
        raise ValueError("workspace artifact changed while being read")
    if not expected or hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError("workspace artifact no longer matches the verified receipt")
    raw.decode("utf-8")
    return raw


def _approved_diff(preview: Mapping[str, object]) -> str:
    changes = preview.get("changes")
    if not isinstance(changes, list):
        return ""
    for value in changes:
        if not isinstance(value, Mapping) or value.get("label") != "差异":
            continue
        diff = str(value.get("after") or "")
        if diff and len(diff.encode("utf-8")) <= 131_072:
            return diff
    return ""


def _text_mime_for(file_name: str) -> str:
    return _TEXT_MIME_BY_SUFFIX.get(Path(file_name).suffix.lower(), "text/plain")


def _file_block(receipt: Mapping[str, object], *, kind: str) -> dict[str, object]:
    media_id = str(receipt["mediaId"])
    session_id = str(receipt["sessionId"])
    sha256 = str(receipt["sha256"])
    return {
        "id": f"tool-artifact:{kind}:{sha256[:16]}",
        "type": "file",
        "data": {
            "mediaId": media_id,
            "sessionId": session_id,
            "fileName": str(receipt.get("fileName") or "artifact"),
            "mimeType": str(receipt["mimeType"]),
            "byteSize": int(receipt["byteSize"]),
            "sha256": sha256,
            "receiptUrl": (
                f"/api/agent/media/{quote(media_id, safe='')}/content"
                f"?sessionId={quote(session_id, safe='')}"
            ),
        },
    }
