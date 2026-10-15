"""Минимальный валидатор схем параметров операций (подмножество JSON Schema) — общий для шлюза агентов и слоя операций.

Поддержано: object (properties / required / additionalProperties=false), string (enum, pattern, minLength, maxLength),
integer (minimum, maximum; bool не считается числом), boolean, array (items, minItems, maxItems). Лишние поля запрещены.
`validate()` возвращает текст первой ошибки или None — исключений не бросает.
"""
import re

DEFAULT_MAX_STRING = 200
DEFAULT_MAX_ITEMS = 50


def validate(schema, value, path="params"):
    t = schema.get("type")
    if t == "object":
        if not isinstance(value, dict):
            return f"{path} must be an object"
        props = schema.get("properties", {})
        free = schema.get("additionalProperties") is True  # свободный объект: внутренние поля проверяет вызывающий слой
        for k in value:
            if k not in props and not free:
                return f"unknown parameter '{k}'"
        for k in schema.get("required", []):
            if k not in value:
                return f"missing parameter '{k}'"
        for k, v in value.items():
            if k not in props:
                continue
            err = validate(props[k], v, f"parameter '{k}'")
            if err:
                return err
        return None
    if t == "string":
        if not isinstance(value, str):
            return f"{path} must be a string"
        if len(value) > schema.get("maxLength", DEFAULT_MAX_STRING):
            return f"{path} is longer than {schema.get('maxLength', DEFAULT_MAX_STRING)} characters"
        if len(value) < schema.get("minLength", 0):
            return f"{path} is shorter than {schema['minLength']} characters"
        if "enum" in schema and value not in schema["enum"]:
            return f"{path} must be one of {schema['enum']}"
        if "pattern" in schema and not re.fullmatch(schema["pattern"], value):
            return f"{path} has an invalid format"
        return None
    if t == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            return f"{path} must be an integer"
        if "minimum" in schema and value < schema["minimum"]:
            return f"{path} must be at least {schema['minimum']}"
        if "maximum" in schema and value > schema["maximum"]:
            return f"{path} must be at most {schema['maximum']}"
        return None
    if t == "boolean":
        return None if isinstance(value, bool) else f"{path} must be a boolean"
    if t == "array":
        if not isinstance(value, list):
            return f"{path} must be an array"
        if len(value) > schema.get("maxItems", DEFAULT_MAX_ITEMS):
            return f"{path} has more than {schema.get('maxItems', DEFAULT_MAX_ITEMS)} items"
        if len(value) < schema.get("minItems", 0):
            return f"{path} needs at least {schema['minItems']} items"
        for i, item in enumerate(value):
            err = validate(schema.get("items", {}), item, f"{path}[{i}]")
            if err:
                return err
        return None
    return None  # схема без типа — ограничений нет


def obj(properties=None, required=()):
    """Короткая запись схемы-объекта."""
    return {"type": "object", "properties": properties or {}, "required": list(required), "additionalProperties": False}
