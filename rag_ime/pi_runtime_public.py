"""Pi message shaping and public projection shared by both protocols.

The second tranche out of `pi_runtime`'s privates. `pi_runtime_v2` imported
these from v1, which made v1 the owner of logic that describes the Pi wire
format and what may be shown publicly -- concerns neither protocol version
owns alone.

Everything here is a pure function of its arguments: message identity and
visibility, assistant preview and error extraction, redaction, and the public
projections for usage, models, retry status, fork candidates, tool activity
and confirmation values. Names and bodies are unchanged, so Provider payloads,
event ordering and abort behaviour are untouched.

`pi_message_payload` and the media URL builder it uses now live here too, so
`pi_runtime_v2` imports no private name from `pi_runtime` at all.

`__all__` is the projection contract. Every runtime protocol -- v1, v2 and
any future v3 adapter -- consumes exactly these names; the import-boundary
gate rejects private imports and public-looking names absent from `__all__`,
so the contract cannot silently regrow an undeclared back channel.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import quote

from .agent_blocks import (
    extract_completed_agent_blocks,
    normalize_trusted_agent_blocks,
)
from .agent_protocol import AgentBlock, AgentMessage, normalize_agent_block
from .contracts.json_schema import validate_contract

from .pi_runtime_values import (
    PiRuntimeError,
    as_integer,
    as_mapping,
    redact_runtime_text,
)

__all__ = [
    "APPROVAL_TITLE_PREFIX",
    "GROUPED_QUESTIONS_SCHEMA_VERSION",
    "GROUPED_QUESTIONS_TITLE_PREFIX",
    "REVIEW_TITLE_PREFIX",
    "canonical_grouped_answers",
    "canonical_code_tool_name",
    "grouped_questions_from_wire",
    "last_assistant_error",
    "last_assistant_preview",
    "last_room_commit_response_evidence",
    "managed_media_content_url",
    "pi_message_id",
    "pi_message_completes_public_turn",
    "pi_message_is_public",
    "pi_message_payload",
    "provider_retry_status",
    "public_code_tool_arguments",
    "public_code_tool_activity",
    "public_reasoning_summaries",
    "public_tool_error_text",
    "public_tool_output_text",
    "public_file_name",
    "public_fork_candidate_text",
    "public_pi_model",
    "public_usage",
    "public_usage_evidence",
    "redact_mapping",
    "safe_scalar",
    "supported_thinking_levels",
    "ui_confirmation_value",
    "visible_message_text",
]


APPROVAL_TITLE_PREFIX = "RAG-IME-APPROVAL:"


REVIEW_TITLE_PREFIX = "RAG-IME-REVIEW:"

GROUPED_QUESTIONS_TITLE_PREFIX = "RAG-IME-QUESTIONS:"


GROUPED_QUESTIONS_SCHEMA_VERSION = "rag-ime.grouped-questions.v2"


_GROUPED_QUESTION_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,79}$")
_GROUPED_CUSTOM_OPTION_LABELS = frozenset({"other", "其他", "其它", "自定义"})
_GROUPED_QUESTION_KEYS = frozenset(
    {"id", "question", "header", "options", "multi", "recommended"}
)
_GROUPED_OPTION_KEYS = frozenset({"label", "description", "preview"})


_CODE_TOOL_ALIASES = {
    "read_file": "read",
    "workspace_read": "read",
    "edit_file": "edit",
    "workspace_edit_file": "edit",
    "workspace_edit": "edit",
    "workspace_patch": "edit",
    "apply_patch": "edit",
    "write_file": "write",
    "workspace_write_file": "write",
    "workspace_write": "write",
    "shell": "bash",
    "workspace_shell": "bash",
    "workspace_job": "bash",
    "workspace_search": "grep",
    "workspace_list": "ls",
}


def canonical_code_tool_name(tool_name: object) -> str:
    """Collapse legacy and governed adapters onto the Pi public tool contract.

    Product authorization may still be implemented by internal ``workspace_*``
    adapters, but providers, events, and UI projections expose one coding-tool
    vocabulary: read, edit, write, bash (plus the optional grep/find/ls tools).
    """

    normalized = str(tool_name or "").strip().lower()
    return _CODE_TOOL_ALIASES.get(normalized, normalized)
_GROUPED_ANSWER_KEYS = frozenset({"selected", "custom"})


def public_tool_error_text(value: object, *, maximum: int = 1_000) -> str:
    """Extract one safe, useful tool failure reason from Pi's loose result carrier."""

    fragments: list[str] = []

    def visit(candidate: object, depth: int = 0) -> None:
        if depth > 4 or len(fragments) >= 8 or candidate is None:
            return
        if isinstance(candidate, str):
            normalized = candidate.strip()
            if not normalized:
                return
            if normalized[:1] in {"{", "["}:
                try:
                    decoded = json.loads(normalized)
                except (TypeError, ValueError):
                    decoded = None
                if decoded is not None:
                    visit(decoded, depth + 1)
                    return
            fragments.append(normalized)
            return
        if isinstance(candidate, Mapping):
            for key in (
                "error",
                "errorMessage",
                "reason",
                "message",
                "outputPreview",
                "summary",
            ):
                if candidate.get(key) is not None:
                    visit(candidate.get(key), depth + 1)
                    if fragments:
                        return
            for key in ("content", "details", "result"):
                if candidate.get(key) is not None:
                    visit(candidate.get(key), depth + 1)
                    if fragments:
                        return
            return
        if isinstance(candidate, (list, tuple)):
            for item in candidate[:16]:
                visit(item, depth + 1)
                if fragments:
                    return

    visit(value)
    normalized = redact_runtime_text(" ".join(fragments))
    # A failure reason is an untrusted scalar, but key-shaped assignments can
    # still occur inside that scalar (for example ``API_KEY=...``). Reuse the
    # mapping redactor so the key name, not only ``sk-*`` token syntax, owns
    # the safety decision.
    redacted = redact_mapping({"error": normalized}).get("error")
    safe = str(redacted or "")[:maximum].strip()
    if not safe:
        return ""
    if re.search(r"questionOptions|answerKind|questionKind", safe, re.IGNORECASE):
        return "这个问题的选项没有准备完整，伙伴会修正后重新发送。"
    if re.search(
        r"(?:验收短名|acceptanceAliases?).*(?:不一致|之外|unknown|mismatch)",
        safe,
        re.IGNORECASE,
    ):
        return "提交的完成条件与当前任务不一致，伙伴会读取最新进度后重试。"
    if re.search(
        r"(?:room_commit\.evidence|evidenceRefs?|验证依据).*(?:缺少|无效|invalid|missing|required)",
        safe,
        re.IGNORECASE,
    ):
        return "还缺少能证明任务完成的验证结果，伙伴会先完成对应检查。"
    if re.search(
        r"(?:工作卡片|room_(?:state|define|collaborate|integrate|post|commit)|"
        r"acceptanceAliases?|\bKernel\b|\bRoot\b|\bDispatch\b|\bReceipt\b)",
        safe,
        re.IGNORECASE,
    ):
        return "这一步没有通过任务检查，伙伴会读取最新进度后继续处理。"
    return safe


