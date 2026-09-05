from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rag_ime.agent_memory_sources import AgentMemorySourceStore
from rag_ime.agent_sessions import AgentSessionStore
from rag_ime.local_sqlite_core import LocalSqliteCoreClient
from rag_ime.models import InputEvent
from rag_ime.owner_memory_curation import OwnerMemoryCurator


class _PersonalV2NoopOrganizer:
    provider_name = "openai-codex"
    curation_protocol_version = "personal-v2"

    def __init__(self, *, fail_finish: bool = False) -> None:
        self.fail_finish = fail_finish
        self.finished = False
        self.source_refs: list[str] = []

    def begin_run(self, _run_id: str, *, frozen_input_sha256: str) -> None:
        if len(frozen_input_sha256) != 64:
            raise AssertionError("frozen input hash missing")

    def finish_run(self) -> None:
        if self.fail_finish:
            raise RuntimeError("session retirement failed")
        self.finished = True

    def fail_run(self, _error: BaseException) -> None:
        return

    def curate_owner_memory(self, *, bundle, **_kwargs):
        source = dict(bundle["inputs"][0])
        self.source_refs.append(str(source["sourceRef"]))
        return {
            "schemaVersion": "rag-ime.personal-memory-curation.v2",
            "provider": "openai-codex",
            "model": "gpt-5.6-luna",
            "sourceDecisions": [
                {
                    "sourceRef": source["sourceRef"],
                    "evidenceId": source["evidenceId"],
                    "disposition": "remember",
                    "evidenceAdmissionState": "admitted",
                    "reasonCode": "durable_personal_preference",
                    "confidence": 0.97,
                }
            ],
            "memoryAtoms": [],
            "memoryRetractions": [],
            "topicBooks": [],
            "personalCurationV2": {
                "protocol": "personal-v2",
                "independentlyVerified": True,
            },
            "modelDiagnostics": {
                "verifier": {"sessionId": "isolated-verifier-session"}
            },
            "modelBundleStats": {"sourceCount": 1},
        }


