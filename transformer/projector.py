import logging
import re
from transformer.models import CanonicalRecord
from transformer.normalizers.phone import normalize_phone
from transformer.normalizers.skill import canonicalize_skill

logger = logging.getLogger(__name__)


def _resolve_path(record: CanonicalRecord, path: str):
    """
    Resolve a dot-notation path with optional array index against the canonical record.
    Examples: "full_name", "emails[0]", "skills[].name", "location.country"
    """
    data = record.model_dump()

    # Handle array-flatten pattern like "skills[].name"
    flatten_match = re.match(r"^(\w+)\[\]\.(\w+)$", path)
    if flatten_match:
        arr_key = flatten_match.group(1)
        sub_key = flatten_match.group(2)
        arr = data.get(arr_key, []) or []
        return [item.get(sub_key) for item in arr if isinstance(item, dict) and item.get(sub_key) is not None]

    # Handle array index pattern like "emails[0]"
    index_match = re.match(r"^(\w+)\[(\d+)\]$", path)
    if index_match:
        key = index_match.group(1)
        idx = int(index_match.group(2))
        arr = data.get(key, []) or []
        return arr[idx] if idx < len(arr) else None

    # Handle dot-notation like "location.country"
    parts = path.split(".")
    obj = data
    for part in parts:
        if isinstance(obj, dict):
            obj = obj.get(part)
        else:
            return None
    return obj


def _apply_normalize(val, normalize: str | None):
    if not normalize or val is None:
        return val
    norm = normalize.lower()
    if norm == "e164":
        if isinstance(val, list):
            return [normalize_phone(str(v)) for v in val if v]
        return normalize_phone(str(val))
    if norm == "canonical":
        if isinstance(val, list):
            return [canonicalize_skill(str(v)) for v in val if v]
        return canonicalize_skill(str(val))
    if norm == "lowercase":
        if isinstance(val, list):
            return [str(v).lower() for v in val]
        return str(val).lower()
    return val


class ProjectionError(Exception):
    """Raised internally; caught by pipeline and returned as structured error."""
    def __init__(self, field: str, path: str):
        self.field = field
        self.path = path
        super().__init__(f"Field '{field}' (from '{path}') is required but resolved to null/empty")


def project(record: CanonicalRecord, config: dict) -> tuple[dict, list[str]]:
    """
    Apply the output config to produce a projected output dict.
    Returns (result_dict, projection_errors).
    projection_errors is non-empty only when on_missing='error' and a required field is absent.
    """
    fields = config.get("fields", [])
    include_confidence = config.get("include_confidence", True)
    on_missing = config.get("on_missing", "null")
    projection_errors: list[str] = []

    if not fields:
        # No fields specified → return full canonical record
        out = record.model_dump()
        if not include_confidence:
            out.pop("overall_confidence", None)
            out.pop("provenance", None)
            for skill in out.get("skills", []):
                skill.pop("confidence", None)
                skill.pop("sources", None)
        return out, []

    result = {}

    for field_def in fields:
        output_key = field_def.get("path")
        source_path = field_def.get("from", output_key)
        normalize = field_def.get("normalize")

        if not output_key:
            continue

        val = _resolve_path(record, source_path)
        val = _apply_normalize(val, normalize)

        is_empty = val is None or val == [] or val == ""
        if is_empty:
            if on_missing == "omit":
                continue
            elif on_missing == "error":
                # Structured error — do NOT raise; collect and let pipeline surface it
                msg = f"Field '{output_key}' (from '{source_path}') is required but resolved to null/empty"
                projection_errors.append(msg)
                logger.error("Projection error: %s", msg)
                result[output_key] = None  # still include with null so output is complete
            else:  # "null" (default)
                result[output_key] = None
        else:
            result[output_key] = val

    if include_confidence:
        result["_confidence"] = record.overall_confidence
        result["_provenance"] = [p.model_dump() for p in record.provenance]

    return result, projection_errors
