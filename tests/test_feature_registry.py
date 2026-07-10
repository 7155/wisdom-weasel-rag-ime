from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "docs" / "feature-registry.md"
PROJECT_STATUS_PATH = ROOT / "docs" / "project-status.md"

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
DEBUG_OR_OFFLINE_PROJECT_STATUS_ROWS = {
    "Management console": "C",
    "Active RAG preview / selected text assist": "C",
    "`x1top` / x1api cleanup": "C",
    "Rime export apply/rollback": "C",
    "`macos/RagImeMac` preview": "C",
    "MLX benchmark/model matrix": "C",
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
        project_status = PROJECT_STATUS_PATH.read_text(encoding="utf-8")
        for label, expected_status in DEBUG_OR_OFFLINE_PROJECT_STATUS_ROWS.items():
            pattern = rf"\| {re.escape(label)} \| {expected_status} \|"
            self.assertRegex(project_status, pattern)
            self.assertNotRegex(project_status, rf"\| {re.escape(label)} \| A \|")

        for feature in _load_registry():
            if feature["v1Status"] in {"debug_preview", "offline_tool"}:
                self.assertNotEqual(feature["v1Status"], "foreground_verified", feature["featureId"])

    def test_remote_or_preview_lanes_are_explicitly_bridged_not_realtime(self) -> None:
        by_id = {feature["featureId"]: feature for feature in _load_registry()}
        self.assertEqual(by_id["x1top-cleanup-to-curated-memory"]["v1Status"], "offline_tool")
        self.assertIn("curated", by_id["x1top-cleanup-to-curated-memory"]["dataSource"])
        self.assertEqual(by_id["ragimemac-debug-harness"]["v1Status"], "debug_preview")
        self.assertIn("patched Squirrel/Rime", by_id["ragimemac-debug-harness"]["realImeTrigger"])
        self.assertIn("local MLX", by_id["mlx-provider-health"]["dataSource"])
        self.assertIn("remote/OpenAI-compatible providers are offline", by_id["mlx-provider-health"]["dataSource"])


def _load_registry() -> list[dict[str, object]]:
    text = REGISTRY_PATH.read_text(encoding="utf-8")
    match = re.search(r"```json\s*(.*?)\s*```", text, flags=re.DOTALL)
    if not match:
        raise AssertionError("docs/feature-registry.md must contain a JSON code block")
    payload = json.loads(match.group(1))
    if not isinstance(payload, list):
        raise AssertionError("feature registry JSON must be a list")
    for item in payload:
        if not isinstance(item, dict):
            raise AssertionError("feature registry items must be objects")
    return payload


if __name__ == "__main__":
    unittest.main()