class _AtomFirstOrganizer:
    provider_name = "openai-codex"
    curation_protocol_version = "atom-first-v1"

    def __init__(self, db_path: Path, session_id: str) -> None:
        self.db_path = db_path
        self.session_id = session_id
        self.run_id = ""

    def begin_run(self, run_id: str, *, frozen_input_sha256: str) -> None:
        self.run_id = run_id
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO memory_curation_model_runs(
                    run_id, session_id, profile, provider, model_id,
                    thinking_level, frozen_input_sha256, state,
                    created_at_ms, updated_at_ms
                ) VALUES (?, ?, 'MEMORY_CURATION', 'openai-codex',
                          'gpt-5.6-luna', 'max', ?, 'prepared', 1, 1)
                """,
                (run_id, self.session_id, frozen_input_sha256),
            )

    def finish_run(self) -> None:
        return

    def fail_run(self, _error: BaseException) -> None:
        return

    def curate_owner_memory(self, *, bundle, **_kwargs):
        inputs = [dict(item) for item in bundle["inputs"]]
        source = next(item for item in inputs if "Rime 候选" in str(item["text"]))
        evidence_id = str(source["evidenceId"])
        event_ids = list(source["sourceEventIds"])
        first_id = "atom:proposal:rime-order"
        second_id = "atom:proposal:stale-context"
        return {
            "schemaVersion": "rag-ime.memory-curation-decisions.v1",
            "provider": self.provider_name,
            "model": "gpt-5.6-luna",
            "curationArchitecture": "atom-first-v1",
            "personalCurationV2": {
                "protocol": "personal-v2",
                "curationArchitecture": "atom-first-v1",
                "canonicalEvidence": True,
            },
            "sourceDecisions": [
                {
                    "sourceRef": item["sourceRef"],
                    "evidenceId": item["evidenceId"],
                    "disposition": (
                        "remember" if item is source else "not_for_memory"
                    ),
                    "evidenceAdmissionState": (
                        "admitted" if item is source else "rejected"
                    ),
                    "reasonCode": (
                        "two_independent_project_constraints"
                        if item is source
                        else "fixture_not_selected"
                    ),
                    "confidence": 0.98,
                }
                for item in inputs
            ],
            "memoryAtoms": [
                {
                    "atomId": first_id,
                    "operation": "create",
                    "kind": "project_constraint",
                    "claimKey": "ime:rime-candidate-order",
                    "canonicalText": "Rime 候选不能被模型候选重排。",
                    "sourceEventIds": event_ids,
                    "evidenceIds": [evidence_id],
                    "curationArchitecture": "atom-first-v1",
                    "confidence": 0.98,
                    "qualityScore": 0.98,
                },
                {
                    "atomId": second_id,
                    "operation": "create",
                    "kind": "project_requirement",
                    "claimKey": "ime:stale-candidate-invalidation",
                    "canonicalText": "应用切换后必须让旧模型候选失效。",
                    "sourceEventIds": event_ids,
                    "evidenceIds": [evidence_id],
                    "curationArchitecture": "atom-first-v1",
                    "confidence": 0.97,
                    "qualityScore": 0.97,
                },
            ],
            "topicBooks": [
                {
                    "title": "输入法候选边界",
                    "summary": "Rime 候选保持原有顺序。",
                    "sourceEventIds": event_ids,
                    "memoryAtomIds": [first_id],
                    "confidence": 0.98,
                    "qualityScore": 0.98,
                },
                {
                    "title": "上下文稳定性",
                    "summary": "应用切换会让旧模型候选失效。",
                    "sourceEventIds": event_ids,
                    "memoryAtomIds": [second_id],
                    "confidence": 0.97,
                    "qualityScore": 0.97,
                },
            ],
            "memoryRetractions": [],
            "warnings": [],
        }


class PersonalMemoryOwnerFlowTests(unittest.TestCase):
    def test_atom_first_cross_app_correction_retires_previous_choice(self) -> None:
        self._assert_cross_app_correction("supersede")

    def test_atom_first_update_refreshes_existing_book_summary(self) -> None:
        self._assert_cross_app_correction("update")

    def _assert_cross_app_correction(self, correction_action: str) -> None:
        from rag_ime.deepseek_memory_organizer import _bind_atom_first_canonical_evidence
        from rag_ime.memory_curation import (
            build_memory_curation_model_bundle, curation_decisions_to_compile_output,
        )

        initial = "在 PAW 本次迭代的记忆报告中，时间随记忆条目展示。"
        correction = "更正：在 PAW 本次迭代的记忆报告中，用户展开条目后才显示时间。"
        current = "在 PAW 本次迭代的记忆报告中，用户展开条目后才显示时间。"

        class RecordedDecisionOrganizer(_AtomFirstOrganizer):
            def curate_owner_memory(self, *, bundle, project, **_kwargs):
                snapshot = build_memory_curation_model_bundle(bundle)
                source = next(item for item in snapshot["inputs"]
                              if "记忆报告中" in item["text"])
                changed = source["text"].startswith("更正")
                action = {"e": source["ref"], "text": current if changed else initial,
                          "kind": "project_decision", "g": "new:memory-report",
                          "topicTitle": "记忆报告", "confidence": 0.99}
                if changed:
                    action["p"] = next(item["ref"] for item in snapshot["existingAtoms"]
                                       if item["text"] == initial)
                    action.pop("g")
                    action.pop("topicTitle")
                decisions = {correction_action if changed else "create": [action],
                             "ignore": [item["ref"] for item in snapshot["inputs"]
                                        if item["ref"] != source["ref"]]}
                compiled = curation_decisions_to_compile_output(
                    decisions, source_bundle=bundle, project=project)
                return _bind_atom_first_canonical_evidence(compiled, bundle=bundle)

        self._capture(initial, ordinal=2, app="RagImeControl")
        organizer = RecordedDecisionOrganizer(self.db_path, self._curation_session_id())
        curator = OwnerMemoryCurator(self.db_path, organizer=organizer,
            project="personal-agent-workbench", initial_settle_ms=0, auto_apply=True)
        curator.initialize()
        first = curator.run_due(manual=True, owner_kind="user", owner_id="default",
                                current_ms=10_000)
        self.assertTrue(first["ok"], first)
        self._capture(correction, ordinal=3, app="com.openai.codex")
        organizer.session_id = self._curation_session_id()
        second = curator.run_due(manual=True, owner_kind="user", owner_id="default",
                                 current_ms=20_000)
        self.assertTrue(second["ok"], second)
        with self.core._connect() as conn:
            rows = [dict(row) for row in conn.execute(
                "SELECT * FROM memory_atoms WHERE canonical_text LIKE '%记忆报告中%'")]
            books = [dict(row) for row in conn.execute(
                "SELECT * FROM memory_books WHERE status IN ('active', 'approved')")]
        active = [row for row in rows if row["claim_state"] == "current"]
        self.assertEqual([row["canonical_text"] for row in active], [current])
        if correction_action == "supersede":
            old = next(row for row in rows if row["canonical_text"] == initial)
            self.assertEqual(old["status"], "superseded")
            self.assertEqual(active[0]["supersedes_id"], old["id"])
            self.assertEqual(active[0]["valid_from_ms"], 3_000)
            self.assertEqual(old["valid_to_ms"], 3_000)
        self.assertTrue(books)
        self.assertTrue(any(current in row["summary"] for row in books))
        self.assertTrue(all(initial not in row["summary"] for row in books))
        self.assertTrue(all(3 in json.loads(row["source_event_ids_json"]) for row in books))

    def test_full_source_and_bound_question_share_curation_budget(self):
        from rag_ime.memory_curation import build_memory_curation_model_bundle
        from rag_ime.owner_memory_curation import (
            _build_owner_source_bundle, _bounded_personal_v2_model_inputs,
            _fit_personal_v2_inputs_to_catalog,
        )

        text = "本次调整需要保留来源和适用范围。" * 300 + "最后一个限制：未经确认不能发布。"
        self._capture(text, ordinal=2)
        with self.core._connect() as conn:
            bundle = _build_owner_source_bundle(conn, owner_kind="user", owner_id="default",
                project="personal-agent-workbench", limit=10, canonical_personal=True)
        snapshot = build_memory_curation_model_bundle(bundle)
        self.assertIn(text, [item["text"] for item in snapshot["inputs"]])
        choice = {"text": "推荐后者", "decisionContext": {"questionText": "范" * 4000},
                  "createdAtMs": 100, "sourceId": "choice"}
        with patch("rag_ime.owner_memory_curation.MAX_PERSONAL_V2_INPUT_TOKENS", 8000):
            self.assertEqual(len(_bounded_personal_v2_model_inputs([choice, choice])), 1)
            self.assertEqual(len(_fit_personal_v2_inputs_to_catalog([choice, choice],
                existing_memory_context={}, context_only=[])), 1)
            with self.assertRaisesRegex(ValueError, "budget"):
                _fit_personal_v2_inputs_to_catalog([{"text": "范" * 7000}],
                    existing_memory_context={}, context_only=[])

    def test_automatic_catch_up_stops_on_failure(self):
        self._capture("我长期要求解释记忆的来源和适用条件。", ordinal=2,
                      created_at_ms=13 * 60 * 60 * 1000)
        curator = OwnerMemoryCurator(self.db_path, organizer=_PersonalV2NoopOrganizer(fail_finish=True),
            project="personal-agent-workbench", initial_settle_ms=0, auto_apply=True)
        curator.initialize()
        report = curator.run_due(current_ms=100 * 60 * 60 * 1000)
        self.assertFalse(report["ok"])
        self.assertEqual(len(report["results"]), 1)
        self.assertEqual(report["status"]["pendingSourceCount"], 2)

    def test_automatic_catch_up_handles_late_sources_behind_monotonic_cursor(self):
        hour = 60 * 60 * 1000
        for ordinal in (2, 3):
            self._capture(f"我长期要求第{ordinal}个协作约定保留来源。",
                          ordinal=ordinal, created_at_ms=ordinal * 13 * hour)
        curator = OwnerMemoryCurator(self.db_path, organizer=_PersonalV2NoopOrganizer(),
            project="personal-agent-workbench", initial_settle_ms=0, auto_apply=True)
        curator.initialize()
        with self.core._connect() as conn:
            conn.execute("""INSERT INTO memory_curation_cursors
                (owner_kind, owner_id, project, lane, last_source_created_at_ms,
                 last_source_id, next_due_at_ms, status, updated_at_ms)
                VALUES ('user', 'default', 'personal-agent-workbench', 'daily', ?,
                        'source:later-cursor', 0, 'idle', 0)""", (100 * hour,))
        report = curator.run_due(current_ms=200 * hour)
        self.assertTrue(report["ok"])
        self.assertEqual(len(report["results"]), 3)
        self.assertEqual(report["status"]["pendingSourceCount"], 0)
        with self.core._connect() as conn:
            self.assertEqual(conn.execute("SELECT last_source_created_at_ms FROM memory_curation_cursors").fetchone()[0],
                             100 * hour)

    def test_automatic_curation_catches_up_in_bounded_batches_then_resumes_cadence(self):
        hour = 60 * 60 * 1000
        for ordinal in range(2, 6):
            self._capture(f"我长期希望第{ordinal}项协作约定保持清楚且可以追溯。",
                          ordinal=ordinal, created_at_ms=ordinal * 13 * hour)
        organizer = _PersonalV2NoopOrganizer()
        curator = OwnerMemoryCurator(self.db_path, organizer=organizer,
            project="personal-agent-workbench", initial_settle_ms=0,
            daily_interval_ms=12 * hour, auto_apply=True)
        curator.initialize()
        now = 100 * hour
        first = curator.run_due(current_ms=now)
        self.assertTrue(first["ok"])
        self.assertEqual(first["ranScopeCount"], 1)
        self.assertEqual(len(first["results"]), 3)
        self.assertTrue(first["status"]["due"])
        second = curator.run_due(current_ms=now + 1)
        self.assertTrue(second["ok"])
        self.assertEqual(second["status"]["pendingSourceCount"], 0)
        # E/S refs are local to each frozen batch; the drained ledger and five
        # calls prove each of the five separately timed inputs was handled.
        self.assertEqual(len(organizer.source_refs), 5)
        scope = second["status"]["scopes"][0]
        self.assertEqual(scope["nextDueAtMs"], now + 1 + 12 * hour)
        self.assertFalse(curator.run_due(current_ms=now + 2)["results"])

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="rag-ime-personal-owner-")
        self.db_path = Path(self.temporary.name) / "rag-ime.sqlite"
        self.core = LocalSqliteCoreClient(self.db_path)
        self.core.initialize()
        self.evidence_id = self._capture(
            "我长期偏好回答简洁自然，并且不使用机器化话术。"
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_session_retirement_failure_precedes_evidence_mutation(self) -> None:
        report = self._run(_PersonalV2NoopOrganizer(fail_finish=True))

        self.assertFalse(report["ok"])
        self.assertEqual(self._evidence_state(), "candidate")
        with self.core._connect() as conn:
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM memory_evidence_admission_events WHERE actor_kind = 'luna'"
                ).fetchone()[0],
                0,
            )

    def test_persistence_failure_compensates_admission_transition(self) -> None:
        organizer = _PersonalV2NoopOrganizer()
        with patch(
            "rag_ime.owner_memory_curation._store_empty_owner_run",
            side_effect=RuntimeError("draft persistence failed"),
        ):
            report = self._run(organizer)

        self.assertTrue(organizer.finished)
        self.assertFalse(report["ok"])
        self.assertEqual(self._evidence_state(), "candidate")
        with self.core._connect() as conn:
            actors = [
                row["actor_kind"]
                for row in conn.execute(
                    """
                    SELECT actor_kind
                    FROM memory_evidence_admission_events
                    WHERE evidence_id = ?
                    ORDER BY rowid
                    """,
                    (self.evidence_id,),
                ).fetchall()
            ]
        self.assertEqual(actors[-2:], ["luna", "rollback"])

    def test_rule_rejection_updates_evidence_receipt_and_source_together(self) -> None:
        noise_evidence_id = self._capture("嗯嗯", ordinal=2)

        report = self._run(_PersonalV2NoopOrganizer())

        self.assertTrue(report["ok"])
        with self.core._connect() as conn:
            evidence = conn.execute(
                """
                SELECT admission_state, admission_reason, source_id
                FROM agent_memory_evidence
                WHERE evidence_id = ?
                """,
                (noise_evidence_id,),
            ).fetchone()
            receipt = conn.execute(
                """
                SELECT evidence_state, evidence_reason
                FROM input_capture_receipts
                WHERE evidence_id = ?
                """,
                (noise_evidence_id,),
            ).fetchone()
            source = conn.execute(
                """
                SELECT source.disposition, source.disposition_reason
                FROM agent_memory_sources AS source
                JOIN memory_evidence_input_event_links AS link
                  ON link.input_event_id = source.input_event_id
                 AND link.relation = 'source'
                WHERE link.evidence_id = ?
                """,
                (noise_evidence_id,),
            ).fetchone()
            event = conn.execute(
                """
                SELECT actor_kind, new_state, reason_code
                FROM memory_evidence_admission_events
                WHERE evidence_id = ?
                ORDER BY rowid DESC
                LIMIT 1
                """,
                (noise_evidence_id,),
            ).fetchone()

        self.assertEqual(
            tuple(evidence)[:2],
            ("rejected", "short_cjk_fragment"),
        )
        self.assertEqual(tuple(receipt), ("rejected", "short_cjk_fragment"))
        self.assertEqual(tuple(source), ("not_for_memory", "short_cjk_fragment"))
        self.assertEqual(tuple(event), ("rule", "rejected", "short_cjk_fragment"))

    def test_personal_status_counts_only_canonical_curatable_evidence(self) -> None:
        legacy_sources = AgentMemorySourceStore(
            self.db_path,
            project="personal-agent-workbench",
        )
        legacy_sources.initialize()
        legacy_session = AgentSessionStore(self.db_path).create(
            title="Legacy untyped input",
            created_at_ms=1_500,
        )
        legacy_sources.checkpoint_user_message(
            session_id=str(legacy_session["id"]),
            pi_entry_id="legacy-entry",
            turn_id="legacy-turn",
            text="这是一条旧版会话输入，不具有 capture-v2 最终边界。",
            created_at_ms=2_000,
        )
        curator = OwnerMemoryCurator(
            self.db_path,
            organizer=_PersonalV2NoopOrganizer(),
            project="personal-agent-workbench",
            clock_ms=lambda: 10_000,
            initial_settle_ms=0,
            auto_apply=True,
            include_agent_dialogue=False,
        )
        curator.initialize()

        status = curator.status(current_ms=10_000)

        self.assertEqual(status["pendingSourceCount"], 1)
        self.assertEqual(status["needsReviewSourceCount"], 0)
        self.assertEqual(len(status["scopes"]), 1)
        self.assertEqual(status["scopes"][0]["totalSourceCount"], 1)
        self.assertEqual(
            status["policy"]["evidenceOrigins"],
            [
                "applied_personal_receipt",
                "capture_v2_input",
                "capture_v2_voice",
                "explicit_user_memory",
                "legacy_untyped_input",
            ],
        )
        self.assertTrue(
            status["policy"]["historicalLegacyRequiresPromotionReceipt"]
        )
        self.assertNotIn("session_digest", status["policy"]["sourceKinds"])

    def test_late_capture_behind_cursor_is_processed_once_without_rewinding(self) -> None:
        organizer = _PersonalV2NoopOrganizer()
        curator = OwnerMemoryCurator(
            self.db_path,
            organizer=organizer,
            project="personal-agent-workbench",
            clock_ms=lambda: 10_000,
            initial_settle_ms=0,
            auto_apply=True,
            include_agent_dialogue=False,
        )
        curator.initialize()

        first = curator.run_due(
            manual=True,
            owner_kind="user",
            owner_id="default",
            current_ms=10_000,
        )
        cursor_before = first["status"]["scopes"][0]["lastSourceCursor"]

        late_evidence_id = self._capture(
            "如果目标或边界不清楚，先询问关键问题再修改。",
            ordinal=2,
            created_at_ms=500,
        )
        pending = curator.status(current_ms=20_000)
        second = curator.run_due(
            manual=True,
            owner_kind="user",
            owner_id="default",
            current_ms=20_000,
        )
        cursor_after = second["status"]["scopes"][0]["lastSourceCursor"]
        third = curator.run_due(
            manual=True,
            owner_kind="user",
            owner_id="default",
            current_ms=30_000,
        )

        self.assertTrue(first["ok"], first)
        self.assertEqual(pending["pendingSourceCount"], 1)
        self.assertTrue(second["ok"], second)
        self.assertFalse(second["results"][0]["skipped"])
        self.assertEqual(self._evidence_state(late_evidence_id), "admitted")
        self.assertEqual(cursor_after, cursor_before)
        self.assertTrue(third["ok"], third)
        self.assertEqual(third["results"][0]["reason"], "no_sources")
        self.assertEqual(len(organizer.source_refs), 2)

    def test_atom_first_keeps_canonical_evidence_and_independent_book_membership(self) -> None:
        text = (
            "Rime 候选不能被模型候选重排。"
            "应用切换后必须让旧模型候选失效。"
        )
        second_evidence_id = self._capture(text, ordinal=2)
        organizer = _AtomFirstOrganizer(
            self.db_path,
            self._curation_session_id(),
        )
        curator = OwnerMemoryCurator(
            self.db_path,
            organizer=organizer,
            project="personal-agent-workbench",
            initial_settle_ms=0,
            auto_apply=True,
            include_agent_dialogue=False,
            max_sources=1_000,
        )
        curator.initialize()

        report = curator.run_due(
            manual=True,
            owner_kind="user",
            owner_id="default",
            current_ms=10_000,
        )

        self.assertTrue(report["ok"], report)
        self.assertEqual(curator.max_sources, 1_000)
        self.assertEqual(self._evidence_state(second_evidence_id), "admitted")
        with self.core._connect() as conn:
            atoms = conn.execute(
                """
                SELECT id, claim_key, knowledge_domain, scope_mode
                FROM memory_atoms
                WHERE claim_key IN (
                    'ime:rime-candidate-order',
                    'ime:stale-candidate-invalidation'
                )
                ORDER BY claim_key
                """
            ).fetchall()
            books = conn.execute(
                """
                SELECT title, memory_atom_ids_json
                FROM memory_books
                WHERE title IN ('输入法候选边界', '上下文稳定性')
                ORDER BY title
                """
            ).fetchall()
            links = conn.execute(
                """
                SELECT memory_atom_id, evidence_id, relation
                FROM memory_atom_evidence_links
                WHERE evidence_id = ?
                ORDER BY memory_atom_id
                """,
                (second_evidence_id,),
            ).fetchall()
        self.assertEqual(len(atoms), 2)
        self.assertTrue(
            all(
                str(row["knowledge_domain"]) == "legacy"
                and str(row["scope_mode"]) == "legacy"
                for row in atoms
            )
        )
        self.assertEqual(len(books), 2)
        self.assertTrue(
            all(len(json.loads(row["memory_atom_ids_json"])) == 1 for row in books)
        )
        self.assertEqual(len(links), 2)
        self.assertEqual({str(row["relation"]) for row in links}, {"supports"})

    def _curation_session_id(self) -> str:
        session = AgentSessionStore(self.db_path).create(
            title="Memory curation fixture",
            created_at_ms=900,
        )
        return str(session["id"])

    def _run(self, organizer: _PersonalV2NoopOrganizer) -> dict[str, object]:
        curator = OwnerMemoryCurator(
            self.db_path,
            organizer=organizer,
            project="personal-agent-workbench",
            clock_ms=lambda: 10_000,
            initial_settle_ms=0,
            auto_apply=True,
            include_agent_dialogue=False,
        )
        curator.initialize()
        return curator.run_due(
            manual=True,
            owner_kind="user",
            owner_id="default",
        )

    def _evidence_state(self, evidence_id: str | None = None) -> str:
        with self.core._connect() as conn:
            row = conn.execute(
                "SELECT admission_state FROM agent_memory_evidence WHERE evidence_id = ?",
                (evidence_id or self.evidence_id,),
            ).fetchone()
        assert row is not None
        return str(row["admission_state"])

    def _capture(
        self,
        text: str,
        *,
        ordinal: int = 1,
        created_at_ms: int | None = None,
        app: str = "com.apple.TextEdit",
    ) -> str:
        timestamp = ordinal * 1_000 if created_at_ms is None else created_at_ms
        metadata = {
            "schemaVersion": "rag-ime.input-capture.v2",
            "captureId": f"capture:personal-owner:{ordinal}",
            "transactionId": f"transaction:personal-owner:{ordinal}",
            "sequence": ordinal,
            "channel": "input_method",
            "boundaryKind": "host_return",
            "boundaryConfidence": "strong",
            "nativeCompositionBefore": False,
            "rimeHandled": False,
            "hostForwarded": True,
            "modifiedReturn": False,
            "finalCommitted": True,
            "controllerEpoch": 1,
            "focusEpoch": 1,
            "appBundleId": app,
            "fieldIdentitySha256": hashlib.sha256(b"personal-owner-field").hexdigest(),
            "privacyRevision": "foreground-privacy.v1",
            "occurredStartMs": timestamp,
            "occurredEndMs": timestamp + 20,
            "contentSha256": hashlib.sha256(text.encode()).hexdigest(),
            "captureSource": "text_input_client",
            "fallbackReason": "",
            "fieldContextChars": len(text),
            "imeBufferChars": len(text),
            "selectionRule": "final_committed_segment",
        }
        _event_ref, receipt = self.core.record_event_with_capture_receipt(
            InputEvent(
                event_id=None,
                created_at_ms=timestamp,
                source="squirrel_input_segment",
                committed_text=text,
                privacy_disposition="allowed",
                app=app,
                project="personal-agent-workbench",
                capture_metadata=metadata,
            )
        )
        return str(receipt["evidenceId"])


if __name__ == "__main__":
    unittest.main()
