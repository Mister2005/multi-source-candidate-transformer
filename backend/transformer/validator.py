import logging
import jsonschema

logger = logging.getLogger(__name__)

# JSON Schema for the full canonical output
CANONICAL_SCHEMA = {
    "type": "object",
    "properties": {
        "candidate_id": {"type": "string"},
        "full_name": {"type": ["string", "null"]},
        "emails": {"type": "array", "items": {"type": "string"}},
        "phones": {"type": "array", "items": {"type": "string"}},
        "location": {"type": ["object", "null"]},
        "links": {"type": "object"},
        "headline": {"type": ["string", "null"]},
        "years_experience": {"type": ["number", "null"]},
        "skills": {"type": "array"},
        "experience": {"type": "array"},
        "education": {"type": "array"},
        "provenance": {"type": "array"},
        "overall_confidence": {"type": "number"},
    },
}


def validate(output: dict, config: dict | None = None) -> tuple[bool, list[str]]:
    """
    Validate the output dict against the canonical schema (or a config-derived schema).
    Returns (success, list_of_error_messages).
    """
    schema = _build_schema(config)
    errors = []
    try:
        jsonschema.validate(instance=output, schema=schema)
        return True, []
    except jsonschema.ValidationError as e:
        errors.append(f"Validation error at '{e.json_path}': {e.message}")
        return False, errors
    except jsonschema.SchemaError as e:
        errors.append(f"Schema error: {e.message}")
        return False, errors


def _build_schema(config: dict | None) -> dict:
    if not config or not config.get("fields"):
        return CANONICAL_SCHEMA

    # Build a schema from config's field list
    properties = {}
    required_fields = []

    for field_def in config.get("fields", []):
        key = field_def.get("path")
        if not key:
            continue
        ftype = field_def.get("type", "string")
        required = field_def.get("required", False)

        json_type = _map_type(ftype)
        properties[key] = json_type
        if required:
            required_fields.append(key)

    schema = {"type": "object", "properties": properties}
    if required_fields:
        schema["required"] = required_fields
    return schema


def _map_type(type_str: str) -> dict:
    mapping = {
        "string": {"type": ["string", "null"]},
        "string[]": {"type": ["array", "null"], "items": {"type": "string"}},
        "number": {"type": ["number", "null"]},
        "boolean": {"type": ["boolean", "null"]},
        "object": {"type": ["object", "null"]},
    }
    return mapping.get(type_str, {"type": ["string", "null"]})
