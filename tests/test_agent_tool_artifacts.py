from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from rag_ime.agent_media import AgentMediaStore
from rag_ime.agent_sessions import AgentSessionStore
from rag_ime.agent_tool_artifacts import AgentToolArtifactProjector
from rag_ime.agent_tool_block_bridge import AgentToolBlockBuffer


class AgentToolArtifactProjectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rag-ime-tool-artifacts-")
        self.root = Path(self.tmp.name)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.media = AgentMediaStore(self.root / "rag-ime.sqlite", root=self.root / "media")
        self.media.initialize()
        self.projector = AgentToolArtifactProjector(self.media)
        sessions = AgentSessionStore(self.root / "rag-ime.sqlite")
        sessions.initialize()
        self.session = sessions.create(
            title="artifact test",
            mode="coordinator",
            workspace_roots=[str(self.workspace)],
            created_at_ms=1,
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_patch_projects_final_file_and_reviewed_diff_as_managed_blocks(self) -> None:
        target = self.workspace / "handoff.md"
        target.write_text("# 已交付\n\n- 测试通过\n", encoding="utf-8")
        raw = target.read_bytes()
        diff = "--- a/handoff.md\n+++ b/handoff.md\n@@ -1 +1,3 @@\n-# 草稿\n+# 已交付\n"

        projection = self.projector.project_workspace_patch(
            session=self.session,
            approval_id="approval-artifact",
            receipt={
                "mutationApplied": True,
                "path": str(target),
                "postimageSha256": hashlib.sha256(raw).hexdigest(),
            },
            preview={
                "actionPayload": {"path": str(target)},
                "changes": [{"label": "差异", "before": "", "after": diff}],
            },
        )

        self.assertEqual(projection.status, "available")
        self.assertEqual(len(projection.blocks), 2)
        first, second = projection.blocks
        self.assertEqual(first["data"]["mimeType"], "text/markdown")
        self.assertEqual(second["data"]["mimeType"], "text/x-diff")
        self.assertEqual(first["data"]["sessionId"], self.session["id"])
        self.assertNotIn(str(self.workspace), str(projection.blocks))

        file_receipt, file_raw = self.media.read(
            str(first["data"]["mediaId"]),
            session_id=str(self.session["id"]),
        )
        self.assertEqual(file_raw, raw)
        self.assertEqual(file_receipt["origin"], "tool_result")
        self.assertEqual(file_receipt["originTool"], "workspace_patch")
        self.assertEqual(file_receipt["originReceiptId"], "approval-artifact")
        with self.assertRaises(KeyError):
            self.media.read(str(first["data"]["mediaId"]), session_id="session-other")

    def test_projection_failure_never_relabels_an_applied_patch_as_failed(self) -> None:
        target = self.workspace / "main.py"
        target.write_text("print('changed')\n", encoding="utf-8")

        projection = self.projector.project_workspace_patch(
            session=self.session,
            approval_id="approval-stale",
            receipt={
                "mutationApplied": True,
                "path": str(target),
                "postimageSha256": "0" * 64,
            },
            preview={"actionPayload": {"path": str(target)}, "changes": []},
        )

        self.assertEqual(projection.status, "unavailable")
        self.assertEqual(projection.reason, "verification_failed")
        self.assertEqual(projection.blocks, ())
        self.assertEqual(target.read_text(encoding="utf-8"), "print('changed')\n")

    def test_projection_rejects_a_receipt_path_outside_the_authorized_workspace(self) -> None:
        outside = self.root / "outside.html"
        outside.write_text("<h1>outside</h1>", encoding="utf-8")
        raw = outside.read_bytes()

        projection = self.projector.project_workspace_patch(
            session=self.session,
            approval_id="approval-outside",
            receipt={
                "mutationApplied": True,
                "path": str(outside),
                "postimageSha256": hashlib.sha256(raw).hexdigest(),
            },
            preview={"actionPayload": {"path": str(outside)}, "changes": []},
        )

        self.assertEqual(projection.status, "unavailable")
        self.assertEqual(self.media.list_for_session(str(self.session["id"])), [])

    def test_explicit_html_read_projects_a_managed_static_preview_block(self) -> None:
        target = self.workspace / "project-intro.html"
        target.write_text("<!doctype html><h1>项目介绍</h1>", encoding="utf-8")
        raw = target.read_bytes()

        projection = self.projector.project_workspace_read(
            session=self.session,
            receipt={
                "path": str(target),
                "resourceRevision": f"sha256:{hashlib.sha256(raw).hexdigest()}",
            },
        )

        self.assertEqual(projection.status, "available")
        self.assertEqual(len(projection.blocks), 1)
        block = projection.blocks[0]
        self.assertEqual(block["type"], "file")
        self.assertEqual(block["data"]["fileName"], "project-intro.html")
        self.assertEqual(block["data"]["mimeType"], "text/html")
        _, stored = self.media.read(
            str(block["data"]["mediaId"]),
            session_id=str(self.session["id"]),
        )
        self.assertEqual(stored, raw)


class AgentToolBlockBufferTests(unittest.TestCase):
    def test_tool_blocks_wait_for_the_final_assistant_message_and_deduplicate(self) -> None:
        block = _managed_file_block()
        buffer = AgentToolBlockBuffer()

        captured = buffer.capture(
            {"details": {"agentBlocks": [block, block]}},
            source_ref="session:turn:tool",
        )
        self.assertEqual(len(captured), 1)
        self.assertIsNone(
            buffer.blocks_for_message(
                {"content": [{"type": "toolCall", "id": "next"}]},
                None,
            )
        )

        delivered = buffer.blocks_for_message(
            {"content": [{"type": "text", "text": "完成"}]},
            None,
        )
        self.assertIsInstance(delivered, list)
        self.assertEqual(len(delivered), 1)
        self.assertIsNone(
            buffer.blocks_for_message(
                {"content": [{"type": "text", "text": "下一条"}]},
                None,
            )
        )

    def test_tool_block_capture_rejects_a_forged_media_identifier(self) -> None:
        forged = _managed_file_block()
        forged["data"]["mediaId"] = "../../private.md"
        buffer = AgentToolBlockBuffer()

        self.assertEqual(
            buffer.capture(
                {"details": {"agentBlocks": [forged]}},
                source_ref="session:turn:tool",
            ),
            (),
        )

    def test_nested_v2_approval_receipt_is_recovered_without_overwriting_invalid_event_blocks(self) -> None:
        block = _managed_file_block()
        buffer = AgentToolBlockBuffer()

        captured = buffer.capture(
            {"details": {"approval": {"receipt": {"agentBlocks": [block]}}}},
            source_ref="session:turn:approval",
        )
        self.assertEqual(len(captured), 1)
        invalid_event_blocks = {"not": "an array"}
        self.assertIs(
            buffer.blocks_for_message(
                {"content": [{"type": "text", "text": "完成"}]},
                invalid_event_blocks,
            ),
            invalid_event_blocks,
        )
        self.assertEqual(
            len(
                buffer.blocks_for_message(
                    {"content": [{"type": "text", "text": "重试"}]},
                    None,
                )
            ),
            1,
        )


def _managed_file_block() -> dict[str, object]:
    return {
        "id": "tool-artifact:file:0123456789abcdef",
        "type": "file",
        "data": {
            "mediaId": "media_abcdefghijklmnop",
            "sessionId": "session-artifact",
            "fileName": "handoff.md",
            "mimeType": "text/markdown",
            "byteSize": 42,
            "sha256": "a" * 64,
            "receiptUrl": (
                "/api/agent/media/media_abcdefghijklmnop/content"
                "?sessionId=session-artifact"
            ),
        },
    }


if __name__ == "__main__":
    unittest.main()
