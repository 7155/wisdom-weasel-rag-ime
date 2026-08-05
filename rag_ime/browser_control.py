from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import signal
import sqlite3
import subprocess
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


SCHEMA_VERSION = "rag-ime.browser-control.v1"
ALLOWED_MODES = frozenset({"observe", "codrive", "managed"})
READ_ACTIONS = frozenset({"tabs", "snapshot", "read_page", "screenshot"})
WRITE_ACTIONS = frozenset({"navigate", "click", "type", "scroll", "wait"})
ALLOWED_ACTIONS = READ_ACTIONS | WRITE_ACTIONS
MAX_SNAPSHOT_MARKDOWN = 160_000
MAX_SCREENSHOT_BYTES = 8 * 1024 * 1024
MAX_RESULT_JSON = 256_000
DEFAULT_COMMAND_TIMEOUT_SECONDS = 15.0


class BrowserControlError(ValueError):
    pass


class BrowserControlService:
    """Durable localhost bridge shared by the Sidecar and Agent Gateway.

    The extension continuously records compact page snapshots. Agent calls only
    read those snapshots on demand or enqueue an explicit command. SQLite is
    used deliberately because the 8766 and 8768 processes must observe the same
    queue without introducing a third resident daemon.
    """

    def __init__(
        self,
        db_path: str | Path,
        *,
        extension_root: str | Path | None = None,
        app_support_root: str | Path | None = None,
        command_runner: Any | None = None,
    ) -> None:
        self.db_path = Path(db_path).expanduser().resolve(strict=False)
        self.app_support_root = Path(
            app_support_root
            or os.environ.get("RAG_IME_APP_SUPPORT_DIR")
            or Path.home() / "Library" / "Application Support" / "RagIme"
        ).expanduser()
        self.extension_root = self._resolve_extension_root(extension_root)
        self.command_runner = command_runner or subprocess.Popen
        self.initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.db_path), timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS browser_control_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at_ms INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS browser_control_clients (
                    device_id TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL,
                    client_kind TEXT NOT NULL,
                    extension_version TEXT NOT NULL,
                    browser_name TEXT NOT NULL,
                    active_tab_id INTEGER,
                    last_seen_ms INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS browser_control_snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    device_id TEXT NOT NULL,
                    tab_id INTEGER NOT NULL,
                    frame_id INTEGER NOT NULL DEFAULT 0,
                    url TEXT NOT NULL,
                    title TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    markdown TEXT NOT NULL,
                    interactive_count INTEGER NOT NULL DEFAULT 0,
                    viewport_json TEXT NOT NULL DEFAULT '{}',
                    screenshot_mime TEXT,
                    screenshot_bytes BLOB,
                    created_at_ms INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_browser_snapshots_device_tab
                    ON browser_control_snapshots(device_id, tab_id, created_at_ms DESC);
                CREATE TABLE IF NOT EXISTS browser_control_commands (
                    command_id TEXT PRIMARY KEY,
                    device_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    result_json TEXT,
                    failure_reason TEXT,
                    created_at_ms INTEGER NOT NULL,
                    claimed_at_ms INTEGER,
                    completed_at_ms INTEGER,
                    claimed_by TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_browser_commands_queue
                    ON browser_control_commands(device_id, status, created_at_ms);
                CREATE TABLE IF NOT EXISTS browser_control_permissions (
                    prompt_id TEXT PRIMARY KEY,
                    device_id TEXT NOT NULL,
                    origin TEXT NOT NULL,
                    action TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    status TEXT NOT NULL,
                    decision TEXT,
                    created_at_ms INTEGER NOT NULL,
                    resolved_at_ms INTEGER
                );
                CREATE TABLE IF NOT EXISTS browser_control_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind TEXT NOT NULL,
                    device_id TEXT NOT NULL,
                    command_id TEXT,
                    detail_json TEXT NOT NULL,
                    created_at_ms INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_browser_events_created
                    ON browser_control_events(created_at_ms DESC);
                """
            )
            if self._setting(connection, "pairing_token") is None:
                self._set_setting(connection, "pairing_token", secrets.token_urlsafe(32))
            if self._setting(connection, "mode") not in ALLOWED_MODES:
                self._set_setting(connection, "mode", "observe")
            connection.commit()

    def authenticate(self, token: str) -> bool:
        candidate = str(token or "").strip()
        if not candidate:
            return False
        with self._connection() as connection:
            expected = self._setting(connection, "pairing_token") or ""
        return secrets.compare_digest(candidate, expected)

    def pairing(self) -> dict[str, object]:
        with self._connection() as connection:
            token = self._setting(connection, "pairing_token") or ""
        return {
            "schemaVersion": SCHEMA_VERSION,
            "ok": True,
            "bridgeUrl": os.environ.get("RAG_IME_BROWSER_BRIDGE_URL", "http://127.0.0.1:8766"),
            "pairingToken": token,
            "tokenFingerprint": self._fingerprint(token),
            "extensionPath": str(self.extension_root),
        }

    def rotate_pairing(self) -> dict[str, object]:
        token = secrets.token_urlsafe(32)
        with self._connection() as connection:
            self._set_setting(connection, "pairing_token", token)
            connection.execute("DELETE FROM browser_control_clients")
            connection.commit()
        response = self.pairing()
        response["summary"] = "配对凭据已轮换，现有浏览器需要重新连接"
        return response

    def hello(self, payload: Mapping[str, object]) -> dict[str, object]:
        device_id = self._identifier(payload.get("deviceId"), field="deviceId")
        display_name = self._text(payload.get("displayName"), maximum=80) or "Chrome"
        client_kind = self._text(payload.get("clientKind"), maximum=24) or "user"
        if client_kind not in {"user", "managed"}:
            raise BrowserControlError("clientKind must be user or managed")
        now = self._now_ms()
        with self._connection() as connection:
            existing = connection.execute(
                "SELECT client_kind FROM browser_control_clients WHERE device_id=?",
                (device_id,),
            ).fetchone()
            if client_kind == "managed" and (
                existing is None or existing["client_kind"] != "managed"
            ):
                expected = self._setting(connection, "managed_bootstrap_token") or ""
                provided = self._text(
                    payload.get("managedBootstrapToken"),
                    maximum=240,
                )
                if not expected or not secrets.compare_digest(provided, expected):
                    raise BrowserControlError("managed browser bootstrap token is invalid")
            connection.execute(
                """
                INSERT INTO browser_control_clients(
                    device_id, display_name, client_kind, extension_version,
                    browser_name, active_tab_id, last_seen_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(device_id) DO UPDATE SET
                    display_name=excluded.display_name,
                    client_kind=excluded.client_kind,
                    extension_version=excluded.extension_version,
                    browser_name=excluded.browser_name,
                    active_tab_id=COALESCE(excluded.active_tab_id, browser_control_clients.active_tab_id),
                    last_seen_ms=excluded.last_seen_ms
                """,
                (
                    device_id,
                    display_name,
                    client_kind,
                    self._text(payload.get("extensionVersion"), maximum=40),
                    self._text(payload.get("browserName"), maximum=80) or "Chrome",
                    self._positive_int(payload.get("activeTabId"), allow_none=True),
                    now,
                ),
            )
            self._event(connection, "connected", device_id, {"clientKind": client_kind})
            connection.commit()
        return {
            "schemaVersion": SCHEMA_VERSION,
            "ok": True,
            "deviceId": device_id,
            "mode": self.mode(),
            "pollAfterMs": 450,
        }

    def push_snapshot(self, payload: Mapping[str, object]) -> dict[str, object]:
        device_id = self._identifier(payload.get("deviceId"), field="deviceId")
        tab_id = self._positive_int(payload.get("tabId"))
        snapshot_id = self._identifier(
            payload.get("snapshotId") or f"snap_{uuid.uuid4().hex}",
            field="snapshotId",
        )
        raw_url = str(payload.get("url") or "").strip()
        page_url = self._page_url(raw_url, allow_blank=True)
        markdown = str(payload.get("markdown") or "")[:MAX_SNAPSHOT_MARKDOWN]
        if raw_url and raw_url != page_url:
            markdown = markdown.replace(raw_url, page_url)
        screenshot_mime, screenshot_bytes = self._decode_screenshot(payload.get("screenshotDataUrl"))
        now = self._now_ms()
        with self._connection() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO browser_control_snapshots(
                    snapshot_id, device_id, tab_id, frame_id, url, title, summary,
                    markdown, interactive_count, viewport_json, screenshot_mime,
                    screenshot_bytes, created_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    device_id,
                    tab_id,
                    self._positive_int(payload.get("frameId"), allow_zero=True, allow_none=True) or 0,
                    page_url,
                    self._text(payload.get("title"), maximum=500),
                    self._text(payload.get("summary"), maximum=1_200),
                    markdown,
                    self._positive_int(payload.get("interactiveCount"), allow_zero=True, allow_none=True) or 0,
                    json.dumps(payload.get("viewport") if isinstance(payload.get("viewport"), Mapping) else {}),
                    screenshot_mime,
                    screenshot_bytes,
                    now,
                ),
            )
            connection.execute(
                """
                UPDATE browser_control_clients
                SET active_tab_id=?, last_seen_ms=?
                WHERE device_id=?
                """,
                (tab_id, now, device_id),
            )
            self._event(
                connection,
                "snapshot",
                device_id,
                {
                    "snapshotId": snapshot_id,
                    "tabId": tab_id,
                    "title": self._text(payload.get("title"), maximum=180),
                    "url": page_url,
                    "interactiveCount": self._positive_int(
                        payload.get("interactiveCount"),
                        allow_zero=True,
                        allow_none=True,
                    )
                    or 0,
                },
            )
            connection.commit()
        return {"schemaVersion": SCHEMA_VERSION, "ok": True, "snapshotId": snapshot_id}

    def status(self, *, agent_safe: bool = False) -> dict[str, object]:
        now = self._now_ms()
        with self._connection() as connection:
            clients = [
                self._public_client(row, now=now)
                for row in connection.execute(
                    "SELECT * FROM browser_control_clients ORDER BY last_seen_ms DESC"
                ).fetchall()
            ]
            counts = {
                str(row["status"]): int(row["count"])
                for row in connection.execute(
                    "SELECT status, COUNT(*) AS count FROM browser_control_commands GROUP BY status"
                ).fetchall()
            }
            permission_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM browser_control_permissions WHERE status='pending'"
                ).fetchone()[0]
            )
            snapshot = self._latest_snapshot_row(connection)
        response: dict[str, object] = {
            "schemaVersion": SCHEMA_VERSION,
            "ok": True,
            "mode": self.mode(),
            "connected": any(client["connected"] for client in clients),
            "clients": clients,
            "commandCounts": counts,
            "pendingPermissions": permission_count,
            "managedBrowser": self.managed_status(),
            "latestSnapshot": self._public_snapshot(snapshot, include_markdown=False) if snapshot else None,
            "summary": (
                f"{sum(1 for item in clients if item['connected'])} 个浏览器已连接"
                if clients
                else "尚未连接浏览器插件"
            ),
        }
        if not agent_safe:
            response["extensionPath"] = str(self.extension_root)
        return response

    def mode(self) -> str:
        with self._connection() as connection:
            return self._setting(connection, "mode") or "observe"

    def set_mode(self, value: object) -> dict[str, object]:
        mode = str(value or "").strip()
        if mode not in ALLOWED_MODES:
            raise BrowserControlError("mode must be observe, codrive, or managed")
        with self._connection() as connection:
            self._set_setting(connection, "mode", mode)
            self._event(connection, "mode_changed", "", {"mode": mode})
            connection.commit()
        return {"schemaVersion": SCHEMA_VERSION, "ok": True, "mode": mode}

    def tabs(self) -> dict[str, object]:
        now = self._now_ms()
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT snapshots.*
                FROM browser_control_snapshots snapshots
                INNER JOIN (
                    SELECT device_id, tab_id, MAX(created_at_ms) AS newest
                    FROM browser_control_snapshots
                    GROUP BY device_id, tab_id
                ) latest
                ON latest.device_id=snapshots.device_id
                AND latest.tab_id=snapshots.tab_id
                AND latest.newest=snapshots.created_at_ms
                ORDER BY snapshots.created_at_ms DESC
                LIMIT 100
                """
            ).fetchall()
            client_rows = {
                str(row["device_id"]): row
                for row in connection.execute("SELECT * FROM browser_control_clients").fetchall()
            }
        items = []
        for row in rows:
            client = client_rows.get(str(row["device_id"]))
            item = self._public_snapshot(row, include_markdown=False)
            item.update(
                {
                    "deviceName": str(client["display_name"]) if client else str(row["device_id"]),
                    "clientKind": str(client["client_kind"]) if client else "user",
                    "connected": bool(client and now - int(client["last_seen_ms"]) <= 15_000),
                }
            )
            items.append(item)
        return {
            "schemaVersion": SCHEMA_VERSION,
            "ok": True,
            "items": items,
            "summary": f"已读取 {len(items)} 个浏览器标签页",
        }

    def latest_snapshot(
        self,
        *,
        device_id: str = "",
        tab_id: int | None = None,
        include_markdown: bool = True,
    ) -> dict[str, object]:
        with self._connection() as connection:
            row = self._latest_snapshot_row(connection, device_id=device_id, tab_id=tab_id)
        if row is None:
            raise BrowserControlError("browser snapshot is unavailable")
        return {
            "schemaVersion": SCHEMA_VERSION,
            "ok": True,
            **self._public_snapshot(row, include_markdown=include_markdown),
            "summary": f"已读取《{str(row['title']) or '未命名页面'}》的页面快照",
        }

    def snapshot_image(self, snapshot_id: str) -> tuple[str, bytes]:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT screenshot_mime, screenshot_bytes FROM browser_control_snapshots WHERE snapshot_id=?",
                (snapshot_id,),
            ).fetchone()
        if row is None or not row["screenshot_bytes"]:
            raise BrowserControlError("snapshot image is unavailable")
        return str(row["screenshot_mime"] or "image/png"), bytes(row["screenshot_bytes"])

    def submit_command(
        self,
        action: str,
        payload: Mapping[str, object],
        *,
        session_id: str = "",
        timeout_seconds: float = DEFAULT_COMMAND_TIMEOUT_SECONDS,
    ) -> dict[str, object]:
        normalized_action = str(action or "").strip()
        if normalized_action not in ALLOWED_ACTIONS:
            raise BrowserControlError(f"unsupported browser action: {normalized_action}")
        mode = self.mode()
        if normalized_action in WRITE_ACTIONS and mode == "observe":
            raise BrowserControlError("browser is in observe mode; switch to co-drive or managed mode first")
        device_id = self._select_device(
            requested=str(payload.get("deviceId") or ""),
            prefer_managed=mode == "managed",
        )
        command_id = f"bcmd_{uuid.uuid4().hex}"
        command_payload = self._normalize_command(normalized_action, payload)
        now = self._now_ms()
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO browser_control_commands(
                    command_id, device_id, session_id, action, payload_json,
                    status, created_at_ms
                ) VALUES (?, ?, ?, ?, ?, 'queued', ?)
                """,
                (
                    command_id,
                    device_id,
                    self._text(session_id, maximum=240),
                    normalized_action,
                    json.dumps(command_payload, ensure_ascii=False),
                    now,
                ),
            )
            self._event(
                connection,
                "command_queued",
                device_id,
                {"action": normalized_action},
                command_id=command_id,
            )
            connection.commit()

        deadline = time.monotonic() + min(max(float(timeout_seconds), 1.0), 60.0)
        while time.monotonic() < deadline:
            with self._connection() as connection:
                row = connection.execute(
                    "SELECT * FROM browser_control_commands WHERE command_id=?",
                    (command_id,),
                ).fetchone()
            if row is not None and row["status"] in {"completed", "failed", "cancelled"}:
                result = self._json_object(row["result_json"])
                return {
                    "schemaVersion": SCHEMA_VERSION,
                    "ok": row["status"] == "completed" and result.get("ok", True) is not False,
                    "commandId": command_id,
                    "action": normalized_action,
                    "status": str(row["status"]),
                    "durationMs": max(0, int(row["completed_at_ms"] or self._now_ms()) - int(row["created_at_ms"])),
                    "failureReason": str(row["failure_reason"] or ""),
                    "result": result,
                    "summary": self._command_summary(normalized_action, row["status"], result),
                }
            time.sleep(0.12)
        with self._connection() as connection:
            connection.execute(
                """
                UPDATE browser_control_commands
                SET status='failed', failure_reason='browser_command_timeout', completed_at_ms=?
                WHERE command_id=? AND status IN ('queued', 'claimed')
                """,
                (self._now_ms(), command_id),
            )
            self._event(
                connection,
                "command_timeout",
                device_id,
                {"action": normalized_action},
                command_id=command_id,
            )
            connection.commit()
        return {
            "schemaVersion": SCHEMA_VERSION,
            "ok": False,
            "commandId": command_id,
            "action": normalized_action,
            "status": "failed",
            "failureReason": "browser_command_timeout",
            "summary": "浏览器插件未在时限内返回结果",
        }

    def next_command(
        self,
        *,
        device_id: str,
        client_id: str,
        timeout_seconds: float = 20.0,
    ) -> dict[str, object]:
        normalized_device = self._identifier(device_id, field="deviceId")
        normalized_client = self._identifier(client_id, field="clientId")
        deadline = time.monotonic() + min(max(float(timeout_seconds), 0.0), 25.0)
        while True:
            # Extension long-polls are normally empty. Keep that common path
            # read-only so it cannot starve Room/Agent writers sharing this DB.
            with self._connection() as connection:
                row = connection.execute(
                    """
                    SELECT * FROM browser_control_commands
                    WHERE device_id=? AND status='queued'
                    ORDER BY created_at_ms ASC
                    LIMIT 1
                    """,
                    (normalized_device,),
                ).fetchone()

            if row is not None:
                try:
                    with self._connection() as connection:
                        connection.execute("BEGIN IMMEDIATE")
                        # Another extension process may have claimed the row
                        # after the read-only probe. The status predicate makes
                        # this a compare-and-swap claim.
                        claimed_at = self._now_ms()
                        updated = connection.execute(
                            """
                            UPDATE browser_control_commands
                            SET status='claimed', claimed_at_ms=?, claimed_by=?
                            WHERE command_id=? AND status='queued'
                            """,
                            (claimed_at, normalized_client, row["command_id"]),
                        ).rowcount
                        if updated:
                            self._touch_client(connection, normalized_device)
                            self._event(
                                connection,
                                "command_claimed",
                                normalized_device,
                                {"action": row["action"], "clientId": normalized_client},
                                command_id=str(row["command_id"]),
                            )
                            connection.commit()
                            return {
                                "schemaVersion": SCHEMA_VERSION,
                                "ok": True,
                                "command": {
                                    "commandId": str(row["command_id"]),
                                    "action": str(row["action"]),
                                    **self._json_object(row["payload_json"]),
                                },
                            }
                except sqlite3.OperationalError as exc:
                    if "locked" not in str(exc).lower():
                        raise
            if time.monotonic() >= deadline:
                return {"schemaVersion": SCHEMA_VERSION, "ok": True, "command": None}
            time.sleep(0.2)

    def complete_command(self, payload: Mapping[str, object]) -> dict[str, object]:
        command_id = self._identifier(payload.get("commandId"), field="commandId")
        result = payload.get("result") if isinstance(payload.get("result"), Mapping) else {}
        result = dict(result)
        if result.get("url"):
            result["url"] = self._page_url(result.get("url"))
        screenshot_data_url = result.pop("screenshotDataUrl", None)
        page_markdown = result.pop("markdown", None)
        failure_reason = self._text(result.get("failureReason") or result.get("error"), maximum=240)
        status = "completed" if result.get("ok", True) is not False else "failed"
        with self._connection() as connection:
            record = connection.execute(
                "SELECT * FROM browser_control_commands WHERE command_id=?",
                (command_id,),
            ).fetchone()
            if record is None:
                raise BrowserControlError("browser command not found")
            if record["status"] not in {"queued", "claimed"}:
                raise BrowserControlError(f"browser command is already {record['status']}")
            if screenshot_data_url or page_markdown:
                snapshot_id = self._store_command_snapshot(
                    connection,
                    record=record,
                    result=result,
                    screenshot_data_url=screenshot_data_url,
                    markdown=page_markdown,
                )
                result["snapshotId"] = snapshot_id
                result["imagePath"] = f"/api/browser/snapshots/{snapshot_id}/image"
            encoded = json.dumps(result, ensure_ascii=False)
            if len(encoded.encode("utf-8")) > MAX_RESULT_JSON:
                result = {
                    "ok": result.get("ok", True) is not False,
                    "summary": self._text(result.get("summary"), maximum=1_200),
                    "url": self._url(result.get("url"), allow_blank=True),
                    "title": self._text(result.get("title"), maximum=500),
                    "truncated": True,
                }
                encoded = json.dumps(result, ensure_ascii=False)
            completed_at = self._now_ms()
            connection.execute(
                """
                UPDATE browser_control_commands
                SET status=?, result_json=?, failure_reason=?, completed_at_ms=?
                WHERE command_id=?
                """,
                (status, encoded, failure_reason, completed_at, command_id),
            )
            self._touch_client(connection, str(record["device_id"]))
            self._event(
                connection,
                "command_completed" if status == "completed" else "command_failed",
                str(record["device_id"]),
                {"action": record["action"], "failureReason": failure_reason},
                command_id=command_id,
            )
            connection.commit()
        return {"schemaVersion": SCHEMA_VERSION, "ok": True, "commandId": command_id}

    def permissions(self, *, limit: int = 100) -> dict[str, object]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM browser_control_permissions
                ORDER BY created_at_ms DESC
                LIMIT ?
                """,
                (min(max(int(limit), 1), 200),),
            ).fetchall()
        return {
            "schemaVersion": SCHEMA_VERSION,
            "ok": True,
            "items": [self._public_permission(row) for row in rows],
            "summary": f"已读取 {len(rows)} 条浏览器权限记录",
        }

    def request_permission(self, payload: Mapping[str, object]) -> dict[str, object]:
        device_id = self._identifier(payload.get("deviceId"), field="deviceId")
        origin = self._origin(payload.get("origin"))
        action = self._text(payload.get("action"), maximum=80)
        prompt_id = f"bperm_{uuid.uuid4().hex}"
        now = self._now_ms()
        with self._connection() as connection:
            remembered = connection.execute(
                """
                SELECT * FROM browser_control_permissions
                WHERE device_id=? AND origin=? AND action=?
                    AND status='resolved' AND decision IN ('allow_once', 'allow_site')
                ORDER BY resolved_at_ms DESC
                LIMIT 1
                """,
                (device_id, origin, action),
            ).fetchone()
            if remembered is not None:
                decision = str(remembered["decision"])
                if decision == "allow_once":
                    connection.execute(
                        "UPDATE browser_control_permissions SET status='consumed' WHERE prompt_id=?",
                        (remembered["prompt_id"],),
                    )
                self._event(
                    connection,
                    "permission_reused",
                    device_id,
                    {"origin": origin, "decision": decision},
                )
                connection.commit()
                return {
                    "schemaVersion": SCHEMA_VERSION,
                    "ok": True,
                    "authorized": True,
                    "decision": decision,
                    "promptId": str(remembered["prompt_id"]),
                }
            connection.execute(
                """
                INSERT INTO browser_control_permissions(
                    prompt_id, device_id, origin, action, reason, status, created_at_ms
                ) VALUES (?, ?, ?, ?, ?, 'pending', ?)
                """,
                (
                    prompt_id,
                    device_id,
                    origin,
                    action,
                    self._text(payload.get("reason"), maximum=500),
                    now,
                ),
            )
            self._event(connection, "permission_requested", device_id, {"promptId": prompt_id})
            connection.commit()
        return {
            "schemaVersion": SCHEMA_VERSION,
            "ok": True,
            "authorized": False,
            "promptId": prompt_id,
        }

    def permission_status(self, prompt_id: str) -> dict[str, object]:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM browser_control_permissions WHERE prompt_id=?",
                (self._identifier(prompt_id, field="promptId"),),
            ).fetchone()
        if row is None:
            raise BrowserControlError("browser permission prompt not found")
        return {"schemaVersion": SCHEMA_VERSION, "ok": True, **self._public_permission(row)}

    def decide_permission(self, prompt_id: str, decision: object) -> dict[str, object]:
        normalized = str(decision or "").strip()
        if normalized not in {"allow_once", "allow_site", "deny"}:
            raise BrowserControlError("decision must be allow_once, allow_site, or deny")
        resolved_at = self._now_ms()
        with self._connection() as connection:
            updated = connection.execute(
                """
                UPDATE browser_control_permissions
                SET status='resolved', decision=?, resolved_at_ms=?
                WHERE prompt_id=? AND status='pending'
                """,
                (normalized, resolved_at, self._identifier(prompt_id, field="promptId")),
            ).rowcount
            if not updated:
                raise BrowserControlError("browser permission prompt is no longer pending")
            self._event(connection, "permission_resolved", "", {"promptId": prompt_id, "decision": normalized})
            connection.commit()
        return {"schemaVersion": SCHEMA_VERSION, "ok": True, "promptId": prompt_id, "decision": normalized}

    def traces(self, *, limit: int = 50) -> dict[str, object]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM browser_control_commands
                ORDER BY created_at_ms DESC
                LIMIT ?
                """,
                (min(max(int(limit), 1), 200),),
            ).fetchall()
        items = [self._public_trace(row) for row in rows]
        return {
            "schemaVersion": SCHEMA_VERSION,
            "ok": True,
            "items": items,
            "summary": f"已读取 {len(items)} 条浏览器执行轨迹",
        }

    def stop(self) -> dict[str, object]:
        now = self._now_ms()
        with self._connection() as connection:
            cancelled = connection.execute(
                """
                UPDATE browser_control_commands
                SET status='cancelled', failure_reason='cancelled_by_user', completed_at_ms=?
                WHERE status IN ('queued', 'claimed')
                """,
                (now,),
            ).rowcount
            self._event(connection, "stop_requested", "", {"cancelled": cancelled})
            connection.commit()
        return {
            "schemaVersion": SCHEMA_VERSION,
            "ok": True,
            "cancelled": cancelled,
            "summary": f"已停止 {cancelled} 个待执行浏览器操作",
        }

    def managed_status(self) -> dict[str, object]:
        with self._connection() as connection:
            raw_pid = self._setting(connection, "managed_pid") or ""
        pid = int(raw_pid) if raw_pid.isdigit() else 0
        running = self._pid_running(pid)
        return {
            "running": running,
            "pid": pid if running else None,
            "profilePath": str(self.app_support_root / "BrowserCopilot" / "managed-profile"),
        }

    def start_managed(self) -> dict[str, object]:
        current = self.managed_status()
        if current["running"]:
            return {"schemaVersion": SCHEMA_VERSION, "ok": True, **current, "summary": "托管浏览器已在运行"}
        chrome = self._chrome_executable()
        if chrome is None:
            raise BrowserControlError("未找到 Google Chrome 或 Chromium")
        if not (self.extension_root / "manifest.json").is_file():
            raise BrowserControlError(f"浏览器插件目录不可用: {self.extension_root}")
        profile = self.app_support_root / "BrowserCopilot" / "managed-profile"
        profile.mkdir(parents=True, exist_ok=True)
        bootstrap_token = secrets.token_urlsafe(32)
        bootstrap_url = (
            "http://127.0.0.1:8766/api/browser/managed/bootstrap"
            f"?token={bootstrap_token}"
        )
        command = [
            str(chrome),
            f"--user-data-dir={profile}",
            f"--disable-extensions-except={self.extension_root}",
            f"--load-extension={self.extension_root}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-sync",
            bootstrap_url,
        ]
        process = self.command_runner(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        pid = int(getattr(process, "pid", 0) or 0)
        if pid <= 0:
            raise BrowserControlError("托管浏览器未返回有效进程号")
        with self._connection() as connection:
            self._set_setting(connection, "managed_pid", str(pid))
            self._set_setting(connection, "managed_bootstrap_token", bootstrap_token)
            self._set_setting(connection, "mode", "managed")
            self._event(connection, "managed_started", "", {"pid": pid})
            connection.commit()
        return {
            "schemaVersion": SCHEMA_VERSION,
            "ok": True,
            **self.managed_status(),
            "summary": "托管浏览器已启动",
        }

    def stop_managed(self) -> dict[str, object]:
        current = self.managed_status()
        pid = int(current.get("pid") or 0)
        if pid:
            try:
                os.killpg(pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                try:
                    os.kill(pid, signal.SIGTERM)
                except (ProcessLookupError, PermissionError):
                    pass
        with self._connection() as connection:
            self._set_setting(connection, "managed_pid", "")
            self._set_setting(connection, "managed_bootstrap_token", "")
            self._set_setting(connection, "mode", "observe")
            self._event(connection, "managed_stopped", "", {"pid": pid})
            connection.commit()
        return {
            "schemaVersion": SCHEMA_VERSION,
            "ok": True,
            "running": False,
            "summary": "托管浏览器已停止",
        }

    def _resolve_extension_root(self, extension_root: str | Path | None) -> Path:
        candidates = [
            extension_root,
            os.environ.get("RAG_IME_BROWSER_EXTENSION_DIR"),
            self.app_support_root / "BrowserCopilot" / "extension",
            Path(__file__).resolve().parents[1] / "integrations" / "browser-copilot" / "extension",
        ]
        for value in candidates:
            if not value:
                continue
            path = Path(value).expanduser().resolve(strict=False)
            if (path / "manifest.json").is_file():
                return path
        return Path(candidates[-1]).expanduser().resolve(strict=False)

    def _select_device(self, *, requested: str, prefer_managed: bool) -> str:
        now = self._now_ms()
        with self._connection() as connection:
            if requested:
                row = connection.execute(
                    "SELECT * FROM browser_control_clients WHERE device_id=?",
                    (self._identifier(requested, field="deviceId"),),
                ).fetchone()
                if row is None or now - int(row["last_seen_ms"]) > 15_000:
                    raise BrowserControlError("requested browser device is not connected")
                if prefer_managed and row["client_kind"] != "managed":
                    raise BrowserControlError(
                        "managed mode cannot target the user's daily browser"
                    )
                return str(row["device_id"])
            rows = connection.execute(
                "SELECT * FROM browser_control_clients ORDER BY last_seen_ms DESC"
            ).fetchall()
        active = [row for row in rows if now - int(row["last_seen_ms"]) <= 15_000]
        if prefer_managed:
            managed = next((row for row in active if row["client_kind"] == "managed"), None)
            if managed is not None:
                return str(managed["device_id"])
            raise BrowserControlError("managed browser extension is not connected")
        if active:
            return str(active[0]["device_id"])
        raise BrowserControlError("browser extension is not connected")

    def _normalize_command(self, action: str, payload: Mapping[str, object]) -> dict[str, object]:
        result: dict[str, object] = {}
        if payload.get("tabId") is not None:
            result["tabId"] = self._positive_int(payload.get("tabId"))
        if payload.get("refId") is not None:
            result["refId"] = self._identifier(payload.get("refId"), field="refId")
        if action == "navigate":
            result["url"] = self._url(payload.get("url"))
        if action == "type":
            result["text"] = str(payload.get("text") or "")[:8_000]
            result["clear"] = payload.get("clear") is not False
        if action == "scroll":
            direction = str(payload.get("direction") or "down")
            if direction not in {"up", "down", "left", "right"}:
                raise BrowserControlError("scroll direction is invalid")
            result["direction"] = direction
            result["amount"] = min(max(int(payload.get("amount") or 650), 80), 2_400)
        if action == "wait":
            result["text"] = str(payload.get("text") or "")[:500]
            result["timeoutMs"] = min(max(int(payload.get("timeoutMs") or 5_000), 100), 20_000)
        return result

    def _store_command_snapshot(
        self,
        connection: sqlite3.Connection,
        *,
        record: sqlite3.Row,
        result: dict[str, object],
        screenshot_data_url: object,
        markdown: object,
    ) -> str:
        mime, data = self._decode_screenshot(screenshot_data_url)
        latest = self._latest_snapshot_row(
            connection,
            device_id=str(record["device_id"]),
            tab_id=self._positive_int(result.get("tabId"), allow_none=True),
        )
        snapshot_id = f"snap_{uuid.uuid4().hex}"
        connection.execute(
            """
            INSERT INTO browser_control_snapshots(
                snapshot_id, device_id, tab_id, frame_id, url, title, summary,
                markdown, interactive_count, viewport_json, screenshot_mime,
                screenshot_bytes, created_at_ms
            ) VALUES (?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot_id,
                str(record["device_id"]),
                self._positive_int(result.get("tabId"), allow_none=True)
                or (int(latest["tab_id"]) if latest else 1),
                self._page_url(result.get("url"), allow_blank=True) or (str(latest["url"]) if latest else ""),
                self._text(result.get("title"), maximum=500) or (str(latest["title"]) if latest else ""),
                self._text(result.get("summary"), maximum=1_200)
                or ("可视页面截图" if data else "页面操作后的结构化快照"),
                str(markdown or "")[:MAX_SNAPSHOT_MARKDOWN]
                or (str(latest["markdown"]) if latest else ""),
                self._positive_int(
                    result.get("interactiveCount"),
                    allow_zero=True,
                    allow_none=True,
                )
                or (int(latest["interactive_count"]) if latest else 0),
                json.dumps(result.get("viewport") if isinstance(result.get("viewport"), Mapping) else {})
                if isinstance(result.get("viewport"), Mapping)
                else (str(latest["viewport_json"]) if latest else "{}"),
                mime,
                data,
                self._now_ms(),
            ),
        )
        return snapshot_id

    def _latest_snapshot_row(
        self,
        connection: sqlite3.Connection,
        *,
        device_id: str = "",
        tab_id: int | None = None,
    ) -> sqlite3.Row | None:
        conditions: list[str] = []
        values: list[object] = []
        if device_id:
            conditions.append("device_id=?")
            values.append(device_id)
        if tab_id:
            conditions.append("tab_id=?")
            values.append(tab_id)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        return connection.execute(
            f"SELECT * FROM browser_control_snapshots {where} ORDER BY created_at_ms DESC LIMIT 1",
            values,
        ).fetchone()

    def _public_client(self, row: sqlite3.Row, *, now: int) -> dict[str, object]:
        last_seen = int(row["last_seen_ms"])
        return {
            "deviceId": str(row["device_id"]),
            "displayName": str(row["display_name"]),
            "clientKind": str(row["client_kind"]),
            "extensionVersion": str(row["extension_version"]),
            "browserName": str(row["browser_name"]),
            "activeTabId": row["active_tab_id"],
            "lastSeenMs": last_seen,
            "connected": now - last_seen <= 15_000,
        }

    def _public_snapshot(self, row: sqlite3.Row, *, include_markdown: bool) -> dict[str, object]:
        snapshot_id = str(row["snapshot_id"])
        result: dict[str, object] = {
            "snapshotId": snapshot_id,
            "deviceId": str(row["device_id"]),
            "tabId": int(row["tab_id"]),
            "frameId": int(row["frame_id"]),
            "url": str(row["url"]),
            "title": str(row["title"]),
            "pageSummary": str(row["summary"]),
            "interactiveCount": int(row["interactive_count"]),
            "viewport": self._json_object(row["viewport_json"]),
            "hasScreenshot": bool(row["screenshot_bytes"]),
            "imagePath": f"/api/browser/snapshots/{snapshot_id}/image" if row["screenshot_bytes"] else "",
            "createdAtMs": int(row["created_at_ms"]),
        }
        if include_markdown:
            result["markdown"] = str(row["markdown"])
        return result

    def _public_permission(self, row: sqlite3.Row) -> dict[str, object]:
        return {
            "promptId": str(row["prompt_id"]),
            "deviceId": str(row["device_id"]),
            "origin": str(row["origin"]),
            "action": str(row["action"]),
            "reason": str(row["reason"]),
            "status": str(row["status"]),
            "decision": str(row["decision"] or ""),
            "createdAtMs": int(row["created_at_ms"]),
            "resolvedAtMs": int(row["resolved_at_ms"]) if row["resolved_at_ms"] else None,
        }

    def _public_trace(self, row: sqlite3.Row) -> dict[str, object]:
        created = int(row["created_at_ms"])
        completed = int(row["completed_at_ms"]) if row["completed_at_ms"] else None
        return {
            "commandId": str(row["command_id"]),
            "deviceId": str(row["device_id"]),
            "sessionId": str(row["session_id"]),
            "action": str(row["action"]),
            "status": str(row["status"]),
            "createdAtMs": created,
            "claimedAtMs": int(row["claimed_at_ms"]) if row["claimed_at_ms"] else None,
            "completedAtMs": completed,
            "durationMs": max(0, completed - created) if completed else None,
            "failureReason": str(row["failure_reason"] or ""),
            "result": self._trace_result(self._json_object(row["result_json"])),
        }

    def _trace_result(self, value: Mapping[str, object]) -> dict[str, object]:
        return {
            key: child
            for key, child in value.items()
            if key in {"ok", "summary", "url", "title", "tabId", "snapshotId", "imagePath"}
        }

    def _touch_client(self, connection: sqlite3.Connection, device_id: str) -> None:
        connection.execute(
            "UPDATE browser_control_clients SET last_seen_ms=? WHERE device_id=?",
            (self._now_ms(), device_id),
        )

    def _event(
        self,
        connection: sqlite3.Connection,
        kind: str,
        device_id: str,
        detail: Mapping[str, object],
        *,
        command_id: str | None = None,
    ) -> None:
        connection.execute(
            """
            INSERT INTO browser_control_events(kind, device_id, command_id, detail_json, created_at_ms)
            VALUES (?, ?, ?, ?, ?)
            """,
            (kind, device_id, command_id, json.dumps(dict(detail), ensure_ascii=False), self._now_ms()),
        )
        connection.execute(
            """
            DELETE FROM browser_control_events
            WHERE event_id NOT IN (
                SELECT event_id FROM browser_control_events ORDER BY created_at_ms DESC LIMIT 1000
            )
            """
        )

    def _setting(self, connection: sqlite3.Connection, key: str) -> str | None:
        row = connection.execute(
            "SELECT value FROM browser_control_settings WHERE key=?",
            (key,),
        ).fetchone()
        return str(row["value"]) if row else None

    def _set_setting(self, connection: sqlite3.Connection, key: str, value: str) -> None:
        connection.execute(
            """
            INSERT INTO browser_control_settings(key, value, updated_at_ms)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at_ms=excluded.updated_at_ms
            """,
            (key, value, self._now_ms()),
        )

    def _decode_screenshot(self, value: object) -> tuple[str | None, bytes | None]:
        text = str(value or "")
        if not text:
            return None, None
        if not text.startswith("data:image/") or ";base64," not in text:
            raise BrowserControlError("screenshotDataUrl must be a base64 image data URL")
        header, encoded = text.split(",", 1)
        mime = header[5:].split(";", 1)[0].lower()
        if mime not in {"image/png", "image/jpeg", "image/webp"}:
            raise BrowserControlError("browser screenshot mime type is not supported")
        try:
            data = base64.b64decode(encoded, validate=True)
        except ValueError as exc:
            raise BrowserControlError("browser screenshot base64 is invalid") from exc
        if not data or len(data) > MAX_SCREENSHOT_BYTES:
            raise BrowserControlError("browser screenshot exceeds the 8 MiB limit")
        return mime, data

    def _chrome_executable(self) -> Path | None:
        candidates = [
            os.environ.get("RAG_IME_CHROME_EXECUTABLE"),
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ]
        for candidate in candidates:
            if candidate and Path(candidate).is_file():
                return Path(candidate)
        return None

    @staticmethod
    def _pid_running(pid: int) -> bool:
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
            return True
        except (ProcessLookupError, PermissionError):
            return False

    @staticmethod
    def _now_ms() -> int:
        return int(time.time() * 1000)

    @staticmethod
    def _fingerprint(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]

    @staticmethod
    def _text(value: object, *, maximum: int) -> str:
        return " ".join(str(value or "").split())[:maximum]

    @staticmethod
    def _identifier(value: object, *, field: str) -> str:
        text = str(value or "").strip()
        if not text or len(text) > 160 or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-" for character in text):
            raise BrowserControlError(f"{field} is invalid")
        return text

    @staticmethod
    def _positive_int(
        value: object,
        *,
        allow_zero: bool = False,
        allow_none: bool = False,
    ) -> int | None:
        if value is None and allow_none:
            return None
        if isinstance(value, bool):
            raise BrowserControlError("numeric browser field is invalid")
        try:
            number = int(value)
        except (TypeError, ValueError) as exc:
            raise BrowserControlError("numeric browser field is invalid") from exc
        minimum = 0 if allow_zero else 1
        if number < minimum:
            raise BrowserControlError("numeric browser field is invalid")
        return number

    @staticmethod
    def _url(value: object, *, allow_blank: bool = False) -> str:
        text = str(value or "").strip()
        if allow_blank and not text:
            return ""
        parsed = urlsplit(text)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise BrowserControlError("browser URL must use http or https")
        try:
            parsed.port
        except ValueError as exc:
            raise BrowserControlError("browser URL port is invalid") from exc
        return text[:4_000]

    @staticmethod
    def _page_url(value: object, *, allow_blank: bool = False) -> str:
        text = BrowserControlService._url(value, allow_blank=allow_blank)
        if not text:
            return ""
        parsed = urlsplit(text)
        host = parsed.hostname or ""
        if ":" in host:
            host = f"[{host}]"
        if parsed.port is not None:
            host = f"{host}:{parsed.port}"
        query = urlencode(
            [
                (
                    key,
                    "[redacted]" if BrowserControlService._sensitive_query_key(key) else child,
                )
                for key, child in parse_qsl(parsed.query, keep_blank_values=True)
            ],
            doseq=True,
        )
        return urlunsplit((parsed.scheme, host, parsed.path, query, ""))[:4_000]

    @staticmethod
    def _sensitive_query_key(value: str) -> bool:
        normalized = value.lower().replace("-", "_")
        return any(
            marker in normalized
            for marker in (
                "token",
                "secret",
                "password",
                "passwd",
                "auth",
                "session",
                "jwt",
                "signature",
                "api_key",
                "code",
                "state",
            )
        )

    @staticmethod
    def _origin(value: object) -> str:
        text = str(value or "").strip()
        parsed = urlsplit(text)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise BrowserControlError("browser origin must use http or https")
        return f"{parsed.scheme}://{parsed.netloc}"[:500]

    @staticmethod
    def _json_object(value: object) -> dict[str, object]:
        if isinstance(value, Mapping):
            return dict(value)
        if not value:
            return {}
        try:
            parsed = json.loads(str(value))
        except (TypeError, ValueError):
            return {}
        return dict(parsed) if isinstance(parsed, Mapping) else {}

    @staticmethod
    def _command_summary(action: str, status: object, result: Mapping[str, object]) -> str:
        if status != "completed":
            return f"浏览器操作 {action} 未完成"
        provided = " ".join(str(result.get("summary") or "").split())
        return provided[:1_200] or f"浏览器操作 {action} 已完成"
