from __future__ import annotations

import importlib.util
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "room_context_epoch_canary.py"
SPEC = importlib.util.spec_from_file_location("room_context_epoch_canary", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
CANARY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CANARY)
sys.modules.setdefault("room_context_epoch_canary", CANARY)
REPORT_SCRIPT = ROOT / "scripts" / "report_room_context_epoch_canary.py"
REPORT_SPEC = importlib.util.spec_from_file_location(
    "report_room_context_epoch_canary", REPORT_SCRIPT
)
assert REPORT_SPEC is not None and REPORT_SPEC.loader is not None
REPORT = importlib.util.module_from_spec(REPORT_SPEC)
REPORT_SPEC.loader.exec_module(REPORT)


class RoomContextEpochCanaryTest(unittest.TestCase):
    def test_memory_check_is_scoped_to_the_session_memory_envelope(self) -> None:
        requests = [
            {
                "payload": {
                    "input": [
                        {
                            "role": "developer",
                            "content": (
                                "Core 规则：不输出相关度、分数或内部 ID。\n"
                                '<rag-ime-context type="session_memory">\n'
                                "## Session 记忆\n"
                                "- **项目偏好**: 每个 epoch 只补一份恢复包。\n"
                                "</rag-ime-context>"
                            ),
                        }
                    ]
                }
            }
        ]

        blocks = CANARY._provider_session_memory_blocks(requests)

        self.assertEqual(len(blocks), 1)
        self.assertIn("每个 epoch 只补一份恢复包", blocks[0])
        self.assertNotIn("相关度", blocks[0])

    def test_memory_check_finds_internal_retrieval_metadata(self) -> None:
        requests = [
            {
                "payload": {
                    "input": (
                        '<rag-ime-context type="session_memory">'
                        "## Session 记忆\nsourceId=atom:private\n相关度：0.92"
                        "</rag-ime-context>"
                    )
                }
            }
        ]

        block = CANARY._provider_session_memory_blocks(requests)[0]
        leaked = {
            token for token in CANARY._FORBIDDEN_MEMORY_METADATA if token in block
        }

        self.assertEqual(leaked, {"sourceId", "相关度："})

    def test_transcript_evidence_rejects_room_projection_as_user_message(self) -> None:
        entries = [
            {"type": "session", "version": 3},
            {
                "type": "message",
                "message": {
                    "role": "user",
                    "content": "执行当前受管 Room 任务；任务事实以 Provider Context 为准。",
                },
            },
            {
                "type": "message",
                "message": {
                    "role": "user",
                    "content": (
                        "收工检查未通过：请使用精确验收 ID。"
                        '<room-projection state="pending">不应进入 Session</room-projection>'
                    ),
                },
            },
        ]
        payload = "".join(
            json.dumps(entry, ensure_ascii=False) + "\n" for entry in entries
        ).encode("utf-8")
        digest = hashlib.sha256(payload).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "session.jsonl"
            path.write_bytes(payload)

            evidence = CANARY.transcript_evidence(Path(directory), digest)

        self.assertEqual(evidence["privateTriggerCount"], 1)
        self.assertEqual(evidence["repairContinuationCount"], 1)
        self.assertEqual(evidence["roomEnvelopeCount"], 1)

    def test_offline_report_reuses_recorded_session_memory_receipt(self) -> None:
        receipt = REPORT._recorded_memory_evidence(
            {
                "blockCount": 2,
                "nonEmptyBlockCount": 2,
                "forbiddenMetadata": [],
            },
            turn_id="turn:1",
            source="canary_report",
        )

        self.assertEqual(
            receipt,
            {
                "turnId": "turn:1",
                "blockCount": 2,
                "nonEmptyBlockCount": 2,
                "forbiddenMetadata": [],
                "source": "canary_report",
            },
        )

    def test_offline_report_reuses_sealed_transcript_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evidence.json"
            path.write_text(
                json.dumps(
                    {
                        "epochs": [],
                        "observations": {"transcript": {"sha256": "a" * 64}},
                    }
                ),
                encoding="utf-8",
            )

            digest = REPORT._prior_transcript_sha(path)

        self.assertEqual(digest, "a" * 64)

    def test_transcript_boundary_does_not_require_a_repair_per_epoch(self) -> None:
        checks = REPORT._transcript_boundary_checks(
            {
                "privateTriggerCount": 3,
                "repairContinuationCount": 1,
                "roomEnvelopeCount": 0,
                "publicCanaryPostCount": 0,
            },
            epoch_count=3,
        )

        self.assertEqual(
            checks,
            {
                "repairContinuationsAreBounded": True,
                "roomContextAbsentFromSessionTranscript": True,
            },
        )

    def test_transcript_boundary_rejects_an_unbounded_repair_loop(self) -> None:
        checks = REPORT._transcript_boundary_checks(
            {
                "privateTriggerCount": 3,
                "repairContinuationCount": 4,
                "roomEnvelopeCount": 0,
                "publicCanaryPostCount": 0,
            },
            epoch_count=3,
        )

        self.assertFalse(checks["repairContinuationsAreBounded"])


if __name__ == "__main__":
    unittest.main()