def _bounded_grouped_string(
    value: object,
    *,
    field: str,
    maximum: int,
    required: bool = False,
) -> str:
    if not isinstance(value, str):
        if required:
            raise ValueError(f"grouped {field} must be a string")
        return ""
    normalized = value.strip()
    if required and not normalized:
        raise ValueError(f"grouped {field} must not be empty")
    if len(normalized) > maximum:
        raise ValueError(f"grouped {field} is too long")
    return normalized


def _grouped_option_label_is_custom(label: str) -> bool:
    return label.casefold() in _GROUPED_CUSTOM_OPTION_LABELS


def _canonical_grouped_question(
    value: object,
    *,
    seen_ids: set[str],
) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError("grouped question must be an object")
    if set(value) - _GROUPED_QUESTION_KEYS:
        raise ValueError("grouped question contains unsupported fields")
    question_id = _bounded_grouped_string(
        value.get("id"),
        field="question id",
        maximum=80,
        required=True,
    )
    if _GROUPED_QUESTION_ID_RE.fullmatch(question_id) is None:
        raise ValueError("grouped question id is invalid")
    if question_id in seen_ids:
        raise ValueError("grouped question ids must be unique")
    question = _bounded_grouped_string(
        value.get("question"),
        field="question text",
        maximum=160,
        required=True,
    )
    raw_header = value.get("header")
    header = (
        _bounded_grouped_string(
            raw_header,
            field="question header",
            maximum=80,
            required=True,
        )
        if raw_header is not None
        else ""
    )
    raw_options = value.get("options")
    if not isinstance(raw_options, list) or not 2 <= len(raw_options) <= 5:
        raise ValueError("grouped question must contain two to five options")
    options: list[dict[str, object]] = []
    seen_labels: set[str] = set()
    for raw_option in raw_options:
        if not isinstance(raw_option, Mapping):
            raise ValueError("grouped question option must be an object")
        if set(raw_option) - _GROUPED_OPTION_KEYS:
            raise ValueError("grouped question option contains unsupported fields")
        label = _bounded_grouped_string(
            raw_option.get("label"),
            field="option label",
            maximum=240,
            required=True,
        )
        if _grouped_option_label_is_custom(label):
            raise ValueError("grouped question must not add an Other option")
        if label in seen_labels:
            raise ValueError("grouped question option labels must be unique")
        option: dict[str, object] = {"label": label}
        for field in ("description", "preview"):
            raw_value = raw_option.get(field)
            if raw_value is None:
                continue
            normalized = _bounded_grouped_string(
                raw_value,
                field=f"option {field}",
                maximum=500,
                required=True,
            )
            option[field] = normalized
        seen_labels.add(label)
        options.append(option)
    raw_multi = value.get("multi")
    if raw_multi is not None and not isinstance(raw_multi, bool):
        raise ValueError("grouped question multi must be a boolean")
    multi = bool(raw_multi) if raw_multi is not None else False
    raw_recommended = value.get("recommended")
    recommended: int | None = None
    if raw_recommended is not None:
        if (
            isinstance(raw_recommended, bool)
            or not isinstance(raw_recommended, int)
            or not 0 <= raw_recommended < len(options)
        ):
            raise ValueError("grouped question recommendation index is invalid")
        recommended = raw_recommended
    seen_ids.add(question_id)
    canonical: dict[str, object] = {
        "id": question_id,
        "question": question,
        "options": options,
    }
    if header:
        canonical["header"] = header
    if raw_multi is not None:
        canonical["multi"] = multi
    if recommended is not None:
        canonical["recommended"] = recommended
    return canonical


def grouped_questions_from_wire(value: object) -> list[dict[str, object]]:
    if not isinstance(value, str) or len(value.encode("utf-8")) > 12_000:
        raise ValueError("grouped question payload is missing or too large")
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("grouped question payload is not valid JSON") from exc
    if not isinstance(decoded, Mapping):
        raise ValueError("grouped question payload must be an object")
    if set(decoded) != {"schemaVersion", "questions"}:
        raise ValueError("grouped question payload contains unsupported fields")
    if decoded.get("schemaVersion") != GROUPED_QUESTIONS_SCHEMA_VERSION:
        raise ValueError("unsupported grouped question schema")
    raw_questions = decoded.get("questions")
    if not isinstance(raw_questions, list) or not 1 <= len(raw_questions) <= 4:
        raise ValueError("grouped question payload must contain one to four questions")
    seen_ids: set[str] = set()
    return [
        _canonical_grouped_question(item, seen_ids=seen_ids)
        for item in raw_questions
    ]


def canonical_grouped_answers(
    value: object,
    questions: object,
) -> str:
    if not isinstance(value, str) or len(value.encode("utf-8")) > 12_000:
        raise ValueError("grouped answer payload is missing or too large")
    if not isinstance(questions, list) or not 1 <= len(questions) <= 4:
        raise ValueError("grouped question state is invalid")
    try:
        canonical_questions: list[dict[str, object]] = []
        seen_ids: set[str] = set()
        for question in questions:
            canonical_questions.append(
                _canonical_grouped_question(question, seen_ids=seen_ids)
            )
    except ValueError as exc:
        raise ValueError("grouped question state is invalid") from exc
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("grouped answer payload is not valid JSON") from exc
    if not isinstance(decoded, Mapping) or set(decoded) != {"answers"}:
        raise ValueError("grouped answer payload must contain only answers")
    raw_answers = decoded.get("answers")
    if not isinstance(raw_answers, Mapping):
        raise ValueError("grouped answers must be an object")
    expected_ids = [str(question["id"]) for question in canonical_questions]
    if set(raw_answers) != set(expected_ids):
        raise ValueError("grouped answers must cover every offered question")
    answers: dict[str, dict[str, object]] = {}
    for question in canonical_questions:
        question_id = str(question["id"])
        raw_answer = raw_answers.get(question_id)
        if not isinstance(raw_answer, Mapping):
            raise ValueError("grouped answer must be an object")
        if set(raw_answer) - _GROUPED_ANSWER_KEYS or "selected" not in raw_answer:
            raise ValueError("grouped answer shape is invalid")
        raw_selected = raw_answer.get("selected")
        if (
            not isinstance(raw_selected, list)
            or any(not isinstance(item, str) for item in raw_selected)
        ):
            raise ValueError("grouped answer selections must be strings")
        selected = [item.strip() for item in raw_selected]
        if any(not item for item in selected) or len(set(selected)) != len(selected):
            raise ValueError("grouped answer selections must be non-empty and unique")
        option_labels = {
            str(option["label"])
            for option in question["options"]
            if isinstance(option, Mapping)
        }
        if any(item not in option_labels for item in selected):
            raise ValueError("grouped answer is not one of the offered options")
        multi = question.get("multi") is True
        if not multi and len(selected) > 1:
            raise ValueError("single-choice grouped answers allow one selection")
        raw_custom = raw_answer.get("custom")
        custom = ""
        if raw_custom is not None:
            custom = _bounded_grouped_string(
                raw_custom,
                field="custom answer",
                maximum=1_000,
                required=True,
            )
        if not selected and not custom:
            raise ValueError("grouped answer must select an option or provide custom text")
        if selected and custom and not multi:
            raise ValueError("single-choice grouped answers cannot combine custom text")
        answer: dict[str, object] = {"selected": selected}
        if custom:
            answer["custom"] = custom
        answers[question_id] = answer
    return json.dumps(
        {"answers": answers},
        ensure_ascii=False,
        separators=(",", ":"),
    )


