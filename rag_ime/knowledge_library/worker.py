from __future__ import annotations

import argparse
import json
import tempfile
import time
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .client import LocalKnowledgeClient
from .models import AssetBlob, KNOWLEDGE_SCHEMA_VERSION, KnowledgeConflictError, KnowledgeLibraryConfig, KnowledgeLibraryError, KnowledgeNotFoundError
from .service import KnowledgeLibraryService


IMPORT_SCHEMA_VERSION = "rag-ime.knowledge-document-import.v1"
MAX_JSON_BYTES = 2 * 1024 * 1024


class KnowledgeWorkerServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], service: KnowledgeLibraryService):
        super().__init__(address, KnowledgeWorkerHandler)
        self.service = service
        self.agent_client = LocalKnowledgeClient(service)
        self.last_activity = time.monotonic()


class KnowledgeWorkerHandler(BaseHTTPRequestHandler):
    server: KnowledgeWorkerServer
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802
        self._dispatch("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._dispatch("POST")

    def do_PATCH(self) -> None:  # noqa: N802
        self._dispatch("PATCH")

    def do_DELETE(self) -> None:  # noqa: N802
        self._dispatch("DELETE")

    def log_message(self, format: str, *args: object) -> None:
        return None

    def _dispatch(self, method: str) -> None:
        self.server.last_activity = time.monotonic()
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = urllib.parse.parse_qs(parsed.query)
        try:
            result, status = self._route(method, path, query)
        except KnowledgeNotFoundError as exc:
            self._error(HTTPStatus.NOT_FOUND, exc)
            return
        except KnowledgeConflictError as exc:
            self._error(HTTPStatus.CONFLICT, exc)
            return
        except KnowledgeLibraryError as exc:
            status = HTTPStatus.REQUEST_ENTITY_TOO_LARGE if exc.code in {"asset_too_large", "source_too_large", "request_too_large"} else HTTPStatus.BAD_REQUEST
            self._error(status, exc)
            return
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self._error(
                HTTPStatus.BAD_REQUEST,
                KnowledgeLibraryError(str(exc) or "invalid request", code="invalid_request"),
            )
            return
        except Exception as exc:
            self._error(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                KnowledgeLibraryError(str(exc) or "knowledge worker failed", code="internal_error"),
            )
            return
        if isinstance(result, AssetBlob):
            self._asset(status, result)
        else:
            self._json(status, result)

    def _route(
        self,
        method: str,
        path: str,
        query: dict[str, list[str]],
    ) -> tuple[dict[str, Any] | AssetBlob, HTTPStatus]:
        service = self.server.service
        agent = self.server.agent_client
        if method == "GET" and path == "/v1/health":
            return {"status": "ok", "schemaVersion": KNOWLEDGE_SCHEMA_VERSION}, HTTPStatus.OK
        if method == "GET" and path == "/v1/agent/knowledge/bases":
            return agent.list_bases({}), HTTPStatus.OK
        if method == "GET" and path == "/v1/agent/knowledge/status":
            return agent.status({}), HTTPStatus.OK
        if method == "POST" and path == "/v1/agent/knowledge/search":
            body = self._json_body()
            return agent.search(body), HTTPStatus.OK
        if method == "POST" and path == "/v1/agent/knowledge/find":
            body = self._json_body()
            return agent.find(body), HTTPStatus.OK
        if method == "POST" and path == "/v1/agent/knowledge/open":
            body = self._json_body()
            return agent.open(body), HTTPStatus.OK
        if method == "GET" and path == "/v1/knowledge/status":
            return service.status(), HTTPStatus.OK
        if method == "GET" and path == "/v1/knowledge/mineru/health":
            return service.mineru_health(), HTTPStatus.OK
        if method == "GET" and path == "/v1/knowledge/bases":
            return service.list_bases(), HTTPStatus.OK
        if method == "POST" and path == "/v1/knowledge/bases":
            body = self._json_body()
            return service.create_base(
                str(body.get("name") or ""),
                description=str(body.get("description") or ""),
                parser_mode=str(body.get("parserMode") or body.get("parserProvider") or "auto"),
                agent_enabled=bool(body.get("agentEnabled", False)),
                chunking_config=body.get("chunkingConfig"),
                retrieval_config=body.get("retrievalConfig"),
            ), HTTPStatus.CREATED
        if path.startswith("/v1/knowledge/bases/"):
            tail = path.removeprefix("/v1/knowledge/bases/")
            parts = tail.split("/")
            kb_id = urllib.parse.unquote(parts[0])
            if len(parts) == 2 and parts[1] == "reindex-preview" and method == "GET":
                return service.reindex_preview(kb_id), HTTPStatus.OK
            if len(parts) == 2 and parts[1] == "rebuild" and method == "POST":
                body = self._json_body()
                return service.rebuild_base(
                    kb_id,
                    preview_token=str(body.get("previewToken") or ""),
                    expected_revision=int(body.get("expectedRevision") or 0),
                    confirm_text=str(body.get("confirmText") or ""),
                ), HTTPStatus.OK
            if len(parts) == 4 and parts[1] == "documents" and parts[3] == "detail" and method == "GET":
                return service.document_detail(
                    kb_id,
                    urllib.parse.unquote(parts[2]),
                    offset=int(_first(query, "offset", default="0")),
                    limit=int(_first(query, "limit", default="100")),
                    line_offset=int(_first(query, "lineOffset", default="0")),
                    line_limit=int(_first(query, "lineLimit", default="200")),
                ), HTTPStatus.OK
            if len(parts) == 4 and parts[1] == "documents" and parts[3] == "source" and method == "GET":
                return service.read_document_source(kb_id, urllib.parse.unquote(parts[2])), HTTPStatus.OK
            if len(parts) == 5 and parts[1] == "documents" and parts[3] == "assets" and method == "GET":
                return service.read_document_asset(
                    kb_id,
                    urllib.parse.unquote(parts[2]),
                    urllib.parse.unquote(parts[4]),
                ), HTTPStatus.OK
            if len(parts) != 1:
                raise KnowledgeNotFoundError(f"worker route not found: {method} {path}")
            if method == "GET":
                return service.get_base(kb_id), HTTPStatus.OK
            if method == "PATCH":
                body = self._json_body()
                return service.update_base(
                    kb_id,
                    name=body.get("name") if "name" in body else None,
                    description=body.get("description") if "description" in body else None,
                    parser_mode=(body.get("parserMode") if "parserMode" in body else body.get("parserProvider")),
                    agent_enabled=body.get("agentEnabled") if "agentEnabled" in body else None,
                    chunking_config=body.get("chunkingConfig") if "chunkingConfig" in body else None,
                    retrieval_config=body.get("retrievalConfig") if "retrievalConfig" in body else None,
                    expected_revision=int(body["expectedRevision"]) if body.get("expectedRevision") is not None else None,
                ), HTTPStatus.OK
            if method == "DELETE":
                return service.delete_base(kb_id), HTTPStatus.OK
        if method == "GET" and path == "/v1/knowledge/documents":
            return service.list_documents(_first(query, "kbId")), HTTPStatus.OK
        if method == "GET" and path == "/v1/knowledge/jobs":
            return service.list_jobs(
                base_id=str((query.get("kbId") or [""])[0]),
                limit=int(_first(query, "limit", default="100")),
            ), HTTPStatus.OK
        if method == "POST" and path == "/v1/knowledge/documents/import":
            return self._import_document(query), HTTPStatus.CREATED
        if path.startswith("/v1/knowledge/documents/"):
            tail = path.removeprefix("/v1/knowledge/documents/")
            if tail.endswith("/retry") and method == "POST":
                file_id = urllib.parse.unquote(tail.removesuffix("/retry"))
                body = self._json_body()
                return service.retry_document(file_id, parser_mode=body.get("parserMode")), HTTPStatus.OK
            file_id = urllib.parse.unquote(tail)
            if method == "GET":
                return service.get_document(file_id), HTTPStatus.OK
            if method == "DELETE":
                return service.delete_document(file_id), HTTPStatus.OK
        if method == "POST" and path == "/v1/knowledge/search":
            body = self._json_body()
            return service.search(
                str(body.get("query") or ""),
                base_ids=_string_list(body.get("kbIds") or body.get("kbId")),
                limit=int(body["limit"]) if body.get("limit") is not None else None,
                mode=str(body["mode"]) if body.get("mode") is not None else None,
                threshold=float(body["threshold"]) if body.get("threshold") is not None else None,
            ), HTTPStatus.OK
        if method == "POST" and path == "/v1/knowledge/find":
            body = self._json_body()
            requested_query = _query_from_body(body)
            if body.get("fileId"):
                return service.find_in_document(
                    str(body["fileId"]),
                    _patterns_from_body(body),
                    use_regex=body.get("useRegex") is True or body.get("regex") is True,
                    case_sensitive=body.get("caseSensitive") is True,
                    max_windows=int(body.get("maxWindows") or body.get("limit") or 8),
                    window_size=int(body.get("windowSize") or body.get("lineWindow") or 24),
                ), HTTPStatus.OK
            find_result = service.find(
                requested_query,
                base_ids=_string_list(body.get("kbIds") or body.get("kbId")),
                limit=int(body.get("limit") or body.get("topK") or 20),
            )
            search_result = service.search(
                requested_query,
                base_ids=_string_list(body.get("kbIds") or body.get("kbId")),
                limit=int(body.get("limit") or body.get("topK") or 20),
            )
            return {**find_result, "contentHits": search_result["hits"]}, HTTPStatus.OK
        if method == "POST" and path == "/v1/knowledge/open":
            body = self._json_body()
            if body.get("chunkId"):
                return service.open(
                    str(body["chunkId"]),
                    before=int(body.get("before") or 1),
                    after=int(body.get("after") or 1),
                ), HTTPStatus.OK
            return service.open_document(
                str(body.get("fileId") or ""),
                offset=int(body.get("offset") or 0),
                limit=int(body.get("limit") or body.get("topK") or 5),
            ), HTTPStatus.OK
        raise KnowledgeNotFoundError(f"worker route not found: {method} {path}")

    def _import_document(self, query: dict[str, list[str]]) -> dict[str, Any]:
        content_length = _content_length(self.headers.get("Content-Length"))
        if content_length > self.server.service.config.max_source_bytes:
            raise KnowledgeLibraryError("source file exceeds the configured size limit", code="source_too_large")
        kb_id = self.headers.get("X-Knowledge-Base-Id") or _first(query, "kbId")
        encoded_name = self.headers.get("X-Knowledge-File-Name") or _first(query, "fileName", default="document.bin")
        file_name = Path(urllib.parse.unquote(encoded_name)).name
        if not file_name or file_name in {".", ".."}:
            raise KnowledgeLibraryError("file name is required", code="invalid_argument")
        incoming = self.server.service.config.root_dir / "incoming"
        incoming.mkdir(parents=True, exist_ok=True)
        suffix = Path(file_name).suffix[:20]
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(dir=incoming, suffix=suffix, delete=False) as target:
                temporary_path = Path(target.name)
                remaining = content_length
                while remaining:
                    block = self.rfile.read(min(1024 * 1024, remaining))
                    if not block:
                        raise KnowledgeLibraryError("request body ended before Content-Length", code="invalid_request")
                    target.write(block)
                    remaining -= len(block)
            document = self.server.service.import_document(
                kb_id,
                temporary_path,
                display_name=file_name,
                mime_type=str(self.headers.get("Content-Type") or "application/octet-stream").split(";", 1)[0],
                parser_mode=(str(query["parserMode"][0]) if query.get("parserMode") else None),
            )
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
        receipt = {
            "kbId": document["kbId"],
            "documentId": document["documentId"],
            "fileName": document["fileName"],
            "mimeType": document["mimeType"],
            "byteSize": document["byteSize"],
            "sha256": document["sha256"],
            "status": document["status"],
        }
        return {"schemaVersion": IMPORT_SCHEMA_VERSION, "ok": True, "receipt": receipt}

    def _json_body(self) -> dict[str, Any]:
        content_length = _content_length(self.headers.get("Content-Length"))
        if content_length > MAX_JSON_BYTES:
            raise KnowledgeLibraryError("JSON body is too large", code="request_too_large")
        if content_length == 0:
            return {}
        raw = self.rfile.read(content_length)
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise KnowledgeLibraryError("JSON request body must be an object", code="invalid_request")
        return payload

    def _json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(int(status))
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def _asset(self, status: HTTPStatus, asset: AssetBlob) -> None:
        encoded_name = urllib.parse.quote(asset.file_name, safe="")
        self.send_response(int(status))
        self.send_header("Content-Type", asset.media_type)
        self.send_header("Content-Length", str(asset.byte_size))
        self.send_header("ETag", f'"{asset.asset_id}"')
        self.send_header("Cache-Control", "private, max-age=31536000, immutable")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Disposition", f"inline; filename*=UTF-8''{encoded_name}")
        self.end_headers()
        self.wfile.write(asset.data)

    def _error(self, status: HTTPStatus, error: KnowledgeLibraryError) -> None:
        self._json(
            status,
            {
                "schemaVersion": KNOWLEDGE_SCHEMA_VERSION,
                "ok": False,
                "error": {"code": error.code, "message": str(error)},
            },
        )


def default_knowledge_root() -> Path:
    return Path.home() / "Library" / "Application Support" / "RagIme" / "Knowledge"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="RAG-IME isolated document knowledge worker")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8_769)
    parser.add_argument("--root", type=Path, default=default_knowledge_root())
    parser.add_argument("--mineru-enabled", action="store_true")
    parser.add_argument("--mineru-port", type=int, default=30_001)
    parser.add_argument("--idle-seconds", type=float, default=900.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.host not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit("knowledge worker host must be loopback")
    if not 1_024 <= args.port <= 65_535:
        raise SystemExit("knowledge worker port must be between 1024 and 65535")
    config = KnowledgeLibraryConfig(
        root_dir=args.root,
        mineru_enabled=bool(args.mineru_enabled),
        mineru_port=int(args.mineru_port),
    )
    service = KnowledgeLibraryService(config, background_jobs=True)
    server = KnowledgeWorkerServer((args.host, args.port), service)
    server.timeout = 0.5
    try:
        while True:
            server.handle_request()
            if args.idle_seconds > 0 and time.monotonic() - server.last_activity >= args.idle_seconds:
                break
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        service.close(wait=True)
    return 0


def _content_length(value: str | None) -> int:
    if value is None:
        raise KnowledgeLibraryError("Content-Length is required", code="length_required")
    try:
        length = int(value)
    except ValueError as exc:
        raise KnowledgeLibraryError("invalid Content-Length", code="invalid_request") from exc
    if length < 0:
        raise KnowledgeLibraryError("invalid Content-Length", code="invalid_request")
    return length


def _first(query: dict[str, list[str]], key: str, *, default: str = "") -> str:
    values = query.get(key) or []
    value = str(values[0]) if values else default
    if not value and not default:
        raise KnowledgeLibraryError(f"{key} is required", code="invalid_argument")
    return value


def _string_list(value: Any) -> tuple[str, ...]:
    if value is None or value == "":
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list):
        return tuple(str(item) for item in value if str(item).strip())
    raise KnowledgeLibraryError("kbIds must be a string or string array", code="invalid_argument")


def _query_from_body(body: dict[str, Any]) -> str:
    query = str(body.get("query") or "").strip()
    if query:
        return query
    patterns = body.get("patterns")
    if isinstance(patterns, str):
        return patterns
    if isinstance(patterns, list):
        return " ".join(str(item).strip() for item in patterns if str(item).strip())
    return ""


def _patterns_from_body(body: dict[str, Any]) -> tuple[str, ...]:
    patterns = body.get("patterns")
    if isinstance(patterns, str):
        result = (patterns.strip(),)
    elif isinstance(patterns, list):
        result = tuple(str(item).strip() for item in patterns if str(item).strip())
    else:
        query = str(body.get("query") or "").strip()
        result = (query,) if query else ()
    if not result:
        raise KnowledgeLibraryError("find requires query or patterns", code="invalid_argument")
    return result[:10]


if __name__ == "__main__":
    raise SystemExit(main())
