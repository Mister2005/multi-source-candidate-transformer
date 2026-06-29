import re
import logging

logger = logging.getLogger(__name__)

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}", re.IGNORECASE)


def normalize_email(raw: str) -> str | None:
    if not raw or not raw.strip():
        return None
    cleaned = raw.strip().lower()
    if EMAIL_RE.fullmatch(cleaned):
        return cleaned
    logger.warning("Email failed validation (not logging value)")
    return None


def normalize_emails(raw_list: list[str]) -> list[str]:
    seen = set()
    result = []
    for raw in raw_list:
        normalized = normalize_email(raw)
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


def extract_emails_from_text(text: str) -> list[str]:
    found = EMAIL_RE.findall(text)
    return normalize_emails(found)
