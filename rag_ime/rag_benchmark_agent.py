from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .rag_benchmark_sandbox import (
    RagBenchmarkSandboxError,
    RagBenchmarkSandboxTool,
)


RAG_BENCHMARK_AGENT_PROFILE = "rag-benchmark-v1"
RAG_BENCHMARK_AGENT_RESULT_SCHEMA_VERSION = (
    "rag-ime.rag-benchmark-agent-tool-result.v1"
)
_TOOL_CALL_SCHEMA_VERSION = "rag-ime.agent-tool-call.v1"
_ALL_OPERATIONS = (
    "create_run",
    "create_base",
    "import_documents",
    "configure_base",
    "rebuild_preview",
    "rebuild",
    "graph_rebuild",
    "search",
    "evaluate_validation",
    "status",
    "cleanup",
)
_TOOL_CALL_FIELDS = frozenset(
    {
        "schemaVersion",
        "sessionId",
        "tool",
        "toolCallId",
        "args",
        "loadReceiptId",
    }
)
_SPOOL_REQUEST_SCHEMA_VERSION = "rag-ime.rag-benchmark-spool-request.v1"
_SPOOL_RESPONSE_SCHEMA_VERSION = "rag-ime.rag-benchmark-spool-response.v1"
_SPOOL_REQUEST_NAME = re.compile(
    r"^(?P<request_id>[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})\.request\.json$"
)


