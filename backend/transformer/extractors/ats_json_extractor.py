import json
import logging
from pathlib import Path

from transformer.extractors.base import BaseExtractor
from transformer.models import SourceItem, RawRecord, ExperienceEntry, EducationEntry

logger = logging.getLogger(__name__)

# Default field map: ATS field name → canonical destination
DEFAULT_FIELD_MAP = {
    # Name variants
    "firstName": "first_name",
    "lastName": "last_name",
    "fullName": "full_name",
    "name": "full_name",
    "candidateName": "full_name",
    # Email
    "email": "emails",
    "emailAddress": "emails",
    "email_address": "emails",
    # Phone
    "phone": "phones",
    "phoneNumber": "phones",
    "mobile": "phones",
    # Location
    "location": "location_raw",
    "address": "location_raw",
    "city": "location_raw",
    # Links
    "linkedinUrl": "linkedin_url",
    "linkedin": "linkedin_url",
    "githubUrl": "github_url",
    "github": "github_url",
    # Headline / title
    "headline": "headline",
    "currentTitle": "headline",
    "jobTitle": "headline",
    # Skills
    "skills": "skills_raw",
    "skillSet": "skills_raw",
    # Experience
    "experience": "experience",
    "workHistory": "experience",
    # Education
    "education": "education",
}


def _get_nested(obj: dict, *keys: str):
    for key in keys:
        if isinstance(obj, dict):
            obj = obj.get(key)
        else:
            return None
    return obj


class ATSJsonExtractor(BaseExtractor):
    def __init__(self, field_map: dict | None = None):
        self.field_map = {**DEFAULT_FIELD_MAP, **(field_map or {})}

    def extract(self, source: SourceItem) -> RawRecord:
        record = RawRecord(source_type="ats_json")
        try:
            raw = source.raw_content
            if isinstance(raw, (str, Path)):
                with open(raw, encoding="utf-8") as f:
                    data = json.load(f)
            elif isinstance(raw, dict):
                data = raw
            else:
                data = json.loads(raw)

            mapped: dict = {}
            for ats_key, canonical_key in self.field_map.items():
                val = data.get(ats_key)
                if val is not None:
                    mapped[canonical_key] = val

            # Compose full_name from parts if needed
            if "full_name" not in mapped:
                first = mapped.pop("first_name", "") or ""
                last = mapped.pop("last_name", "") or ""
                if first or last:
                    mapped["full_name"] = f"{first} {last}".strip()

            record.full_name = mapped.get("full_name")
            record.location_raw = mapped.get("location_raw")
            record.linkedin_url = mapped.get("linkedin_url")
            record.github_url = mapped.get("github_url")
            record.headline = mapped.get("headline")

            # Emails — could be string or list
            emails_raw = mapped.get("emails")
            if isinstance(emails_raw, list):
                record.emails = [str(e) for e in emails_raw if e]
            elif isinstance(emails_raw, str) and emails_raw:
                record.emails = [emails_raw]

            # Phones — could be string or list
            phones_raw = mapped.get("phones")
            if isinstance(phones_raw, list):
                record.phones = [str(p) for p in phones_raw if p]
            elif isinstance(phones_raw, str) and phones_raw:
                record.phones = [phones_raw]

            # Skills — list of strings or list of dicts
            skills_raw = mapped.get("skills_raw", [])
            if isinstance(skills_raw, list):
                for s in skills_raw:
                    if isinstance(s, str):
                        record.skills_raw.append(s)
                    elif isinstance(s, dict):
                        name = s.get("name") or s.get("skill") or s.get("title")
                        if name:
                            record.skills_raw.append(str(name))
            elif isinstance(skills_raw, str):
                record.skills_raw = [x.strip() for x in skills_raw.split(",") if x.strip()]

            # Experience
            exp_raw = mapped.get("experience", [])
            if isinstance(exp_raw, list):
                for e in exp_raw:
                    if isinstance(e, dict):
                        record.experience.append(ExperienceEntry(
                            company=e.get("company") or e.get("organization"),
                            title=e.get("title") or e.get("role") or e.get("position"),
                            start=e.get("start") or e.get("startDate"),
                            end=e.get("end") or e.get("endDate"),
                            summary=e.get("summary") or e.get("description"),
                        ))

            # Education
            edu_raw = mapped.get("education", [])
            if isinstance(edu_raw, list):
                for e in edu_raw:
                    if isinstance(e, dict):
                        record.education.append(EducationEntry(
                            institution=e.get("institution") or e.get("school") or e.get("university"),
                            degree=e.get("degree") or e.get("qualification"),
                            field=e.get("field") or e.get("major") or e.get("fieldOfStudy"),
                            end_year=e.get("end_year") or e.get("graduationYear") or e.get("year"),
                        ))

        except Exception as e:
            logger.error("ATS JSON extraction failed: %s", e)

        return record
