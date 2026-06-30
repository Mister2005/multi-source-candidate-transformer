import re
import logging

logger = logging.getLogger(__name__)

MONTH_MAP = {
    "jan": "01", "feb": "02", "mar": "03", "apr": "04",
    "may": "05", "jun": "06", "jul": "07", "aug": "08",
    "sep": "09", "oct": "10", "nov": "11", "dec": "12",
    "january": "01", "february": "02", "march": "03", "april": "04",
    "june": "06", "july": "07", "august": "08", "september": "09",
    "october": "10", "november": "11", "december": "12",
}

# Patterns: "Jan 2022", "January 2022", "2022-01", "01/2022", "2022"
_PATTERNS = [
    (re.compile(r"(\d{4})-(\d{2})"), lambda m: f"{m.group(1)}-{m.group(2)}"),
    (re.compile(r"(\d{2})/(\d{4})"), lambda m: f"{m.group(2)}-{m.group(1)}"),
    (re.compile(r"([A-Za-z]+)\s+(\d{4})"), lambda m: _month_year(m.group(1), m.group(2))),
    (re.compile(r"(\d{4})"), lambda m: f"{m.group(1)}-01"),
]


def _month_year(month_str: str, year: str) -> str | None:
    mm = MONTH_MAP.get(month_str.lower())
    if mm:
        return f"{year}-{mm}"
    return None


def normalize_date(raw: str) -> str | None:
    if not raw or not raw.strip():
        return None
    raw = raw.strip()
    if raw.lower() in ("present", "current", "now", "ongoing"):
        return None
    for pattern, formatter in _PATTERNS:
        m = pattern.fullmatch(raw) or pattern.search(raw)
        if m:
            result = formatter(m)
            if result:
                return result
    logger.debug("Could not parse date: %s", raw[:20])
    return None
