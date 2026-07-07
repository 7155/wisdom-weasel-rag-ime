import copy
from pathlib import Path
import unittest

from rag_ime.feature_bridge.foreground_acceptance import (
    acceptance_command_mentions_foreground_trace,
    feature_has_panel_trace_event,
    feature_requires_foreground_trace,
)
from rag_ime.feature_bridge.memory_compile_bridge import (
    CURATED_MEMORY_REQUIRED_SIGNALS,
    DOWNSTREAM_SOURCE_TYPES,
    FORBIDDEN_REALTIME_PROVIDER_HINTS,
    OFFLINE_CLEANUP_PROVIDERS,
)
from rag_ime.feature_bridge.registry import (
    FeatureRegistryError,
    load_feature_registry,
    validate_feature_registry,
)
from rag_ime.feature_bridge.rime_export_bridge import (
    CANDIDATE_SOURCE_TYPE as RIME_EXPORT_SOURCE_TYPE,
    REQUIRED_FOREGROUND_PROOF_EVENTS as RIME_EXPORT_PROOF_EVENTS,
)
from rag_ime.feature_bridge.runtime_config_bridge import (
    REQUIRED_FOREGROUND_PROOF_EVENTS as RUNTIME_CONFIG_PROOF_EVENTS,
    RUNTIME_CONFIG_ARTIFACTS,
)
from rag_ime.feature_bridge.selected_text_bridge import (
    CANDIDATE_SOURCE_TYPE as SELECTED_TEXT_SOURCE_TYPE,
    REQUIRED_FOREGROUND_PROOF_EVENTS as SELECTED_TEXT_PROOF_EVENTS,
    SELECTED_TEXT_BRIDGE_FIELDS,
)


ROOT = Path(__file__).resolve().parents[1]


class FeatureBridgeTests(unittest.TestCase):
    def test_load_feature_registry_from_docs(self) -> None:
        features = load_feature_registry(ROOT / "docs" / "feature-registry.md")
        statuses = {feature["v1Status"] for feature in features}
        ids = {feature["featureId"] for feature in features}

        self.assertEqual(len(features), 11)
        self.assertIn("backend_only", statuses)
        self.assertIn("debug_preview", statuses)
        self.assertIn("offline_tool", statuses)
        self.assertIn("blocked_by_bug", statuses)
        self.assertIn("active-rag-selected-text-bridge", ids)
        self.assertIn("x1top-cleanup-to-curated-memory", ids)
        self.assertIn("rime-export-bridge", ids)

    def test_validate_feature_registry_rejects_bad_status_and_duplicate_id(self) -> None:
        features = load_feature_registry(ROOT / "docs" / "feature-registry.md")

        bad_status = copy.deepcopy(features)
        bad_status[0]["v1Status"] = "complete_because_backend_works"
        with self.assertRaisesRegex(FeatureRegistryError, "invalid v1Status"):
            validate_feature_registry(bad_status)

        duplicate = copy.deepcopy(features)
        duplicate[1]["featureId"] = duplicate[0]["featureId"]
        with self.assertRaisesRegex(FeatureRegistryError, "duplicate featureId"):
            validate_feature_registry(duplicate)

    def test_foreground_acceptance_helpers_keep_status_honest(self) -> None:
        backend_only = {
            "v1Status": "backend_only",
            "acceptanceCommand": "python3 -m unittest tests.test_rime_sidecar -v",
            "foregroundTraceEvents": ["panel_display_candidates"],
        }
        foreground_verified = {
            "v1Status": "foreground_verified",
            "acceptanceCommand": "scripts/verify_squirrel_foreground_trace.sh --auto-type",
            "foregroundTraceEvents": ["sidecar_response_received", "panel_display_candidates"],
        }

        self.assertFalse(feature_requires_foreground_trace(backend_only))
        self.assertTrue(feature_requires_foreground_trace(foreground_verified))
        self.assertTrue(acceptance_command_mentions_foreground_trace(foreground_verified))
        self.assertTrue(feature_has_panel_trace_event(foreground_verified))

    def test_bridge_descriptors_name_real_runtime_artifacts(self) -> None:
        self.assertIn("sidecar_settings_store", RUNTIME_CONFIG_ARTIFACTS)
        self.assertIn("panel_display_candidates", RUNTIME_CONFIG_PROOF_EVENTS)

        self.assertIn("selectedText", SELECTED_TEXT_BRIDGE_FIELDS)
        self.assertEqual(SELECTED_TEXT_SOURCE_TYPE, "rag")
        self.assertIn("selected_text_context_captured", SELECTED_TEXT_PROOF_EVENTS)
        self.assertIn("panel_display_candidates", SELECTED_TEXT_PROOF_EVENTS)

        self.assertIn("x1top", OFFLINE_CLEANUP_PROVIDERS)
        self.assertIn("memory", DOWNSTREAM_SOURCE_TYPES)
        self.assertIn("rag", DOWNSTREAM_SOURCE_TYPES)
        self.assertIn("curated", CURATED_MEMORY_REQUIRED_SIGNALS)
        self.assertIn("x1top realtime prediction", FORBIDDEN_REALTIME_PROVIDER_HINTS)

        self.assertEqual(RIME_EXPORT_SOURCE_TYPE, "rime")
        self.assertIn("rime_export_applied", RIME_EXPORT_PROOF_EVENTS)
        self.assertIn("rime_deploy_observed", RIME_EXPORT_PROOF_EVENTS)
        self.assertIn("rime_candidate_from_export_visible", RIME_EXPORT_PROOF_EVENTS)


if __name__ == "__main__":
    unittest.main()
