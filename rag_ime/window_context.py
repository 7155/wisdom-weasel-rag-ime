from __future__ import annotations

from collections.abc import Mapping

from .text_utils import compact_whitespace, truncate_text


WINDOW_CONTEXT_SCHEMA_VERSION = "rag-ime.window-context.v1"
GENERATION_WINDOW_CONTEXT_PROJECTION = "generation_text"
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
    """Normalize bounded AX semantics and reject visual/coordinate payloads."""

    if value in (None, {}):
        return {}
    if not isinstance(value, Mapping):
        raise ValueError("windowContext must be an object")
    if str(value.get("schemaVersion") or "") != WINDOW_CONTEXT_SCHEMA_VERSION:
        raise ValueError("windowContext schemaVersion is invalid")
    if str(value.get("captureMode") or "") != "accessibility_semantics":
        raise ValueError("windowContext must use accessibility_semantics")
    if _contains_forbidden_visual_key(value):
        raise ValueError("windowContext must not contain screenshots, OCR, or coordinates")
    if str(value.get("privacyDisposition") or "allowed") != "allowed":
        return {}

    application = value.get("application") if isinstance(value.get("application"), Mapping) else {}
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
        value_text = "" if secure else _text(raw.get("value"), 800)
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
    return {
        "schemaVersion": WINDOW_CONTEXT_SCHEMA_VERSION,
        "captureMode": "accessibility_semantics",
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


def project_window_context_for_generation(value: object) -> dict[str, object]:
    """Keep readable AX text for generation without leaking the control tree.

    Desktop operation consumes the full validated tree. The stateless generation
    path only needs the text the user is reading or editing, so structural
    groups, buttons, actions, node references, app chrome, and window metadata
    are intentionally excluded here.
    """

    if not isinstance(value, Mapping):
        return {}
    raw_nodes = value.get("nodes") if isinstance(value.get("nodes"), list) else []
    candidates: list[dict[str, object]] = []
    seen_text: set[str] = set()
    for raw in raw_nodes[:160]:
        if not isinstance(raw, Mapping) or raw.get("secure") is True:
            continue
        role = _text(raw.get("role"), 80)
        if role in _NON_TEXT_ROLES:
            continue
        node_value = _text(raw.get("value"), 800)
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

    if not candidates:
        return {}
    return {
        "schemaVersion": WINDOW_CONTEXT_SCHEMA_VERSION,
        "captureMode": "accessibility_semantics",
        "projection": GENERATION_WINDOW_CONTEXT_PROJECTION,
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