class RagBenchmarkAgentGateway:
    """Session-bound Agent bridge for the benchmark-only Knowledge sandbox.

    The production Tool catalog never contains ``rag_benchmark``. A local
    evaluation harness must bind each private Session explicitly, and the
    binding disappears with this process.
    """

    def __init__(
        self,
        tool: RagBenchmarkSandboxTool,
        *,
        base_gateway: object | None = None,
        session_loader: Callable[[str], Mapping[str, object]] | None = None,
        delegated_parent_loader: Callable[[str], str | None] | None = None,
    ) -> None:
        self.tool = tool
        self.base_gateway = base_gateway
        self.session_loader = session_loader
        self.delegated_parent_loader = delegated_parent_loader
        self._lock = threading.RLock()
        self._bindings: dict[str, frozenset[str]] = {}
        self._binding_receipts: dict[str, str] = {}
        self._binding_owners: dict[str, str] = {}
        self._binding_run_ids: dict[str, str] = {}
        self._binding_base_tools: dict[str, frozenset[str]] = {}
        self._binding_parents: dict[str, str] = {}
        self._citation_refs: dict[tuple[str, str], dict[str, str]] = {}
        self._ledger: list[dict[str, object]] = []

    def bind_session(
        self,
        session_id: object,
        *,
        allowed_operations: Sequence[str] = _ALL_OPERATIONS,
        sandbox_owner_id: object | None = None,
        sandbox_run_id: object | None = None,
        allowed_base_tools: Sequence[str] = (),
        parent_session_id: object | None = None,
    ) -> dict[str, object]:
        normalized_session_id = _text(session_id, "sessionId", maximum=256)
        normalized_owner_id = _text(
            sandbox_owner_id if sandbox_owner_id is not None else normalized_session_id,
            "sandboxOwnerId",
            maximum=256,
        )
        operations = tuple(dict.fromkeys(str(item).strip() for item in allowed_operations))
        if not operations or any(item not in _ALL_OPERATIONS for item in operations):
            raise ValueError("benchmark binding contains an unsupported operation")
        normalized_run_id = str(sandbox_run_id or "").strip()
        if normalized_run_id and re.fullmatch(r"[a-f0-9]{32}", normalized_run_id) is None:
            raise ValueError("sandboxRunId must be a 32-character lowercase hex run ID")
        operation_set = frozenset(operations)
        base_tool_set = frozenset(
            _text(item, "allowedBaseTool", maximum=120)
            for item in dict.fromkeys(str(value).strip() for value in allowed_base_tools)
        )
        normalized_parent_id = str(parent_session_id or "").strip()
        if normalized_parent_id == normalized_session_id:
            raise ValueError("delegated benchmark binding cannot parent itself")
        manifest = self._benchmark_runtime_manifest(
            operation_set,
            bound_run_id=normalized_run_id,
        )
        authorization_receipt_id = "binding:" + _sha256_json(
            {
                "sessionId": normalized_session_id,
                "sandboxOwnerSha256": hashlib.sha256(
                    normalized_owner_id.encode("utf-8")
                ).hexdigest(),
                "manifestSha256": _sha256_json(manifest),
                "allowedOperations": sorted(operation_set),
                "allowedBaseTools": sorted(base_tool_set),
                "parentSessionSha256": (
                    hashlib.sha256(normalized_parent_id.encode("utf-8")).hexdigest()
                    if normalized_parent_id
                    else ""
                ),
                "sandboxRunSha256": (
                    hashlib.sha256(normalized_run_id.encode("utf-8")).hexdigest()
                    if normalized_run_id
                    else ""
                ),
            }
        )
        with self._lock:
            self._bindings[normalized_session_id] = operation_set
            self._binding_receipts[normalized_session_id] = authorization_receipt_id
            self._binding_owners[normalized_session_id] = normalized_owner_id
            self._binding_run_ids[normalized_session_id] = normalized_run_id
            self._binding_base_tools[normalized_session_id] = base_tool_set
            self._binding_parents[normalized_session_id] = normalized_parent_id
        receipt: dict[str, object] = {
            "schemaVersion": "rag-ime.rag-benchmark-agent-binding.v1",
            "sessionId": normalized_session_id,
            "profile": RAG_BENCHMARK_AGENT_PROFILE,
            "allowedOperations": [
                item for item in _ALL_OPERATIONS if item in operation_set
            ],
            "allowedBaseTools": sorted(base_tool_set),
            "delegatedChild": bool(normalized_parent_id),
            "ephemeral": True,
            "productionCatalogChanged": False,
            "manifestSha256": _sha256_json(manifest),
            "authorizationReceiptId": authorization_receipt_id,
            "sandboxOwnerSha256": hashlib.sha256(
                normalized_owner_id.encode("utf-8")
            ).hexdigest(),
            "runBound": bool(normalized_run_id),
            "sandboxRunSha256": (
                hashlib.sha256(normalized_run_id.encode("utf-8")).hexdigest()
                if normalized_run_id
                else ""
            ),
        }
        receipt["bindingSha256"] = _sha256_json(receipt)
        return receipt

    def unbind_session(self, session_id: object) -> bool:
        normalized_session_id = _text(session_id, "sessionId", maximum=256)
        with self._lock:
            removed = self._bindings.pop(normalized_session_id, None) is not None
            self._binding_receipts.pop(normalized_session_id, None)
            self._binding_owners.pop(normalized_session_id, None)
            self._binding_run_ids.pop(normalized_session_id, None)
            self._binding_base_tools.pop(normalized_session_id, None)
            self._binding_parents.pop(normalized_session_id, None)
            return removed

    def unbind_lineage(self, parent_session_id: object) -> list[str]:
        parent_id = _text(parent_session_id, "parentSessionId", maximum=256)
        session_ids = self.lineage_session_ids(parent_id)
        for session_id in reversed(session_ids):
            self.unbind_session(session_id)
        return session_ids

    def lineage_session_ids(self, parent_session_id: object) -> list[str]:
        parent_id = _text(parent_session_id, "parentSessionId", maximum=256)
        with self._lock:
            parent_map = dict(self._binding_parents)
        selected = [parent_id]
        while True:
            additions = sorted(
                child
                for child, direct_parent in parent_map.items()
                if child not in selected and direct_parent in selected
            )
            if not additions:
                return selected
            selected.extend(additions)

    def runtime_manifests(
        self,
        session: Mapping[str, object],
    ) -> list[Mapping[str, object]]:
        session_id = str(session.get("id") or "").strip()
        self._ensure_delegated_binding(session_id)
        with self._lock:
            operations = self._bindings.get(session_id)
            bound_run_id = self._binding_run_ids.get(session_id, "")
            allowed_base_tools = self._binding_base_tools.get(session_id, frozenset())
        if operations is None:
            return []
        manifests: list[Mapping[str, object]] = []
        provider = getattr(self.base_gateway, "runtime_manifests", None)
        if allowed_base_tools and callable(provider):
            manifests.extend(
                dict(item)
                for item in provider(session)
                if str(item.get("name") or "") in allowed_base_tools
            )
        if operations is not None:
            manifests.append(
                self._benchmark_runtime_manifest(
                    operations,
                    bound_run_id=bound_run_id,
                )
            )
        return manifests

    def execute(self, payload: Mapping[str, object]) -> dict[str, object]:
        tool_id = str(payload.get("tool") or "").strip()
        if tool_id != self.tool.tool_id:
            session_id = _text(payload.get("sessionId"), "sessionId", maximum=256)
            session = self.session_loader(session_id) if self.session_loader else None
            if session is not None and str(session.get("status") or "") == "archived":
                raise ValueError("archived sessions cannot execute benchmark tools")
            with self._lock:
                allowed_base_tools = self._binding_base_tools.get(session_id)
            if allowed_base_tools is None or tool_id not in allowed_base_tools:
                raise ValueError("tool is not enabled for this evaluation session")
            executor = getattr(self.base_gateway, "execute", None)
            if not callable(executor):
                raise ValueError("tool is not enabled for this evaluation harness")
            return dict(executor(payload))

        request = _benchmark_tool_call(payload)
        session_id = str(request["sessionId"])
        session = self.session_loader(session_id) if self.session_loader else None
        if session is not None and str(session.get("status") or "") == "archived":
            raise ValueError("archived sessions cannot execute benchmark tools")
        with self._lock:
            operations = self._bindings.get(session_id)
            binding_receipt_id = self._binding_receipts.get(session_id, "")
            sandbox_owner_id = self._binding_owners.get(session_id, "")
            bound_run_id = self._binding_run_ids.get(session_id, "")
        if operations is None or not binding_receipt_id or not sandbox_owner_id:
            raise ValueError("rag_benchmark is not bound to this evaluation session")
        args = request["args"]
        assert isinstance(args, Mapping)
        operation = str(args.get("op") or "").strip()
        if operation not in operations:
            raise ValueError(
                f"rag_benchmark operation {operation or '(empty)'} is not allowed for this session"
            )
        if bound_run_id and operation != "create_run":
            supplied_run_id = str(args.get("runId") or "").strip()
            if supplied_run_id and supplied_run_id != bound_run_id:
                raise ValueError("rag_benchmark runId does not match the bound evaluation run")
            request = dict(request)
            request["args"] = {**dict(args), "runId": bound_run_id}
            args = request["args"]

        started_ns = time.perf_counter_ns()
        try:
            result = self.tool.execute(sandbox_owner_id, args)
        except Exception as exc:
            self._append_ledger(
                request=request,
                operation=operation,
                started_ns=started_ns,
                result=None,
                error=exc,
                binding_receipt_id=binding_receipt_id,
                sandbox_owner_id=sandbox_owner_id,
            )
            raise
        result = self._with_case_scoped_citation_refs(
            operation,
            args,
            result,
            bound_run_id=bound_run_id,
        )
        self._append_ledger(
            request=request,
            operation=operation,
            started_ns=started_ns,
            result=result,
            error=None,
            binding_receipt_id=binding_receipt_id,
            sandbox_owner_id=sandbox_owner_id,
        )
        return {
            "schemaVersion": RAG_BENCHMARK_AGENT_RESULT_SCHEMA_VERSION,
            "ok": True,
            "tool": self.tool.tool_id,
            "operation": operation,
            "result": result,
        }

    def _with_case_scoped_citation_refs(
        self,
        operation: str,
        args: Mapping[str, object],
        result: Mapping[str, object],
        *,
        bound_run_id: str,
    ) -> dict[str, object]:
        projected = deepcopy(dict(result))
        hits = projected.get("hits")
        case_id = str(args.get("evaluationCaseId") or "").strip()
        run_id = str(projected.get("runId") or bound_run_id or "").strip()
        if operation != "search" or not case_id or not run_id or not isinstance(hits, list):
            return projected
        with self._lock:
            references = self._citation_refs.setdefault((run_id, case_id), {})
            for hit in hits:
                if not isinstance(hit, dict):
                    continue
                external_id = str(hit.get("externalDocumentId") or "").strip()
                if not external_id:
                    continue
                citation_ref = references.get(external_id)
                if not citation_ref:
                    citation_ref = f"K{len(references) + 1}"
                    references[external_id] = citation_ref
                hit["citationRef"] = citation_ref
                citation = hit.get("citation")
                if isinstance(citation, dict):
                    citation["citationRef"] = citation_ref
        return projected

    def lineage_ledger(self, parent_session_id: object) -> dict[str, object]:
        parent_id = _text(parent_session_id, "parentSessionId", maximum=256)
        session_ids = self.lineage_session_ids(parent_id)
        selected = set(session_ids)
        with self._lock:
            items = [
                deepcopy(item)
                for item in self._ledger
                if str(item.get("sessionId") or "") in selected
            ]
        report: dict[str, object] = {
            "schemaVersion": "rag-ime.rag-benchmark-agent-lineage-ledger.v1",
            "sessionId": parent_id,
            "sessionIds": session_ids,
            "childSessionCount": max(0, len(session_ids) - 1),
            "itemCount": len(items),
            "items": items,
        }
        report["ledgerSha256"] = _sha256_json(report)
        return report

    def ledger(self, *, session_id: str = "") -> dict[str, object]:
        normalized = str(session_id or "").strip()
        with self._lock:
            items = [
                deepcopy(item)
                for item in self._ledger
                if not normalized or item["sessionId"] == normalized
            ]
        report: dict[str, object] = {
            "schemaVersion": "rag-ime.rag-benchmark-agent-ledger.v1",
            "sessionId": normalized,
            "itemCount": len(items),
            "items": items,
        }
        report["ledgerSha256"] = _sha256_json(report)
        return report

    def _benchmark_runtime_manifest(
        self,
        operations: frozenset[str],
        *,
        bound_run_id: str = "",
    ) -> dict[str, object]:
        source = self.tool.manifest()
        parameters = _operation_parameter_subset(
            source["parameters"],
            operations,
            bound_run_id=bound_run_id,
        )
        return {
            "name": self.tool.tool_id,
            "description": (
                "Operate a run-owned local Knowledge benchmark sandbox, including Luna-backed "
                "Knowledge-only graph construction, an independent bounded reranker, and "
                "aggregate validation scoring whose qrels remain host-only. "
                "Only public or synthetic fixture queries and Tool results may be sent to the configured model Provider."
            ),
            "parameters": parameters,
            "when": [
                "A local evaluation Session must build, configure, rebuild, construct a Knowledge graph, independently rerank, score a registered validation suite, inspect, or clean its bound Knowledge sandbox"
            ],
            "notFor": [
                "Production Knowledge bases, private documents, personal Memory, or host filesystem paths"
            ],
            "input": "One allowlisted benchmark operation and run-owned inline public fixture data.",
            "output": "Bounded Knowledge result with external document identities, citations, usage, and lifecycle receipts.",
            "does": "Builds and optimizes only the current Session's isolated Knowledge benchmark run.",
            "profile": RAG_BENCHMARK_AGENT_PROFILE,
            "risk": "R0",
            "runBound": bool(bound_run_id),
        }

    def _ensure_delegated_binding(self, session_id: str) -> None:
        if not session_id:
            return
        with self._lock:
            if session_id in self._bindings:
                return
        loader = self.delegated_parent_loader
        if loader is None:
            return
        parent_id = str(loader(session_id) or "").strip()
        if not parent_id:
            return
        with self._lock:
            parent_operations = self._bindings.get(parent_id)
            owner_id = self._binding_owners.get(parent_id, "")
            run_id = self._binding_run_ids.get(parent_id, "")
        if parent_operations is None or not owner_id or not run_id:
            raise ValueError("delegated benchmark parent has no active run binding")
        child_operations = tuple(
            operation
            for operation in ("search", "status")
            if operation in parent_operations
        )
        if "search" not in child_operations:
            raise ValueError("delegated benchmark parent does not allow search")
        self.bind_session(
            session_id,
            allowed_operations=child_operations,
            sandbox_owner_id=owner_id,
            sandbox_run_id=run_id,
            parent_session_id=parent_id,
        )

    def _append_ledger(
        self,
        *,
        request: Mapping[str, object],
        operation: str,
        started_ns: int,
        result: Mapping[str, object] | None,
        error: Exception | None,
        binding_receipt_id: str,
        sandbox_owner_id: str,
    ) -> None:
        args = request.get("args")
        assert isinstance(args, Mapping)
        runtime_load_receipt_id = str(request.get("loadReceiptId") or "")
        authorization_receipt_id = runtime_load_receipt_id or binding_receipt_id
        item: dict[str, object] = {
            "sequence": 0,
            "sessionId": str(request["sessionId"]),
            "sandboxOwnerSha256": hashlib.sha256(
                sandbox_owner_id.encode("utf-8")
            ).hexdigest(),
            "toolCallId": str(request["toolCallId"]),
            "loadReceiptId": runtime_load_receipt_id,
            "authorizationReceiptId": authorization_receipt_id,
            "authorizationSource": (
                "runtime_load_receipt"
                if runtime_load_receipt_id
                else "ephemeral_session_binding"
            ),
            "operation": operation,
            "args": _safe_args_summary(operation, args),
            "ok": error is None,
            "elapsedMs": round((time.perf_counter_ns() - started_ns) / 1_000_000, 3),
            "resultSha256": _sha256_json(result) if result is not None else "",
            "resultSummary": (
                _safe_result_summary(operation, result)
                if result is not None
                else None
            ),
            "errorType": type(error).__name__ if error is not None else "",
            "errorCode": str(getattr(error, "code", "")) if error is not None else "",
        }
        with self._lock:
            item["sequence"] = len(self._ledger) + 1
            item["receiptSha256"] = _sha256_json(item)
            self._ledger.append(item)


