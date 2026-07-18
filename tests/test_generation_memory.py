from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from rag_ime.deepseek_completion import CompletionCandidateDelta
from rag_ime.generation_memory import (
    generation_memory_evidence_pack,
    retrieve_generation_memory_hits,
)
from rag_ime.hybrid_rag_models import MemoryHit
from rag_ime.local_sqlite_core import LocalSqliteCoreClient
from rag_ime.rime_sidecar import (
    _predict_deepseek_post_commit_candidates,
    parse_rime_context_payload,
)


class _CapturingFlashProvider:
    def __init__(self) -> None:
        self.requests = []

    def stream_candidates(self, request):
        self.requests.append(request)
        yield CompletionCandidateDelta(
            text="继续验证记忆召回",
            insert_text="继续验证记忆召回",
        )


class GenerationMemoryTests(unittest.TestCase):
    def test_generation_retrieval_keeps_current_atom_and_book_bodies(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-generation-memory-") as tmp:
            core = LocalSqliteCoreClient(Path(tmp) / "rag-ime.sqlite")
            core.initialize()
            with core._connect() as conn:
                for values in (
                    (
                        "atom:current-model",
                        "atom",
                        "atom:current-model",
                        "输入法当前使用 100M 自训练模型",
                        "输入法 模型 100M",
                        "active",
                        '{"atomIds":["atom:current-model"],"title":"当前模型"}',
                    ),
                    (
                        "book:ime-runtime",
                        "book",
                        "book:ime-runtime",
                        "输入法工程包含本地推理、RAG 与 Personal Context Core",
                        "输入法 工程 RAG",
                        "active",
                        '{"bookIds":["book:ime-runtime"],"title":"输入法工程"}',
                    ),
                    (
                        "atom:old-model",
                        "atom",
                        "atom:old-model",
                        "输入法仍使用旧 0.8B 模型",
                        "输入法 模型 0.8B",
                        "inactive",
                        '{"atomIds":["atom:old-model"],"title":"旧模型"}',
                    ),
                ):
                    conn.execute(
                        """
                        INSERT INTO memory_retrieval_docs(
                            doc_id, doc_type, source_id, raw_text, tags_text,
                            project, app, status, updated_at_ms, metadata_json
                        ) VALUES (?, ?, ?, ?, ?, 'wisdom-weasel-rag-ime', '', ?, 100, ?)
                        """,
                        values,
                    )

            hits = retrieve_generation_memory_hits(
                core,
                current_context="输入法当前模型和 RAG 工程是什么",
                project="wisdom-weasel-rag-ime",
                top_k=6,
            )

        texts = [hit.text for hit in hits]
        self.assertTrue(any("100M 自训练模型" in text for text in texts))
        self.assertTrue(any("Personal Context Core" in text for text in texts))
        self.assertFalse(any("旧 0.8B" in text for text in texts))

    def test_raw_history_cannot_crow_atom_and_book_out_of_generation_context(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-generation-diversity-") as tmp:
            core = LocalSqliteCoreClient(Path(tmp) / "rag-ime.sqlite")
            core.initialize()
            raw_items = [
                _hit(
                    hit_id=f"hit:item:{index}",
                    doc_type="item",
                    text=f"历史输入片段 {index}",
                )
                for index in range(10)
            ]
            current = _hit(
                hit_id="hit:atom:current",
                doc_type="atom",
                text="当前事实仍然必须进入生成上下文",
                atom_ids=("atom:current",),
            )
            book = _hit(
                hit_id="hit:book:current",
                doc_type="book",
                text="当前主题书也必须进入生成上下文",
                book_ids=("book:current",),
            )
            with patch(
                "rag_ime.generation_memory.retrieve_hybrid_rag_memory_hit_objects",
                return_value=[*raw_items, current, book],
            ):
                hits = retrieve_generation_memory_hits(
                    core,
                    current_context="继续输入法记忆工作",
                    top_k=6,
                )

        self.assertIn(current, hits)
        self.assertIn(book, hits)
        self.assertEqual(sum(hit.doc_type == "item" for hit in hits), 1)
        self.assertLessEqual(len(hits), 6)

    def test_flash_request_receives_full_field_context_and_governed_memory(self) -> None:
        snapshot = parse_rime_context_payload(
            {
                "sessionId": "post-commit",
                "requestSeq": 2,
                "privacyDisposition": "allowed",
                "rawInput": "",
                "preedit": "",
                "committedContext": "语音粘贴后又手动修改的最终完整正文，正在验证输入法模型记忆。",
                "commitTextPreview": "输入法模型记忆",
                "progressiveFollowUp": True,
                "frontendRevision": 2,
                "selectionEpoch": 2,
                "inputGeneration": 2,
                "frontAppBundleId": "com.apple.TextEdit",
                "inputSourceId": "im.rime.inputmethod.Squirrel.Hans",
                "panelSessionId": "panel:generation-memory",
            },
            default_project="wisdom-weasel-rag-ime",
        )
        current = _hit(
            hit_id="hit:atom:current",
            doc_type="atom",
            text="输入法当前使用 100M 自训练模型，旧配置已经停用。",
            atom_ids=("atom:current-model",),
        )
        book = _hit(
            hit_id="hit:book:ime",
            doc_type="book",
            text="输入法工程使用混合检索和 Personal Context Core。",
            book_ids=("book:ime",),
            metadata={"title": "输入法工程"},
        )
        provider = _CapturingFlashProvider()
        final_field = "语音粘贴后又手动修改的最终完整正文，正在验证输入法模型记忆。"

        with (
            patch.dict(os.environ, {"RAG_IME_DEEPSEEK_POST_COMMIT": "1"}),
            patch(
                "rag_ime.rime_sidecar.retrieve_generation_memory_hits",
                return_value=(current, book),
            ),
            patch(
                "rag_ime.rime_sidecar.timeline_evidence_pack_from_core",
                return_value=(),
            ),
        ):
            predictions, lane = _predict_deepseek_post_commit_candidates(
                provider=provider,
                core=object(),
                snapshot=snapshot,
                current_context=final_field,
                existing_predictions=[],
                project="wisdom-weasel-rag-ime",
                max_candidates=3,
                started=time.perf_counter(),
                budget_ms=2_000,
                rime_candidates=(),
            )

        self.assertEqual([item.text for item in predictions], ["继续验证记忆召回"])
        self.assertEqual(lane["generationMemoryHitCount"], 2)
        self.assertEqual(lane["generationMemoryEvidenceCount"], 2)
        self.assertEqual(len(provider.requests), 1)
        request = provider.requests[0]
        self.assertEqual(request.current_context, final_field)
        previews = [str(item.get("evidencePreview") or "") for item in request.evidence_pack]
        self.assertTrue(any("100M 自训练模型" in preview for preview in previews))
        self.assertTrue(any("Personal Context Core" in preview for preview in previews))
        self.assertIn(final_field, request.context_packet["currentInput"]["committedTail"])
        self.assertEqual(request.context_packet["memoryBook"][0]["bookId"], "book:ime")

    def test_memory_evidence_is_context_not_an_insertable_instruction(self) -> None:
        item = generation_memory_evidence_pack(
            [
                _hit(
                    hit_id="hit:atom:policy",
                    doc_type="atom",
                    text="用户偏好先验证再重构",
                    atom_ids=("atom:policy",),
                )
            ]
        )[0]

        self.assertTrue(item["maySupportFacts"])
        self.assertFalse(item["instructional"])
        self.assertEqual(item["sourceType"], "memory_atom")


def _hit(
    *,
    hit_id: str,
    doc_type: str,
    text: str,
    atom_ids: tuple[str, ...] = (),
    book_ids: tuple[str, ...] = (),
    metadata: dict[str, object] | None = None,
) -> MemoryHit:
    return MemoryHit(
        hit_id=hit_id,
        doc_id=hit_id.removeprefix("hit:"),
        doc_type=doc_type,
        source_id=hit_id.removeprefix("hit:"),
        text=text,
        surface_hints=(),
        source_type="memory",
        source_lane="bm25_raw",
        score=0.92,
        confidence=0.9,
        tags=("输入法",),
        memory_ids=(*atom_ids, *book_ids),
        atom_ids=atom_ids,
        book_ids=book_ids,
        evidence_event_ids=(7,),
        evidence_preview=text,
        metadata={"lanes": ["bm25_raw"], **dict(metadata or {})},
    )


if __name__ == "__main__":
    unittest.main()