def visible_message_text(role: str, text: str) -> str:
    if role != "user":
        return text
    tagged = re.search(
        r"<(?:agent|rag-ime)-user-query>\s*(.*?)\s*</(?:agent|rag-ime)-user-query>",
        text,
        flags=re.DOTALL,
    )
    if tagged:
        return tagged.group(1).strip()
    legacy_prefix = "请在当前连续会话中处理这个输入法深度查找任务。"
    marker = "\n用户问题：\n"
    if text.startswith(legacy_prefix) and marker in text:
        question = text.split(marker, 1)[1].split("\n\n本地时间：", 1)[0].strip()
        if question:
            return question
    return text


def public_file_name(value: str) -> str:
    normalized = str(value or "").replace("\\", "/").rstrip("/")
    file_name = normalized.rsplit("/", 1)[-1].strip()
    if not file_name or len(file_name) > 240 or any(ord(character) < 32 for character in file_name):
        return ""
    if _public_sensitive_file_path(normalized):
        return ""
    return file_name


def _public_sensitive_file_path(value: object) -> bool:
    normalized = str(value or "").replace("\\", "/").lower().rstrip("/")
    basename = normalized.rsplit("/", 1)[-1]
    if not basename:
        return False
    return (
        basename.startswith(".env")
        or basename in {
            ".npmrc", ".pypirc", ".netrc", "auth.json", "credentials",
            "credentials.json", "id_rsa", "id_ed25519",
        }
        or bool(re.search(
            r"(?:^|[._-])(?:auth|credentials?|secrets?|tokens?|passwords?|"
            r"cookies?|api[_-]?keys?|authorization)(?:$|[._-])",
            basename,
            re.IGNORECASE,
        ))
        or basename.endswith((".pem", ".key", ".p12", ".pfx"))
    )


def _public_command_references_sensitive_file(value: object) -> bool:
    command = str(value or "")
    if not command:
        return False
    fixed_basenames = {
        "credentials", "id_rsa", "id_ed25519", ".npmrc", ".pypirc",
        ".netrc",
    }
    for token in re.split(r"[\s\"'`|;&<>()]+", command):
        for part in token.split("="):
            candidate = part.strip("[]{}:,$")
            if not candidate:
                continue
            basename = candidate.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1].lower()
            looks_like_file = (
                "/" in candidate
                or "." in basename
                or basename in fixed_basenames
            )
            if looks_like_file and _public_sensitive_file_path(candidate):
                return True
    return False


def supported_thinking_levels(raw: Mapping[str, object]) -> list[str]:
    if not bool(raw.get("reasoning")):
        return ["off"]
    explicit = raw.get("thinkingLevels")
    if isinstance(explicit, list):
        allowed = {"off", "minimal", "low", "medium", "high", "xhigh", "max"}
        explicit_levels = [str(level) for level in explicit if str(level) in allowed]
        return list(dict.fromkeys(explicit_levels)) or ["off"]
    mapping = as_mapping(raw.get("thinkingLevelMap"))
    levels: list[str] = []
    for level in ("off", "minimal", "low", "medium", "high", "xhigh", "max"):
        mapped = mapping.get(level)
        if mapped is None and level in mapping:
            continue
        if level in {"xhigh", "max"} and level not in mapping:
            continue
        levels.append(level)
    return levels or ["off"]


def safe_scalar(value: object) -> object:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return redact_runtime_text(str(value))[:2000]


def last_assistant_error(messages: list[object]) -> str:
    for item in reversed(messages):
        message = as_mapping(item)
        if str(message.get("role") or "") != "assistant":
            continue
        if str(message.get("stopReason") or "").lower() != "error" and not message.get("errorMessage"):
            return ""
        return redact_runtime_text(str(message.get("errorMessage") or "模型请求失败，请重试"))
    return ""


def last_assistant_preview(messages: list[object]) -> str:
    for item in reversed(messages):
        message = as_mapping(item)
        if str(message.get("role") or "") != "assistant":
            continue
        content = message.get("content")
        if isinstance(content, str):
            return " ".join(content.split())[:240]
        if isinstance(content, list):
            text = " ".join(
                str(as_mapping(block).get("text") or "")
                for block in content
                if str(as_mapping(block).get("type") or "") == "text"
            )
            return " ".join(text.split())[:240]
    return ""


def pi_message_id(raw: Mapping[str, object], turn_id: str) -> str:
    value = str(raw.get("id") or "").strip()
    if value:
        return value
    timestamp = as_integer(raw.get("timestamp"))
    role = str(raw.get("role") or "assistant").lower()
    if timestamp:
        return f"pi:message:{role}:{timestamp}"
    serialized = json.dumps(raw.get("content"), ensure_ascii=False, sort_keys=True, default=str)
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:20]
    return f"pi:message:{role}:{digest}"


def pi_message_is_public(raw: Mapping[str, object]) -> bool:
    """Keep Pi's loop protocol out while retaining user-visible assistant text.

    Providers commonly attach a public progress paragraph and a Tool call to
    the same assistant message.  The Tool protocol is projected separately as
    a redacted activity timeline, but that must not erase the paragraph from
    durable history.  Tool-only messages remain absent from the human
    transcript.
    """

    role = str(raw.get("role") or "assistant").lower()
    if role == "user":
        return True
    if role != "assistant":
        return False
    content = raw.get("content")
    if not isinstance(content, list):
        return bool(str(content or "").strip()) or bool(raw.get("errorMessage"))
    return any(
        (
            str(as_mapping(item).get("type") or "") == "text"
            and bool(str(as_mapping(item).get("text") or "").strip())
        )
        or str(as_mapping(item).get("type") or "") == "image"
        for item in content
    ) or bool(raw.get("errorMessage"))