class RagBenchmarkAgentGatewayServer:
    """Loopback HTTP bridge consumed by managed Pi during isolated evals."""

    transport = "loopback-http-v1"

    def __init__(
        self,
        gateway: RagBenchmarkAgentGateway,
        *,
        token: str | None = None,
        max_request_bytes: int = 8 * 1024 * 1024,
    ) -> None:
        self.gateway = gateway
        self.token = str(token or secrets.token_urlsafe(32))
        self.max_request_bytes = max(1_024, int(max_request_bytes))
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def tool_gateway_url(self) -> str:
        if self._server is None:
            raise RuntimeError("benchmark Agent gateway server is not running")
        return f"http://127.0.0.1:{self._server.server_port}/api/agent/tool/execute"

    def start(self) -> "RagBenchmarkAgentGatewayServer":
        if self._server is not None:
            return self
        gateway = self.gateway
        expected_token = self.token
        maximum = self.max_request_bytes

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                if self.path != "/api/agent/tool/execute":
                    self._write(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not found"})
                    return
                provided = self.headers.get("X-RAG-IME-Agent-Token", "")
                if not provided or not hmac.compare_digest(provided, expected_token):
                    self._write(
                        HTTPStatus.FORBIDDEN,
                        {"ok": False, "error": "agent capability token required"},
                    )
                    return
                try:
                    length = int(self.headers.get("Content-Length") or "0")
                except ValueError:
                    length = 0
                if length <= 0 or length > maximum:
                    self._write(
                        HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                        {"ok": False, "error": "invalid benchmark Tool request size"},
                    )
                    return
                try:
                    payload = json.loads(self.rfile.read(length).decode("utf-8"))
                    if not isinstance(payload, Mapping):
                        raise ValueError("benchmark Tool request must be an object")
                    response = gateway.execute(payload)
                except (RagBenchmarkSandboxError, TypeError, ValueError, json.JSONDecodeError) as exc:
                    self._write(
                        HTTPStatus.BAD_REQUEST,
                        {
                            "ok": False,
                            "error": str(exc),
                            "errorCode": str(getattr(exc, "code", "invalid_request")),
                        },
                    )
                    return
                self._write(HTTPStatus.OK, response)

            def _write(self, status: HTTPStatus, payload: Mapping[str, object]) -> None:
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(int(status))
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, _format: str, *_args: object) -> None:
                return None

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="rag-benchmark-agent-gateway",
            daemon=True,
        )
        self._thread.start()
        return self

    def close(self) -> None:
        server = self._server
        thread = self._thread
        self._server = None
        self._thread = None
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=5)

    def __enter__(self) -> "RagBenchmarkAgentGatewayServer":
        return self.start()

    def __exit__(self, *_args: object) -> None:
        self.close()


