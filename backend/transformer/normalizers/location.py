import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).parent.parent.parent / "data"


def _load_country_codes() -> dict[str, str]:
    path = _DATA_DIR / "country_codes.json"
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


_COUNTRY_CODES: dict[str, str] = {}


def _get_codes() -> dict[str, str]:
    global _COUNTRY_CODES
    if not _COUNTRY_CODES:
        _COUNTRY_CODES = _load_country_codes()
    return _COUNTRY_CODES


def normalize_location(raw: str | None) -> dict | None:
    if not raw:
        return None
    raw = raw.strip()
    codes = _get_codes()

    parts = [p.strip() for p in raw.split(",")]
    result: dict = {}

    # Try to identify country from last or any part
    country_code = None
    for part in reversed(parts):
        key = part.strip().lower()
        # direct ISO-2 match
        if len(part.strip()) == 2 and part.strip().upper() in codes.values():
            country_code = part.strip().upper()
            break
        # name match
        for name, code in codes.items():
            if key == name.lower():
                country_code = code
                break
        if country_code:
            break

    # Assign city / region / country heuristically
    if len(parts) >= 3:
        result["city"] = parts[0]
        result["region"] = parts[1]
        result["country"] = country_code or parts[-1]
    elif len(parts) == 2:
        result["city"] = parts[0]
        result["region"] = None
        result["country"] = country_code or parts[-1]
    else:
        result["city"] = None
        result["region"] = None
        result["country"] = country_code or raw

    return result
