from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from copy import deepcopy
from functools import lru_cache
from pathlib import Path


CONTRACTS_DIR = Path(__file__).with_name("json")
JsonSchema = Mapping[str, object] | bool


class ContractValidationError(ValueError):
    pass


def load_contract(name: str) -> dict[str, object]:
    return deepcopy(_load_contract_cached(CONTRACTS_DIR, name))


@lru_cache(maxsize=256)
def _load_contract_cached(contracts_dir: Path, name: str) -> dict[str, object]:
    path = contracts_dir / name
    if not path.is_file():
        raise ValueError(f"unknown JSON contract: {name}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON contract must contain an object: {name}")
    return payload


def validate_json_schema(
    schema: object,
    *,
    path: str = "schema",
    maximum_depth: int = 32,
    maximum_nodes: int = 512,
    allow_boolean_root: bool = True,
) -> JsonSchema:
    """Validate the JSON-Schema shape accepted by the local contract runtime."""

    nodes = [0]

    def visit(value: object, *, current_path: str, depth: int) -> None:
        if depth > maximum_depth:
            raise ValueError(f"{current_path} exceeds the maximum schema depth")
        nodes[0] += 1
        if nodes[0] > maximum_nodes:
            raise ValueError(f"{path} contains too many schema nodes")
        if isinstance(value, bool):
            return
        if not isinstance(value, Mapping):
            raise ValueError(f"{current_path} must be a JSON Schema object or boolean")

        reference = value.get("$ref")
        if reference is not None and not isinstance(reference, str):
            raise ValueError(f"{current_path}.$ref must be a string")
        declared_type = value.get("type")
        schema_types = {
            "null", "boolean", "object", "array", "number", "integer", "string",
        }
        if declared_type is not None:
            if isinstance(declared_type, str):
                declared_types = [declared_type]
            elif (
                isinstance(declared_type, list)
                and declared_type
                and all(isinstance(item, str) for item in declared_type)
            ):
                declared_types = declared_type
            else:
                raise ValueError(f"{current_path}.type must be a string or string array")
            if any(item not in schema_types for item in declared_types):
                raise ValueError(f"{current_path}.type contains an unsupported JSON type")

        for keyword in ("properties", "patternProperties", "$defs", "dependentSchemas"):
            children = value.get(keyword)
            if children is None:
                continue
            if not isinstance(children, Mapping):
                raise ValueError(f"{current_path}.{keyword} must be an object")
            for key, child in children.items():
                visit(
                    child,
                    current_path=f"{current_path}.{keyword}.{key}",
                    depth=depth + 1,
                )

        for keyword in (
            "items", "additionalProperties", "contains", "not", "if", "then", "else",
            "propertyNames",
        ):
            child = value.get(keyword)
            if child is not None:
                visit(
                    child,
                    current_path=f"{current_path}.{keyword}",
                    depth=depth + 1,
                )

        for keyword in ("allOf", "anyOf", "oneOf", "prefixItems"):
            children = value.get(keyword)
            if children is None:
                continue
            if not isinstance(children, list) or not children:
                raise ValueError(f"{current_path}.{keyword} must be a non-empty schema array")
            for index, child in enumerate(children):
                visit(
                    child,
                    current_path=f"{current_path}.{keyword}[{index}]",
                    depth=depth + 1,
                )

        for unsupported in ("unevaluatedProperties", "unevaluatedItems"):
            if unsupported in value:
                raise ValueError(f"{current_path}.{unsupported} is not supported")

    if isinstance(schema, bool) and not allow_boolean_root:
        raise ValueError(f"{path} must be a JSON Schema object")
    visit(schema, current_path=path, depth=0)
    return schema if isinstance(schema, bool) else dict(schema)


def validate_contract(payload: object, contract: str | JsonSchema) -> None:
    schema = (
        _validated_contract_cached(CONTRACTS_DIR, contract)
        if isinstance(contract, str)
        else validate_json_schema(contract)
    )
    errors: list[str] = []
    _validate(payload, schema, root=schema, path="$", errors=errors)
    if errors:
        raise ContractValidationError("; ".join(errors[:8]))


@lru_cache(maxsize=256)
def _validated_contract_cached(contracts_dir: Path, name: str) -> JsonSchema:
    return validate_json_schema(_load_contract_cached(contracts_dir, name))