def pi_message_completes_public_turn(raw: Mapping[str, object]) -> bool:
    """Whether a Pi message is the durable assistant result for this turn.

    A Provider may stream useful progress text and a Tool call in the same
    assistant message.  That text is public, but the message is not terminal:
    the Tool result will be followed by another assistant message.  Publishing
    both as ``message_completed`` creates duplicate transcript rows and makes
    the first, provisional row look like a finished answer.
    """

    if not pi_message_is_public(raw):
        return False
    content = raw.get("content")
    if not isinstance(content, list):
        return True
    return not any(
        str(as_mapping(item).get("type") or "") in {"toolCall", "tool_call"}
        for item in content
    )


def public_reasoning_summaries(
    raw: Mapping[str, object],
    *,
    maximum_items: int = 8,
) -> list[str]:
    """Project only Provider-authored reasoning *summaries*.

    Pi's generic ``thinking`` carrier also transports private chain-of-thought
    for some Providers.  Only the OpenAI Responses API and the Codex Responses
    adapter define this carrier as a user-visible reasoning summary, so every
    other API (and every ``redacted_thinking`` block) stays private.  The
    projection is bounded, path/secret redacted, and contains no signatures or
    raw Provider metadata.
    """

    if str(raw.get("api") or "").strip().lower() not in {
        "openai-responses",
        "openai-codex-responses",
    }:
        return []
    content = raw.get("content")
    if not isinstance(content, list):
        return []
    limit = max(1, min(int(maximum_items), 12))
    result: list[str] = []
    for raw_block in content:
        block = as_mapping(raw_block)
        if str(block.get("type") or "") != "thinking":
            continue
        value = str(block.get("thinking") or block.get("text") or "").strip()
        if not value:
            continue
        headings = re.findall(r"\*\*([^*\n]{1,300})\*\*", value)
        candidates = headings or re.split(r"(?:\r?\n){2,}|\r?\n", value)
        for candidate in candidates:
            normalized = re.sub(
                r"^(?:[-*+]\s+|#{1,6}\s+)",
                "",
                str(candidate).strip(),
            )
            normalized = normalized.strip("*_` ")
            if not normalized:
                continue
            # Non-heading summaries can be paragraphs. Keep the first bounded
            # sentence rather than exposing an entire reasoning transcript.
            if not headings:
                sentence = re.split(r"(?<=[。！？.!?])\s+", normalized, maxsplit=1)[0]
                normalized = sentence or normalized
            safe = redact_runtime_text(normalized)[:240].strip()
            if safe and safe not in result:
                result.append(safe)
            if len(result) >= limit:
                return result
    return result


def public_usage(value: object) -> dict[str, int]:
    message = as_mapping(value)
    usage = as_mapping(message.get("usage"))
    input_tokens = as_integer(usage.get("input"))
    output_tokens = as_integer(usage.get("output"))
    cache_read = as_integer(usage.get("cacheRead"))
    cache_write = as_integer(usage.get("cacheWrite"))
    total = as_integer(usage.get("totalTokens"))
    if total <= 0:
        total = input_tokens + output_tokens + cache_read + cache_write
    return {
        "input": input_tokens,
        "output": output_tokens,
        "cacheRead": cache_read,
        "cacheWrite": cache_write,
        "totalTokens": total,
    }


def public_usage_evidence(value: object) -> dict[str, bool]:
    """Describe which usage fields the Provider response actually reported."""

    usage_value = as_mapping(value).get("usage")
    if not isinstance(usage_value, Mapping):
        return {
            "usageReported": False,
            "cacheUsageReported": False,
        }
    usage = dict(usage_value)

    def reported(key: str) -> bool:
        metric = usage.get(key)
        return (
            isinstance(metric, (int, float))
            and not isinstance(metric, bool)
        )

    return {
        "usageReported": any(
            reported(key)
            for key in (
                "input",
                "output",
                "cacheRead",
                "cacheWrite",
                "totalTokens",
            )
        ),
        "cacheUsageReported": any(
            reported(key)
            for key in ("cacheRead", "cacheWrite")
        ),
    }


def last_room_commit_response_evidence(
    messages: list[object],
) -> dict[str, object]:
    """Return safe model/usage evidence for the exact ``room_commit`` call.

    Managed Room turns commonly finish by calling ``room_commit`` and then
    settling without another public assistant paragraph.  The Provider still
    reports its identity and usage on that Tool-call message.  Keep the
    protocol body private, but retain those bounded receipt fields so the
    eventual Room Post can show its real runtime provenance.

    A normal public final message already owns this evidence through
    ``message_completed`` and must not create a second provenance event.
    """

    for item in reversed(messages):
        message = as_mapping(item)
        if str(message.get("role") or "").lower() != "assistant":
            continue
        if pi_message_completes_public_turn(message):
            return {}
        content = message.get("content")
        if not isinstance(content, list):
            continue
        commit_calls = [
            as_mapping(block)
            for block in content
            if (
                isinstance(block, Mapping)
                and str(block.get("type") or "") == "toolCall"
                and str(block.get("name") or "") == "room_commit"
                and str(block.get("id") or "").strip()
            )
        ]
        if len(commit_calls) != 1:
            continue
        tool_call_id = str(commit_calls[0]["id"]).strip()[:240]
        provider = str(message.get("provider") or "").strip()[:80]
        model = str(
            message.get("responseModel")
            or message.get("model")
            or ""
        ).strip()[:160]
        reporting = public_usage_evidence(message)
        if not provider and not model and not reporting["usageReported"]:
            return {}
        evidence: dict[str, object] = {
            "toolCallId": tool_call_id,
            "usageReported": reporting["usageReported"],
            "cacheUsageReported": (
                reporting["cacheUsageReported"]
                if reporting["usageReported"]
                else False
            ),
        }
        if provider:
            evidence["provider"] = provider
        if model:
            evidence["model"] = model
        if reporting["usageReported"]:
            evidence["usage"] = public_usage(message)
        return evidence
    return {}


def provider_retry_status(
    payload: Mapping[str, object],
    *,
    started: bool,
) -> dict[str, object]:
    """Project retry progress without leaking raw Provider diagnostics."""

    attempt = max(1, as_integer(payload.get("attempt")))
    maximum = max(attempt, as_integer(payload.get("maxAttempts")))
    if started:
        return {
            "status": "retrying",
            "phase": "provider_retry",
            "activityState": "running",
            "summary": f"模型连接暂时失败，正在自动重试（{attempt}/{maximum}）",
            "attempt": attempt,
            "maxAttempts": maximum,
            "delayMs": max(0, as_integer(payload.get("delayMs"))),
        }
    success = payload.get("success") is True
    return {
        "status": "analyzing" if success else "working",
        "phase": "provider_retry",
        "activityState": "completed" if success else "failed",
        "summary": (
            "模型连接已恢复，继续处理"
            if success
            else "自动重试未恢复，正在结束本轮"
        ),
        "attempt": attempt,
        "maxAttempts": maximum,
        "success": success,
    }


