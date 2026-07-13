from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "release" / "feature-registry.json"

ALLOWED_V1_STATUS = {
    "foreground_verified",
    "backend_only",
    "debug_preview",
    "offline_tool",
    "blocked_by_bug",
}
REQUIRED_FIELDS = {
    "featureId",
    "userValue",
    "currentStatus",
    "realImeTrigger",
    "sidecarEndpoint",
    "candidateSourceType",
    "keyPolicy",
    "dataSource",
    "foregroundTraceEvents",
    "acceptanceCommand",
    "failureFallback",
    "userVisibleBehavior",
    "tests",
    "v1Status",
}
NON_FOREGROUND_FEATURES = {
    "active-rag-selected-text-bridge": "blocked_by_bug",
    "dsv4-cleanup-to-curated-memory": "offline_tool",
    "rime-export-bridge": "offline_tool",
    "ime-first-demo-pack": "offline_tool",
    "minimind-retraining-quality-gate": "offline_tool",
}


class FeatureRegistryTests(unittest.TestCase):
    def test_feature_registry_is_machine_readable_and_complete(self) -> None:
        features = _load_registry()
        self.assertGreaterEqual(len(features), 10)
        seen_ids: set[str] = set()

        for feature in features:
            missing = REQUIRED_FIELDS - set(feature)
            self.assertEqual(missing, set(), feature.get("featureId"))
            feature_id = str(feature["featureId"])
            self.assertNotIn(feature_id, seen_ids)
            seen_ids.add(feature_id)
            self.assertIn(feature["v1Status"], ALLOWED_V1_STATUS)
            self.assertTrue(str(feature["userValue"]).strip(), feature_id)
            self.assertTrue(str(feature["realImeTrigger"]).strip(), feature_id)
            self.assertTrue(str(feature["sidecarEndpoint"]).strip(), feature_id)
            self.assertTrue(str(feature["candidateSourceType"]).strip(), feature_id)
            self.assertTrue(str(feature["keyPolicy"]).strip(), feature_id)
            self.assertIsInstance(feature["foregroundTraceEvents"], list, feature_id)
            self.assertGreater(len(feature["foregroundTraceEvents"]), 0, feature_id)
            self.assertTrue(str(feature["acceptanceCommand"]).strip(), feature_id)
            self.assertIsInstance(feature["tests"], list, feature_id)
            self.assertGreater(len(feature["tests"]), 0, feature_id)

    def test_foreground_verified_requires_foreground_acceptance_command(self) -> None:
        for feature in _load_registry():
            if feature["v1Status"] != "foreground_verified":
                continue
            command = str(feature["acceptanceCommand"])
            events = " ".join(str(item) for item in feature["foregroundTraceEvents"])
            self.assertRegex(command, r"(verify_squirrel_foreground_trace|check_squirrel_soak_report)")
            self.assertRegex(events, r"(panel_display_candidates|assistant_overlay_candidate_visible)")

    def test_debug_preview_and_offline_tools_are_not_marked_product_complete(self) -> None:
        by_id = {feature["featureId"]: feature for feature in _load_registry()}
        for feature_id, expected_status in NON_FOREGROUND_FEATURES.items():
            self.assertEqual(by_id[feature_id]["v1Status"], expected_status)
        for feature in by_id.values():
            if feature["v1Status"] in {"debug_preview", "offline_tool"}:
                self.assertNotEqual(feature["v1Status"], "foreground_verified", feature["featureId"])

    def test_remote_or_preview_lanes_are_explicitly_bridged_not_realtime(self) -> None:
        by_id = {feature["featureId"]: feature for feature in _load_registry()}
        self.assertEqual(by_id["dsv4-cleanup-to-curated-memory"]["v1Status"], "offline_tool")
        self.assertIn("curated", by_id["dsv4-cleanup-to-curated-memory"]["dataSource"])
        self.assertNotIn("ragimemac-debug-harness", by_id)
        self.assertIn("local MLX", by_id["mlx-provider-health"]["dataSource"])
        self.assertIn("remote/OpenAI-compatible providers are offline", by_id["mlx-provider-health"]["dataSource"])


def _load_registry() -> list[dict[str, object]]:
    payload = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise AssertionError("feature registry JSON must be a list")
    for item in payload:
        if not isinstance(item, dict):
            raise AssertionError("feature registry items must be objects")
    return payload


if __name__ == "__main__":
    unittest.main()