class RagBenchmarkAgentSpoolGateway:
    """Private filesystem bridge for eval sandboxes that cannot bind sockets."""

    transport = "private-file-spool-v1"

    def __init__(
        self,
        gateway: RagBenchmarkAgentGateway,
        *,
        spool_dir: str | Path,
        token: str | None = None,
        max_request_bytes: int = 8 * 1024 * 1024,
    ) -> None:
        self.gateway = gateway
        self.spool_dir = Path(spool_dir).expanduser()
        self.token = str(token or secrets.token_urlsafe(32))
        self.max_request_bytes = max(1_024, int(max_request_bytes))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def tool_gateway_url(self) -> str:
        thread = self._thread
        if thread is None or not thread.is_alive():
            raise RuntimeError("benchmark Agent spool gateway is not running")
        return "rag-ime-spool://gateway/api/agent/tool/execute"

    def start(self) -> "RagBenchmarkAgentSpoolGateway":
        if self._thread is not None and self._thread.is_alive():
            return self
        if self.spool_dir.exists() and (
            self.spool_dir.is_symlink() or not self.spool_dir.is_dir()
        ):
            raise RuntimeError("benchmark Agent spool root must be a real directory")
        self.spool_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.spool_dir.chmod(0o700)
        if any(self.spool_dir.iterdir()):
            raise RuntimeError("benchmark Agent spool root must start empty")
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._serve_forever,
            name="rag-benchmark-agent-spool-gateway",
            daemon=True,
        )
        self._thread.start()
        return self

    def close(self) -> None:
        thread = self._thread
        self._thread = None
        self._stop.set()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=5)

    def __enter__(self) -> "RagBenchmarkAgentSpoolGateway":
        return self.start()

    def __exit__(self, *_args: object) -> None:
        self.close()

    def _serve_forever(self) -> None:
        while not self._stop.is_set():
            processed = False
            for request_path in sorted(self.spool_dir.glob("*.request.json")):
                processed = True
                self._serve_request(request_path)
            self._stop.wait(0.0 if processed else 0.01)

    def _serve_request(self, request_path: Path) -> None:
        match = _SPOOL_REQUEST_NAME.fullmatch(request_path.name)
        if match is None or request_path.is_symlink() or not request_path.is_file():
            return
        request_id = match.group("request_id")
        response_path = self.spool_dir / f"{request_id}.response.json"
        status = HTTPStatus.INTERNAL_SERVER_ERROR
        response_payload: Mapping[str, object] = {
            "ok": False,
            "error": "benchmark Tool spool gateway failed",
        }
        try:
            if request_path.stat().st_size > self.max_request_bytes + 64 * 1024:
                status = HTTPStatus.REQUEST_ENTITY_TOO_LARGE
                response_payload = {
                    "ok": False,
                    "error": "invalid benchmark Tool request size",
                }
            else:
                envelope = json.loads(request_path.read_text(encoding="utf-8"))
                status, response_payload = self._execute_envelope(
                    envelope,
                    request_id=request_id,
                )
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            status = HTTPStatus.BAD_REQUEST
            response_payload = {
                "ok": False,
                "error": "invalid benchmark Tool spool envelope",
            }
        except Exception as exc:  # pragma: no cover - fail-closed worker guard
            status = HTTPStatus.INTERNAL_SERVER_ERROR
            response_payload = {
                "ok": False,
                "error": f"benchmark Tool gateway internal error: {type(exc).__name__}",
            }
        response = {
            "schemaVersion": _SPOOL_RESPONSE_SCHEMA_VERSION,
            "requestId": request_id,
            "status": int(status),
            "headers": {"content-type": "application/json; charset=utf-8"},
            "body": json.dumps(response_payload, ensure_ascii=False),
        }
        temporary = self.spool_dir / (
            f".{request_id}.{secrets.token_hex(8)}.response.tmp"
        )
        try:
            with temporary.open("x", encoding="utf-8") as stream:
                json.dump(response, stream, ensure_ascii=False, separators=(",", ":"))
                stream.write("\n")
            temporary.chmod(0o600)
            os.replace(temporary, response_path)
        finally:
            temporary.unlink(missing_ok=True)
            request_path.unlink(missing_ok=True)

    def _execute_envelope(
        self,
        value: object,
        *,
        request_id: str,
    ) -> tuple[HTTPStatus, Mapping[str, object]]:
        if not isinstance(value, Mapping):
            raise ValueError("benchmark Tool spool envelope must be an object")
        if value.get("schemaVersion") != _SPOOL_REQUEST_SCHEMA_VERSION:
            raise ValueError("benchmark Tool spool schema is unsupported")
        if str(value.get("requestId") or "") != request_id:
            raise ValueError("benchmark Tool spool request identity does not match")
        if str(value.get("method") or "").upper() != "POST":
            return HTTPStatus.METHOD_NOT_ALLOWED, {"ok": False, "error": "method not allowed"}
        target = urlsplit(str(value.get("url") or ""))
        if (
            target.scheme != "rag-ime-spool"
            or target.netloc != "gateway"
            or target.path != "/api/agent/tool/execute"
            or target.query
            or target.fragment
        ):
            return HTTPStatus.NOT_FOUND, {"ok": False, "error": "not found"}
        headers = value.get("headers")
        if not isinstance(headers, Mapping):
            raise ValueError("benchmark Tool spool headers must be an object")
        normalized_headers = {
            str(name).lower(): str(header_value)
            for name, header_value in headers.items()
        }
        provided = normalized_headers.get("x-rag-ime-agent-token", "")
        if not provided or not hmac.compare_digest(provided, self.token):
            return HTTPStatus.FORBIDDEN, {
                "ok": False,
                "error": "agent capability token required",
            }
        body = value.get("body")
        if not isinstance(body, str):
            raise ValueError("benchmark Tool spool body must be text")
        if not body or len(body.encode("utf-8")) > self.max_request_bytes:
            return HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {
                "ok": False,
                "error": "invalid benchmark Tool request size",
            }
        try:
            payload = json.loads(body)
            if not isinstance(payload, Mapping):
                raise ValueError("benchmark Tool request must be an object")
            response = self.gateway.execute(payload)
        except (RagBenchmarkSandboxError, TypeError, ValueError, json.JSONDecodeError) as exc:
            return HTTPStatus.BAD_REQUEST, {
                "ok": False,
                "error": str(exc),
                "errorCode": str(getattr(exc, "code", "invalid_request")),
            }
        return HTTPStatus.OK, response


