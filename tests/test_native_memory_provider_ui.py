from __future__ import annotations

import re
import sqlite3
import tempfile
import unittest
from pathlib import Path

from rag_ime.config_portability import provider_metadata
from rag_ime.memory_graph import MemoryGraphPrincipal, MemoryGraphStore


ROOT = Path(__file__).resolve().parents[1]
PROJECT = "wisdom-weasel-rag-ime"


class NativeMemoryProviderUIContractTests(unittest.TestCase):
    def test_provider_ui_uses_hash_bound_management_routes(self) -> None:
        app_model = (ROOT / "macos/RagImeControl/AppModel.swift").read_text(encoding="utf-8")
        page = (ROOT / "macos/RagImeControl/Pages/RagAndModelsPage.swift").read_text(
            encoding="utf-8"
        )
        routes = (ROOT / "rag_ime/debug_server.py").read_text(encoding="utf-8")

        self.assertIn('api.get("api/providers/configuration")', app_model)
        self.assertIn('"expectedConfigurationHash": .string(current.configurationHash)', app_model)
        self.assertIn('"api/providers/configuration/apply"', app_model)
        self.assertIn("model.applyProviderConfiguration(", page)
        self.assertIn('model: instantModel', page)
        self.assertIn('model: knowledgeModel', page)
        self.assertIn('parsed.path == "/api/providers/configuration"', routes)
        self.assertIn('path == "/api/providers/configuration/apply"', routes)
        self.assertIn("providerSaveBusy", page)
        self.assertIn("guard !providerSaveBusy else { return }", page)
        self.assertIn("unsupportedInstantProvider", page)
        self.assertIn("unsupportedKnowledgeProvider", page)
        self.assertIn("原配置尚未改动", page)
        self.assertNotIn("即时补全仅允许本机或局域网地址", page)

    def test_provider_ui_validates_local_fields_before_backend_apply(self) -> None:
        page = (ROOT / "macos/RagImeControl/Pages/RagAndModelsPage.swift").read_text(
            encoding="utf-8"
        )
        store = (ROOT / "macos/Shared/ModelProviderConfigStore.swift").read_text(
            encoding="utf-8"
        )

        instant_save = page[page.index("private func saveInstantSlot() async") :]
        instant_save = instant_save[: instant_save.index("private func saveKnowledgeSlot() async")]
        knowledge_save = page[page.index("private func saveKnowledgeSlot() async") :]
        knowledge_save = knowledge_save[: knowledge_save.index("@ViewBuilder")]

        self.assertLess(
            instant_save.index("ModelProviderConfigStore.validateInstant(slot)"),
            instant_save.index("model.applyProviderConfiguration("),
        )
        self.assertLess(
            knowledge_save.index("ModelProviderConfigStore.validateKnowledge(slot)"),
            knowledge_save.index("model.applyProviderConfiguration("),
        )
        self.assertIn("static func validateInstant(_ slot: InstantCompletionSlot) throws", store)
        self.assertIn("static func validateKnowledge(_ slot: KnowledgeProviderSlot) throws", store)

    def test_provider_metadata_has_every_non_optional_swift_decode_field(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-provider-ui-") as temporary:
            support = Path(temporary)
            (support / "predictor.env").write_text(
                "RAG_IME_PREDICTOR_PROVIDER=mlx\n"
                "RAG_IME_PREDICTOR_BASE_URL=http://127.0.0.1:8767\n"
                "RAG_IME_PREDICTOR_MODEL=minimind-ime-100m-user-daily-core-v1\n",
                encoding="utf-8",
            )
            (support / "deepseek.env").write_text(
                "RAG_IME_KNOWLEDGE_PROVIDER=deepseek\n"
                "RAG_IME_DEEPSEEK_BASE_URL=https://api.deepseek.com\n"
                "RAG_IME_DEEPSEEK_MODEL=deepseek-v4-flash\n",
                encoding="utf-8",
            )

            payload = provider_metadata(support_directory=support)

        self.assertTrue({"instant", "knowledge", "voice", "secretsIncluded"} <= payload.keys())
        for slot in ("instant", "knowledge", "voice"):
            self.assertIn("provider", payload[slot])
        for slot in ("instant", "knowledge"):
            self.assertTrue({"endpoint", "model"} <= payload[slot].keys())
        self.assertFalse(payload["secretsIncluded"])

    def test_memory_graph_payload_matches_native_models_and_rehydrates_evidence(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-memory-graph-ui-") as temporary:
            db_path = Path(temporary) / "rag-ime.sqlite"
            store = MemoryGraphStore(db_path)
            store.initialize()
            with sqlite3.connect(db_path) as connection:
                cursor = connection.execute(
                    """
                    INSERT INTO input_events(
                        created_at_ms, source, committed_text, recent_context, preedit,
                        schema_id, app, project, provider_name, tags_json,
                        context_group_id, context_group_level
                    ) VALUES (1000, 'manual', '八月考试让我感到压力', '', '',
                              'default', 'RagImeControl', ?, 'local', '[]', '', 'app')
                    """,
                    (PROJECT,),
                )
                event_id = int(cursor.lastrowid)
                connection.execute(
                    "INSERT INTO memory_state(event_id, updated_at_ms) VALUES (?, 1000)",
                    (event_id,),
                )
                connection.commit()

            store.upsert_entity(
                entity_id="entity:exam",
                entity_type="concept",
                name="考试",
                project=PROJECT,
                updated_at_ms=1000,
            )
            store.upsert_entity(
                entity_id="entity:stress",
                entity_type="concept",
                name="压力",
                project=PROJECT,
                updated_at_ms=1000,
            )
            store.upsert_relation(
                relation_id="relation:exam-stress",
                source_entity_id="entity:exam",
                target_entity_id="entity:stress",
                relation_type="causes",
                fact="考试准备使用户感到压力",
                idempotency_key="ui-contract:exam-stress",
                sources=[{"sourceType": "input_event", "sourceId": str(event_id)}],
                project=PROJECT,
                valid_from_ms=1000,
                updated_at_ms=1000,
            )
            principal = MemoryGraphPrincipal(project=PROJECT, local_admin=True)
            graph = store.browse(principal, as_of_ms=2000, node_limit=18, relation_limit=36)
            evidence = store.get_sources(
                principal,
                relation_ids=["relation:exam-stress"],
            )

        self.assertTrue(
            {
                "schemaVersion",
                "asOfMs",
                "query",
                "entities",
                "relations",
                "summary",
                "filters",
            }
            <= graph.keys()
        )
        self.assertTrue(
            {
                "entityId",
                "entityType",
                "canonicalName",
                "description",
                "aliases",
                "ownerKind",
                "ownerId",
                "project",
                "status",
                "revision",
                "confidence",
                "createdAtMs",
                "updatedAtMs",
                "sources",
                "relationCount",
            }
            <= graph["entities"][0].keys()
        )
        self.assertTrue(
            {
                "relationId",
                "sourceEntityId",
                "targetEntityId",
                "sourceName",
                "targetName",
                "sourceType",
                "targetType",
                "relationType",
                "fact",
                "sourceCount",
            }
            <= graph["relations"][0].keys()
        )
        self.assertEqual(evidence["count"], 1)
        self.assertTrue(
            {
                "sourceType",
                "sourceId",
                "sourceRevision",
                "text",
                "createdAtMs",
                "project",
                "app",
                "relationIds",
            }
            <= evidence["sources"][0].keys()
        )
        self.assertEqual(evidence["sources"][0]["relationIds"], ["relation:exam-stress"])

    def test_memory_page_wires_graph_filters_and_source_rehydration(self) -> None:
        page = (ROOT / "macos/RagImeControl/Pages/MemoryPage.swift").read_text(encoding="utf-8")
        app_model = (ROOT / "macos/RagImeControl/AppModel.swift").read_text(encoding="utf-8")
        models = (ROOT / "macos/RagImeControl/Models/ManagementModels.swift").read_text(
            encoding="utf-8"
        )

        self.assertIn("MemoryEntityGraph(", page)
        self.assertIn("MemoryGraphInspector(", page)
        self.assertIn("model.loadMemoryGraphSources(relationId: relationId)", page)
        self.assertIn("model.clearMemoryGraphSources()", page)
        self.assertIn("sourcesLoading: model.memoryGraphSourcesLoading", page)
        self.assertIn("sourcesRelationId: model.memoryGraphSourcesRelationId", page)
        self.assertIn("$0.relationIds.contains(relationId)", page)
        self.assertIn('api.get("api/memory/graph", query: query)', app_model)
        self.assertIn('URLQueryItem(name: "limit", value: "18")', app_model)
        self.assertIn('"api/memory/graph/sources"', app_model)
        self.assertIn("memoryGraphSourcesGeneration", app_model)
        self.assertIn("memoryGraphSourcesRelationId == relationId", app_model)
        self.assertIn("struct MemoryGraphResponse: Decodable", models)
        self.assertIn("let relationIds: [String]", models)
        self.assertIn("ControlDesign.bodyFont.weight(.semibold)", page)
        self.assertIn("ControlDesign.metadataFont", page)

    def test_shared_type_scale_has_readable_native_minimums(self) -> None:
        components = (
            ROOT / "macos/RagImeControl/Components/ControlComponents.swift"
        ).read_text(encoding="utf-8")

        def size(name: str) -> float:
            match = re.search(
                rf"static let {name} = Font\.system\(size: ([0-9.]+)",
                components,
            )
            self.assertIsNotNone(match, name)
            return float(match.group(1))

        self.assertGreaterEqual(size("pageTitleFont"), 28)
        self.assertGreaterEqual(size("sectionTitleFont"), 17)
        self.assertGreaterEqual(size("bodyFont"), 15)
        self.assertGreaterEqual(size("detailFont"), 14)
        self.assertGreaterEqual(size("metadataFont"), 13)
        self.assertIn("Text(title).font(ControlDesign.pageTitleFont)", components)
        self.assertIn("Text(subtitle).font(ControlDesign.detailFont)", components)


if __name__ == "__main__":
    unittest.main()
