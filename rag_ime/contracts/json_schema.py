from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path


CONTRACTS_DIR = Path(__file__).with_name("json")


class ContractValidationError(ValueError):
    pass


def load_contract(name: str) -> dict[str, object]:
    path = CONTRACTS_DIR / name
    if not path.is_file():
        raise ValueError(f"unknown JSON contract: {name}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON contract must contain an object: {name}")
    return payload


def validate_contract(payload: object, contract: str | Mapping[str, object]) -> None:
    schema = load_contract(contract) if isinstance(contract, str) else dict(contract)
    errors: list[str] = []
    _validate(payload, schema, root=schema, path="$", errors=errors)
    if errors:
        raise ContractValidationError("; ".join(errors[:8]))


def _validate(
    value: object,
    schema: Mapping[str, object],
    *,
    root: Mapping[str, object],
    path: str,
    errors: list[str],
) -> None:
    reference = schema.get("$ref")
    if isinstance(reference, str):
        target = _resolve_reference(reference, root)
        _validate(value, target, root=root, path=path, errors=errors)
        return
    expected_type = schema.get("type")
    if isinstance(expected_type, list):
        if not any(_matches_type(value, item) for item in expected_type):
            errors.append(f"{path}: expected one of {expected_type}")
            return
    elif isinstance(expected_type, str) and not _matches_type(value, expected_type):
        errors.append(f"{path}: expected {expected_type}")
        return
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: expected constant {schema['const']!r}")
    enum = schema.get("enum")
    if isinstance(enum, list) and value not in enum:
        errors.append(f"{path}: unsupported value {value!r}")
    if isinstance(value, str):
        minimum_length = schema.get("minLength")
        if isinstance(minimum_length, int) and len(value) < minimum_length:
            errors.append(f"{path}: string is shorter than {minimum_length}")
        pattern = schema.get("pattern")
        if isinstance(pattern, str) and re.search(pattern, value) is None:
            errors.append(f"{path}: string does not match required pattern")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        minimum = schema.get("minimum")
        if isinstance(minimum, (int, float)) and value < minimum:
            errors.append(f"{path}: value is below {minimum}")
    if isinstance(value, Mapping):
        required = schema.get("required")
        if isinstance(required, list):
            for key in required:
                if isinstance(key, str) and key not in value:
                    errors.append(f"{path}: missing required field {key}")
        properties = schema.get("properties")
        if isinstance(properties, Mapping):
            if schema.get("additionalProperties") is False:
                for key in value:
                    if key not in properties:
                        errors.append(f"{path}: unsupported field {key}")
            for key, child_schema in properties.items():
                if key in value and isinstance(child_schema, Mapping):
                    _validate(value[key], child_schema, root=root, path=f"{path}.{key}", errors=errors)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        items = schema.get("items")
        if isinstance(items, Mapping):
            for index, item in enumerate(value):
                _validate(item, items, root=root, path=f"{path}[{index}]", errors=errors)


def _resolve_reference(reference: str, root: Mapping[str, object]) -> Mapping[str, object]:
    if not reference.startswith("#/"):
        raise ValueError(f"only local JSON references are supported: {reference}")
    value: object = root
    for part in reference[2:].split("/"):
        key = part.replace("~1", "/").replace("~0", "~")
        if not isinstance(value, Mapping) or key not in value:
            raise ValueError(f"invalid JSON contract reference: {reference}")
        value = value[key]
    if not isinstance(value, Mapping):
        raise ValueError(f"JSON contract reference is not an object: {reference}")
    return value


def _matches_type(value: object, expected: object) -> bool:
    return {
        "object": isinstance(value, Mapping),
        "array": isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)),
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "null": value is None,
    }.get(str(expected), True)