def _benchmark_tool_call(payload: Mapping[str, object]) -> dict[str, object]:
    unexpected = sorted(set(payload) - _TOOL_CALL_FIELDS)
    if unexpected:
        raise ValueError(
            "unsupported benchmark Tool envelope fields: " + ", ".join(unexpected)
        )
    if payload.get("schemaVersion") != _TOOL_CALL_SCHEMA_VERSION:
        raise ValueError(f"schemaVersion must be {_TOOL_CALL_SCHEMA_VERSION}")
    session_id = _text(payload.get("sessionId"), "sessionId", maximum=256)
    tool_call_id = _text(payload.get("toolCallId"), "toolCallId", maximum=256)
    if str(payload.get("tool") or "") != "rag_benchmark":
        raise ValueError("benchmark Tool envelope has the wrong tool")
    args = payload.get("args")
    if not isinstance(args, Mapping):
        raise ValueError("benchmark Tool args must be an object")
    raw_load_receipt_id = payload.get("loadReceiptId")
    load_receipt_id = (
        _text(raw_load_receipt_id, "loadReceiptId", maximum=512)
        if raw_load_receipt_id is not None
        else ""
    )
    return {
        "schemaVersion": _TOOL_CALL_SCHEMA_VERSION,
        "sessionId": session_id,
        "tool": "rag_benchmark",
        "toolCallId": tool_call_id,
        "args": dict(args),
        "loadReceiptId": load_receipt_id,
    }