def ui_confirmation_value(value: object) -> bool:
    normalized = str(value or "").strip().lower()
    affirmative = (
        "yes",
        "y",
        "true",
        "confirm",
        "confirmed",
        "allow",
        "approve",
        "是",
        "确认",
        "同意",
        "允许",
        "批准",
        "保留",
    )
    negative = (
        "no",
        "n",
        "false",
        "cancel",
        "deny",
        "reject",
        "否",
        "取消",
        "不同意",
        "拒绝",
        "不允许",
        "删除",
    )
    if any(normalized == item or normalized.startswith(f"{item}，") or normalized.startswith(f"{item},") for item in affirmative):
        return True
    if any(normalized == item or normalized.startswith(f"{item}，") or normalized.startswith(f"{item},") for item in negative):
        return False
    raise PiRuntimeError("confirm UI response must explicitly approve or reject the request")


def public_fork_candidate_text(value: object, *, role: str = "user") -> str:
    """Return a public transcript preview without leaking injected context."""

    normalized = " ".join(str(value or "").split())[:8000]
    visible = (
        " ".join(visible_message_text("user", normalized).split())[:8000]
        if role == "user"
        else normalized
    )
    if any(
        marker in visible
        for marker in (
            "<agent-deep-search-context",
            "<agent-user-query",
            "<rag-ime-deep-search-context",
            "<rag-ime-user-query",
        )
    ):
        return ""
    return visible


def public_code_tool_activity(
    tool_name: str,
    args: Mapping[str, object],
    raw_result: object = None,
) -> dict[str, object]:
    """Project a bounded, useful coding-tool receipt for the private timeline.

    Tool arguments in the generic event envelope are intentionally redacted,
    but reducing every path, query and command to a generic label made the
    timeline useless for debugging. This projection keeps the operational
    nouns a user needs to audit (target, pattern, command, range) while
    redacting credentials and bounding returned output. Mutation bodies are
    never copied into the event.
    """

    normalized_tool = canonical_code_tool_name(tool_name)
    file_tools = {
        "read", "write", "edit",
    }
    search_tools = {"grep"}
    list_tools = {"find", "ls"}
    command_tools = {"bash", "workspace_job"}
    semantic_tools = {"workspace_lsp"}
    coding_tools = (
        file_tools | search_tools | list_tools | command_tools | semantic_tools
    )
    if normalized_tool not in coding_tools:
        return {}
    evidence = _public_tool_evidence_envelope(raw_result)
    evidence_request = as_mapping(evidence.get("evidenceRequest"))
    effective_args = {**evidence_request, **dict(args)}
    raw_path = str(
        effective_args.get("relativePath")
        or effective_args.get("fileName")
        or effective_args.get("file_path")
        or effective_args.get("path")
        or ""
    )
    workspace_path = _public_workspace_path(raw_path)
    file_name = public_file_name(raw_path)
    result: dict[str, object] = {}
    if file_name:
        result["fileName"] = file_name
    if workspace_path:
        result["path"] = workspace_path
    for key in ("root", "cwd"):
        visible_path = _public_workspace_path(effective_args.get(key))
        if visible_path:
            result[key] = visible_path

    for key in (
        "op",
        "operation",
        "mode",
        "patternKind",
        "server",
        "label",
        "jobId",
        "status",
        "reason",
    ):
        value = _public_tool_text(effective_args.get(key), maximum=240)
        if value:
            result[key] = value
    for key in ("query", "pattern", "glob", "title", "newName"):
        value = _public_tool_text(effective_args.get(key), maximum=500)
        if value:
            result[key] = value
    for key in (
        "offset",
        "limit",
        "context",
        "timeout",
        "line",
        "column",
        "timeoutMs",
        "timeoutSeconds",
        "cursor",
        "limitBytes",
    ):
        numeric_value = effective_args.get(key)
        if isinstance(numeric_value, (int, float)) and not isinstance(
            numeric_value,
            bool,
        ):
            result[key] = numeric_value

    raw_command = effective_args.get("command") or effective_args.get("cmd")
    protected_command = (
        normalized_tool in command_tools
        and _public_command_references_sensitive_file(raw_command)
    )
    if normalized_tool in command_tools:
        command = (
            "已运行受保护命令"
            if protected_command
            else _public_tool_text(raw_command, maximum=2_000)
        )
        if command:
            result["command"] = command

    if normalized_tool == "write":
        content = effective_args.get("content")
        if isinstance(content, str) and content:
            normalized = content.replace("\r\n", "\n").replace("\r", "\n")
            lines = normalized.split("\n")
            while lines and not lines[-1]:
                lines.pop()
            line_count = max(1, len(lines))
            result.update({"lineCount": line_count, "additions": line_count})
            if file_name:
                result["summary"] = f"{file_name} +{line_count}"
    if normalized_tool == "edit":
        edit = _public_edit_projection(raw_result, fallback_path=raw_path)
        if edit:
            result.update(edit)
    progress_summary = _public_tool_text(
        _public_tool_result_scalar(raw_result, "summary"),
        maximum=500,
    )
    if progress_summary and not result.get("summary"):
        result["summary"] = progress_summary
    preview_tools = (
        file_tools
        - {
            "write", "edit",
        }
        | search_tools
        | list_tools
        | command_tools
        | semantic_tools
    )
    if (
        normalized_tool in preview_tools
        and _public_tool_output_allowed(
            normalized_tool,
            raw_path,
            command=raw_command,
        )
    ):
        preview, truncated = _public_tool_output_preview(
            raw_result,
            evidence=evidence,
        )
        if preview:
            result["outputPreview"] = preview
            result["outputTruncated"] = truncated
    if (
        normalized_tool in command_tools
        and _public_tool_output_allowed(
            normalized_tool,
            raw_path,
            command=raw_command,
        )
    ):
        for channel in ("stdout", "stderr"):
            channel_preview, channel_truncated = _public_tool_channel_preview(
                raw_result,
                channel,
            )
            if channel_preview:
                result[f"{channel}Preview"] = channel_preview
                result[f"{channel}Truncated"] = channel_truncated
        exit_code = _public_tool_result_scalar(raw_result, "exitCode")
        if isinstance(exit_code, (int, float)) and not isinstance(exit_code, bool):
            result["exitCode"] = int(exit_code)
    model_decision = _public_approval_model_decision(raw_result)
    if model_decision:
        result["decisionMode"] = "model"
        result["approvalModelDecision"] = model_decision
        result["automatic"] = True

    return result


