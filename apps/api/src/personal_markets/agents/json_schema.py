from typing import Any

from pydantic import BaseModel


def _enforce_object(schema: dict[str, Any], defs: dict[str, Any]) -> None:
    if "$ref" in schema:
        return
    if "anyOf" in schema:
        for item in schema["anyOf"]:
            if isinstance(item, dict):
                _walk(item, defs)
        return
    if "items" in schema and isinstance(schema["items"], dict):
        _walk(schema["items"], defs)
    if schema.get("type") != "object" and "properties" not in schema:
        return
    schema["type"] = "object"
    schema["additionalProperties"] = False
    properties = schema.setdefault("properties", {})
    required = set(schema.get("required", []))
    for name, child in properties.items():
        _walk(child, defs)
        required.add(name)
    schema["required"] = sorted(required)


def _walk(schema: dict[str, Any], defs: dict[str, Any]) -> None:
    if "$ref" in schema:
        return
    _enforce_object(schema, defs)
    if "items" in schema and isinstance(schema["items"], dict):
        _walk(schema["items"], defs)
    for key in ("anyOf", "oneOf"):
        if key in schema:
            for item in schema[key]:
                if isinstance(item, dict):
                    _walk(item, defs)


def strict_json_schema(model: type[BaseModel]) -> dict[str, Any]:
    schema = model.model_json_schema()
    defs = schema.get("$defs", {})
    for definition in defs.values():
        if isinstance(definition, dict):
            _enforce_object(definition, defs)
    _enforce_object(schema, defs)
    schema.pop("title", None)
    return schema