def _operation_parameter_subset(
    value: object,
    operations: frozenset[str],
    *,
    bound_run_id: str = "",
) -> dict[str, object]:
    if not isinstance(value, Mapping) or not isinstance(value.get("oneOf"), list):
        raise ValueError("rag_benchmark parameters must contain oneOf")
    selected = []
    for raw_schema in value["oneOf"]:
        if not isinstance(raw_schema, Mapping):
            continue
        properties = raw_schema.get("properties")
        operation = (
            properties.get("op")
            if isinstance(properties, Mapping)
            else None
        )
        operation_name = (
            str(operation.get("const") or "")
            if isinstance(operation, Mapping)
            else ""
        )
        if operation_name in operations:
            schema = deepcopy(dict(raw_schema))
            if bound_run_id and operation_name != "create_run":
                required = schema.get("required")
                if isinstance(required, list):
                    schema["required"] = [item for item in required if item != "runId"]
                copied_properties = schema.get("properties")
                if isinstance(copied_properties, dict):
                    copied_properties.pop("runId", None)
            selected.append(schema)
    if len(selected) != len(operations):
        raise ValueError("rag_benchmark parameter schema does not cover the binding")
    return {"type": "object", "oneOf": selected}


def _safe_args_summary(
    operation: str,
    args: Mapping[str, object],
) -> dict[str, object]:
    if operation == "import_documents":
        documents = args.get("documents")
        summaries = []
        if isinstance(documents, list):
            for value in documents:
                if not isinstance(value, Mapping):
                    continue
                text = str(value.get("text") or "")
                summaries.append(
                    {
                        "externalId": str(value.get("externalId") or ""),
                        "name": str(value.get("name") or ""),
                        "mimeType": str(value.get("mimeType") or ""),
                        "byteSize": len(text.encode("utf-8")),
                        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    }
                )
        return {
            "op": operation,
            "runId": str(args.get("runId") or ""),
            "baseAlias": str(args.get("baseAlias") or ""),
            "documents": summaries,
        }
    if operation == "search":
        query = str(args.get("query") or "")
        return {
            key: deepcopy(value)
            for key, value in args.items()
            if key != "query"
        } | {
            "querySha256": hashlib.sha256(query.encode("utf-8")).hexdigest(),
            "queryChars": len(query),
        }
    return deepcopy(dict(args))