def _public_tool_result_layers(raw_result: object) -> list[Mapping[str, object]]:
    root = as_mapping(raw_result)
    if not root:
        return []
    layers: list[Mapping[str, object]] = [root]
    seen = {id(root)}
    frontier = [root]
    for _ in range(4):
        next_frontier: list[Mapping[str, object]] = []
        for layer in frontier:
            for key in ("details", "result", "receipt", "approval"):
                candidate = layer.get(key)
                if not isinstance(candidate, Mapping) or id(candidate) in seen:
                    continue
                seen.add(id(candidate))
                layers.append(candidate)
                next_frontier.append(candidate)
        frontier = next_frontier
        if not frontier:
            break
    return layers


def _public_tool_result_scalar(raw_result: object, key: str) -> object:
    for layer in _public_tool_result_layers(raw_result):
        if key in layer:
            return layer[key]
    return None


def _public_tool_channel_preview(
    raw_result: object,
    channel: str,
) -> tuple[str, bool]:
    raw_value = _public_tool_result_scalar(raw_result, channel)
    if not isinstance(raw_value, str) or not raw_value:
        return "", False
    safe = _public_tool_text(raw_value, maximum=6_000)
    if not safe:
        return "", False
    lines = safe.splitlines()
    preview = "\n".join(lines[:40])[:6_000]
    return preview, len(raw_value) > 6_000 or len(lines) > 40


def _public_edit_projection(
    raw_result: object,
    *,
    fallback_path: str = "",
) -> dict[str, object]:
    """Return a bounded semantic edit result with a safe diff preview.

    OMP edit results place the authoritative unified diff in ``details.diff``
    (and multi-file edits in ``details.perFileResults``). Keeping that shape at
    the runtime boundary lets both Session and Room show real file work instead
    of a generic successful Tool row, without persisting mutation bodies.
    """

    root = as_mapping(raw_result)
    nested_result = as_mapping(root.get("result"))
    layers = (
        root,
        as_mapping(root.get("details")),
        nested_result,
        as_mapping(nested_result.get("details")),
    )
    raw_files: list[tuple[str, str]] = []
    for layer in layers:
        per_file = layer.get("perFileResults")
        if not isinstance(per_file, list):
            continue
        for item in per_file[:64]:
            entry = as_mapping(item)
            path = str(
                entry.get("path")
                or entry.get("fileName")
                or fallback_path
                or ""
            )
            diff = entry.get("diff")
            if isinstance(diff, str):
                raw_files.append((path, diff))
    if not raw_files:
        for layer in layers:
            diff = layer.get("diff")
            if not isinstance(diff, str):
                continue
            path = str(
                layer.get("path")
                or layer.get("fileName")
                or fallback_path
                or ""
            )
            raw_files.append((path, diff))
            break
    if not raw_files:
        return {}

    changed_files: list[dict[str, object]] = []
    preview_chunks: list[str] = []
    total_additions = 0
    total_deletions = 0
    source_truncated = False
    for path, diff in raw_files:
        # Refuse mutation previews for credential-bearing files just as the
        # read projection does. Counts are also withheld because a secret-file
        # mutation should not become a public Room artifact.
        if not _public_tool_output_allowed("edit", path):
            continue
        bounded_source = diff[:4_000_000]
        source_truncated = source_truncated or len(diff) > len(bounded_source)
        additions, deletions = _public_diff_counts(bounded_source)
        total_additions += additions
        total_deletions += deletions
        workspace_path = _public_workspace_path(path)
        file_name = public_file_name(path)
        changed_files.append(
            {
                **({"path": workspace_path} if workspace_path else {}),
                **({"fileName": file_name} if file_name else {}),
                "additions": additions,
                "deletions": deletions,
            }
        )
        safe_diff = _public_tool_text(bounded_source, maximum=6_000)
        if safe_diff:
            preview_chunks.append(safe_diff)

    if not changed_files:
        return {}
    preview_source = "\n".join(preview_chunks)
    preview_lines = preview_source.splitlines()
    preview = "\n".join(preview_lines[:80])[:6_000]
    output_truncated = (
        source_truncated
        or len(preview_source) > 6_000
        or len(preview_lines) > 80
    )
    primary = changed_files[0]
    summary_target = (
        str(primary.get("fileName") or "")
        if len(changed_files) == 1
        else f"{len(changed_files)} 个文件"
    )
    return {
        "additions": total_additions,
        "deletions": total_deletions,
        "changedFiles": changed_files,
        "summary": f"{summary_target} +{total_additions} -{total_deletions}",
        **({"outputPreview": preview} if preview else {}),
        **({"outputTruncated": True} if output_truncated else {}),
    }


def _public_diff_counts(diff: str) -> tuple[int, int]:
    additions = 0
    deletions = 0
    for line in diff.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            additions += 1
        elif line.startswith("-") and not line.startswith("---"):
            deletions += 1
    return additions, deletions

def _public_approval_model_decision(
    raw_result: object,
) -> dict[str, object]:
    root = as_mapping(raw_result)
    nested_result = as_mapping(root.get("result"))
    nested_details = as_mapping(root.get("details"))
    nested_approval = as_mapping(
        root.get("approval")
        or nested_result.get("approval")
        or nested_details.get("approval")
    )
    for candidate in (
        root.get("approvalModelDecision"),
        nested_result.get("approvalModelDecision"),
        nested_details.get("approvalModelDecision"),
        nested_approval.get("approvalModelDecision"),
    ):
        if not isinstance(candidate, Mapping):
            continue
        public = dict(candidate)
        try:
            validate_contract(
                public,
                "agent-approval-model-decision.v1.json",
            )
        except ValueError:
            continue
        return public
    return {}



def _public_workspace_path(value: object) -> str:
    normalized = str(value or "").replace("\\", "/").strip()
    normalized = re.sub(r"/{2,}", "/", normalized)
    if (
        not normalized
        or len(normalized) > 1_000
        or any(ord(character) < 32 for character in normalized)
        or _public_sensitive_file_path(normalized)
        or re.search(
            r"token|secret|password|api.?key|authorization|cookie",
            normalized,
            re.IGNORECASE,
        )
    ):
        return ""
    parts = [part for part in normalized.split("/") if part]
    if any(part in {".", ".."} for part in parts):
        return ""
    absolute = normalized.startswith("/") or normalized.startswith("~/")
    if not absolute:
        return "/".join(parts) or normalized
    visible_parts = parts
    if normalized.startswith("/Users/") and len(parts) >= 2:
        visible_parts = parts[2:]
    elif normalized.startswith("/Volumes/") and len(parts) >= 2:
        visible_parts = parts[2:]
    elif normalized.startswith("/private/var/") and len(parts) >= 2:
        visible_parts = parts[2:]
    # Keep enough suffix to identify a concrete target without persisting a
    # home-directory account name or external-volume label.
    suffix = "/".join(visible_parts[-4:])
    return f"…/{suffix}" if suffix else ""