def clear_contract_cache() -> None:
    """Forget named contract resources after a deliberate on-disk replacement."""

    _validated_contract_cached.cache_clear()
    _load_contract_cached.cache_clear()


def _validate(
    value: object,
    schema: JsonSchema,
    *,
    root: JsonSchema,
    path: str,
    errors: list[str],
) -> None:
    if schema is True:
        return
    if schema is False:
        errors.append(f"{path}: matches a forbidden schema")
        return

    reference = schema.get("$ref")
    if isinstance(reference, str):
        target = _resolve_reference(reference, root)
        _validate(value, target, root=root, path=path, errors=errors)
        return

    all_of = schema.get("allOf")
    if isinstance(all_of, list):
        for candidate in all_of:
            if isinstance(candidate, (Mapping, bool)):
                _validate(
                    value,
                    candidate,
                    root=root,
                    path=path,
                    errors=errors,
                )

    any_of = schema.get("anyOf")
    if isinstance(any_of, list):
        matching = [
            candidate
            for candidate in any_of
            if isinstance(candidate, (Mapping, bool))
            and _schema_matches(value, candidate, root=root, path=path)
        ]
        if not matching:
            errors.append(f"{path}: does not match any allowed schema")

    one_of = schema.get("oneOf")
    if isinstance(one_of, list):
        match_count = sum(
            1
            for candidate in one_of
            if isinstance(candidate, (Mapping, bool))
            and _schema_matches(value, candidate, root=root, path=path)
        )
        if match_count != 1:
            errors.append(
                f"{path}: expected exactly one allowed schema, matched {match_count}"
            )

    excluded = schema.get("not")
    if (
        isinstance(excluded, (Mapping, bool))
        and _schema_matches(value, excluded, root=root, path=path)
    ):
        errors.append(f"{path}: matches a forbidden schema")

    condition = schema.get("if")
    if isinstance(condition, (Mapping, bool)):
        branch = (
            schema.get("then")
            if _schema_matches(value, condition, root=root, path=path)
            else schema.get("else")
        )
        if isinstance(branch, (Mapping, bool)):
            _validate(
                value,
                branch,
                root=root,
                path=path,
                errors=errors,
            )

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
        maximum_length = schema.get("maxLength")
        if isinstance(maximum_length, int) and len(value) > maximum_length:
            errors.append(f"{path}: string is longer than {maximum_length}")
        pattern = schema.get("pattern")
        if isinstance(pattern, str) and re.search(pattern, value) is None:
            errors.append(f"{path}: string does not match required pattern")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        minimum = schema.get("minimum")
        if isinstance(minimum, (int, float)) and value < minimum:
            errors.append(f"{path}: value is below {minimum}")
        maximum = schema.get("maximum")
        if isinstance(maximum, (int, float)) and value > maximum:
            errors.append(f"{path}: value is above {maximum}")
    if isinstance(value, Mapping):
        required = schema.get("required")
        if isinstance(required, list):
            for key in required:
                if isinstance(key, str) and key not in value:
                    errors.append(f"{path}: missing required field {key}")
        properties = schema.get("properties")
        pattern_properties = schema.get("patternProperties")
        if isinstance(properties, Mapping):
            additional = schema.get("additionalProperties")
            for key in value:
                pattern_schemas = [
                    candidate
                    for pattern, candidate in pattern_properties.items()
                    if isinstance(pattern_properties, Mapping)
                    and isinstance(pattern, str)
                    and re.search(pattern, str(key)) is not None
                ] if isinstance(pattern_properties, Mapping) else []
                if key in properties or pattern_schemas:
                    for candidate in pattern_schemas:
                        if isinstance(candidate, (Mapping, bool)):
                            _validate(
                                value[key], candidate, root=root,
                                path=f"{path}.{key}", errors=errors,
                            )
                    continue
                if additional is False:
                    errors.append(f"{path}: unsupported field {key}")
                elif isinstance(additional, (Mapping, bool)):
                    _validate(
                        value[key],
                        additional,
                        root=root,
                        path=f"{path}.{key}",
                        errors=errors,
                    )
            for key, child_schema in properties.items():
                if key in value and isinstance(child_schema, (Mapping, bool)):
                    _validate(
                        value[key],
                        child_schema,
                        root=root,
                        path=f"{path}.{key}",
                        errors=errors,
                    )
        elif isinstance(pattern_properties, Mapping):
            additional = schema.get("additionalProperties")
            for key in value:
                matches = [
                    child for pattern, child in pattern_properties.items()
                    if isinstance(pattern, str) and re.search(pattern, str(key)) is not None
                ]
                if matches:
                    for child in matches:
                        if isinstance(child, (Mapping, bool)):
                            _validate(value[key], child, root=root, path=f"{path}.{key}", errors=errors)
                elif additional is False:
                    errors.append(f"{path}: unsupported field {key}")
                elif isinstance(additional, (Mapping, bool)):
                    _validate(value[key], additional, root=root, path=f"{path}.{key}", errors=errors)
        elif schema.get("additionalProperties") is False and value:
            for key in value:
                errors.append(f"{path}: unsupported field {key}")
        dependent_schemas = schema.get("dependentSchemas")
        if isinstance(dependent_schemas, Mapping):
            for key, child in dependent_schemas.items():
                if key in value and isinstance(child, (Mapping, bool)):
                    _validate(value, child, root=root, path=path, errors=errors)
        property_names = schema.get("propertyNames")
        if isinstance(property_names, (Mapping, bool)):
            for key in value:
                _validate(str(key), property_names, root=root, path=f"{path}.{key}", errors=errors)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        minimum_items = schema.get("minItems")
        if isinstance(minimum_items, int) and len(value) < minimum_items:
            errors.append(f"{path}: array has fewer than {minimum_items} items")
        maximum_items = schema.get("maxItems")
        if isinstance(maximum_items, int) and len(value) > maximum_items:
            errors.append(f"{path}: array has more than {maximum_items} items")
        if schema.get("uniqueItems") is True:
            identities = [_json_identity(item) for item in value]
            if len(identities) != len(set(identities)):
                errors.append(f"{path}: array items must be unique")
        prefix_items = schema.get("prefixItems")
        prefix_count = len(prefix_items) if isinstance(prefix_items, list) else 0
        if isinstance(prefix_items, list):
            for index, child_schema in enumerate(prefix_items[:len(value)]):
                if isinstance(child_schema, (Mapping, bool)):
                    _validate(
                        value[index], child_schema, root=root,
                        path=f"{path}[{index}]", errors=errors,
                    )
        items = schema.get("items")
        if isinstance(items, (Mapping, bool)):
            for index, item in enumerate(value[prefix_count:], start=prefix_count):
                _validate(
                    item,
                    items,
                    root=root,
                    path=f"{path}[{index}]",
                    errors=errors,
                )
        contains = schema.get("contains")
        if isinstance(contains, (Mapping, bool)):
            matches = sum(
                1 for index, item in enumerate(value)
                if _schema_matches(item, contains, root=root, path=f"{path}[{index}]")
            )
            minimum_contains = schema.get("minContains", 1)
            maximum_contains = schema.get("maxContains")
            if isinstance(minimum_contains, int) and matches < minimum_contains:
                errors.append(f"{path}: array has fewer than {minimum_contains} matching items")
            if isinstance(maximum_contains, int) and matches > maximum_contains:
                errors.append(f"{path}: array has more than {maximum_contains} matching items")


def _schema_matches(
    value: object,
    schema: JsonSchema,
    *,
    root: JsonSchema,
    path: str,
) -> bool:
    candidate_errors: list[str] = []
    _validate(
        value,
        schema,
        root=root,
        path=path,
        errors=candidate_errors,
    )
    return not candidate_errors


def _json_identity(value: object) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError):
        return repr(value)


def _resolve_reference(reference: str, root: JsonSchema) -> JsonSchema:
    if not reference.startswith("#/"):
        raise ValueError(f"only local JSON references are supported: {reference}")
    value: object = root
    for part in reference[2:].split("/"):
        key = part.replace("~1", "/").replace("~0", "~")
        if not isinstance(value, Mapping) or key not in value:
            raise ValueError(f"invalid JSON contract reference: {reference}")
        value = value[key]
    if not isinstance(value, (Mapping, bool)):
        raise ValueError(f"JSON contract reference is not a schema: {reference}")
    return value if isinstance(value, bool) else dict(value)


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
