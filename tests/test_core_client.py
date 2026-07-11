from __future__ import annotations

import sys
import unittest

from rag_ime.core_client import JsonCommandCoreClient
from rag_ime.memory_optimizer_models import ContextFrame, RawRetrievalHit
from rag_ime.models import InputEvent


class JsonCommandCoreClientTests(unittest.TestCase):
    def test_sensitive_event_is_not_sent_to_external_core(self) -> None:
        client = JsonCommandCoreClient([sys.executable, "-c", "raise SystemExit(99)"])

        result = client.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=1,
                source="squirrel",
                committed_text="must-not-leave-process",
                privacy_disposition="sensitive",
            )
        )

        self.assertEqual(result, "skipped:privacy_sensitive")

    def test_optimize_memory_candidates_preserves_blocked_reasons(self) -> None:
        command = [
            sys.executable,
            "-c",
            (
                "import json,sys; "
                "json.loads(sys.stdin.read()); "
                "sys.stdout.write(json.dumps({"
                "'candidates':[{'id':'phrase:连续预测','text':'连续预测','source_type':'memory','lane':'memory','score':0.9,'confidence':0.88,"
                "'evidence_preview':'高频短语','memory_atom_ids':['phrase:连续预测'],'tags':['phrase-memory'],'debug_features':{'prefixMatch':1.0},'metadata':{}}],"
                "'blocked':[{'id':'event:1','reason':'recent_committed_echo','metadata':{'match':'recent'}}],"
                "'trace_id':'trace-json-core','latency_ms':1.25,'degraded':False,'warnings':['ok']"
                "}, ensure_ascii=False))"
            ),
        ]
        client = JsonCommandCoreClient(command)
        context = ContextFrame(
            session_id="json-core-test",
            request_seq=1,
            front_app_bundle_id="com.apple.TextEdit",
            input_mode="post_commit_continuation",
            raw_input="",
            preedit="",
            committed_tail="我想继续写连续",
            selected_rime_candidates=["连续"],
            semantic_query="连续预测",
            semantic_query_source="rime_candidate",
            composition_hash="compose",
            context_hash="context",
            active_tags=["连续预测"],
            project_scope="wisdom-weasel-rag-ime",
            timestamp_ms=1,
        )
        hits = [
            RawRetrievalHit(
                id="phrase:连续预测",
                text="连续预测",
                source="phrase",
                score=0.8,
                memory_atom_id="phrase:连续预测",
                evidence="高频短语",
                metadata={"source_type": "memory"},
            )
        ]

        result = client.optimize_memory_candidates(
            context,
            hits,
            top_k=2,
            latency_budget_ms=15,
        )

        self.assertEqual(result.trace_id, "trace-json-core")
        self.assertEqual(len(result.candidates), 1)
        self.assertEqual(result.candidates[0].id, "phrase:连续预测")
        self.assertEqual(len(result.blocked), 1)
        self.assertEqual(result.blocked[0].reason, "recent_committed_echo")
        self.assertEqual(result.blocked[0].metadata["match"], "recent")
