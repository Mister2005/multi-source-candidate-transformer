import logging
from pathlib import Path

from transformer.extractors.base import BaseExtractor
from transformer.extractors.resume_extractor import (
    _extract_name_heuristic,
    _extract_skills_from_text,
    PHONE_RE,
    LINKEDIN_RE,
    GITHUB_RE,
)
from transformer.models import SourceItem, RawRecord
from transformer.normalizers.email import extract_emails_from_text

logger = logging.getLogger(__name__)


class TxtExtractor(BaseExtractor):
    def extract(self, source: SourceItem) -> RawRecord:
        record = RawRecord(source_type="recruiter_txt")
        try:
            raw = source.raw_content
            if isinstance(raw, (str, Path)) and Path(str(raw)).exists():
                with open(str(raw), encoding="utf-8") as f:
                    text = f.read()
            else:
                text = str(raw)

            if not text.strip():
                return record

            lines = text.split("\n")

            record.full_name = _extract_name_heuristic(lines)
            record.emails = extract_emails_from_text(text)

            phone_candidates = PHONE_RE.findall(text)
            record.phones = [p.strip() for p in phone_candidates if len(p.strip()) >= 7][:5]

            for m in LINKEDIN_RE.finditer(text):
                record.linkedin_url = f"https://linkedin.com/in/{m.group(1)}"
                break
            for m in GITHUB_RE.finditer(text):
                uname = m.group(1)
                if uname.lower() not in ("com", "orgs", "topics", "trending"):
                    record.github_url = f"https://github.com/{uname}"
                    break

            record.skills_raw = _extract_skills_from_text(text)

        except Exception as e:
            logger.error("TXT extraction failed: %s", e)

        return record