def _safe_result_summary(
    operation: str,
    result: Mapping[str, object],
) -> dict[str, object]:
    summary = {
        key: deepcopy(result[key])
        for key in (
            "schemaVersion",
            "runId",
            "baseAlias",
            "configRevision",
            "documentCount",
            "importedCount",
            "requested",
            "ready",
            "failed",
            "queued",
            "total",
            "deleted",
            "localOnly",
            "networkUploadAllowed",
            "state",
            "baseCount",
            "usage",
            "limits",
            "retrieval",
            "dense",
            "reranker",
            "jobId",
            "status",
            "revision",
            "sourceRevision",
            "stats",
            "extractor",
            "requestedExtractor",
            "knowledgeOnly",
            "memoryMutationPerformed",
            "lunaReceipts",
            "lunaExtractionPassed",
            "evaluationSuiteId",
            "evaluationSuiteSha256",
            "caseIdsSha256",
            "split",
            "caseCount",
            "kValues",
            "metrics",
            "qrelsVisibleToAgent",
            "perCaseResultsVisible",
            "heldOutLabelsObserved",
            "uploaded",
            "elapsedMs",
            "evaluationReceiptSha256",
        )
        if key in result
    }
    if operation == "search" and isinstance(result.get("hits"), list):
        summary["hits"] = [
            {
                key: deepcopy(hit[key])
                for key in (
                    "externalDocumentId",
                    "citationRef",
                    "chunkId",
                    "documentName",
                    "ordinal",
                    "score",
                    "citation",
                )
                if key in hit
            }
            for hit in result["hits"]
            if isinstance(hit, Mapping)
        ]
    if operation == "import_documents" and isinstance(result.get("documents"), list):
        summary["documents"] = [
            {
                key: deepcopy(document[key])
                for key in (
                    "externalDocumentId",
                    "name",
                    "mimeType",
                    "byteSize",
                    "sha256",
                    "status",
                    "chunkCount",
                )
                if key in document
            }
            for document in result["documents"]
            if isinstance(document, Mapping)
        ]
    return summary


def _text(value: object, field: str, *, maximum: int) -> str:
    normalized = str(value or "").strip()
    if not normalized or len(normalized) > maximum or "\x00" in normalized:
        raise ValueError(f"{field} must be non-empty and at most {maximum} characters")
    return normalized


def _sha256_json(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
