#!/usr/bin/env python3
"""Run a safe, real macOS Accessibility acceptance against a dedicated app."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rag_ime.agent_sessions import AgentSessionStore
from rag_ime.agent_tools import ControlToolGateway
from rag_ime.desktop_bridge import DesktopBridgeClient, DesktopBridgeError


BUNDLE_ID = "com.rag-ime.desktop-smoke-target"


def build_target(parent: Path) -> Path:
    app = parent / "RagImeDesktopSmokeTarget.app"
    executable_dir = app / "Contents" / "MacOS"
    executable_dir.mkdir(parents=True)
    shutil.copy2(
        ROOT / "macos" / "RagImeDesktopSmokeTarget" / "Info.plist",
        app / "Contents" / "Info.plist",
    )
    executable = executable_dir / "RagImeDesktopSmokeTarget"
    subprocess.run(
        [
            "xcrun",
            "swiftc",
            "-O",
            "-swift-version",
            "5",
            "-target",
            "arm64-apple-macosx13.0",
            "-framework",
            "AppKit",
            str(ROOT / "macos" / "RagImeDesktopSmokeTarget" / "DesktopSmokeTarget.swift"),
            "-o",
            str(executable),
        ],
        check=True,
    )
    subprocess.run(["codesign", "--force", "--deep", "--sign", "-", str(app)], check=True)
    return app


def tool_call(session_id: str, operation: str, **arguments: object) -> dict[str, object]:
    return {
        "schemaVersion": "rag-ime.agent-tool-call.v1",
        "sessionId": session_id,
        "tool": "desktop_semantic",
        "toolCallId": f"desktop-smoke:{uuid.uuid4()}",
        "args": {"op": operation, **arguments},
    }


def main() -> int:
    client = DesktopBridgeClient(timeout_seconds=3.0)
    status = client.status()
    if status.get("accessibilityTrusted") is not True:
        raise RuntimeError("RagImeDesktopBridge does not have Accessibility permission")
    if status.get("usesScreenCapture") is not False:
        raise RuntimeError("desktop bridge unexpectedly reports screen capture")

    with tempfile.TemporaryDirectory(prefix="rag-ime-desktop-smoke-") as temporary:
        root = Path(temporary)
        app = build_target(root)
        process = subprocess.Popen([str(app / "Contents" / "MacOS" / "RagImeDesktopSmokeTarget")])
        try:
            store = AgentSessionStore(root / "agent.sqlite")
            store.initialize()
            session = store.create(title="desktop foreground smoke")
            session_id = str(session["id"])
            gateway = ControlToolGateway(
                sessions=store,
                management=object(),
                core=object(),
                project="desktop-foreground-smoke",
                desktop_client=client,
            )

            tool_status = gateway.execute(tool_call(session_id, "status"))["result"]
            if not isinstance(tool_status, dict) or tool_status.get("available") is not True:
                raise RuntimeError("desktop_semantic status is not available through the Agent Tool")

            def inspect() -> dict[str, object]:
                result = gateway.execute(
                    tool_call(
                        session_id,
                        "inspect",
                        bundleId=BUNDLE_ID,
                        maxNodes=300,
                        maxDepth=10,
                        incremental=False,
                    )
                )["result"]
                assert isinstance(result, dict)
                return result

            snapshot: dict[str, object] | None = None
            deadline = time.monotonic() + 8.0
            while time.monotonic() < deadline:
                try:
                    candidate = inspect()
                    identifiers = {
                        str(node.get("identifier") or "")
                        for node in candidate.get("nodes", [])
                        if isinstance(node, dict)
                    }
                    if {"smoke-input", "smoke-apply", "smoke-stepper"} <= identifiers:
                        snapshot = candidate
                        break
                except DesktopBridgeError:
                    pass
                time.sleep(0.15)
            if snapshot is None:
                raise RuntimeError("smoke target did not become visible in the Accessibility tree")

            listed = gateway.execute(
                tool_call(session_id, "list", includeBackground=False)
            )["result"]
            if not isinstance(listed, dict) or not any(
                isinstance(item, dict) and item.get("bundleId") == BUNDLE_ID
                for item in listed.get("items", [])
            ):
                raise RuntimeError("desktop_semantic list did not return the smoke target")

            def node(current: dict[str, object], identifier: str) -> dict[str, object]:
                match = next(
                    (
                        item
                        for item in current.get("nodes", [])
                        if isinstance(item, dict) and item.get("identifier") == identifier
                    ),
                    None,
                )
                if match is None:
                    raise RuntimeError(f"Accessibility node missing: {identifier}")
                return match

            def prepare(
                current: dict[str, object], identifier: str, action: str, **arguments: object
            ) -> dict[str, object]:
                target = node(current, identifier)
                result = gateway.execute(
                    tool_call(
                        session_id,
                        "act",
                        snapshotId=current["snapshotId"],
                        revision=current["revision"],
                        nodeRef=target["nodeRef"],
                        action=action,
                        **arguments,
                    )
                )["result"]
                assert isinstance(result, dict)
                if result.get("approvalRequired") is not True:
                    raise RuntimeError("desktop mutation bypassed native approval")
                return result

            def approve(prepared: dict[str, object]) -> dict[str, object]:
                approval = prepared["approval"]
                assert isinstance(approval, dict)
                decided = store.decide_approval(
                    str(approval["approvalId"]),
                    approved=True,
                    payload_sha256=str(approval["payloadSha256"]),
                    decided_by="desktop-foreground-smoke",
                )
                receipt = gateway.apply_approval(decided)
                assert isinstance(receipt, dict)
                return receipt

            def applied_method(receipt: dict[str, object]) -> str:
                native = receipt.get("receipt")
                if not isinstance(native, dict) or native.get("applied") is not True:
                    raise RuntimeError("desktop action did not return an applied native receipt")
                return str(native.get("method") or "")

            checks: list[dict[str, object]] = []
            checks.append({"operation": "status", "verified": "available"})
            checks.append({"operation": "list", "verified": BUNDLE_ID})
            checks.append({"operation": "inspect", "verified": "stable identifiers"})

            first_incremental = gateway.execute(
                tool_call(
                    session_id,
                    "inspect",
                    bundleId=BUNDLE_ID,
                    maxNodes=299,
                    maxDepth=10,
                )
            )["result"]
            second_incremental = gateway.execute(
                tool_call(
                    session_id,
                    "inspect",
                    bundleId=BUNDLE_ID,
                    maxNodes=299,
                    maxDepth=10,
                )
            )["result"]
            if (
                not isinstance(first_incremental, dict)
                or not isinstance(second_incremental, dict)
                or second_incremental.get("diff", {}).get("fullSnapshot") is not False
            ):
                raise RuntimeError("desktop_semantic did not apply the automatic incremental cursor")
            checks.append(
                {
                    "operation": "inspect_incremental",
                    "verified": second_incremental.get("returnedNodeCount"),
                }
            )

            found = gateway.execute(
                tool_call(
                    session_id,
                    "find",
                    bundleId=BUNDLE_ID,
                    match={"identifier": "smoke-input"},
                )
            )["result"]
            if not isinstance(found, dict) or found.get("matchCount") != 1:
                raise RuntimeError("desktop_semantic find did not return one compact target")
            checks.append({"operation": "find", "verified": "smoke-input"})

            direct = gateway.execute(
                tool_call(
                    session_id,
                    "act",
                    bundleId=BUNDLE_ID,
                    match={"identifier": "smoke-input"},
                    action="set_text",
                    text="selector-ready",
                )
            )["result"]
            assert isinstance(direct, dict)
            if direct.get("approval", {}).get("preview", {}).get("selectorResolved") is not True:
                raise RuntimeError("selector act did not resolve through native find")
            direct_receipt = approve(direct)
            if "postSnapshot" in direct_receipt.get("receipt", {}):
                raise RuntimeError("compact model receipt leaked the full post snapshot")
            if "postSnapshot" not in direct_receipt.get("auditReceipt", {}):
                raise RuntimeError("durable audit receipt lost the full post snapshot")
            payload_bytes = {
                "fullInspect": len(
                    json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")).encode()
                ),
                "semanticFind": len(
                    json.dumps(found, ensure_ascii=False, separators=(",", ":")).encode()
                ),
                "compactActionReceipt": len(
                    json.dumps(
                        direct_receipt["receipt"],
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ).encode()
                ),
                "durableAuditReceipt": len(
                    json.dumps(
                        direct_receipt["auditReceipt"],
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ).encode()
                ),
            }
            snapshot = inspect()
            if node(snapshot, "smoke-input").get("value") != "selector-ready":
                raise RuntimeError("selector act did not update the real NSTextField")
            checks.append({"action": "selector+set_text", "verified": "selector-ready"})

            prepared = prepare(snapshot, "smoke-input", "set_text", text="semantic-ready")
            approve(prepared)
            snapshot = inspect()
            if node(snapshot, "smoke-input").get("value") != "semantic-ready":
                raise RuntimeError("set_text did not update the real NSTextField")
            checks.append({"action": "set_text", "verified": "semantic-ready"})

            approve(prepare(snapshot, "smoke-stepper", "increment"))
            snapshot = inspect()
            if float(str(node(snapshot, "smoke-stepper").get("value") or "nan")) != 2.0:
                raise RuntimeError("increment did not update the real NSStepper")
            checks.append({"action": "increment", "verified": 2})

            approve(prepare(snapshot, "smoke-stepper", "decrement"))
            snapshot = inspect()
            if float(str(node(snapshot, "smoke-stepper").get("value") or "nan")) != 1.0:
                raise RuntimeError("decrement did not update the real NSStepper")
            checks.append({"action": "decrement", "verified": 1})

            click_receipt = approve(prepare(snapshot, "smoke-apply", "click"))
            if applied_method(click_receipt) != "ax_press":
                raise RuntimeError("click did not prefer the semantic AX press action")
            snapshot = inspect()
            if node(snapshot, "smoke-status").get("value") != "applied#1:semantic-ready":
                raise RuntimeError("click did not invoke the real NSButton callback")
            checks.append({"action": "click", "verified": "applied#1:semantic-ready"})

            press_receipt = approve(prepare(snapshot, "smoke-apply", "press"))
            if applied_method(press_receipt) != "ax_press":
                raise RuntimeError("press did not use the native AX action")
            snapshot = inspect()
            if node(snapshot, "smoke-status").get("value") != "applied#2:semantic-ready":
                raise RuntimeError("press did not invoke the real NSButton callback")
            checks.append({"action": "press", "verified": "applied#2:semantic-ready"})

            double_receipt = approve(prepare(snapshot, "smoke-apply", "double_click"))
            if applied_method(double_receipt) != "cg_mouse_at_ax_bounds":
                raise RuntimeError("double_click did not use AX-derived bounds")
            snapshot = inspect()
            double_status = str(node(snapshot, "smoke-status").get("value") or "")
            if not double_status.startswith("applied#") or double_status == "applied#2:semantic-ready":
                raise RuntimeError("double_click did not reach the real NSButton")
            checks.append({"action": "double_click", "verified": double_status})

            long_receipt = approve(
                prepare(snapshot, "smoke-apply", "long_press", durationMs=120)
            )
            if applied_method(long_receipt) != "cg_mouse_at_ax_bounds":
                raise RuntimeError("long_press did not use AX-derived bounds")
            snapshot = inspect()
            long_status = str(node(snapshot, "smoke-status").get("value") or "")
            if long_status == double_status:
                raise RuntimeError("long_press did not reach the real NSButton")
            checks.append({"action": "long_press", "verified": long_status})

            approve(prepare(snapshot, "smoke-input", "focus"))
            snapshot = inspect()
            approve(prepare(snapshot, "smoke-input", "type_text", text="-typed"))
            snapshot = inspect()
            typed_value = str(node(snapshot, "smoke-input").get("value") or "")
            if "-typed" not in typed_value:
                raise RuntimeError("type_text did not reach the focused real NSTextField")
            checks.append({"action": "focus+type_text", "verified": typed_value})

            key_receipt = approve(prepare(snapshot, "smoke-input", "key", key="end"))
            if applied_method(key_receipt) != "cg_keyboard":
                raise RuntimeError("key did not use the native keyboard event path")
            checks.append({"action": "key", "verified": "end"})

            snapshot = inspect()
            scroll_receipt = approve(prepare(snapshot, "smoke-scroll", "scroll", scrollDelta=3))
            if applied_method(scroll_receipt) != "cg_scroll_at_ax_bounds":
                raise RuntimeError("scroll did not use Accessibility-derived bounds")
            checks.append({"action": "scroll", "verified": "ax-bounds"})

            snapshot = inspect()
            stale_preview = prepare(snapshot, "smoke-input", "set_text", text="must-not-apply")
            stale_approval = stale_preview["approval"]
            assert isinstance(stale_approval, dict)
            stale_decision = store.decide_approval(
                str(stale_approval["approvalId"]),
                approved=True,
                payload_sha256=str(stale_approval["payloadSha256"]),
                decided_by="desktop-foreground-smoke",
            )
            approve(prepare(snapshot, "smoke-input", "set_text", text="newer-state"))
            try:
                gateway.apply_approval(stale_decision)
            except DesktopBridgeError as error:
                if error.code != "stale_state":
                    raise
            else:
                raise RuntimeError("an approved action overwrote a node that changed after preview")
            snapshot = inspect()
            if node(snapshot, "smoke-input").get("value") != "newer-state":
                raise RuntimeError("stale action changed the field despite rejection")
            checks.append({"action": "stale_rejection", "verified": "newer-state"})

            menu_receipt = approve(prepare(snapshot, "smoke-menu", "show_menu"))
            if applied_method(menu_receipt) != "ax_show_menu":
                raise RuntimeError("show_menu did not use the native AX action")
            checks.append({"action": "show_menu", "verified": "ax_show_menu"})

            # Close the popup through the same semantic action path before the
            # context-menu check. The root can change while a menu is open, so
            # use any node returned by the fresh snapshot as the key target.
            snapshot = inspect()
            available_nodes = [item for item in snapshot.get("nodes", []) if isinstance(item, dict)]
            if not available_nodes:
                raise RuntimeError("menu snapshot did not expose a key target")
            escape_result = gateway.execute(
                tool_call(
                    session_id,
                    "act",
                    snapshotId=snapshot["snapshotId"],
                    revision=snapshot["revision"],
                    nodeRef=available_nodes[0]["nodeRef"],
                    action="key",
                    key="escape",
                )
            )["result"]
            assert isinstance(escape_result, dict)
            if applied_method(approve(escape_result)) != "cg_keyboard":
                raise RuntimeError("escape did not close the native menu through the key path")

            snapshot = inspect()
            right_receipt = approve(prepare(snapshot, "smoke-apply", "right_click"))
            if applied_method(right_receipt) != "cg_mouse_at_ax_bounds":
                raise RuntimeError("right_click did not use Accessibility-derived bounds")
            checks.append({"action": "right_click", "verified": "ax-bounds"})

            print(
                json.dumps(
                    {
                        "schemaVersion": "rag-ime.desktop-foreground-acceptance.v1",
                        "ok": True,
                        "bundleId": BUNDLE_ID,
                        "captureMode": status.get("captureMode"),
                        "usesScreenCapture": status.get("usesScreenCapture"),
                        "usesModelSuppliedCoordinates": status.get("usesModelSuppliedCoordinates"),
                        "payloadBytes": payload_bytes,
                        "checks": checks,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        finally:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
