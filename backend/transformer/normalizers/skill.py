import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).parent.parent.parent / "data"


def _load_synonyms() -> dict[str, str]:
    path = _DATA_DIR / "skill_synonyms.json"
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


_SYNONYMS: dict[str, str] = {}


def _get_synonyms() -> dict[str, str]:
    global _SYNONYMS
    if not _SYNONYMS:
        _SYNONYMS = _load_synonyms()
    return _SYNONYMS


def canonicalize_skill(raw: str) -> str:
    if not raw:
        return raw
    synonyms = _get_synonyms()
    key = raw.strip().lower()
    return synonyms.get(key, raw.strip().title())


def canonicalize_skills(raw_list: list[str]) -> list[str]:
    seen = set()
    result = []
    for raw in raw_list:
        canonical = canonicalize_skill(raw)
        if canonical and canonical not in seen:
            seen.add(canonical)
            result.append(canonical)
    return result
