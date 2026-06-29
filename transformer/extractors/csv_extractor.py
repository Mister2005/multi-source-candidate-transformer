import csv
import io
import logging
from pathlib import Path

from transformer.extractors.base import BaseExtractor
from transformer.models import SourceItem, RawRecord, ExperienceEntry

logger = logging.getLogger(__name__)

# Map of CSV column names → canonical fields (case-insensitive)
COLUMN_MAP = {
    "name": "full_name",
    "full_name": "full_name",
    "email": "emails",
    "email_address": "emails",
    "phone": "phones",
    "phone_number": "phones",
    "current_company": "company",
    "company": "company",
    "title": "title",
    "job_title": "title",
    "location": "location_raw",
    "city": "location_raw",
    "linkedin": "linkedin_url",
    "linkedin_url": "linkedin_url",
    "github": "github_url",
    "github_url": "github_url",
    "headline": "headline",
    "skills": "skills_raw",
}


class CSVExtractor(BaseExtractor):
    def extract(self, source: SourceItem) -> RawRecord:
        record = RawRecord(source_type="csv")
        try:
            raw = source.raw_content
            if isinstance(raw, Path) or (isinstance(raw, str) and Path(str(raw)).exists()):
                with open(raw, encoding="utf-8-sig", newline="") as f:
                    content = f.read()
            elif isinstance(raw, str):
                content = raw  # treat as raw CSV string
            else:
                content = str(raw)

            reader = csv.DictReader(io.StringIO(content))
            rows = list(reader)
            if not rows:
                logger.warning("CSV: no rows found")
                return record

            # Take first row (one candidate per run)
            row = rows[0]
            mapped: dict = {}
            for col, val in row.items():
                if not col:
                    continue
                key = COLUMN_MAP.get(col.strip().lower())
                if key and val and val.strip():
                    mapped[key] = val.strip()

            record.full_name = mapped.get("full_name")
            if "emails" in mapped:
                record.emails = [mapped["emails"]]
            if "phones" in mapped:
                record.phones = [mapped["phones"]]
            record.location_raw = mapped.get("location_raw")
            record.linkedin_url = mapped.get("linkedin_url")
            record.github_url = mapped.get("github_url")
            record.headline = mapped.get("headline")

            # Build a minimal experience entry from company + title
            company = mapped.get("company")
            title = mapped.get("title")
            if company or title:
                record.experience.append(ExperienceEntry(company=company, title=title))

            # Skills may be comma-separated in a single cell
            if "skills_raw" in mapped:
                record.skills_raw = [s.strip() for s in mapped["skills_raw"].split(",") if s.strip()]

        except Exception as e:
            logger.error("CSV extraction failed: %s", e)

        return record
