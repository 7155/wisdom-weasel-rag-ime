from __future__ import annotations

import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from rag_ime.cloudops_benchmark_agent import (
    CloudOpsBenchmarkGateway,
    CloudOpsBenchmarkGatewayServer,
    CloudOpsBlindSuite,
    _contains_host_locator,
)


class CloudOpsBenchmarkGatewayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="cloudops-gateway-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.case_ids = [f"demo/runtime/{index}" for index in range(1, 5)]
        _write_fixture(self.root, self.case_ids)
        self.suite = CloudOpsBlindSuite(
            self.root / "blind",
            batches={"batch-1": self.case_ids},
        )
        self.gateway = CloudOpsBenchmarkGateway(self.suite, max_reads_per_case=2)
        self.gateway.bind_session("session-1", batch_id="batch-1")

    def _call(self, operation: str, **args: object) -> dict[str, object]:
        return self.gateway.execute(
            {
                "schemaVersion": "rag-ime.agent-tool-call.v1",
                "sessionId": "session-1",
                "tool": "cloudops_benchmark",
                "toolCallId": f"tool:{operation}:{len(self.gateway.ledger(session_id='session-1')['items'])}",
                "sourceLoopId": "loop:one",
                "args": {"op": operation, **args},
            }
        )

    def test_search_is_exposed_only_to_the_evidence_search_profile(self) -> None:
        self.assertEqual([], self.gateway.runtime_manifests({"id": "other"}))
        manifest = self.gateway.runtime_manifests({"id": "session-1"})[0]
        operations = {
            item["properties"]["op"]["const"]
            for item in manifest["parameters"]["oneOf"]
        }
        self.assertEqual({"index", "list", "read", "submit"}, operations)
        self.assertNotIn("Search", manifest["description"])
        with self.assertRaisesRegex(ValueError, "workflow profile"):
            self._call("search", caseId=self.case_ids[0], query="probe failed")

        self.gateway.unbind_session("session-1")
        self.gateway.bind_session(
            "session-1",
            batch_id="batch-1",
            workflow_profile="evidence-search-v1",
        )
        evidence_manifest = self.gateway.runtime_manifests({"id": "session-1"})[0]
        evidence_operations = {
            item["properties"]["op"]["const"]
            for item in evidence_manifest["parameters"]["oneOf"]
        }
        self.assertEqual({"index", "list", "search", "read", "submit"}, evidence_operations)
        self.assertIn("Search", evidence_manifest["description"])

    def test_search_ranks_discriminating_observations_without_returning_full_values(self) -> None:
        self.gateway.unbind_session("session-1")
        self.gateway.bind_session(
            "session-1",
            batch_id="batch-1",
            workflow_profile="evidence-search-v1",
        )
        case_id = self.case_ids[0]

        result = self._call(
            "search",
            caseId=case_id,
            query="probe failed",
            limit=2,
        )["result"]

        self.assertEqual("paw.cloudops-observation-search.v1", result["schemaVersion"])
        self.assertEqual(1, result["totalMatches"])
        self.assertEqual("GetErrorLogs", result["items"][0]["toolName"])
        self.assertIn('"app":"api"', result["items"][0]["cacheKey"])
        self.assertGreater(result["items"][0]["matchScore"], 0)
        self.assertNotIn("observation", result["items"][0])
        self.assertNotIn("preview", result["items"][0])
        self.assertNotIn("probe failed", json.dumps(result))
        self.assertEqual(64, len(result["querySha256"]))

        ledger = self.gateway.ledger(session_id="session-1")["items"][-1]
        self.assertEqual("search", ledger["operation"])
        self.assertNotIn("query", ledger["args"])
        self.assertEqual(64, len(ledger["args"]["querySha256"]))

    def test_search_truncates_excess_terms_instead_of_rejecting_a_schema_valid_query(self) -> None:
        self.gateway.unbind_session("session-1")
        self.gateway.bind_session(
            "session-1",
            batch_id="batch-1",
            workflow_profile="evidence-search-v1",
        )

        result = self._call(
            "search",
            caseId=self.case_ids[0],
            query=(
                "probe failed restart latency network packet retransmit timeout "
                "service node pod dependency error log cpu memory"
            ),
        )["result"]

        self.assertEqual(12, result["usedTermCount"])
        self.assertEqual(4, result["ignoredTermCount"])
        self.assertEqual(64, len(result["querySha256"]))
        ledger = self.gateway.ledger(session_id="session-1")["items"][-1]
        self.assertNotIn("query", ledger["args"])
        self.assertEqual(64, len(ledger["args"]["querySha256"]))

    def test_index_list_and_read_are_batch_scoped_and_do_not_leak_paths_or_gold(self) -> None:
        indexed = self._call("index")["result"]
        self.assertEqual(self.case_ids, [item["caseId"] for item in indexed["cases"]])

        listed = self._call("list", caseId=self.case_ids[0], limit=1)["result"]
        self.assertEqual(1, len(listed["items"]))
        self.assertNotIn("preview", listed["items"][0])
        cache_key = listed["items"][0]["cacheKey"]
        read = self._call("read", caseId=self.case_ids[0], cacheKey=cache_key)["result"]
        self.assertEqual("pod restarted twice", read["observation"])
        self.assertTrue(str(read["evidenceId"]).startswith("evidence:cloudops:"))

        public = json.dumps(
            {"index": indexed, "list": listed, "ledger": self.gateway.ledger(session_id="session-1")},
            sort_keys=True,
        )
        self.assertNotIn(str(self.root), public)
        self.assertNotIn("gold.json", public)
        self.assertNotIn("pod restarted twice", public)
        self.assertNotIn("pod restarted twice", json.dumps(self.gateway.ledger(session_id="session-1")))

        with self.assertRaisesRegex(ValueError, "assigned"):
            self._call("list", caseId="other/runtime/1")
        with self.assertRaisesRegex(ValueError, "cache key"):
            self._call("read", caseId=self.case_ids[0], cacheKey="unknown")

    def test_read_budget_and_submit_contract_fail_closed(self) -> None:
        case_id = self.case_ids[0]
        keys = [
            item["cacheKey"]
            for item in self._call("list", caseId=case_id, limit=10)["result"]["items"]
        ]
        self._call("read", caseId=case_id, cacheKey=keys[0])
        self._call("read", caseId=case_id, cacheKey=keys[1])
        with self.assertRaisesRegex(ValueError, "budget"):
            self._call("read", caseId=case_id, cacheKey=keys[0])

        bad_answers = [_answer(case_id) for case_id in self.case_ids[:-1]]
        with self.assertRaisesRegex(ValueError, "assigned cases"):
            self._call("submit", answers=bad_answers)

        submitted = self._call(
            "submit",
            answers=[_answer(case_id) for case_id in self.case_ids],
        )["result"]
        self.assertEqual(4, submitted["answerCount"])
        self.assertNotIn("answers", submitted)
        with self.assertRaisesRegex(ValueError, "already"):
            self._call("submit", answers=[_answer(case_id) for case_id in self.case_ids])

    def test_concurrent_submit_has_exactly_one_winner(self) -> None:
        barrier = threading.Barrier(2)
        original = self.suite.validate_answers

        def delayed(batch_id: str, value: object) -> list[dict[str, object]]:
            result = original(batch_id, value)
            barrier.wait(timeout=2)
            return result

        def submit(call_id: str) -> object:
            try:
                return self.gateway.execute(
                    {
                        "schemaVersion": "rag-ime.agent-tool-call.v1",
                        "sessionId": "session-1",
                        "tool": "cloudops_benchmark",
                        "toolCallId": call_id,
                        "sourceLoopId": "loop:one",
                        "args": {
                            "op": "submit",
                            "answers": [_answer(case_id) for case_id in self.case_ids],
                        },
                    }
                )
            except ValueError as exc:
                return exc

        with patch.object(self.suite, "validate_answers", side_effect=delayed):
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(submit, ("tool:submit:a", "tool:submit:b")))

        self.assertEqual(1, sum(isinstance(item, dict) for item in results))
        self.assertEqual(1, sum("already" in str(item) for item in results))

    def test_structured_observation_uses_the_frozen_index_serialization(self) -> None:
        case_id = self.case_ids[0]
        listed = self._call(
            "list",
            caseId=case_id,
            toolName="GetErrorLogs",
            limit=10,
        )["result"]
        cache_key = next(
            item["cacheKey"]
            for item in listed["items"]
            if "structured" in item["cacheKey"]
        )

        result = self._call("read", caseId=case_id, cacheKey=cache_key)["result"]

        self.assertEqual('{"patterns": [{"count": 1}]}', result["observation"])

    def test_suite_rejects_a_gold_named_file_inside_the_blind_boundary(self) -> None:
        (self.root / "blind" / "gold.json").write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "leakage"):
            CloudOpsBlindSuite(
                self.root / "blind",
                batches={"batch-1": self.case_ids},
            )

    def test_suite_rejects_unexpected_index_fields_and_locator_like_tool_names(self) -> None:
        case_root = self.root / "blind" / "cases" / "demo" / "runtime" / "1"
        index_path = case_root / "tool_cache_index.json"
        index = json.loads(index_path.read_text(encoding="utf-8"))
        index[0]["hostPath"] = "/Users/example/private"
        index_path.write_text(json.dumps(index), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "descriptor"):
            CloudOpsBlindSuite(
                self.root / "blind",
                batches={"batch-1": self.case_ids},
            )

        del index[0]["hostPath"]
        index_path.write_text(json.dumps(index), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Tool name"):
            self._call("list", caseId=self.case_ids[0], toolName="/Users/example/private")

    def test_host_locator_detection_is_cross_platform(self) -> None:
        for value in (
            "file:///tmp/private.json",
            "/private/var/folders/secret",
            "/tmp/private.json",
            "/home/user/private.json",
            r"C:\\Users\\example\\private.json",
            r"\\\\server\\share\\private.json",
            "path=/private/a",
            r"root=C:\Users\me\a",
            r"share=\\server\share\a",
        ):
            with self.subTest(value=value):
                self.assertTrue(_contains_host_locator(value))
        self.assertFalse(_contains_host_locator("app/api and node/worker-01"))

    def test_loopback_bridge_keeps_the_gateway_and_capability_token_explicit(self) -> None:
        server = CloudOpsBenchmarkGatewayServer(self.gateway, token="test-token")
        self.assertIs(self.gateway, server.gateway)
        self.assertEqual("test-token", server.token)
        self.assertEqual("loopback-http-v1", server.transport)
        with self.assertRaisesRegex(RuntimeError, "not running"):
            _ = server.tool_gateway_url


def _answer(case_id: str) -> dict[str, object]:
    return {
        "case_id": case_id,
        "key_evidence_summary": "restart evidence",
        "top_3_predictions": [
            {"rank": 1, "fault_object": "app/api", "root_cause": "restart_loop"},
            {"rank": 2, "fault_object": "app/api", "root_cause": "bad_probe"},
            {"rank": 3, "fault_object": "node/worker-01", "root_cause": "node_loss"},
        ],
    }


def _write_fixture(root: Path, case_ids: list[str]) -> None:
    blind = root / "blind"
    cases = []
    for case_id in case_ids:
        system, category, name = case_id.split("/")
        cases.append(
            {
                "case_id": case_id,
                "system": system,
                "fault_category": category,
                "case_name": name,
                "namespace": system,
                "query": "Service restarted.",
                "difficulty": "easy",
            }
        )
        case_root = blind / "cases" / system / category / name
        case_root.mkdir(parents=True)
        (case_root / "case.json").write_text(json.dumps(cases[-1]), encoding="utf-8")
        cache = {
            'GetResources:{"resource_type":"pods"}': "pod restarted twice",
            'GetErrorLogs:{"app":"api"}': "probe failed",
            'GetErrorLogs:{"app":"structured"}': {"patterns": [{"count": 1}]},
        }
        (case_root / "tool_cache.json").write_text(json.dumps(cache), encoding="utf-8")
        index = []
        for cache_key, observation in cache.items():
            import hashlib

            observation_text = (
                observation
                if isinstance(observation, str)
                else json.dumps(observation, ensure_ascii=False, sort_keys=True)
            )

            index.append(
                {
                    "cacheKey": cache_key,
                    "toolName": cache_key.split(":", 1)[0],
                    "observationChars": len(observation_text),
                    "observationSha256": hashlib.sha256(observation_text.encode()).hexdigest(),
                    "preview": observation_text,
                }
            )
        (case_root / "tool_cache_index.json").write_text(json.dumps(index), encoding="utf-8")
    (blind / "suite.json").write_text(
        json.dumps(
            {
                "schemaVersion": "paw.cloudops-blind-suite.v1",
                "sourceRevision": "source-revision-v1",
                "cases": cases,
                "answerContract": {
                    "format": "JSONL",
                    "requiredFields": ["case_id", "key_evidence_summary", "top_3_predictions"],
                    "predictionRanks": [1, 2, 3],
                },
            }
        ),
        encoding="utf-8",
    )
    (blind / "diagnosis-contract.json").write_text(
        json.dumps(
            {
                "schemaVersion": "paw.cloudops-diagnosis-contract.v1",
                "rootCauses": ["restart_loop", "bad_probe", "node_loss"],
                "validNodes": ["worker-01"],
                "validServices": {"demo": ["api"]},
                "validNamespaces": {"demo": ["demo"]},
                "faultObjectFormat": "kind/name",
                "faultObjectContract": {"allowedKinds": ["app", "node"]},
                "singlePrimaryFault": True,
                "rankOneMustBeEvidenceBacked": True,
            }
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    unittest.main()
