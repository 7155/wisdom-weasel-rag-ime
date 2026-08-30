from __future__ import annotations

from collections.abc import Mapping

from .text_utils import compact_whitespace, truncate_preserving_layout, truncate_text


WINDOW_CONTEXT_SCHEMA_VERSION = "rag-ime.window-context.v1"
GENERATION_WINDOW_CONTEXT_PROJECTION = "generation_text"
WINDOW_CONTEXT_CAPTURE_MODES = frozenset(
    {
        "accessibility_semantics",
        "terminal_visible_range",
    }
)
_FORBIDDEN_VISUAL_KEYS = frozenset(
    {
        "dataBase64",
        "mimeType",
        "pixelWidth",
        "pixelHeight",
        "image",
        "screenshot",
        "ocr",
        "bounds",
        "x",
        "y",
    }
)
_NON_TEXT_ROLES = frozenset(
    {
        "AXApplication",
        "AXButton",
        "AXCheckBox",
        "AXDisclosureTriangle",
        "AXGroup",
        "AXImage",
        "AXMenu",
        "AXMenuBar",
        "AXMenuButton",
        "AXMenuItem",
        "AXRadioButton",
        "AXScrollArea",
        "AXScrollBar",
        "AXSheet",
        "AXSplitter",
        "AXTabGroup",
        "AXToolbar",
        "AXWindow",
    }
)
_LABEL_TEXT_ROLES = frozenset(
    {
        "AXCell",
        "AXColumn",
        "AXHeading",
        "AXLink",
        "AXListItem",
        "AXOutlineRow",
        "AXParagraph",
        "AXRow",
        "AXStaticText",
        "AXTextArea",
        "AXTextField",
        "AXWebArea",
    }
)


def validate_window_context(value: object) -> dict[str, object]:
    """Normalize bounded foreground semantics and reject visual payloads."""

    if value in (None, {}):
        return {}
    if not isinstance(value, Mapping):
        raise ValueError("windowContext must be an object")
    if str(value.get("schemaVersion") or "") != WINDOW_CONTEXT_SCHEMA_VERSION:
        raise ValueError("windowContext schemaVersion is invalid")
    capture_mode = str(value.get("captureMode") or "")
    if capture_mode not in WINDOW_CONTEXT_CAPTURE_MODES:
        raise ValueError("windowContext captureMode is unsupported")
    if _contains_forbidden_visual_key(value):
        raise ValueError("windowContext must not contain screenshots, OCR, or coordinates")
    if str(value.get("privacyDisposition") or "allowed") != "allowed":
        return {}

    application = value.get("application") if isinstance(value.get("application"), Mapping) else {}
    node_value_limit = 4_000 if capture_mode == "terminal_visible_range" else 800
    nodes: list[dict[str, object]] = []
    raw_nodes = value.get("nodes") if isinstance(value.get("nodes"), list) else []
    for raw in raw_nodes[:160]:
        if not isinstance(raw, Mapping):
            continue
        secure = raw.get("secure") is True
        node: dict[str, object] = {
            "nodeRef": _text(raw.get("nodeRef"), 200),
            "parentRef": _text(raw.get("parentRef"), 200),
            "depth": _integer(raw.get("depth"), default=0, minimum=0, maximum=12),
            "role": _text(raw.get("role"), 80),
            "enabled": raw.get("enabled") is not False,
            "focused": raw.get("focused") is True,
            "selected": raw.get("selected") is True,
            "secure": secure,
            "actions": _strings(raw.get("actions"), limit=20, maximum=80),
        }
        subrole = _text(raw.get("subrole"), 80)
        label = _text(raw.get("label"), 240)
        value_text = "" if secure else _text(raw.get("value"), node_value_limit)
        if subrole:
            node["subrole"] = subrole
        if label:
            node["label"] = label
        if value_text:
            node["value"] = value_text
        if node["nodeRef"] and node["role"]:
            nodes.append(node)

    semantic_text = truncate_text(
        compact_whitespace(str(value.get("semanticText") or "")),
        12_000,
    )
    validated: dict[str, object] = {
        "schemaVersion": WINDOW_CONTEXT_SCHEMA_VERSION,
        "captureMode": capture_mode,
        "snapshotId": _text(value.get("snapshotId"), 200),
        "revision": _integer(value.get("revision"), default=1, minimum=1, maximum=2_147_483_647),
        "capturedAtMs": _integer(value.get("capturedAtMs"), default=0, minimum=0, maximum=10**16),
        "privacyDisposition": "allowed",
        "application": {
            "pid": _integer(application.get("pid"), default=0, minimum=0, maximum=2_147_483_647),
            "bundleId": _text(application.get("bundleId"), 300),
            "name": _text(application.get("name"), 160),
            "windowTitle": _text(application.get("windowTitle"), 240),
        },
        "focusedNodeRef": _text(value.get("focusedNodeRef"), 200),
        "nodes": nodes,
        "nodeCount": len(nodes),
        "truncated": value.get("truncated") is True or len(raw_nodes) > len(nodes),
        "semanticText": semantic_text,
    }
    application_semantics = _application_semantics(value.get("applicationSemantics"))
    if application_semantics:
        validated["applicationSemantics"] = application_semantics
    return validated


