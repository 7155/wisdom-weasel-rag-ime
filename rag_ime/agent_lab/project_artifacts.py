"""Business-agnostic presentation contracts for Agent-authored Lab artifacts.

Only rendering primitives are fixed. Field names, columns, domain meanings and
the choice of presentation belong to each artifact and its optional Skill
template. HTML is data for an isolated renderer, never server-executed code.
"""
from __future__ import annotations

import copy
import json
from typing import Any

MAX_ARTIFACT_BYTES = 500_000
VIEWS = {"markdown", "table", "form", "code", "html", "json"}
_FIELD_TYPES = {"text", "long_text", "number", "boolean", "select", "multiselect"}


def _text(value: Any, label: str, maximum: int = 240, *, empty: bool = False) -> str:
    if not isinstance(value, str) or len(value) > maximum or (not empty and not value.strip()):
        raise ValueError(f"{label}无效。")
    return value


def _object(value: Any, fields: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) - fields:
        raise ValueError(f"{label}字段无效。")
    return value


def _list(value: Any, label: str, maximum: int, *, nonempty: bool = True) -> list[Any]:
    if not isinstance(value, list) or len(value) > maximum or (nonempty and not value):
        raise ValueError(f"{label}需要有效列表。")
    return value


def _unique_keys(items: list[dict[str, Any]]) -> None:
    if len({item["key"] for item in items}) != len(items):
        raise ValueError("字段标识不能重复。")


def validate_content(view: str, content: Any) -> Any:
    if view not in VIEWS:
        raise ValueError("成果展示类型尚未支持。")
    try:
        size = len(json.dumps(content, ensure_ascii=False, allow_nan=False).encode("utf-8"))
    except (ValueError, TypeError) as exc:
        raise ValueError("成果内容需要有效 JSON。") from exc
    if size > MAX_ARTIFACT_BYTES:
        raise ValueError("单份成果超过 500 KB，请拆分为关联成果或文件。")
    if view in {"markdown", "html"}:
        _text(content, "成果正文", MAX_ARTIFACT_BYTES, empty=True)
    elif view == "code":
        _object(content, {"language", "source", "filename"}, "代码成果")
        _text(content.get("language", "text"), "代码语言", 80)
        _text(content.get("source"), "代码正文", MAX_ARTIFACT_BYTES, empty=True)
        if "filename" in content:
            _text(content["filename"], "文件名", 500)
    elif view == "table":
        _object(content, {"columns", "rows", "caption"}, "数据表")
        columns = _list(content.get("columns"), "表格列", 80)
        for column in columns:
            _object(column, {"key", "label"}, "表格列")
            _text(column.get("key"), "列标识")
            _text(column.get("label"), "列标题", 500)
        _unique_keys(columns)
        keys = {item["key"] for item in columns}
        for row in _list(content.get("rows"), "表格行", 2000, nonempty=False):
            if not isinstance(row, dict) or set(row) - keys:
                raise ValueError("表格行必须引用已声明的列。")
        if "caption" in content:
            _text(content["caption"], "表格说明", 5000, empty=True)
    elif view == "form":
        _object(content, {"fields", "values", "description"}, "项目输入")
        fields = _list(content.get("fields"), "项目输入字段", 80)
        for field in fields:
            _object(field, {"key", "label", "type", "required", "options", "description", "placeholder"}, "输入字段")
            _text(field.get("key"), "字段标识")
            _text(field.get("label"), "字段名称", 500)
            if not isinstance(field.get("type"), str) or field["type"] not in _FIELD_TYPES:
                raise ValueError("不支持此输入类型。")
            if "required" in field and not isinstance(field["required"], bool):
                raise ValueError("必填设置需要是或否。")
            for key in ("description", "placeholder"):
                if key in field:
                    _text(field[key], "字段说明", 5000, empty=True)
            if field["type"] in {"select", "multiselect"}:
                options = _list(field.get("options"), "可选项", 100)
                for option in options:
                    _text(option, "选项", 500)
                if len(set(options)) != len(options):
                    raise ValueError("选项不能重复。")
            elif "options" in field:
                raise ValueError("只有选择字段可以提供选项。")
        _unique_keys(fields)
        if "description" in content:
            _text(content["description"], "输入说明", 10_000, empty=True)
        validate_form_values(content, content.get("values", {}), require_complete=False)
    return copy.deepcopy(content)


def validate_form_values(content: dict[str, Any], values: Any, *, require_complete: bool) -> dict[str, Any]:
    if not isinstance(values, dict):
        raise ValueError("项目输入需要 JSON 对象。")
    fields = {field["key"]: field for field in content["fields"]}
    if set(values) - fields.keys():
        raise ValueError("输入包含当前成果未声明的字段。")
    for key, field in fields.items():
        value = values.get(key)
        if value is None or value == "" or value == []:
            if require_complete and field.get("required"):
                raise ValueError(f'请填写“{field["label"]}”。')
            continue
        kind = field["type"]
        if kind in {"text", "long_text"}:
            _text(value, "字段内容", 50_000, empty=True)
        elif kind == "number":
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise ValueError(f'“{field["label"]}”需要数字。')
        elif kind == "boolean" and not isinstance(value, bool):
            raise ValueError(f'“{field["label"]}”需要是或否。')
        elif kind == "select" and value not in field["options"]:
            raise ValueError(f'“{field["label"]}”需要选择现有选项。')
        elif kind == "multiselect":
            if not isinstance(value, list) or any(not isinstance(item, str) or item not in field["options"] for item in value) or len(value) != len(set(value)):
                raise ValueError(f'“{field["label"]}”需要选择现有选项。')
    return copy.deepcopy(values)


def validate_artifact(value: dict[str, Any]) -> dict[str, Any]:
    _object(value, {"title", "kind", "view", "content", "templateRef", "actions", "summary"}, "项目成果")
    view = _text(value.get("view"), "展示类型", 80)
    result = {"title": _text(value.get("title"), "成果标题", 500),
              "kind": _text(value.get("kind", "artifact"), "成果类型", 240), "view": view,
              "content": validate_content(view, value.get("content")),
              "summary": _text(value.get("summary", ""), "成果摘要", 5000, empty=True),
              "templateRef": None, "actions": []}
    template = value.get("templateRef")
    if template is not None:
        _object(template, {"skillId", "templateId", "version"}, "模板引用")
        result["templateRef"] = {key: _text(template.get(key), "模板来源") for key in ("skillId", "templateId", "version")}
    seen = set()
    for action in _list(value.get("actions", []), "成果操作", 20, nonempty=False):
        _object(action, {"actionId", "label", "prompt"}, "成果操作")
        item = {key: _text(action.get(key), "操作内容", 5000 if key == "prompt" else 240) for key in ("actionId", "label", "prompt")}
        if item["actionId"] in seen:
            raise ValueError("成果操作标识不能重复。")
        seen.add(item["actionId"])
        result["actions"].append(item)
    return result