def _public_tool_text(value: object, *, maximum: int) -> str:
    if not isinstance(value, str):
        return ""
    text = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return ""
    text = re.sub(r"\bsk-[A-Za-z0-9_-]{6,}\b", "[REDACTED_SECRET]", text)
    text = re.sub(
        r"(?<![A-Za-z0-9_-])(?P<quote>[\"']?)"
        r"(?P<key>[A-Za-z0-9_-]*(?:api[_-]?key|access[_-]?token|password|secret|"
        r"authorization|token|cookie|bearer))(?P=quote)"
        r"(?P<separator>\s*(?:=|:)\s*)"
        r"(?:(?:Bearer|Basic|Token)\s+)?"
        r"(?:\"[^\"\r\n]*\"|'[^'\r\n]*'|[^\s'\"&,}]+)",
        r"\g<quote>\g<key>\g<quote>\g<separator>[REDACTED_SECRET]",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"(?i)(--(?:api[_-]?key|token|password|secret)\s+)"
        r"([^\s'\";]+|\"[^\"]*\"|'[^']*')",
        r"\1[REDACTED_SECRET]",
        text,
    )
    # Keep useful path suffixes in commands and grep output, but never persist
    # the local account or external-volume label. Prefix replacement works for
    # quoted paths containing spaces, unlike a whitespace-delimited path regex.
    text = re.sub(r"/Users/[^/\s]+/", "~/", text)
    text = re.sub(r"/Volumes/[^/]+/", "/…/", text)
    text = text.replace("/private/var/", "/…/var/")
    text = text.replace("/var/folders/", "/…/var/folders/")
    return text[:maximum]


def public_tool_output_text(
    value: object,
    *,
    maximum: int = 6_000,
) -> str:
    """Return bounded, multiline-safe public Tool output text.

    This is the public projection boundary used by event mirrors that must
    retain semantic line structure (notably unified diffs) without duplicating
    the runtime's secret and machine-path redaction rules.
    """

    return _public_tool_text(value, maximum=maximum)


def _public_tool_output_allowed(
    tool_name: str,
    raw_path: str,
    *,
    command: object = "",
) -> bool:
    if tool_name in {"bash", "workspace_shell", "workspace_job"}:
        return not _public_command_references_sensitive_file(command)
    return not _public_sensitive_file_path(raw_path)


def _public_tool_evidence_envelope(raw_result: object) -> dict[str, object]:
    """Recover a managed coding-tool receipt before generic truncation.

    The runtime bridge deliberately returns a small JSON evidence envelope
    rather than placing raw workspace output in the public event. Treating
    that envelope as ordinary text exposed internal handles and JSON syntax
    while hiding the useful request/summary. Parse only the bounded envelope
    shapes owned by the bridge; malformed or oversized values fall back to
    the generic safe preview path.
    """

    result = as_mapping(raw_result)
    candidates: list[object] = []
    content = result.get("content")
    if isinstance(content, list):
        candidates.extend(
            as_mapping(item).get("text")
            for item in content[:16]
        )
    candidates.extend(result.get(key) for key in ("stdout", "output", "text"))
    for candidate in candidates:
        if not isinstance(candidate, str) or not candidate:
            continue
        # Large enough for the bridge's intentionally bounded summaries, but
        # refuse to JSON-decode arbitrary multi-megabyte tool output.
        if len(candidate) > 4_000_000 or not candidate.lstrip().startswith("{"):
            continue
        try:
            parsed = json.loads(candidate)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        envelope = as_mapping(parsed)
        if not envelope.get("evidenceHandle"):
            continue
        if not any(
            key in envelope
            for key in ("evidenceSummary", "previewHead", "evidenceRequest")
        ):
            continue
        return envelope
    return {}


def _public_tool_output_preview(
    raw_result: object,
    *,
    evidence: Mapping[str, object] | None = None,
) -> tuple[str, bool]:
    evidence = evidence or _public_tool_evidence_envelope(raw_result)
    if evidence:
        raw_summary = evidence.get("evidenceSummary") or evidence.get("previewHead")
        source = str(raw_summary or "")
        text = _public_tool_text(source, maximum=6_000)
        if text:
            lines = text.splitlines()
            preview = "\n".join(lines[:40])[:6_000]
            evidence_bytes = as_integer(evidence.get("evidenceBytes"))
            truncated = (
                len(source) > 6_000
                or len(lines) > 40
                or evidence_bytes > len(source.encode("utf-8"))
                or bool(evidence.get("continuation"))
            )
            return preview, truncated

    result = as_mapping(raw_result)
    content = result.get("content")
    chunks: list[str] = []
    source_truncated = False
    if isinstance(content, list):
        source_truncated = len(content) > 16
        for item in content[:16]:
            raw_text = as_mapping(item).get("text")
            if isinstance(raw_text, str) and len(raw_text) > 6_000:
                source_truncated = True
            text = _public_tool_text(raw_text, maximum=6_000)
            if text:
                chunks.append(text)
    if not chunks:
        for key in ("stdout", "output", "text"):
            raw_text = result.get(key)
            if isinstance(raw_text, str) and len(raw_text) > 6_000:
                source_truncated = True
            text = _public_tool_text(raw_text, maximum=6_000)
            if text:
                chunks.append(text)
                break
    if not chunks:
        return "", False
    joined = "\n".join(chunks)
    lines = joined.splitlines()
    truncated = source_truncated or len(joined) > 6_000 or len(lines) > 40
    preview = "\n".join(lines[:40])[:6_000]
    return preview, truncated


def public_pi_model(raw: Mapping[str, object]) -> dict[str, object]:
    provider = str(raw.get("provider") or "").strip()
    model_id = str(raw.get("id") or "").strip()
    if not provider or not model_id:
        return {}
    raw_inputs = raw.get("input")
    inputs = raw_inputs if isinstance(raw_inputs, list) else []
    return {
        "provider": provider[:80],
        "id": model_id[:160],
        "name": str(raw.get("name") or model_id).strip()[:160] or model_id[:160],
        "api": str(raw.get("api") or "").strip()[:80],
        "reasoning": bool(raw.get("reasoning")),
        "thinkingLevels": supported_thinking_levels(raw),
        "supportsImages": "image" in {str(item) for item in inputs},
        "contextWindow": as_integer(raw.get("contextWindow")),
        "maxTokens": as_integer(raw.get("maxTokens")),
    }


def redact_mapping(value: Mapping[str, object], *, depth: int = 0) -> dict[str, object]:
    if depth >= 4:
        return {"truncated": True}
    result: dict[str, object] = {}
    for raw_key, raw_value in list(value.items())[:64]:
        key = str(raw_key)[:120]
        if re.search(r"token|secret|password|api.?key|authorization|cookie", key, re.IGNORECASE):
            result[key] = "[REDACTED_SECRET]"
        elif isinstance(raw_value, Mapping):
            result[key] = redact_mapping(raw_value, depth=depth + 1)
        elif isinstance(raw_value, list):
            result[key] = [
                redact_mapping(item, depth=depth + 1) if isinstance(item, Mapping) else safe_scalar(item)
                for item in raw_value[:64]
            ]
        else:
            result[key] = safe_scalar(raw_value)
    return result


