from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
import uuid
from http import HTTPStatus
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

from rag_ime.rag_benchmark_agent import (
    RagBenchmarkAgentGateway,
    RagBenchmarkAgentGatewayServer,
    RagBenchmarkAgentSpoolGateway,
    _sha256_json,
)
from rag_ime.rag_benchmark_sandbox import (
    RagBenchmarkSandbox,
    RagBenchmarkSandboxTool,
)


class RagBenchmarkAgentGatewayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.sandbox = RagBenchmarkSandbox(Path(self.temporary.name) / "runs")
        self.addCleanup(self.sandbox.close)
        self.gateway = RagBenchmarkAgentGateway(
            RagBenchmarkSandboxTool(self.sandbox)
        )

    def test_manifest_is_disclosed_only_to_bound_session_with_operation_subset(self) -> None:
        self.assertEqual([], self.gateway.runtime_manifests({"id": "session-a"}))

        binding = self.gateway.bind_session(
            "session-a",
            allowed_operations=("search", "status"),
        )
        manifests = self.gateway.runtime_manifests({"id": "session-a"})

        self.assertEqual("rag_benchmark", manifests[0]["name"])
        self.assertEqual("rag-benchmark-v1", manifests[0]["profile"])
        self.assertEqual("object", manifests[0]["parameters"]["type"])
        self.assertTrue(binding["ephemeral"])
        self.assertFalse(binding["productionCatalogChanged"])
        operations = {
            item["properties"]["op"]["const"]
            for item in manifests[0]["parameters"]["oneOf"]
        }
        self.assertEqual({"search", "status"}, operations)
        self.assertEqual([], self.gateway.runtime_manifests({"id": "session-b"}))

    def test_manifest_exposes_real_chunking_and_retrieval_parameter_bounds(self) -> None:
        self.gateway.bind_session(
            "session-a",
            allowed_operations=("create_base", "configure_base", "graph_rebuild"),
        )
        manifest = self.gateway.runtime_manifests({"id": "session-a"})[0]
        create_base = next(
            item
            for item in manifest["parameters"]["oneOf"]
            if item["properties"]["op"]["const"] == "create_base"
        )

        chunking = create_base["properties"]["chunkingConfig"]
        retrieval = create_base["properties"]["retrievalConfig"]
        self.assertEqual(200, chunking["properties"]["size"]["minimum"])
        self.assertEqual(8_000, chunking["properties"]["size"]["maximum"])
        self.assertEqual(20, retrieval["properties"]["candidateMultiplier"]["maximum"])
        self.assertIn("hybrid", retrieval["properties"]["mode"]["enum"])
        search = next(
            item
            for item in self.gateway.tool.manifest()["parameters"]["oneOf"]
            if item["properties"]["op"]["const"] == "search"
        )
        self.assertIn("evaluationCaseId", search["properties"])
        self.assertEqual(20, search["properties"]["topK"]["maximum"])
        self.assertEqual("boolean", search["properties"]["rerank"]["type"])
        self.assertEqual(
            100,
            search["properties"]["rerankCandidateDepth"]["maximum"],
        )
        graph = next(
            item
            for item in manifest["parameters"]["oneOf"]
            if item["properties"]["op"]["const"] == "graph_rebuild"
        )
        self.assertEqual(["luna", "deterministic"], graph["properties"]["extractorMode"]["enum"])
        self.assertEqual(0, graph["properties"]["expectedRevision"]["minimum"])

    def test_gateway_exposes_and_executes_aggregate_validation_without_qrels(self) -> None:
        sandbox = RagBenchmarkSandbox(
            Path(self.temporary.name) / "validation-runs",
            evaluation_suites={
                "validation-v1": [
                    {
                        "caseId": "case-1",
                        "split": "validation",
                        "query": "Beidou approver",
                        "relevant": {"doc-1": 1},
                    }
                ]
            },
        )
        self.addCleanup(sandbox.close)
        gateway = RagBenchmarkAgentGateway(RagBenchmarkSandboxTool(sandbox))
        gateway.bind_session(
            "session-validation",
            allowed_operations=(
                "create_run",
                "create_base",
                "import_documents",
                "evaluate_validation",
            ),
        )
        manifest = gateway.runtime_manifests({"id": "session-validation"})[0]
        evaluation_schema = next(
            item
            for item in manifest["parameters"]["oneOf"]
            if item["properties"]["op"]["const"] == "evaluate_validation"
        )
        self.assertIn("evaluationSuiteId", evaluation_schema["required"])

        def call(call_id: str, args: dict[str, object]) -> dict[str, object]:
            payload = self._call("session-validation", call_id, args)
            payload.pop("loadReceiptId")
            return gateway.execute(payload)

        run_id = call("run", {"op": "create_run"})["result"]["runId"]
        call(
            "base",
            {
                "op": "create_base",
                "runId": run_id,
                "baseAlias": "kb",
                "name": "Validation KB",
            },
        )
        call(
            "import",
            {
                "op": "import_documents",
                "runId": run_id,
                "baseAlias": "kb",
                "documents": [
                    {
                        "externalId": "doc-1",
                        "name": "policy.md",
                        "text": "Beidou approver is Lin Lan.",
                    }
                ],
            },
        )
        evaluated = call(
            "evaluate",
            {
                "op": "evaluate_validation",
                "runId": run_id,
                "baseAlias": "kb",
                "evaluationSuiteId": "validation-v1",
                "topK": 1,
                "mode": "lexical",
            },
        )["result"]

        self.assertEqual(1.0, evaluated["metrics"]["mrr"])
        self.assertFalse(evaluated["qrelsVisibleToAgent"])
        self.assertFalse(evaluated["perCaseResultsVisible"])
        ledger = gateway.ledger(session_id="session-validation")
        evaluation_record = ledger["items"][-1]
        self.assertEqual("evaluate_validation", evaluation_record["operation"])
        self.assertEqual(
            evaluated["evaluationReceiptSha256"],
            evaluation_record["resultSummary"]["evaluationReceiptSha256"],
        )
        self.assertNotIn("doc-1", json.dumps(evaluation_record, ensure_ascii=False))

    def test_execute_requires_binding_and_owner_scope_with_receipt_fallback(self) -> None:
        binding = self.gateway.bind_session("session-a")
        run = self.gateway.execute(
            self._call("session-a", "call-create", {"op": "create_run"})
        )["result"]

        with self.assertRaisesRegex(ValueError, "not bound"):
            self.gateway.execute(
                self._call(
                    "session-b",
                    "call-status-other",
                    {"op": "status", "runId": run["runId"]},
                )
            )
        missing_receipt = self._call(
            "session-a",
            "call-status-no-load",
            {"op": "status", "runId": run["runId"]},
        )
        missing_receipt.pop("loadReceiptId")
        fallback_status = self.gateway.execute(missing_receipt)
        self.assertTrue(fallback_status["ok"])

        status = self.gateway.execute(
            self._call(
                "session-a",
                "call-status",
                {"op": "status", "runId": run["runId"]},
            )
        )
        self.assertTrue(status["ok"])
        self.assertEqual("rag_benchmark", status["tool"])
        ledger = self.gateway.ledger(session_id="session-a")
        self.assertEqual(3, ledger["itemCount"])
        self.assertEqual(
            "ephemeral_session_binding",
            ledger["items"][1]["authorizationSource"],
        )
        self.assertEqual(
            binding["authorizationReceiptId"],
            ledger["items"][1]["authorizationReceiptId"],
        )
        self.assertEqual(
            "runtime_load_receipt",
            ledger["items"][2]["authorizationSource"],
        )

    def test_runtime_source_loop_id_is_accepted_and_hashed_in_ledger(self) -> None:
        self.gateway.bind_session("session-a")
        request = self._call(
            "session-a",
            "call-create-source-loop",
            {"op": "create_run", "label": "source-loop"},
        )
        request["sourceLoopId"] = "pi:message:assistant:101"

        result = self.gateway.execute(request)

        self.assertTrue(result["ok"])
        ledger_item = self.gateway.ledger(session_id="session-a")["items"][0]
        self.assertEqual(
            hashlib.sha256(request["sourceLoopId"].encode("utf-8")).hexdigest(),
            ledger_item["sourceLoopIdSha256"],
        )
        self.assertNotIn(request["sourceLoopId"], json.dumps(ledger_item))

    def test_import_ledger_hashes_inline_text_instead_of_copying_it(self) -> None:
        self.gateway.bind_session("session-a")
        run_id = self.gateway.execute(
            self._call("session-a", "call-run", {"op": "create_run"})
        )["result"]["runId"]
        self.gateway.execute(
            self._call(
                "session-a",
                "call-base",
                {
                    "op": "create_base",
                    "runId": run_id,
                    "baseAlias": "kb",
                    "name": "Fixture",
                },
            )
        )
        secret_marker = "public fixture body that must not be duplicated"
        self.gateway.execute(
            self._call(
                "session-a",
                "call-import",
                {
                    "op": "import_documents",
                    "runId": run_id,
                    "baseAlias": "kb",
                    "documents": [
                        {
                            "externalId": "doc-1",
                            "name": "doc-1.md",
                            "text": secret_marker,
                        }
                    ],
                },
            )
        )

        ledger = self.gateway.ledger(session_id="session-a")

        self.assertNotIn(secret_marker, json.dumps(ledger))
        imported = ledger["items"][-1]["args"]["documents"][0]
        self.assertEqual(len(secret_marker.encode("utf-8")), imported["byteSize"])
        self.assertEqual(64, len(imported["sha256"]))
        result_document = ledger["items"][-1]["resultSummary"]["documents"][0]
        self.assertEqual("doc-1", result_document["externalDocumentId"])
        self.assertNotIn("text", result_document)

        search = self.gateway.execute(
            self._call(
                "session-a",
                "call-search",
                {
                    "op": "search",
                    "runId": run_id,
                    "baseAlias": "kb",
                    "query": "public fixture body",
                    "topK": 1,
                    "mode": "lexical",
                    "threshold": 0,
                    "rerank": False,
                    "evaluationCaseId": "case-01",
                },
            )
        )
        result_hit = search["result"]["hits"][0]
        ledger_hit = self.gateway.ledger(session_id="session-a")["items"][-1][
            "resultSummary"
        ]["hits"][0]
        self.assertEqual("K1", result_hit["citationRef"])
        self.assertEqual(result_hit["citationRef"], ledger_hit["citationRef"])
        self.assertEqual(
            result_hit["citation"]["citationRef"],
            ledger_hit["citation"]["citationRef"],
        )

        repeated_search = self.gateway.execute(
            self._call(
                "session-a",
                "call-search-repeat",
                {
                    "op": "search",
                    "runId": run_id,
                    "baseAlias": "kb",
                    "query": "fixture",
                    "topK": 1,
                    "mode": "lexical",
                    "threshold": 0,
                    "rerank": False,
                    "evaluationCaseId": "case-01",
                },
            )
        )
        repeated_hit = repeated_search["result"]["hits"][0]
        self.assertEqual("doc-1", repeated_hit["externalDocumentId"])
        self.assertEqual("K1", repeated_hit["citationRef"])
        self.assertEqual("K1", repeated_hit["citation"]["citationRef"])

    def test_explicit_shared_owner_allows_isolated_sessions_to_use_one_lane_base(self) -> None:
        owner = "lane-owner"
        first = self.gateway.bind_session(
            "session-a",
            sandbox_owner_id=owner,
        )
        self.gateway.bind_session(
            "session-b",
            sandbox_owner_id=owner,
            allowed_operations=("status",),
        )
        run_id = self.gateway.execute(
            self._call("session-a", "call-run", {"op": "create_run"})
        )["result"]["runId"]

        status = self.gateway.execute(
            self._call("session-b", "call-status", {"op": "status", "runId": run_id})
        )

        self.assertTrue(status["ok"])
        self.assertEqual(
            first["sandboxOwnerSha256"],
            self.gateway.ledger(session_id="session-b")["items"][0][
                "sandboxOwnerSha256"
            ],
        )

    def test_bound_run_is_hidden_from_schema_and_injected_by_gateway(self) -> None:
        owner = "lane-owner"
        self.gateway.bind_session("session-a", sandbox_owner_id=owner)
        run_id = self.gateway.execute(
            self._call("session-a", "call-run", {"op": "create_run"})
        )["result"]["runId"]
        binding = self.gateway.bind_session(
            "session-b",
            sandbox_owner_id=owner,
            sandbox_run_id=run_id,
            allowed_operations=("status",),
        )

        manifest = self.gateway.runtime_manifests({"id": "session-b"})[0]
        status_schema = manifest["parameters"]["oneOf"][0]
        self.assertNotIn("runId", status_schema["required"])
        self.assertNotIn("runId", status_schema["properties"])
        self.assertTrue(binding["runBound"])

        response = self.gateway.execute(
            self._call("session-b", "call-status", {"op": "status"})
        )

        self.assertTrue(response["ok"])
        self.assertEqual(
            run_id,
            self.gateway.ledger(session_id="session-b")["items"][0]["args"]["runId"],
        )
        with self.assertRaisesRegex(ValueError, "bound evaluation run"):
            self.gateway.execute(
                self._call(
                    "session-b",
                    "call-wrong-run",
                    {"op": "status", "runId": "0" * 32},
                )
            )

    def test_delegated_child_inherits_exact_run_without_base_tool_authority(self) -> None:
        class BaseGateway:
            def runtime_manifests(self, _session):
                return [
                    {"name": "agents", "parameters": {"type": "object"}},
                    {"name": "memory", "parameters": {"type": "object"}},
                ]

            def execute(self, payload):
                return {
                    "schemaVersion": "rag-ime.agent-tool-result.v1",
                    "ok": True,
                    "tool": payload["tool"],
                    "operation": payload["args"]["op"],
                    "result": {"accepted": True},
                }

        parent_map = {"child-session": "parent-session"}
        self.gateway.base_gateway = BaseGateway()
        self.gateway.delegated_parent_loader = parent_map.get
        self.gateway.bind_session(
            "parent-session",
            allowed_base_tools=("agents",),
        )
        run_id = self.gateway.execute(
            self._call("parent-session", "call-run", {"op": "create_run"})
        )["result"]["runId"]
        self.gateway.bind_session(
            "parent-session",
            allowed_operations=("search", "status"),
            sandbox_run_id=run_id,
            allowed_base_tools=("agents",),
        )

        parent_names = {
            manifest["name"]
            for manifest in self.gateway.runtime_manifests({"id": "parent-session"})
        }
        child_manifests = self.gateway.runtime_manifests({"id": "child-session"})
        child_names = {manifest["name"] for manifest in child_manifests}

        self.assertEqual({"agents", "rag_benchmark"}, parent_names)
        self.assertEqual({"rag_benchmark"}, child_names)
        self.assertTrue(child_manifests[0]["runBound"])
        status = self.gateway.execute(
            self._call("child-session", "child-status", {"op": "status"})
        )
        self.assertTrue(status["ok"])
        with self.assertRaisesRegex(ValueError, "not enabled"):
            self.gateway.execute(
                {
                    **self._call("child-session", "child-agents", {"op": "status"}),
                    "tool": "agents",
                }
            )
        parent_agents = self.gateway.execute(
            {
                **self._call("parent-session", "parent-agents", {"op": "catalog"}),
                "tool": "agents",
            }
        )
        self.assertTrue(parent_agents["ok"])
        lineage = self.gateway.lineage_ledger("parent-session")
        self.assertEqual(1, lineage["childSessionCount"])
        self.assertEqual(2, lineage["itemCount"])
        self.assertEqual("child-session", lineage["items"][-1]["sessionId"])
        self.assertEqual(
            ["parent-session", "child-session"],
            self.gateway.unbind_lineage("parent-session"),
        )
        self.assertEqual([], self.gateway.runtime_manifests({"id": "parent-session"}))

    def test_loopback_server_requires_capability_token(self) -> None:
        self.gateway.bind_session("session-a")
        server = RagBenchmarkAgentGatewayServer(
            self.gateway,
            token="benchmark-token",
        )
        try:
            server.start()
        except PermissionError:
            self.skipTest("current execution sandbox forbids loopback socket binding")
        self.addCleanup(server.close)
        direct_opener = build_opener(ProxyHandler({}))
        payload = self._call(
            "session-a",
            "call-http",
            {"op": "create_run", "label": "http"},
        )
        denied = Request(
            server.tool_gateway_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(HTTPError) as caught:
            direct_opener.open(denied, timeout=5)
        caught.exception.close()

        allowed = Request(
            server.tool_gateway_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-RAG-IME-Agent-Token": "benchmark-token",
            },
            method="POST",
        )
        with direct_opener.open(allowed, timeout=5) as response:
            result = json.loads(response.read().decode("utf-8"))

        self.assertEqual(403, caught.exception.code)
        self.assertTrue(result["ok"])
        self.assertEqual("create_run", result["operation"])

    def test_loopback_server_records_client_disconnect_without_thread_error(self) -> None:
        class BrokenResponseHandler:
            close_connection = False

            def send_response(self, _status: int) -> None:
                return None

            def send_header(self, _name: str, _value: str) -> None:
                return None

            def end_headers(self) -> None:
                raise BrokenPipeError(32, "client disconnected")

        server = RagBenchmarkAgentGatewayServer(
            self.gateway,
            token="benchmark-token",
        )

        written = server._write_response(
            BrokenResponseHandler(),
            HTTPStatus.OK,
            {"ok": True},
        )

        receipt = server.transport_receipt()
        self.assertFalse(written)
        self.assertFalse(receipt["accepted"])
        self.assertEqual(1, receipt["failureCount"])
        self.assertEqual(["BrokenPipeError"], receipt["failureTypes"])
        self.assertTrue(receipt["receiptSha256"])

    def test_loopback_server_records_other_socket_write_failures(self) -> None:
        class FailedResponseHandler:
            close_connection = False

            def send_response(self, _status: int) -> None:
                return None

            def send_header(self, _name: str, _value: str) -> None:
                return None

            def end_headers(self) -> None:
                raise OSError(5, "socket write failed")

        handler = FailedResponseHandler()
        server = RagBenchmarkAgentGatewayServer(
            self.gateway,
            token="benchmark-token",
        )

        written = server._write_response(handler, HTTPStatus.OK, {"ok": True})

        receipt = server.transport_receipt()
        self.assertFalse(written)
        self.assertTrue(handler.close_connection)
        self.assertFalse(receipt["accepted"])
        self.assertEqual(1, receipt["failureCount"])
        self.assertEqual(["OSError"], receipt["failureTypes"])
        claimed = receipt.pop("receiptSha256")
        self.assertEqual(_sha256_json(receipt), claimed)

    def test_private_spool_gateway_requires_token_without_binding_socket(self) -> None:
        self.gateway.bind_session("session-a")
        spool_dir = Path(self.temporary.name) / "tool-spool"
        with RagBenchmarkAgentSpoolGateway(
            self.gateway,
            spool_dir=spool_dir,
            token="benchmark-token",
        ) as server:
            self.assertEqual(
                "rag-ime-spool://gateway/api/agent/tool/execute",
                server.tool_gateway_url,
            )
            denied = self._spool_call(
                spool_dir,
                payload=self._call(
                    "session-a",
                    "call-spool-denied",
                    {"op": "create_run", "label": "denied"},
                ),
                token="wrong-token",
            )
            allowed = self._spool_call(
                spool_dir,
                payload=self._call(
                    "session-a",
                    "call-spool-allowed",
                    {"op": "create_run", "label": "allowed"},
                ),
                token="benchmark-token",
            )

        self.assertEqual(403, denied["status"])
        self.assertFalse(json.loads(denied["body"])["ok"])
        self.assertEqual(200, allowed["status"])
        result = json.loads(allowed["body"])
        self.assertTrue(result["ok"])
        self.assertEqual("create_run", result["operation"])

    def test_node_wrapper_routes_custom_fetch_through_private_spool(self) -> None:
        node = shutil.which("node")
        if not node:
            self.skipTest("Node is unavailable")
        self.gateway.bind_session("session-a")
        temporary_root = Path(self.temporary.name)
        spool_dir = temporary_root / "node-tool-spool"
        probe = temporary_root / "spool-probe.mjs"
        payload = self._call(
            "session-a",
            "call-node-spool",
            {"op": "create_run", "label": "node-spool"},
        )
        probe.write_text(
            "const response = await fetch(\n"
            "  'rag-ime-spool://gateway/api/agent/tool/execute',\n"
            "  {method:'POST',headers:{'content-type':'application/json',"
            "'x-rag-ime-agent-token':process.env.BENCHMARK_TOKEN},"
            f"body:{json.dumps(json.dumps(payload))}}},\n"
            ");\n"
            "console.log(JSON.stringify({status:response.status,body:await response.json()}));\n",
            encoding="utf-8",
        )
        wrapper = (
            Path(__file__).resolve().parents[1]
            / "scripts"
            / "rag_agent_spool_runtime_wrapper.mjs"
        )
        with RagBenchmarkAgentSpoolGateway(
            self.gateway,
            spool_dir=spool_dir,
            token="benchmark-token",
        ):
            environment = os.environ.copy()
            environment.update(
                {
                    "BENCHMARK_TOKEN": "benchmark-token",
                    "RAG_IME_BENCHMARK_GATEWAY_SPOOL": str(spool_dir),
                    "RAG_IME_BENCHMARK_RUNTIME_ENTRYPOINT": str(probe),
                    "RAG_IME_BENCHMARK_GATEWAY_TIMEOUT_MS": "5000",
                }
            )
            completed = subprocess.run(
                [node, str(wrapper)],
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
                env=environment,
            )

        result = json.loads(completed.stdout)
        self.assertEqual(200, result["status"])
        self.assertTrue(result["body"]["ok"])
        self.assertEqual("create_run", result["body"]["operation"])

    @staticmethod
    def _spool_call(
        spool_dir: Path,
        *,
        payload: dict[str, object],
        token: str,
    ) -> dict[str, object]:
        request_id = str(uuid.uuid4())
        envelope = {
            "schemaVersion": "rag-ime.rag-benchmark-spool-request.v1",
            "requestId": request_id,
            "url": "rag-ime-spool://gateway/api/agent/tool/execute",
            "method": "POST",
            "headers": {
                "content-type": "application/json",
                "x-rag-ime-agent-token": token,
            },
            "body": json.dumps(payload),
        }
        request_path = spool_dir / f"{request_id}.request.json"
        temporary = spool_dir / f".{request_id}.tmp"
        temporary.write_text(json.dumps(envelope), encoding="utf-8")
        temporary.replace(request_path)
        response_path = spool_dir / f"{request_id}.response.json"
        deadline = time.monotonic() + 5
        while not response_path.is_file():
            if time.monotonic() >= deadline:
                raise TimeoutError("benchmark spool response did not arrive")
            time.sleep(0.01)
        return json.loads(response_path.read_text(encoding="utf-8"))

    @staticmethod
    def _call(
        session_id: str,
        tool_call_id: str,
        args: dict[str, object],
    ) -> dict[str, object]:
        return {
            "schemaVersion": "rag-ime.agent-tool-call.v1",
            "sessionId": session_id,
            "tool": "rag_benchmark",
            "toolCallId": tool_call_id,
            "args": args,
            "loadReceiptId": "load-receipt",
        }


if __name__ == "__main__":
    unittest.main()