def project_window_context_for_generation(value: object) -> dict[str, object]:
    """Keep bounded foreground text without leaking the AX control tree.

    Desktop operation consumes the full validated tree. The stateless generation
    path keeps readable AX text plus an explicitly sourced, read-only application
    projection. Structural groups, buttons, actions, node references, process
    identifiers, and absolute workspace paths are intentionally excluded.
    """

    if not isinstance(value, Mapping):
        return {}
    capture_mode = str(value.get("captureMode") or "")
    if capture_mode not in WINDOW_CONTEXT_CAPTURE_MODES:
        capture_mode = "accessibility_semantics"
    raw_application = value.get("application")
    application = raw_application if isinstance(raw_application, Mapping) else {}
    application_name = _text(application.get("name"), 160)
    window_title = _text(application.get("windowTitle"), 240)
    orientation = {
        key: text
        for key, text in (
            ("name", application_name),
            ("windowTitle", window_title),
        )
        if text
    }
    node_value_limit = 4_000 if capture_mode == "terminal_visible_range" else 800
    raw_nodes = value.get("nodes") if isinstance(value.get("nodes"), list) else []
    candidates: list[dict[str, object]] = []
    seen_text: set[str] = set()
    for raw in raw_nodes[:160]:
        if not isinstance(raw, Mapping) or raw.get("secure") is True:
            continue
        role = _text(raw.get("role"), 80)
        if role in _NON_TEXT_ROLES:
            continue
        node_value = _text(raw.get("value"), node_value_limit)
        label = _text(raw.get("label"), 240)
        readable_text = node_value or (label if role in _LABEL_TEXT_ROLES else "")
        if not readable_text:
            continue
        normalized = readable_text.casefold()
        if normalized in seen_text:
            continue
        seen_text.add(normalized)
        node: dict[str, object] = {
            "role": role or "AXText",
            "value": readable_text,
        }
        subrole = _text(raw.get("subrole"), 80)
        if subrole:
            node["subrole"] = subrole
        if label and label.casefold() != normalized:
            node["label"] = label
        if raw.get("focused") is True:
            node["focused"] = True
        if raw.get("selected") is True:
            node["selected"] = True
        candidates.append(node)
        if len(candidates) >= 48:
            break

    application_semantics = _application_semantics(value.get("applicationSemantics"))
    if not candidates and not orientation and not application_semantics:
        return {}
    projected: dict[str, object] = {
        "schemaVersion": WINDOW_CONTEXT_SCHEMA_VERSION,
        "captureMode": capture_mode,
        "projection": GENERATION_WINDOW_CONTEXT_PROJECTION,
        "capturedAtMs": _integer(value.get("capturedAtMs"), default=0, minimum=0, maximum=10**16),
        "nodes": candidates,
        "nodeCount": len(candidates),
        "sourceNodeCount": len(raw_nodes),
        "truncated": value.get("truncated") is True or len(candidates) < len(raw_nodes),
        "trust": {
            "maySupportIntent": True,
            "maySupportFacts": False,
            "mustNotOverrideCurrentInput": True,
        },
    }
    if orientation:
        projected["application"] = orientation
    if application_semantics:
        projected["applicationSemantics"] = application_semantics
    return projected


def _application_semantics(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {}
    if str(value.get("source") or "") != "zed_workspace_state":
        return {}
    raw_trust = value.get("trust")
    trust = raw_trust if isinstance(raw_trust, Mapping) else {}
    projected: dict[str, object] = {
        "source": "zed_workspace_state",
        "freshness": "best_effort_local_state",
        "projectName": _project_name(value.get("projectName")),
        "activeFile": _relative_file(value.get("activeFile")),
        "editorExcerpt": truncate_preserving_layout(
            str(value.get("editorExcerpt") or ""),
            8_000,
        ),
        "editorExcerptStartLine": _integer(
            value.get("editorExcerptStartLine"),
            default=1,
            minimum=1,
            maximum=10_000_000,
        ),
        "projectEntries": _project_entries(value.get("projectEntries")),
        "projectEntriesScope": "workspace_root",
        "contentOrigin": (
            "zed_recovery_buffer"
            if str(value.get("contentOrigin") or "") == "zed_recovery_buffer"
            else (
                "sensitive_file_blocked"
                if str(value.get("contentOrigin") or "") == "sensitive_file_blocked"
                else "workspace_file"
            )
        ),
        "trust": {
            "maySupportIntent": True,
            "maySupportFacts": False,
            "mayLagUnsavedChanges": trust.get("mayLagUnsavedChanges") is True,
            "mustNotOverrideCurrentInput": True,
        },
    }
    if not any(
        (
            projected["projectName"],
            projected["activeFile"],
            projected["editorExcerpt"],
            projected["projectEntries"],
        )
    ):
        return {}
    return projected


def _contains_forbidden_visual_key(value: object, *, depth: int = 0) -> bool:
    if depth > 4:
        return False
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key) in _FORBIDDEN_VISUAL_KEYS:
                return True
            if _contains_forbidden_visual_key(item, depth=depth + 1):
                return True
    elif isinstance(value, list):
        return any(_contains_forbidden_visual_key(item, depth=depth + 1) for item in value[:200])
    return False


def _text(value: object, maximum: int) -> str:
    return truncate_text(compact_whitespace(str(value or "")), maximum)


def _integer(value: object, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _strings(value: object, *, limit: int, maximum: int) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        text = _text(item, maximum)
        if text and text not in result:
            result.append(text)
        if len(result) >= limit:
            break
    return result


def _project_name(value: object) -> str:
    text = _text(value, 160)
    return "" if text in {".", ".."} or "/" in text or "\\" in text else text


def _relative_file(value: object) -> str:
    text = _text(value, 500)
    if (
        not text
        or text.startswith(("/", "~"))
        or "\\" in text
        or any(part in {"", ".", ".."} for part in text.split("/"))
    ):
        return ""
    return text


def _project_entries(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value[:48]:
        text = _text(item, 240)
        name = text[:-1] if text.endswith("/") else text
        if (
            not name
            or name in {".", ".."}
            or "/" in name
            or "\\" in name
        ):
            continue
        normalized = f"{name}/" if text.endswith("/") else name
        if normalized not in result:
            result.append(normalized)
    return result