_MUTATION_BODY_ARGUMENT_KEYS = frozenset({
    "changes",
    "content",
    "diff",
    "edits",
    "newtext",
    "oldtext",
    "patch",
    "replacement",
    "replacementtext",
})


def public_code_tool_arguments(
    tool_name: object,
    value: Mapping[str, object],
) -> dict[str, object]:
    """Return the one bounded argument carrier used by public tool events.

    ``edit`` and ``write`` bodies can be large and may contain private source.
    Their public receipt is the separately bounded semantic result (line counts,
    target and managed Diff), so keeping mutation bodies in the generic args
    carrier would create a second rendering path and persist content before the
    tool finishes.  Internal workspace adapters are canonicalized before this
    boundary and receive the same treatment.
    """

    redacted = redact_mapping(value)
    if canonical_code_tool_name(tool_name) not in {"edit", "write"}:
        return redacted

    def strip_mutation_bodies(candidate: object) -> object:
        if isinstance(candidate, Mapping):
            return {
                str(key): strip_mutation_bodies(item)
                for key, item in candidate.items()
                if re.sub(r"[^a-z]", "", str(key).lower())
                not in _MUTATION_BODY_ARGUMENT_KEYS
            }
        if isinstance(candidate, list):
            return [strip_mutation_bodies(item) for item in candidate]
        return candidate

    return dict(strip_mutation_bodies(redacted))


def managed_media_content_url(session_id: str, media_id: str) -> str:
    return (
        f"/api/agent/media/{quote(str(media_id), safe='')}/content"
        f"?sessionId={quote(str(session_id), safe='')}"
    )


def pi_message_payload(
    raw: Mapping[str, object],
    *,
    session_id: str,
    turn_id: str,
    media_resolver: Callable[[str, str, str], str] | None = None,
    message_id: str | None = None,
    trusted_blocks: object = None,
) -> AgentMessage:
    role = str(raw.get("role") or "assistant")
    if role not in {"user", "assistant", "tool", "system"}:
        role = "tool" if role.lower().startswith("tool") else "assistant"
    content = raw.get("content")
    resolved_message_id = message_id or pi_message_id(raw, turn_id)
    fallback_blocks_enabled = trusted_blocks is None
    blocks: list[AgentBlock] = []
    blocks.extend(
        AgentBlock.from_payload(item)
        for item in normalize_trusted_agent_blocks(
            trusted_blocks,
            source_kind="pi_runtime_event",
            source_ref=f"{session_id}:{resolved_message_id}",
        )
    )
    attachments: list[str] = []
    if isinstance(content, str):
        visible_content = visible_message_text(role, content)
        extracted = (
            extract_completed_agent_blocks(
                visible_content,
                source_kind="pi_session_message",
                source_ref=f"{session_id}:{resolved_message_id}",
            )
            if role == "assistant"
            else None
        )
        if extracted is not None:
            visible_content = extracted.text
            if fallback_blocks_enabled:
                blocks.extend(AgentBlock.from_payload(item) for item in extracted.blocks)
        if visible_content:
            blocks.append(
                normalize_agent_block(
                    {
                        "id": f"{turn_id}:text:0",
                        "type": "text",
                        "status": "completed",
                        "presentationKind": "markdown",
                        "data": {"text": visible_content},
                    }
                )
            )
    elif isinstance(content, list):
        for index, item in enumerate(content):
            value = as_mapping(item)
            content_type = str(value.get("type") or "unknown")
            if content_type == "text":
                visible_content = visible_message_text(role, str(value.get("text") or ""))
                extracted = (
                    extract_completed_agent_blocks(
                        visible_content,
                        source_kind="pi_session_message",
                        source_ref=f"{session_id}:{resolved_message_id}",
                    )
                    if role == "assistant"
                    else None
                )
                if extracted is not None:
                    visible_content = extracted.text
                    if fallback_blocks_enabled:
                        blocks.extend(AgentBlock.from_payload(item) for item in extracted.blocks)
                if visible_content:
                    blocks.append(
                        normalize_agent_block(
                            {
                                "id": f"{turn_id}:text:{index}",
                                "type": "text",
                                "status": "completed",
                                "presentationKind": "markdown",
                                "data": {"text": visible_content},
                            }
                        )
                    )
            elif content_type == "image" and media_resolver is not None:
                media_id = media_resolver(
                    session_id,
                    str(value.get("mimeType") or ""),
                    str(value.get("data") or ""),
                )
                if media_id:
                    attachments.append(media_id)
                    receipt_url = managed_media_content_url(session_id, media_id)
                    blocks.append(
                        normalize_agent_block(
                            {
                                "id": f"{turn_id}:image:{index}",
                                "type": "image",
                                "status": "completed",
                                "presentationKind": "image",
                                "data": {
                                    "mediaId": media_id,
                                    "receiptUrl": receipt_url,
                                },
                            }
                        )
                    )
            elif content_type in {"thinking", "redacted_thinking"}:
                continue
            elif content_type in {"toolCall", "tool_call"}:
                # Tool lifecycle events own the public execution timeline.
                # Do not duplicate Pi protocol blocks or their arguments in
                # the human transcript message.
                continue
    error_message = redact_runtime_text(str(raw.get("errorMessage") or "").strip())
    failed = str(raw.get("stopReason") or "").lower() == "error" or bool(error_message)
    if failed:
        blocks.append(
            normalize_agent_block(
                {
                    "id": f"{turn_id}:error:0",
                    "type": "error",
                    "status": "failed",
                    "presentationKind": "error",
                    "data": {"message": error_message or "模型请求失败，请重试"},
                }
            )
        )
    if not blocks:
        blocks.append(
            normalize_agent_block(
                {
                    "id": f"{turn_id}:progress:0",
                    "type": "progress",
                    "status": "completed",
                    "presentationKind": "progress",
                    "data": {"label": "本轮没有可展示正文"},
                }
            )
        )
    created_at = as_integer(raw.get("timestamp")) or int(time.time() * 1000)
    return AgentMessage(
        message_id=resolved_message_id,
        session_id=session_id,
        turn_id=turn_id,
        role=role,
        status="failed" if failed else "completed",
        blocks=tuple(blocks),
        attachments=tuple(dict.fromkeys(attachments)),
        created_at_ms=created_at,
        completed_at_ms=created_at,
        provider=str(raw.get("provider") or "").strip()[:80],
        model=str(raw.get("responseModel") or raw.get("model") or "").strip()[:160],
        usage=public_usage(raw) if role == "assistant" else None,
    )
