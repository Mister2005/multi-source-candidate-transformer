import logging
import phonenumbers

logger = logging.getLogger(__name__)


def normalize_phone(raw: str, default_region: str = "US") -> str | None:
    if not raw or not raw.strip():
        return None
    try:
        parsed = phonenumbers.parse(raw.strip(), default_region)
        if phonenumbers.is_valid_number(parsed):
            return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
        logger.warning("Phone number invalid (not logging value)")
        return None
    except phonenumbers.NumberParseException:
        logger.warning("Phone number could not be parsed (not logging value)")
        return None


def normalize_phones(raw_list: list[str]) -> list[str]:
    seen = set()
    result = []
    for raw in raw_list:
        normalized = normalize_phone(raw)
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result
