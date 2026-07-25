from __future__ import annotations

import unittest

from rag_ime.assistant_overlay import build_assistant_overlay_payload
from rag_ime.contracts.json_schema import ContractValidationError, load_contract, validate_contract


class JsonContractTests(unittest.TestCase):
    def test_all_versioned_contracts_load(self) -> None:
        for name in (
            "rime-suggest-request.v1.json",
            "rime-suggest-response.v1.json",
            "assistant-overlay.v1.json",
            "overlay-config.v1.json",
            "foreground-context.v2.json",
            "rime-select.v1.json",
            "rime-rank-selection.v1.json",
            "foreground-commit.v1.json",
            "assistant-candidate-action.v1.json",
            "active-rag-start.v1.json",
            "active-rag-status.v1.json",
            "frontend-suggest-request.v1.json",
            "frontend-suggest-response.v1.json",
            "frontend-selection.v1.json",
            "frontend-selection-response.v1.json",
            "frontend-capabilities.v1.json",
            "pi-runtime-manifest.v1.json",
            "agent-model-catalog.v1.json",
            "agent-model-selection.v1.json",
            "agent-thinking-selection.v1.json",
            "agent-configuration.v1.json",
            "agent-control-event.v1.json",
            "agent-artifact-ref.v1.json",
            "agent-artifact-inspection.v1.json",
            "agent-room-intercom.v1.json",
            "agent-control-bootstrap.v1.json",
            "management-work-preview.v1.json",
            "management-work-receipt.v1.json",
            "management-work-error.v1.json",
            "memory-graph.v1.json",
            "knowledge-graph.v1.json",
            "memory-entity.v1.json",
            "memory-read-error.v1.json",
        ):
            with self.subTest(name=name):
                self.assertEqual(load_contract(name)["type"], "object")

    def test_suggest_request_and_selection_fixtures_validate(self) -> None:
        candidate = {"text": "继续完成", "insertText": "继续完成", "sourceType": "model"}
        request = {
            "sessionId": "session-1",
            "requestSeq": 7,
            "rawInput": "",
            "preedit": "",
            "foregroundText": {
                "available": True,
                "source": "text_input_client",
                "freshnessMs": 12,
                "canReplaceSelection": False,
            },
        }
        selection = {
            "candidate": candidate,
            "shownCandidates": [candidate],
            "query": "继续",
            "privacyDisposition": "allowed",
        }

        validate_contract(request, "rime-suggest-request.v1.json")
        validate_contract(selection, "rime-select.v1.json")

        validate_contract(
            {"candidate": {"insertText": "兼容候选", "sourceType": "model"}},
            "rime-select.v1.json",
        )
        validate_contract(
            {"text": "旧客户端仍可解析，但服务端会按 unknown no-store"},
            "foreground-commit.v1.json",
        )
        validate_contract(
            {
                "text": "输入框最终内容",
                "source": "squirrel_input_segment",
                "privacyDisposition": "allowed",
                "captureMetadata": {
                    "captureSource": "text_input_client",
                    "fallbackReason": "",
                    "fieldContextChars": 8,
                    "imeBufferChars": 8,
                    "selectedTextSha256": "",
                    "selectionRule": "field_context_if_not_shorter_else_ime_buffer",
                },
            },
            "foreground-commit.v1.json",
        )
        validate_contract(
            {
                "selectedText": "修复当前命令失败",
                "privacyDisposition": "allowed",
                "frontAppBundleId": "com.mitchellh.ghostty",
                "windowContext": {
                    "schemaVersion": "rag-ime.window-context.v1",
                    "captureMode": "terminal_visible_range",
                    "snapshotId": "axsnap-terminal",
                    "revision": 1,
                    "application": {
                        "bundleId": "com.mitchellh.ghostty",
                        "name": "Ghostty",
                    },
                    "nodes": [],
                },
            },
            "active-rag-start.v1.json",
        )

        with self.assertRaises(ContractValidationError):
            validate_contract(
                {
                    "candidate": candidate,
                    "privacyDisposition": "probably-safe",
                },
                "rime-select.v1.json",
            )

    def test_generated_overlay_matches_versioned_contract(self) -> None:
        candidate = {"text": "继续完成", "insertText": "继续完成", "sourceType": "model"}
        overlay = build_assistant_overlay_payload(
            ui_mode="post_commit_prediction",
            input_mode="post_commit_predicting",
            display_candidates=[candidate],
            rag_candidates=[],
            prediction_session={"phase": "post_commit", "snapshotId": "snap:1"},
            key_policy={"tab": "accept_top_prediction"},
            progressive={},
            frontend_transaction={},
        )

        validate_contract(overlay, "assistant-overlay.v1.json")

    def test_missing_required_field_fails_with_path(self) -> None:
        with self.assertRaisesRegex(ContractValidationError, "missing required field requestSeq"):
            validate_contract({"sessionId": "one"}, "rime-suggest-request.v1.json")

    def test_validator_enforces_bounds_uniqueness_and_combinators(self) -> None:
        schema = {
            "type": "object",
            "required": ["mode", "label", "items", "score"],
            "properties": {
                "mode": {"enum": ["a", "b"]},
                "label": {"type": "string", "minLength": 1, "maxLength": 4},
                "items": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 2,
                    "uniqueItems": True,
                    "items": {"type": "string"},
                },
                "score": {"type": "integer", "minimum": 0, "maximum": 2},
                "onlyA": {"type": "string"},
            },
            "allOf": [
                {
                    "if": {
                        "properties": {"mode": {"const": "a"}},
                        "required": ["mode"],
                    },
                    "then": {"required": ["onlyA"]},
                    "else": {"not": {"required": ["onlyA"]}},
                }
            ],
            "additionalProperties": False,
        }
        validate_contract(
            {
                "mode": "a",
                "label": "okay",
                "items": ["x", "y"],
                "score": 2,
                "onlyA": "required",
            },
            schema,
        )
        invalid = (
            {
                "mode": "a",
                "label": "too long",
                "items": ["x"],
                "score": 1,
                "onlyA": "required",
            },
            {
                "mode": "a",
                "label": "okay",
                "items": ["x", "x"],
                "score": 1,
                "onlyA": "required",
            },
            {
                "mode": "a",
                "label": "okay",
                "items": [],
                "score": 3,
            },
            {
                "mode": "b",
                "label": "okay",
                "items": ["x"],
                "score": 1,
                "onlyA": "forbidden",
            },
        )
        for payload in invalid:
            with self.assertRaises(ContractValidationError):
                validate_contract(payload, schema)

    def test_frontend_selection_requires_generation_bound_snapshot(self) -> None:
        selection = {
            "schemaVersion": "rag-ime.frontend-selection.v1",
            "frontend": {"id": "squirrel"},
            "session": {"id": "session-1", "requestSeq": 7, "inputGeneration": 11},
            "privacy": {"disposition": "allowed"},
            "candidate": {
                "id": "model:1",
                "snapshotId": "snapshot:7",
                "snapshotGeneration": 3,
                "inputGeneration": 11,
                "text": "继续完成",
                "insertText": "继续完成",
                "origin": "model",
            },
        }
        validate_contract(selection, "frontend-selection.v1.json")

        missing_generation = {**selection, "session": {"id": "session-1", "requestSeq": 7}}
        with self.assertRaisesRegex(ContractValidationError, "missing required field inputGeneration"):
            validate_contract(missing_generation, "frontend-selection.v1.json")

        empty_snapshot = {**selection, "candidate": {**selection["candidate"], "snapshotId": ""}}
        with self.assertRaisesRegex(ContractValidationError, "string is shorter than 1"):
            validate_contract(empty_snapshot, "frontend-selection.v1.json")


if __name__ == "__main__":
    unittest.main()
